"""Generate the Coze relay Worker and the plugins' OpenAPI files.

dist/coze/worker/    a wrangler project: src/ (Worker + shared TS client + generated config.ts), wrangler.toml
dist/coze/openapi/   <region>/<plugin>.yaml, one file per plugin to import into Coze ("create plugin from API")

A test build (--base-url) points the Worker at a fake gateway and lets it download from http / local hosts.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from common import DIST, ROOT, Context, dump_yaml, fresh_dir, load_yaml

PLATFORM = "coze"
HERE = Path(__file__).resolve().parent
COMPATIBILITY_DATE = "2026-02-12"  # the newest date the tested runtime supports (workerd in wrangler 4.65)
QUALITIES = ["auto", "low", "medium", "high"]
ASPECTS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"]
IMAGE_SIZES = ["auto", "1K", "2K", "4K"]
RESOLUTION_ORDER = ["480p", "540p", "720p", "1080p", "4k"]
PATHS = {"image": "/v1/images", "submit": "/v1/videos", "status": "/v1/videos/status"}


def config() -> dict:
    return load_yaml(HERE / "coze.yaml")


def get_key_url(ctx: Context, conf: dict, plugin: dict, region: str) -> str:
    code = conf["regions"][region].get("aff") or plugin["aff"]
    return f"{ctx.site['sign_up_url']}?aff={code}"


# ---- which models ----

def region_models(ctx: Context, conf: dict, region: str, category: str) -> list[str]:
    allowed = conf["regions"][region]["families"]
    names = []
    for m in ctx.models(category):
        if m["name"] in conf["exclude"]:
            continue
        if allowed != "all" and m.get("family") not in allowed:
            continue
        names.append(m["name"])
    return sorted(names)


def default_model(conf: dict, category: str, models: list[str]) -> str:
    wanted = conf["defaults"][category]
    return wanted if wanted in models else models[0]


# ---- text ----

T = {
    "en": {
        "key_desc": 'Your SteadyRouter API key as "Bearer <key>". Bind it by Reference to a private variable; never type the key here or in a prompt.',
        "prompt_image": "What the image should show.",
        "prompt_video": "What the video should show.",
        "model": "Model. Options: {options}. Default: {default}.",
        "aspect_ratio": "Aspect ratio, Nano Banana (Gemini) models only. Options: {options}.",
        "image_size": "Resolution, Nano Banana (Gemini) models only; higher costs more. Options: {options}.",
        "quality": "Quality; higher costs more. Options: {options}.",
        "free_size": "Optional size, for example 1024x1024 or 2048x2048. Each model takes its own sizes; leave empty for the default.",
        "reference_images": "Optional reference images (up to {n} public https links) to edit or combine. Nano Banana (Gemini) models only.",
        "resolution": "Resolution; each model takes its own, higher costs more. Options: {options}.",
        "seconds": "Length in seconds; each model takes its own, longer costs more.",
        "start_image": "Optional first frame (a public https link). Some models need one, some refuse it.",
        "task_id": "The task_id returned by Submit video.",
        "code": "0 = success. Anything else is an error; msg says what went wrong.",
        "msg": "Error or status message, safe to show.",
        "image_url": "Link to the first image. Kept for {days} days.",
        "image_urls": "Links to all images. Kept for {days} days.",
        "used_model": "The model that made the image.",
        "expires_in_days": "Days the files are kept before they are deleted.",
        "submit_status": "queued when the task was accepted.",
        "video_status": "running, succeeded or failed.",
        "progress": "Progress reported by the model, if any.",
        "video_url": "Link to the video once status is succeeded. Kept for {days} days.",
        "fail_reason": "Why the video failed, if it did.",
        "image_summary": "Generate an image from a prompt and return a link to it. Can take several minutes: in workflows set this node's timeout to 10 minutes.",
        "submit_summary": "Start a video task and return its task_id. Then call Check video with that task_id.",
        "status_summary": "Check a video task. Call again every 15 seconds or so until status is succeeded or failed; then video_url links to the video.",
        "plugin": (
            "{what}. Bring your own SteadyRouter API key: get one at steadyrouter.com ({link}). After adding the plugin, "
            'bind its Authorization parameter by Reference to a private variable whose value is "Bearer <your key>"; '
            "never put the key in a prompt or a shared workflow. Usage is billed to your SteadyRouter account. "
            "Generated files are kept for {days} days, then deleted: save them soon. In workflows, set this plugin's "
            "node timeout to 10 minutes."
        ),
        "plugin_video": " For videos, call Submit video, keep the task_id, then call Check video until it is done.",
    },
    "zh": {
        "key_desc": "你的 SteadyRouter API Key，格式 Bearer 加 Key。请用「引用」绑定到私有变量，别直接填在这里或写进提示词。",
        "prompt_image": "图片要画什么。",
        "prompt_video": "视频要拍什么。",
        "model": "型号。可选：{options}。默认：{default}。",
        "aspect_ratio": "宽高比，只对 Nano Banana（Gemini）型号有效。可选：{options}。",
        "image_size": "清晰度，只对 Nano Banana（Gemini）型号有效，越高越贵。可选：{options}。",
        "quality": "质量，越高越贵。可选：{options}。",
        "free_size": "可选的尺寸，例如 1024x1024、2048x2048。每个型号支持的尺寸不同，不填用默认。",
        "reference_images": "可选的参考图（最多 {n} 个公开的 https 链接），用来修改或融合。只对 Nano Banana（Gemini）型号有效。",
        "resolution": "分辨率，每个型号支持的不同，越高越贵。可选：{options}。",
        "seconds": "时长（秒），每个型号支持的不同，越长越贵。",
        "start_image": "可选的首帧图（公开的 https 链接）。有的型号必须要，有的不接受。",
        "task_id": "「提交视频」返回的 task_id。",
        "code": "0 表示成功，其他都是出错，原因见 msg。",
        "msg": "出错或状态说明，可以直接展示。",
        "image_url": "第一张图的链接，保存 {days} 天。",
        "image_urls": "所有图片的链接，保存 {days} 天。",
        "used_model": "生成这张图的型号。",
        "expires_in_days": "文件保存的天数，到期自动删除。",
        "submit_status": "任务已接受时为 queued。",
        "video_status": "running（生成中）、succeeded（成功）或 failed（失败）。",
        "progress": "型号报的进度（如果有）。",
        "video_url": "成功后视频的链接，保存 {days} 天。",
        "fail_reason": "失败原因（如果失败）。",
        "image_summary": "按提示词生成图片，返回图片链接。有时要几分钟：在工作流里请把这个节点的超时调到 10 分钟。",
        "submit_summary": "提交视频任务，返回 task_id。然后用「查询视频」查这个 task_id。",
        "status_summary": "查询视频任务。每隔 15 秒左右查一次，直到 status 为 succeeded 或 failed；成功后 video_url 就是视频链接。",
        "plugin": (
            "{what}。使用你自己的 SteadyRouter API Key：在 steadyrouter.com 获取（{link}）。添加插件后，把 Authorization "
            "参数用「引用」绑定到一个私有变量，变量值写 Bearer 加你的 Key；别把 Key 写进提示词或共享的工作流。费用从你的 "
            "SteadyRouter 账户扣。生成的文件保存 {days} 天后自动删除，请及时保存。在工作流里请把本插件节点的超时调到 10 分钟。"
        ),
        "plugin_video": "视频先调「提交视频」，记下 task_id，再调「查询视频」直到完成。",
    },
}
TOOL_NAMES = {
    "en": {"image": "Generate image", "submit": "Submit video", "status": "Check video"},
    "zh": {"image": "生成图片", "submit": "提交视频", "status": "查询视频"},
}


def enum_param(values: list[str], default: str, desc: str) -> dict:
    return {"type": "string", "enum": values, "default": default, "description": desc}


def string(desc: str, **extra) -> dict:
    return {"type": "string", "description": desc, **extra}


def json_body(props: dict, required: list[str]) -> dict:
    return {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": required,
                                                                          "properties": props}}}}


def json_reply(props: dict, t: dict) -> dict:
    base = {"code": {"type": "integer", "description": t["code"]}, "msg": string(t["msg"])}
    return {"200": {"description": "OK", "content": {"application/json": {"schema": {
        "type": "object", "required": ["code", "msg"], "properties": {**base, **props}}}}}}


def key_param(t: dict) -> dict:
    return {"name": "Authorization", "in": "header", "required": True, "description": t["key_desc"],
            "schema": {"type": "string"}}


def image_op(ctx: Context, conf: dict, region: str, t: dict, lang: str) -> dict:
    models = region_models(ctx, conf, region, "image")
    default = default_model(conf, "image", models)
    days = conf["keep_days"]
    props = {
        "prompt": string(t["prompt_image"]),
        "model": enum_param(models, default, t["model"].format(options=", ".join(models), default=default)),
    }
    props |= {
        "size": string(t["free_size"]),
        "quality": enum_param(QUALITIES, "auto", t["quality"].format(options=", ".join(QUALITIES))),
        "aspect_ratio": enum_param(ASPECTS, "auto", t["aspect_ratio"].format(options=", ".join(ASPECTS))),
        "image_size": enum_param(IMAGE_SIZES, "auto", t["image_size"].format(options=", ".join(IMAGE_SIZES))),
        "reference_images": {"type": "array", "description": t["reference_images"].format(n=conf["limits"]["reference_images"]),
                             "items": {"type": "string", "format": "image_url"}},
    }
    reply = {
        "image_url": string(t["image_url"].format(days=days), format="image_url"),
        "image_urls": {"type": "array", "description": t["image_urls"].format(days=days),
                       "items": {"type": "string", "format": "image_url"}},
        "model": string(t["used_model"]),
        "expires_in_days": {"type": "integer", "description": t["expires_in_days"]},
    }
    return {"post": {"operationId": "generate_image", "summary": f"{TOOL_NAMES[lang]['image']}: {t['image_summary']}",
                     "parameters": [key_param(t)], "requestBody": json_body(props, ["prompt", "model"]),
                     "responses": json_reply(reply, t)}}


def video_ops(ctx: Context, conf: dict, region: str, t: dict, lang: str) -> dict:
    models = region_models(ctx, conf, region, "video")
    default = default_model(conf, "video", models)
    rules = [ctx.video[m] for m in models if m in ctx.video]
    resolutions = [r for r in RESOLUTION_ORDER if any(r in rule["resolutions"] for rule in rules)]
    res_default = "720p" if "720p" in resolutions else resolutions[0]
    days = conf["keep_days"]
    submit_props = {
        "prompt": string(t["prompt_video"]),
        "model": enum_param(models, default, t["model"].format(options=", ".join(models), default=default)),
        "resolution": enum_param(resolutions, res_default, t["resolution"].format(options=", ".join(resolutions))),
        "seconds": {"type": "integer", "default": 5, "description": t["seconds"]},
        "start_image": string(t["start_image"], format="image_url"),
    }
    submit = {"post": {"operationId": "submit_video", "summary": f"{TOOL_NAMES[lang]['submit']}: {t['submit_summary']}",
                       "parameters": [key_param(t)], "requestBody": json_body(submit_props, ["prompt", "model"]),
                       "responses": json_reply({"task_id": string(t["task_id"]),
                                                "status": string(t["submit_status"])}, t)}}
    status = {"post": {"operationId": "check_video", "summary": f"{TOOL_NAMES[lang]['status']}: {t['status_summary']}",
                       "parameters": [key_param(t)],
                       "requestBody": json_body({"task_id": string(t["task_id"])}, ["task_id"]),
                       "responses": json_reply({
                           "task_id": string(t["task_id"]),
                           "status": string(t["video_status"]),
                           "progress": string(t["progress"]),
                           "video_url": string(t["video_url"].format(days=days), format="video_url"),
                           "fail_reason": string(t["fail_reason"]),
                           "expires_in_days": {"type": "integer", "description": t["expires_in_days"]},
                       }, t)}}
    return {"submit": submit, "status": status}


def openapi(ctx: Context, conf: dict, plugin: dict, region: str) -> dict:
    lang = conf["regions"][region]["lang"]
    t = T[lang]
    prefix = f"/coze/{region}"
    ops = video_ops(ctx, conf, region, t, lang)
    paths = {prefix + PATHS["image"]: image_op(ctx, conf, region, t, lang),
             prefix + PATHS["submit"]: ops["submit"], prefix + PATHS["status"]: ops["status"]}
    description = t["plugin"].format(what=plugin["what"][lang], link=get_key_url(ctx, conf, plugin, region), days=conf["keep_days"])
    description += t["plugin_video"]
    return {
        "openapi": "3.0.1",
        "info": {"title": plugin["name"][lang], "version": ctx.versions[PLATFORM], "description": description},
        "servers": [{"url": conf["api_base"]}],
        "paths": paths,
    }


# ---- worker ----

def config_ts(ctx: Context, conf: dict, test_build: bool, pricing_url: str | None) -> str:
    regions = {name: {"lang": r["lang"], "families": r["families"]} for name, r in conf["regions"].items()}
    values = {
        "TEST_BUILD": test_build,
        "API_BASE": ctx.api_base,
        "PRICING_URL": pricing_url or (f"{ctx.api_base}/api/pricing" if test_build else ctx.site["pricing_api"]),
        "PREFIX": conf["prefix"],
        "KEEP_DAYS": conf["keep_days"],
        "LIMITS": conf["limits"],
        "EXCLUDE": conf["exclude"],
    }
    lines = ["// Generated by platforms/coze/build.py from coze.yaml and catalog/site.yaml. Do not edit.", ""]
    lines += [f"export const {k} = {json.dumps(v, ensure_ascii=False)} as const;" for k, v in values.items()]
    lines.append("export const REGIONS: Record<string, { lang: 'en' | 'zh'; families: 'all' | readonly string[] }> = "
                 f"{json.dumps(regions, ensure_ascii=False)};")
    return "\n".join(lines) + "\n"


def wrangler_toml(conf: dict) -> str:
    return f"""# Generated by platforms/coze/build.py.
name = "{conf['worker_name']}"
main = "src/index.ts"
compatibility_date = "{COMPATIBILITY_DATE}"
# No *.workers.dev address: it would show the Cloudflare account name. The Worker is reached only through the
# custom hostname route below.
workers_dev = false
preview_urls = false

# Planned: a Cloudflare for SaaS custom hostname. Fill in the zone at deploy time; use the
# hostname, not */*, so the route catches nothing else on that zone.
# routes = [{{ pattern = "files.steadyrouter.com/*", zone_name = "<the SaaS zone>" }}]

[[r2_buckets]]
binding = "FILES"
bucket_name = "{conf['bucket']}"

[vars]
FILES_BASE_URL = "{conf['files_base']}"
# FILE_NAME_SECRET is a secret: `wrangler secret put FILE_NAME_SECRET` (any long random string).

# Requests carry the caller's API key in a header, so nothing is logged: no Workers Logs, no invocation logs.
[observability]
enabled = false

[observability.logs]
enabled = false
invocation_logs = false
"""


def build(ctx: Context, out: Path | None = None, pricing_url: str | None = None, limits: dict | None = None) -> Path:
    """`out`, `pricing_url` and `limits` are for tests (tests/e2e/coze_e2e.py)."""
    conf = config()
    conf["limits"] = {**conf["limits"], **(limits or {})}
    test_build = ctx.api_base != ctx.site["api_base"].rstrip("/")
    dest = fresh_dir(out or DIST / PLATFORM)
    worker = dest / "worker"
    shutil.copytree(HERE / "worker" / "src", worker / "src")
    shutil.copytree(ROOT / "core" / "ts" / "srclient", worker / "src" / "srclient")
    (worker / "src" / "config.ts").write_text(config_ts(ctx, conf, test_build, pricing_url))
    (worker / "wrangler.toml").write_text(wrangler_toml(conf))
    shutil.copy(HERE / "worker" / "tsconfig.json", worker / "tsconfig.json")
    for plugin in conf["plugins"]:
        for region in plugin["regions"]:
            path = dest / "openapi" / region / f"{plugin['id']}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(dump_yaml(openapi(ctx, conf, plugin, region)))
    return dest
