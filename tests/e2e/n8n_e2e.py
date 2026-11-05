#!/usr/bin/env python3
"""Run the n8n package inside a real n8n (docker) against the fake gateway. Local only, nothing is charged.

usage: SR_NODE_TOOLCHAIN=<toolchain> python tests/e2e/n8n_e2e.py [--image n8nio/n8n:2.45.7] [--keep]

Builds a --base-url test copy of the package, mounts it where `n8n-node dev` would put it
(~/.n8n/custom/node_modules), imports a credential and a few workflows with the n8n CLI, runs each with
`n8n execute`, and checks the results and what the fake received. The container runs with host networking
so it can reach the fake on 127.0.0.1; it listens on nothing else. Exits non-zero on any failure.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from fake_upstream import KEY, Fake
from test_n8n import build_test_package

PORT = 9010
PKG = "n8n-nodes-steadyrouter"
# Packages in ~/.n8n/custom load under the CUSTOM prefix (as in `n8n-node dev`); from npm they load as
# n8n-nodes-steadyrouter.<name>. The node code is the same either way.
NODE = "CUSTOM.steadyRouter"
CHAT = "CUSTOM.lmChatSteadyRouter"
CRED = {"steadyRouterApi": {"id": "srcred0000000100", "name": "SteadyRouter test"}}


def node(name: str, params: dict, x: int, type_: str = NODE, creds: bool = True) -> dict:
    out = {"id": name, "name": name, "type": type_, "typeVersion": 1, "position": [x, 0], "parameters": params}
    if creds:
        out["credentials"] = CRED
    return out


def workflow(wid: str, nodes: list[dict], extra_connections: dict | None = None) -> dict:
    trigger = {"id": "start", "name": "Start", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1,
               "position": [0, 0], "parameters": {}}
    chain = [trigger] + [n for n in nodes if n["type"] != CHAT]
    connections = {a["name"]: {"main": [[{"node": b["name"], "type": "main", "index": 0}]]} for a, b in itertools.pairwise(chain)}
    connections.update(extra_connections or {})
    return {"id": wid, "name": wid, "nodes": [trigger] + nodes, "connections": connections, "active": False,
            "settings": {"executionOrder": "v1"}, "pinData": {}}


def workflows() -> list[dict]:
    text = {"resource": "text", "operation": "message", "model": "some-chat", "prompt": "hi", "simplify": True,
            "options": {"maxTokens": 32}}
    gen = {"resource": "image", "operation": "generate", "prompt": "a cat", "options": {}}
    video = {"resource": "video", "operation": "generate", "model": "viduq3-turbo", "prompt": "waves",
             "waitForCompletion": True, "options": {"resolution": "540p", "seconds": 5}}
    chat_model = node("Model", {"model": "some-chat", "options": {"maxTokens": 32}}, 200, CHAT)
    chain = {"id": "Chain", "name": "Chain", "type": "@n8n/n8n-nodes-langchain.chainLlm", "typeVersion": 1.7,
             "position": [400, 0], "parameters": {"promptType": "define", "text": "hi"}}
    return [
        workflow("srtext0000000100", [node("Text", text, 200)]),
        workflow("srb6400000000100", [node("Image", {**gen, "model": "m-b64"}, 200)]),
        workflow("srurl00000000100", [node("Image", {**gen, "model": "m-url"}, 200)]),
        workflow("srgemini00000100", [node("Image", {**gen, "model": "gemini-md-link-image",
                                                   "options": {"aspectRatio": "16:9"}}, 200)]),
        workflow("sredit0000000100", [node("Image", {**gen, "model": "m-b64"}, 200),
                                    node("Edit", {**gen, "operation": "edit", "model": "m-b64",
                                                  "binaryPropertyNames": "data"}, 400)]),
        workflow("srvideo000000100", [node("Video", video, 200)]),
        workflow("srstatus00000100", [node("Status", {"resource": "video", "operation": "getStatus",
                                                    "taskId": "task_bad_9"}, 200)]),
        workflow("srleak0000000100", [node("Image", {**gen, "model": "err-leak"}, 200)]),
        workflow("srchain000000100", [chat_model, chain],
                 {"Model": {"ai_languageModel": [[{"node": "Chain", "type": "ai_languageModel", "index": 0}]]}}),
    ]


def last_output(run: dict, name: str) -> list[dict]:
    task = run["data"]["resultData"]["runData"][name][-1]
    return task["data"]["main"][0] if task.get("data") else []


def run_error(run: dict) -> str:
    err = run["data"]["resultData"].get("error") or {}
    return f"{err.get('message', '')} {err.get('description', '')}"


def check(results: dict[str, dict], fake: Fake) -> list[str]:
    problems = []

    def expect(ok: bool, what: str):
        if not ok:
            problems.append(what)

    text = last_output(results["srtext0000000100"], "Text")
    expect(text and text[0]["json"].get("text") == "Hello", f"text: {text}")
    for wid, name in (("srb6400000000100", "Image"), ("srurl00000000100", "Image"), ("srgemini00000100", "Image"),
                      ("sredit0000000100", "Edit")):
        out = last_output(results[wid], name)
        binary = out[0].get("binary", {}).get("data", {}) if out else {}
        expect(binary.get("mimeType") == "image/png", f"{wid}: no image in output {out}")
    video = last_output(results["srvideo000000100"], "Video")
    expect(video and video[0].get("binary", {}).get("data", {}).get("mimeType") == "video/mp4", f"video: {video}")
    status = last_output(results["srstatus00000100"], "Status")
    expect(status and status[0]["json"].get("failed") is True and "secret.example" not in json.dumps(status),
           f"status: {status}")
    leak = run_error(results["srleak0000000100"])
    expect("418" in leak and KEY not in leak and "upstream.example" not in leak, f"error text: {leak}")
    chain = last_output(results["srchain000000100"], "Chain")
    expect(chain and "Hello" in json.dumps(chain[0]["json"]), f"chat model via LLM chain: {chain} {run_error(results['srchain000000100'])}")
    # what the fake saw
    upstream = [r for r in fake.requests if r["path"].startswith("/upstream/")]
    expect(upstream and all(r["auth"] is None for r in upstream), f"upstream requests carried a key: {upstream}")
    gateway = [r for r in fake.requests if r["path"].startswith("/v1/")]
    expect(gateway and all(r["auth"] == f"Bearer {KEY}" for r in gateway), "gateway requests without the key")
    edits = [r for r in fake.requests if r["path"] == "/v1/images/edits"]
    expect(edits and edits[0]["ctype"].startswith("multipart/form-data; boundary="), f"edit request: {edits}")
    chats = [r for r in fake.requests if r["path"] == "/v1/chat/completions" and isinstance(r["body"], dict)]
    gemini = [r for r in chats if r["body"].get("model", "").startswith("gemini")]
    expect(gemini and gemini[0]["body"].get("extra_body") == {"google": {"image_config": {"aspect_ratio": "16:9"}}},
           f"gemini request: {gemini}")
    # The Text resource sends max_completion_tokens; the chat model goes through LangChain, which sends max_tokens
    # (and switches to max_completion_tokens for reasoning models by itself).
    capped = [r for r in chats if r["body"].get("model") == "some-chat"
              and 32 in (r["body"].get("max_completion_tokens"), r["body"].get("max_tokens"))]
    expect(len(capped) >= 2, f"chat requests: {[r['body'] for r in chats]}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", default="n8nio/n8n:2.45.7")
    parser.add_argument("--keep", action="store_true", help="keep the temporary n8n folder")
    args = parser.parse_args()
    toolchain = Path(os.environ["SR_NODE_TOOLCHAIN"]).resolve()
    work = Path(tempfile.mkdtemp(prefix="sr-n8n-e2e-"))
    fake = Fake("127.0.0.1", PORT)
    try:
        package = build_test_package(fake.base, work / "package")
        (package / "node_modules").unlink()
        (package / "node_modules").mkdir()  # mount point for the toolchain's node_modules
        home = work / "home"
        (home / "custom" / "node_modules").mkdir(parents=True)
        (home / "creds.json").write_text(json.dumps([{"id": CRED["steadyRouterApi"]["id"], "name": "SteadyRouter test",
                                                      "type": "steadyRouterApi", "data": {"apiKey": KEY}}]))
        flows = workflows()
        (home / "workflows.json").write_text(json.dumps(flows))
        runs = "; ".join(f"n8n execute --id={w['id']} --rawOutput > /home/node/.n8n/out-{w['id']}.json 2>/home/node/.n8n/err-{w['id']}.txt"
                         for w in flows)
        script = ("set -e; n8n import:credentials --input=/home/node/.n8n/creds.json; "
                  "n8n import:workflow --input=/home/node/.n8n/workflows.json; "
                  f"n8n export:nodes --output=/home/node/.n8n/nodes.json >/dev/null; set +e; {runs}")
        mount = "/home/node/.n8n/custom/node_modules/" + PKG
        cmd = ["docker", "run", "--rm", "--network", "host", "--user", f"{os.getuid()}:{os.getgid()}",
               "-e", "N8N_DIAGNOSTICS_ENABLED=false", "-e", "N8N_VERSION_NOTIFICATIONS_ENABLED=false",
               "-e", "N8N_LISTEN_ADDRESS=127.0.0.1", "-e", "N8N_RUNNERS_BROKER_LISTEN_ADDRESS=127.0.0.1",
               "-e", "HOME=/home/node",
               "-v", f"{home}:/home/node/.n8n", "-v", f"{package}:{mount}:ro",
               "-v", f"{toolchain / 'node_modules'}:{mount}/node_modules:ro",
               "--entrypoint", "sh", args.image, "-c", script]
        done = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=900)
        print(done.stdout[-3000:], done.stderr[-3000:], sep="\n")
        types = {n["name"] for n in json.loads((home / "nodes.json").read_text())}
        loaded = {NODE, CHAT} <= types
        print("our nodes loaded:", loaded)
        results = {}
        for w in flows:
            raw = (home / f"out-{w['id']}.json").read_text()
            # Failed runs print log lines and a stack before the JSON; the JSON starts on a line of its own.
            start = re.search(r"^\{\s*$", raw, re.MULTILINE)
            try:
                results[w["id"]] = json.JSONDecoder().raw_decode(raw[start.start():])[0] if start else {}
            except ValueError:
                print(f"{w['id']}: could not parse output:\n{raw[:2000]}\n{(home / f'err-{w['id']}.txt').read_text()[-2000:]}")
                results[w["id"]] = {"data": {"resultData": {"runData": {}}}}
        try:
            problems = ([] if loaded else ["nodes not loaded"]) + check(results, fake)
        except (KeyError, IndexError, TypeError) as exc:
            problems = [f"unexpected output shape: {exc!r}"]
            for wid, res in results.items():
                print(wid, json.dumps(res)[:1500])
        for problem in problems:
            print("FAIL:", problem)
        print("n8n e2e:", "ok" if not problems else f"{len(problems)} problems")
        return 1 if problems else 0
    finally:
        fake.close()
        if args.keep:
            print("kept", work)
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
