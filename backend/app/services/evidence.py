"""Investigation evidence: observed facts vs heuristic inferences, comparison assets, shared indicators, reports.

Everything here is derived from stored records — the candidate snapshot from its latest observation, the stored
assessment, the observation history and the brand profile. Nothing is fetched or synthesized at review time.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..detection import indicators as ind
from ..detection.scoring import DEFAULT_CONFIG
from ..models import Brand, Candidate, Finding, Observation, Scan

SIGNAL_LABELS = {
    "name": "Display name", "handle": "Handle", "package": "Bundle / package ID", "logo": "Logo / icon",
    "description": "Description text", "urls": "Links", "scam": "Scam indicators", "publisher": "Publisher",
}
STATUS_LABELS = {"open": "Needs review", "escalated": "Further review", "confirmed": "Confirmed impersonation",
                 "safe": "Marked legitimate", "resolved": "No longer observed"}
ACTION_LABELS = {"confirm": "Confirmed impersonation", "mark_safe": "Marked legitimate", "escalate": "Marked for further review",
                 "reopen": "Reopened", "note": "Note"}
SOURCE_TYPE_NOTES = {
    "live": "Collected from the public source.",
    "simulated": "SYNTHETIC record from the bundled demo dataset — not a real account or listing.",
    "imported": "Imported by an analyst from a CSV file; not independently collected.",
}
STORE_FOR_SOURCE = {"apple_app_store": "apple", "google_play": "google_play"}


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


def observed_facts(c: Candidate) -> list[dict]:
    """Verbatim fields from the stored candidate, each tagged with the field it came from."""
    m = c.extra or {}
    facts: list[tuple[str, object, str]] = [
        ("Name", c.name, "name"),
        ("Handle", f"@{c.handle}" if c.handle else None, "handle"),
        ("Platform", m.get("platform") or c.source, "metadata.platform"),
        ("Source URL", c.url, "url"),
        ("Source ID", c.external_id, "external_id"),
        ("Developer / publisher", c.publisher_name, "publisher_name"),
        ("Developer ID", c.publisher_id, "publisher_id"),
        ("Apple track ID", m.get("track_id"), "metadata.track_id"),
        ("Bundle / package ID", m.get("bundle_id") or m.get("package") or (m.get("native_id") if c.kind == "app" else None), "metadata"),
        ("Listed links", ", ".join(c.external_links) if c.external_links else None, "external_links"),
        ("Account / listing created", c.source_created_at, "source_created_at"),
        ("Followers", m.get("followers"), "metadata.followers"),
        ("Bluesky verification", m.get("bluesky_verified_status") if m.get("bluesky_verified_status") not in (None, "none") else None, "metadata.bluesky_verified_status"),
        ("Rating", m.get("rating"), "metadata.rating"),
        ("Installs", m.get("installs"), "metadata.installs"),
        ("Category", m.get("genre"), "metadata.genre"),
        ("Description length", f"{len(c.description)} characters" if c.description else "No description provided", "description"),
    ]
    return [{"label": l, "value": str(v), "field": f} for l, v, f in facts if v not in (None, "")]


def inferences(f: Finding) -> list[dict]:
    """The stored heuristic assessment, per signal, with the group it belongs to and whether it corroborates."""
    sig = (f.signals or {}).get("signals", {})
    groups = DEFAULT_CONFIG["groups"]
    out = []
    for gname, g in groups.items():
        for s in g["signals"]:
            if s not in sig:
                continue
            v = sig[s]
            out.append({
                "group": gname, "group_label": g["label"], "signal": s, "label": SIGNAL_LABELS.get(s, s),
                "evaluated": bool(v.get("evaluated")), "score": v.get("score", 0.0), "statement": v.get("detail", ""),
                "evidence": v.get("evidence", []), "corroborates": gname in (f.corroborating_groups or []) and bool(v.get("evaluated")),
            })
    return out


def comparison_assets(f: Finding, c: Candidate, brand: Brand) -> dict:
    """The official assets the candidate is compared against (from the *current* brand profile)."""
    sig = (f.signals or {}).get("signals", {})
    platform = (c.extra or {}).get("platform") or c.source
    store = STORE_FOR_SOURCE.get(c.source, platform)
    apps = [a for a in brand.official_apps if a.store == store] or (list(brand.official_apps) if c.kind == "app" else [])
    accounts = [a for a in brand.official_accounts if a.platform == platform]
    return {
        "brand_name": brand.name,
        "matched_brand_name": (sig.get("name", {}).get("data") or {}).get("matched_brand_name") or None,
        "aliases": brand.aliases or [],
        "logo": {"available": bool(brand.logo_path), "phash": brand.logo_phash, "dhash": brand.logo_dhash},
        "official_domains": brand.official_domains or [],
        "official_apps": [
            {"store": a.store, "name": a.name, "app_id": a.app_id, "publisher_id": a.publisher_id, "publisher_name": a.publisher_name,
             "same_store": a.store == store}
            for a in apps
        ] if c.kind == "app" else [],
        "official_accounts": [{"platform": a.platform, "handle": a.handle, "profile_url": a.profile_url} for a in accounts] if c.kind == "account" else [],
        "description_reference": bool(brand.description or brand.keywords),
        "note": "Official assets come from the current brand profile and may have changed since the finding was scored.",
    }


def provenance(c: Candidate, db: Session) -> dict:
    p = c.provenance or {}
    queries = p.get("queries") or ([p["query"]] if p.get("query") else [])
    n_obs = db.scalar(select(Observation.id).where(Observation.candidate_id == c.id).order_by(Observation.id.desc()).limit(1))
    return {
        "source": c.source, "source_type": c.source_type, "source_type_note": SOURCE_TYPE_NOTES.get(c.source_type, ""),
        "adapter": p.get("adapter"), "endpoint": p.get("endpoint"), "queries": queries,
        "first_observed_at": _iso(c.first_observed_at), "last_observed_at": _iso(c.last_observed_at),
        "collected_at": _iso(c.last_observed_at), "content_hash": (c.content_hash or "")[:12], "has_observations": n_obs is not None,
    }


def build_evidence(db: Session, f: Finding, brand: Brand) -> dict:
    c = f.candidate
    return {
        "observed_facts": observed_facts(c),
        "inferences": inferences(f),
        "comparison": comparison_assets(f, c, brand),
        "provenance": provenance(c, db),
        "indicators": [{"kind": i.kind, "label": ind.KIND_LABELS[i.kind], "value": i.display, "field": i.field}
                       for i in ind.extract(c, brand.official_domains)],
        "disclaimer": "Potential impersonation — review required. Scores are heuristic triage evidence, not proof of intent or ownership.",
    }


def shared_indicators(db: Session, org_id: int, f: Finding, limit: int = 2000) -> list[dict]:
    """Other candidates in the organization that share an observable indicator with this finding's candidate."""
    brand = db.get(Brand, f.brand_id)
    mine = {(i.kind, i.value): i for i in ind.extract(f.candidate, brand.official_domains)}
    if not mine:
        return []
    rows = db.execute(
        select(Finding, Brand).join(Brand, Finding.brand_id == Brand.id).join(Candidate, Finding.candidate_id == Candidate.id)
        .where(Brand.organization_id == org_id, Finding.id != f.id)
        .options(selectinload(Finding.candidate)).order_by(Finding.id.desc()).limit(limit)
    ).all()
    groups: dict[tuple[str, str], list[dict]] = {}
    for other, b in rows:
        oc = other.candidate
        for i in ind.extract(oc, b.official_domains):
            key = (i.kind, i.value)
            if key in mine:
                # Same handle on the *same* platform is the same account (already de-duplicated) — skip.
                if i.kind == "handle" and oc.source == f.candidate.source:
                    continue
                groups.setdefault(key, []).append({
                    "finding_id": other.id, "name": oc.name, "handle": oc.handle, "platform": (oc.extra or {}).get("platform") or oc.source,
                    "kind": oc.kind, "brand_name": b.name, "risk_level": other.risk_level, "status": other.status,
                    "source_type": oc.source_type, "observed_in": i.field,
                })
    out = []
    for key, matches in groups.items():
        i = mine[key]
        out.append({"kind": i.kind, "label": ind.KIND_LABELS[i.kind], "value": i.display, "observed_in": i.field, "candidates": matches[:25],
                    "count": len(matches)})
    order = list(ind.KIND_LABELS)
    out.sort(key=lambda g: (order.index(g["kind"]), -g["count"]))
    return out


# ------------------------------------------------------------------ report

def report_data(db: Session, f: Finding, org_name: str, generated_by: str) -> dict:
    from ..serializers import finding_out

    brand = db.get(Brand, f.brand_id)
    out = finding_out(f, brand.name, detail=True)
    history = db.execute(
        select(Observation, Scan).join(Scan, Observation.scan_id == Scan.id).where(Observation.candidate_id == f.candidate_id).order_by(Observation.id)
    ).all()
    return {
        "report": {"title": f"Evidence report — finding #{f.id}", "organization": org_name, "generated_by": generated_by,
                   "generated_at": datetime.now(timezone.utc).isoformat(),
                   "statement": "Potential impersonation — review required. This report records observed data and heuristic signals; "
                                "it is not a determination of fraud, ownership or intent."},
        "finding": {k: out[k] for k in ("id", "brand_name", "risk_level", "risk_score", "classification", "detection_type", "status",
                                        "change_state", "explanation", "corroborating_groups")},
        "status_label": STATUS_LABELS.get(f.status, f.status),
        "candidate": out["candidate"],
        "evidence": build_evidence(db, f, brand),
        "related": shared_indicators(db, brand.organization_id, f),
        "observations": [{"scan_id": s.id, "observed_at": _iso(o.observed_at), "risk_score": o.risk_score, "content_hash": o.content_hash[:12],
                          "trigger": s.trigger} for o, s in history],
        "review_history": [{**d, "action_label": ACTION_LABELS.get(d["action"], d["action"])} for d in out["decisions"]],
    }


def report_html(data: dict) -> str:
    e = html.escape
    r, fi, c, ev = data["report"], data["finding"], data["candidate"], data["evidence"]

    def table(rows: list[tuple[str, str]]) -> str:
        return "<table>" + "".join(f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in rows) + "</table>"

    synthetic = c["source_type"] == "simulated"
    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
        f"<title>{e(r['title'])}</title><style>",
        "body{font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:#1a1d1c;max-width:860px;margin:32px auto;padding:0 16px}",
        "h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 8px;border-bottom:1px solid #ddd;padding-bottom:4px}",
        "table{border-collapse:collapse;width:100%}th,td{text-align:left;vertical-align:top;padding:5px 8px;border-bottom:1px solid #eee;font-size:13px}",
        "th{width:220px;color:#555;font-weight:500}.note{background:#f4f6f5;border-left:3px solid #2b6b57;padding:8px 12px;font-size:13px}",
        ".warn{background:#fff6e5;border-left:3px solid #b7791f;padding:8px 12px;font-size:13px}code{font-size:12px}ul{margin:4px 0;padding-left:20px}",
        "small{color:#666}</style></head><body>",
        f"<h1>{e(r['title'])}</h1><small>{e(r['organization'])} · generated {e(r['generated_at'])} by {e(r['generated_by'])}</small>",
        f"<p class=note>{e(r['statement'])}</p>",
    ]
    if synthetic:
        parts.append("<p class=warn>This finding is based on a SYNTHETIC demo record. It does not describe a real account or listing.</p>")
    parts += [
        "<h2>Summary</h2>",
        table([("Brand", fi["brand_name"]), ("Classification", fi["classification"]), ("Risk level", f"{fi['risk_level']} (heuristic score {fi['risk_score']:.0f}/100)"),
               ("Review status", data["status_label"]), ("Candidate", c["name"]), ("Source URL", c["url"] or "—"),
               ("First observed", c["first_observed_at"]), ("Last observed", c["last_observed_at"])]),
        f"<p>{e(fi['explanation'])}</p>",
        "<h2>Observed facts</h2><small>Verbatim from the stored record collected from the source.</small>",
        table([(x["label"], x["value"]) for x in ev["observed_facts"]]),
    ]
    if c.get("description"):
        parts.append(f"<p><b>Description as collected</b></p><blockquote>{e(c['description'])}</blockquote>")
    parts.append("<h2>Heuristic inferences</h2><small>Automated similarity and pattern signals. Scores are 0–1; ✓ marks groups that corroborate the identity match.</small><table>")
    for x in ev["inferences"]:
        score = f"{x['score']:.2f}" if x["evaluated"] else "not evaluated"
        evid = "".join(f"<li>{e(t)}</li>" for t in x["evidence"])
        parts.append(f"<tr><th>{e(x['label'])}{' ✓' if x['corroborates'] else ''}</th><td><b>{score}</b> — {e(x['statement'])}{f'<ul>{evid}</ul>' if evid else ''}</td></tr>")
    parts.append("</table>")
    cmp_ = ev["comparison"]
    rows = [("Brand names", ", ".join([cmp_["brand_name"], *cmp_["aliases"]])), ("Official domains", ", ".join(cmp_["official_domains"]) or "—"),
            ("Brand logo", f"pHash {cmp_['logo']['phash']}" if cmp_["logo"]["available"] else "No logo on file")]
    rows += [(f"Official app ({a['store']})", f"{a['name'] or ''} {a['app_id']} · developer {a['publisher_name'] or '—'} (ID {a['publisher_id'] or '—'})") for a in cmp_["official_apps"]]
    rows += [(f"Official account ({a['platform']})", a["handle"]) for a in cmp_["official_accounts"]]
    parts += ["<h2>Official assets used for comparison</h2>", table(rows), f"<small>{e(cmp_['note'])}</small>"]
    if data["related"]:
        parts.append("<h2>Shared observable indicators</h2><small>Other findings in this organization showing the same value. "
                     "An overlap is an observation, not evidence of common ownership or coordination.</small><table>")
        for g in data["related"]:
            names = "; ".join(f"#{m['finding_id']} {m['name']} ({m['platform']})" for m in g["candidates"])
            parts.append(f"<tr><th>{e(g['label'])}: <code>{e(g['value'])}</code></th><td>{e(names)}</td></tr>")
        parts.append("</table>")
    pv = ev["provenance"]
    parts += ["<h2>Provenance</h2>", table([("Source", pv["source"]), ("Data type", f"{pv['source_type']} — {pv['source_type_note']}"),
                                             ("Collection method", pv["endpoint"] or "—"), ("Matched queries", ", ".join(pv["queries"]) or "—"),
                                             ("Collected (latest observation)", pv["collected_at"]), ("Content hash", pv["content_hash"])])]
    if data["observations"]:
        parts.append("<h2>Observation history</h2><table><tr><th>Scan</th><td><b>Observed · score · content hash</b></td></tr>")
        parts += [f"<tr><th>#{o['scan_id']} ({e(o['trigger'])})</th><td>{e(o['observed_at'])} · {o['risk_score'] if o['risk_score'] is not None else '—'} · {e(o['content_hash'])}</td></tr>" for o in data["observations"]]
        parts.append("</table>")
    parts.append("<h2>Review history</h2>")
    if data["review_history"]:
        parts.append("<table>")
        for d in data["review_history"]:
            trans = f" ({d['from_status']} → {d['to_status']})" if d.get("from_status") and d.get("to_status") and d["from_status"] != d["to_status"] else ""
            parts.append(f"<tr><th>{e(d['created_at'])}<br>{e(d['user'])}</th><td><b>{e(d['action_label'])}</b>{e(trans)}{('<br>' + e(d['note'])) if d['note'] else ''}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<p>No review decisions recorded.</p>")
    parts.append("</body></html>")
    return "".join(parts)
