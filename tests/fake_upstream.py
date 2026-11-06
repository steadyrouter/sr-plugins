"""A local stand-in for the gateway and for an upstream file host. No network, no money."""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
KEY = "sk-test-secret-key-123456"
UPSTREAM_PATH = "/upstream/org-private-account/secret-bucket/file"


class Fake:
    def __init__(self, host="127.0.0.1", port=0, public_base=None, png=PNG, mp4=MP4):
        """png / mp4: the bytes served as generated files. The defaults are only headers; pass real files
        when the platform decodes them (ComfyUI turns images into tensors)."""
        self.requests: list[dict] = []
        self.polls: dict[str, int] = {}
        self.png = png
        self.mp4 = mp4
        self.content_status = 200
        self.content_body = mp4
        self.server = ThreadingHTTPServer((host, port), self._handler())
        self.base = public_base or f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def seen(self, prefix):
        return [r for r in self.requests if r["path"].startswith(prefix)]

    def _handler(fake):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _send(self, status, body, ctype="application/json", headers=None):
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def _record(self):
                size = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(size) if size else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = raw
                fake.requests.append({"method": self.command, "path": self.path, "body": body,
                                      "auth": self.headers.get("Authorization"),
                                      "ctype": self.headers.get("Content-Type", "")})
                return body

            def _authed(self):
                if self.headers.get("Authorization") != f"Bearer {KEY}":
                    self._send(401, {"error": {"message": "Invalid token", "code": "invalid"}})
                    return False
                return True

            def do_GET(self):
                if self.path == "/__seen":  # for tests in other languages: what the fake has received so far
                    return self._send(200, [{**r, "body": f"<{len(r['body'])} bytes>"} if isinstance(r["body"], bytes)
                                            else r for r in fake.requests])
                if self.path == "/__reset":
                    fake.requests.clear()
                    fake.polls.clear()
                    fake.content_status, fake.content_body = 200, fake.mp4
                    return self._send(200, {})
                if self.path.startswith("/__content/"):  # /__content/<status>[/huge]
                    parts = self.path.split("/")
                    fake.content_status = int(parts[2])
                    fake.content_body = fake.mp4 + b"\0" * 4096 if parts[3:] == ["huge"] else fake.mp4
                    return self._send(200, {})
                self._record()
                if self.path == "/api/pricing":
                    return self._send(200, {"data": [
                        {"model_name": "gpt-image-2", "tags": "Image", "supported_endpoint_types": ["openai"],
                         "group_prices": {"Secret-Group-01": 1}},
                        {"model_name": "brand-new-image", "tags": "Image", "supported_endpoint_types": ["openai"]},
                        {"model_name": "some-chat", "tags": "Chat", "supported_endpoint_types": ["openai"]},
                    ]})
                if self.path.startswith("/upstream/redirect-http"):
                    return self._send(302, b"", headers={"Location": "http://127.0.0.1:1/x"})
                if self.path.startswith("/upstream/html"):
                    return self._send(200, b"<html>error</html>", "text/html")
                if self.path.startswith("/upstream/huge"):
                    return self._send(200, fake.png + b"\0" * 4096, "image/png")
                if self.path.startswith("/upstream/video"):
                    return self._send(200, fake.mp4, "video/mp4")
                if self.path.startswith("/upstream/"):
                    return self._send(200, fake.png, "image/png")
                if not self._authed():
                    return None
                if self.path == "/v1/models":
                    return self._send(200, {"data": [{"id": "gpt-image-2"}]})
                if self.path.startswith("/v1/video/generations/"):
                    return self._task(self.path.rsplit("/", 1)[1])
                if self.path.startswith("/v1/videos/"):
                    if fake.content_status == 302:
                        return self._send(302, b"", headers={"Location": fake.base + "/upstream/video"})
                    if fake.content_status != 200:
                        return self._send(fake.content_status, {"error": {"message": "gone"}})
                    return self._send(200, fake.content_body, "video/mp4")
                return self._send(404, {"error": {"message": "not found"}})

            def _task(self, task_id):
                count = fake.polls[task_id] = fake.polls.get(task_id, 0) + 1
                data = {"task_id": task_id, "status": "IN_PROGRESS", "progress": "30%", "fail_reason": ""}
                if task_id.startswith("task_ok") and count >= 2:
                    data.update(status="SUCCESS", progress="100%", result_url=fake.base + "/upstream/video")
                if task_id.startswith("task_bad"):
                    data.update(status="FAILURE",
                                fail_reason=f"upstream refused, see https://secret.example/x?k={KEY}")
                return self._send(200, {"code": "success", "message": "", "data": data})

            def do_POST(self):
                body = self._record()
                if not self._authed():
                    return None
                model = body.get("model") if isinstance(body, dict) else None
                if self.path.startswith("/v1/audio/"):
                    return self._send(200, {"text": "hello world"})
                if self.path == "/v1/images/generations":
                    return self._images(model)
                if self.path == "/v1/images/edits":
                    return self._send(200, {"data": [{"b64_json": base64.b64encode(fake.png).decode()}]})
                if self.path == "/v1/chat/completions":
                    return self._chat(model, body)
                if self.path.startswith("/v1beta/models/") and self.path.endswith(":generateContent"):
                    return self._gemini(self.path.split("/")[-1].removesuffix(":generateContent"))
                if self.path == "/v1/embeddings":
                    return self._send(200, {"model": model, "usage": {"prompt_tokens": 2, "total_tokens": 2},
                                            "data": [{"index": 0, "embedding": [0.1, 0.2]}]})
                if self.path == "/v1/rerank":
                    return self._send(200, {"results": [{"index": 0, "relevance_score": 0.2},
                                                        {"index": 1, "relevance_score": 0.9}]})
                if self.path == "/v1/audio/transcriptions":
                    return self._send(200, {"text": "hello world"})
                if self.path == "/v1/video/generations":
                    if model == "err-price":
                        return self._send(400, {"code": "task_price_unsupported", "message": "no such tier"})
                    return self._send(200, {"task_id": "task_ok_1", "id": "task_ok_1", "status": "queued"})
                return self._send(404, {"error": {"message": "not found"}})

            def _images(self, model):
                if model == "m-b64":
                    return self._send(200, {"data": [{"b64_json": base64.b64encode(fake.png).decode()}]})
                if model == "m-url":
                    return self._send(200, {"data": [{"url": fake.base + UPSTREAM_PATH}]})
                if model == "m-url-http-redirect":
                    return self._send(200, {"data": [{"url": fake.base + "/upstream/redirect-http"}]})
                if model == "m-url-html":
                    return self._send(200, {"data": [{"url": fake.base + "/upstream/html"}]})
                if model == "m-url-huge":
                    return self._send(200, {"data": [{"url": fake.base + "/upstream/huge"}]})
                if model == "m-empty":
                    return self._send(200, {"data": []})
                if model == "err-429":
                    return self._send(429, {"error": {"message": "busy at https://upstream.example/a"}})
                if model == "err-leak":
                    return self._send(418, {"error": {"message": f"bad key {KEY} at https://upstream.example/a"}})
                if model == "err-quota":
                    return self._send(403, {"error": {"code": "insufficient_user_quota", "message": "x"}})
                return self._send(503, {"error": {"code": "model_not_found", "message": "secret group list"}})

            def _chat(self, model, body):
                if not str(model).startswith("gemini-"):
                    return self._plain_chat(model, body)
                data_uri = "data:image/png;base64," + base64.b64encode(fake.png).decode()
                link = fake.base + UPSTREAM_PATH
                content = {
                    "gemini-md-data-image": f"Here it is ![img]({data_uri}) done",
                    "gemini-md-link-image": f"![img]({link})",
                    "gemini-bare-image": data_uri,
                    "gemini-text-image": f"Sorry, I cannot. Token {KEY} rejected.",
                    "gemini-badlink-image": f"Sorry, I cannot. See {fake.base}/upstream/html",
                }.get(model)
                message = {"role": "assistant", "content": content}
                if model == "gemini-parts-image":
                    message["content"] = [{"type": "image_url", "image_url": {"url": data_uri}}]
                if model == "gemini-images-image":
                    message.update(content="", images=[{"type": "image_url", "image_url": {"url": data_uri}}])
                return self._send(200, {"choices": [{"message": message}]})

            def _gemini(self, model):
                encoded = base64.b64encode(fake.png).decode()
                data_uri = "data:image/png;base64," + encoded
                link = fake.base + UPSTREAM_PATH
                image = {"inlineData": {"mimeType": "image/png", "data": encoded}}
                draft = {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(b"a draft").decode()},
                         "thought": True}
                parts = {
                    "gemini-snake-image": [{"inline_data": {"mime_type": "image/png", "data": encoded}}],
                    "gemini-thought-image": [{"text": "Planning.", "thought": True}, draft, image],
                    "gemini-file-image": [{"fileData": {"mimeType": "image/png", "fileUri": link}}],
                    "gemini-md-data-image": [{"text": f"Here it is ![img]({data_uri}) done"}],
                    "gemini-md-link-image": [{"text": f"![img]({link})"}],
                    "gemini-bare-image": [{"text": data_uri}],
                    "gemini-text-image": [{"text": f"Sorry, I cannot. Token {KEY} rejected."}],
                    "gemini-badlink-image": [{"text": f"Sorry, I cannot. See {fake.base}/upstream/html"}],
                    "gemini-thoughts-only-image": [{"text": "Only thinking.", "thought": True}],
                }.get(model, [image])
                if model == "gemini-blocked-image":
                    return self._send(200, {"candidates": [{"finishReason": "IMAGE_SAFETY"}]})
                return self._send(200, {"candidates": [{"content": {"role": "model", "parts": parts},
                                                        "finishReason": "STOP"}]})

            def _plain_chat(self, model, body):
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for delta in ({"role": "assistant", "content": "Hel"}, {"content": "lo"}):
                        chunk = {"id": "c", "model": model, "choices": [{"index": 0, "delta": delta}]}
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    last = {"id": "c", "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}
                    self.wfile.write(f"data: {json.dumps(last)}\n\ndata: [DONE]\n\n".encode())
                    self.close_connection = True
                    return None
                return self._send(200, {"id": "c", "model": model, "usage": {"prompt_tokens": 1, "completion_tokens": 2,
                                                                             "total_tokens": 3},
                                        "choices": [{"index": 0, "finish_reason": "stop",
                                                     "message": {"role": "assistant", "content": "Hello"}}]})

        return Handler
