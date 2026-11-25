"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

  • Đọc REDIS_URL từ config
  • redis.from_url() KHÔNG mở kết nối ngay → app khởi động được khi Redis chưa sẵn sàng
  • Timeout ngắn để /ready và /ask không treo khi Redis chết
  • redis_healthy() dùng cho GET /ready: Redis không kết nối được → False
"""
import redis

from app.config import settings

r: redis.Redis = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
    health_check_interval=30,
)


def redis_healthy() -> bool:
    try:
        return bool(r.ping())
    except (redis.RedisError, OSError):
        return False


def close() -> None:
    try:
        r.close()
    except Exception:  # đang tắt app, không cần báo lỗi
        pass
