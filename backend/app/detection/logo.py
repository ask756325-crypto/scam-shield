"""Perceptual logo hashing (pHash + dHash) with safe image decoding."""
from __future__ import annotations

import io

import imagehash
from PIL import Image, UnidentifiedImageError

from .signals import Signal

Image.MAX_IMAGE_PIXELS = 25_000_000  # decompression-bomb guard
ALLOWED_FORMATS = {"PNG", "JPEG", "GIF", "WEBP"}
HASH_BITS = 64


class InvalidImage(ValueError):
    pass


def load_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.verify()  # structural check
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise InvalidImage("File is not a valid image") from exc
    if fmt not in ALLOWED_FORMATS:
        raise InvalidImage(f"Unsupported image format: {fmt}")
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        img = bg
    return img.convert("RGB")


def compute_hashes(data: bytes) -> dict[str, str]:
    img = load_image(data)
    return {"phash": str(imagehash.phash(img)), "dhash": str(imagehash.dhash(img))}


def hash_similarity(a: str, b: str) -> float:
    """1.0 for identical hashes, 0.0 at ≥ 32 differing bits (≈ unrelated images)."""
    dist = int(imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b))
    return max(0.0, 1.0 - dist / (HASH_BITS / 2))


def logo_similarity(brand_hashes: dict[str, str] | None, candidate_hashes: dict[str, str] | None, reason: str = "") -> Signal:
    if not brand_hashes or not brand_hashes.get("phash"):
        return Signal.missing("logo", "Brand has no logo on file")
    if not candidate_hashes or not candidate_hashes.get("phash"):
        return Signal.missing("logo", reason or "Candidate image unavailable")
    p = hash_similarity(brand_hashes["phash"], candidate_hashes["phash"])
    d = hash_similarity(brand_hashes["dhash"], candidate_hashes["dhash"]) if brand_hashes.get("dhash") and candidate_hashes.get("dhash") else p
    # Require both hashes to agree: use the lower of the two to reduce chance collisions.
    score = float(min(p, d))
    pd = imagehash.hex_to_hash(brand_hashes["phash"]) - imagehash.hex_to_hash(candidate_hashes["phash"])
    return Signal(
        name="logo",
        evaluated=True,
        score=score,
        detail=f"Perceptual hash distance {pd}/64 (pHash sim {p:.2f}, dHash sim {d:.2f})",
        data={"phash_distance": int(pd), "candidate_phash": candidate_hashes["phash"]},
    )
