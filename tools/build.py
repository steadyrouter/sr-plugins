#!/usr/bin/env python3
"""Assemble platform packages into dist/<platform>. --base-url points a test build at a fake gateway."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, load_context

PLATFORMS = ["dify-model", "dify-tools", "pr-kits", "n8n", "comfyui", "coze"]


def load_builder(platform: str):
    path = ROOT / "platforms" / platform / "build.py"
    spec = importlib.util.spec_from_file_location(f"build_{platform.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=[*PLATFORMS, "all"])
    parser.add_argument("--base-url")
    args = parser.parse_args()
    ctx = load_context(args.base_url)
    for platform in PLATFORMS if args.platform == "all" else [args.platform]:
        if not (ROOT / "platforms" / platform / "build.py").exists():
            print(f"{platform}: not written yet")
            continue
        print(f"{platform}: {load_builder(platform).build(ctx)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
