#!/usr/bin/env python3
"""Webflow Bridge — Firefox companion icon generator.

Canonical logo sources live in tools/logo_final/ (sky-blue rounded square
#2979FF + white "WB" in Arial Bold, confirmed 2026-09-09). This script copies
the required sizes into ff/extension/icons/ byte-identical to the reviewed
artwork. No Pillow / fonts / rendering needed.

Usage:
    python3 ff/extension/make_icons.py
"""
import os
import shutil
import sys

SRC = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),  # ff/extension
    "..", "..", "tools", "logo_final")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
SIZES = [16, 32, 48, 96, 128]


def main() -> None:
    src_dir = os.path.normpath(SRC)
    os.makedirs(OUT, exist_ok=True)
    for size in SIZES:
        src = os.path.join(src_dir, f"icon{size}.png")
        if not os.path.exists(src):
            raise SystemExit(f"missing source icon: {src}")
        dst = os.path.join(OUT, f"icon{size}.png")
        shutil.copy2(src, dst)
        print(f"copied {dst}")
    print("done")


if __name__ == "__main__":
    sys.exit(main())
