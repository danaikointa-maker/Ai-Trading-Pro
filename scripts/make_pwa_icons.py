"""Generate the PWA icons as PNGs without any image library.

The dashboard needs real PNG icons (iOS ignores SVG for the home-screen icon), and
checking a hand-made binary into git is not reviewable. So the icon is drawn here with
numpy and zlib: a dark rounded tile with a gold rising-chart glyph — the same shape at
every size, so the 192px and 512px icons can never drift apart.

    .venv/bin/python scripts/make_pwa_icons.py

Re-run it after changing the design; the output is deterministic (no timestamps), so a
rebuild produces byte-identical files and no spurious diff.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

PUBLIC = Path(__file__).resolve().parents[1] / "apps" / "web-dashboard" / "public"
INK = (0x07, 0x09, 0x0C)
GOLD = (0xF5, 0xB5, 0x41)
GOLD_DIM = (0x8A, 0x63, 0x1C)
SUPERSAMPLE = 4


def _rounded_rect_mask(size: int, radius_ratio: float) -> np.ndarray:
    """1 inside a rounded square, 0 outside, antialiased by supersampling."""
    big = size * SUPERSAMPLE
    ys, xs = np.mgrid[0:big, 0:big]
    r = radius_ratio * big
    # distance from the nearest corner centre, clamped to the straight edges
    cx = np.clip(xs, r, big - r)
    cy = np.clip(ys, r, big - r)
    inside = ((xs - cx) ** 2 + (ys - cy) ** 2) <= r ** 2
    return inside.reshape(size, SUPERSAMPLE, size, SUPERSAMPLE).mean(axis=(1, 3))


def _bar(mask: np.ndarray, x0: float, x1: float, y0: float, y1: float) -> np.ndarray:
    """Rectangle coverage in unit coordinates (0..1), supersampled like the tile."""
    size = mask.shape[0]
    big = size * SUPERSAMPLE
    ys, xs = np.mgrid[0:big, 0:big]
    ux, uy = (xs + 0.5) / big, (ys + 0.5) / big
    inside = (ux >= x0) & (ux <= x1) & (uy >= y0) & (uy <= y1)
    return inside.reshape(size, SUPERSAMPLE, size, SUPERSAMPLE).mean(axis=(1, 3))


def draw(size: int, *, bleed: bool, glyph_scale: float = 1.0) -> np.ndarray:
    """RGBA icon: dark tile, three gold bars of rising height plus a trend line."""
    mask = np.ones((size, size)) if bleed else _rounded_rect_mask(size, 0.22)
    rgb = np.zeros((size, size, 3), dtype=np.float64)
    rgb[:] = INK

    # glyph geometry in unit space, shrunk around the centre for maskable padding
    def gx(v: float) -> float:
        return 0.5 + (v - 0.5) * glyph_scale

    bars = [(0.24, 0.22), (0.42, 0.38), (0.60, 0.62)]
    for left, height in bars:
        x0, x1 = gx(left), gx(left + 0.12)
        y0, y1 = gx(0.76 - height), gx(0.76)
        cov = _bar(mask, x0, x1, y0, y1)[..., None]
        rgb = rgb * (1 - cov) + np.array(GOLD_DIM) * cov

    # the last, tallest bar is the bright one
    x0, x1 = gx(0.60), gx(0.72)
    cov = _bar(mask, x0, x1, gx(0.14), gx(0.76))[..., None]
    rgb = rgb * (1 - cov) + np.array(GOLD) * cov

    alpha = mask
    out = np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype(np.uint8)
    return out


def write_png(path: Path, rgba: np.ndarray) -> None:
    height, width = rgba.shape[:2]
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(height))
    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


def main() -> int:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    targets = [
        ("icon-192.png", 192, False, 1.0),
        ("icon-512.png", 512, False, 1.0),
        ("icon-maskable-512.png", 512, True, 0.78),   # full bleed + safe-zone padding
        ("apple-touch-icon.png", 180, True, 1.0),      # iOS wants an opaque square
    ]
    for name, size, bleed, scale in targets:
        write_png(PUBLIC / name, draw(size, bleed=bleed, glyph_scale=scale))
        print(f"{name}: {size}x{size} -> {PUBLIC / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
