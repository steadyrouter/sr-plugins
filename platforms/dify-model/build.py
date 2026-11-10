"""Generate the Dify model provider plugin: one YAML per model, code stays thin."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from common import DIST, ROOT, Context, copy_tree, dump_yaml, fill, fresh_dir, safe_file_name

PLATFORM = "dify-model"
HERE = Path(__file__).resolve().parent
LOCALES = ("en_US", "zh_Hans", "ja_JP", "pt_BR")
DEFAULT_MAX_TOKENS = 2048  # the gateway reserves balance for the maximum output, so keep the default modest
CREATED_AT = dt.datetime(2026, 11, 2, tzinfo=dt.UTC)
AUDIO_EXTENSIONS = "flac,mp3,mp4,mpeg,mpga,m4a,ogg,wav,webm"


def text(ctx: Context, key: str) -> dict:
    return {k: ctx.strings[key][k] for k in LOCALES}


def llm_yaml(model: dict) -> dict:
    features = []
    if "Tools" in model["features"]:
        features += ["tool-call", "multi-tool-call", "stream-tool-call", "agent-thought"]
    if "Vision" in model["features"]:
        features.append("vision")
    rules = [
        {"name": "temperature", "use_template": "temperature"},
        {"name": "top_p", "use_template": "top_p"},
        {"name": "presence_penalty", "use_template": "presence_penalty"},
        {"name": "frequency_penalty", "use_template": "frequency_penalty"},
        {"name": "max_tokens", "use_template": "max_tokens", "default": min(DEFAULT_MAX_TOKENS, model["max_output"]),
         "min": 1, "max": model["max_output"]},
    ]
    entry = {"model": model["name"], "label": {"en_US": model["name"]}, "model_type": "llm"}
    if features:
        entry["features"] = features
    entry["model_properties"] = {"mode": "chat", "context_size": model["context"]}
    entry["parameter_rules"] = rules
    return entry


def embedding_yaml(model: dict) -> dict:
    return {"model": model["name"], "label": {"en_US": model["name"]}, "model_type": "text-embedding",
            "model_properties": {"context_size": model["context"], "max_chunks": 32}}


def rerank_yaml(model: dict) -> dict:
    return {"model": model["name"], "label": {"en_US": model["name"]}, "model_type": "rerank",
            "model_properties": {"context_size": model["context"]}}


def stt_yaml(model: dict) -> dict:
    return {"model": model["name"], "label": {"en_US": model["name"]}, "model_type": "speech2text",
            "model_properties": {"file_upload_limit": 25, "supported_file_extensions": AUDIO_EXTENSIONS}}


def write_models(out: Path, folder: str, models: list[dict], render) -> None:
    target = out / "models" / folder
    target.mkdir(parents=True, exist_ok=True)
    order = sorted(models, key=lambda m: (not m["featured"], m["vendor"].lower(), m["name"].lower()))
    for model in order:
        (target / f"{safe_file_name(model['name'])}.yaml").write_text(dump_yaml(render(model)))
    (target / "_position.yaml").write_text(dump_yaml([m["name"] for m in order]))


def custom_model_form(ctx: Context) -> dict:
    """Lets users add a model the moment it goes on sale, before a new plugin version ships."""
    def label(en, zh):
        return {"en_US": en, "zh_Hans": zh}

    def yes_no(variable, en, zh, yes, no):
        return {"variable": variable, "label": label(en, zh), "type": "select", "required": False, "default": no,
                "show_on": [{"variable": "__model_type", "value": "llm"}],
                "options": [{"value": yes, "label": label("Yes", "是")}, {"value": no, "label": label("No", "否")}]}

    return {
        "model": {"label": label("Model name", "型号名称"),
                  "placeholder": label("Enter the model name from Model Square", "填写模型广场上的型号名称")},
        "credential_form_schemas": [
            api_key_field(ctx),
            {"variable": "context_size", "label": label("Model context size", "模型上下文长度"),
             "type": "text-input", "required": True, "default": "128000",
             "show_on": [{"variable": "__model_type", "value": "llm"}]},
            {"variable": "max_tokens_to_sample", "label": label("Upper bound for max tokens", "最大 token 上限"),
             "type": "text-input", "required": True, "default": "4096",
             "show_on": [{"variable": "__model_type", "value": "llm"}]},
            yes_no("vision_support", "Vision support", "支持图片输入", "support", "not_support"),
            yes_no("function_calling_type", "Tool calling", "支持工具调用", "tool_call", "no_call"),
        ],
    }


def api_key_field(ctx: Context) -> dict:
    return {"variable": "api_key", "label": text(ctx, "api_key"), "type": "secret-input", "required": True,
            "placeholder": text(ctx, "api_key_placeholder")}


def provider_yaml(ctx: Context) -> dict:
    return {
        "provider": ctx.site["slug"],
        "label": {"en_US": ctx.site["brand"]},
        "description": text(ctx, "tagline"),
        "icon_small": {"en_US": "icon.svg"},
        "icon_large": {"en_US": "icon.svg"},
        "background": "#F0FDFA",
        "help": {"title": text(ctx, "get_key"), "url": {"en_US": ctx.site["get_key_url"]}},
        "supported_model_types": ["llm", "text-embedding", "rerank", "speech2text"],
        "configurate_methods": ["predefined-model", "customizable-model"],
        "provider_credential_schema": {"credential_form_schemas": [api_key_field(ctx)]},
        "model_credential_schema": custom_model_form(ctx),
        "models": {
            kind: {"position": f"models/{kind}/_position.yaml", "predefined": [f"models/{kind}/*.yaml"]}
            for kind in ("llm", "text_embedding", "rerank", "speech2text")
        },
        "extra": {"python": {
            "provider_source": "provider/steadyrouter.py",
            "model_sources": ["models/llm/llm.py", "models/text_embedding/text_embedding.py",
                              "models/rerank/rerank.py", "models/speech2text/speech2text.py"],
        }},
    }


def manifest(ctx: Context) -> dict:
    version = ctx.versions[PLATFORM]
    return {
        "version": version,
        "type": "plugin",
        "author": ctx.site["slug"],
        "name": ctx.site["slug"],
        "repo": ctx.site["repo_url"],
        "contact": ctx.site["contact"],
        "label": {"en_US": ctx.site["brand"]},
        "description": text(ctx, "tagline"),
        "icon": "icon.svg",
        "created_at": CREATED_AT.isoformat(),
        "resource": {"memory": 268435456, "permission": {"model": {"enabled": False}}},
        "plugins": {"models": ["provider/steadyrouter.yaml"]},
        "meta": {"version": "0.0.2", "arch": ["amd64", "arm64"],
                 "runner": {"language": "python", "version": "3.12", "entrypoint": "main"}},
        "privacy": "PRIVACY.md",
    }


def build(ctx: Context) -> Path:
    ctx = ctx.for_channel(PLATFORM)
    out = fresh_dir(DIST / PLATFORM)
    copy_tree(HERE / "files", out)
    (out / "models" / "_site.py").write_text(f'API_BASE = "{ctx.api_base}"\n')
    for name in ("README.md", "PRIVACY.md"):
        (out / name).write_text(fill((HERE / "files" / name).read_text(), ctx))
    (out / "_assets").mkdir()
    shutil.copy(ROOT / "brand" / "logo.svg", out / "_assets" / "icon.svg")
    (out / "manifest.yaml").write_text(dump_yaml(manifest(ctx)))
    (out / "provider" / "steadyrouter.yaml").write_text(dump_yaml(provider_yaml(ctx)))
    write_models(out, "llm", ctx.models("language", platform=PLATFORM), llm_yaml)
    write_models(out, "text_embedding", ctx.models("embedding", platform=PLATFORM), embedding_yaml)
    write_models(out, "rerank", ctx.models("rerank", platform=PLATFORM), rerank_yaml)
    stt = [m for m in ctx.models("audio", platform=PLATFORM) if m.get("audio_kind") == "speech2text"]
    write_models(out, "speech2text", stt, stt_yaml)
    return out
