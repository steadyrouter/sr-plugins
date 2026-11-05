"""The upstream kits: what can be checked without the upstream toolchains."""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
KITS = ROOT / "dist" / "pr-kits"
sys.path.insert(0, str(ROOT / "tools"))
import apply_pr_kit


@pytest.fixture(scope="module", autouse=True)
def built():
    subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), "pr-kits"], check=True, capture_output=True)


def models_dev_files():
    return sorted((KITS / "models.dev" / "files" / "providers" / "steadyrouter" / "models").glob("*.toml"))


def test_models_dev_provider():
    data = tomllib.loads((KITS / "models.dev" / "files/providers/steadyrouter/provider.toml").read_text())
    assert data["npm"] == "@ai-sdk/openai-compatible" and data["api"] == "https://api.steadyrouter.com/v1"
    assert "aff=" not in data["doc"] and data["env"] == ["STEADYROUTER_API_KEY"]


def test_models_dev_models_are_override_only_without_cost():
    catalog = {m["name"] for m in json.loads((ROOT / "catalog" / "catalog.json").read_text())["models"]}
    files = models_dev_files()
    assert 20 <= len(files) <= 30
    for path in files:
        data = tomllib.loads(path.read_text())
        assert data["schema"] == 2 and "/" in data["base_model"]
        assert "cost" not in data and "id" not in data
        assert path.stem in catalog


def test_models_dev_logo_rules():
    logo = (KITS / "models.dev" / "files/providers/steadyrouter/logo.svg").read_text()
    assert "currentColor" in logo and "viewBox" in logo
    assert not re.search(r"#[0-9a-fA-F]{3,6}|<rect|width=|height=|<script", logo.replace("stroke-width", ""))


def test_models_dev_base_models_exist_in_clone():
    clone = ROOT.parent.parent / "t96-upstream" / "models.dev"
    if not clone.exists():
        pytest.skip("no local clone")
    listed = subprocess.run(["git", "-C", str(clone), "ls-tree", "-r", "--name-only", "HEAD", "models"],
                            capture_output=True, text=True, check=True).stdout.split()
    for path in models_dev_files():
        base = tomllib.loads(path.read_text())["base_model"]
        assert f"models/{base}.toml" in listed, base


def test_cherry_entry_is_valid_json_and_matches_source():
    kit = json.loads((KITS / "cherry-studio" / "kit.json").read_text())
    text = next(e["text"] for e in kit["edits"] if e["file"].endswith("providers.json"))
    entry = json.loads(text.strip().rstrip(","))
    assert entry["id"] == "steadyrouter" and "aff=" in entry["metadata"]["website"]["apiKey"]
    source = (KITS / "cherry-studio/files/packages/provider-registry/src/providers/steadyrouter.ts").read_text()
    for endpoint, config in entry["endpointConfigs"].items():
        assert f"'{endpoint}'" in source and config["baseUrl"] in source


def test_lobehub_lists_gemini_through_chat_and_no_video():
    source = (KITS / "lobehub/files/packages/model-bank/src/aiModels/steadyrouter.ts").read_text()
    assert "type: 'image'" in source and "type: 'video'" not in source
    assert "id: 'gemini-3.1-flash-image:image'" in source
    assert "pricing" not in source


def test_lobe_icons_toc_entry():
    kit = json.loads((KITS / "lobe-icons" / "kit.json").read_text())
    toc = next(e for e in kit["edits"] if e["kind"] == "json_toc")
    assert toc["entry"]["id"] == "SteadyRouter" and toc["entry"]["param"]["hasCombine"] is False


@pytest.mark.parametrize("name", ["dify-model", "dify-tools", "models.dev", "cherry-studio", "lobehub", "lobe-icons"])
def test_pr_bodies_filled(name):
    body = (KITS / name / "PR.md").read_text()
    assert "{{" not in body and "steadyrouter" in body.lower()


def test_insert_before_refuses_missing_anchor_and_duplicates(tmp_path):
    path = tmp_path / "f.ts"
    path.write_text("a\nb\n")
    apply_pr_kit.insert_before(path, r"^b", "x\n")
    assert path.read_text() == "a\nx\nb\n"
    with pytest.raises(SystemExit):
        apply_pr_kit.insert_before(path, r"^zzz", "y\n")
    with pytest.raises(SystemExit):
        apply_pr_kit.insert_before(path, r"^b", "x\n")
