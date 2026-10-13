"""Application configuration, loaded from environment variables / backend/.env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_prefix="SCAMSHIELD_", extra="ignore")

    # "development" enables local conveniences (reset links in server log, non-secure cookies on http).
    env: str = "development"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'scamshield.db').as_posix()}"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"

    # Sessions
    session_cookie_name: str = "ss_session"
    session_ttl_hours: int = 24 * 30  # "Remember me": persistent cookie
    short_session_ttl_hours: int = 12  # default: browser-session cookie, short server-side expiry
    email_verification_ttl_hours: int = 48
    cookie_secure: bool | None = None  # defaults to True outside development

    # Public origin of the frontend, used to build password-reset links.
    frontend_origin: str = "http://localhost:3000"

    # Outbound HTTP
    http_timeout_seconds: float = 12.0
    source_timeout_seconds: float = 90.0
    # Delay before the single retry of a query that timed out or hit a 5xx/network error.
    source_retry_delay_seconds: float = 1.5
    user_agent: str = "ScamShieldAI/1.0 (+brand-protection research; contact: admin@localhost)"

    # Uploads
    max_logo_bytes: int = 2 * 1024 * 1024
    max_remote_image_bytes: int = 2 * 1024 * 1024
    max_import_bytes: int = 2 * 1024 * 1024

    # Scheduler
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = 60
    scheduler_max_concurrent_scans: int = 2
    # Which process this is: "api" (default) or "worker" (python -m app.worker). Scans record the role that runs them.
    process_role: str = "api"
    # A finding is resolved after this many consecutive clean scans of its source that did not observe it.
    resolve_after_misses: int = 2

    # Optional per-instance Mastodon access tokens, e.g. "mastodon.social=TOKEN,fosstodon.org=TOKEN2".
    # Server-side only: never returned by the API, never logged. With a token, requests count against that
    # account's limits instead of the anonymous per-IP limit. Use a token with the read:search scope only.
    mastodon_access_tokens: SecretStr | None = None
    # Hosts verified as Mastodon servers are cached for this long when saving source settings.
    instance_validation_cache_seconds: int = 6 * 3600

    def mastodon_tokens(self) -> dict[str, str]:
        raw = self.mastodon_access_tokens.get_secret_value() if self.mastodon_access_tokens else ""
        out: dict[str, str] = {}
        for part in raw.split(","):
            host, sep, token = part.strip().partition("=")
            if sep and host.strip() and token.strip():
                out[host.strip().lower()] = token.strip()
        return out

    # Auth rate limits (attempts per window per IP+identifier)
    auth_rate_limit_attempts: int = 10
    auth_rate_limit_window_seconds: int = 300

    # Optional SMTP for password reset delivery
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    @property
    def is_dev(self) -> bool:
        return self.env.lower() in {"development", "dev", "test"}

    @property
    def secure_cookies(self) -> bool:
        return (not self.is_dev) if self.cookie_secure is None else self.cookie_secure


@lru_cache
def get_settings() -> Settings:
    return Settings()
