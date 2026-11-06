"""Behaviour shared by the tools. Mixins on purpose: the SDK allows one Tool subclass per source file."""

from __future__ import annotations

import base64
import re
from collections.abc import Generator
from typing import Any

from dify_plugin.entities import I18nObject, ParameterOption
from srclient import (
    FileTooLarge,
    GeneratedFile,
    SRClient,
    SRError,
    VideoFailed,
    VideoStatus,
    VideoStillRunning,
    image_size_for,
    list_models,
    sniff,
    video_download_hint,
)
from srclient import _generated as gen
from srclient.client import API_BASE

from tools._site import TEST_BUILD

MAX_REFERENCE_IMAGES = 10


def client_for(tool: Any) -> SRClient:
    options: dict[str, Any] = {"user_agent": "steadyrouter-dify"}
    if TEST_BUILD:  # a build made with --base-url talks to a fake gateway on a private address
        options.update(check_host=lambda _host: None, https_only=False)
    return SRClient(tool.runtime.credentials.get("api_key") or "", **options)


def to_options(names: list[str]) -> list[ParameterOption]:
    return [ParameterOption(value=name, label=I18nObject(en_US=name)) for name in names]


def file_name(prefix: str, index: int, extension: str) -> str:
    return f"{re.sub(r'[^A-Za-z0-9._-]+', '-', prefix)}-{index}.{extension}"


def read_upload(upload: Any) -> GeneratedFile:
    data = upload.blob
    mime = sniff(data) or upload.mime_type or "application/octet-stream"
    return GeneratedFile(data, mime)


class ImageTool:
    FAMILY: str | None = None
    ONLY: str | None = None  # a model-name prefix, for a plugin named after one model in a family

    def _fetch_parameter_options(self, parameter: str) -> list[ParameterOption]:
        if parameter != "model":
            return []
        names = list_models("image", self.FAMILY, exclude=gen.EXCLUDE["image-tools"])
        return to_options([n for n in names if n.startswith(self.ONLY or "")])

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[Any, None, None]:
        uploads = tool_parameters.get("images") or []
        uploads = uploads if isinstance(uploads, list) else [uploads]
        if len(uploads) > MAX_REFERENCE_IMAGES:
            raise ValueError(f"At most {MAX_REFERENCE_IMAGES} reference images are accepted.")
        references = [read_upload(u) for u in uploads]
        model = tool_parameters.get("model")
        image_size, note = image_size_for(model, tool_parameters.get("image_size"))
        try:
            files = client_for(self).generate_image(
                model,
                tool_parameters.get("prompt") or "",
                size=tool_parameters.get("size"),
                quality=tool_parameters.get("quality"),
                aspect_ratio=tool_parameters.get("aspect_ratio"),
                image_size=image_size,
                images=references,
            )
        except SRError as exc:
            raise ValueError(str(exc)) from None
        if note:
            yield self.create_text_message(note)
        for index, item in enumerate(files):
            yield self.create_blob_message(
                blob=item.data,
                meta={"mime_type": item.mime, "filename": file_name(model, index, item.extension)},
            )


def _deliver_video(tool: Any, client: SRClient, state: VideoStatus) -> Generator[Any, None, None]:
    yield tool.create_json_message({"task_id": state.task_id, "status": "SUCCESS"})
    try:
        video = client.download_video(state)
    except FileTooLarge:
        yield tool.create_text_message(
            "The video is ready but larger than the 50 MB file limit here, so it was not attached.\n"
            + video_download_hint(state.task_id, API_BASE)
        )
        return
    yield tool.create_blob_message(
        blob=video.data,
        meta={"mime_type": video.mime, "filename": file_name(state.task_id, 0, video.extension)},
    )


class VideoTool:
    FAMILY: str | None = None

    def _fetch_parameter_options(self, parameter: str) -> list[ParameterOption]:
        if parameter != "model":
            return []
        return to_options(list_models("video", self.FAMILY))

    @staticmethod
    def _start_image(parameters: dict[str, Any]) -> str | None:
        upload = parameters.get("start_image")
        if upload:
            item = read_upload(upload)
            return f"data:{item.mime};base64,{base64.b64encode(item.data).decode()}"
        return parameters.get("start_image_url") or None

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[Any, None, None]:
        client = client_for(self)
        seconds = tool_parameters.get("seconds")
        try:
            task_id = client.submit_video(
                tool_parameters.get("model"),
                tool_parameters.get("prompt") or "",
                resolution=tool_parameters.get("resolution"),
                seconds=int(seconds) if seconds is not None else None,
                start_image=self._start_image(tool_parameters),
            )
            state = client.wait_video(task_id)
            yield from _deliver_video(self, client, state)
        except VideoStillRunning as exc:
            yield self.create_json_message({"task_id": exc.task_id, "status": "IN_PROGRESS"})
            yield self.create_text_message(
                f"The video is still being made. Task ID: {exc.task_id}. Use Check Video Task in a few minutes."
            )
        except SRError as exc:
            raise ValueError(str(exc)) from None


class CheckVideoTool:
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[Any, None, None]:
        client = client_for(self)
        task_id = (tool_parameters.get("task_id") or "").strip()
        try:
            state = client.video_status(task_id)
            if state.failed:
                reason = state.fail_reason or "The upstream did not make the video."
                raise VideoFailed(f"No video was made and the charge is refunded. {reason}")
            if not state.done:
                yield self.create_json_message({"task_id": task_id, "status": state.status, "progress": state.progress})
                yield self.create_text_message(
                    f"Still running ({state.progress or state.status}). Check again in a little while."
                )
                return
            yield from _deliver_video(self, client, state)
        except SRError as exc:
            raise ValueError(str(exc)) from None
