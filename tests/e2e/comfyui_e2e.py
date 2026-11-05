#!/usr/bin/env python3
"""Run the ComfyUI package inside a real ComfyUI against the fake gateway. Local only, nothing is charged.

usage: SR_COMFYUI=<ComfyUI checkout> <ComfyUI venv>/bin/python tests/e2e/comfyui_e2e.py [--browser] [--keep]

Builds a --base-url test copy of the package into a temporary ComfyUI base directory (custom_nodes, user, output),
saves the API key in that ComfyUI's settings file the way the settings panel does, starts `main.py --cpu` on
127.0.0.1, queues workflows through POST /prompt, reads /history, and checks the saved files and what the fake
received. Stops ComfyUI at the end. Exits non-zero on any failure.

--browser also opens the settings panel in a headless Chrome for Testing (comfyui_settings.cjs; needs node,
playwright-core under SR_NODE_TOOLCHAIN and the browser under ~/.cache/chrome-for-testing), types a key there and
runs one more node to show that the key saved by the panel is the one the nodes send.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tools")]
import av
from fake_upstream import KEY, Fake
from PIL import Image

NODE_IDS = ["SteadyRouterChat", "SteadyRouterImage", "SteadyRouterNanoBanana", "SteadyRouterGPTImage",
            "SteadyRouterSeedream", "SteadyRouterQwenImage", "SteadyRouterVideo", "SteadyRouterSeedance",
            "SteadyRouterWanVideo", "SteadyRouterVidu", "SteadyRouterVideoTask"]
PACKAGE_DIR = "comfyui-steadyrouter"


def media() -> tuple[bytes, bytes]:
    """A real PNG and a real H.264 MP4, so ComfyUI can decode what the fake returns."""
    png = BytesIO()
    Image.new("RGB", (8, 6), (200, 30, 30)).save(png, format="PNG")
    mp4 = BytesIO()
    with av.open(mp4, "w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=8)
        stream.width, stream.height, stream.pix_fmt = 16, 16, "yuv420p"
        for i in range(8):
            for packet in stream.encode(av.VideoFrame.from_image(Image.new("RGB", (16, 16), (i * 30, 0, 0)))):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return png.getvalue(), mp4.getvalue()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(base: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as reply:
            raw = reply.read()
    except urllib.error.HTTPError as err:
        raw = err.read()
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def sr(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


def save_image(source: str, prefix: str) -> dict:
    return {"class_type": "SaveImage", "inputs": {"images": [source, 0], "filename_prefix": prefix}}


def save_video(source: str, prefix: str) -> dict:
    return {"class_type": "SaveVideo", "inputs": {"video": [source, 0], "filename_prefix": prefix, "format": "mp4"}}


def workflows() -> dict[str, dict]:
    image = {"prompt": "a cat", "seed": 1}
    video = {"prompt": "waves", "seconds": 5, "wait_minutes": 2, "seed": 1}
    return {
        "chat": {"1": sr("SteadyRouterChat", model="gemini-3.8-flash", prompt="hi", seed=0, system="be brief",
                         max_tokens=32, custom_model="some-chat"),
                 "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 0]}}},
        "b64": {"1": sr("SteadyRouterImage", model="gpt-image-2-c", custom_model="m-b64", **image),
                "2": save_image("1", "sr/b64")},
        "link": {"1": sr("SteadyRouterGPTImage", model="gpt-image-2-c", custom_model="m-url", size="1536x1024",
                         quality="high", **image),
                 "2": save_image("1", "sr/link")},
        "gemini": {"1": sr("SteadyRouterNanoBanana", model="gemini-3.1-flash-image", custom_model="gemini-md-link-image",
                           aspect_ratio="16:9", resolution="2K", **image),
                   "2": save_image("1", "sr/gemini")},
        "edit": {"1": sr("SteadyRouterImage", model="gpt-image-2-c", custom_model="m-b64", prompt="first", seed=2),
                 "2": sr("SteadyRouterSeedream", model="doubao-seedream-4-5-251128", custom_model="m-b64",
                         prompt="edit it", seed=3, images=["1", 0]),
                 "3": save_image("2", "sr/edit")},
        "video": {"1": sr("SteadyRouterVidu", model="viduq3-turbo", resolution="540p", **video),
                  "2": save_video("1", "sr/video"),
                  "3": {"class_type": "PreviewAny", "inputs": {"source": ["1", 1]}}},
        "frame": {"1": sr("SteadyRouterImage", model="gpt-image-2-c", custom_model="m-b64", prompt="frame", seed=4),
                  "2": sr("SteadyRouterSeedance", model="doubao-seedance-2-0-260128", resolution="720p",
                          start_image=["1", 0], **{**video, "prompt": "from a frame"}),
                  "3": save_video("2", "sr/frame")},
        "task_bad": {"1": sr("SteadyRouterVideoTask", task_id="task_bad_7", wait_minutes=1),
                     "2": save_video("1", "sr/bad")},
        "leak": {"1": sr("SteadyRouterImage", model="gpt-image-2-c", custom_model="err-leak", **image),
                 "2": save_image("1", "sr/leak")},
    }


def wait_for(base: str, proc: subprocess.Popen, seconds: int = 180) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            http(base, "/system_stats")
            return True
        except OSError:
            time.sleep(1)
    return False


def run_all(base: str, graphs: dict[str, dict] | None = None) -> dict[str, dict]:
    results = {}
    for name, graph in (graphs or workflows()).items():
        queued = http(base, "/prompt", {"prompt": graph, "client_id": "sr-e2e"})
        if not isinstance(queued, dict) or "prompt_id" not in queued:
            results[name] = {"rejected": queued}
            continue
        pid = queued["prompt_id"]
        deadline = time.monotonic() + 200
        while time.monotonic() < deadline:
            history = http(base, f"/history/{pid}")
            status = history.get(pid, {}).get("status", {}) if isinstance(history, dict) else {}
            if status.get("completed") is not None and status.get("status_str") in ("success", "error"):
                results[name] = history[pid]
                break
            time.sleep(0.5)
        else:
            results[name] = {"timeout": True}
    return results


def error_of(result: dict) -> str:
    for kind, data in result.get("status", {}).get("messages", []):
        if kind == "execution_error":
            return f"{data.get('exception_type', '')}: {data.get('exception_message', '')}"
    return ""


def check(results: dict[str, dict], fake: Fake, out: Path) -> list[str]:
    problems = []

    def expect(ok, what):
        if not ok:
            problems.append(what)

    def ok(name):
        status = results[name].get("status", {}).get("status_str")
        expect(status == "success", f"{name}: {status} {error_of(results[name]) or results[name]}")
        return status == "success"

    if ok("chat"):
        expect(results["chat"]["outputs"]["2"]["text"] == ["Hello"], f"chat: {results['chat']['outputs']}")
    for name in ("b64", "link", "gemini", "edit"):
        if ok(name):
            node = "3" if name == "edit" else "2"
            files = results[name]["outputs"][node]["images"]
            with Image.open(out / files[0]["subfolder"] / files[0]["filename"]) as saved:
                expect(saved.size == (8, 6), f"{name}: saved image is {saved.size}")
    for name in ("video", "frame"):
        if ok(name):
            node = "2" if name == "video" else "3"
            saved = results[name]["outputs"][node]
            item = (saved.get("images") or saved.get("videos") or saved.get("gifs") or [{}])[0]
            path = out / item.get("subfolder", "") / item.get("filename", "missing")
            expect(path.exists() and path.stat().st_size > 100, f"{name}: no saved video {saved}")
    if results["video"].get("outputs"):
        expect(results["video"]["outputs"]["3"]["text"] == ["task_ok_1"], f"task id: {results['video']['outputs']}")
    for name, words in (("task_bad", "refunded"), ("leak", "418")):
        text = error_of(results[name])
        expect(words in text and "SteadyRouterError" in text, f"{name}: error was {text!r}")
        expect(KEY not in text and "http" not in text and "secret" not in text, f"{name}: error not clean {text!r}")
        tb = json.dumps(results[name])
        expect(KEY not in tb and "secret.example" not in tb and "upstream.example" not in tb, f"{name}: leak in history")
    upstream = [r for r in fake.requests if r["path"].startswith("/upstream/")]
    expect(upstream and all(r["auth"] is None for r in upstream), f"upstream requests: {upstream}")
    gateway = [r for r in fake.requests if r["path"].startswith("/v1/")]
    expect(gateway and all(r["auth"] == f"Bearer {KEY}" for r in gateway), "gateway requests without the key")
    chats = [r["body"] for r in fake.requests if r["path"] == "/v1/chat/completions"]
    text_chat = [b for b in chats if b.get("model") == "some-chat"]
    expect(text_chat and text_chat[0].get("max_completion_tokens") == 32
           and text_chat[0]["messages"][0] == {"role": "system", "content": "be brief"}, f"chat body: {text_chat}")
    gemini = [b for b in chats if str(b.get("model")).startswith("gemini")]
    expect(gemini and gemini[0].get("extra_body") == {"google": {"image_config": {"aspect_ratio": "16:9",
                                                                                   "image_size": "2K"}}},
           f"gemini body: {gemini}")
    gens = [r["body"] for r in fake.requests if r["path"] == "/v1/images/generations"]
    expect(any(b.get("size") == "1536x1024" and b.get("quality") == "high" for b in gens), f"gpt image: {gens}")
    edits = [r for r in fake.requests if r["path"] == "/v1/images/edits"]
    expect(edits and edits[0]["ctype"].startswith("multipart/form-data"), f"edit: {edits}")
    videos = [r["body"] for r in fake.requests if r["path"] == "/v1/video/generations"]
    vidu = [b for b in videos if b.get("model") == "viduq3-turbo"]
    expect(vidu and vidu[0].get("size") == "540p" and vidu[0].get("duration") == 5, f"vidu: {videos}")
    seedance = [b for b in videos if b.get("model", "").startswith("doubao-seedance")]
    expect(seedance and seedance[0].get("metadata") == {"resolution": "720p", "duration": 5}
           and seedance[0]["images"][0].startswith("data:image/png;base64,"), f"seedance: {videos}")
    return problems


def browser_check(base: str, work: Path, fake: Fake) -> list[str]:
    chrome = sorted(glob.glob(os.path.expanduser("~/.cache/chrome-for-testing/chrome/linux-*/chrome-linux64/chrome")))
    modules = Path(os.environ.get("SR_NODE_TOOLCHAIN", "/nonexistent")) / "node_modules"
    if not chrome or not (modules / "playwright-core").exists():
        return ["--browser: Chrome for Testing or playwright-core (SR_NODE_TOOLCHAIN) not found"]
    shot = work / "settings.png"
    # Chrome puts its singleton socket under TMPDIR; a long TMPDIR goes past the 108-byte socket path limit and Chrome
    # aborts on start, so it gets the system default.
    env = {k: v for k, v in os.environ.items() if k != "TMPDIR"} | {"NODE_PATH": str(modules)}
    done = subprocess.run(["node", str(HERE / "comfyui_settings.cjs"), base, chrome[-1], str(work / "chrome-profile"),
                           str(shot)], env=env, capture_output=True, text=True, timeout=240, check=False)
    print(done.stdout[-2000:], done.stderr[-2000:])
    if done.returncode:
        return ["settings UI check failed"]
    fake.requests.clear()  # the next run must carry the key typed in the browser, which the fake does not know
    result = run_all(base, {"typed": {"1": sr("SteadyRouterChat", model="gemini-3.8-flash", prompt="typed key", seed=9,
                                              custom_model="some-chat"),
                                      "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 0]}}}})["typed"]
    sent = [r["auth"] for r in fake.requests if r["path"] == "/v1/chat/completions"]
    if sent != ["Bearer sk-typed-in-browser-0000"] or "API key is wrong" not in error_of(result):
        return [f"key from the settings panel not used: {sent} {error_of(result)}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", action="store_true", help="keep the temporary ComfyUI base directory")
    parser.add_argument("--browser", action="store_true", help="also check the settings panel in a headless browser")
    args = parser.parse_args()
    comfyui = Path(os.environ["SR_COMFYUI"]).resolve()
    work = Path(tempfile.mkdtemp(prefix="sr-comfyui-e2e-"))
    png, mp4 = media()
    fake = Fake(png=png, mp4=mp4)
    proc = None
    try:
        import common
        from build import load_builder
        load_builder("comfyui").build(common.load_context(fake.base), work / "custom_nodes" / PACKAGE_DIR)
        settings = work / "user" / "default" / "comfy.settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"SteadyRouter.ApiKey": KEY}))  # what the settings panel saves
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = {k: v for k, v in os.environ.items() if k != "STEADYROUTER_API_KEY"}
        log = (work / "comfyui.log").open("w")
        proc = subprocess.Popen([sys.executable, "main.py", "--cpu", "--listen", "127.0.0.1", "--port", str(port),
                                 "--base-directory", str(work), "--disable-auto-launch", "--offline",
                                 "--database-url", "sqlite:///:memory:"],
                                cwd=comfyui, env=env, stdout=log, stderr=subprocess.STDOUT)
        if not wait_for(base, proc):
            print((work / "comfyui.log").read_text()[-4000:])
            print("comfyui e2e: ComfyUI did not start")
            return 1
        info = http(base, "/object_info")
        missing = [n for n in NODE_IDS if n not in info]
        extensions = http(base, "/extensions")
        script = next((e for e in extensions if e.endswith("/steadyrouter.js")), None)
        served = urllib.request.urlopen(base + script, timeout=10).read().decode() if script else ""
        problems = [f"nodes not loaded: {missing}"] if missing else []
        if "SteadyRouter.ApiKey" not in served or "'password'" not in served:
            problems.append(f"settings script not served: {script} {extensions}")
        results = run_all(base)
        for name, result in results.items():
            if "status" not in result:
                problems.append(f"{name}: {result}")
        if not problems:
            problems += check(results, fake, work / "output")
        if args.browser and not problems:
            problems += browser_check(base, work, fake)
        for problem in problems:
            print("FAIL:", problem)
        if problems:
            print((work / "comfyui.log").read_text()[-6000:])
        if args.keep and args.browser:
            print("settings screenshot:", work / "settings.png")
        print("comfyui e2e:", "ok" if not problems else f"{len(problems)} problems")
        return 1 if problems else 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        fake.close()
        if args.keep:
            print("kept", work)
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
