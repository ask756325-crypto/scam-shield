"""Name and handle similarity using RapidFuzz over confusable skeletons."""
from __future__ import annotations

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from .normalize import handle_local_part, normalize, skeleton, tokens
from .signals import Signal
from .variants import detect_variant_features

MIN_BRAND_LEN_FOR_FUZZY = 4  # very short brand names only match exactly / as whole tokens


def _pair_score(candidate: str, brand: str) -> tuple[float, str]:
    c_skel, b_skel = skeleton(candidate), skeleton(brand)
    if not c_skel or not b_skel:
        return 0.0, "empty"
    if c_skel == b_skel:
        return 1.0, "skeleton match"
    if len(b_skel) < MIN_BRAND_LEN_FOR_FUZZY:
        # Short names: only whole-token matches count, to avoid matching inside unrelated words.
        if b_skel in {skeleton(t) for t in tokens(candidate)}:
            return 0.8, "short brand as whole token"
        return 0.0, "short brand not present"
    if b_skel in c_skel:
        # Brand embedded with extra characters; more extra text → weaker identity claim.
        coverage = len(b_skel) / len(c_skel)
        return min(0.95, 0.80 + 0.15 * coverage), "brand embedded"
    # Normalized Levenshtein (substitution = 1 edit); RapidFuzz's Indel-based fuzz.ratio is too lenient
    # on short names ("anypal" vs "paypal" scores 0.83 there, 0.67 here).
    ratio = Levenshtein.normalized_similarity(c_skel, b_skel)
    # Typo variants embedded in longer names ("paypall support"): a strict edit-distance window.
    # (Fuzzy partial alignment was too lenient on real data — "AnyPal"/"PayPOS" matched "PayPal".)
    features = detect_variant_features(candidate, brand)
    typo = 0.0
    if features.typo_distance:
        typo = 0.88 if features.typo_distance == 1 else 0.80
        typo *= 0.85 + 0.15 * min(1.0, len(b_skel) / max(len(c_skel), 1))
    token = fuzz.token_set_ratio(normalize(candidate), normalize(brand)) / 100.0 if " " in normalize(brand) else 0.0
    best = max(ratio, typo, token * 0.9)
    return best, "typo variant" if best == typo and typo else "fuzzy"


def name_similarity(candidate_name: str | None, brand_names: list[str]) -> Signal:
    if not candidate_name or not candidate_name.strip():
        return Signal.missing("name", "Candidate has no display name")
    best_score, best_brand, how = 0.0, "", ""
    for b in brand_names:
        s, h = _pair_score(candidate_name, b)
        if s > best_score:
            best_score, best_brand, how = s, b, h
    features = detect_variant_features(candidate_name, best_brand) if best_brand else None
    evidence = features.describe() if features else []
    detail = (
        f"“{candidate_name}” vs “{best_brand}”: {best_score:.2f} ({how})" if best_brand else "No similarity to brand names"
    )
    return Signal(
        name="name",
        evaluated=True,
        score=best_score,
        detail=detail,
        evidence=evidence,
        data={"matched_brand_name": best_brand, "risky_terms": features.risky_added_terms if features else []},
    )


def handle_similarity(handle: str | None, brand_names: list[str], platform: str | None = None) -> Signal:
    local = handle_local_part(handle, platform)
    if not local:
        return Signal.missing("handle", "Candidate has no handle")
    best_score, best_brand, how = 0.0, "", ""
    for b in brand_names:
        s, h = _pair_score(local, b)
        if s > best_score:
            best_score, best_brand, how = s, b, h
    features = detect_variant_features(local, best_brand) if best_brand else None
    return Signal(
        name="handle",
        evaluated=True,
        score=best_score,
        detail=f"@{local} vs “{best_brand}”: {best_score:.2f} ({how})" if best_brand else "No similarity",
        evidence=features.describe() if features else [],
        data={"local_part": local, "risky_terms": features.risky_added_terms if features else []},
    )


# Reverse-DNS / platform boilerplate that says nothing about identity.
_PACKAGE_STOPWORDS = {
    "com", "net", "org", "io", "co", "app", "apps", "android", "ios", "mobile", "www", "inc", "ltd", "llc",
    "official", "free", "pro", "lite", "beta", "prod", "release",
}


def package_similarity(app_id: str | None, brand_names: list[str], official_app_ids: list[str] | None = None) -> Signal:
    """Similarity of a bundle/package identifier to the brand, plus reuse of an official package namespace.

    The candidate has already passed the official allowlist (exact app ID), so any match here is a
    *different* listing. A package ID is chosen by the developer, so on its own this is identity evidence only.
    """
    if not app_id or "." not in app_id:
        return Signal.missing("package", "Listing exposes no bundle/package identifier")
    segments = [s for s in app_id.lower().replace("-", "_").split(".") if s]
    best_score, best_brand, best_seg, how = 0.0, "", "", ""
    for seg in segments:
        if seg in _PACKAGE_STOPWORDS:
            continue
        for part in {seg, seg.replace("_", " "), seg.replace("_", "")}:
            for b in brand_names:
                s, h = _pair_score(part, b)
                if s > best_score:
                    best_score, best_brand, best_seg, how = s, b, part, h
    evidence: list[str] = []
    data: dict = {"segment": best_seg, "matched_brand_name": best_brand}
    # Same reverse-DNS namespace as an official app (e.g. com.brand.* ) but not on the allowlist.
    namespaces = {".".join(a.lower().split(".")[:2]) for a in (official_app_ids or []) if a.count(".") >= 2}
    ns = ".".join(segments[:2])
    if ns in namespaces:
        data["official_namespace"] = ns
        evidence.append(f"Uses the official package namespace “{ns}.*” but is not a registered official app")
        best_score = max(best_score, 0.85)
    if best_score >= 0.7 and best_brand:
        features = detect_variant_features(best_seg, best_brand)
        evidence.extend(f"Package ID: {e}" for e in features.describe())
        if not features.describe():
            evidence.append(f"Package ID contains “{best_seg}”, resembling “{best_brand}”")
    detail = f"{app_id}: segment “{best_seg}” vs “{best_brand}” {best_score:.2f} ({how})" if best_brand else f"{app_id}: no brand-like segment"
    return Signal(name="package", evaluated=True, score=best_score, detail=detail, evidence=evidence, data=data)
