import base64
import json

import pytest

import app as app_module
from tests.test_import_routes import Resp

PNG = base64.b64encode(b"imgbytes").decode()
AI_ENV = ("AI_IMAGE_PROVIDER", "AI_IMAGE_MODEL", "AI_IMAGE_BASE_URL", "AI_IMAGE_API_KEY")


@pytest.fixture
def client(monkeypatch):
    app_module.app.config["TESTING"] = True
    monkeypatch.setenv("BA_API_URL", "http://ba.test")
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s["ba_token"] = "tok"
    return c


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in AI_ENV:
        monkeypatch.delenv(k, raising=False)


def capture(monkeypatch, resp):
    calls = []

    def post(url, **kw):
        calls.append((url, kw))
        return resp

    monkeypatch.setattr(app_module.http, "post", post)
    return calls


def gen(client, prompt="a lime"):
    return client.post("/api/ai/image", json={"prompt": prompt})


def test_openai_ok(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("AI_IMAGE_API_KEY", "sk-secret")
    calls = capture(monkeypatch, Resp(json_data={"data": [{"b64_json": PNG}]}))
    r = gen(client, "edited prompt")
    assert r.status_code == 200
    assert r.get_json()["image"] == f"data:image/png;base64,{PNG}"
    url, kw = calls[0]
    assert url == "https://api.openai.com/v1/images/generations"
    assert kw["json"]["prompt"] == "edited prompt"
    assert kw["json"]["model"] == "gpt-image-1"
    assert "response_format" not in kw["json"]
    assert kw["headers"]["Authorization"] == "Bearer sk-secret"


def test_openai_dalle_sends_response_format(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("AI_IMAGE_MODEL", "dall-e-3")
    monkeypatch.setenv("AI_IMAGE_API_KEY", "k")
    calls = capture(monkeypatch, Resp(json_data={"data": [{"b64_json": PNG}]}))
    assert gen(client).status_code == 200
    assert calls[0][1]["json"]["response_format"] == "b64_json"


@pytest.mark.parametrize("env", [
    {},
    {"AI_IMAGE_PROVIDER": "openai"},
    {"AI_IMAGE_PROVIDER": "gemini"},
    {"AI_IMAGE_PROVIDER": "compatible", "AI_IMAGE_MODEL": "m"},
    {"AI_IMAGE_PROVIDER": "compatible", "AI_IMAGE_BASE_URL": "http://x/v1"},
])
def test_not_configured(client, monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    r = gen(client)
    assert r.status_code == 400
    assert "not configured" in r.get_json()["error"]


def test_provider_rejects(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("AI_IMAGE_API_KEY", "k")
    capture(monkeypatch, Resp(400, json_data={"error": {"message": "content policy"}}))
    r = gen(client)
    assert r.status_code == 502
    assert r.get_json()["error"] == "content policy"


def test_provider_reject_falls_back_to_status(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("AI_IMAGE_API_KEY", "k")
    capture(monkeypatch, Resp(401))
    assert gen(client).get_json()["error"] == "HTTP 401"


def test_no_image_returned(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("AI_IMAGE_API_KEY", "k")
    capture(monkeypatch, Resp(json_data={"data": []}))
    r = gen(client)
    assert r.status_code == 502
    assert r.get_json()["error"] == "no image returned"


def test_empty_prompt(client):
    r = gen(client, "")
    assert r.status_code == 400
    assert r.get_json()["error"] == "prompt required"


def test_not_logged_in():
    c = app_module.app.test_client()
    assert c.post("/api/ai/image", json={"prompt": "x"}).status_code == 401


def test_compatible_no_key(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "compatible")
    monkeypatch.setenv("AI_IMAGE_MODEL", "local")
    monkeypatch.setenv("AI_IMAGE_BASE_URL", "http://192.168.1.5:8080/v1/")
    calls = capture(monkeypatch, Resp(json_data={"data": [{"b64_json": PNG}]}))
    assert gen(client).status_code == 200
    url, kw = calls[0]
    assert url == "http://192.168.1.5:8080/v1/images/generations"
    assert "Authorization" not in kw["headers"]
    assert kw["json"]["response_format"] == "b64_json"


def test_compatible_url_response(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "compatible")
    monkeypatch.setenv("AI_IMAGE_MODEL", "local")
    monkeypatch.setenv("AI_IMAGE_BASE_URL", "http://h/v1")
    capture(monkeypatch, Resp(json_data={"data": [{"url": "http://h/i.png"}]}))
    fetched = Resp(headers={"Content-Type": "image/webp"})
    fetched.content = b"imgbytes"
    fetched.raise_for_status = lambda: None
    monkeypatch.setattr(app_module.http, "get", lambda u, **kw: fetched)
    r = gen(client)
    assert r.get_json()["image"] == f"data:image/webp;base64,{PNG}"


def test_gemini_parsing(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("AI_IMAGE_API_KEY", "gk")
    body = {"candidates": [{"content": {"parts": [
        {"text": "here"},
        {"inlineData": {"mimeType": "image/jpeg", "data": PNG}},
    ]}}]}
    calls = capture(monkeypatch, Resp(json_data=body))
    r = gen(client, "hello")
    assert r.get_json()["image"] == f"data:image/jpeg;base64,{PNG}"
    url, kw = calls[0]
    assert url.endswith("/models/gemini-2.5-flash-image:generateContent")
    assert kw["headers"]["x-goog-api-key"] == "gk"
    assert kw["json"] == {"contents": [{"parts": [{"text": "hello"}]}]}


def test_gemini_error_message(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("AI_IMAGE_API_KEY", "gk")
    capture(monkeypatch, Resp(400, json_data={"error": {"message": "bad key"}}))
    assert gen(client).get_json()["error"] == "bad key"


def test_config_never_returns_key(client, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "ENV_PATH", str(tmp_path / ".env"))
    r = client.post("/config", json={"ai_provider": "openai", "ai_model": "m",
                                     "ai_api_key": "sk-supersecret"})
    assert r.status_code == 200
    out = client.get("/config")
    assert "sk-supersecret" not in out.get_data(as_text=True)
    cfg = out.get_json()
    assert cfg["ai_key_set"] is True and cfg["ai_provider"] == "openai"
    assert json.dumps(cfg).find("sk-supersecret") == -1


def test_blank_key_same_provider_keeps(client, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "ENV_PATH", str(tmp_path / ".env"))
    client.post("/config", json={"ai_provider": "openai", "ai_api_key": "k"})
    client.post("/config", json={"ai_provider": "openai", "ai_model": "m", "ai_api_key": ""})
    assert client.get("/config").get_json()["ai_key_set"] is True


def test_provider_change_clears_key(client, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "ENV_PATH", str(tmp_path / ".env"))
    client.post("/config", json={"ai_provider": "openai", "ai_api_key": "k"})
    client.post("/config", json={"ai_provider": "gemini", "ai_api_key": ""})
    cfg = client.get("/config").get_json()
    assert cfg["ai_key_set"] is False and cfg["ai_provider"] == "gemini"


def test_ai_config_requires_login(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.delenv("BA_API_URL", raising=False)
    c = app_module.app.test_client()
    assert c.post("/config", json={"ai_provider": "openai"}).status_code == 401
    assert c.get("/config").get_json()["ai_provider"] == ""


def test_string_error_body(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "compatible")
    monkeypatch.setenv("AI_IMAGE_MODEL", "m")
    monkeypatch.setenv("AI_IMAGE_BASE_URL", "http://h/v1")
    capture(monkeypatch, Resp(400, json_data={"error": "model not loaded"}))
    assert gen(client).get_json()["error"] == "model not loaded"
