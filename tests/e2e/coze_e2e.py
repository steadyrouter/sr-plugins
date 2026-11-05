#!/usr/bin/env python3
"""Run the Coze relay Worker for real (wrangler dev --local, local R2) against the fake gateway. No network, no money.

usage: python tests/e2e/coze_e2e.py        (needs wrangler on PATH; never logs in, telemetry off)

Prints one line per check and exits 1 if any failed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tools")]
from fake_upstream import KEY, MP4, UPSTREAM_PATH, Fake  # noqa: E402

from build import load_builder  # noqa: E402
from common import load_context  # noqa: E402

coze_build = load_builder("coze")

BIG_PNG = b"\x89PNG\r\n\x1a\n" + os.urandom(150 * 1024)  # big enough that the Worker lifts the base64 out
SECRET = "e2e-file-name-secret-0123456789"
IMAGE_MODELS = ["m-b64", "m-url", "m-url-http-redirect", "m-url-html", "m-url-huge", "m-empty", "err-429", "err-leak",
                "err-quota", "gpt-image-2", "mj_imagine", "gemini-md-data-image", "gemini-md-link-image",
                "gemini-text-image", "gemini-parts-image", "gemini-images-image"]
VIDEO_MODELS = ["doubao-seedance-2-0-mini-260615", "err-price"]
HEX_FILE = re.compile(r"/coze/([0-9a-f]{32})\.(png|mp4)$")

results: list[tuple[bool, str]] = []


def check(ok: bool, what: str) -> None:
    results.append((bool(ok), what))
    print(("PASS " if ok else "FAIL ") + what, flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pricing_server() -> ThreadingHTTPServer:
    rows = [{"model_name": m, "tags": "Image", "supported_endpoint_types": ["openai"]} for m in IMAGE_MODELS]
    rows += [{"model_name": m, "tags": "Video", "supported_endpoint_types": ["openai-video"]} for m in VIDEO_MODELS]
    rows.append({"model_name": "some-chat", "tags": "Chat", "supported_endpoint_types": ["openai"]})
    raw = json.dumps({"data": rows}).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def http(method: str, url: str, body=None, key: str | None = KEY, headers=None) -> tuple[int, dict, bytes]:
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if key is not None:
        req.add_header("Authorization", f"Bearer {key}")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=120) as res:
            return res.status, dict(res.headers), res.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def blobs(state: Path) -> int:
    return sum(1 for p in state.rglob("*") if p.is_file() and "blobs" in p.parts)


def main() -> int:
    fake = Fake(png=BIG_PNG)
    prices = pricing_server()
    work = Path(tempfile.mkdtemp(prefix="coze-e2e-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    ctx = load_context(fake.base)
    limits = {"image_mb": (len(BIG_PNG) + 2048) / 1024 / 1024, "video_mb": 2048 / 1024 / 1024,
              "video_buffer_mb": 2048 / 1024 / 1024}
    worker = coze_build.build(ctx, out=work / "build", pricing_url=f"http://127.0.0.1:{prices.server_address[1]}/api/pricing",
                              limits=limits) / "worker"
    (worker / ".dev.vars").write_text(f"FILE_NAME_SECRET={SECRET}\n")
    state = work / "state"
    env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
    env.update(WRANGLER_SEND_METRICS="false", CI="1", NO_UPDATE_NOTIFIER="1")
    log = (work / "wrangler.log").open("w")
    proc = subprocess.Popen(["wrangler", "dev", "--local", "--ip", "127.0.0.1", "--port", str(port), "--persist-to", str(state),
                             "--var", f"FILES_BASE_URL:{base}"], cwd=worker, env=env, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        for _ in range(90):
            try:
                if http("GET", f"{base}/ready", key=None)[0] == 404:
                    break
            except OSError:
                time.sleep(1)
        else:
            print((work / "wrangler.log").read_text()[-3000:])
            return 1
        run_checks(base, fake, state)
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=30)
        log.close()
        wlog = (work / "wrangler.log").read_text()
        check(KEY not in wlog and SECRET not in wlog, "the wrangler log holds neither the API key nor the secret")
        warnings = [line for line in wlog.splitlines() if "warn" in line.lower() and "upgrade" not in line.lower()
                    and "update available" not in line.lower()]
        check(not warnings, f"wrangler log has no config warnings {warnings[:3]} (log: {work}/wrangler.log)")
        fake.close()
        prices.shutdown()
    failed = [w for ok, w in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    if not failed:
        shutil.rmtree(work)  # kept on failure for the wrangler log
    return 1 if failed else 0


def tool(base: str, region: str, name: str, body: dict, key: str | None = KEY) -> dict:
    path = {"image": "v1/images", "submit": "v1/videos", "status": "v1/videos/status"}[name]
    status, headers, raw = http("POST", f"{base}/coze/{region}/{path}", body, key=key)
    assert status == 200, (status, raw[:300])
    return json.loads(raw)


def run_checks(base: str, fake: Fake, state: Path) -> None:
    def no_leak(reply: dict) -> bool:
        text = json.dumps(reply)
        return KEY not in text and "upstream.example" not in text and "secret.example" not in text and \
            "127.0.0.1:" + fake.base.rsplit(":", 1)[1] not in text

    # images: base64 reply, big enough to be lifted out before JSON.parse
    r = tool(base, "com", "image", {"prompt": "a cat", "model": "m-b64"})
    m = HEX_FILE.search(r.get("image_url", ""))
    check(r["code"] == 0 and m and r["image_urls"] == [r["image_url"]] and r["expires_in_days"] == 15,
          "image (b64 reply, 150 KB, lifted) is stored and linked under coze/<32 hex>.png")
    status, headers, raw = http("GET", r["image_url"], key=None)
    check(status == 200 and raw == BIG_PNG and headers.get("Content-Type") == "image/png"
          and headers.get("X-Content-Type-Options") == "nosniff", "the stored image is served with the right bytes and type")
    status, headers, raw = http("GET", r["image_url"], key=None, headers={"Range": "bytes=0-7"})
    check(status == 206 and raw == BIG_PNG[:8] and headers.get("Content-Range", "").startswith("bytes 0-7/"),
          "range requests work (206)")
    status, _, raw = http("HEAD", r["image_url"], key=None)
    check(status == 200 and raw == b"", "HEAD works")
    gen = [x for x in fake.seen("/v1/images/generations")][-1]
    check(gen["auth"] == f"Bearer {KEY}" and gen["body"]["model"] == "m-b64", "the key went to the gateway as Bearer")

    r = tool(base, "com", "image", {"prompt": "a cat", "model": "gemini-md-data-image", "aspect_ratio": "16:9", "image_size": "2K"})
    check(r["code"] == 0 and HEX_FILE.search(r["image_url"]), "Nano Banana (markdown data URI, lifted) is stored")
    chat = fake.seen("/v1/chat/completions")[-1]["body"]
    check(chat["extra_body"]["google"]["image_config"] == {"aspect_ratio": "16:9", "image_size": "2K"},
          "aspect ratio and resolution reach the gateway")
    for model in ("gemini-parts-image", "gemini-images-image"):
        r = tool(base, "com", "image", {"prompt": "x", "model": model})
        check(r["code"] == 0, f"{model} (image in message parts) is stored")

    before = len(fake.seen(UPSTREAM_PATH))
    r = tool(base, "com", "image", {"prompt": "a cat", "model": "m-url"})
    got = fake.seen(UPSTREAM_PATH)
    check(r["code"] == 0 and len(got) == before + 1 and got[-1]["auth"] is None and UPSTREAM_PATH not in json.dumps(r),
          "image (link reply): downloaded once without the key; the upstream link is not handed out")
    r = tool(base, "com", "image", {"prompt": "a cat", "model": "gemini-md-link-image"})
    check(r["code"] == 0 and UPSTREAM_PATH not in json.dumps(r), "Nano Banana (markdown link) is downloaded and re-linked")

    # references are passed as links; the Worker never fetches them
    ref = "https://example.invalid/ref.png"
    r = tool(base, "com", "image", {"prompt": "edit", "model": "gemini-md-data-image", "reference_images": [ref]})
    parts = fake.seen("/v1/chat/completions")[-1]["body"]["messages"][0]["content"]
    check(r["code"] == 0 and {"type": "image_url", "image_url": {"url": ref}} in parts,
          "reference images go to the gateway as links (the Worker did not fetch example.invalid)")
    r = tool(base, "com", "image", {"prompt": "edit", "model": "gemini-md-data-image", "reference_images": ["http://example.invalid/a.png"]})
    check(r["code"] == 400 and "https" in r["msg"], "an http reference link is refused")
    r = tool(base, "com", "image", {"prompt": "edit", "model": "m-b64", "reference_images": [ref]})
    check(r["code"] == 400, "reference links on a model that cannot take them are refused before any call")
    r = tool(base, "com", "image", {"prompt": "edit", "model": "gemini-md-data-image", "reference_images": [ref] * 5})
    check(r["code"] == 400, "more than 4 reference images are refused")

    # nothing is stored when anything fails
    count = blobs(state)
    cases = [
        ("m-url-http-redirect", lambda r: r["code"] != 0, "a link that redirects to a dead host fails"),
        ("m-url-html", lambda r: r["code"] != 0, "a link that is not an image fails"),
        ("m-url-huge", lambda r: r["code"] == 413, "an image over the size limit fails with 413"),
        ("m-empty", lambda r: r["code"] != 0 and "no image" in r["msg"], "no image in the reply fails"),
        ("err-429", lambda r: r["code"] == 429, "gateway 429 maps to code 429"),
        ("err-leak", lambda r: r["code"] == 418 and KEY not in r["msg"] and "upstream.example" not in r["msg"],
         "gateway error text is scrubbed of the key and links"),
        ("err-quota", lambda r: r["code"] == 403 and "balance" in r["msg"], "insufficient balance maps to 403"),
        ("gemini-text-image", lambda r: r["code"] != 0 and KEY not in r["msg"], "a text-only reply fails, key scrubbed"),
        ("gpt-image-2", lambda r: r["code"] == 503, "model not in the key's groups maps to 503"),
    ]
    for model, ok, what in cases:
        r = tool(base, "com", "image", {"prompt": "a cat", "model": model})
        check(ok(r) and no_leak(r) and r["image_url"] == "", f"{what} ({model})")
    r = tool(base, "com", "image", {"prompt": "a cat", "model": "m-b64"}, key="sk-wrong-key-000000")
    check(r["code"] == 401 and "key" in r["msg"].lower(), "a wrong key gets 401 from the gateway")
    calls = len(fake.requests)
    r = tool(base, "com", "image", {"prompt": "a cat", "model": "m-b64"}, key=None)
    check(r["code"] == 401 and "Authorization" in r["msg"] and len(fake.requests) == calls, "no key: refused before any call")
    r = tool(base, "cn", "image", {"prompt": "a cat", "model": "m-b64"}, key=None)
    check(r["code"] == 401 and "私有变量" in r["msg"], "coze.cn gets its messages in Chinese")
    for region, model, what in (("com", "some-chat", "a chat model"), ("com", "mj_imagine", "an excluded model"),
                                ("com", "not-a-model", "an unknown model"), ("cn", "m-b64", "a non-domestic model on coze.cn"),
                                ("com", "doubao-seedance-2-0-mini-260615", "a video model on the image tool")):
        calls = len(fake.requests)
        r = tool(base, region, "image", {"prompt": "a cat", "model": model})
        check(r["code"] == 400 and len(fake.requests) == calls, f"{what} is refused before any gateway call")
    r = tool(base, "cn", "image", {"prompt": "a cat", "model": "gemini-md-data-image"})
    check(r["code"] == 0, "Nano Banana is allowed on coze.cn")
    r = tool(base, "com", "image", {"model": "m-b64"})
    check(r["code"] == 400 and "prompt" in r["msg"].lower(), "a missing prompt is refused")
    check(blobs(state) == count + 1, "only the one successful call above wrote to R2")

    status, _, raw = http("POST", f"{base}/coze/com/v1/images", b"{" + b" " * 70000 + b"}")
    check(status == 200 and json.loads(raw)["code"] == 400, "a body over 64 KB is refused")
    status, _, raw = http("POST", f"{base}/coze/com/v1/images", b"not json")
    check(status == 200 and json.loads(raw)["code"] == 400, "a body that is not JSON is refused")

    # video: submit, check until done, store once, reuse on the next check
    r = tool(base, "com", "submit", {"prompt": "waves", "model": "doubao-seedance-2-0-mini-260615", "resolution": "720p",
                                      "seconds": 5, "start_image": "https://example.invalid/first.png"})
    sub = fake.seen("/v1/video/generations")[-1]["body"]
    check(r["code"] == 0 and r["task_id"] == "task_ok_1" and r["status"] == "queued"
          and sub["metadata"] == {"resolution": "720p", "duration": 5} and sub["images"] == ["https://example.invalid/first.png"],
          "video submit returns the task id; parameters and the first-frame link reach the gateway")
    r = tool(base, "com", "status", {"task_id": "task_ok_1"})
    check(r["code"] == 0 and r["status"] == "running" and r["video_url"] == "", "first check: running")
    r = tool(base, "com", "status", {"task_id": "task_ok_1"})
    m = HEX_FILE.search(r["video_url"])
    check(r["code"] == 0 and r["status"] == "succeeded" and m and m.group(2) == "mp4", "second check: succeeded, video stored")
    status, headers, raw = http("GET", r["video_url"], key=None)
    check(status == 200 and raw == MP4 and headers.get("Content-Type") == "video/mp4", "the stored video is served")
    content = len(fake.seen("/v1/videos/"))
    again = tool(base, "com", "status", {"task_id": "task_ok_1"})
    check(again["video_url"] == r["video_url"] and len(fake.seen("/v1/videos/")) == content,
          "a later check reuses the stored video (no second download)")
    check(all(x["auth"] == f"Bearer {KEY}" for x in fake.seen("/v1/videos/")), "the gateway download carried the key")

    http("GET", f"{fake.base}/__content/302", key=None)
    tool(base, "com", "status", {"task_id": "task_ok_2"})
    r = tool(base, "com", "status", {"task_id": "task_ok_2"})
    hop = fake.seen("/upstream/video")
    check(r["status"] == "succeeded" and hop and hop[-1]["auth"] is None, "a gateway redirect is followed without the key")
    http("GET", f"{fake.base}/__content/404", key=None)
    tool(base, "com", "status", {"task_id": "task_ok_3"})
    r = tool(base, "com", "status", {"task_id": "task_ok_3"})
    check(r["status"] == "succeeded" and HEX_FILE.search(r["video_url"]) and "upstream" not in r["video_url"],
          "no gateway download: falls back to the link the gateway returned, re-linked")
    http("GET", f"{fake.base}/__content/200/huge", key=None)
    count = blobs(state)
    tool(base, "com", "status", {"task_id": "task_ok_4"})
    r = tool(base, "com", "status", {"task_id": "task_ok_4"})
    check(r["code"] == 413 and blobs(state) == count, "a video over the size limit is refused and not stored")
    http("GET", f"{fake.base}/__reset", key=None)

    r = tool(base, "com", "status", {"task_id": "task_bad_1"})
    check(r["code"] == 0 and r["status"] == "failed" and KEY not in r["fail_reason"] and "secret.example" not in r["fail_reason"]
          and "refunded" in r["msg"], "a failed task reports failed with a scrubbed reason")
    r = tool(base, "com", "status", {"task_id": "../etc"})
    check(r["code"] == 400, "a malformed task id is refused")
    r = tool(base, "com", "submit", {"prompt": "waves", "model": "err-price"})
    check(r["code"] == 400 and "resolution" in r["msg"], "an unsupported tier maps to a readable 400")
    r = tool(base, "com", "submit", {"prompt": "waves", "model": "doubao-seedance-2-0-mini-260615", "seconds": 99})
    check(r["code"] == 400, "a length the model does not take is refused before any call")
    r = tool(base, "com", "submit", {"prompt": "waves", "model": "doubao-seedance-2-0-mini-260615", "start_image": "ftp://x/y"})
    check(r["code"] == 400, "a non-https first frame is refused")
    r = tool(base, "com", "submit", {"prompt": "waves", "model": "m-b64"})
    check(r["code"] == 400, "an image model on the video tool is refused")

    # file route: only <32 hex>.<allowed ext>, no listing
    name = HEX_FILE.search(tool(base, "com", "image", {"prompt": "x", "model": "m-b64"})["image_url"]).group(1)
    for path in ("/coze/", "/coze", "/", f"/coze/{name}.html", f"/coze/{name}.mp4", f"/coze/{name[:31]}.png",
                 f"/coze/{name.upper()}.png", f"/other/{name}.png", f"/coze/{name}.png/x", f"/coze/x{name}.png"):
        status, _, _ = http("GET", base + path, key=None)
        check(status == 404, f"GET {path} is 404")
    status, _, _ = http("GET", f"{base}/coze/com/v1/images", key=None)
    check(status == 405, "GET on a tool path is 405")
    status, _, _ = http("POST", f"{base}/coze/xx/v1/images", {"prompt": "x"})
    check(status == 404, "an unknown region is 404")
    status, _, _ = http("POST", f"{base}/coze/{name}.png", {"prompt": "x"})
    check(status == 404, "POST to a file path is 404")


if __name__ == "__main__":
    raise SystemExit(main())
