"""Detection pipeline: official-asset exclusion → signal extraction → scoring.

The same pipeline processes live, simulated and imported records.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..candidate import CandidateRecord
from .exclusion import ExclusionMatch, OfficialAccountRef, OfficialAppRef, OfficialIndex
from .logo import logo_similarity
from .publisher import publisher_signal
from .scam import scam_signal
from .scoring import Assessment, assess, merge_config
from .similarity import handle_similarity, name_similarity, package_similarity
from .text import description_similarities
from .urls import extract_urls, url_signal


@dataclass
class BrandContext:
    name: str
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    official_domains: list[str] = field(default_factory=list)
    logo_hashes: dict | None = None
    official_accounts: list[OfficialAccountRef] = field(default_factory=list)
    official_apps: list[OfficialAppRef] = field(default_factory=list)
    official_app_descriptions: list[str] = field(default_factory=list)
    additional_identifiers: list[str] = field(default_factory=list)  # reference text: similarity corpus only, never exclusion
    exclusion_rules: dict | None = None

    @property
    def names(self) -> list[str]:
        out = []
        for n in [self.name, *self.aliases]:
            if n and n not in out:
                out.append(n)
        return out

    @property
    def corpus(self) -> list[str]:
        docs = [self.description, " ".join(self.keywords), " ".join(self.additional_identifiers), *self.official_app_descriptions]
        return [d for d in docs if d and d.strip()]


@dataclass
class EvaluatedCandidate:
    record: CandidateRecord
    excluded: ExclusionMatch | None
    assessment: Assessment | None


def evaluate(
    brand: BrandContext,
    records: list[CandidateRecord],
    image_hashes: dict[str, dict | None] | None = None,
    image_errors: dict[str, str] | None = None,
    config_overrides: dict | None = None,
) -> list[EvaluatedCandidate]:
    """Evaluate records. `image_hashes` maps record key → {'phash','dhash'} (or None if unavailable)."""
    cfg = merge_config(config_overrides)
    index = OfficialIndex(brand.official_accounts, brand.official_apps, brand.official_domains, brand.exclusion_rules)
    image_hashes = image_hashes or {}
    image_errors = image_errors or {}
    results: list[EvaluatedCandidate] = []
    to_score: list[CandidateRecord] = []
    for r in records:
        m = index.match(r)
        if m:
            results.append(EvaluatedCandidate(r, m, None))
        else:
            to_score.append(r)

    # Official listings found in this scan extend the brand corpus (copied store text is a strong tell).
    official_docs = [e.record.description for e in results if e.record.description]
    desc_signals = description_similarities(brand.corpus + official_docs, [r.description for r in to_score], brand.names)
    for r, desc in zip(to_score, desc_signals):
        key = record_key(r)
        signals = [name_similarity(r.name, brand.names), desc]
        if r.kind == "account":
            signals.append(handle_similarity(r.handle, brand.names, r.source))
        else:
            signals.append(package_similarity(store_app_id(r), brand.names, [a.app_id for a in brand.official_apps]))
        hashes = r.image_hashes or image_hashes.get(key)
        signals.append(logo_similarity(brand.logo_hashes, hashes, image_errors.get(key, "Candidate image unavailable")))
        links = list(dict.fromkeys([*r.external_links, *extract_urls(r.description)]))
        signals.append(url_signal(links, brand.official_domains, brand.names))
        signals.append(scam_signal(r.name, r.description, " ".join(r.external_links)))
        signals.append(publisher_signal(r, brand.official_apps, brand.names))
        results.append(EvaluatedCandidate(r, None, assess(signals, r.kind, cfg)))
    return results


def store_app_id(r: CandidateRecord) -> str:
    """The store's own bundle/package ID (demo and imported records namespace `external_id`)."""
    m = r.metadata or {}
    return m.get("bundle_id") or m.get("package") or m.get("native_id") or r.external_id


def record_key(r: CandidateRecord) -> str:
    return f"{r.source}:{r.external_id}"
