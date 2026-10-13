"""Request IDs, structured access logging and in-process request metrics (Prometheus text format)."""
from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
import uuid
from collections import defaultdict

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
access_log = logging.getLogger("scamshield.access")


def new_request_id(incoming: str | None) -> str:
    """Honour a well-formed upstream X-Request-ID (e.g. from a load balancer); otherwise mint one."""
    return incoming if incoming and _SAFE_ID.match(incoming) else uuid.uuid4().hex


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def install_logging() -> None:
    f = RequestIdFilter()
    for h in logging.getLogger().handlers:
        if not any(isinstance(x, RequestIdFilter) for x in h.filters):
            h.addFilter(f)
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s"))


class Metrics:
    """Per-process counters. With several replicas, scrape each one (or aggregate in Prometheus)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.requests: dict[tuple[str, str, str], int] = defaultdict(int)  # (method, route, status class)
        self.latency: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * (len(BUCKETS) + 1))
        self.latency_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.errors = 0
        self.started = time.time()

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        with self._lock:
            self.requests[(method, route, f"{status // 100}xx")] += 1
            buckets = self.latency[(method, route)]
            for i, b in enumerate(BUCKETS):
                if seconds <= b:
                    buckets[i] += 1
            buckets[-1] += 1  # +Inf
            self.latency_sum[(method, route)] += seconds
            if status >= 500:
                self.errors += 1

    def render(self) -> list[str]:
        out = ["# HELP scamshield_http_requests_total HTTP requests by method, route template and status class",
               "# TYPE scamshield_http_requests_total counter"]
        with self._lock:
            for (m, r, s), n in sorted(self.requests.items()):
                out.append(f'scamshield_http_requests_total{{method="{m}",route="{r}",status="{s}"}} {n}')
            out += ["# HELP scamshield_http_request_duration_seconds Request latency", "# TYPE scamshield_http_request_duration_seconds histogram"]
            for (m, r), buckets in sorted(self.latency.items()):
                labels = f'method="{m}",route="{r}"'
                for b, n in zip(BUCKETS, buckets):
                    out.append(f'scamshield_http_request_duration_seconds_bucket{{{labels},le="{b}"}} {n}')
                out.append(f'scamshield_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {buckets[-1]}')
                out.append(f"scamshield_http_request_duration_seconds_sum{{{labels}}} {self.latency_sum[(m, r)]:.6f}")
                out.append(f"scamshield_http_request_duration_seconds_count{{{labels}}} {buckets[-1]}")
            out += ["# TYPE scamshield_http_server_errors_total counter", f"scamshield_http_server_errors_total {self.errors}",
                    "# TYPE scamshield_process_uptime_seconds gauge", f"scamshield_process_uptime_seconds {time.time() - self.started:.0f}"]
        return out


metrics = Metrics()
