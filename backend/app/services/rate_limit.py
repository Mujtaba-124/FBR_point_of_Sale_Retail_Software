"""Login rate limiting: fixed windows stored in Redis.

Two counters per window:
- attempts per client IP (every login request counts)
- failures per email (only wrong passwords count; cleared on success)

If Redis is unreachable, login fails closed (503) rather than allowing
unlimited password guessing.
"""

import hashlib
import logging

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)


def _email_key(email: str) -> str:
    # Hash so raw email addresses are never stored in Redis.
    return "rl:login:email:" + hashlib.sha256(email.encode()).hexdigest()


def _ip_key(ip: str) -> str:
    return f"rl:login:ip:{ip}"


def _unavailable() -> AppError:
    return AppError(
        503, "service_unavailable", "Sign-in is temporarily unavailable. Try again shortly."
    )


def _too_many(retry_after: int) -> AppError:
    return AppError(
        429,
        "rate_limited",
        "Too many sign-in attempts. Please wait and try again.",
        headers={"Retry-After": str(max(retry_after, 1))},
    )


class LoginRateLimiter:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.window = settings.login_rate_window_seconds
        self.max_email_failures = settings.login_max_failures_per_email
        self.max_ip_attempts = settings.login_max_attempts_per_ip

    def check_and_count_attempt(self, email: str, ip: str) -> None:
        """Count this attempt for the IP and reject if either limit is exhausted."""
        try:
            pipe = self.redis.pipeline()
            pipe.incr(_ip_key(ip))
            pipe.expire(_ip_key(ip), self.window, nx=True)
            pipe.get(_email_key(email))
            pipe.ttl(_ip_key(ip))
            pipe.ttl(_email_key(email))
            ip_count, _, email_failures, ip_ttl, email_ttl = pipe.execute()
        except RedisError:
            logger.exception("login rate limiter unavailable")
            raise _unavailable() from None

        if int(email_failures or 0) >= self.max_email_failures:
            raise _too_many(int(email_ttl))
        if int(ip_count) > self.max_ip_attempts:
            raise _too_many(int(ip_ttl))

    def record_failure(self, email: str) -> None:
        try:
            pipe = self.redis.pipeline()
            pipe.incr(_email_key(email))
            pipe.expire(_email_key(email), self.window, nx=True)
            pipe.execute()
        except RedisError:
            logger.exception("login rate limiter unavailable")

    def record_success(self, email: str) -> None:
        try:
            self.redis.delete(_email_key(email))
        except RedisError:
            logger.exception("login rate limiter unavailable")
