"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429 kèm header Retry-After
  • State lưu trong Redis (sorted set, score = thời điểm ms) → mọi worker / instance
    dùng chung và vẫn còn sau khi restart agent
  • Toàn bộ "xoá cũ → đếm → thêm" chạy trong một Lua script nên atomic,
    không có race condition giữa 2 worker cùng đếm một lúc
  • Key Redis dùng hash của API key, không lưu API key thô
"""
import hashlib
import math
import time
import uuid

from fastapi import HTTPException, status

from app.config import settings
from app.redis_client import r

WINDOW_MS = 60_000

# KEYS[1] = key; ARGV = now_ms, window_ms, limit, member
_SLIDING_WINDOW_LUA = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  return {0, count, tonumber(oldest[2]) or now}
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('PEXPIRE', key, window)
return {1, count + 1, 0}
"""
_sliding_window = r.register_script(_SLIDING_WINDOW_LUA)


def _bucket_key(key: str) -> str:
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"ratelimit:{digest}"


def check_rate_limit(key: str) -> int:
    """Raise 429 nếu vượt giới hạn; trả về số request còn lại trong cửa sổ hiện tại."""
    limit = settings.rate_limit_per_minute
    now_ms = int(time.time() * 1000)
    allowed, count, oldest_ms = _sliding_window(
        keys=[_bucket_key(key)],
        args=[now_ms, WINDOW_MS, limit, f"{now_ms}-{uuid.uuid4().hex}"],
    )
    if not allowed:
        retry_after = max(1, math.ceil((int(oldest_ms) + WINDOW_MS - now_ms) / 1000))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {limit} requests per minute",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )
    return max(0, limit - int(count))
