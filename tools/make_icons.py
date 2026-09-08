#!/usr/bin/env python3
"""Webflow Bridge — Chrome/Edge extension icon generator.

The canonical logo sources live in tools/logo_final/ (sky-blue rounded
square #2979FF + white "WB" in Arial Bold, confirmed 2026-09-09). This
script copies the required sizes into extension/assets/icons/, keeping the
packaged icons byte-identical to the reviewed artwork. No Pillow / fonts /
rendering needed — the .png files in logo_final ARE the source of truth.

Usage:
    python3 tools/make_icons.py
    python3 tools/make_icons.py --out /some/dir --sizes 16 48
"""
import argparse
import os
import shutil

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_final")
DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "extension", "assets", "icons")
DEFAULT_SIZES = [16, 32, 48, 128]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--sizes", type=int, nargs="+", default=DEFAULT_SIZES)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    for size in a.sizes:
        src = os.path.join(SRC, f"icon{size}.png")
        if not os.path.exists(src):
            raise SystemExit(f"missing source icon: {src}")
        dst = os.path.join(a.out, f"icon{size}.png")
        shutil.copy2(src, dst)
        print(f"copied {dst}")
    print("done")


if __name__ == "__main__":
    main()
