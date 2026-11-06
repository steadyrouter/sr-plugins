import base64

import pytest
from fake_upstream import KEY, MP4, PNG, UPSTREAM_PATH, Fake
from srclient import (
    FileTooLarge,
    GeneratedFile,
    SRClient,
    SRError,
    ValidationError,
    VideoFailed,
    VideoStatus,
    VideoStillRunning,
    list_models,
    pricing_models,
    scrub,
    video_download_hint,
)


@pytest.fixture
def fake():
    server = Fake()
    yield server
    server.close()


def client(fake, **kwargs):
    defaults = {"base_url": fake.base, "check_host": lambda _h: None, "https_only": False, "poll_seconds": 0,
                "video_wait_seconds": 5, "sleep": lambda _s: None}
    return SRClient(KEY, **{**defaults, **kwargs})


def assert_clean(text, fake=None):
    assert KEY not in text
    assert "http://" not in text and "https://" not in text
    assert "org-private-account" not in text


# ---- images: both reply shapes ----

def test_b64_reply(fake):
    assert client(fake).generate_image("m-b64", "cat")[0].data == PNG


def test_url_reply_is_downloaded_without_key(fake):
    files = client(fake).generate_image("m-url", "cat")
    assert files[0].data == PNG and files[0].mime == "image/png"
    assert fake.seen(UPSTREAM_PATH)[0]["auth"] is None


@pytest.mark.parametrize("model", ["gemini-inline-image", "gemini-snake-image", "gemini-thought-image", "gemini-file-image",
                                   "gemini-md-data-image", "gemini-md-link-image", "gemini-bare-image"])
def test_gemini_image_shapes(fake, model):
    files = client(fake).generate_image(model, "cat")
    assert [f.data for f in files] == [PNG]  # the thought draft is never returned
    assert fake.seen(f"/v1beta/models/{model}:generateContent") and not fake.seen("/v1/chat/completions")


def test_gemini_image_sends_size_ratio_and_references_natively(fake):
    # In the OpenAI format some upstreams ignore both and return their default 1024x1024.
    reference = GeneratedFile(PNG, "image/png")
    client(fake).generate_image("gemini-inline-image", "cat", aspect_ratio="16:9", image_size="2K", images=[reference])
    body = fake.seen("/v1beta/models/gemini-inline-image:generateContent")[0]["body"]
    assert body["generationConfig"]["imageConfig"] == {"aspectRatio": "16:9", "imageSize": "2K"}
    assert body["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
    assert body["contents"][0]["parts"] == [{"text": "cat"}, {"inlineData": {"mimeType": "image/png",
                                                                             "data": base64.b64encode(PNG).decode()}}]
    assert "extra_body" not in body and "model" not in body


def test_gemini_image_auto_sends_no_config(fake):
    client(fake).generate_image("gemini-inline-image", "cat", aspect_ratio="auto", image_size="auto")
    assert "imageConfig" not in fake.seen("/v1beta/models/")[0]["body"]["generationConfig"]


@pytest.mark.parametrize("model", ["gemini-text-image", "gemini-badlink-image", "gemini-thoughts-only-image"])
def test_chat_text_reply_is_a_clean_error(fake, model):
    with pytest.raises(SRError) as err:
        client(fake).generate_image(model, "cat")
    assert_clean(str(err.value))


def test_blocked_gemini_reply_says_why(fake):
    with pytest.raises(SRError, match="IMAGE_SAFETY"):
        client(fake).generate_image("gemini-blocked-image", "cat")


def test_edit_uses_multipart(fake):
    ref = GeneratedFile(PNG, "image/png")
    assert client(fake).generate_image("m-b64", "cat", images=[ref])[0].data == PNG
    assert "multipart/form-data" in fake.seen("/v1/images/edits")[0]["ctype"]


def test_no_image_in_reply(fake):
    with pytest.raises(SRError, match="no image"):
        client(fake).generate_image("m-empty", "cat")


def test_non_image_download_is_refused(fake):
    with pytest.raises(SRError, match="could not be read"):
        client(fake).generate_image("m-url-html", "cat")


def test_oversize_download_stops(fake):
    with pytest.raises(FileTooLarge):
        client(fake).generate_image("m-url-huge", "cat", limit=1024)


def test_empty_prompt_sends_nothing(fake):
    with pytest.raises(ValidationError):
        client(fake).generate_image("m-b64", "  ")
    assert not fake.requests


# ---- download safety ----

def test_http_link_refused_by_default(fake):
    with pytest.raises(SRError, match="could not be downloaded"):
        client(fake, https_only=True).generate_image("m-url", "cat")


def test_private_address_refused_by_default(fake):
    with pytest.raises(SRError, match="could not be downloaded"):
        SRClient(KEY, base_url=fake.base, https_only=False).generate_image("m-url", "cat")


@pytest.mark.parametrize("ip,allowed", [
    ("198.18.0.40", True), ("198.19.255.1", True), ("93.184.216.34", True), ("127.0.0.1", False), ("10.0.0.5", False),
    ("192.168.1.1", False), ("172.17.0.2", False), ("169.254.169.254", False), ("::1", False), ("fd00::1", False),
])
def test_host_check_allows_proxy_fake_ip_only(monkeypatch, ip, allowed):
    from srclient import client as module

    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", (ip, 443))])
    if allowed:
        module.public_host_only("example.com")
    else:
        with pytest.raises(SRError):
            module.public_host_only("example.com")


def test_each_redirect_hop_is_checked(fake):
    hosts = []

    def check(host):
        hosts.append(host)

    with pytest.raises(SRError):
        client(fake, check_host=check).generate_image("m-url-http-redirect", "cat")
    assert len(hosts) == 2


# ---- errors never carry a key or a link ----

@pytest.mark.parametrize("model,needle", [
    ("err-429", "busy"), ("err-quota", "balance"), ("no-such-model", "groups your API key"), ("err-leak", "418"),
])
def test_errors_are_clean(fake, model, needle):
    with pytest.raises(SRError) as err:
        client(fake).generate_image(model, "cat")
    assert needle in str(err.value)
    assert_clean(str(err.value))


def test_wrong_key():
    fake = Fake()
    try:
        bad = SRClient("sk-wrong-key-000000", base_url=fake.base)
        with pytest.raises(SRError, match="API key") as err:
            bad.generate_image("m-b64", "cat")
        assert err.value.status == 401
    finally:
        fake.close()


def test_scrub():
    out = scrub(f"Bearer {KEY} token-abcdefgh sk-abcdefgh https://a.example/b?c=d {KEY}", KEY)
    assert_clean(out)
    assert len(scrub("x" * 5000)) == 300
    assert scrub(f"see https://a.example/b?k={KEY} now", KEY) == "see [link removed] now"


# ---- video ----

def test_video_payload_top_level():
    body = SRClient.video_payload("viduq3-turbo", "p", resolution="540P", seconds=5)
    assert body == {"model": "viduq3-turbo", "prompt": "p", "size": "540p", "duration": 5}


def test_video_payload_metadata():
    body = SRClient.video_payload("doubao-seedance-2-0-mini-260615", "p", resolution="480p", seconds=4)
    assert body["metadata"] == {"resolution": "480p", "duration": 4}
    assert "size" not in body


def test_video_payload_start_image_keys():
    assert SRClient.video_payload("viduq2-pro", "p", start_image="u")["images"] == ["u"]
    assert SRClient.video_payload("wan2.6-i2v", "p", start_image="u")["image"] == "u"


@pytest.mark.parametrize("model,options", [
    ("viduq2-pro", {}),  # needs a starting image
    ("wan3.0-video", {"start_image": "u"}),  # refuses one
    ("viduq2", {"resolution": "4k"}),
    ("viduq2", {"seconds": 6}),
    ("doubao-seedance-2-5-260628", {"seconds": 16}),
])
def test_video_payload_refused_before_spending(model, options):
    with pytest.raises(ValidationError):
        SRClient.video_payload(model, "p", **options)


def test_video_payload_unlisted_model_passes():
    assert SRClient.video_payload("new-video", "p", resolution="720p", seconds=9)["size"] == "720p"


def test_video_success_and_download(fake):
    c = client(fake)
    task = c.submit_video("viduq3-turbo", "p", resolution="540p", seconds=5)
    state = c.wait_video(task)
    assert state.done and fake.polls[task] == 2
    assert c.download_video(state).data == MP4
    assert fake.seen("/v1/videos/")[0]["auth"] == f"Bearer {KEY}"
    assert not fake.seen("/upstream/")


def test_video_status_repr_hides_link(fake):
    state = client(fake).video_status("task_ok_2")
    state = client(fake).video_status("task_ok_2")
    assert state.done and state._result_url
    assert "upstream" not in repr(state)


def test_video_download_falls_back_without_key(fake):
    fake.content_status = 500
    c = client(fake)
    state = c.wait_video("task_ok_3")
    assert c.download_video(state).data == MP4
    assert fake.seen("/upstream/video")[0]["auth"] is None


def test_video_gateway_redirect_drops_key(fake):
    fake.content_status = 302
    c = client(fake)
    assert c.download_video(c.wait_video("task_ok_4")).data == MP4
    assert fake.seen("/upstream/video")[0]["auth"] is None


def test_video_too_large(fake):
    fake.content_body = MP4 + b"\0" * 4096
    c = client(fake)
    with pytest.raises(FileTooLarge):
        c.download_video(c.wait_video("task_ok_5"), limit=1024)
    hint = video_download_hint("task_ok_5", api_base="https://api.steadyrouter.com")
    assert "task_ok_5/content" in hint and "Authorization" in hint and "limited time" in hint
    assert "upstream" not in hint


def test_video_failure_is_clean(fake):
    with pytest.raises(VideoFailed) as err:
        client(fake).wait_video("task_bad_1")
    assert "refunded" in str(err.value)
    assert_clean(str(err.value))


def test_video_wait_runs_out(fake):
    with pytest.raises(VideoStillRunning) as err:
        client(fake, video_wait_seconds=0).wait_video("task_slow_1")
    assert err.value.task_id == "task_slow_1"


def test_video_price_error(fake):
    with pytest.raises(SRError, match="resolution, length or input"):
        client(fake).submit_video("err-price", "p")


def test_bad_task_id_sends_nothing(fake):
    with pytest.raises(ValidationError):
        client(fake).video_status("../../etc/passwd")
    assert not fake.requests


def test_no_download_without_any_source(fake):
    fake.content_status = 404
    with pytest.raises(SRError):
        client(fake).download_video(VideoStatus(task_id="t", status="SUCCESS"))


# ---- model lists ----

def test_list_models_live(fake):
    import requests

    rows = pricing_models(requests, fake.base + "/api/pricing")
    assert all("group_prices" not in r for r in rows)
    names = list_models("image", fetch=lambda: rows)
    assert names == ["brand-new-image", "gpt-image-2"]
    assert list_models("image", "gpt_image", fetch=lambda: rows) == ["gpt-image-2"]


def test_list_models_falls_back_to_shipped():
    def boom():
        raise ValueError("down")

    names = list_models("video", "seedance", fetch=boom)
    assert "doubao-seedance-2-5-260628" in names
    assert "mj_imagine" not in list_models("image", fetch=boom, exclude=["mj_imagine"])


# ---- chat ----

def test_chat_sends_options_and_reads_text(fake):
    out = client(fake).chat("some-chat", [{"role": "user", "content": "hi"}], temperature=0.2, max_tokens=50,
                            json_output=True)
    assert out.text == "Hello" and out.model == "some-chat" and out.finish_reason == "stop"
    assert out.usage["total_tokens"] == 3
    body = fake.seen("/v1/chat/completions")[0]["body"]
    assert body["max_completion_tokens"] == 50 and "max_tokens" not in body
    assert body["temperature"] == 0.2 and body["response_format"] == {"type": "json_object"}
    assert body["stream"] is False


def test_chat_sends_nothing_optional_by_default(fake):
    client(fake).chat("some-chat", [{"role": "user", "content": "hi"}])
    body = fake.seen("/v1/chat/completions")[0]["body"]
    assert set(body) == {"model", "messages", "stream"}


def test_chat_refuses_before_sending(fake):
    with pytest.raises(ValidationError):
        client(fake).chat("", [{"role": "user", "content": "hi"}])
    with pytest.raises(ValidationError):
        client(fake).chat("some-chat", [])
    assert not fake.requests


def test_chat_error_is_clean(fake):
    with pytest.raises(SRError) as err:
        SRClient("sk-wrong-key-0000000", base_url=fake.base).chat("some-chat", [{"role": "user", "content": "hi"}])
    assert err.value.status == 401
    assert_clean(str(err.value))
