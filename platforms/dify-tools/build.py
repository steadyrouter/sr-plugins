"""Generate the Dify tool plugins: SteadyRouter Image & Video (one named tool per popular family) and the plugins
named after one model, listed in single.yaml."""

from __future__ import annotations

import datetime as dt
import re
import shutil
from dataclasses import replace
from pathlib import Path

from common import DIST, ROOT, Context, copy_tree, dump_yaml, fill, fresh_dir, load_yaml

PLATFORM = "dify-tools"
HERE = Path(__file__).resolve().parent
PROVIDER = "steadyrouter_media"
CREATED_AT = dt.datetime(2026, 11, 2, tzinfo=dt.UTC)
LOCALES = ("en_US", "zh_Hans", "ja_JP", "pt_BR")
ASPECTS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"]
RESOLUTIONS = ["480p", "540p", "720p", "1080p", "4k"]
GPT_SIZES = ["auto", "1024x1024", "1536x1024", "1024x1536"]
QUALITIES = ["auto", "low", "medium", "high"]


def label(en: str, zh: str) -> dict:
    return {"en_US": en, "zh_Hans": zh}


def options(values: list[str]) -> list[dict]:
    return [{"value": v, "label": {"en_US": v}} for v in values]


def text_param(name, en, zh, human_en, human_zh, llm=None, required=False, form="form") -> dict:
    param = {"name": name, "type": "string", "required": required, "form": form, "label": label(en, zh),
             "human_description": label(human_en, human_zh)}
    if llm:
        param["llm_description"] = llm
    return param


def select_param(name, en, zh, human_en, human_zh, values, default) -> dict:
    return {"name": name, "type": "select", "required": False, "form": "form", "default": default,
            "label": label(en, zh), "human_description": label(human_en, human_zh), "options": options(values)}


def model_param(default: str | None, suggest: str | None = None) -> dict:
    # form: llm, not form: Dify's workflow panel only fetches dynamic options for this section. Under SETTINGS
    # (form: form) it never asks and the dropdown stays empty (seen in the browser on Dify 1.19.0).
    # In an Agent the model fills this in, so tell it what to pick.
    pick = default or suggest
    param = {"name": "model", "type": "dynamic-select", "required": True, "form": "llm",
             "llm_description": f"The SteadyRouter model ID. Use {pick} unless the user names another model.",
             "label": label("Model", "型号"),
             "human_description": label("The list comes live from SteadyRouter, so new models appear on their own.",
                                        "列表实时取自 SteadyRouter，新上架的型号会自动出现。")}
    if default:
        param["default"] = default
    return param


def prompt_param(what: str, zh: str) -> dict:
    return text_param("prompt", "Prompt", "提示词", f"Describe the {what} you want.", f"描述你想要的{zh}。",
                      llm=f"A description of the {what} to generate.", required=True, form="llm")


def reference_images() -> dict:
    return {"name": "images", "type": "files", "required": False, "form": "llm", "label": label("Reference images", "参考图"),
            "human_description": label("Optional. With reference images the model edits or combines them.",
                                       "可选。带参考图时，型号按提示词修改或融合这些图片。"),
            "llm_description": "Optional images to edit or combine according to the prompt."}


def image_params(kind: str, default: str | None, suggest: str | None = None) -> list[dict]:
    params = [prompt_param("image", "图片"), model_param(default, suggest), reference_images()]
    aspect = select_param("aspect_ratio", "Aspect ratio", "宽高比", "Used by Gemini image models.",
                          "Gemini 生图型号使用。", ASPECTS, "auto")
    clarity = select_param("image_size", "Resolution", "清晰度", "Used by Gemini image models. Higher costs more.",
                           "Gemini 生图型号使用。越高越贵。", ["auto", "1K", "2K", "4K"], "auto")
    gpt_size = select_param("size", "Size", "尺寸", "Output size.", "输出尺寸。", GPT_SIZES, "auto")
    quality = select_param("quality", "Quality", "质量", "Higher quality costs more.", "质量越高越贵。", QUALITIES, "auto")
    free_size = text_param("size", "Size", "尺寸", "Optional, for example 1024x1024. Each model takes its own sizes.",
                           "可选，例如 1024x1024。每个型号支持的尺寸不同。")
    if kind == "nano_banana":
        return params + [aspect, clarity]
    if kind == "gpt_image":
        return params + [gpt_size, quality]
    if kind == "all":
        return params + [free_size, quality, aspect, clarity]
    return params + [free_size]


def video_params(default: str | None, suggest: str | None = None) -> list[dict]:
    return [
        prompt_param("video", "视频"),
        model_param(default, suggest),
        select_param("resolution", "Resolution", "分辨率", "Each model takes its own resolutions. Higher costs more.",
                     "每个型号支持的分辨率不同。越高越贵。", RESOLUTIONS, "720p"),
        {"name": "seconds", "type": "number", "required": False, "form": "form", "default": 5, "min": 1, "max": 16,
         "label": label("Length (seconds)", "时长（秒）"),
         "human_description": label("Each model takes its own lengths. Longer costs more.",
                                    "每个型号支持的时长不同。越长越贵。")},
        {"name": "start_image", "type": "file", "required": False, "form": "llm", "label": label("Starting image", "首帧图"),
         "human_description": label("Required by some models, refused by others.", "有的型号必须要，有的不接受。"),
         "llm_description": "Optional starting image for the video."},
        text_param("start_image_url", "Starting image link", "首帧图链接", "A public link, used if no file is given.",
                   "公开可访问的链接，没传文件时使用。", llm="Optional public link to a starting image.", form="llm"),
    ]


def tool_defs(ctx: Context) -> list[dict]:
    fam = ctx.families
    image_note = "Results come back as files."
    return [
        {"id": "generate_image", "mixin": "ImageTool", "family": None, "kind": "all", "default": None,
         "suggest": fam["gpt_image"]["default"],
         "en": "Generate Image", "zh": "生成图片", "desc_en": f"Generate or edit images with any SteadyRouter image model. {image_note}",
         "desc_zh": "用 SteadyRouter 上任意生图型号生成或修改图片。"},
        {"id": "nano_banana", "mixin": "ImageTool", "family": "nano_banana", "kind": "nano_banana",
         "default": fam["nano_banana"]["default"], "en": "Nano Banana (SteadyRouter)", "zh": "Nano Banana（SteadyRouter）",
         "desc_en": f"Generate or edit images with Gemini image models (Nano Banana). {image_note}",
         "desc_zh": "用 Gemini 生图型号（Nano Banana）生成或修改图片。"},
        {"id": "gpt_image", "mixin": "ImageTool", "family": "gpt_image", "kind": "gpt_image",
         "default": fam["gpt_image"]["default"], "en": "GPT Image (SteadyRouter)", "zh": "GPT Image（SteadyRouter）",
         "desc_en": f"Generate or edit images with GPT Image models. {image_note}", "desc_zh": "用 GPT Image 型号生成或修改图片。"},
        {"id": "seedream", "mixin": "ImageTool", "family": "seedream", "kind": "plain",
         "default": fam["seedream"]["default"], "en": "Seedream (SteadyRouter)", "zh": "Seedream（SteadyRouter）",
         "desc_en": f"Generate images with Doubao Seedream models. {image_note}", "desc_zh": "用豆包 Seedream 型号生成图片。"},
        {"id": "qwen_image", "mixin": "ImageTool", "family": "tongyi_image", "kind": "plain",
         "default": fam["tongyi_image"]["default"], "en": "Qwen Image & Wan (SteadyRouter)", "zh": "通义万相 & Qwen Image（SteadyRouter）",
         "desc_en": f"Generate images with Qwen Image and Wan models. {image_note}", "desc_zh": "用 Qwen Image 和万相型号生成图片。"},
        {"id": "generate_video", "mixin": "VideoTool", "family": None, "kind": "video", "default": None,
         "suggest": fam["seedance"]["default"],
         "en": "Generate Video", "zh": "生成视频",
         "desc_en": "Generate a video with any SteadyRouter video model and wait for it (up to 8 minutes). If it takes longer, you get a task ID for Check Video Task.",
         "desc_zh": "用 SteadyRouter 上任意视频型号生成视频并等待结果（最多 8 分钟）。超时会给出任务 ID，用「查视频任务」接着查。"},
        {"id": "seedance", "mixin": "VideoTool", "family": "seedance", "kind": "video",
         "default": fam["seedance"]["default"], "en": "Seedance (SteadyRouter)", "zh": "Seedance（SteadyRouter）",
         "desc_en": "Generate a video with Doubao Seedance models and wait for it (up to 8 minutes). If it takes longer, you get a task ID for Check Video Task.",
         "desc_zh": "用豆包 Seedance 型号生成视频并等待结果（最多 8 分钟）。超时会给出任务 ID，用「查视频任务」接着查。"},
        {"id": "check_video_task", "mixin": "CheckVideoTool", "family": None, "kind": "check", "default": None,
         "en": "Check Video Task", "zh": "查视频任务",
         "desc_en": "Check a video task by its ID, and get the video once it is ready.", "desc_zh": "按任务 ID 查视频任务，好了就取回视频。"},
    ]


def tool_yaml(ctx: Context, tool: dict) -> dict:
    if tool["kind"] == "video":
        params = video_params(tool["default"], tool.get("suggest"))
    elif tool["kind"] == "check":
        params = [text_param("task_id", "Task ID", "任务 ID", "The ID returned when the video was submitted.",
                             "提交视频时返回的任务 ID。", llm="The video task ID.", required=True, form="llm")]
    else:
        params = image_params(tool["kind"], tool["default"], tool.get("suggest"))
    return {
        "identity": {"name": tool["id"], "author": ctx.site["slug"], "label": label(tool["en"], tool["zh"])},
        "description": {"human": label(tool["desc_en"], tool["desc_zh"]), "llm": tool["desc_en"]},
        "parameters": params,
        "extra": {"python": {"source": f"tools/{tool['id']}.py"}},
    }


def tool_source(tool: dict) -> str:
    cls = re.sub(r"(?:^|_)(\w)", lambda m: m.group(1).upper(), tool["id"])
    family = f'"{tool["family"]}"' if tool["family"] else "None"
    attrs = "    pass" if tool["kind"] == "check" else f"    FAMILY = {family}"
    if tool.get("only"):
        attrs += f'\n    ONLY = "{tool["only"]}"'
    return (f"from dify_plugin import Tool\n\nfrom tools._base import {tool['mixin']}\n\n\n"
            f"class {cls}({tool['mixin']}, Tool):\n{attrs}\n")


def provider_yaml(ctx: Context, listing: dict, tools: list[dict]) -> dict:
    return {
        "identity": {"author": ctx.site["slug"], "name": PROVIDER, "label": {"en_US": listing["label"]},
                     "description": listing["tagline"], "icon": "icon.svg"},
        "credentials_for_provider": {"api_key": {
            "type": "secret-input", "required": True, "label": {k: ctx.strings["api_key"][k] for k in LOCALES},
            "placeholder": {k: ctx.strings["api_key_placeholder"][k] for k in LOCALES},
            "help": {k: ctx.strings["get_key"][k] for k in LOCALES}, "url": ctx.site["get_key_url"]}},
        "extra": {"python": {"source": "provider/steadyrouter_media.py"}},
        "tools": [f"tools/{t['id']}.yaml" for t in tools],
    }


def manifest(ctx: Context, listing: dict) -> dict:
    return {
        "version": ctx.versions[listing["package"]],
        "type": "plugin",
        "author": ctx.site["slug"],
        "name": listing["name"],
        "repo": ctx.site["repo_url"],
        "label": {"en_US": listing["label"]},
        "description": listing["tagline"],
        "icon": "icon.svg",
        "created_at": CREATED_AT.isoformat(),
        "resource": {"memory": 536870912, "permission": {"tool": {"enabled": True}}},
        "plugins": {"tools": ["provider/steadyrouter_media.yaml"]},
        "meta": {"version": "0.0.2", "arch": ["amd64", "arm64"],
                 "runner": {"language": "python", "version": "3.12", "entrypoint": "main"}},
        "privacy": "PRIVACY.md",
    }


def single_listing(ctx: Context, spec: dict) -> dict:
    brand = ctx.site["brand"]
    what, owner = spec["what"], spec["owner"]
    return {
        "package": spec["package"],
        "name": spec["name"],
        "label": f"{spec['model']} by {brand}",
        "tagline": {"en_US": f"{what['en_US']} through {brand}, an independent API gateway not affiliated with {owner}.",
                    "zh_Hans": f"通过 {brand} {what['zh_Hans']}。{brand} 是独立的 API 网关，与 {owner} 没有关联。"},
    }


def single_tools(ctx: Context, spec: dict) -> list[dict]:
    what = spec["what"]
    video = spec["kind"] == "video"
    tool = {"id": spec["name"].removesuffix(f"_{ctx.site['slug']}"), "mixin": "VideoTool" if video else "ImageTool",
            "family": spec["family"], "only": spec.get("only"), "kind": spec["kind"],
            "default": spec.get("default") or ctx.families[spec["family"]]["default"], "en": spec["model"], "zh": spec["model"]}
    if not video:
        return [{**tool, "desc_en": f"{what['en_US']}. Results come back as files.", "desc_zh": f"{what['zh_Hans']}。"}]
    check = next(t for t in tool_defs(ctx) if t["id"] == "check_video_task")
    return [{**tool, "desc_en": f"{what['en_US']} and wait for it (up to 8 minutes). If it takes longer, you get a task ID for Check Video Task.",
             "desc_zh": f"{what['zh_Hans']}并等待结果（最多 8 分钟）。超时会给出任务 ID，用「查视频任务」接着查。"}, check]


def write_package(ctx: Context, listing: dict, tools: list[dict], readme: str, privacy: str, icon: str = "logo.svg") -> Path:
    out = fresh_dir(DIST / listing["package"])
    copy_tree(HERE / "files", out)
    (out / "README.md").write_text(readme)
    (out / "PRIVACY.md").write_text(privacy)
    (out / "_assets").mkdir()
    shutil.copy(ROOT / "brand" / icon, out / "_assets" / "icon.svg")
    copy_tree(ROOT / "core" / "python" / "srclient", out / "srclient")
    test_build = ctx.api_base != ctx.site["api_base"]
    if test_build:
        generated = out / "srclient" / "_generated.py"
        text = generated.read_text().replace(ctx.site["api_base"], ctx.api_base)
        text = text.replace(ctx.site["pricing_api"], f"{ctx.api_base}/api/pricing")
        generated.write_text(text)
    (out / "tools" / "_site.py").write_text(f"TEST_BUILD = {test_build}\n")
    for tool in tools:
        (out / "tools" / f"{tool['id']}.yaml").write_text(dump_yaml(tool_yaml(ctx, tool)))
        (out / "tools" / f"{tool['id']}.py").write_text(tool_source(tool))
    (out / "manifest.yaml").write_text(dump_yaml(manifest(ctx, listing)))
    (out / "provider" / "steadyrouter_media.yaml").write_text(dump_yaml(provider_yaml(ctx, listing, tools)))
    return out


def build_single(ctx: Context, spec: dict) -> Path:
    listing = single_listing(ctx, spec)
    ctx = ctx.for_channel(spec["package"])
    ctx = replace(ctx, site={**ctx.site, "plugin_label": listing["label"], "tagline": listing["tagline"]["en_US"],
                             "model": spec["model"], "owner": spec["owner"]})
    template = "video" if spec["kind"] == "video" else "image"
    readme = fill((HERE / "single" / f"README.{template}.md").read_text(), ctx)
    notice = f"{ctx.site['brand']} is an independent API gateway, not affiliated with {spec['owner']}.\n\nQuestions:"
    privacy = fill((HERE / "files" / "PRIVACY.md").read_text().replace("Questions:", notice), ctx)
    return write_package(ctx, listing, single_tools(ctx, spec), readme, privacy, spec.get("icon", "logo.svg"))


def build(ctx: Context) -> Path:
    for spec in load_yaml(HERE / "single.yaml"):
        build_single(ctx, spec)
    ctx = ctx.for_channel(PLATFORM)
    listing = {"package": PLATFORM, "name": "steadyrouter_image_video", "label": f"{ctx.site['brand']} Image & Video",
               "tagline": {k: ctx.strings["tools_tagline"][k] for k in LOCALES}}
    readme, privacy = (fill((HERE / "files" / name).read_text(), ctx) for name in ("README.md", "PRIVACY.md"))
    return write_package(ctx, listing, tool_defs(ctx), readme, privacy)
