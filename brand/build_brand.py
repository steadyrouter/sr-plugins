#!/usr/bin/env python3
"""logo.svg -> dist/brand: colour SVG, currentColor SVG, PNG sizes. PNGs need cairosvg."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT.parent / "dist" / "brand"
SIZES = (16, 32, 48, 64, 128, 256, 512)


def mono(svg: str) -> str:
    """The S alone, drawn in currentColor on a transparent background (models.dev, lobe-icons)."""
    out = re.sub(r"<rect[^>]*/>", "", svg)
    return re.sub(r'stroke="#[0-9a-fA-F]+"', 'stroke="currentColor"', out)


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    svg = (ROOT / "logo.svg").read_text()
    (DIST / "icon.svg").write_text(svg)
    (DIST / "icon-mono.svg").write_text(mono(svg))
    try:
        import cairosvg
    except (ImportError, OSError):
        print("cairosvg not available: SVG files only", file=sys.stderr)
        return 0
    for size in SIZES:
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(DIST / f"icon-{size}.png"),
                         output_width=size, output_height=size)
    print(f"wrote {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
