"""Analyst-supplied CSV import. Records are labelled `imported` and scored by the same engine."""
from __future__ import annotations

import csv
import io

import httpx

from ..candidate import CandidateRecord
from .base import SourceAdapter, SourceInfo

PLATFORM_TO_SOURCE = {"bluesky": "bluesky", "mastodon": "mastodon", "apple": "apple_app_store", "google_play": "google_play"}
REQUIRED = {"platform", "kind", "external_id", "name"}
MAX_ROWS = 2000


class ImportError_(ValueError):
    pass


def parse_csv(data: bytes) -> list[CandidateRecord]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportError_("File must be UTF-8 encoded CSV") from exc
    reader = csv.DictReader(io.StringIO(text))
    cols = {c.strip().lower() for c in (reader.fieldnames or [])}
    missing = REQUIRED - cols
    if missing:
        raise ImportError_(f"Missing required column(s): {', '.join(sorted(missing))}")
    out: list[CandidateRecord] = []
    for i, raw in enumerate(reader, start=2):
        if i - 1 > MAX_ROWS:
            raise ImportError_(f"At most {MAX_ROWS} rows per import")
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        platform = row["platform"].lower()
        kind = row["kind"].lower()
        if kind not in ("account", "app"):
            raise ImportError_(f"Row {i}: kind must be 'account' or 'app'")
        if not row["external_id"] or not row["name"]:
            raise ImportError_(f"Row {i}: external_id and name are required")
        url = row.get("url") or None
        if url and not url.lower().startswith(("http://", "https://")):
            raise ImportError_(f"Row {i}: url must start with http(s)://")
        out.append(
            CandidateRecord(
                source="import",
                source_type="imported",
                kind=kind,
                external_id=f"{platform}:{row['external_id']}"[:255],
                name=row["name"][:500],
                handle=row.get("handle") or None,
                url=url,
                description=row.get("description", "")[:10000],
                avatar_url=row.get("avatar_url") or None,
                publisher_name=row.get("publisher_name") or None,
                publisher_id=row.get("publisher_id") or None,
                external_links=[u for u in (row.get("links") or "").split() if u.lower().startswith(("http://", "https://"))][:20],
                metadata={"platform": platform, "native_id": row["external_id"], "track_id": row.get("track_id") or None},
                provenance={"adapter": "import", "endpoint": "CSV upload", "query": f"row {i}"},
            )
        )
    if not out:
        raise ImportError_("The file contains no rows")
    return out


class ImportAdapter(SourceAdapter):
    info = SourceInfo(
        name="import",
        label="CSV import",
        category="import",
        source_type="imported",
        integration="Analyst-uploaded CSV",
        reliability="analyst supplied",
        notes="Columns: platform, kind, external_id, name, handle, url, description, publisher_name, publisher_id, track_id, links, avatar_url",
    )

    def __init__(self, records: list[CandidateRecord]):
        super().__init__({})
        self.records = records

    async def search(self, term: str, client: httpx.AsyncClient) -> list[CandidateRecord]:
        return list(self.records)
