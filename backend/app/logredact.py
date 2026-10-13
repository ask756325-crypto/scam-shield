"""Defence in depth: redact configured secrets from every log record, whichever library emits it."""
from __future__ import annotations

import logging


class SecretRedactor(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        from .config import get_settings

        s = get_settings()
        secrets = [v for v in (*s.mastodon_tokens().values(), s.youtube_key()) if v and len(v) >= 6]
        if s.smtp_password:
            secrets.append(s.smtp_password)
        if not secrets:
            return True
        msg = record.getMessage()
        if any(x in msg for x in secrets):
            for x in secrets:
                msg = msg.replace(x, "[redacted]")
            record.msg, record.args = msg, ()
        return True


def install() -> None:
    """Attach the filter to every existing handler (and the root logger's future records)."""
    f = SecretRedactor()
    root = logging.getLogger()
    for h in root.handlers:
        if not any(isinstance(x, SecretRedactor) for x in h.filters):
            h.addFilter(f)
    for name in ("httpx", "httpcore", "uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        if not any(isinstance(x, SecretRedactor) for x in lg.filters):
            lg.addFilter(f)
