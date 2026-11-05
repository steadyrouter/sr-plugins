"""Runs tests/comfyui/comfy_nodes.py in a Python that has torch and ComfyUI's requirements.

Set SR_COMFYUI to a ComfyUI checkout and SR_COMFY_PYTHON to that venv's python.
Skipped when either is missing. The package contents are checked here without ComfyUI.
"""

import ast
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMFYUI = Path(os.environ.get("SR_COMFYUI", "/nonexistent"))
PYTHON = Path(os.environ.get("SR_COMFY_PYTHON", "/nonexistent"))


def built(tmp_path: Path) -> Path:
    sys.path.insert(0, str(ROOT / "tools"))
    import common
    from build import load_builder
    return load_builder("comfyui").build(common.load_context(), tmp_path / "comfyui")


@pytest.mark.skipif(not ((COMFYUI / "comfy_api").is_dir() and PYTHON.exists()), reason="SR_COMFYUI or SR_COMFY_PYTHON missing")
def test_comfyui_nodes():
    run = subprocess.run([str(PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/comfyui/comfy_nodes.py"],
                         cwd=ROOT, env={**os.environ, "COMFYUI": str(COMFYUI)}, check=False, capture_output=True,
                         text=True, timeout=110)
    assert run.returncode == 0, run.stdout[-6000:] + run.stderr[-2000:]
    assert " passed" in run.stdout and "failed" not in run.stdout


def test_package_contents(tmp_path):
    package = built(tmp_path)
    names = {p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file()}
    assert {"__init__.py", "nodes.py", "key.py", "convert.py", "_models.py", "pyproject.toml", "README.md", "LICENSE",
            "requirements.txt", "icon.svg", "web/steadyrouter.js", "srclient/client.py", ".comfyignore",
            ".github/workflows/publish_action.yml"} <= names
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
    meta = tomllib.loads((package / "pyproject.toml").read_text())
    assert meta["project"]["name"] == "steadyrouter"
    assert meta["project"]["urls"]["Repository"] == "https://github.com/steadyrouter/comfyui-steadyrouter"
    assert meta["project"]["urls"]["Repository"].startswith("https://github.com/")
    assert meta["tool"]["comfy"]["DisplayName"] == "SteadyRouter"
    for text in (package / "README.md").read_text(), (package / "web" / "steadyrouter.js").read_text():
        assert "{{" not in text


def test_registry_rules(tmp_path):
    """No eval / exec, no runtime installs or subprocesses, no network at import time."""
    package = built(tmp_path)
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(), str(path))
        for item in ast.walk(tree):
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Name):
                assert item.func.id not in {"eval", "exec", "compile", "__import__"}, f"{path}: {item.func.id}"
            if isinstance(item, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in item.names] if isinstance(item, ast.Import) else [item.module or ""]
                assert not any(m.split(".")[0] in {"subprocess", "pip", "ctypes"} for m in mods), f"{path}: {mods}"
    for path in package.rglob("*.js"):
        text = path.read_text()
        assert "eval(" not in text and "new Function" not in text and "fetch(" not in text
