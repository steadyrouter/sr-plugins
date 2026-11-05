"""Loads the generated packages with the real Dify SDK and runs them against the fake gateway."""

import importlib
import io
import json
import subprocess
import sys
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
from dify_plugin.interfaces.tool import Tool
from fake_upstream import KEY, MP4, PNG, Fake

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "dist" / "dify-model"
TOOLS = ROOT / "dist" / "dify-tools"


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


# ---- schema: what Dify's own classes accept ----

@pytest.mark.parametrize("package", [MODEL, TOOLS])
def test_manifest_loads(package):
    config = PluginConfiguration(**load(package / "manifest.yaml"))
    assert config.repo and config.author == "steadyrouter"
    data = load(package / "manifest.yaml")
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
