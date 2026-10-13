"""Possible campaigns: clusters of findings that share observable indicators.

Two findings are linked when they share at least one *strong* indicator (same phone number, email address,
messaging link, developer account or full URL) or at least two distinct weaker ones (same web domain, same handle
on different platforms). Linked findings are grouped transitively (union-find).

An indicator seen in more than `MAX_INDICATOR_SPREAD` findings is ignored: something that common (a popular
link hub, a big news site) connects unrelated accounts. A cluster is an observation to investigate — it is never
presented as proof of common ownership or coordination.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..detection import indicators as ind
from ..models import Brand, Finding

STRONG = {"phone", "email", "messaging", "publisher_id", "url"}
MAX_INDICATOR_SPREAD = 25
MAX_FINDINGS = 5000
RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def find_campaigns(db: Session, org_id: int, brand_id: int | None = None) -> dict:
    q = (select(Finding, Brand).join(Brand, Finding.brand_id == Brand.id).where(Brand.organization_id == org_id)
         .options(selectinload(Finding.candidate)).order_by(Finding.id.desc()).limit(MAX_FINDINGS))
    if brand_id:
        q = q.where(Finding.brand_id == brand_id)
    rows = db.execute(q).all()
    by_id = {f.id: (f, b) for f, b in rows}
    inds: dict[int, list[ind.Indicator]] = {f.id: ind.extract(f.candidate, b.official_domains) for f, b in rows}
    holders: dict[tuple[str, str], set[int]] = defaultdict(set)
    for fid, items in inds.items():
        for i in items:
            holders[(i.kind, i.value)].add(fid)
    ignored = {k for k, v in holders.items() if len(v) > MAX_INDICATOR_SPREAD}

    # Pairwise shared indicators (only through indicators held by 2+ findings).
    shared: dict[tuple[int, int], set[tuple[str, str]]] = defaultdict(set)
    for key, fids in holders.items():
        if len(fids) < 2 or key in ignored:
            continue
        ordered = sorted(fids)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                if key[0] == "handle" and by_id[a][0].candidate.source == by_id[b][0].candidate.source:
                    continue  # same handle on the same platform is the same account
                shared[(a, b)].add(key)

    parent = {fid: fid for fid in by_id}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for (a, b), keys in shared.items():
        if any(k[0] in STRONG for k in keys) or len(keys) >= 2:
            parent[root(a)] = root(b)

    groups: dict[int, list[int]] = defaultdict(list)
    for fid in by_id:
        groups[root(fid)].append(fid)

    campaigns = []
    for members in groups.values():
        if len(members) < 2:
            continue
        mset = set(members)
        common = [{"kind": k, "label": ind.KIND_LABELS[k], "value": next(i.display for i in inds[min(fids & mset)] if (i.kind, i.value) == (k, v)),
                   "findings": len(fids & mset), "strong": k in STRONG}
                  for (k, v), fids in holders.items() if (k, v) not in ignored and len(fids & mset) >= 2]
        common.sort(key=lambda c: (not c["strong"], -c["findings"], c["kind"]))
        items = []
        for fid in members:
            f, b = by_id[fid]
            c = f.candidate
            items.append({"finding_id": f.id, "name": c.name, "handle": c.handle, "kind": c.kind, "platform": (c.extra or {}).get("platform") or c.source,
                          "brand_name": b.name, "risk_level": f.risk_level, "risk_score": f.risk_score, "status": f.status,
                          "source_type": c.source_type, "first_observed_at": c.first_observed_at.isoformat(), "last_observed_at": c.last_observed_at.isoformat()})
        items.sort(key=lambda x: (RANK.get(x["risk_level"], 9), -x["risk_score"]))
        top = items[0]["risk_level"]
        campaigns.append({
            "id": f"c{min(members)}",
            "label": f"Possible campaign — {len(items)} findings share {len(common)} observable indicator{'s' if len(common) != 1 else ''}",
            "size": len(items), "max_risk": top, "platforms": sorted({x["platform"] for x in items}),
            "confirmed": sum(1 for x in items if x["status"] == "confirmed"), "open": sum(1 for x in items if x["status"] in ("open", "escalated")),
            "synthetic": all(x["source_type"] == "simulated" for x in items),
            "first_observed_at": min(x["first_observed_at"] for x in items), "last_observed_at": max(x["last_observed_at"] for x in items),
            "shared_indicators": common, "findings": items,
        })
    campaigns.sort(key=lambda c: (RANK.get(c["max_risk"], 9), -c["size"]))
    return {
        "campaigns": campaigns,
        "ignored_common_indicators": len(ignored),
        "note": ("Grouped only by values the findings demonstrably share (links, contacts, developer IDs, handles). A shared "
                 "value is an observation worth investigating — it does not by itself prove common ownership or coordination."),
    }
