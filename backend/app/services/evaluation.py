"""Detection accuracy: metrics from analyst decisions (real) and from the bundled synthetic benchmark.

Predicted positive at threshold T = finding's risk level is T or more severe. Ground truth:
    analyst metrics  — status "confirmed" (impersonation) vs "safe" (marked legitimate); everything else unlabelled
    benchmark        — the hand labels in app/evaluation/benchmark.py
Both report the confusion matrix, precision, recall and F1 per threshold, plus a 0–100 score sweep for tuning.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Brand, Candidate, Finding

LEVELS = ["critical", "high", "medium", "low"]
RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
MIN_LABELS = 20  # below this, metrics are shown but flagged as too few to rely on


def _metrics(pairs: list[tuple[bool, bool]]) -> dict:
    tp = sum(1 for pred, truth in pairs if pred and truth)
    fp = sum(1 for pred, truth in pairs if pred and not truth)
    fn = sum(1 for pred, truth in pairs if not pred and truth)
    tn = sum(1 for pred, truth in pairs if not pred and not truth)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if precision is not None and recall is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": _r(precision), "recall": _r(recall), "f1": _r(f1)}


def _r(v):
    return round(v, 4) if v is not None else None


def summarize(items: list[tuple[str, float, bool]]) -> dict:
    """items: (risk_level, risk_score, is_impersonation)."""
    by_level = {lvl: _metrics([(RANK.get(level, 4) <= RANK[lvl], truth) for level, _, truth in items]) for lvl in LEVELS}
    sweep = [{"min_score": t, **_metrics([(score >= t, truth) for _, score, truth in items])} for t in range(0, 101, 5)]
    scored = [s for s in sweep if s["f1"] is not None]
    best = max(scored, key=lambda s: (s["f1"], s["precision"] or 0)) if scored else None
    positives = sum(1 for *_, t in items if t)
    return {
        "labelled": len(items), "positives": positives, "negatives": len(items) - positives,
        "enough_labels": len(items) >= MIN_LABELS and 0 < positives < len(items),
        "by_threshold": by_level, "score_sweep": sweep, "best_f1_threshold": best,
    }


def analyst_metrics(db: Session, org_id: int, brand_id: int | None = None) -> dict:
    q = (select(Finding.risk_level, Finding.risk_score, Finding.status, Candidate.source_type, Candidate.source)
         .join(Brand, Finding.brand_id == Brand.id).join(Candidate, Finding.candidate_id == Candidate.id)
         .where(Brand.organization_id == org_id, Finding.status.in_(["confirmed", "safe"])))
    if brand_id:
        q = q.where(Finding.brand_id == brand_id)
    rows = db.execute(q).all()
    live = [(lvl, score, status == "confirmed") for lvl, score, status, stype, _ in rows if stype != "simulated"]
    out = summarize(live)
    out["excluded_simulated"] = sum(1 for r in rows if r[3] == "simulated")
    by_source: dict[str, list] = {}
    for lvl, score, status, stype, source in rows:
        if stype != "simulated":
            by_source.setdefault(source, []).append((RANK.get(lvl, 4) <= RANK["medium"], status == "confirmed"))
    out["by_source_at_medium"] = {s: {**_metrics(p), "labelled": len(p)} for s, p in by_source.items()}
    out["note"] = ("Ground truth is your analysts' decisions: Confirmed = impersonation, Marked legitimate = not. Open findings are "
                   "unlabelled and not counted. Decisions are made after seeing the score, so these numbers can be optimistic; "
                   "simulated (demo) findings are excluded.")
    return out


def benchmark_metrics() -> dict:
    from ..detection.engine import evaluate
    from ..evaluation.benchmark import BRAND, CASES

    # evaluate() returns excluded records first, so match results to cases by record identity, not position.
    by_record = {id(ev.record): ev for ev in evaluate(BRAND, [c.record for c in CASES])}
    rows, cases, official_errors = [], [], []
    for case in CASES:
        ev = by_record[id(case.record)]
        if case.official:
            if ev.excluded is None:
                official_errors.append(case.id)
            cases.append({"id": case.id, "category": case.category, "label": "official", "excluded": ev.excluded is not None,
                          "risk_level": None, "risk_score": None, "name": case.record.name})
            continue
        a = ev.assessment
        level = a.risk_level if ev.excluded is None else "info"
        score = a.risk_score if ev.excluded is None else 0.0
        rows.append((level, score, case.label))
        cases.append({"id": case.id, "category": case.category, "label": "impersonation" if case.label else "legitimate",
                      "excluded": ev.excluded is not None, "risk_level": level, "risk_score": score, "name": case.record.name,
                      "predicted_at_medium": RANK.get(level, 4) <= RANK["medium"]})
    out = summarize(rows)
    out.update({"cases": cases, "official_assets_flagged": official_errors,
                "note": "Synthetic, hand-labelled benchmark (fictional brand). It guards against regressions and documents trade-offs; "
                        "it does not measure real-world accuracy. Logo similarity is not exercised (no images)."})
    return out
