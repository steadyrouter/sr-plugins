#!/usr/bin/env python3
"""Apply dist/pr-kits/<kit> onto a local clone: a branch with one local commit. Never pushes.

usage: apply_pr_kit.py <kit> <clone dir>
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(clone: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(clone), *args], check=True, capture_output=True, text=True).stdout


def git_config(clone: Path, key: str) -> str:
    reply = subprocess.run(["git", "-C", str(clone), "config", key], capture_output=True, text=True)
    return reply.stdout.strip()


def insert_before(path: Path, anchor: str, text: str) -> None:
    source = path.read_text()
    if text in source:
        raise SystemExit(f"{path}: already has {text.strip()!r}")
    match = re.search(anchor, source, flags=re.MULTILINE)
    if not match:
        raise SystemExit(f"{path}: anchor not found: {anchor}")
    path.write_text(source[: match.start()] + text + source[match.start():])


def json_dump(path: Path, data) -> None:
    trailing = "\n" if path.read_text().endswith("\n") else ""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + trailing)


def apply_edit(clone: Path, edit: dict) -> None:
    kind = edit["kind"]
    if kind == "before":
        insert_before(clone / edit["file"], edit["anchor"], edit["text"])
    elif kind == "before_glob":
        paths = sorted(clone.glob(edit["file"]))
        if not paths:
            raise SystemExit(f"no files for {edit['file']}")
        for path in paths:
            insert_before(path, edit["anchor"], edit["text"])
    elif kind == "catalog_version":
        # Same formula as the upstream catalog-source-sync test: sha256 of the sorted JSON body, first 16 hex.
        path = clone / edit["file"]
        source = path.read_text()
        body = json.loads(source)
        old = body.pop("version")
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        new = hashlib.sha256(canonical.encode()).hexdigest()[:16]
        if source.count(f'"{old}"') != 1:
            raise SystemExit(f"{path}: version string is not unique")
        path.write_text(source.replace(f'"{old}"', f'"{new}"'))
    elif kind == "json_toc":
        path = clone / edit["file"]
        data = json.loads(path.read_text())
        ids = [i["id"] for i in data]
        data.insert(ids.index(edit["before_id"]), edit["entry"])
        json_dump(path, data)
    else:
        raise SystemExit(f"unknown edit kind {kind}")


def edited_paths(kit: dict) -> list[str]:
    paths = {e["file"] for e in kit["edits"]}
    return sorted(f"/{p}" for p in paths)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    kit_dir = ROOT / "dist" / "pr-kits" / sys.argv[1]
    clone = Path(sys.argv[2]).resolve()
    kit = json.loads((kit_dir / "kit.json").read_text())
    if git(clone, "status", "--porcelain").strip():
        raise SystemExit(f"{clone}: has local changes")
    default = git(clone, "rev-parse", "--abbrev-ref", "origin/HEAD").strip().split("/", 1)[1]
    branch = kit["branch"]
    if git_config(clone, "core.sparseCheckout") == "true":
        git(clone, "sparse-checkout", "add", *kit["sparse"], *edited_paths(kit))
    git(clone, "checkout", "-q", default)
    if branch in git(clone, "branch", "--list", branch):
        git(clone, "branch", "-q", "-D", branch)
    git(clone, "checkout", "-q", "-b", branch)
    files = kit_dir / "files"
    for path in files.rglob("*"):
        if path.is_file():
            target = clone / path.relative_to(files)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(path, target)
    try:
        for edit in kit["edits"]:
            apply_edit(clone, edit)
    except SystemExit:
        git(clone, "reset", "-q", "--hard")
        git(clone, "clean", "-fdq")
        raise
    git(clone, "config", "user.name", "steadyrouter-dev")
    git(clone, "config", "user.email", "351740447+steadyrouter-dev@users.noreply.github.com")
    git(clone, "add", "--sparse", "-A")
    git(clone, "commit", "-q", "--no-verify", *(["--signoff"] if kit.get("signoff") else []), "-m", kit["commit"])
    print(git(clone, "log", "--oneline", "-1").strip())
    print(git(clone, "show", "--stat", "--format=", "HEAD").strip().splitlines()[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
