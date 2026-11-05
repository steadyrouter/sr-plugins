"""Runs the TS client's tests (core/ts/tests) against the fake gateway.

Needs node and a folder with typescript and @types/node installed: set SR_NODE_TOOLCHAIN to it
(see the README). Skipped when either is missing.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fake_upstream import KEY, Fake

ROOT = Path(__file__).resolve().parent.parent
TOOLCHAIN = Path(os.environ.get("SR_NODE_TOOLCHAIN", "/nonexistent"))
TSC = TOOLCHAIN / "node_modules" / "typescript" / "bin" / "tsc"

pytestmark = pytest.mark.skipif(not (shutil.which("node") and TSC.exists()),
                                reason="node or SR_NODE_TOOLCHAIN missing")


def compile_ts(out: Path) -> None:
    run = subprocess.run(["node", str(TSC), "-p", str(ROOT / "core" / "ts" / "tsconfig.json"), "--outDir", str(out),
                          "--typeRoots", str(TOOLCHAIN / "node_modules" / "@types")],
                         check=False, capture_output=True, text=True, timeout=110)
    assert run.returncode == 0, run.stdout + run.stderr


def test_ts_client(tmp_path):
    compile_ts(tmp_path)
    fake = Fake()
    try:
        run = subprocess.run(["node", "--test", "--test-reporter=tap", str(tmp_path / "tests" / "client.test.js")],
                             env={**os.environ, "FAKE_BASE": fake.base, "FAKE_KEY": KEY},
                             check=False, capture_output=True, text=True, timeout=110)
    finally:
        fake.close()
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-2000:]
    passed = int(re.search(r"^# pass (\d+)", run.stdout, re.MULTILINE).group(1))
    assert passed >= 60, f"only {passed} TS tests ran"
