"""Look-alike search-term generation and variant-feature detection."""
from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz.distance import DamerauLevenshtein

from .normalize import compact, normalize, skeleton, tokens

# Terms impersonators commonly append to a brand name. Bounded and reviewed list.
RISKY_TERMS = {
    "support", "help", "helpdesk", "care", "customer", "service", "official", "team", "verify",
    "verification", "login", "signin", "secure", "security", "wallet", "refund", "claim", "giveaway",
    "airdrop", "bonus", "promo", "rewards", "reward", "gift", "free", "admin", "hq", "desk", "center",
    "centre", "recovery", "unlock", "update", "app", "pay", "payments", "crypto", "invest", "trading",
}
_SEARCH_SUFFIXES = ["support", "official", "help", "app", "login", "wallet"]


def generate_search_terms(name: str, aliases: list[str] | None = None, max_terms: int = 8) -> list[str]:
    """Bounded list of queries: base names first, then high-signal impersonation combinations.

    Public search endpoints are already fuzzy, so we query base names and a few risky combinations
    rather than enumerating every typo (which would multiply request volume without benefit).
    """
    bases: list[str] = []
    for value in [name, *(aliases or [])]:
        v = normalize(value)
        if v and v not in bases:
            bases.append(v)
    terms: list[str] = list(bases)
    # A spaced/joined variant of the primary name ("pay pal" ↔ "paypal") if it differs.
    primary = bases[0] if bases else ""
    joined = compact(primary)
    if joined and joined not in terms and len(joined) >= 4:
        terms.append(joined)
    for suffix in _SEARCH_SUFFIXES:
        if len(terms) >= max_terms:
            break
        t = f"{primary} {suffix}".strip()
        if primary and t not in terms:
            terms.append(t)
    return terms[:max_terms]


@dataclass
class VariantFeatures:
    exact: bool = False
    homoglyph: bool = False  # differs as typed but identical after confusable mapping
    separator_variation: bool = False  # identical once separators are removed
    typo_distance: int | None = None  # Damerau-Levenshtein distance on skeletons when 1..2
    contains_brand: bool = False
    added_terms: list[str] = field(default_factory=list)
    risky_added_terms: list[str] = field(default_factory=list)

    def describe(self) -> list[str]:
        out = []
        if self.exact:
            out.append("exact brand name")
        if self.homoglyph:
            out.append("character substitution (homoglyph/leetspeak)")
        if self.separator_variation:
            out.append("spacing/separator variation")
        if self.typo_distance:
            out.append(f"typo variant (edit distance {self.typo_distance})")
        if self.risky_added_terms:
            out.append("brand name plus impersonation terms: " + ", ".join(self.risky_added_terms))
        elif self.added_terms and self.contains_brand:
            out.append("brand name plus additional terms: " + ", ".join(self.added_terms[:4]))
        return out


def detect_variant_features(candidate: str, brand_name: str) -> VariantFeatures:
    f = VariantFeatures()
    if not candidate or not brand_name:
        return f
    c_norm, b_norm = normalize(candidate), normalize(brand_name)
    c_comp, b_comp = compact(candidate), compact(brand_name)
    c_skel, b_skel = skeleton(candidate), skeleton(brand_name)
    if not b_skel:
        return f

    f.exact = c_norm == b_norm
    if c_skel == b_skel and c_comp != b_comp:
        f.homoglyph = True
    if c_comp == b_comp and c_norm != b_norm:
        f.separator_variation = True

    brand_tokens = set(tokens(brand_name))
    cand_tokens = tokens(candidate)
    f.contains_brand = b_skel in c_skel
    if f.contains_brand:
        # Identify which tokens were added around the brand reference.
        extra = [t for t in cand_tokens if t not in brand_tokens and skeleton(t) not in b_skel]
        # Tokens glued to the brand ("paypalsupport") — recover the remainder of the skeleton.
        remainder = c_skel.replace(b_skel, " ").split()
        for r in remainder:
            if r and r not in extra and not any(skeleton(e) == r for e in extra):
                extra.append(r)
        f.added_terms = extra
        f.risky_added_terms = sorted({t for t in extra if skeleton(t) in {skeleton(r) for r in RISKY_TERMS}})
    else:
        # Typo detection on brand-sized windows that start at a word boundary of the candidate, so a
        # window cannot straddle unrelated words ("fast|paywal|let" is not a typo of "paypal").
        best = DamerauLevenshtein.distance(c_skel, b_skel)
        n = len(b_skel)
        starts, pos = [], 0
        for t in cand_tokens:
            starts.append(pos)
            pos += len(skeleton(t))
        for size in (n - 1, n, n + 1):
            if size <= 0 or size > len(c_skel):
                continue
            for i in starts:
                if i + size <= len(c_skel):
                    best = min(best, DamerauLevenshtein.distance(c_skel[i : i + size], b_skel))
        max_typos = 1 if n < 8 else 2  # short names: 2 edits reach unrelated words ("anypal" vs "paypal")
        if 0 < best <= max_typos and n >= 4:
            f.typo_distance = best
    return f
