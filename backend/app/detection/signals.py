"""Common result type for detection signals."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Signal:
    """A single heuristic signal. `score` is in [0, 1] and only meaningful when `evaluated` is True."""

    name: str
    evaluated: bool
    score: float = 0.0
    detail: str = ""
    evidence: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    @classmethod
    def missing(cls, name: str, reason: str) -> "Signal":
        return cls(name=name, evaluated=False, score=0.0, detail=reason)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["score"] = round(float(self.score), 4)
        return d
