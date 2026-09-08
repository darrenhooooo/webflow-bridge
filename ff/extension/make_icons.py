#!/usr/bin/env python3
"""Webflow Bridge (Firefox companion) -- generate icons/icon{16,32,48,96}.png

Design: dark rounded-square tile with a minimal "bridge" glyph (two piers +
a deck) in the accent colour.  Drawn at 4x supersampling then downscaled so
small sizes stay clean.  Pillow only, no external resources.
"""
import os
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
SIZES = [16, 32, 48, 96]
SS = 4  # supersample factor


def draw_tile(size: int) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def px(v: float) -> int:
        return int(v * s)

    # background rounded square (deep navy)
    d.rounded_rectangle(
        [0, 0, s - 1, s - 1], radius=px(0.21), fill=(14, 19, 30, 255))
    # subtle inner sheen (top half lighter)
    d.rounded_rectangle(
        [px(0.02), px(0.02), s - px(0.02) - 1, s - px(0.02) - 1],
        radius=px(0.19), outline=(48, 66, 100, 255), width=px(0.015))
    # piers (two vertical rounded bars)
    d.rounded_rectangle(
        [px(0.20), px(0.44), px(0.34), px(0.88)], radius=px(0.07),
        fill=(125, 211, 252, 255))
    d.rounded_rectangle(
        [px(0.66), px(0.44), px(0.80), px(0.88)], radius=px(0.07),
        fill=(52, 211, 153, 255))
    # deck (horizontal rounded bar on top of the piers)
    d.rounded_rectangle(
        [px(0.10), px(0.34), px(0.90), px(0.50)], radius=px(0.08),
        fill=(226, 240, 254, 255))
    # highlight dots on deck ends
    d.ellipse([px(0.20), px(0.38), px(0.28), px(0.46)],
              fill=(56, 189, 248, 255))
    d.ellipse([px(0.72), px(0.38), px(0.80), px(0.46)],
              fill=(52, 211, 153, 255))

    img = img.resize((size, size), Image.LANCZOS)
    return img


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for size in SIZES:
        path = os.path.join(OUT, f"icon{size}.png")
        draw_tile(size).save(path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
