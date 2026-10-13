"""Text normalization and confusable-character skeletons.

`normalize()` produces readable, case-folded text without accents.
`skeleton()` collapses visually confusable characters (homoglyphs, leetspeak, `rn`→`m`) and drops
separators so that "PayPa1-Support", "pаypal support" (Cyrillic а) and "pay.pal support" compare equal
to "paypalsupport". Both sides of any comparison must be skeletonized.
"""
from __future__ import annotations

import re
import unicodedata

# Single-character confusables → canonical latin. Kept deliberately small and auditable.
_CONFUSABLES: dict[str, str] = {
    # Cyrillic
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "l", "ј": "j",
    "ѕ": "s", "ԁ": "d", "ӏ": "l", "к": "k", "м": "m", "т": "t", "в": "b", "н": "h", "ո": "n",
    # Greek
    "ο": "o", "α": "a", "ν": "v", "ρ": "p", "τ": "t", "ι": "l", "κ": "k", "ε": "e", "υ": "u",
    # Latin look-alikes and leetspeak. i / l / 1 / | all collapse to "l" (classic confusable class).
    "0": "o", "1": "l", "i": "l", "|": "l", "!": "l", "ı": "l", "3": "e", "4": "a", "5": "s",
    "7": "t", "8": "b", "@": "a", "$": "s", "ɡ": "g", "ß": "ss",
}
# Multi-character confusables applied after single-character mapping.
_MULTI = [("rn", "m"), ("vv", "w"), ("cl", "d")]

_SEPARATORS = re.compile(r"[\s._\-·•‧,:;/\\'\"`~+*()\[\]{}<>]+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_ZERO_WIDTH = re.compile("[​-‏⁠﻿]")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str | None) -> str:
    """NFKC, remove zero-width characters, case-fold, strip accents, collapse whitespace."""
    if not text:
        return ""
    text = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", text))
    text = strip_accents(text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str | None) -> list[str]:
    """Alphanumeric word tokens of the normalized text (separators split words)."""
    return [t for t in re.split(r"[^\w]+", normalize(text)) if t]


def skeleton(text: str | None) -> str:
    """Confusable-collapsed, separator-free form used for look-alike comparisons."""
    if not text:
        return ""
    # Map confusables before accent stripping/NFKC so Cyrillic/Greek letters are caught.
    raw = _ZERO_WIDTH.sub("", text).casefold()
    mapped = "".join(_CONFUSABLES.get(ch, ch) for ch in raw)
    mapped = strip_accents(unicodedata.normalize("NFKC", mapped))
    mapped = "".join(_CONFUSABLES.get(ch, ch) for ch in mapped)  # second pass after NFKC
    mapped = _NON_ALNUM.sub("", _SEPARATORS.sub("", mapped))
    for src, dst in _MULTI:
        mapped = mapped.replace(src, dst)
    return mapped


def compact(text: str | None) -> str:
    """Normalized text with separators removed but no confusable mapping."""
    return _NON_ALNUM.sub("", normalize(text))


def handle_local_part(handle: str | None, platform: str | None = None) -> str:
    """Strip platform suffixes/instances: 'acme-help.bsky.social' → 'acme-help', 'acme@mastodon.social' → 'acme'."""
    if not handle:
        return ""
    h = handle.strip().lstrip("@").lower()
    if "@" in h:  # mastodon acct user@instance
        h = h.split("@", 1)[0]
    for suffix in (".bsky.social", ".bsky.team"):
        if h.endswith(suffix):
            return h[: -len(suffix)]
    return h
