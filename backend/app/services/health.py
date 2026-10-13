"""Source health for the dashboard and sidebar — a view of the source registry status (real evidence only)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Organization
from .source_status import registry_status


def source_health(db: Session, org: Organization, brand_ids: list[int], include_demo: bool = False) -> list[dict]:
    return registry_status(db, org, brand_ids, include_demo=include_demo)
