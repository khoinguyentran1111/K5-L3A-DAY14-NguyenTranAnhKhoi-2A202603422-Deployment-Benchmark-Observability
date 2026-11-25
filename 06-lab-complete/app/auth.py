"""
API Key authentication (tiêu chí 6).

  • Client gửi header  X-API-Key: <key>
  • Key phải trùng biến môi trường AGENT_API_KEY
  • Thiếu hoặc sai key → HTTP 401 (auto_error=False để FastAPI không tự trả 403/422)
  • So sánh bằng hmac.compare_digest để tránh timing attack
  • AGENT_API_KEY chưa cấu hình → từ chối tất cả (fail closed)
"""
import hmac

from fastapi import HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho FastAPI — dùng trong /ask: Depends(verify_api_key)."""
    expected = settings.agent_api_key
    if not api_key or not expected or not hmac.compare_digest(api_key.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key (header X-API-Key)",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
