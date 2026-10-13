"""Deterministic synthetic logo images for the demo brand (generated with Pillow, no external assets)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSET_DIR = Path(__file__).resolve().parent / "assets"


def _official(fg=(31, 77, 58), bg=(244, 241, 234), accent=(76, 140, 130), shift=0, size=256) -> Image.Image:
    img = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(img)
    s = size / 256
    d.rounded_rectangle([24 * s, 24 * s, 232 * s, 232 * s], radius=36 * s, fill=fg)
    # Stylised "N" built from three bars + a teal accent dot.
    d.rectangle([(72 + shift) * s, 68 * s, (100 + shift) * s, 188 * s], fill=bg)
    d.rectangle([(156 + shift) * s, 68 * s, (184 + shift) * s, 188 * s], fill=bg)
    d.polygon([((72 + shift) * s, 68 * s), ((100 + shift) * s, 68 * s), ((184 + shift) * s, 188 * s), ((156 + shift) * s, 188 * s)], fill=bg)
    d.ellipse([186 * s, 44 * s, 214 * s, 72 * s], fill=accent)
    return img


def _unrelated_mountain(size=256) -> Image.Image:
    img = Image.new("RGB", (size, size), (220, 232, 240))
    d = ImageDraw.Draw(img)
    d.polygon([(10, 220), (100, 70), (190, 220)], fill=(70, 90, 110))
    d.polygon([(110, 220), (180, 110), (250, 220)], fill=(110, 130, 150))
    d.ellipse([180, 30, 230, 80], fill=(240, 200, 90))
    return img


def _unrelated_calc(size=256) -> Image.Image:
    img = Image.new("RGB", (size, size), (250, 250, 250))
    d = ImageDraw.Draw(img)
    for i in range(3):
        for j in range(3):
            d.rectangle([40 + i * 62, 60 + j * 62, 90 + i * 62, 110 + j * 62], fill=(60 + 40 * i, 60, 160 - 30 * j))
    return img


def _person(size=256) -> Image.Image:
    img = Image.new("RGB", (size, size), (200, 180, 220))
    d = ImageDraw.Draw(img)
    d.ellipse([88, 50, 168, 130], fill=(120, 90, 70))
    d.pieslice([48, 140, 208, 300], 180, 360, fill=(120, 90, 70))
    return img


GENERATORS = {
    "northvale-official.png": lambda: _official(),
    "northvale-copy.png": lambda: _official(),  # byte-different re-encode of an identical design
    "northvale-tinted.png": lambda: _official(fg=(36, 84, 64), accent=(90, 150, 140)),
    "northvale-shifted.png": lambda: _official(shift=6, accent=(200, 160, 60)),
    "mountain.png": _unrelated_mountain,
    "calculator.png": _unrelated_calc,
    "person.png": _person,
}


def ensure_assets() -> Path:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for name, gen in GENERATORS.items():
        path = ASSET_DIR / name
        if not path.exists():
            img = gen()
            if name == "northvale-copy.png":
                img = img.resize((240, 240)).resize((256, 256))  # simulate re-upload/compression
            img.save(path, format="PNG")
    return ASSET_DIR


def asset_path(name: str) -> Path | None:
    if name not in GENERATORS:
        return None
    ensure_assets()
    return ASSET_DIR / name
