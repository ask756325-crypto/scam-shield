"""Takedown cases: platform reporting routes, generated evidence reports, status lifecycle and scan verification.

ScamShield never submits reports or contacts platforms. It prepares the report, links to the platform's own
reporting route, and records what the analyst did. Reporting URLs change — the UI tells analysts to verify them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Brand, Finding, Observation, Scan, TakedownCase
from .evidence import build_evidence

STATUSES = ("draft", "reported", "acknowledged", "removed", "rejected", "withdrawn")
OPEN_STATUSES = ("draft", "reported", "acknowledged")
TRANSITIONS: dict[str, set[str]] = {
    "draft": {"reported", "withdrawn"},
    "reported": {"acknowledged", "removed", "rejected", "withdrawn"},
    "acknowledged": {"removed", "rejected", "withdrawn"},
    "rejected": {"reported", "withdrawn"},  # resubmit with more evidence
    "removed": {"reported"},  # it came back: report again
    "withdrawn": {"draft"},
}


def channel_for(platform: str, candidate) -> tuple[str, str | None, str]:
    """(label, url, instructions) for the platform's own reporting route."""
    meta = candidate.extra or {}
    if platform == "apple":
        return ("Apple — App Store content dispute", "https://www.apple.com/legal/intellectual-property/dispute-forms/app-store/",
                "Submit the App Store dispute form as the rights holder. Include the listing URL, bundle ID and developer ID below.")
    if platform == "google_play":
        return ("Google — Report content for legal reasons (Google Play)", "https://support.google.com/legal/answer/3110420",
                "Choose Google Play → impersonation / trademark. Include the package name and developer name below.")
    if platform == "bluesky":
        return ("Bluesky — report the account in the app", candidate.url,
                "Open the profile, choose Report account → Impersonation (or Misleading), and paste the summary below.")
    if platform == "mastodon":
        home = meta.get("home_instance") or (urlsplit(candidate.url).hostname if candidate.url else None)
        return (f"Mastodon — report to the moderators of {home or 'the hosting instance'}", f"https://{home}/about" if home else candidate.url,
                "Use Report on the profile (moderators of the hosting instance review it). The /about page lists the instance's rules and contact.")
    if platform == "youtube":
        return ("YouTube — impersonation report", "https://support.google.com/youtube/answer/2801947",
                "Report the channel for impersonation from the channel's About page, or use the impersonation form.")
    if platform == "domain":
        return ("Phishing / abusive domain — Google Safe Browsing report", "https://safebrowsing.google.com/safebrowsing/report_phish/",
                "Report the site to Safe Browsing, and contact the domain registrar's abuse address (find it in the WHOIS/RDAP record).")
    return ("Platform reporting route", candidate.url, "Report the account or listing through the platform's own reporting tools.")


def generate_report(db: Session, f: Finding, brand: Brand) -> str:
    c = f.candidate
    ev = build_evidence(db, f, brand)
    facts = {x["label"]: x["value"] for x in ev["observed_facts"]}
    reasons = [r for x in ev["inferences"] if x["corroborates"] for r in x["evidence"]][:6]
    cmp_ = ev["comparison"]
    official = [f"{a['store']} app {a['app_id']}" for a in cmp_["official_apps"]] + [f"{a['platform']} account {a['handle']}" for a in cmp_["official_accounts"]]
    lines = [
        f"Subject: Impersonation of {brand.name}",
        "",
        f"We represent {brand.name}. The {'listing' if c.kind == 'app' else 'account'} below appears to impersonate our brand and may mislead users.",
        "",
        "Reported content",
        f"- Name: {c.name}",
    ]
    for label in ("Handle", "Source URL", "Source ID", "Bundle / package ID", "Developer / publisher", "Developer ID"):
        if label in facts:
            lines.append(f"- {label}: {facts[label]}")
    lines += [
        f"- First observed: {c.first_observed_at.date().isoformat()} · last observed: {c.last_observed_at.date().isoformat()}",
        "",
        "Why we believe this is impersonation",
        *[f"- {r}" for r in reasons],
        "",
        f"Our official {'apps and accounts' if official else 'domains'}: " + (", ".join(official) if official else ", ".join(cmp_["official_domains"]) or "—"),
        "",
        "This content is not operated by or affiliated with us. Please review it under your impersonation policy.",
    ]
    return "\n".join(lines)


def _event(case: TakedownCase, status: str, note: str, user_email: str | None) -> None:
    case.events = [*(case.events or []), {"at": datetime.now(timezone.utc).isoformat(), "status": status, "note": note[:1000], "user": user_email or "System"}]


def create_case(db: Session, f: Finding, user) -> TakedownCase:
    brand = db.get(Brand, f.brand_id)
    c = f.candidate
    platform = (c.extra or {}).get("platform") or c.source
    label, url, _ = channel_for(platform, c)
    case = TakedownCase(organization_id=brand.organization_id, finding_id=f.id, platform=platform, channel_label=label, channel_url=url,
                        report_text=generate_report(db, f, brand), created_by_id=user.id)
    _event(case, "draft", "Case opened with a generated report", user.email)
    db.add(case)
    return case


def apply_status(case: TakedownCase, status: str, note: str, reference: str | None, user_email: str) -> None:
    if status not in TRANSITIONS.get(case.status, set()):
        raise ValueError(f"Cannot move a {case.status} case to {status}")
    now = datetime.now(timezone.utc)
    case.status = status
    if reference is not None:
        case.reference = reference.strip()[:200]
    if status == "reported":
        case.reported_at, case.closed_at = now, None
    if status in ("removed", "rejected", "withdrawn"):
        case.closed_at = now
    _event(case, status, note, user_email)


def verify_after_scan(db: Session, scan: Scan) -> int:
    """After a scan, record whether reported listings are still observed. Only sources that completed cleanly count."""
    clean = {ss.source for ss in scan.sources if ss.status in ("ok", "empty")}
    if not clean:
        return 0
    rows = db.execute(
        select(TakedownCase, Finding).join(Finding, TakedownCase.finding_id == Finding.id)
        .where(Finding.brand_id == scan.brand_id, TakedownCase.status.in_(["reported", "acknowledged", "removed"]))
    ).all()
    n = 0
    for case, f in rows:
        if f.candidate.source not in clean:
            continue
        seen = db.scalar(select(Observation.id).where(Observation.scan_id == scan.id, Observation.candidate_id == f.candidate_id)) is not None
        if seen:
            new = "reappeared" if case.status == "removed" else "still_observed"
        elif f.change_state == "resolved":  # absent from consecutive clean scans (same rule as resolution)
            new = "not_observed"
        else:
            continue  # one clean miss is not enough evidence either way
        if new == "reappeared" and case.verification != "reappeared":
            _event(case, case.status, f"Seen again in scan #{scan.id} after being marked removed", None)
        case.verification, case.verified_scan_id, case.verified_at = new, scan.id, datetime.now(timezone.utc)
        n += 1
    return n


def case_out(case: TakedownCase, f: Finding | None = None, brand_name: str | None = None) -> dict:
    instructions = None
    if f is not None:
        instructions = channel_for(case.platform, f.candidate)[2]
    return {
        "id": case.id, "finding_id": case.finding_id, "platform": case.platform, "channel_label": case.channel_label, "channel_url": case.channel_url,
        "instructions": instructions, "status": case.status, "reference": case.reference, "report_text": case.report_text, "events": case.events or [],
        "verification": case.verification, "verified_scan_id": case.verified_scan_id,
        "verified_at": case.verified_at.isoformat() if case.verified_at else None,
        "reported_at": case.reported_at.isoformat() if case.reported_at else None, "closed_at": case.closed_at.isoformat() if case.closed_at else None,
        "created_at": case.created_at.isoformat(), "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        "allowed_next": sorted(TRANSITIONS.get(case.status, set())),
        "candidate": {"name": f.candidate.name, "handle": f.candidate.handle, "url": f.candidate.url, "source_type": f.candidate.source_type} if f else None,
        "brand_name": brand_name, "finding_status": f.status if f else None, "risk_level": f.risk_level if f else None,
    }
