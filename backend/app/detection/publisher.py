"""Publisher mismatch for app-store listings."""
from __future__ import annotations

from ..candidate import CandidateRecord
from .exclusion import OfficialAppRef, platform_for
from .similarity import _pair_score
from .signals import Signal


def publisher_signal(c: CandidateRecord, official_apps: list[OfficialAppRef], brand_names: list[str]) -> Signal:
    if c.kind != "app":
        return Signal.missing("publisher", "Not applicable to social accounts")
    store = platform_for(c)
    on_store = [a for a in official_apps if a.store == store]
    official_ids = {a.publisher_id for a in on_store if a.publisher_id}
    if not c.publisher_id and not c.publisher_name:
        return Signal.missing("publisher", "Listing has no publisher information")
    if c.publisher_id and c.publisher_id in official_ids:
        # Same verified developer account: mitigating, but still a distinct listing (not auto-excluded).
        return Signal(
            name="publisher",
            evaluated=True,
            score=0.0,
            detail=f"Published by the official developer account ({c.publisher_id})",
            data={"same_official_publisher": True},
        )
    name_sim = max((_pair_score(c.publisher_name or "", b)[0] for b in brand_names), default=0.0)
    if not c.publisher_id:
        official_names = {(a.publisher_name or "").strip().lower() for a in on_store if a.publisher_name}
        if (c.publisher_name or "").strip().lower() in official_names:
            # Display-name match is NOT trusted, but without an ID we also cannot call it a mismatch.
            return Signal.missing("publisher", f"Developer name matches “{c.publisher_name}” but the listing exposes no developer ID to verify")
    if not official_ids:
        if name_sim >= 0.8:
            return Signal(
                name="publisher",
                evaluated=True,
                score=0.5,
                detail=f"Developer “{c.publisher_name}” uses the brand name, but no official publisher ID is on file for {store} to verify it",
                evidence=["Add the official publisher ID to the brand profile to verify developer identity"],
            )
        return Signal.missing("publisher", f"No official publisher on file for {store}; cannot verify developer")
    if name_sim >= 0.8:
        return Signal(
            name="publisher",
            evaluated=True,
            score=0.9,
            detail=f"Developer “{c.publisher_name}” resembles the brand but its ID ({c.publisher_id}) is not an official publisher",
            evidence=["Publisher name mimics brand with an unofficial developer account"],
        )
    return Signal(
        name="publisher",
        evaluated=True,
        score=0.6,
        detail=f"Published by “{c.publisher_name}” — not an official publisher of this brand",
        evidence=["Publisher differs from every official developer account"],
    )
