"""SteadyRouter nodes: chat, image and video models through one API key.

The model lists come from _models.py (generated from the SteadyRouter catalog when the package is built).
The API key is read from ComfyUI's settings (key.py), never from a node input.
Files that come back are handed to ComfyUI as IMAGE / VIDEO; this package stores nothing.
"""

from __future__ import annotations

import base64
import time
from io import BytesIO

from comfy_api.latest import IO, InputImpl

from . import _models as models
from .convert import batch_to_pngs, to_batch
from .key import api_key
from .srclient import (
    MAX_VIDEO_BYTES,
    FileTooLarge,
    GeneratedFile,
    SRClient,
    SRError,
    VideoStillRunning,
    video_download_hint,
)
from .srclient.client import POLL_SECONDS

CATEGORY = "SteadyRouter"
MAX_REFERENCE_IMAGES = 10
ASPECTS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"]
IMAGE_SIZES = ["auto", "1K", "2K", "4K"]
GPT_SIZES = ["auto", "1024x1024", "1536x1024", "1024x1536"]
QUALITIES = ["auto", "low", "medium", "high"]
DEFAULT_WAIT_MINUTES = 8
MAX_WAIT_MINUTES = 60
SEED_MAX = 2**31 - 1


class SteadyRouterError(Exception):
    """Shown to the user as is. The text is already scrubbed of keys and links."""


def _shown(exc: SRError) -> SteadyRouterError:
    return SteadyRouterError(str(exc))


def _sleep(seconds: float) -> None:
    """Sleep between checks of a video task, stopping at once when the user cancels the run."""
    import comfy.model_management

    end = time.monotonic() + seconds
    while True:
        comfy.model_management.throw_exception_if_processing_interrupted()
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(left, 0.5))


def client(wait_minutes: int = DEFAULT_WAIT_MINUTES) -> SRClient:
    key = api_key()
    if not key:
        raise SteadyRouterError("No SteadyRouter API key. Add it in Settings > SteadyRouter, then run again. "
                                "ComfyUI started with --multi-user cannot use the key. "
                                "No key yet? Sign up at {{get_key_url}}: new accounts get free trial credit to try "
                                "image generation.")
    options = {"base_url": models.API_BASE, "user_agent": f"steadyrouter-comfyui/{models.VERSION}",
               "sleep": _sleep, "poll_seconds": POLL_SECONDS, "video_wait_seconds": max(0, wait_minutes) * 60}
    if models.TEST_BUILD:  # a build made with --base-url talks to a fake gateway on a private address
        options.update(check_host=lambda _host: None, https_only=False)
    return SRClient(key, **options)


def _model(chosen: str, custom: str | None) -> str:
    return (custom or "").strip() or chosen


# ---- shared inputs ----

def _model_input(options: list[str], default: str) -> IO.Combo.Input:
    return IO.Combo.Input("model", options=options, default=default if default in options else options[0],
                          tooltip="The SteadyRouter model to use.")


def _prompt_input(what: str) -> IO.String.Input:
    return IO.String.Input("prompt", multiline=True, default="", tooltip=f"Describe the {what} you want.")


def _seed_input(control: IO.ControlAfterGenerate) -> IO.Int.Input:
    return IO.Int.Input("seed", default=0, min=0, max=SEED_MAX, control_after_generate=control,
                        display_mode=IO.NumberDisplay.number,
                        tooltip="Not sent to the model. ComfyUI reuses the last result while every input stays the "
                                "same; a new seed asks for a new result.")


def _custom_model_input() -> IO.String.Input:
    return IO.String.Input("custom_model", default="", optional=True, advanced=True,
                           tooltip="A model name that is not in the list yet. Leave empty to use the list.")


def _wait_input(minimum: int) -> IO.Int.Input:
    return IO.Int.Input("wait_minutes", default=DEFAULT_WAIT_MINUTES, min=minimum, max=MAX_WAIT_MINUTES,
                        display_mode=IO.NumberDisplay.number,
                        tooltip="How long to wait for the video. If it is not ready by then, the node stops with "
                                "the task ID; pick it up later with SteadyRouter Video Task.")


# ---- chat ----

class SteadyRouterChat(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="SteadyRouterChat",
            display_name="SteadyRouter Chat",
            category=f"{CATEGORY}/text",
            description="Ask a SteadyRouter language model, for example to write or improve a prompt, or to "
                        "describe an image.",
            search_aliases=["llm", "gpt", "claude", "gemini", "prompt", "caption"],
            inputs=[
                _model_input(models.CHAT_MODELS, models.CHAT_DEFAULT),
                IO.String.Input("prompt", multiline=True, default="", tooltip="Your message to the model."),
                IO.String.Input("system", multiline=True, default="", optional=True,
                                tooltip="Optional instructions that steer how the model answers."),
                IO.Int.Input("max_tokens", default=0, min=0, max=262144, optional=True, advanced=True,
                             display_mode=IO.NumberDisplay.number,
                             tooltip="Upper limit on the length of the answer. 0 leaves it to the model."),
                IO.Boolean.Input("json_output", default=False, optional=True, advanced=True,
                                 tooltip="Ask for a JSON object. Mention JSON in the prompt too."),
                _seed_input(IO.ControlAfterGenerate.fixed),
                IO.Image.Input("images", optional=True,
                               tooltip=f"Optional images for the model to look at (up to {MAX_REFERENCE_IMAGES}). "
                                       "Pick a model that reads images."),
                _custom_model_input(),
            ],
            outputs=[IO.String.Output("text")],
        )

    @classmethod
    def execute(cls, model: str, prompt: str, seed: int, system: str = "", max_tokens: int = 0,
                json_output: bool = False, images=None, custom_model: str = "") -> IO.NodeOutput:
        if not (prompt or "").strip():
            raise SteadyRouterError("A prompt is required.")
        pngs = batch_to_pngs(images, MAX_REFERENCE_IMAGES)
        content: str | list[dict] = prompt
        if pngs:
            content = [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(p).decode()}}
                for p in pngs]
        messages = ([{"role": "system", "content": system}] if (system or "").strip() else [])
        messages.append({"role": "user", "content": content})
        try:
            result = client().chat(_model(model, custom_model), messages, max_tokens=max_tokens or None,
                                   json_output=bool(json_output))
        except SRError as exc:
            raise _shown(exc) from None
        return IO.NodeOutput(result.text)


# ---- images ----

class _ImageNode(IO.ComfyNode):
    """Shared by the image nodes. KIND picks the options the family takes."""

    NODE_ID = ""
    DISPLAY = ""
    FAMILY = "all"
    KIND = "all"
    BLURB = ""

    @classmethod
    def _options(cls) -> list:
        aspect = IO.Combo.Input("aspect_ratio", options=ASPECTS, default="auto", optional=True,
                                tooltip="Used by Gemini image models (Nano Banana).")
        image_size = IO.Combo.Input("resolution", options=IMAGE_SIZES, default="auto", optional=True,
                                    tooltip="Used by Gemini image models (Nano Banana). Higher costs more.")
        quality = IO.Combo.Input("quality", options=QUALITIES, default="auto", optional=True,
                                 tooltip="Used by GPT Image models. Higher costs more.")
        free_size = IO.String.Input("size", default="", optional=True,
                                    tooltip="Optional, for example 1024x1024. Each model takes its own sizes.")
        if cls.KIND == "nano_banana":
            return [aspect, image_size]
        if cls.KIND == "gpt_image":
            return [IO.Combo.Input("size", options=GPT_SIZES, default="auto", optional=True, tooltip="Output size."),
                    quality]
        if cls.KIND == "all":
            aspect = IO.Combo.Input("aspect_ratio", options=ASPECTS, default="auto", optional=True,
                                    tooltip="Used by Gemini image models (Nano Banana). GPT Image models take the "
                                            "nearest size (square, 1536x1024 or 1024x1536) when size is empty. "
                                            "Other models ignore it.")
            return [free_size, quality, aspect, image_size]
        return [free_size]

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id=cls.NODE_ID,
            display_name=cls.DISPLAY,
            category=f"{CATEGORY}/image",
            description=f"{cls.BLURB} Connect reference images to edit or combine them.",
            inputs=[
                _model_input(models.IMAGE_MODELS[cls.FAMILY], models.IMAGE_DEFAULTS[cls.FAMILY]),
                _prompt_input("image"),
                *cls._options(),
                _seed_input(IO.ControlAfterGenerate.randomize),
                IO.Image.Input("images", optional=True,
                               tooltip=f"Optional reference images (up to {MAX_REFERENCE_IMAGES}). With them the "
                                       "model edits or combines the images as the prompt says."),
                _custom_model_input(),
            ],
            outputs=[IO.Image.Output("image")],
        )

    @classmethod
    def execute(cls, model: str, prompt: str, seed: int, images=None, custom_model: str = "", size: str = "",
                quality: str = "auto", aspect_ratio: str = "auto", resolution: str = "auto") -> IO.NodeOutput:
        references = [GeneratedFile(p, "image/png") for p in batch_to_pngs(images, MAX_REFERENCE_IMAGES)]
        try:
            files = client().generate_image(_model(model, custom_model), prompt or "", size=(size or "").strip(),
                                            quality=quality, aspect_ratio=aspect_ratio, image_size=resolution,
                                            images=references,
                                            # ComfyUI has no 50 MB file cap (that default is Dify's); a 4K image can pass 20 MB.
                                            limit=MAX_VIDEO_BYTES)
        except SRError as exc:
            raise _shown(exc) from None
        return IO.NodeOutput(to_batch([f.data for f in files]))


class SteadyRouterImage(_ImageNode):
    NODE_ID, DISPLAY = "SteadyRouterImage", "SteadyRouter Image"
    BLURB = "Generate images with any SteadyRouter image model."


class SteadyRouterNanoBanana(_ImageNode):
    NODE_ID, DISPLAY, FAMILY, KIND = "SteadyRouterNanoBanana", "Nano Banana (SteadyRouter)", "nano_banana", "nano_banana"
    BLURB = "Generate images with Gemini image models (Nano Banana)."


class SteadyRouterGPTImage(_ImageNode):
    NODE_ID, DISPLAY, FAMILY, KIND = "SteadyRouterGPTImage", "GPT Image (SteadyRouter)", "gpt_image", "gpt_image"
    BLURB = "Generate images with GPT Image models."


class SteadyRouterSeedream(_ImageNode):
    NODE_ID, DISPLAY, FAMILY, KIND = "SteadyRouterSeedream", "Seedream (SteadyRouter)", "seedream", "plain"
    BLURB = "Generate images with Doubao Seedream models."


class SteadyRouterQwenImage(_ImageNode):
    NODE_ID, DISPLAY, FAMILY, KIND = "SteadyRouterQwenImage", "Qwen Image & Wan (SteadyRouter)", "tongyi_image", "plain"
    BLURB = "Generate images with Qwen Image and Wan models."


# ---- video ----

def _deliver(sr: SRClient, state) -> InputImpl.VideoFromFile:
    try:
        video = sr.download_video(state, limit=MAX_VIDEO_BYTES)
    except FileTooLarge:
        raise SteadyRouterError(f"The video is ready but larger than {MAX_VIDEO_BYTES // 2**20} MB, so it was not "
                                "loaded.\n" + video_download_hint(state.task_id, models.API_BASE)) from None
    return InputImpl.VideoFromFile(BytesIO(video.data))


def _still_running(task_id: str) -> SteadyRouterError:
    return SteadyRouterError(f"The video is still being made. Task ID: {task_id}\n"
                             "Put this ID into a SteadyRouter Video Task node to pick it up later. "
                             "Running this node again would make (and charge for) a second video.")


class _VideoNode(IO.ComfyNode):
    NODE_ID = ""
    DISPLAY = ""
    FAMILY = "all"
    BLURB = ""

    @classmethod
    def define_schema(cls):
        resolutions = models.VIDEO_RESOLUTIONS[cls.FAMILY]
        low, high = models.VIDEO_SECONDS[cls.FAMILY]
        return IO.Schema(
            node_id=cls.NODE_ID,
            display_name=cls.DISPLAY,
            category=f"{CATEGORY}/video",
            description=f"{cls.BLURB} Waits for the video (up to {DEFAULT_WAIT_MINUTES} minutes by default) and "
                        "returns it with its task ID.",
            inputs=[
                _model_input(models.VIDEO_MODELS[cls.FAMILY], models.VIDEO_DEFAULTS[cls.FAMILY]),
                _prompt_input("video"),
                IO.Combo.Input("resolution", options=resolutions,
                               default="720p" if "720p" in resolutions else resolutions[0],
                               tooltip="Each model takes its own resolutions. Higher costs more."),
                IO.Int.Input("seconds", default=min(max(5, low), high), min=low, max=high,
                             display_mode=IO.NumberDisplay.number,
                             tooltip="Length of the video. Each model takes its own lengths. Longer costs more."),
                _wait_input(1),
                _seed_input(IO.ControlAfterGenerate.randomize),
                IO.Image.Input("start_image", optional=True,
                               tooltip="Optional first frame (the first image of the batch). Some models need one, "
                                       "some refuse one."),
                _custom_model_input(),
            ],
            outputs=[IO.Video.Output("video"), IO.String.Output("task_id")],
        )

    @classmethod
    def execute(cls, model: str, prompt: str, resolution: str, seconds: int, wait_minutes: int, seed: int,
                start_image=None, custom_model: str = "") -> IO.NodeOutput:
        frame = None
        if start_image is not None:
            png = batch_to_pngs(start_image[:1], 1)[0]
            frame = "data:image/png;base64," + base64.b64encode(png).decode()
        sr = client(wait_minutes)
        try:
            task_id = sr.submit_video(_model(model, custom_model), prompt or "", resolution=resolution,
                                      seconds=int(seconds), start_image=frame)
            try:
                state = sr.wait_video(task_id)
            except VideoStillRunning:
                raise _still_running(task_id) from None
            return IO.NodeOutput(_deliver(sr, state), task_id)
        except SRError as exc:
            raise _shown(exc) from None


class SteadyRouterVideo(_VideoNode):
    NODE_ID, DISPLAY = "SteadyRouterVideo", "SteadyRouter Video"
    BLURB = "Generate a video with any SteadyRouter video model."


class SteadyRouterSeedance(_VideoNode):
    NODE_ID, DISPLAY, FAMILY = "SteadyRouterSeedance", "Seedance (SteadyRouter)", "seedance"
    BLURB = "Generate a video with Doubao Seedance models."


class SteadyRouterWanVideo(_VideoNode):
    NODE_ID, DISPLAY, FAMILY = "SteadyRouterWanVideo", "Wan Video (SteadyRouter)", "wan_video"
    BLURB = "Generate a video with Wan models."


class SteadyRouterVidu(_VideoNode):
    NODE_ID, DISPLAY, FAMILY = "SteadyRouterVidu", "Vidu (SteadyRouter)", "vidu"
    BLURB = "Generate a video with Vidu models."


class SteadyRouterVideoTask(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="SteadyRouterVideoTask",
            display_name="SteadyRouter Video Task",
            category=f"{CATEGORY}/video",
            description="Pick up a video by its task ID, for one that was still being made when its node stopped "
                        "waiting. Nothing is charged here.",
            inputs=[
                IO.String.Input("task_id", default="", tooltip="The task ID from a SteadyRouter video node."),
                _wait_input(0),
            ],
            outputs=[IO.Video.Output("video")],
        )

    @classmethod
    def execute(cls, task_id: str, wait_minutes: int) -> IO.NodeOutput:
        task_id = (task_id or "").strip()
        sr = client(wait_minutes)
        try:
            try:
                state = sr.wait_video(task_id)
            except VideoStillRunning:
                raise _still_running(task_id) from None
            return IO.NodeOutput(_deliver(sr, state))
        except SRError as exc:
            raise _shown(exc) from None


NODES = [SteadyRouterChat, SteadyRouterImage, SteadyRouterNanoBanana, SteadyRouterGPTImage, SteadyRouterSeedream,
         SteadyRouterQwenImage, SteadyRouterVideo, SteadyRouterSeedance, SteadyRouterWanVideo, SteadyRouterVidu,
         SteadyRouterVideoTask]
