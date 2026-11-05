#!/usr/bin/env python3
"""Checks that need no external tool: package contents and generated files. Platform CLIs run if present.

usage: check.py [comfyui | coze]   (check only that platform's dist folder)
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BANNED_NAMES = {".env", ".git", ".DS_Store", "__pycache__", ".venv", ".pytest_cache", ".ruff_cache", ".idea", ".vscode"}
BANNED_SUFFIXES = {".pyc", ".log", ".exe", ".so", ".dll", ".pem", ".key"}


def check_contents(package: Path) -> list[str]:
    problems = []
    for path in package.rglob("*"):
        if path.name in BANNED_NAMES or path.suffix in BANNED_SUFFIXES:
            problems.append(f"{path.relative_to(ROOT)}: not allowed in a package")
    return problems


N8N_PUBLISHED = {"package.json", "README.md", "LICENSE.md", "CHANGELOG.md"}


def check_n8n() -> list[str]:
    """dist/n8n must be a release build; its npm tarball (if packed) may hold only the compiled code and docs."""
    package = DIST / "n8n"
    if not package.exists():
        return ["n8n: run `python tools/n8n.py` first"]
    problems = []
    if "TEST_BUILD = false" not in (package / "nodes" / "shared" / "site.ts").read_text():
        problems.append("n8n: dist/n8n is a --base-url test build; rebuild without it")
    compiled = package / "dist"
    if compiled.exists():
        problems += check_contents(compiled)
    else:
        print("n8n: not compiled, run `python tools/n8n.py`")
    for tarball in DIST.glob("n8n-nodes-steadyrouter-*.tgz"):
        with tarfile.open(tarball) as archive:
            names = [n.removeprefix("package/") for n in archive.getnames()]
        problems += [f"{tarball.name}: {n} should not be published" for n in names
                     if not (n in N8N_PUBLISHED or n.startswith("dist/")) or Path(n).name in BANNED_NAMES]
    return problems


def check_comfyui() -> list[str]:
    """dist/comfyui must be a release build holding only the custom node's own files."""
    package = DIST / "comfyui"
    if not package.exists():
        return ["comfyui: run `python tools/build.py comfyui` first"]
    problems = check_contents(package)
    if "TEST_BUILD = False" not in (package / "_models.py").read_text():
        problems.append("comfyui: dist/comfyui is a --base-url test build; rebuild without it")
    allowed = {"__init__.py", "nodes.py", "key.py", "convert.py", "_models.py", "pyproject.toml", "README.md",
               "LICENSE", "requirements.txt", "icon.svg", ".gitignore", ".comfyignore", ".github", "web", "srclient"}
    problems += [f"comfyui: {p.name} should not be in the package" for p in package.iterdir() if p.name not in allowed]
    if 'PublisherId = ""' in (package / "pyproject.toml").read_text():
        print("comfyui: PublisherId is still empty in pyproject.toml (fill it in before publishing)")
    return problems


def check_coze() -> list[str]:
    """dist/coze must be a release build; every OpenAPI file must pass Coze's import rules (platforms/coze/validate.py)."""
    package = DIST / "coze"
    if not package.exists():
        return ["coze: run `python tools/build.py coze` first"]
    sys.path.insert(0, str(ROOT / "platforms" / "coze"))
    import validate
    import yaml

    conf = yaml.safe_load((ROOT / "platforms" / "coze" / "coze.yaml").read_text())
    problems = []
    config_ts = (package / "worker" / "src" / "config.ts").read_text()
    if "TEST_BUILD = false" not in config_ts:
        problems.append("coze: dist/coze is a --base-url test build; rebuild without it")
    if "observability" not in (package / "worker" / "wrangler.toml").read_text() or \
            "invocation_logs = false" not in (package / "worker" / "wrangler.toml").read_text():
        problems.append("coze: wrangler.toml must turn logs off (requests carry API keys)")
    files = sorted((package / "openapi").rglob("*.yaml"))
    if not files:
        problems.append("coze: no OpenAPI files")
    for path in files:
        doc = yaml.safe_load(path.read_text())
        problems += [f"coze: {path.relative_to(package)}: {p}" for p in validate.problems(doc, keep_days=conf["keep_days"])]
    if importlib.util.find_spec("openapi_spec_validator") is None:
        print("coze: openapi-spec-validator not installed, the general OpenAPI 3.0 check was skipped")
    return problems


def main() -> int:
    if sys.argv[1:] in (["comfyui"], ["coze"]):  # release jobs that build only one package
        problems = check_comfyui() if sys.argv[1] == "comfyui" else check_coze()
        print("check: ok" if not problems else "\n".join(problems))
        return 1 if problems else 0
    problems = check_n8n() + check_comfyui() + check_coze()
    for name in ("dify-model", "dify-tools"):
        package = DIST / name
        if not package.exists():
            problems.append(f"{name}: run `make build` first")
            continue
        problems += check_contents(package)
        if shutil.which("dify"):
            subprocess.run(["dify", "plugin", "package", str(package), "-o", str(DIST / f"{name}.difypkg")], check=True)
        else:
            print(f"{name}: dify CLI not installed, not packaged")
    for problem in problems:
        print(problem, file=sys.stderr)
    print("check: ok" if not problems else f"check: {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
