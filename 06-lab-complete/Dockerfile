# ============================================================
# Production Dockerfile — multi-stage
#   Stage 1 (builder): cài dependencies vào virtualenv /opt/venv
#   Stage 2 (runtime): chỉ copy venv + source, user non-root, HEALTHCHECK
#   uvicorn là PID 1 (exec) → nhận SIGTERM trực tiếp khi `docker stop`
# ============================================================

# ---------- Stage 1: builder ----------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
# requirements trước source → layer dependencies được cache khi chỉ sửa code
COPY requirements.txt .
RUN pip install -r requirements.txt


# ---------- Stage 2: runtime ----------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000 \
    WEB_CONCURRENCY=2

RUN groupadd --system --gid 10001 agent \
 && useradd --system --uid 10001 --gid agent --no-create-home --shell /usr/sbin/nologin agent

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=agent:agent app/ ./app/
COPY --chown=agent:agent utils/ ./utils/

USER agent

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=3)" || exit 1

# Lắng nghe theo biến PORT do platform cấp (Railway/Render), mặc định 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout-graceful-shutdown 8"]
