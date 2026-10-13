"""Scam-indicator patterns in profile/listing text. Each category counts once (no keyword stuffing)."""
from __future__ import annotations

import re

from .normalize import normalize
from .signals import Signal

# (category, weight, pattern). Weights are heuristic and combined with noisy-OR across categories.
INDICATORS: list[tuple[str, float, re.Pattern]] = [
    ("crypto_giveaway", 0.55, re.compile(r"\b(giveaway|airdrop|double your|send \d+ ?(btc|eth|sol|usdt)|free (btc|eth|crypto|usdt|tokens?)|claim (your )?(reward|tokens?|bonus))\b")),
    ("credential_request", 0.6, re.compile(r"\b(verify (your )?(account|wallet|identity)|confirm (your )?(identity|details|account)|seed phrase|recovery phrase|secret phrase|private key|connect (your )?wallet|validate (your )?wallet)\b")),
    # Directed requests only: "send money" alone is ordinary product language for payment brands.
    ("payment_request", 0.45, re.compile(r"\b(refund (desk|department|team)|(processing|release|verification|unlock(ing)?) fee|(send|transfer|pay) (us|me) (the )?(money|payment|funds|crypto)|(pay|paid) (with|in|using) gift ?cards?|wire (the )?(money|funds|payment) to|pay (a|the) fee|unlock (your )?(account|funds))\b")),
    ("off_platform_contact", 0.35, re.compile(r"(\bdm (us|me|now)\b|\bwhats ?app\b|\btelegram\b|\bt\.me/|\bwa\.me/|\bsignal me\b|\bcontact (us )?on (telegram|whatsapp))")),
    ("support_impersonation", 0.3, re.compile(r"\b(customer (care|support|service)|support (team|desk|center|centre|line)|help ?desk|24/7 (support|help)|account recovery)\b")),
    ("urgency", 0.2, re.compile(r"\b(urgent(ly)?|immediately|act now|limited time|within 24 hours|account (is )?(suspended|locked|restricted))\b")),
    ("phone_number", 0.25, re.compile(r"(\+?\d[\d\s().-]{8,}\d)")),
    ("official_claim", 0.15, re.compile(r"\b(official|verified|authori[sz]ed) (account|page|support|partner|agent|team)\b")),
]


# Categories that are rarely present in legitimate brand profiles/listings. Weak categories (support
# wording, urgency, phone numbers, "official") are common in genuine app descriptions, so on their own
# they are capped below the corroboration threshold.
STRONG_CATEGORIES = {"crypto_giveaway", "credential_request", "payment_request", "off_platform_contact"}
WEAK_ONLY_CAP = 0.35


def scam_signal(*texts: str | None) -> Signal:
    joined = normalize(" \n ".join(t for t in texts if t))
    if not joined:
        return Signal.missing("scam", "No text available to analyze")
    matched: dict[str, str] = {}
    score_complement = 1.0
    for category, weight, pattern in INDICATORS:
        m = pattern.search(joined)
        if m:
            snippet = m.group(0).strip()
            if category == "phone_number" and sum(ch.isdigit() for ch in snippet) < 9:
                continue
            matched[category] = snippet
            score_complement *= 1.0 - weight
    score = 1.0 - score_complement
    strong = STRONG_CATEGORIES & set(matched)
    if matched and not strong:
        score = min(score, WEAK_ONLY_CAP)
    evidence = [f"{c.replace('_', ' ')}: “{s[:60]}”" for c, s in matched.items()]
    detail = f"{len(matched)} scam indicator categor{'y' if len(matched) == 1 else 'ies'} matched" if matched else "No scam indicators matched"
    if matched and not strong:
        detail += " (weak indicators only — common in legitimate listings)"
    return Signal(name="scam", evaluated=True, score=score, detail=detail, evidence=evidence, data={"categories": sorted(matched)})
