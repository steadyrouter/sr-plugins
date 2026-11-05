"""Coze: the generated OpenAPI files, the import-rule checker, and the Worker's TypeScript.

The Worker itself runs end to end in tests/e2e/coze_e2e.py (wrangler dev, local R2, fake gateway).
"""

import copy
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "platforms" / "coze"))
import common  # noqa: E402
import validate  # noqa: E402

TOOLCHAIN = Path(os.environ.get("SR_NODE_TOOLCHAIN", "/nonexistent"))
TSC = TOOLCHAIN / "node_modules" / "typescript" / "bin" / "tsc"
CONF = yaml.safe_load((ROOT / "platforms" / "coze" / "coze.yaml").read_text())
DOMESTIC = {"nano_banana", "seedream", "tongyi_image", "seedance", "wan_video", "vidu"}


def load_builder():
    spec = importlib.util.spec_from_file_location("build_coze", ROOT / "platforms" / "coze" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    out = tmp_path_factory.mktemp("coze")
    load_builder().build(common.load_context(), out=out / "coze")
    return out / "coze"


def docs(release):
    return {(p.parent.name, p.stem): yaml.safe_load(p.read_text()) for p in (release / "openapi").rglob("*.yaml")}


def enums(doc, field):
    found = []
    for item in doc["paths"].values():
        for op in item.values():
            props = op["requestBody"]["content"]["application/json"]["schema"]["properties"]
            if field in props:
                found += props[field].get("enum", [])
    return found


def test_plugin_set(release):
    assert set(docs(release)) == {
        ("com", "steadyrouter"), ("com", "nano_banana"), ("com", "gpt_image"), ("com", "seedream"), ("com", "seedance"),
        ("com", "tongyi"),
        ("cn", "steadyrouter"), ("cn", "nano_banana"), ("cn", "seedream"), ("cn", "seedance"), ("cn", "tongyi"),
    }


def test_every_file_passes_the_import_rules(release):
    for name, doc in docs(release).items():
        assert validate.problems(doc, keep_days=CONF["keep_days"]) == [], name


def test_models_follow_region_and_family(release):
    catalog = {m["name"]: m for m in common.load_context().catalog["models"]}
    all_docs = docs(release)
    for (region, plugin), doc in all_docs.items():
        models = enums(doc, "model")
        assert models, (region, plugin)
        assert not set(models) & set(CONF["exclude"])
        if region == "cn":
            assert {catalog[m]["family"] for m in models} <= DOMESTIC, plugin
    assert {catalog[m]["family"] for m in enums(all_docs[("com", "gpt_image")], "model")} == {"gpt_image"}
    assert any(m.startswith("flux") for m in enums(all_docs[("com", "steadyrouter")], "model"))
    assert not any(m.startswith(("flux", "gpt-image", "grok")) for m in enums(all_docs[("cn", "steadyrouter")], "model"))
    tongyi = all_docs[("com", "tongyi")]
    assert sorted(op["post"]["operationId"] for op in tongyi["paths"].values()) == ["check_video", "generate_image", "submit_video"]
    assert sorted(all_docs[("com", "seedance")]["paths"]) == ["/coze/com/v1/videos", "/coze/com/v1/videos/status"]


def test_texts(release):
    plugins = {p["id"]: p for p in CONF["plugins"]}
    for (region, plugin), doc in docs(release).items():
        desc = doc["info"]["description"]
        code = CONF["regions"][region].get("aff") or plugins[plugin]["aff"]
        assert f"aff={code}" in desc and "10" in desc and "15" in desc
        assert doc["servers"] == [{"url": CONF["api_base"]}]
        for path in doc["paths"]:
            assert path.startswith(f"/coze/{region}/v1/")
        if region == "cn":
            assert "私有变量" in desc
        # the model's options are in its description too: Coze gives the LLM descriptions, not enums
        for item in doc["paths"].values():
            props = item["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]
            if "model" in props:
                assert all(m in props["model"]["description"] for m in props["model"]["enum"])


def test_release_config(release):
    config = (release / "worker" / "src" / "config.ts").read_text()
    assert "TEST_BUILD = false" in config and '"https://api.steadyrouter.com"' in config
    toml = (release / "worker" / "wrangler.toml").read_text()
    assert "workers_dev = false" in toml and "invocation_logs = false" in toml and f'bucket_name = "{CONF["bucket"]}"' in toml
    assert "FILE_NAME_SECRET" not in config


def test_test_build_points_at_the_fake(tmp_path):
    load_builder().build(common.load_context("http://127.0.0.1:9"), out=tmp_path / "coze")
    config = (tmp_path / "coze" / "worker" / "src" / "config.ts").read_text()
    assert "TEST_BUILD = true" in config and "http://127.0.0.1:9" in config


GOOD = {
    "openapi": "3.0.1",
    "info": {"title": "T", "version": "0.1.0",
             "description": "x https://www.steadyrouter.com/sign-up?aff=X 10 minutes 15 days"},
    "servers": [{"url": "https://files.example.com"}],
    "paths": {"/a": {"post": {
        "operationId": "a", "summary": "s",
        "parameters": [{"name": "Authorization", "in": "header", "required": True, "schema": {"type": "string"}}],
        "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {
            "p": {"type": "string"}}}}}},
        "responses": {"200": {"description": "OK", "content": {"application/json": {"schema": {"type": "object", "properties": {
            "u": {"type": "string", "format": "image_url"}}}}}}},
    }}},
}


def broken(change):
    doc = copy.deepcopy(GOOD)
    change(doc)
    return validate.problems(doc, keep_days=15)


def op(doc):
    return doc["paths"]["/a"]["post"]


@pytest.mark.parametrize("change, expect", [
    (lambda d: d["servers"].append({"url": "https://b.example.com"}), "only one server"),
    (lambda d: d["info"].update(description=""), "description of info"),
    (lambda d: op(d).pop("summary"), "summary is required"),
    (lambda d: op(d).pop("operationId"), "operationID is required"),
    (lambda d: op(d)["parameters"].append({"name": "o", "in": "query", "schema": {"type": "object", "properties": {"a": {"type": "string"}}}}),
     "cannot be 'object'"),
    (lambda d: op(d)["parameters"].append({"name": "q", "in": "query", "schema": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}}),
     "cannot be 'object' or 'array'"),
    (lambda d: op(d)["requestBody"]["content"]["application/json"]["schema"].update(type="array", items={"type": "string"}),
     "only supports 'object'"),
    (lambda d: op(d)["requestBody"]["content"].update({"application/x-yaml": {"schema": {"type": "object"}}}),
     "one media type"),
    (lambda d: op(d)["responses"].update({"201": op(d)["responses"]["200"]}), "only supports '200'"),
    (lambda d: op(d)["responses"]["200"]["content"]["application/json"]["schema"]["properties"].update(
        n={"type": "number", "format": "double"}), "format 'double' is invalid"),
    (lambda d: op(d)["requestBody"]["content"]["application/json"]["schema"]["properties"].update(
        u={"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}), "oneOf"),
    (lambda d: op(d)["requestBody"]["content"]["application/json"]["schema"]["properties"].update(o={"type": "object"}),
     "object without properties"),
    (lambda d: op(d)["parameters"][0]["schema"].update(default="Bearer sk-x"), "must not carry a default"),
    (lambda d: op(d)["parameters"].clear(), "Authorization header"),
    (lambda d: d["servers"][0].update(url="https://sr-coze.someone.workers.dev"), "workers.dev"),
    (lambda d: d["info"].update(description="no link here, 10, 15"), "get-a-key link"),
])
def test_checker_catches(change, expect):
    assert validate.problems(copy.deepcopy(GOOD), keep_days=15) == []
    assert any(expect in p for p in broken(change)), broken(change)


@pytest.mark.skipif(not (shutil.which("node") and TSC.exists()), reason="node or SR_NODE_TOOLCHAIN missing")
def test_worker_typechecks(release):
    run = subprocess.run(["node", str(TSC), "-p", str(release / "worker" / "tsconfig.json")],
                         check=False, capture_output=True, text=True, timeout=110)
    assert run.returncode == 0, run.stdout + run.stderr


LIFT_TEST = r"""
const assert = require('node:assert');
const { FetchTransport } = require('./transport.js');
const big = Buffer.alloc(150000, 7);
const b64 = big.toString('base64');
const t = new FetchTransport('k');
// b64_json reply
let text = JSON.stringify({ data: [{ b64_json: b64 }] });
let lifted = t.lift(text);
assert.ok(lifted.length < 200 && lifted.includes('__srlift_0__'), lifted);
assert.deepStrictEqual(Buffer.from(t.decode(JSON.parse(lifted).data[0].b64_json)), big);
// markdown data URI in a chat reply, next to a short one that stays in place
text = JSON.stringify({ choices: [{ message: { content: `a ![x](data:image/png;base64,${b64}) b ![y](data:image/png;base64,AAAA)` } }] });
lifted = t.lift(text);
const content = JSON.parse(lifted).choices[0].message.content;
assert.ok(content.includes('data:image/png;base64,__srlift_1__)') && content.includes('base64,AAAA)'), content);
assert.deepStrictEqual(Buffer.from(t.decode('__srlift_1__')), big);
// a run holding a JSON escape is left alone and still parses
text = '{"data":[{"b64_json":"' + b64.slice(0, 5000) + '\\/' + b64.slice(5000, 9000) + '"}]}';
assert.strictEqual(t.lift(text), text);
// unknown placeholder: unreadable, not a crash
assert.strictEqual(t.decode('__srlift_99__'), null);
console.log('lift ok');
"""


@pytest.mark.skipif(not (shutil.which("node") and TSC.exists()), reason="node or SR_NODE_TOOLCHAIN missing")
def test_transport_lift(release, tmp_path):
    out = tmp_path / "js"
    run = subprocess.run(["node", str(TSC), "-p", str(release / "worker" / "tsconfig.json"), "--noEmit", "false",
                          "--outDir", str(out), "--module", "commonjs", "--moduleResolution", "node"],
                         check=False, capture_output=True, text=True, timeout=110)
    assert run.returncode == 0, run.stdout + run.stderr
    (out / "lift.test.js").write_text(LIFT_TEST)
    run = subprocess.run(["node", "lift.test.js"], cwd=out, check=False, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0 and "lift ok" in run.stdout, run.stdout + run.stderr
