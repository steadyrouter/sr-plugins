"""Loads the generated packages with the real Dify SDK and runs them against the fake gateway."""

import importlib
import io
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest
import yaml

pytest.importorskip("dify_plugin")

from dify_plugin.core.entities.plugin.setup import PluginConfiguration
from dify_plugin.core.utils.class_loader import load_single_subclass_from_source
from dify_plugin.entities.model import AIModelEntity
from dify_plugin.entities.model.message import UserPromptMessage
from dify_plugin.entities.model.provider import ProviderEntity
from dify_plugin.entities.tool import ToolProviderIdentity
from dify_plugin.errors.model import CredentialsValidateFailedError
from dify_plugin.interfaces.model.ai_model import AIModel
from dify_plugin.interfaces.tool import Tool, ToolProvider
from fake_upstream import KEY, MP4, PNG, Fake

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "dist" / "dify-model"
TOOLS = ROOT / "dist" / "dify-tools"
SINGLE_SPECS = yaml.safe_load((ROOT / "platforms" / "dify-tools" / "single.yaml").read_text())
SINGLES = [ROOT / "dist" / s["package"] for s in SINGLE_SPECS]


@pytest.fixture(scope="session", autouse=True)
def built():
    subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), "dify-model"], check=True, capture_output=True)
    subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), "dify-tools"], check=True, capture_output=True)
    for path in (MODEL, TOOLS):
        sys.path.insert(0, str(path))


@pytest.fixture
def fake():
    server = Fake()
    yield server
    server.close()


def load(path: Path):
    return yaml.safe_load(path.read_text())


def first_version_line(path: Path) -> str:
    # The pre-check's version-update rule takes the first `version:` line anywhere in the manifest, nested or not.
    return re.search(r"^\s*version\s*:\s*[\"']?([^\"'\n#]+)", path.read_text(), re.M).group(1).strip()


# ---- schema: what Dify's own classes accept ----

@pytest.mark.parametrize("package", [MODEL, TOOLS, *SINGLES])
def test_manifest_loads(package):
    config = PluginConfiguration(**load(package / "manifest.yaml"))
    assert config.repo and config.author == "steadyrouter"
    data = load(package / "manifest.yaml")
    assert data["contact"] == "support@steadyrouter.com"  # the Marketplace pre-check requires it
    if package != MODEL:  # dify-plugins #3701: 1-3 tags from the controlled vocabulary
        assert data["tags"] and set(data["tags"]) <= {"image", "videos"}, data.get("tags")
    assert first_version_line(package / "manifest.yaml") == data["version"]
    assert (package / data["privacy"]).read_text().strip()
    assert (package / "_assets" / data["icon"]).exists()
    readme = (package / "README.md").read_text()
    assert "{{" not in readme and "github.com" in readme


def test_model_yaml_all_load():
    seen = 0
    for path in (MODEL / "models").rglob("*.yaml"):
        if path.name != "_position.yaml":
            entity = AIModelEntity(**load(path))
            assert entity.pricing is None  # no price numbers in the package
            seen += 1
    catalog = json.loads((ROOT / "catalog" / "catalog.json").read_text())["models"]
    listed = [m for m in catalog if "dify-model" not in m.get("exclude", [])
              and (m["category"] in ("language", "embedding", "rerank") or m.get("audio_kind") == "speech2text")]
    assert seen == len(listed)


def test_position_files_match_models():
    for kind in ("llm", "text_embedding", "rerank", "speech2text"):
        folder = MODEL / "models" / kind
        names = {load(p)["model"] for p in folder.glob("*.yaml") if p.name != "_position.yaml"}
        assert set(load(folder / "_position.yaml")) == names


def test_provider_yaml_loads():
    data = load(MODEL / "provider" / "steadyrouter.yaml")
    data.pop("models"), data.pop("extra")
    entity = ProviderEntity(**data)
    assert entity.provider == "steadyrouter"
    assert "aff=" in entity.help.url.en_us


def test_tool_provider_yaml():
    data = load(TOOLS / "provider" / "steadyrouter_media.yaml")
    ToolProviderIdentity(**data["identity"])
    assert "aff=" in data["credentials_for_provider"]["api_key"]["url"]
    assert len(data["tools"]) == 8
    for rel in data["tools"]:
        tool = load(TOOLS / rel)
        source = TOOLS / tool["extra"]["python"]["source"]
        cls = load_single_subclass_from_source(module_name=f"t_{source.stem}", script_path=str(source), parent_type=Tool)
        assert issubclass(cls, Tool)


def test_tool_params_validate():
    from dify_plugin.entities.tool import ToolParameter

    for path in (TOOLS / "tools").glob("*.yaml"):
        for param in load(path)["parameters"]:
            ToolParameter(**param)


def test_model_dropdown_is_in_the_section_dify_fills():
    # Dify's workflow panel leaves a dynamic-select under form: form empty (seen on 1.19.0), so it has to be form: llm.
    # In an Agent the model fills it in, so the description has to name a real model to pick.
    tools = [yaml.safe_load(p.read_text()) for p in (TOOLS / "tools").glob("*.yaml")]
    pickers = [next(q for q in t["parameters"] if q["name"] == "model") for t in tools if t["identity"]["name"] != "check_video_task"]
    assert len(pickers) == 7
    for picker in pickers:
        assert (picker["type"], picker["form"]) == ("dynamic-select", "llm")
        assert "Use " in picker["llm_description"] and "None" not in picker["llm_description"]


def test_release_build_has_no_test_switch():
    assert "TEST_BUILD = False" in (TOOLS / "tools" / "_site.py").read_text()
    assert "API_BASE" in (MODEL / "models" / "_site.py").read_text()
    assert "https://api.steadyrouter.com" in (MODEL / "models" / "_site.py").read_text()


# ---- model plugin against the fake gateway ----

@pytest.fixture
def model_env(fake, monkeypatch):
    common = importlib.import_module("models._common")
    monkeypatch.setattr(common, "ENDPOINT", fake.base + "/v1")
    return fake


def llm_instance(name="claude-opus-5-5"):
    module = importlib.import_module("models.llm.llm")
    schema = AIModelEntity(**load(MODEL / "models" / "llm" / f"{name}.yaml"))
    return module.SteadyRouterLargeLanguageModel(model_schemas=[schema])


def test_llm_blocking(model_env):
    result = llm_instance()._invoke("claude-opus-5-5", {"api_key": KEY}, [UserPromptMessage(content="hi")], {},
                                    stream=False)
    assert result.message.content == "Hello"
    sent = model_env.seen("/v1/chat/completions")[0]
    assert sent["auth"] == f"Bearer {KEY}" and sent["body"]["model"] == "claude-opus-5-5"


def test_llm_stream(model_env):
    chunks = list(llm_instance()._invoke("claude-opus-5-5", {"api_key": KEY}, [UserPromptMessage(content="hi")], {},
                                         stream=True))
    assert "".join(c.delta.message.content for c in chunks) == "Hello"


@pytest.mark.parametrize("package", [TOOLS, *SINGLES], ids=lambda p: p.name)
def test_refused_key_is_the_error_dify_shows_as_a_message(package, monkeypatch):
    # Any other type reached the user as a whole traceback with server paths (seen in Dify 1.19.0).
    srclient = importlib.import_module("srclient")

    def refuse(_self):
        raise srclient.SRError("The API key is wrong.")

    monkeypatch.setattr(srclient.SRClient, "check_key", refuse)
    source = package / "provider" / "steadyrouter_media.py"
    cls = load_single_subclass_from_source(module_name=f"p_{package.name.replace('-', '_')}", script_path=str(source),
                                           parent_type=ToolProvider)
    with pytest.raises(CredentialsValidateFailedError, match="API key"):
        cls()._validate_credentials({"api_key": "sk-wrong-000000"})


def test_key_check_spends_nothing(model_env):
    llm_instance().validate_credentials("claude-opus-5-5", {"api_key": KEY})
    assert model_env.seen("/v1/models") and not model_env.seen("/v1/chat")
    with pytest.raises(CredentialsValidateFailedError, match="API key"):
        llm_instance().validate_credentials("claude-opus-5-5", {"api_key": "sk-wrong-000000"})
    with pytest.raises(CredentialsValidateFailedError):
        llm_instance().validate_credentials("claude-opus-5-5", {})


def test_embedding(model_env, monkeypatch):
    # The SDK counts tokens with tiktoken, which downloads its data on first use from a gevent thread (and can hang
    # there). The count has nothing to do with this plugin, so these tests stay offline.
    monkeypatch.setattr(AIModel, "_get_num_tokens_by_gpt2", lambda self, text: len(text))
    module = importlib.import_module("models.text_embedding.text_embedding")
    schema = AIModelEntity(**load(MODEL / "models" / "text_embedding" / "text-embedding-3-small.yaml"))
    result = module.SteadyRouterTextEmbeddingModel(model_schemas=[schema])._invoke(
        "text-embedding-3-small", {"api_key": KEY}, ["hello"])
    assert result.embeddings and model_env.seen("/v1/embeddings")


def test_rerank(model_env):
    module = importlib.import_module("models.rerank.rerank")
    schema = AIModelEntity(**load(MODEL / "models" / "rerank" / "BAAI-bge-reranker-v2-m3.yaml"))
    result = module.SteadyRouterRerankModel(model_schemas=[schema])._invoke(
        "BAAI/bge-reranker-v2-m3", {"api_key": KEY}, "q", ["a", "b"])
    assert [d.index for d in result.docs] == [1, 0] and model_env.seen("/v1/rerank")


def test_speech2text(model_env):
    module = importlib.import_module("models.speech2text.speech2text")
    schema = AIModelEntity(**load(MODEL / "models" / "speech2text" / "whisper-1.yaml"))
    text = module.SteadyRouterSpeech2TextModel(model_schemas=[schema])._invoke(
        "whisper-1", {"api_key": KEY}, io.BytesIO(b"audio"))
    assert text == "hello world"


# ---- tool plugin against the fake gateway ----

@pytest.fixture
def tools_env(fake, monkeypatch):
    from srclient import SRClient

    base = importlib.import_module("tools._base")

    def client_for(tool):
        return SRClient(tool.runtime.credentials.get("api_key") or "", base_url=fake.base,
                        check_host=lambda _h: None, https_only=False, poll_seconds=0, video_wait_seconds=2,
                        sleep=lambda _s: None)

    monkeypatch.setattr(base, "client_for", client_for)
    return fake


def tool(tool_id):
    source = TOOLS / "tools" / f"{tool_id}.py"
    cls = load_single_subclass_from_source(module_name=f"t_{tool_id}", script_path=str(source), parent_type=Tool)
    return cls.from_credentials({"api_key": KEY})


def run(tool_id, **params):
    return list(tool(tool_id)._invoke(params))


def blobs(messages):
    return [m.message.blob for m in messages if m.type.value == "blob"]


def assert_no_links(messages, fake):
    for message in messages:
        text = str(message.message.model_dump() if hasattr(message.message, "model_dump") else message.message)
        if message.type.value != "blob":
            assert "/upstream/" not in text and fake.base not in text and "result_url" not in text


@pytest.mark.parametrize("model", ["m-b64", "m-url", "gemini-md-data-image", "gemini-md-link-image"])
def test_image_tool_returns_files_never_links(tools_env, model):
    messages = run("generate_image", model=model, prompt="cat")
    assert blobs(messages) == [PNG]
    assert_no_links(messages, tools_env)


LITE = "gemini-3.1-flash-lite-image"


def lite_config(fake):
    return fake.seen(f"/v1beta/models/{LITE}:generateContent")[-1]["body"]["generationConfig"].get("imageConfig")


@pytest.mark.parametrize("asked", ["2K", "4K"])
def test_flash_lite_asked_for_more_than_1k_still_makes_an_image_and_says_so(tools_env, asked):
    messages = run("generate_image", model=LITE, prompt="cat", image_size=asked, aspect_ratio="16:9")
    assert blobs(messages) == [PNG]
    assert lite_config(tools_env) == {"aspectRatio": "16:9", "imageSize": "1K"}
    assert [m.message.text for m in messages if m.type.value == "text"] == ["This model only supports 1K, so 1K was used. 这个型号只支持 1K，已改用 1K。"]


@pytest.mark.parametrize("asked", ["1K", "auto", None])
def test_flash_lite_says_nothing_when_the_quality_was_not_changed(tools_env, asked):
    messages = run("generate_image", model=LITE, prompt="cat", image_size=asked)
    assert blobs(messages) == [PNG]
    assert not [m for m in messages if m.type.value == "text"]


def test_other_models_keep_the_quality_they_were_asked_for(tools_env):
    messages = run("generate_image", model="gemini-3.1-flash-image", prompt="cat", image_size="2K")
    assert not [m for m in messages if m.type.value == "text"]
    body = tools_env.seen("/v1beta/models/gemini-3.1-flash-image:generateContent")[-1]["body"]
    assert body["generationConfig"]["imageConfig"] == {"imageSize": "2K"}


def test_image_errors_are_clean(tools_env):
    with pytest.raises(ValueError) as err:
        run("generate_image", model="err-leak", prompt="cat")
    assert KEY not in str(err.value) and "http" not in str(err.value)


class Upload:
    def __init__(self, blob, mime="image/png"):
        self.blob, self.mime_type = blob, mime


def test_image_with_reference_uses_edit(tools_env):
    assert blobs(run("gpt_image", model="m-b64", prompt="cat", images=[Upload(PNG)])) == [PNG]
    assert tools_env.seen("/v1/images/edits")


def test_too_many_references(tools_env):
    with pytest.raises(ValueError, match="At most"):
        run("generate_image", model="m-b64", prompt="cat", images=[Upload(PNG)] * 11)


def test_video_tool_end_to_end(tools_env):
    messages = run("generate_video", model="viduq3-turbo", prompt="p", resolution="720p", seconds=5)
    assert blobs(messages) == [MP4]
    assert_no_links(messages, tools_env)
    assert tools_env.seen("/v1/video/generations")[0]["body"]["size"] == "720p"


def test_video_start_image_as_data_uri(tools_env):
    run("seedance", model="doubao-seedance-2-0-mini-260615", prompt="p", resolution="480p", seconds=4,
        start_image=Upload(PNG))
    body = tools_env.seen("/v1/video/generations")[0]["body"]
    assert body["images"][0].startswith("data:image/png;base64,") and body["metadata"]["duration"] == 4


def test_video_over_50mb_gives_gateway_command_not_upstream(tools_env):
    tools_env.content_body = MP4 + b"\0" * (50 * 1024 * 1024 + 1)
    messages = run("generate_video", model="viduq3-turbo", prompt="p")
    assert not blobs(messages)
    text = " ".join(m.message.text for m in messages if m.type.value == "text")
    assert "/v1/videos/task_ok_1/content" in text and "Authorization" in text and "limited time" in text
    assert "api.steadyrouter.com" in text and "/upstream/" not in text


def test_video_price_error_before_wait(tools_env):
    with pytest.raises(ValueError, match="resolution, length or input"):
        run("generate_video", model="err-price", prompt="p")


def test_video_validation_sends_nothing(tools_env):
    with pytest.raises(ValueError, match="needs a starting image"):
        run("generate_video", model="viduq2-pro", prompt="p")
    assert not tools_env.seen("/v1/video/generations")


def test_check_task_running_then_done(tools_env):
    first = run("check_video_task", task_id="task_ok_9")
    assert not blobs(first) and any("Still running" in m.message.text for m in first if m.type.value == "text")
    assert blobs(run("check_video_task", task_id="task_ok_9")) == [MP4]


def test_check_task_failed_is_clean(tools_env):
    with pytest.raises(ValueError, match="refunded") as err:
        run("check_video_task", task_id="task_bad_2")
    assert KEY not in str(err.value) and "http" not in str(err.value)


def test_dropdowns(monkeypatch):
    client = importlib.import_module("srclient.client")
    rows = [{"model_name": "gemini-3-pro-image", "tags": "Image"}, {"model_name": "gpt-image-2", "tags": "Image"},
            {"model_name": "mj_imagine", "tags": "Midjourney"}, {"model_name": "viduq2", "tags": "Video"}]
    monkeypatch.setattr(client, "pricing_models", lambda *a, **k: rows)
    monkeypatch.setattr(client.list_models, "__defaults__", None, raising=False)
    monkeypatch.setitem(client.list_models.__kwdefaults__, "fetch", lambda: rows)
    values = lambda t: [o.value for o in tool(t)._fetch_parameter_options("model")]
    assert values("generate_image") == ["gemini-3-pro-image", "gpt-image-2"]
    assert values("nano_banana") == ["gemini-3-pro-image"]
    assert values("generate_video") == ["viduq2"]
    assert tool("generate_image")._fetch_parameter_options("other") == []


# ---- plugins named after one model ----

BY_ID = {s["package"]: s for s in SINGLE_SPECS}


def single(spec):
    return ROOT / "dist" / spec["package"]


def single_tool(spec, tool_id):
    source = single(spec) / "tools" / f"{tool_id}.py"
    cls = load_single_subclass_from_source(module_name=f"s_{spec['package']}_{tool_id}".replace("-", "_"), script_path=str(source),
                                           parent_type=Tool)
    return cls.from_credentials({"api_key": KEY})


def test_these_are_the_ones_the_user_asked_for():
    assert sorted(BY_ID) == ["dify-gpt-image", "dify-qwen-image", "dify-seedance", "dify-seedream", "dify-vidu", "dify-wan"]


@pytest.mark.parametrize("spec", SINGLE_SPECS, ids=lambda s: s["package"])
def test_listing_says_who_it_is(spec):
    data = load(single(spec) / "manifest.yaml")
    versions = load(ROOT / "catalog" / "versions.yaml")
    assert data["name"] == spec["name"] and data["version"] == versions[spec["package"]]
    assert data["label"]["en_US"] == f"{spec['model']} by SteadyRouter"  # never the bare model name: it would read as the owner's own
    owner = spec["owner"]
    assert f"not affiliated with {owner}" in data["description"]["en_US"]
    assert owner in data["description"]["zh_Hans"] and "SteadyRouter" in data["description"]["zh_Hans"]
    assert f"not affiliated with or endorsed by {owner}" in (single(spec) / "README.md").read_text()
    assert f"not affiliated with {owner}" in (single(spec) / "PRIVACY.md").read_text()


def test_every_plugin_named_after_a_model_has_its_own_icon():
    assert {s["package"] for s in SINGLE_SPECS if "icon" not in s} <= {"dify-nano-banana-pro"}  # that one is not published
    icons = [(ROOT / "brand" / s["icon"]).read_bytes() for s in SINGLE_SPECS if "icon" in s]
    assert len(set(icons)) == len(icons)


@pytest.mark.parametrize("spec", [s for s in SINGLE_SPECS if "icon" in s], ids=lambda s: s["package"])
def test_icon_is_our_own_drawing(spec):
    # The Marketplace rule: rights to any third-party logo may have to be proved. So only vector shapes we drew, no
    # embedded or linked picture, and not the brand logo either.
    icon = (single(spec) / "_assets" / "icon.svg").read_bytes()
    assert icon == (ROOT / "brand" / spec["icon"]).read_bytes()
    assert icon != (ROOT / "brand" / "logo.svg").read_bytes()
    root = ElementTree.fromstring(icon)
    assert root.get("viewBox") == "0 0 64 64"
    assert not [e.tag for e in root.iter() if e.tag.endswith(("}image", "}use", "}text"))]
    assert b"href" not in icon and b"data:" not in icon


def test_brand_plugin_keeps_the_brand_logo():
    assert (TOOLS / "_assets" / "icon.svg").read_bytes() == (ROOT / "brand" / "logo.svg").read_bytes()


@pytest.mark.parametrize("spec", SINGLE_SPECS, ids=lambda s: s["package"])
def test_single_package_has_the_right_tools(spec):
    from dify_plugin.entities.tool import ToolParameter

    data = load(single(spec) / "provider" / "steadyrouter_media.yaml")
    ToolProviderIdentity(**data["identity"])
    assert data["identity"]["label"]["en_US"] == f"{spec['model']} by SteadyRouter"
    assert "aff=" in data["credentials_for_provider"]["api_key"]["url"]
    video = spec["kind"] == "video"
    main = spec["name"].removesuffix("_steadyrouter")
    assert data["tools"] == [f"tools/{main}.yaml", *(["tools/check_video_task.yaml"] if video else [])]
    assert "generate_image" not in {p.stem for p in (single(spec) / "tools").glob("*.yaml")}
    for rel in data["tools"]:
        tool = load(single(spec) / rel)
        for param in tool["parameters"]:
            ToolParameter(**param)
        assert single_tool(spec, tool["identity"]["name"])
    assert "TEST_BUILD = False" in (single(spec) / "tools" / "_site.py").read_text()
    assert (single(spec) / "tools" / "_base.py").read_bytes() == (TOOLS / "tools" / "_base.py").read_bytes()


@pytest.mark.parametrize("spec", SINGLE_SPECS, ids=lambda s: s["package"])
def test_default_model_is_sold_and_in_the_named_family(spec):
    catalog = {m["name"]: m for m in json.loads((ROOT / "catalog" / "catalog.json").read_text())["models"]}
    main = spec["name"].removesuffix("_steadyrouter")
    picker = next(q for q in load(single(spec) / "tools" / f"{main}.yaml")["parameters"] if q["name"] == "model")
    assert (picker["type"], picker["form"]) == ("dynamic-select", "llm")
    default = picker["default"]
    assert catalog[default]["family"] == spec["family"]
    assert default.startswith(spec.get("only") or "")
    assert f"Use {default} " in picker["llm_description"]


def test_qwen_dropdown_lists_only_qwen_image(monkeypatch):
    # The family also holds Wan and Z-Image; a plugin called Qwen Image must not offer them.
    client = importlib.import_module("srclient.client")
    rows = [{"model_name": name, "tags": "Image"} for name in ("qwen-image-3.0", "qwen-image-max", "wan2.7-image-pro", "z-image-turbo")]
    monkeypatch.setitem(client.list_models.__kwdefaults__, "fetch", lambda: rows)
    values = [o.value for o in single_tool(BY_ID["dify-qwen-image"], "qwen_image")._fetch_parameter_options("model")]
    assert values == ["qwen-image-3.0", "qwen-image-max"]


def test_single_image_tools_return_files(tools_env):
    for spec, main in ((BY_ID["dify-seedream"], "seedream"),
                       (BY_ID["dify-gpt-image"], "gpt_image"), (BY_ID["dify-qwen-image"], "qwen_image")):
        messages = list(single_tool(spec, main)._invoke({"model": "m-b64", "prompt": "cat"}))
        assert blobs(messages) == [PNG]
        assert_no_links(messages, tools_env)


@pytest.mark.parametrize("package, main", [("dify-seedance", "seedance"), ("dify-wan", "wan"), ("dify-vidu", "vidu")])
def test_video_tool_end_to_end(tools_env, package, main):
    spec = BY_ID[package]
    messages = list(single_tool(spec, main)._invoke({"model": "viduq3-turbo", "prompt": "p", "resolution": "720p", "seconds": 5}))
    assert blobs(messages) == [MP4]
    assert_no_links(messages, tools_env)
    assert single_tool(spec, "check_video_task")
