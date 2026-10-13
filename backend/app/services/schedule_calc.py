"""Time-zone-aware next-run calculation for monitoring schedules (pure functions, no I/O).

* `interval`: every N hours, anchored on the previous planned run (no drift). Missed runs — e.g. while the
  scheduler was down — are skipped, never replayed in a burst.
* `daily` / `weekly`: at HH:MM *local time* in the schedule's IANA time zone, so a 09:00 scan stays at 09:00
  across daylight-saving changes. A local time that does not exist (spring-forward gap) runs at the
  equivalent instant just after the gap (e.g. 02:30 → 03:30); an ambiguous time (fall-back) runs once,
  at its first occurrence.
All returned datetimes are timezone-aware UTC.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

FREQUENCIES = ("interval", "daily", "weekly")
MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = 24 * 30
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass
class ScheduleSpec:
    frequency: str = "daily"
    interval_hours: int = 24
    time_of_day: str = "09:00"
    weekdays: list[int] = field(default_factory=list)
    timezone: str = "UTC"


class ScheduleError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def validate(spec: ScheduleSpec) -> ScheduleSpec:
    if spec.frequency not in FREQUENCIES:
        raise ScheduleError("frequency", f"Frequency must be one of: {', '.join(FREQUENCIES)}")
    try:
        if spec.timezone not in available_timezones():
            raise ZoneInfoNotFoundError(spec.timezone)
        ZoneInfo(spec.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ScheduleError("timezone", f"Unknown time zone “{spec.timezone}”. Use an IANA name such as Europe/London.") from None
    if spec.frequency == "interval":
        if not (MIN_INTERVAL_HOURS <= int(spec.interval_hours) <= MAX_INTERVAL_HOURS):
            raise ScheduleError("interval_hours", f"Interval must be between {MIN_INTERVAL_HOURS} and {MAX_INTERVAL_HOURS} hours")
    else:
        if not _TIME_RE.match(spec.time_of_day or ""):
            raise ScheduleError("time_of_day", "Time must be HH:MM in 24-hour format")
    if spec.frequency == "weekly":
        days = sorted(set(spec.weekdays or []))
        if not days or any(not isinstance(d, int) or d < 0 or d > 6 for d in days):
            raise ScheduleError("weekdays", "Choose at least one weekday")
        spec.weekdays = days
    return spec


def _local_to_utc(d: date, t: time, tz: ZoneInfo) -> datetime:
    # fold=0: ambiguous times resolve to the first occurrence; gap times map to the instant after the gap.
    return datetime.combine(d, t, tzinfo=tz).astimezone(timezone.utc)


def next_run(spec: ScheduleSpec, now: datetime, previous_planned: datetime | None = None) -> datetime:
    """The first run strictly after `now`."""
    now = now.astimezone(timezone.utc)
    if spec.frequency == "interval":
        step = timedelta(hours=int(spec.interval_hours))
        if previous_planned is None:
            return now + step
        nxt = previous_planned.astimezone(timezone.utc) + step
        if nxt <= now:  # skip missed slots instead of replaying them
            missed = (now - nxt) // step + 1
            nxt += step * missed
        return nxt
    tz = ZoneInfo(spec.timezone)
    hh, mm = (int(x) for x in spec.time_of_day.split(":"))
    t = time(hh, mm)
    start = now.astimezone(tz).date()
    for k in range(0, 9):
        d = start + timedelta(days=k)
        if spec.frequency == "weekly" and d.weekday() not in spec.weekdays:
            continue
        cand = _local_to_utc(d, t, tz)
        if cand > now:
            return cand
    raise AssertionError("no run found within 8 days")  # unreachable for validated specs


def upcoming(spec: ScheduleSpec, now: datetime, n: int = 3, previous_planned: datetime | None = None) -> list[datetime]:
    out: list[datetime] = []
    cursor, prev = now, previous_planned
    for _ in range(n):
        nxt = next_run(spec, cursor, prev)
        out.append(nxt)
        cursor, prev = nxt, nxt
    return out
