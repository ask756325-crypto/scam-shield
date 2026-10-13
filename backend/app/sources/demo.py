"""Synthetic demo source. Clearly labelled `simulated`; only available for demo brands."""
from __future__ import annotations

import copy

import httpx
from rapidfuzz import fuzz

from ..candidate import CandidateRecord
from ..demo.dataset import DEMO_RECORDS
from ..detection.normalize import skeleton
from .base import SourceAdapter, SourceInfo


class DemoAdapter(SourceAdapter):
    info = SourceInfo(
        name="demo",
        label="Synthetic demo data",
        category="demo",
        source_type="simulated",
        integration="Bundled synthetic dataset (no network access)",
        reliability="synthetic",
        notes="Fictional accounts and apps for the demo brand. Never used as a substitute for a failed live source.",
    )

    def __init__(self, config: dict | None = None, epoch: int = 0):
        super().__init__(config)
        self.epoch = max(0, min(epoch, 2))

    async def search(self, term: str, client: httpx.AsyncClient) -> list[CandidateRecord]:
        t = skeleton(term)
        out = []
        for raw in DEMO_RECORDS:
            if self.epoch not in raw["epochs"]:
                continue
            rec = copy.deepcopy(raw)
            for e, v in sorted(raw.get("variants", {}).items()):  # variants apply from their epoch onwards
                if e <= self.epoch:
                    rec.update(v)
            haystack = skeleton(" ".join([rec["name"], rec.get("handle") or "", rec.get("description") or ""]))
            if t and fuzz.partial_ratio(t, haystack) >= 75:
                out.append(self.to_record(rec, term))
        return out

    @staticmethod
    def to_record(rec: dict, term: str) -> CandidateRecord:
        source_name = {"bluesky": "bluesky", "mastodon": "mastodon", "apple": "apple_app_store", "google_play": "google_play"}[rec["platform"]]
        return CandidateRecord(
            source="demo",
            source_type="simulated",
            kind=rec["kind"],
            external_id=f"{source_name}:{rec['external_id']}",
            name=rec["name"],
            handle=rec.get("handle"),
            url=rec.get("url"),
            description=rec.get("description", ""),
            avatar_url=f"demo-asset://{rec['avatar']}" if rec.get("avatar") else None,
            publisher_name=rec.get("publisher_name"),
            publisher_id=rec.get("publisher_id"),
            external_links=rec.get("links", []),
            metadata={
                "platform": rec["platform"],
                "native_id": rec["external_id"],
                "simulated_source": source_name,
                "track_id": rec.get("track_id"),
                "synthetic": True,
            },
            provenance={"adapter": "demo", "endpoint": "bundled synthetic dataset", "query": term, "epoch": rec.get("epochs")},
        )
