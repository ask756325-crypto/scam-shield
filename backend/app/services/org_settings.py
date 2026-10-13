"""Per-organization operational settings (monitoring limits, resolution rule, data retention) with validation."""
from __future__ import annotations

from ..config import get_settings
from ..models import Organization

# name: (minimum, maximum, description)
LIMITS: dict[str, tuple[int, int, str]] = {
    "resolve_after_misses": (1, 5, "Consecutive clean scans that must miss a finding before it is resolved"),
    "max_queries_per_source": (1, 8, "Look-alike search queries sent to each source per scan"),
    "source_time_budget_seconds": (30, 180, "Maximum time one source may spend per scan"),
    "max_image_fetches": (0, 80, "Candidate avatars/icons downloaded per scan for logo comparison (0 disables logo matching)"),
}
RETENTION_CHOICES = (None, 30, 90, 180, 365)


def defaults() -> dict:
    s = get_settings()
    return {
        "resolve_after_misses": s.resolve_after_misses,
        "max_queries_per_source": 8,
        "source_time_budget_seconds": int(s.source_timeout_seconds),
        "max_image_fetches": 80,
        "scan_history_days": None,  # keep forever
    }


def monitoring_settings(org: Organization | None) -> dict:
    out = defaults()
    raw = (org.monitoring_config if org else None) or {}
    for k, (lo, hi, _) in LIMITS.items():
        v = raw.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi:
            out[k] = v
    if raw.get("scan_history_days") in RETENTION_CHOICES:
        out["scan_history_days"] = raw.get("scan_history_days")
    return out


def validate(values: dict) -> tuple[dict, dict[str, str]]:
    """Return (clean values, field errors). Unknown keys are rejected."""
    clean: dict = {}
    errors: dict[str, str] = {}
    for k, v in values.items():
        if k in LIMITS:
            lo, hi, _ = LIMITS[k]
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                errors[k] = f"Must be a whole number from {lo} to {hi}"
            else:
                clean[k] = v
        elif k == "scan_history_days":
            if v not in RETENTION_CHOICES:
                errors[k] = "Choose keep forever, 30, 90, 180 or 365 days"
            else:
                clean[k] = v
        else:
            errors[k] = "Unknown setting"
    return clean, errors
