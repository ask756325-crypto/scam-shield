"""Official asset registry: exact identifiers, exclusion rules, and a dry-run checker.

Exact identifiers (used to *exclude* official assets before scoring) are reported separately from the fuzzy
similarity references (names, keywords, logo hashes) that are only ever used to *score* candidates.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..candidate import CandidateRecord
from ..db import get_db
from ..deps import Principal, get_brand_for, get_principal, require_owner
from ..detection.exclusion import DEFAULT_RULES, EXCLUSION_RULES, RULE_IDS, OfficialIndex, canonical_handle, canonical_url, effective_rules
from ..models import Exclusion
from ..schemas import ExclusionRulesIn, RegistryCheckIn
from ..serializers import iso
from ..services.scanner import brand_context

router = APIRouter(prefix="/api/brands", tags=["registry"])

PLATFORM_SOURCE = {"bluesky": "bluesky", "mastodon": "mastodon", "apple": "apple_app_store", "google_play": "google_play"}


def _identifiers(brand) -> list[dict]:
    out: list[dict] = []
    for d in brand.official_domains or []:
        out.append({"type": "domain", "platform": None, "value": d, "rules": ["bluesky_verified_domain_handle", "mastodon_verified_link"],
                    "note": "Also treated as non-suspicious when it appears in candidate links."})
    for a in brand.official_accounts:
        ref = f"@{canonical_handle(a.handle)}"
        out.append({"type": "handle", "platform": a.platform, "value": ref, "rules": ["official_platform_handle"]})
        if a.profile_url:
            out.append({"type": "profile_url", "platform": a.platform, "value": canonical_url(a.profile_url), "rules": ["official_profile_url"]})
        if a.external_id:
            out.append({"type": "account_id", "platform": a.platform, "value": a.external_id, "rules": ["official_account_id"]})
        if a.platform not in PLATFORM_SOURCE:
            out[-1]["note"] = "Platform not scanned by a connected source; kept for reference."
    for a in brand.official_apps:
        label = f" ({a.name})" if a.name else ""
        out.append({"type": "app_id", "platform": a.store, "value": a.app_id, "rules": ["official_app_id"], "note": f"Listing{label}".strip() if a.name else None})
        if a.track_id:
            out.append({"type": "track_id", "platform": a.store, "value": a.track_id, "rules": ["official_track_id"]})
        if a.publisher_id:
            out.append({"type": "publisher_id", "platform": a.store, "value": a.publisher_id, "rules": ["official_publisher_id"],
                        "note": "Without the opt-in rule this caps other apps from this publisher at Low instead of excluding them."})
    return out


def _rules_view(brand) -> list[dict]:
    rules = effective_rules(brand.exclusion_rules)
    return [{**r, "enabled": rules[r["id"]]} for r in EXCLUSION_RULES]


@router.get("/{brand_id}/registry")
def registry(brand_id: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    b = get_brand_for(db, p, brand_id)
    stats = {
        rule: {"count": n, "last_at": iso(last)}
        for rule, n, last in db.execute(
            select(Exclusion.rule, func.count(), func.max(Exclusion.created_at)).where(Exclusion.brand_id == b.id).group_by(Exclusion.rule)
        ).all()
    }
    return {
        "brand_id": b.id,
        "can_edit_rules": p.role == "owner",
        "rules": [{**r, "stats": stats.get(r["id"], {"count": 0, "last_at": None})} for r in _rules_view(b)],
        "exact_identifiers": _identifiers(b),
        "similarity_reference": {
            "names": [b.name, *(b.aliases or [])],
            "keywords": b.keywords or [],
            "additional_identifiers": b.additional_identifiers or [],
            "has_description": bool((b.description or "").strip()),
            "logo": {"phash": b.logo_phash, "dhash": b.logo_dhash} if b.logo_phash else None,
            "note": "Used only to score candidates. Never used to exclude anything.",
        },
    }


@router.put("/{brand_id}/exclusion-rules")
def update_rules(brand_id: int, body: ExclusionRulesIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    b = get_brand_for(db, p, brand_id)
    unknown = sorted(set(body.rules) - set(RULE_IDS))
    if unknown:
        raise HTTPException(422, f"Unknown exclusion rule(s): {', '.join(unknown)}")
    merged = {**effective_rules(b.exclusion_rules), **body.rules}
    # Persist only deviations from defaults so future default changes still apply to untouched rules.
    b.exclusion_rules = {k: v for k, v in merged.items() if v != DEFAULT_RULES[k]}
    db.commit()
    return {"rules": _rules_view(b)}


@router.post("/{brand_id}/registry/check")
def check(brand_id: int, body: RegistryCheckIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Dry run: would a candidate with these identifiers be excluded, and by which rule?"""
    b = get_brand_for(db, p, brand_id)
    is_app = body.platform in ("apple", "google_play")
    native = (body.app_id if is_app else body.account_id or body.handle or body.profile_url or "") or ""
    if not native and not body.track_id and not body.publisher_id:
        raise HTTPException(422, "Provide at least one identifier to check")
    rec = CandidateRecord(
        source=PLATFORM_SOURCE[body.platform], source_type="live", kind="app" if is_app else "account",
        external_id=native or "-", name="(dry run)", handle=body.handle, url=body.profile_url,
        publisher_id=body.publisher_id,
        metadata={"platform": body.platform, "native_id": native or None, "track_id": body.track_id,
                  "verified_links": [body.verified_link] if body.verified_link else []},
    )
    ctx = brand_context(b)
    match = OfficialIndex(ctx.official_accounts, ctx.official_apps, ctx.official_domains, ctx.exclusion_rules).match(rec)
    if match:
        return {"excluded": True, "rule": match.rule, "matched_value": match.matched_value,
                "explanation": "This would be set aside as an official asset before scoring."}
    # Would a currently disabled rule have matched? Tell the user instead of leaving them guessing.
    all_on = OfficialIndex(ctx.official_accounts, ctx.official_apps, ctx.official_domains, {k: True for k in RULE_IDS}).match(rec)
    return {
        "excluded": False,
        "rule": None,
        "disabled_rule_would_match": all_on.rule if all_on else None,
        "explanation": (f"Not excluded. It would match “{all_on.rule}”, which is disabled for this brand." if all_on
                        else "Not excluded. It would be scored like any other candidate."),
    }
