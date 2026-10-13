"""Normalized candidate schema shared by every source adapter and the detection engine."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class CandidateRecord:
    source: str  # bluesky | mastodon | apple_app_store | google_play | demo_* | import
    source_type: str  # live | simulated | imported
    kind: str  # account | app
    external_id: str  # stable id at the source (DID, account URL, bundle id, package name)
    name: str
    handle: str | None = None
    url: str | None = None
    description: str = ""
    avatar_url: str | None = None
    publisher_name: str | None = None
    publisher_id: str | None = None
    external_links: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    source_created_at: str | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    provenance: dict = field(default_factory=dict)  # adapter, endpoint, query
    # Optional pre-computed image hashes (used by simulated/imported data that ships hashes, and tests).
    image_hashes: dict | None = None

    def content_hash(self) -> str:
        """Hash of the fields that define 'changed' between observations."""
        payload = {
            "name": self.name,
            "handle": self.handle,
            "description": self.description,
            "avatar_url": self.avatar_url,
            "publisher_id": self.publisher_id,
            "publisher_name": self.publisher_name,
            "external_links": sorted(self.external_links),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["observed_at"] = self.observed_at.isoformat()
        return d
