#!/usr/bin/env python3
"""GET /api/pricing + models.dev -> catalog.json, srclient/_generated.py and the TS srclient/generated.ts.

Only public, non-price fields are copied: the name, vendor, description, feature tags and endpoints.
Group lists, group prices and ratios are never read into the output.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core" / "python" / "srclient"))
from classify import CATEGORIES, classify, family_of, matches_any

CATALOG = ROOT / "catalog"
CACHE = CATALOG / ".cache"
OUT = CATALOG / "catalog.json"
GENERATED = ROOT / "core" / "python" / "srclient" / "_generated.py"
GENERATED_TS = ROOT / "core" / "ts" / "srclient" / "generated.ts"
MODELS_DEV = "https://models.dev/api.json"
OFFICIAL = {  # /api/pricing vendor -> models.dev provider that publishes the model itself
    "OpenAI": "openai", "Anthropic": "anthropic", "Google": "google", "DeepSeek": "deepseek",
    "Alibaba": "alibaba", "xAI": "xai", "Moonshot": "moonshotai", "Zhipu": "zhipuai",
    "MiniMax": "minimax", "Xiaomi": "xiaomi", "ByteDance": "volcengine", "Meta": "llama",
    "Tencent": "tencent",
}
DATE_SUFFIX = re.compile(r"-(?:20\d{2}-\d{2}-\d{2}|\d{8}|\d{6})$")
DEFAULT_CONTEXT, DEFAULT_OUTPUT = 128000, 4096


def fetch_json(url: str, cache_name: str, offline: bool) -> dict:
    path = CACHE / cache_name
    if not offline:
        CACHE.mkdir(exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "steadyrouter-catalog"})
        with urllib.request.urlopen(request, timeout=60) as reply:
            path.write_bytes(reply.read())
    return json.loads(path.read_text())


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CATALOG / name).read_text())


def build_meta_index(models_dev: dict) -> tuple[dict, dict]:
    official: dict = {}
    anywhere: dict = {}
    for provider, body in models_dev.items():
        for model_id, model in body.get("models", {}).items():
            short = model_id.split("/")[-1]
            limit = model.get("limit") or {}
            if not limit.get("context"):
                continue
            entry = (limit["context"], limit.get("output") or 0)
            official[(provider, short)] = entry
            anywhere.setdefault(short, []).append(entry)
    return official, anywhere


def meta_for(name: str, vendor: str, official: dict, anywhere: dict) -> dict:
    provider = OFFICIAL.get(vendor)
    candidates = [name, DATE_SUFFIX.sub("", name)]
    for short in candidates:
        if (provider, short) in official:
            context, output = official[(provider, short)]
            return {"context": context, "max_output": output or DEFAULT_OUTPUT, "meta_source": "official",
                    "base_model": f"{provider}/{short}"}
    for short in candidates:
        if short in anywhere:
            (context, output), _ = Counter(anywhere[short]).most_common(1)[0]
            return {"context": context, "max_output": output or DEFAULT_OUTPUT, "meta_source": "other"}
    return {"context": DEFAULT_CONTEXT, "max_output": DEFAULT_OUTPUT, "meta_source": "default"}


def build(pricing: dict, models_dev: dict, overrides: dict, families: dict, video: dict) -> dict:
    vendors = {v["id"]: v["name"] for v in pricing.get("vendors") or []}
    official, anywhere = build_meta_index(models_dev)
    chat_image = overrides.get("chat_image_match", [])
    models = []
    for row in pricing["data"]:
        name = row["model_name"]
        category = classify(row, overrides.get("category"))
        tags = {t.strip() for t in (row.get("tags") or "").split(",")}
        vendor = vendors.get(row.get("vendor_id"), "")
        entry = {
            "name": name,
            "vendor": vendor,
            "description": row.get("description") or "",
            "category": category,
            "family": family_of(name, families),
            "features": sorted(tags & {"Vision", "Tools", "Reasoning"}),
            "featured": "Featured" in tags,
            "endpoints": sorted(row.get("supported_endpoint_types") or []),
        }
        if category in ("language", "embedding", "rerank"):
            entry.update(meta_for(name, vendor, official, anywhere))
        if category == "image":
            entry["protocol"] = "chat" if matches_any(name, chat_image) else "images"
        if category == "audio":
            entry["audio_kind"] = overrides.get("audio_kind", {}).get(name, "other")
        excluded = sorted(k for k, names in overrides.get("exclude", {}).items() if name in names)
        if excluded:
            entry["exclude"] = excluded
        models.append(entry)
    models.sort(key=lambda m: m["name"].lower())
    missing = sorted(set(video) - {m["name"] for m in models})
    if missing:
        print(f"note: video-params lists models not on sale: {missing}", file=sys.stderr)
    return {
        "schema": 1,
        "counts": {c: sum(m["category"] == c for m in models) for c in CATEGORIES},
        "models": models,
    }


def diff(old: dict | None, new: dict) -> tuple[list[str], list[str]]:
    before = {m["name"] for m in (old or {}).get("models", [])}
    after = {m["name"] for m in new["models"]}
    return sorted(after - before), sorted(before - after)


def write_generated(site: dict, overrides: dict, families: dict, video: dict, catalog: dict) -> None:
    site = {k: v for k, v in site.items() if k != "channel_codes"}  # one package must not carry every plugin's code
    shipped = [{"name": m["name"], "category": m["category"], "family": m["family"]}
               for m in catalog["models"] if m["category"] in ("image", "video")]
    public_families = {k: {"label": v["label"], "category": v["category"], "match": v["match"],
                           "default": v.get("default")} for k, v in families.items()}
    parts = [
        '"""Generated by catalog/build_catalog.py. Do not edit."""\n',
        f"SITE = {json.dumps(site, indent=1, sort_keys=True)}\n",
        f"FAMILIES = {json.dumps(public_families, indent=1)}\n",
        f"VIDEO_PARAMS = {json.dumps(video, indent=1)}\n",
        f"CATEGORY_OVERRIDES = {json.dumps(overrides.get('category', {}), indent=1)}\n",
        f"CHAT_IMAGE_MATCH = {json.dumps(overrides.get('chat_image_match', []))}\n",
        f"EXCLUDE = {json.dumps({k: sorted(v) for k, v in overrides.get('exclude', {}).items()}, indent=1)}\n",
        f"SHIPPED_MODELS = {json.dumps(shipped, indent=0)}\n",
    ]
    text = "\n".join(parts).replace(": null", ": None").replace(": true", ": True").replace(": false", ": False")
    GENERATED.write_text(text)
    write_generated_ts(site, overrides, public_families, video, catalog)


def write_generated_ts(site: dict, overrides: dict, families: dict, video: dict, catalog: dict) -> None:
    """Same data for the TS client. Language models are shipped too: n8n and the Coze relay list them offline."""
    shipped = [{"name": m["name"], "category": m["category"], "family": m["family"]}
               for m in catalog["models"] if m["category"] in ("language", "image", "video")]
    exclude = {k: sorted(v) for k, v in overrides.get("exclude", {}).items()}
    parts = [
        ("// Generated by catalog/build_catalog.py. Do not edit.\n"
         "import type { Category, Family, ShippedModel, VideoRule } from './classify';\n"),
        f"export const SITE = {json.dumps(site, indent=1, sort_keys=True)} as const;\n",
        f"export const FAMILIES: Record<string, Family> = {json.dumps(families, indent=1)};\n",
        f"export const VIDEO_PARAMS: Record<string, VideoRule> = {json.dumps(video, indent=1)};\n",
        f"export const CATEGORY_OVERRIDES: Record<string, Category> = {json.dumps(overrides.get('category', {}), indent=1)};\n",
        f"export const CHAT_IMAGE_MATCH: string[] = {json.dumps(overrides.get('chat_image_match', []))};\n",
        f"export const EXCLUDE: Record<string, string[]> = {json.dumps(exclude, indent=1)};\n",
        f"export const SHIPPED_MODELS: ShippedModel[] = {json.dumps(shipped, indent=0)};\n",
    ]
    GENERATED_TS.write_text("\n".join(parts))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="reuse catalog/.cache instead of fetching")
    args = parser.parse_args()
    site = load_yaml("site.yaml")
    pricing = fetch_json(site["pricing_api"], "pricing.raw.json", args.offline)
    models_dev = fetch_json(MODELS_DEV, "models-dev.raw.json", args.offline)
    overrides, families, video = load_yaml("overrides.yaml"), load_yaml("families.yaml"), load_yaml("video-params.yaml")
    catalog = build(pricing, models_dev, overrides, families, video)
    old = json.loads(OUT.read_text()) if OUT.exists() else None
    added, removed = diff(old, catalog)
    OUT.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n")
    write_generated(site, overrides, families, video, catalog)
    sources = Counter(m.get("meta_source") for m in catalog["models"] if m.get("meta_source"))
    print(f"models: {len(catalog['models'])}  {catalog['counts']}")
    print(f"context from: {dict(sources)}")
    print(f"added ({len(added)}): {added}")
    print(f"removed ({len(removed)}): {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
