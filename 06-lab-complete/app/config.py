"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

Biến môi trường (liệt kê đủ trong .env.example):
    PORT, ENVIRONMENT, AGENT_API_KEY, REDIS_URL,
    RATE_LIMIT_PER_MINUTE, DAILY_BUDGET_USD, MONTHLY_BUDGET_USD,
    LOG_LEVEL, APP_VERSION

Không có secret nào được hard-code: AGENT_API_KEY mặc định rỗng, khi rỗng
mọi request tới /ask đều bị từ chối (401) — fail closed thay vì mở toang.
"""
import os
from dataclasses import dataclass, field


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        raise ValueError(f"{name} phải là số nguyên, nhận được {raw!r}") from None


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        return float(raw) if raw not in (None, "") else default
    except ValueError:
        raise ValueError(f"{name} phải là số thực, nhận được {raw!r}") from None


@dataclass(frozen=True)
class Settings:
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    environment: str = field(default_factory=lambda: _env_str("ENVIRONMENT", "development"))
    app_version: str = field(default_factory=lambda: _env_str("APP_VERSION", "1.0.0"))
    log_level: str = field(default_factory=lambda: _env_str("LOG_LEVEL", "INFO").upper())

    # Secret — chỉ đọc từ env, không có giá trị mặc định
    agent_api_key: str = field(default_factory=lambda: _env_str("AGENT_API_KEY", ""))

    # State dùng chung (rate limit, cost) nằm trong Redis
    redis_url: str = field(default_factory=lambda: _env_str("REDIS_URL", "redis://localhost:6379/0"))

    # Bảo vệ tốc độ & tiền
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 10))
    daily_budget_usd: float = field(default_factory=lambda: _env_float("DAILY_BUDGET_USD", 1.0))
    monthly_budget_usd: float = field(default_factory=lambda: _env_float("MONTHLY_BUDGET_USD", 10.0))

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


settings = Settings()
