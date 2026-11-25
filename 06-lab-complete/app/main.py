"""
Production AI Agent — Part 6 Final Project

Chạy:  uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
Kiểm tra:  python check_production_ready.py

Thành phần:
  • GET  /health  — liveness, luôn 200 khi process còn sống (không phụ thuộc Redis)
  • GET  /ready   — readiness, 503 khi Redis không kết nối được hoặc đang tắt
  • POST /ask     — X-API-Key → rate limit (Redis) → cost guard (Redis) → LLM → ghi cost
  • Log: mỗi dòng là 1 JSON object (kể cả log của uvicorn trong worker)
  • Graceful shutdown: uvicorn nhận SIGTERM → ngừng nhận kết nối mới → chờ request
    đang chạy xong → lifespan shutdown (log + đóng Redis) → exit 0
"""
import asyncio
import json
import logging
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import redis_client
from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from utils.mock_llm import ask as llm_ask


# ─────────────────────────────────────────────────────────
# Structured logging (tiêu chí 10)
# ─────────────────────────────────────────────────────────
_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message", "asctime", "color_message"}


class JsonFormatter(logging.Formatter):
    """Mỗi record → đúng 1 dòng JSON. Field thêm truyền qua `extra={...}`."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level)
    # uvicorn đã tự cấu hình logger của nó trước khi import app → đổi sang JSON luôn
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = [handler] if name != "uvicorn.error" else []
        lg.propagate = name == "uvicorn.error"
    return logging.getLogger("agent")


logger = _setup_logging()


# ─────────────────────────────────────────────────────────
# Lifespan + graceful shutdown (tiêu chí 11)
# ─────────────────────────────────────────────────────────
class _State:
    started_at = time.time()
    shutting_down = False
    in_flight = 0
    lock = threading.Lock()


state = _State()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("startup", extra={
        "environment": settings.environment, "version": settings.app_version,
        "redis_ok": redis_client.redis_healthy(),
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "daily_budget_usd": settings.daily_budget_usd,
        "api_key_configured": bool(settings.agent_api_key),
    })
    yield
    # Tới đây uvicorn đã nhận SIGTERM, ngừng nhận kết nối mới và chờ request đang chạy xong.
    state.shutting_down = True
    deadline = time.time() + 10
    while state.in_flight > 0 and time.time() < deadline:
        await asyncio.sleep(0.05)
    logger.info("shutdown", extra={"in_flight": state.in_flight,
                                   "uptime_s": round(time.time() - state.started_at, 1)})
    redis_client.close()


app = FastAPI(
    title="Production AI Agent",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    request.state.request_id = request_id
    with state.lock:
        state.in_flight += 1
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        with state.lock:
            state.in_flight -= 1
        logger.info("request", extra={
            "request_id": request_id, "method": request.method, "path": request.url.path,
            "status": status_code, "ms": round((time.perf_counter() - start) * 1000, 1),
        })


# ─────────────────────────────────────────────────────────
# Error handling — mã lỗi rõ ràng, không lộ stack trace
# ─────────────────────────────────────────────────────────
def _error(request: Request, status_code: int, error: str, message, headers=None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "detail": message,
                 "request_id": getattr(request.state, "request_id", None)},
        headers=headers,
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    names = {401: "unauthorized", 402: "budget_exceeded", 404: "not_found",
             405: "method_not_allowed", 429: "rate_limited", 503: "service_unavailable"}
    return _error(request, exc.status_code, names.get(exc.status_code, "http_error"),
                  exc.detail, getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    problems = []
    for e in exc.errors():
        field = ".".join(str(p) for p in e.get("loc", ()) if p != "body" and not isinstance(p, int))
        problems.append({"field": field or "body", "message": e.get("msg")})
    return _error(request, 422, "invalid_request", problems)


@app.exception_handler(redis.RedisError)
async def redis_error(request: Request, exc: redis.RedisError):
    logger.error("redis_unavailable", extra={"request_id": getattr(request.state, "request_id", None),
                                             "error": type(exc).__name__})
    return _error(request, 503, "service_unavailable",
                  "State store unavailable, please retry later", {"Retry-After": "5"})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception("unhandled_error", extra={"request_id": getattr(request.state, "request_id", None)})
    return _error(request, 500, "internal_error", "Internal server error")


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=64)

    @field_validator("question")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank")
        return v.strip()


@app.get("/")
def root():
    return {"service": "production-ai-agent", "version": settings.app_version,
            "endpoints": ["GET /health", "GET /ready", "POST /ask"]}


@app.get("/health")
def health():
    """Liveness: process còn sống là 200 — không kiểm tra Redis."""
    return {"status": "ok", "version": settings.app_version, "environment": settings.environment,
            "uptime_s": round(time.time() - state.started_at, 1)}


@app.get("/ready")
def ready():
    """Readiness: chỉ nhận traffic khi Redis kết nối được và chưa bắt đầu tắt."""
    if state.shutting_down:
        return JSONResponse(status_code=503, content={"status": "shutting_down"})
    if not redis_client.redis_healthy():
        return JSONResponse(status_code=503, content={"status": "not_ready", "redis": "unreachable"})
    return {"status": "ready", "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, request: Request, api_key: str = Depends(verify_api_key)):
    remaining = check_rate_limit(api_key)          # 429
    check_budget()                                 # 402

    started = time.perf_counter()
    answer = llm_ask(body.question)
    llm_ms = round((time.perf_counter() - started) * 1000, 1)

    input_tokens, output_tokens = estimate_tokens(body.question), estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)
    logger.info("llm_call", extra={
        "request_id": request.state.request_id, "user_id": body.user_id, "llm_ms": llm_ms,
        "input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": round(cost, 8),
    })
    return JSONResponse(
        content={
            "question": body.question,
            "answer": answer,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cost_usd": round(cost, 8)},
            "request_id": request.state.request_id,
        },
        headers={"X-RateLimit-Limit": str(settings.rate_limit_per_minute),
                 "X-RateLimit-Remaining": str(remaining)},
    )
