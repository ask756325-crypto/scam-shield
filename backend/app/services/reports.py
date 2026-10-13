"""Executive report: a print-ready HTML summary for a period, computed only from stored records.

Synthetic (demo) data is counted separately and labelled; it never inflates the live figures.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Brand, Candidate, Decision, Finding, Organization, Scan, TakedownCase
from .evaluation import analyst_metrics
from .source_status import registry_status

LEVELS = ("critical", "high", "medium", "low")


def build(db: Session, org: Organization, days: int, brand_id: int | None = None) -> dict:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    q_brands = select(Brand).where(Brand.organization_id == org.id)
    if brand_id:
        q_brands = q_brands.where(Brand.id == brand_id)
    brands = db.scalars(q_brands).all()
    ids = [b.id for b in brands]
    scans = db.scalars(select(Scan).where(Scan.brand_id.in_(ids), Scan.created_at >= since)).all() if ids else []
    rows = db.execute(select(Finding, Candidate).join(Candidate, Finding.candidate_id == Candidate.id)
                      .where(Finding.brand_id.in_(ids))).all() if ids else []
    live = [(f, c) for f, c in rows if c.source_type != "simulated"]
    synthetic = len(rows) - len(live)
    new_live = [(f, c) for f, c in live if f.created_at >= since]
    by_level = {lvl: sum(1 for f, _ in new_live if f.risk_level == lvl) for lvl in LEVELS}

    # Weekly new findings (live) for the trend chart.
    weeks = []
    for w in range((days + 6) // 7):
        start, end = since + timedelta(days=7 * w), min(since + timedelta(days=7 * (w + 1)), now)
        weeks.append({"start": start.date().isoformat(), **{lvl: sum(1 for f, _ in new_live if start <= f.created_at < end and f.risk_level == lvl) for lvl in LEVELS}})

    decisions = db.execute(select(Decision, Finding).join(Finding).where(Finding.brand_id.in_(ids), Decision.created_at >= since,
                                                                          Decision.action.in_(["confirm", "mark_safe"]))).all() if ids else []
    first_decision: dict[int, datetime] = {}
    for d, f in decisions:
        if f.id not in first_decision or d.created_at < first_decision[f.id]:
            first_decision[f.id] = d.created_at
    times = [(first_decision[f.id] - f.created_at).total_seconds() / 3600 for f, c in live if f.id in first_decision and first_decision[f.id] >= f.created_at]
    takedowns = db.scalars(select(TakedownCase).where(TakedownCase.organization_id == org.id, TakedownCase.created_at >= since)).all()
    top = sorted([(f, c) for f, c in live if f.status in ("open", "escalated", "confirmed") and f.risk_level in ("critical", "high")],
                 key=lambda fc: (LEVELS.index(fc[0].risk_level), -fc[0].risk_score))[:10]
    acc = analyst_metrics(db, org.id, brand_id)
    return {
        "organization": org.name, "brands": [b.name for b in brands], "days": days, "since": since, "now": now,
        "scans": len(scans), "scans_ok": sum(1 for s in scans if s.status == "completed"), "scans_partial": sum(1 for s in scans if s.status == "partial"),
        "scans_failed": sum(1 for s in scans if s.status == "failed"), "candidates": sum(s.candidates_unique for s in scans if s.mode != "demo"),
        "excluded": sum(s.excluded_official for s in scans if s.mode != "demo"),
        "new_by_level": by_level, "weeks": weeks,
        "confirmed": sum(1 for d, _ in decisions if d.action == "confirm"), "legitimate": sum(1 for d, _ in decisions if d.action == "mark_safe"),
        "backlog": sum(1 for f, _ in live if f.status in ("open", "escalated") and f.risk_level in ("critical", "high", "medium")),
        "median_hours_to_decision": round(median(times), 1) if times else None,
        "takedowns": {s: sum(1 for t in takedowns if t.status == s) for s in ("draft", "reported", "acknowledged", "removed", "rejected", "withdrawn")},
        "takedowns_verified_gone": sum(1 for t in takedowns if t.verification == "not_observed"),
        "top": [{"name": c.name, "platform": (c.extra or {}).get("platform") or c.source, "level": f.risk_level, "score": f.risk_score,
                 "status": f.status, "type": f.detection_type, "id": f.id} for f, c in top],
        "sources": [s for s in registry_status(db, org, ids, include_demo=False) if s["enabled"]],
        "accuracy": acc, "synthetic_findings": synthetic,
    }


def render_html(d: dict, base_url: str) -> str:
    e = html.escape
    colors = {"critical": "#b42318", "high": "#c4320a", "medium": "#b54708", "low": "#667085"}
    maxw = max([sum(w[lvl] for lvl in LEVELS) for w in d["weeks"]] + [1])
    bars = []
    for i, w in enumerate(d["weeks"]):
        y = 140
        for lvl in reversed(LEVELS):
            h = 120 * w[lvl] / maxw
            if h:
                bars.append(f'<rect x="{20 + i * 46}" y="{y - h:.1f}" width="30" height="{h:.1f}" fill="{colors[lvl]}"/>')
                y -= h
        bars.append(f'<text x="{35 + i * 46}" y="156" font-size="9" text-anchor="middle" fill="#667085">{e(w["start"][5:])}</text>')
    chart = f'<svg viewBox="0 0 {max(60, 30 + 46 * len(d["weeks"]))} 160" width="100%" height="170" role="img" aria-label="New live findings per week">{"".join(bars)}</svg>'
    acc = d["accuracy"]
    med = acc["by_threshold"]["medium"]
    pct = lambda v: "—" if v is None else f"{round(v * 100)}%"  # noqa: E731
    kpi = lambda label, value, sub="": f'<div class="kpi"><div class="v">{value}</div><div class="l">{e(label)}</div><div class="s">{e(sub)}</div></div>'  # noqa: E731
    sources = "".join(f"<tr><td>{e(s['label'])}</td><td>{e(s['state'])}</td><td>{e(s['health'].replace('_', ' '))}</td>"
                      f"<td>{e(s['last_success']['at'][:16].replace('T', ' ') if s['last_success'] else 'never')}</td></tr>" for s in d["sources"])
    top = "".join(f"<tr><td>{e(t['name'])}</td><td>{e(t['platform'])}</td><td style='color:{colors.get(t['level'], '#000')}'>{e(t['level'])} · {t['score']:.0f}</td>"
                  f"<td>{e((t['type'] or '').replace('_', ' '))}</td><td>{e(t['status'])}</td></tr>" for t in d["top"]) or "<tr><td colspan=5>None in this period.</td></tr>"
    td = d["takedowns"]
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>ScamShield executive report — {e(d['organization'])}</title>
<style>
body{{font:13px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:#101828;max-width:900px;margin:28px auto;padding:0 18px}}
h1{{font-size:22px;margin:0}}h2{{font-size:14px;margin:26px 0 8px;border-bottom:1px solid #e4e7ec;padding-bottom:4px}}
.sub{{color:#667085}}.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:14px}}
.kpi{{border:1px solid #e4e7ec;border-radius:8px;padding:10px 12px}}.kpi .v{{font-size:22px;font-weight:600}}.kpi .l{{color:#344054}}.kpi .s{{color:#98a2b3;font-size:11px}}
table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:5px 8px;border-bottom:1px solid #f2f4f7;font-size:12.5px}}th{{color:#667085;font-weight:500}}
.note{{background:#f6f8f7;border-left:3px solid #2b6b57;padding:8px 12px;color:#344054;font-size:12px}}.print{{float:right}}
@media print{{.print{{display:none}}body{{margin:0}}}}
</style></head><body>
<button class="print" onclick="window.print()">Print / save as PDF</button>
<h1>Brand protection report</h1>
<div class="sub">{e(d['organization'])} · {e(', '.join(d['brands']) or 'no brands')} · last {d['days']} days ({d['since'].date()} – {d['now'].date()}) · generated {d['now'].strftime('%Y-%m-%d %H:%M UTC')}</div>
<p class="note">Findings are potential impersonations ranked by heuristic evidence; analysts confirm or dismiss each one. All figures come from stored scan and review records{f'; {d["synthetic_findings"]} synthetic demo findings are excluded' if d['synthetic_findings'] else ''}.</p>
<div class="kpis">
{kpi('New critical / high findings', f"{d['new_by_level']['critical']} / {d['new_by_level']['high']}", f"+{d['new_by_level']['medium']} medium")}
{kpi('Confirmed impersonations', d['confirmed'], f"{d['legitimate']} marked legitimate")}
{kpi('Waiting for review', d['backlog'], 'medium and above')}
{kpi('Median time to decision', '—' if d['median_hours_to_decision'] is None else f"{d['median_hours_to_decision']} h", 'first decision after detection')}
{kpi('Scans run', d['scans'], f"{d['scans_ok']} complete · {d['scans_partial']} partial · {d['scans_failed']} failed")}
{kpi('Takedowns removed', td['removed'], f"{td['reported'] + td['acknowledged']} in progress · {d['takedowns_verified_gone']} verified gone by scans")}
</div>
<h2>New live findings per week</h2>{chart}
<div class="sub">Stacked by level: critical, high, medium, low.</div>
<h2>Top threats</h2><table><tr><th>Account / listing</th><th>Platform</th><th>Risk</th><th>Type</th><th>Status</th></tr>{top}</table>
<h2>Detection accuracy (analyst-labelled)</h2>
<p>{acc['labelled']} live findings were confirmed or marked legitimate. Flagging at <b>medium and above</b>: precision {pct(med['precision'])}, recall {pct(med['recall'])}.
{'' if acc['enough_labels'] else ' <i>Too few labels to rely on these numbers.</i>'}</p>
<h2>Sources</h2><table><tr><th>Source</th><th>State</th><th>Last observed health</th><th>Last successful request (UTC)</th></tr>{sources or '<tr><td colspan=4>No sources enabled.</td></tr>'}</table>
<p class="sub" style="margin-top:22px">Open the workspace: {e(base_url)}/app</p>
</body></html>"""
