#!/usr/bin/env python3
"""Compile, lint and pack dist/n8n with the n8n CLI.

usage: SR_NODE_TOOLCHAIN=<folder with the dev dependencies installed> python tools/n8n.py [--base-url URL] [--pack]

The toolchain folder is linked in as node_modules, so nothing is installed into the package itself.
--pack writes the npm tarball to dist/ (what `npm publish` would upload); release builds only.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import load_builder
from common import DIST, load_context


def run(cmd: list[str], cwd: Path) -> None:
    print("$", " ".join(cmd), flush=True)
    done = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
    output = (done.stdout + done.stderr).replace("\r", "\n")
    lines = [line for line in output.splitlines() if line.strip() and "Building TypeScript files" not in line]
    print("\n".join(lines[-40:]))
    if done.returncode:
        raise SystemExit(f"failed: {' '.join(cmd)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url")
    parser.add_argument("--pack", action="store_true")
    args = parser.parse_args()
    toolchain = Path(os.environ.get("SR_NODE_TOOLCHAIN", ""))
    if not (toolchain / "node_modules" / ".bin" / "n8n-node").exists():
        raise SystemExit("set SR_NODE_TOOLCHAIN to a folder where the package's devDependencies are installed")
    if args.pack and args.base_url:
        raise SystemExit("test builds are never packed")
    package = load_builder("n8n").build(load_context(args.base_url))
    (package / "node_modules").symlink_to(toolchain / "node_modules")
    cli = str(package / "node_modules" / ".bin" / "n8n-node")
    run([cli, "build"], package)
    run([cli, "lint"], package)
    if args.pack:
        if not shutil.which("npm"):
            raise SystemExit("npm not found")
        run(["npm", "pack", "--ignore-scripts", "--pack-destination", str(DIST)], package)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
