"""Shared client for api.steadyrouter.com: chat, images, video tasks, safe downloads.

Rules every platform relies on:
- A link from an upstream is downloaded at once and never handed to the user.
- The API key only ever goes to the gateway, never to a download host.
- Errors are scrubbed (see errors.py), so they are safe to display.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
import socket
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import requests

from . import _generated as gen
from .classify import classify, family_of, matches_any
from .errors import (
    FileTooLarge,
    SRError,
    ValidationError,
    VideoFailed,
    VideoStillRunning,
    from_response,
    scrub,
)

API_BASE = gen.SITE["api_base"]
MAX_FILE_BYTES = 50 * 1024 * 1024  # Dify's default PLUGIN_MAX_FILE_SIZE
MAX_VIDEO_BYTES = 200 * 1024 * 1024  # for platforms without Dify's file limit
IMAGE_TIMEOUT = 300  # the public docs tell clients to allow 300 seconds
CHAT_TIMEOUT = 300
SHORT_TIMEOUT = 30
DOWNLOAD_TIMEOUT = (15, 120)
POLL_SECONDS = 12  # the public video guide says every 10 to 15 seconds
VIDEO_WAIT_SECONDS = 480
MAX_REDIRECTS = 3
# Proxies in fake-IP mode (Clash, Surge and the like) answer DNS from this range for every host. It is reserved for
# benchmarking, not used by private networks, and is_global is False for it, so without this such users could not download.
_PROXY_FAKE_IP = ipaddress.ip_network("198.18.0.0/15")
RUNNING = {"NOT_START", "SUBMITTED", "QUEUED", "IN_PROGRESS", "RUNNING", "PENDING"}
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*(data:image/[^)\s]+|https?://[^)\s]+)\s*\)")
_BARE_DATA = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=_-]+")
_BARE_LINK = re.compile(r"https?://[^\s\"'<>)\]]+")
# These refuse 2K and 4K outright. A form field cannot depend on another field, so a default of 2K would always fail.
ONE_K_ONLY_MODELS = frozenset({"gemini-3.1-flash-lite-image"})
ONE_K_NOTE = "This model only supports 1K, so 1K was used. 这个型号只支持 1K，已改用 1K。"


def image_size_for(model: str | None, image_size: str | None) -> tuple[str | None, str | None]:
    """The quality to send, and a note for the user when that is not the one they asked for."""
    if model in ONE_K_ONLY_MODELS and image_size and image_size not in ("1K", "auto"):
        return "1K", ONE_K_NOTE
    return image_size, None


@dataclass
class GeneratedFile:
    data: bytes
    mime: str

    @property
    def extension(self) -> str:
        return {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
                "video/mp4": "mp4", "video/webm": "webm"}.get(self.mime, "bin")


@dataclass
class ChatResult:
    text: str
    model: str
    finish_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoStatus:
    task_id: str
    status: str
    progress: str = ""
    fail_reason: str = ""
    _result_url: str = field(default="", repr=False)  # internal: never show it to anyone

    @property
    def done(self) -> bool:
        return self.status == "SUCCESS"

    @property
    def failed(self) -> bool:
        return self.status == "FAILURE"


def sniff(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[4:8] == b"ftyp":
        return "video/mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    return None


def public_host_only(host: str) -> None:
    """Refuse hosts that resolve to private addresses (the plugin may run inside a private network)."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise SRError("The generated file could not be downloaded.") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if addr in _PROXY_FAKE_IP:
            continue
        if not addr.is_global:
            raise SRError("The generated file could not be downloaded.")


def video_download_hint(task_id: str, api_base: str = API_BASE) -> str:
    """How to fetch a video from the gateway itself. Contains no upstream link."""
    return (
        f"Task ID: {task_id}\n"
        f"Download it from SteadyRouter with your API key (the request must carry the key):\n"
        f"GET {api_base}/v1/videos/{task_id}/content with the header Authorization: Bearer YOUR_API_KEY\n"
        "Videos are kept for a limited time only, so save yours soon."
    )


def pricing_models(http: Any = requests, url: str = gen.SITE["pricing_api"]) -> list[dict[str, Any]]:
    """Live rows from the public model list. Only the name, tags and endpoints are read."""
    reply = http.get(url, timeout=SHORT_TIMEOUT)
    reply.raise_for_status()
    rows = reply.json().get("data") or []
    return [
        {k: row.get(k) for k in ("model_name", "tags", "supported_endpoint_types", "description")}
        for row in rows
    ]


def list_models(category: str, family: str | None = None, *, exclude: Iterable[str] = (),
                fetch: Callable[[], list[dict[str, Any]]] = pricing_models) -> list[str]:
    """Models for a dropdown: live list first, the list shipped in the package if that fails."""
    skip = set(exclude)
    try:
        rows = fetch()
        names = [
            r["model_name"] for r in rows
            if classify(r, gen.CATEGORY_OVERRIDES) == category
            and (family is None or family_of(r["model_name"], gen.FAMILIES) == family)
        ]
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        names = []
    if not names:
        names = [
            m["name"] for m in gen.SHIPPED_MODELS
            if m["category"] == category and (family is None or m["family"] == family)
        ]
    return sorted(n for n in names if n not in skip)


class SRClient:
    def __init__(self, api_key: str, *, base_url: str = API_BASE, session: Any = None,
                 check_host: Callable[[str], None] = public_host_only, https_only: bool = True,
                 poll_seconds: float = POLL_SECONDS, video_wait_seconds: float = VIDEO_WAIT_SECONDS,
                 sleep: Callable[[float], None] = time.sleep, user_agent: str = "steadyrouter-plugin"):
        if not api_key or not api_key.strip():
            raise ValidationError("An API key is required.")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.http = session or requests.Session()
        self.check_host = check_host
        self.https_only = https_only
        self.poll_seconds = poll_seconds
        self.video_wait_seconds = video_wait_seconds
        self.sleep = sleep
        self.user_agent = user_agent

    # ---- transport ----

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "User-Agent": self.user_agent}

    def _call(self, method: str, path: str, *, timeout: float = SHORT_TIMEOUT, **kwargs: Any) -> dict[str, Any]:
        try:
            reply = self.http.request(method, self.base_url + path, headers=self._headers(),
                                      timeout=timeout, allow_redirects=False, **kwargs)
        except requests.Timeout as exc:
            raise SRError("The request timed out. Try again in a little while.") from exc
        except requests.RequestException as exc:
            raise SRError("Could not reach SteadyRouter. Check the network and try again.") from exc
        try:
            body = reply.json()
        except ValueError:
            body = None
        if reply.status_code >= 400 or reply.status_code in (301, 302, 303, 307, 308):
            raise from_response(reply.status_code, body, self.api_key)
        if not isinstance(body, dict):
            raise SRError("SteadyRouter returned a reply that could not be read.", status=reply.status_code)
        return body

    def _read_capped(self, reply: Any, limit: int) -> bytes:
        declared = reply.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > limit:
            raise FileTooLarge("The file is larger than the size limit.", limit=limit)
        chunks, total = [], 0
        for chunk in reply.iter_content(1024 * 256):
            total += len(chunk)
            if total > limit:
                raise FileTooLarge("The file is larger than the size limit.", limit=limit)
            chunks.append(chunk)
        return b"".join(chunks)

    def _check_download_url(self, url: str) -> None:
        parts = urlparse(url)
        if parts.scheme != "https" and self.https_only:
            raise SRError("The generated file could not be downloaded.")
        if parts.scheme not in ("https", "http") or not parts.hostname:
            raise SRError("The generated file could not be downloaded.")
        self.check_host(parts.hostname)

    def _download_public(self, url: str, limit: int) -> bytes:
        """Fetch a link from an upstream: no key, https only, public hosts, bounded size and redirects."""
        for _ in range(MAX_REDIRECTS + 1):
            self._check_download_url(url)
            try:
                reply = self.http.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT, allow_redirects=False,
                                      headers={"User-Agent": self.user_agent})
            except requests.RequestException as exc:
                raise SRError("The generated file could not be downloaded.") from exc
            with reply:
                if reply.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, reply.headers.get("Location", ""))
                    continue
                if reply.status_code != 200:
                    raise SRError("The generated file could not be downloaded.")
                return self._read_capped(reply, limit)
        raise SRError("The generated file could not be downloaded.")

    def check_key(self) -> None:
        """GET /v1/models costs nothing. A wrong key raises SRError."""
        self._call("GET", "/v1/models")

    # ---- chat ----

    def chat(self, model: str, messages: list[dict[str, Any]], *, temperature: float | None = None,
             max_tokens: int | None = None, json_output: bool = False) -> ChatResult:
        """One non-streaming chat completion. Text parts of the reply are joined."""
        if not model:
            raise ValidationError("Choose a model.")
        if not messages:
            raise ValidationError("A prompt is required.")
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens:
            payload["max_completion_tokens"] = max_tokens
        if json_output:
            payload["response_format"] = {"type": "json_object"}
        body = self._call("POST", "/v1/chat/completions", json=payload, timeout=CHAT_TIMEOUT)
        choices = body.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], Mapping) else {}
        message = choice.get("message") if isinstance(choice.get("message"), Mapping) else {}
        content = message.get("content")
        if isinstance(content, list):
            text = "".join(str(p.get("text") or "") for p in content if isinstance(p, Mapping) and p.get("type") == "text")
        else:
            text = "" if content is None else str(content)
        usage = body.get("usage")
        return ChatResult(text=text, model=str(body.get("model") or model),
                          finish_reason=str(choice.get("finish_reason") or ""),
                          usage=dict(usage) if isinstance(usage, Mapping) else {})

    # ---- images ----

    def _file_from_ref(self, ref: str, limit: int) -> GeneratedFile:
        if ref.startswith("data:"):
            return self._file_from_b64(ref.partition(",")[2], limit)
        return self._as_image(self._download_public(ref, limit), limit)

    def _file_from_b64(self, text: str, limit: int) -> GeneratedFile:
        try:
            data = base64.b64decode(text + "==", validate=False)
        except (binascii.Error, ValueError) as exc:
            raise SRError("The model returned an image that could not be read.") from exc
        return self._as_image(data, limit)

    @staticmethod
    def _as_image(data: bytes, limit: int) -> GeneratedFile:
        if len(data) > limit:
            raise FileTooLarge("The file is larger than the size limit.", limit=limit)
        mime = sniff(data)
        if not mime or not mime.startswith("image/"):
            raise SRError("The model returned an image that could not be read.")
        return GeneratedFile(data, mime)

    def _images_from_reply(self, body: Mapping[str, Any], limit: int) -> list[GeneratedFile]:
        files = []
        for item in body.get("data") or []:
            if item.get("b64_json"):
                try:
                    raw = base64.b64decode(item["b64_json"])
                except (binascii.Error, ValueError) as exc:
                    raise SRError("The model returned an image that could not be read.") from exc
                files.append(self._as_image(raw, limit))
            elif item.get("url"):
                files.append(self._file_from_ref(item["url"], limit))
        if not files:
            raise SRError("The model returned no image. Change the prompt and try again.")
        return files

    def _gemini_image(self, model: str, prompt: str, *, aspect_ratio: str | None, image_size: str | None,
                      images: Iterable[GeneratedFile], limit: int) -> list[GeneratedFile]:
        """The native route, because some upstreams ignore size and ratio when asked in the OpenAI format."""
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for image in images:
            parts.append({"inlineData": {"mimeType": image.mime, "data": base64.b64encode(image.data).decode()}})
        generation: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
        config = {k: v for k, v in (("aspectRatio", aspect_ratio), ("imageSize", image_size)) if v and v != "auto"}
        if config:
            generation["imageConfig"] = config
        body = self._call("POST", f"/v1beta/models/{quote(model, safe='')}:generateContent",
                          json={"contents": [{"role": "user", "parts": parts}], "generationConfig": generation},
                          timeout=IMAGE_TIMEOUT)
        candidates = body.get("candidates")
        first = candidates[0] if isinstance(candidates, list) and candidates and isinstance(candidates[0], Mapping) else {}
        content = first.get("content") if isinstance(first.get("content"), Mapping) else {}
        files: list[GeneratedFile] = []
        texts: list[str] = []
        for part in content.get("parts") or []:
            if not isinstance(part, Mapping) or part.get("thought"):  # the model's notes and drafts, not the result
                continue
            inline = part.get("inlineData") or part.get("inline_data")
            linked = part.get("fileData") or part.get("file_data")
            if isinstance(inline, Mapping) and inline.get("data"):
                files.append(self._file_from_b64(str(inline["data"]), limit))
            elif isinstance(linked, Mapping) and (linked.get("fileUri") or linked.get("file_uri")):
                files.append(self._file_from_ref(str(linked.get("fileUri") or linked.get("file_uri")), limit))
            elif part.get("text"):
                texts.append(str(part["text"]))
        if files:
            return files
        text = "\n".join(texts)
        refs = _MD_IMAGE.findall(text) or _BARE_DATA.findall(text) or _BARE_LINK.findall(text)
        if not refs:
            hint = scrub(text or str(first.get("finishReason") or ""), self.api_key)
            raise SRError(f"The model returned no image. {hint}".strip())
        return [self._file_from_ref(ref, limit) for ref in refs]

    def generate_image(self, model: str, prompt: str, *, size: str | None = None, quality: str | None = None,
                       n: int = 1, aspect_ratio: str | None = None, image_size: str | None = None,
                       images: Iterable[GeneratedFile] = (), limit: int = MAX_FILE_BYTES) -> list[GeneratedFile]:
        """Text to image, or image edit when reference images are given. Always returns file bytes."""
        if not prompt or not prompt.strip():
            raise ValidationError("A prompt is required.")
        if not model:
            raise ValidationError("Choose a model.")
        images = list(images)
        if matches_any(model, gen.CHAT_IMAGE_MATCH):
            return self._gemini_image(model, prompt, aspect_ratio=aspect_ratio, image_size=image_size,
                                      images=images, limit=limit)
        fields: dict[str, Any] = {"model": model, "prompt": prompt, "n": n}
        if size and size != "auto":
            fields["size"] = size
        if quality and quality != "auto":
            fields["quality"] = quality
        if images:
            upload = [("image[]", (f"image-{i}.{f.extension}", f.data, f.mime)) for i, f in enumerate(images)]
            body = self._call("POST", "/v1/images/edits", data={k: str(v) for k, v in fields.items()},
                              files=upload, timeout=IMAGE_TIMEOUT)
        else:
            body = self._call("POST", "/v1/images/generations", json=fields, timeout=IMAGE_TIMEOUT)
        return self._images_from_reply(body, limit)

    # ---- video ----

    @staticmethod
    def video_payload(model: str, prompt: str, *, resolution: str | None = None, seconds: int | None = None,
                      start_image: str | None = None) -> dict[str, Any]:
        """Build the request, refusing values the gateway would refuse. Unlisted models pass through."""
        if not prompt or not prompt.strip():
            raise ValidationError("A prompt is required.")
        if not model:
            raise ValidationError("Choose a model.")
        rule = gen.VIDEO_PARAMS.get(model)
        payload: dict[str, Any] = {"model": model, "prompt": prompt}
        resolution = resolution.lower() if resolution else None
        if rule:
            if resolution and resolution not in rule["resolutions"]:
                raise ValidationError(f"{model} takes these resolutions: {', '.join(rule['resolutions'])}.")
            allowed = rule["seconds"]
            if seconds is not None:
                if "values" in allowed and seconds not in allowed["values"]:
                    raise ValidationError(f"{model} takes these lengths in seconds: "
                                          f"{', '.join(map(str, allowed['values']))}.")
                if "min" in allowed and not allowed["min"] <= seconds <= allowed["max"]:
                    raise ValidationError(f"{model} takes {allowed['min']} to {allowed['max']} seconds.")
            if rule["start_image"] == "required" and not start_image:
                raise ValidationError(f"{model} needs a starting image.")
            if rule["start_image"] == "none" and start_image:
                raise ValidationError(f"{model} does not take a starting image.")
        style = rule["style"] if rule else ("metadata" if model.startswith("doubao-seedance-") else "top")
        if style == "metadata":
            meta = {k: v for k, v in (("resolution", resolution), ("duration", seconds)) if v is not None}
            if meta:
                payload["metadata"] = meta
        else:
            if resolution:
                payload["size"] = resolution
            if seconds is not None:
                payload["duration"] = seconds
        if start_image:
            key = rule["image_key"] if rule else ("image" if model.startswith("wan") else "images")
            payload[key] = [start_image] if key == "images" else start_image
        return payload

    def submit_video(self, model: str, prompt: str, **options: Any) -> str:
        payload = self.video_payload(model, prompt, **options)
        body = self._call("POST", "/v1/video/generations", json=payload)
        data = body.get("data") if isinstance(body.get("data"), Mapping) else body
        task_id = data.get("task_id") or data.get("id")
        if not task_id:
            raise SRError("SteadyRouter did not return a task ID.")
        return str(task_id)

    def video_status(self, task_id: str) -> VideoStatus:
        if not task_id or not re.fullmatch(r"[A-Za-z0-9_.:-]+", task_id):
            raise ValidationError("That task ID does not look right.")
        body = self._call("GET", f"/v1/video/generations/{task_id}")
        data = body.get("data") if isinstance(body.get("data"), Mapping) else body
        status = str(data.get("status") or "").upper()
        if status == "COMPLETED":
            status = "SUCCESS"
        elif status == "FAILED":
            status = "FAILURE"
        return VideoStatus(task_id=task_id, status=status, progress=str(data.get("progress") or ""),
                           fail_reason=scrub(data.get("fail_reason"), self.api_key),
                           _result_url=str(data.get("result_url") or data.get("url") or ""))

    def wait_video(self, task_id: str) -> VideoStatus:
        """Check until the task ends. Raises VideoStillRunning with the ID when the wait runs out."""
        deadline = time.monotonic() + self.video_wait_seconds
        while True:
            state = self.video_status(task_id)
            if state.done:
                return state
            if state.failed:
                reason = state.fail_reason or "The upstream did not make the video."
                raise VideoFailed(f"No video was made and the charge is refunded. {reason}")
            if time.monotonic() >= deadline:
                raise VideoStillRunning("The video is not ready yet. Check it later with the task ID.",
                                        task_id=task_id)
            self.sleep(self.poll_seconds)

    def download_video(self, state: VideoStatus, limit: int = MAX_FILE_BYTES) -> GeneratedFile:
        """Prefer the gateway's own download endpoint; the upstream link is only a fallback."""
        data = None
        try:
            reply = self.http.get(f"{self.base_url}/v1/videos/{state.task_id}/content", stream=True,
                                  headers=self._headers(), timeout=DOWNLOAD_TIMEOUT, allow_redirects=False)
            with reply:
                if reply.status_code == 200:
                    data = self._read_capped(reply, limit)
                elif reply.status_code in (301, 302, 303, 307, 308):
                    data = self._download_public(urljoin(self.base_url + "/", reply.headers.get("Location", "")),
                                                 limit)
        except requests.RequestException:
            data = None
        if data is None:
            if not state._result_url:
                raise SRError("The video could not be downloaded.")
            data = self._download_public(state._result_url, limit)
        mime = sniff(data)
        if not mime or not mime.startswith("video/"):
            raise SRError("The video could not be downloaded.")
        return GeneratedFile(data, mime)


__all__ = ["API_BASE", "MAX_FILE_BYTES", "MAX_VIDEO_BYTES", "ChatResult", "GeneratedFile", "SRClient", "VideoStatus",
           "list_models", "pricing_models", "sniff", "video_download_hint"]
