"""TF-IDF description similarity between candidates and a brand's own descriptive corpus."""
from __future__ import annotations

import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .normalize import normalize
from .signals import Signal

MIN_CHARS = 20


def _strip_brand_names(text: str, brand_names: list[str]) -> str:
    """Remove brand names so description similarity does not double-count the name signal."""
    out = normalize(text)
    for b in sorted({normalize(n) for n in brand_names if n}, key=len, reverse=True):
        if len(b) >= 2:
            out = re.sub(re.escape(b), " ", out)
    out = re.sub(r"https?://\S+", " ", out)
    return re.sub(r"\s+", " ", out).strip()


def description_similarities(brand_corpus: list[str], descriptions: list[str | None], brand_names: list[str]) -> list[Signal]:
    """Score each candidate description against the brand corpus (max cosine over corpus documents)."""
    corpus = [_strip_brand_names(d, brand_names) for d in brand_corpus if d and d.strip()]
    corpus = [c for c in corpus if len(c) >= MIN_CHARS]
    cleaned = [_strip_brand_names(d or "", brand_names) for d in descriptions]
    results: list[Signal] = []
    if not corpus:
        return [Signal.missing("description", "Brand profile has no description/keywords to compare") for _ in descriptions]
    valid_idx = [i for i, c in enumerate(cleaned) if len(c) >= MIN_CHARS]
    sims: dict[int, float] = {}
    if valid_idx:
        vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, stop_words="english", min_df=1)
        try:
            matrix = vec.fit_transform(corpus + [cleaned[i] for i in valid_idx])
            brand_m, cand_m = matrix[: len(corpus)], matrix[len(corpus) :]
            sim = cosine_similarity(cand_m, brand_m)
            for row, i in enumerate(valid_idx):
                sims[i] = float(sim[row].max())
        except ValueError:  # empty vocabulary (e.g. only stop words)
            pass
    for i, _ in enumerate(descriptions):
        if i in sims:
            results.append(
                Signal(name="description", evaluated=True, score=sims[i], detail=f"TF-IDF cosine similarity {sims[i]:.2f} to brand profile text (brand names excluded)")
            )
        else:
            results.append(Signal.missing("description", "Candidate description too short or empty"))
    return results
