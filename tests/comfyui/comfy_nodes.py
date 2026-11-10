"""The ComfyUI nodes, called the way ComfyUI calls them, against the fake gateway. Needs torch and a ComfyUI
checkout, so it runs in its own venv: tests/test_comfyui.py starts it (COMFYUI=<checkout>, see that file).

The fake serves a real PNG and a real MP4 here, because the nodes decode images into tensors.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os
import sys
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [os.environ["COMFYUI"], str(ROOT / "tests"), str(ROOT / "tools")]

from comfy.cli_args import args

args.cpu = True  # this torch has no CUDA; ComfyUI picks its device when model_management is imported

import av
import comfy.model_management
import folder_paths
import numpy as np
import torch
from fake_upstream import KEY, Fake
from PIL import Image


def real_png(color=(200, 30, 30), size=(8, 6)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def real_mp4() -> bytes:
    out = BytesIO()
    with av.open(out, "w", format="mp4") as container:
        stream = container.add_stream("mpeg4", rate=8)
        stream.width, stream.height, stream.pix_fmt = 16, 16, "yuv420p"
        for i in range(4):
            frame = av.VideoFrame.from_image(Image.new("RGB", (16, 16), (i * 60, 0, 0)))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return out.getvalue()


PNG = real_png()
MP4 = real_mp4()


@pytest.fixture(scope="module")
def fake():
    server = Fake(png=PNG, mp4=MP4)
    yield server
    server.close()


@pytest.fixture(scope="module")
def pkg(fake, tmp_path_factory):
    """A --base-url test build of the package, imported as a Python package the way ComfyUI loads it."""
    import common
    spec = importlib.util.spec_from_file_location("build_comfyui", ROOT / "platforms" / "comfyui" / "build.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    parent = tmp_path_factory.mktemp("custom_nodes")
    builder.build(common.load_context(fake.base), parent / "sr_comfy_test")
    sys.path.insert(0, str(parent))
    module = importlib.import_module("sr_comfy_test")
    module.nodes.POLL_SECONDS = 0
    return module


@pytest.fixture(autouse=True)
def setup(fake, monkeypatch, tmp_path):
    fake.requests.clear()
    fake.polls.clear()
    fake.content_status, fake.content_body = 200, MP4
    folder_paths.set_user_directory(str(tmp_path / "user"))
    settings = tmp_path / "user" / "default" / "comfy.settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"SteadyRouter.ApiKey": KEY}))
    yield
    comfy.model_management.interrupt_current_processing(False)


def node(pkg, name):
    return getattr(pkg.nodes, name)


def run(pkg, name, **inputs):
    return node(pkg, name).execute(**inputs).args


def tensor_from(data: bytes) -> torch.Tensor:
    return torch.from_numpy(np.array(Image.open(BytesIO(data)).convert("RGB")).astype(np.float32) / 255)[None,]


def gateway(fake, path):
    return [r for r in fake.requests if r["path"] == path]


def assert_clean(text: str):
    assert KEY not in text
    assert "http://" not in text and "https://" not in text and "secret" not in text


# ---- loading ----

def test_extension_lists_every_node_with_a_valid_schema(pkg):
    ext = asyncio.run(pkg.comfy_entrypoint())
    nodes = asyncio.run(ext.get_node_list())
    ids = [n.GET_SCHEMA().node_id for n in nodes]
    assert len(ids) == len(set(ids)) == 11 and all(i.startswith("SteadyRouter") for i in ids)
    for n in nodes:
        info = n.GET_NODE_INFO_V1()
        assert info["category"].startswith("SteadyRouter/")
        names = {**info["input"]["required"], **info["input"].get("optional", {})}
        assert "api_key" not in names and not any("key" in k for k in names)
        if "model" in names:
            options = names["model"][1]["options"]
            assert names["model"][1]["default"] in options and len(options) >= 1
    assert pkg.WEB_DIRECTORY == "./web"


def test_family_nodes_show_only_their_family(pkg):
    nano = node(pkg, "SteadyRouterNanoBanana").GET_SCHEMA().inputs[0].options
    assert nano and all(m.startswith("gemini-") for m in nano)
    every = node(pkg, "SteadyRouterImage").GET_SCHEMA().inputs[0].options
    assert set(nano) < set(every) and "mj_imagine" not in every
    vidu = node(pkg, "SteadyRouterVidu").GET_SCHEMA()
    assert all(m.startswith("vidu") for m in vidu.inputs[0].options)
    assert vidu.inputs[2].options == ["540p", "720p", "1080p"]
    chat = node(pkg, "SteadyRouterChat").GET_SCHEMA().inputs[0].options
    assert "o3-pro" not in chat and len(chat) > 50


def test_release_build_is_not_a_test_build(pkg, tmp_path):
    import common
    spec = importlib.util.spec_from_file_location("build_comfyui_rel", ROOT / "platforms" / "comfyui" / "build.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    out = builder.build(common.load_context(), tmp_path / "rel")
    text = (out / "_models.py").read_text()
    assert "TEST_BUILD = False" in text and 'API_BASE = "https://api.steadyrouter.com"' in text
    assert pkg.nodes.models.TEST_BUILD is True
    assert "{{" not in (out / "web" / "steadyrouter.js").read_text() + (out / "README.md").read_text()


# ---- the key ----

def test_no_key_is_a_clear_error_and_sends_nothing(pkg, fake, monkeypatch):
    (Path(folder_paths.get_user_directory()) / "default" / "comfy.settings.json").unlink()
    with pytest.raises(pkg.nodes.SteadyRouterError, match="Settings > SteadyRouter"):
        run(pkg, "SteadyRouterChat", model="some-chat", prompt="hi", seed=0)
    assert not fake.requests


def test_key_from_settings_only(pkg, fake, monkeypatch):
    settings = Path(folder_paths.get_user_directory()) / "default" / "comfy.settings.json"
    settings.write_text(json.dumps({"SteadyRouter.ApiKey": f"  {KEY} ", "Comfy.Other": 1}))
    assert run(pkg, "SteadyRouterChat", model="some-chat", prompt="hi", seed=0) == ("Hello",)
    assert fake.requests[-1]["auth"] == f"Bearer {KEY}"
    monkeypatch.setenv("STEADYROUTER_API_KEY", "sk-from-env-0000000")  # 0.1.1 no longer reads the environment
    assert pkg.key.api_key() == KEY


def test_multi_user_has_no_key(pkg, monkeypatch):
    monkeypatch.setattr(args, "multi_user", True)
    assert pkg.key.api_key() == ""
    monkeypatch.setattr(args, "multi_user", False)
    assert pkg.key.api_key() == KEY


def test_broken_settings_file_means_no_key(pkg, monkeypatch):
    settings = Path(folder_paths.get_user_directory()) / "default" / "comfy.settings.json"
    settings.write_text("{not json")
    assert pkg.key.api_key() == ""
    settings.write_text(json.dumps({"SteadyRouter.ApiKey": 123}))
    assert pkg.key.api_key() == ""


# ---- chat ----

def test_chat_sends_system_limit_and_json(pkg, fake):
    out = run(pkg, "SteadyRouterChat", model="some-chat", prompt="hi", seed=0, system="be brief", max_tokens=32,
              json_output=True)
    assert out == ("Hello",)
    body = gateway(fake, "/v1/chat/completions")[0]["body"]
    assert body["messages"] == [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]
    assert body["max_completion_tokens"] == 32 and body["response_format"] == {"type": "json_object"}
    assert "temperature" not in body and "max_tokens" not in body
    assert gateway(fake, "/v1/chat/completions")[0]["auth"] == f"Bearer {KEY}"


def test_chat_defaults_send_nothing_extra(pkg, fake):
    run(pkg, "SteadyRouterChat", model="some-chat", prompt="hi", seed=0)
    body = gateway(fake, "/v1/chat/completions")[0]["body"]
    assert set(body) == {"model", "messages", "stream"} and len(body["messages"]) == 1


def test_chat_with_images_and_custom_model(pkg, fake):
    images = torch.cat([tensor_from(PNG), tensor_from(real_png((0, 0, 255)))])
    run(pkg, "SteadyRouterChat", model="some-chat", prompt="what is this", seed=0, images=images,
        custom_model=" my-new-model ")
    body = gateway(fake, "/v1/chat/completions")[0]["body"]
    assert body["model"] == "my-new-model"
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "what is this"}
    assert [p["type"] for p in parts[1:]] == ["image_url", "image_url"]
    sent = base64.b64decode(parts[2]["image_url"]["url"].split(",", 1)[1])
    assert Image.open(BytesIO(sent)).getpixel((0, 0)) == (0, 0, 255)


def test_chat_needs_a_prompt(pkg, fake):
    with pytest.raises(pkg.nodes.SteadyRouterError):
        run(pkg, "SteadyRouterChat", model="some-chat", prompt="  ", seed=0)
    assert not fake.requests


# ---- images ----

@pytest.mark.parametrize("model", ["m-b64", "m-url", "gemini-md-link-image", "gemini-parts-image"])
def test_image_reply_becomes_a_tensor(pkg, fake, model):
    (image,) = run(pkg, "SteadyRouterImage", model=model, prompt="a cat", seed=1)
    assert image.shape == (1, 6, 8, 3) and image.dtype == torch.float32
    assert abs(float(image[0, 0, 0, 0]) - 200 / 255) < 1e-6
    upstream = [r for r in fake.requests if r["path"].startswith("/upstream/")]
    assert all(r["auth"] is None for r in upstream)


def test_nano_banana_sends_aspect_and_resolution(pkg, fake):
    run(pkg, "SteadyRouterNanoBanana", model="gemini-bare-image", prompt="a cat", seed=1, aspect_ratio="16:9",
        resolution="2K")
    body = gateway(fake, "/v1beta/models/gemini-bare-image:generateContent")[0]["body"]
    assert body["generationConfig"]["imageConfig"] == {"aspectRatio": "16:9", "imageSize": "2K"}


def test_gpt_image_sends_size_and_quality_but_not_auto(pkg, fake):
    run(pkg, "SteadyRouterGPTImage", model="m-b64", prompt="a cat", seed=1, size="1536x1024", quality="high")
    run(pkg, "SteadyRouterGPTImage", model="m-b64", prompt="a cat", seed=2, size="auto", quality="auto")
    first, second = (r["body"] for r in gateway(fake, "/v1/images/generations"))
    assert first["size"] == "1536x1024" and first["quality"] == "high"
    assert "size" not in second and "quality" not in second
    assert "seed" not in first


def test_reference_images_go_as_multipart_edit(pkg, fake):
    refs = torch.cat([tensor_from(PNG)] * 3)
    (image,) = run(pkg, "SteadyRouterSeedream", model="m-b64", prompt="combine", seed=1, images=refs)
    assert image.shape[0] == 1
    edit = gateway(fake, "/v1/images/edits")[0]
    assert edit["ctype"].startswith("multipart/form-data") and edit["body"].count(b'name="image[]"') == 3


def test_too_many_reference_images_are_refused_before_sending(pkg, fake):
    with pytest.raises(ValueError, match="At most 10"):
        run(pkg, "SteadyRouterImage", model="m-b64", prompt="x", seed=1, images=torch.cat([tensor_from(PNG)] * 11))
    assert not fake.requests


def test_errors_are_clean_and_unchained(pkg, fake):
    for model in ("err-leak", "m-url-html", "gemini-text-image"):
        with pytest.raises(pkg.nodes.SteadyRouterError) as err:
            run(pkg, "SteadyRouterImage", model=model, prompt="x", seed=1)
        assert_clean(str(err.value))
        assert err.value.__cause__ is None and err.value.__suppress_context__


def test_mixed_sizes_keep_the_first_size(pkg):
    batch = pkg.convert.to_batch([PNG, real_png(size=(4, 4)), real_png((0, 255, 0))])
    assert batch.shape == (2, 6, 8, 3)


def test_png_round_trip(pkg):
    tensor = tensor_from(PNG)
    assert torch.equal(pkg.convert.to_tensor(pkg.convert.to_png(tensor[0])), tensor)


# ---- video ----

def test_video_waits_and_returns_the_file(pkg, fake):
    video, task_id = run(pkg, "SteadyRouterVidu", model="viduq3-turbo", prompt="waves", resolution="540p", seconds=5,
                         wait_minutes=8, seed=1)
    assert task_id == "task_ok_1" and video.get_dimensions() == (16, 16)
    body = gateway(fake, "/v1/video/generations")[0]["body"]
    assert body == {"model": "viduq3-turbo", "prompt": "waves", "size": "540p", "duration": 5}
    content = [r for r in fake.requests if r["path"].startswith("/v1/videos/")]
    assert content and content[0]["auth"] == f"Bearer {KEY}"


def test_seedance_puts_options_in_metadata_with_a_first_frame(pkg, fake):
    run(pkg, "SteadyRouterSeedance", model="doubao-seedance-2-0-260128", prompt="waves", resolution="720p",
        seconds=5, wait_minutes=8, seed=1, start_image=torch.cat([tensor_from(PNG), tensor_from(PNG)]))
    body = gateway(fake, "/v1/video/generations")[0]["body"]
    assert body["metadata"] == {"resolution": "720p", "duration": 5}
    assert len(body["images"]) == 1 and body["images"][0].startswith("data:image/png;base64,")


def test_video_values_the_model_refuses_are_caught_before_sending(pkg, fake):
    with pytest.raises(pkg.nodes.SteadyRouterError, match="takes these resolutions"):
        run(pkg, "SteadyRouterVidu", model="viduq3-turbo", prompt="waves", resolution="4k", seconds=5,
            wait_minutes=8, seed=1)
    with pytest.raises(pkg.nodes.SteadyRouterError, match="needs a starting image"):
        run(pkg, "SteadyRouterWanVideo", model="wan2.6-i2v", prompt="waves", resolution="720p", seconds=5,
            wait_minutes=8, seed=1)
    assert not fake.requests


def test_video_not_ready_gives_the_task_id(pkg, fake):
    with pytest.raises(pkg.nodes.SteadyRouterError, match="Task ID: task_ok_1") as err:
        run(pkg, "SteadyRouterVideo", model="viduq3-turbo", prompt="waves", resolution="540p", seconds=5,
            wait_minutes=0, seed=1)
    assert "Video Task" in str(err.value)
    (video,) = run(pkg, "SteadyRouterVideoTask", task_id="task_ok_1", wait_minutes=0)
    assert video.get_dimensions() == (16, 16)


def test_video_task_failure_is_clean(pkg):
    with pytest.raises(pkg.nodes.SteadyRouterError, match="refunded") as err:
        run(pkg, "SteadyRouterVideoTask", task_id="task_bad_2", wait_minutes=1)
    assert_clean(str(err.value))
    with pytest.raises(pkg.nodes.SteadyRouterError, match="does not look right"):
        run(pkg, "SteadyRouterVideoTask", task_id="../../etc", wait_minutes=1)


def test_video_download_falls_back_and_caps(pkg, fake, monkeypatch):
    fake.content_status = 302  # gateway redirects to the upstream link, which must be fetched without the key
    (video,) = run(pkg, "SteadyRouterVideoTask", task_id="task_ok_3", wait_minutes=1)
    assert video.get_dimensions() == (16, 16)
    assert all(r["auth"] is None for r in fake.requests if r["path"].startswith("/upstream/"))
    fake.content_status = 200
    monkeypatch.setattr(pkg.nodes, "MAX_VIDEO_BYTES", 100)
    with pytest.raises(pkg.nodes.SteadyRouterError, match="Task ID: task_ok_4") as err:
        run(pkg, "SteadyRouterVideoTask", task_id="task_ok_4", wait_minutes=1)
    assert KEY not in str(err.value) and "YOUR_API_KEY" in str(err.value)


def test_cancel_stops_the_wait(pkg, fake):
    comfy.model_management.interrupt_current_processing(True)
    pkg.nodes.POLL_SECONDS = 5
    try:
        with pytest.raises(comfy.model_management.InterruptProcessingException):
            run(pkg, "SteadyRouterVideoTask", task_id="task_slow_1", wait_minutes=1)
    finally:
        pkg.nodes.POLL_SECONDS = 0
    assert len(gateway(fake, "/v1/video/generations/task_slow_1")) == 1
