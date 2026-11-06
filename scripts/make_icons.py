#!/usr/bin/env python3
"""Generate the PWA icons (no third-party libraries required).

The mark is the same idea as the favicon: a gold "N" on the near-black panel the
dashboard uses. Everything is drawn analytically with a 2x2 supersample, so the
result is anti-aliased without needing Pillow.

    python3 scripts/make_icons.py
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

BG = (13, 17, 23)          # ink-950 panel
GOLD = (245, 181, 65)      # gold-400
GOLD_DIM = (245, 181, 65, 0.55)

OUT = Path(__file__).resolve().parents[1] / "apps" / "web-dashboard" / "public" / "icons"


def _rounded_rect(x: float, y: float, x0: float, y0: float, x1: float, y1: float, r: float) -> bool:
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _dist_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy)


def _sample(x: float, y: float, inset: float) -> tuple[float, float, float, float]:
    """Return RGBA (0..1) at normalised coordinates for the icon artwork."""
    # `inset` shrinks the artwork into the safe area for maskable icons.
    if not _rounded_rect(x, y, 0.0, 0.0, 1.0, 1.0, 0.22):
        return (0.0, 0.0, 0.0, 0.0)
    sx = (x - 0.5) / (1.0 - 2 * inset) + 0.5
    sy = (y - 0.5) / (1.0 - 2 * inset) + 0.5

    r, g, b = (v / 255 for v in BG)
    # gold "N": two uprights plus a diagonal
    bar_w = 0.048
    in_left = abs(sx - 0.295) <= bar_w / 2 and 0.30 <= sy <= 0.70
    in_right = abs(sx - 0.705) <= bar_w / 2 and 0.30 <= sy <= 0.70
    on_diag = _dist_to_segment(sx, sy, 0.295, 0.31, 0.705, 0.69) <= 0.042
    if in_left or in_right or on_diag:
        r, g, b = (v / 255 for v in GOLD)
    # accent underline
    elif abs(sy - 0.775) <= 0.017 and 0.295 - 0.06 <= sx <= 0.705 + 0.06:
        a = 0.55
        r = r * (1 - a) + GOLD[0] / 255 * a
        g = g * (1 - a) + GOLD[1] / 255 * a
        b = b * (1 - a) + GOLD[2] / 255 * a
    return (r, g, b, 1.0)


def render(size: int, inset: float = 0.0, samples: int = 2) -> bytes:
    rows = []
    step = 1.0 / (size * samples)
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0.0
            for sy in range(samples):
                for sx in range(samples):
                    x = (px * samples + sx + 0.5) * step
                    y = (py * samples + sy + 0.5) * step
                    sr, sg, sb, sa = _sample(x, y, inset)
                    r += sr * sa
                    g += sg * sa
                    b += sb * sa
                    a += sa
            n = float(samples * samples)
            alpha = a / n
            if alpha > 0:
                row += bytes((round(r / a * 255), round(g / a * 255), round(b / a * 255), round(alpha * 255)))
            else:
                row += b"\x00\x00\x00\x00"
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + row for row in rows)
    return _png(size, size, raw)


def _png(width: int, height: int, raw: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    targets = [
        ("icon-192.png", 192, 0.0),
        ("icon-512.png", 512, 0.0),
        ("maskable-512.png", 512, 0.12),
        ("apple-touch-icon.png", 180, 0.0),
    ]
    for name, size, inset in targets:
        (OUT / name).write_bytes(render(size, inset))
        print(f"wrote {OUT / name} ({size}x{size})")


if __name__ == "__main__":
    main()
