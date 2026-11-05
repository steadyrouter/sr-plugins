import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core" / "python" / "srclient"))
spec = importlib.util.spec_from_file_location("build_catalog", ROOT / "catalog" / "build_catalog.py")
bc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bc)

PRICING = {
    "vendors": [{"id": 1, "name": "OpenAI"}, {"id": 2, "name": "Google"}],
    "group_ratio": {"Secret-Group-01": 1.5},
    "data": [
        {"model_name": "gpt-x-2025-01-02", "tags": "Failover,Chat,Vision,Tools,Featured", "vendor_id": 1,
         "supported_endpoint_types": ["openai"], "description": "A model", "enable_groups": ["Secret-Group-01"],
         "group_prices": {"Secret-Group-01": {"input": 0.123456}}, "model_ratio": 37.5, "completion_ratio": 6,
         "billing_expr": "secret-expr"},
        {"model_name": "gemini-9-image", "tags": "Failover,Image", "vendor_id": 2,
         "supported_endpoint_types": ["openai"]},
        {"model_name": "gpt-image-9", "tags": "Image", "vendor_id": 1, "supported_endpoint_types": ["openai"]},
        {"model_name": "vid-1", "tags": "", "vendor_id": 1, "supported_endpoint_types": ["openai-video"]},
        {"model_name": "emb-1", "vendor_id": 1, "supported_endpoint_types": ["embeddings"]},
        {"model_name": "rr-1", "tags": "Rerank", "vendor_id": 1, "supported_endpoint_types": ["jina-rerank"]},
        {"model_name": "mystery-edit", "vendor_id": 1, "supported_endpoint_types": ["openai"]},
        {"model_name": "whisper-1", "tags": "Audio", "vendor_id": 1, "supported_endpoint_types": ["openai"]},
    ],
}
MODELS_DEV = {"openai": {"models": {"gpt-x": {"limit": {"context": 1000, "output": 100}}}},
              "someone": {"models": {"vendor/emb-1": {"limit": {"context": 8000}}}}}
OVERRIDES = {"category": {"mystery-edit": "image"}, "chat_image_match": ["^gemini-.*image"],
             "audio_kind": {"whisper-1": "speech2text"}, "exclude": {"dify-model": {"whisper-2": "x"}}}
FAMILIES = {"gpt_image": {"label": "GPT Image", "category": "image", "match": ["^gpt-image-"]}}


def built():
    return bc.build(PRICING, MODELS_DEV, OVERRIDES, FAMILIES, {})


def by_name():
    return {m["name"]: m for m in built()["models"]}


def test_categories():
    m = by_name()
    assert [m[n]["category"] for n in ("gpt-x-2025-01-02", "gemini-9-image", "vid-1", "emb-1", "rr-1",
                                       "mystery-edit", "whisper-1")] == [
        "language", "image", "video", "embedding", "rerank", "image", "audio"]


def test_protocol_and_family():
    m = by_name()
    assert m["gemini-9-image"]["protocol"] == "chat" and m["gpt-image-9"]["protocol"] == "images"
    assert m["gpt-image-9"]["family"] == "gpt_image" and m["vid-1"]["family"] is None


def test_meta_sources():
    m = by_name()
    x = m["gpt-x-2025-01-02"]
    assert (x["context"], x["max_output"], x["meta_source"], x["base_model"]) == (1000, 100, "official", "openai/gpt-x")
    assert m["emb-1"]["meta_source"] == "other" and m["rr-1"]["meta_source"] == "default"


def test_output_has_no_price_or_group_fields():
    text = json.dumps(built())
    for needle in ("Secret-Group", "0.123456", "37.5", "secret-expr", "ratio", "enable_groups", "group_prices"):
        assert needle not in text


def test_features_and_featured():
    x = by_name()["gpt-x-2025-01-02"]
    assert x["features"] == ["Tools", "Vision"] and x["featured"] is True


def test_diff():
    new = built()
    old = {"models": [{"name": "gone"}, {"name": "whisper-1"}]}
    added, removed = bc.diff(old, new)
    assert removed == ["gone"] and "gpt-image-9" in added and "whisper-1" not in added


def test_committed_catalog_is_consistent():
    catalog = json.loads((ROOT / "catalog" / "catalog.json").read_text())
    assert sum(catalog["counts"].values()) == len(catalog["models"])
    names = {m["name"] for m in catalog["models"]}
    assert set(yaml.safe_load((ROOT / "catalog" / "video-params.yaml").read_text())) <= names
    for family in yaml.safe_load((ROOT / "catalog" / "families.yaml").read_text()).values():
        assert family["default"] in names
    overrides = yaml.safe_load((ROOT / "catalog" / "overrides.yaml").read_text())
    for models in overrides["exclude"].values():
        assert set(models) <= names
