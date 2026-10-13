"""Risk scoring and classification.

Design:
* Signals are grouped into independent evidence groups. Correlated signals inside a group (display
  name and handle both measure identity) are combined with max(), never summed.
* Score = 100 × Σ(weight × group score) / Σ(weight of groups applicable to this candidate kind).
  Applicable-but-unavailable signals contribute 0 and are reported as "not evaluated" — missing data
  never inflates a score.
* Classification additionally requires *corroboration*: the number of non-identity groups whose score
  crosses their threshold. Name similarity alone, or a different publisher alone, can only yield "low".
  Publisher mismatch is never sufficient corroboration by itself: a different developer account or
  package ID is normal for fan apps, resellers and unrelated namesakes, so at least one other group
  (logo, description, links, scam cues) must also corroborate before an app is rated medium or above.
* Scores are heuristic evidence for triage, not calibrated probabilities.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .signals import Signal

DEFAULT_CONFIG: dict = {
    "groups": {
        "identity": {"signals": ["name", "handle", "package"], "weight": 0.30, "threshold": 0.70, "label": "Name / handle similarity"},
        "visual": {"signals": ["logo"], "weight": 0.20, "threshold": 0.75, "label": "Logo similarity", "kinds": ["account", "app"]},
        "content": {"signals": ["description"], "weight": 0.12, "threshold": 0.30, "label": "Description similarity", "kinds": ["account", "app"]},
        "links": {"signals": ["urls"], "weight": 0.13, "threshold": 0.50, "label": "Suspicious links"},
        "behavior": {"signals": ["scam"], "weight": 0.15, "threshold": 0.40, "label": "Scam indicators"},
        "provenance": {"signals": ["publisher"], "weight": 0.10, "threshold": 0.75, "label": "Publisher mismatch", "kinds": ["app"]},
    },
    # A candidate must look related to the brand before it can become a finding at all.
    "relevance": {"identity_min": 0.70, "visual_min": 0.85},
    "levels": {
        "critical": {"min_score": 55, "min_corroboration": 2, "requires": ["behavior"]},
        "high": {"min_score": 50, "min_corroboration": 2},
        "medium": {"min_score": 35, "min_corroboration": 1},
    },
}

# Groups that may add to the corroboration count but never satisfy it alone.
SUPPORTING_ONLY = {"provenance"}

LEVEL_ORDER = ["critical", "high", "medium", "low", "info"]


def merge_config(overrides: dict | None) -> dict:
    """Deep-merge organization overrides onto defaults, accepting only known keys and sane ranges."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if not overrides:
        return cfg
    for g, vals in (overrides.get("groups") or {}).items():
        if g in cfg["groups"] and isinstance(vals, dict):
            for k in ("weight", "threshold"):
                if k in vals and isinstance(vals[k], (int, float)) and 0 <= vals[k] <= 1:
                    cfg["groups"][g][k] = float(vals[k])
    for k in ("identity_min", "visual_min"):
        v = (overrides.get("relevance") or {}).get(k)
        if isinstance(v, (int, float)) and 0 <= v <= 1:
            cfg["relevance"][k] = float(v)
    for lvl, vals in (overrides.get("levels") or {}).items():
        if lvl in cfg["levels"] and isinstance(vals, dict):
            if isinstance(vals.get("min_score"), (int, float)) and 0 <= vals["min_score"] <= 100:
                cfg["levels"][lvl]["min_score"] = float(vals["min_score"])
            if isinstance(vals.get("min_corroboration"), int) and 0 <= vals["min_corroboration"] <= 5:
                cfg["levels"][lvl]["min_corroboration"] = vals["min_corroboration"]
    return cfg


@dataclass
class Assessment:
    relevant: bool
    risk_score: float
    risk_level: str
    classification: str
    explanation: str
    signals: dict[str, dict]
    group_scores: dict[str, float | None]
    corroborating_groups: list[str]
    reasons: list[str] = field(default_factory=list)
    not_evaluated: list[str] = field(default_factory=list)
    detection_type: str = "unrelated"


def assess(signals: list[Signal], kind: str, config: dict | None = None) -> Assessment:
    cfg = config or DEFAULT_CONFIG
    by_name = {s.name: s for s in signals}
    group_scores: dict[str, float | None] = {}
    applicable_weight = 0.0
    weighted = 0.0
    not_evaluated: list[str] = []
    for gname, g in cfg["groups"].items():
        if "kinds" in g and kind not in g["kinds"]:
            continue
        applicable_weight += g["weight"]
        evaluated = [by_name[s] for s in g["signals"] if s in by_name and by_name[s].evaluated]
        missing = [by_name[s] for s in g["signals"] if s in by_name and not by_name[s].evaluated]
        if evaluated:
            gs = max(s.score for s in evaluated)
            group_scores[gname] = gs
            weighted += g["weight"] * gs
        else:
            group_scores[gname] = None
            reason = missing[0].detail if missing else "signal not collected"
            not_evaluated.append(f"{g['label']}: {reason}")
    score = round(100.0 * weighted / applicable_weight, 1) if applicable_weight else 0.0

    identity = group_scores.get("identity") or 0.0
    visual = group_scores.get("visual") or 0.0
    rel = cfg["relevance"]
    relevant = identity >= rel["identity_min"] or visual >= rel["visual_min"]

    corroborating = [
        g for g, s in group_scores.items() if g != "identity" and s is not None and s >= cfg["groups"][g]["threshold"]
    ]
    # Evidence groups that can stand on their own (publisher mismatch only strengthens other evidence).
    independent = [g for g in corroborating if g not in SUPPORTING_ONLY]
    same_official_publisher = bool(by_name.get("publisher") and by_name["publisher"].data.get("same_official_publisher"))

    reasons: list[str] = []
    for s in signals:
        if s.evaluated and s.score > 0:
            reasons.extend(s.evidence)

    if not relevant:
        level, classification = "info", "Likely unrelated — below brand relevance threshold"
    elif same_official_publisher:
        level, classification = "low", "Published by official developer — verify listing is expected"
    elif not independent:
        level = "low"
        classification = (
            "Different publisher only — insufficient independent evidence" if corroborating
            else "Brand similarity only — insufficient independent evidence"
        )
    else:
        level = "low"
        for lvl in ("critical", "high", "medium"):
            rule = cfg["levels"][lvl]
            if score >= rule["min_score"] and len(corroborating) >= rule["min_corroboration"] and all(
                r in corroborating for r in rule.get("requires", [])
            ):
                level = lvl
                break
        if level == "critical":
            classification = "Potential impersonation with scam indicators — review required"
        elif level in ("high", "medium"):
            classification = "Potential impersonation — review required"
        else:
            classification = "Brand similarity only — insufficient independent evidence"

    explanation = build_explanation(level, score, group_scores, corroborating, by_name, cfg, relevant)
    return Assessment(
        relevant=relevant,
        risk_score=score,
        risk_level=level,
        classification=classification,
        explanation=explanation,
        signals={n: s.to_dict() for n, s in by_name.items()},
        group_scores={g: (round(v, 4) if v is not None else None) for g, v in group_scores.items()},
        corroborating_groups=corroborating,
        reasons=reasons[:12],
        not_evaluated=not_evaluated,
        detection_type=detection_type(kind, relevant, by_name, independent, same_official_publisher),
    )


def build_explanation(level, score, group_scores, corroborating, by_name, cfg, relevant) -> str:
    parts: list[str] = []
    ident = group_scores.get("identity")
    if ident is not None:
        top = max((by_name[n] for n in ("name", "handle", "package") if n in by_name and by_name[n].evaluated), key=lambda s: s.score, default=None)
        if top:
            ev = f" ({'; '.join(top.evidence[:2])})" if top.evidence else ""
            parts.append(f"Identity similarity {ident:.2f}{ev}.")
    if corroborating:
        labels = [cfg["groups"][g]["label"].lower() for g in corroborating]
        parts.append("Corroborated by " + ", ".join(labels) + ".")
    else:
        parts.append("No independent corroborating evidence beyond name similarity." if relevant else "")
    if level in ("low", "info"):
        parts.append("Not treated as impersonation without further evidence.")
    else:
        parts.append(f"Heuristic score {score:.0f}/100 — analyst review required before any action.")
    return " ".join(p for p in parts if p)


DETECTION_TYPES = {
    "fake_brand_page": "Fake brand page",
    "fake_profile": "Fake profile",
    "scam_account": "Scam account using brand identity",
    "lookalike_account": "Look-alike account",
    "suspicious_app": "Suspicious app listing",
    "lookalike_app": "Look-alike app",
    "official_publisher_app": "App from official publisher",
    "phishing_domain": "Possible phishing domain",
    "lookalike_domain": "Look-alike domain",
    "unrelated": "Unrelated",
}


def detection_type(kind: str, relevant: bool, by_name: dict[str, Signal], corroborating: list[str], same_official_publisher: bool) -> str:
    """What kind of impersonation the evidence suggests. Purely descriptive; risk level is decided separately."""
    if not relevant:
        return "unrelated"
    if kind == "domain":
        # A brand-bearing hostname always trips the link heuristics; "phishing" also needs scam/credential wording.
        return "phishing_domain" if "behavior" in corroborating else "lookalike_domain"
    if kind == "app":
        if same_official_publisher:
            return "official_publisher_app"
        return "suspicious_app" if corroborating else "lookalike_app"
    if "behavior" in corroborating:
        return "scam_account"
    if not corroborating:
        return "lookalike_account"
    name = by_name.get("name")
    handle = by_name.get("handle")
    # Presents as the brand itself: (near-)exact brand name with no extra persona words.
    claims_brand = any(
        s is not None and s.evaluated and s.score >= 0.95 and not s.data.get("risky_terms") for s in (name, handle)
    )
    official_claim = "official_claim" in ((by_name.get("scam").data or {}).get("categories", []) if by_name.get("scam") else [])
    if claims_brand or official_claim:
        return "fake_brand_page"
    # A "fake profile" copies the brand's identity (logo/bio) or poses as staff ("support", "official"…).
    # A name match corroborated only by, say, a link stays a look-alike — e.g. an artist called "DJ Brand".
    persona = any(s is not None and s.evaluated and s.data.get("risky_terms") for s in (name, handle))
    if persona or {"visual", "content"} & set(corroborating):
        return "fake_profile"
    return "lookalike_account"
