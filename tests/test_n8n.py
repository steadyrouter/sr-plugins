"""Builds a test copy of the n8n package pointed at the fake gateway, compiles it with the n8n CLI and runs
tests/n8n/node.test.cjs against it.

Needs node and SR_NODE_TOOLCHAIN (a folder with the package's dev dependencies installed, see
the README). Skipped when either is missing.
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fake_upstream import KEY, Fake

ROOT = Path(__file__).resolve().parent.parent
TOOLCHAIN = Path(os.environ.get("SR_NODE_TOOLCHAIN", "/nonexistent"))
CLI = TOOLCHAIN / "node_modules" / ".bin" / "n8n-node"

pytestmark = pytest.mark.skipif(not (shutil.which("node") and CLI.exists()), reason="node or SR_NODE_TOOLCHAIN missing")


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def build_test_package(base: str, out: Path) -> Path:
    sys.path.insert(0, str(ROOT / "tools"))
    import common
    builder = load(ROOT / "platforms" / "n8n" / "build.py", "build_n8n")
    package = builder.build(common.load_context(base), out)
    (package / "node_modules").symlink_to(TOOLCHAIN / "node_modules")
    run = subprocess.run([str(CLI), "build"], cwd=package, check=False, capture_output=True, text=True, timeout=110)
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
    return package


def test_n8n_node(tmp_path):
    fake = Fake()
    try:
        package = build_test_package(fake.base, tmp_path / "n8n")
        site = (package / "nodes" / "shared" / "site.ts").read_text()
        assert "TEST_BUILD = true" in site
        run = subprocess.run(["node", "--test", "--test-reporter=tap", str(ROOT / "tests" / "n8n" / "node.test.cjs")],
                             env={**os.environ, "FAKE_BASE": fake.base, "FAKE_KEY": KEY, "PKG": str(package)},
                             check=False, capture_output=True, text=True, timeout=110)
    finally:
        fake.close()
    assert run.returncode == 0, run.stdout[-5000:] + run.stderr[-2000:]
    passed = int(re.search(r"^# pass (\d+)", run.stdout, re.MULTILINE).group(1))
    assert passed >= 20, f"only {passed} n8n node tests ran"
