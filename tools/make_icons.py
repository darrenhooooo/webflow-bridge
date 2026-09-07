#!/usr/bin/env python3
"""Generate the Webflow Bridge extension icons.

Design: a rounded-square dark background (#0A0A0A) with a single bold cyan
(#00B8D4) glyph — two vertical pylons joined by a suspension arc (a geometric
"bridge" mark). Flat, no gradients, no text. Readable down to 16px.

Usage:
    uv run --python 3.11 python tools/make_icons.py
    uv run --python 3.11 python tools/make_icons.py --out /some/dir --sizes 16 48

Dependencies: Pillow only. Icons are rendered from a 4x supersampled master
canvas and downscaled with LANCZOS so edges stay clean at every size.
"""

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
BG = "#0A0A0A"        # dark rounded-square background
CYAN = "#00B8D4"      # glyph colour (single bold bridge/arc mark)

# ---------------------------------------------------------------------------
# Design geometry, in logical units on a 128x128 grid (master is 4x this).
# Keep values in whole/quarter units so everything scales cleanly.
#
# Glyph: two vertical pylons joined by a suspension arc (top half of an
# ellipse). The arc is rendered as a smooth constant-width tube whose end
# caps sit centred on the pylon centres, so the outer silhouette runs flush:
# straight pylon edge x=18 curves up into the arch with no step or bulge.
# ---------------------------------------------------------------------------
CANVAS = 128.0
MASTER_SCALE = 4                      # supersampling factor
CORNER_RADIUS = 28                    # rounded-square corner radius (logical)

ARC_WIDTH = 16.0                      # tube/arc stroke width (logical)
ARC_CX = 64.0                         # ellipse centre x
ARC_CY = 46.0                         # ellipse centre y (endpoint height)
ARC_RX = 38.0                         # ellipse half-width (ends at x 26 / 102)
ARC_RY = 24.0                         # ellipse half-height (apex y = 46-24-8)
ARC_STEPS = 240                       # dots around the top half (>=120 is smooth)

PYLON_SPANS = ((18.0, 34.0), (94.0, 110.0))  # left/right pylon x-spans (width 16)
PYLON_TOP = 36.0                      # start above the arc seam so the joint is solid
PYLON_BOTTOM = 110.0

SIZES = (16, 32, 48, 128)


def _logical_to_master(v):
    """Logical 128-grid coordinate -> master canvas pixel coordinate."""
    return v * MASTER_SCALE


def draw_glyph(img: Image.Image) -> None:
    """Draw the rounded-square background + bridge glyph on `img` (master px)."""
    d = ImageDraw.Draw(img)
    S = _logical_to_master

    # Background: rounded square, transparent corners.
    d.rounded_rectangle(
        [0, 0, img.width - 1, img.height - 1],
        radius=S(CORNER_RADIUS),
        fill=BG,
    )

    # Suspension arc: stamp small filled circles along the top half of the
    # ellipse (a = pi -> west end, a = 0 -> east end). PIL's own thick-arc
    # strokes are axis-stamped and lumpy; dot-tube keeps the width exact.
    r = S(ARC_WIDTH) / 2.0
    cx, cy, rx, ry = S(ARC_CX), S(ARC_CY), S(ARC_RX), S(ARC_RY)
    for i in range(ARC_STEPS + 1):
        a = math.pi * i / ARC_STEPS
        x = cx + rx * math.cos(a)
        y = cy - ry * math.sin(a)
        d.ellipse([x - r, y - r, x + r, y + r], fill=CYAN)

    # Two vertical pylons running down from the arc ends.
    for x0, x1 in PYLON_SPANS:
        d.rectangle(
            [S(x0), S(PYLON_TOP), S(x1), S(PYLON_BOTTOM)],
            fill=CYAN,
        )


def make_icon(size: int, master: Image.Image) -> Image.Image:
    """Downscale the master render to the requested icon size."""
    return master.resize((size, size), Image.LANCZOS)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "extension" / "assets" / "icons",
        help="output directory (default: <repo>/extension/assets/icons)",
    )
    ap.add_argument(
        "--sizes",
        type=int,
        nargs="*",
        default=list(SIZES),
        help="icon sizes to emit (default: 16 32 48 128)",
    )
    args = ap.parse_args()

    master_px = int(CANVAS * MASTER_SCALE)
    master = Image.new("RGBA", (master_px, master_px), (0, 0, 0, 0))
    draw_glyph(master)

    args.out.mkdir(parents=True, exist_ok=True)
    for size in args.sizes:
        icon = make_icon(size, master)
        path = args.out / f"icon{size}.png"
        icon.save(path)
        print(f"wrote {path} ({icon.size[0]}x{icon.size[1]})")

    # Optional: preview renders (not written to the repo output dir) for
    # eyeballing legibility at small sizes.
    if args.sizes and min(args.sizes) <= 32:
        print("tip: sizes <= 32px look best on a light background in a store UI")


if __name__ == "__main__":
    main()
