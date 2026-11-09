import base64
import json

import pytest
from dotenv import dotenv_values

import app as app_module
from tests.test_import_routes import Resp

PNG = base64.b64encode(b"imgbytes").decode()
AI_ENV = ("AI_IMAGE_PROVIDER", "AI_IMAGE_MODEL", "AI_IMAGE_BASE_URL", "AI_IMAGE_API_KEY",
          "AI_PROMPT_INGREDIENT", "AI_PROMPT_COCKTAIL")


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
    assert kw["json"]["model"] == "gpt-image-2"
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


@pytest.mark.parametrize("kind", ["ingredient", "cocktail"])
def test_prompt_template_round_trip(client, monkeypatch, tmp_path, kind):
    env = tmp_path / ".env"
    monkeypatch.setattr(app_module, "ENV_PATH", str(env))
    field = f"ai_prompt_{kind}"
    assert client.get("/config").get_json()[field] == ""
    r = client.post("/config", json={field: "  Photo of {name},\n\n moody  light "})
    assert r.status_code == 200
    want = "Photo of {name}, moody light"
    assert client.get("/config").get_json()[field] == want
    assert dotenv_values(env)[f"AI_PROMPT_{kind.upper()}"] == want
    client.post("/config", json={field: ""})  # back to the default
    assert client.get("/config").get_json()[field] == ""


def test_config_writes_through_env_symlink(client, monkeypatch, tmp_path):
    # Docker image links /app/.env -> /config/.env; saving must update the
    # mounted file, not replace the link with a file inside the container.
    target = tmp_path / "config" / ".env"
    target.parent.mkdir()
    target.touch()
    link = tmp_path / ".env"
    link.symlink_to(target)
    monkeypatch.setattr(app_module, "ENV_PATH", str(link))
    r = client.post("/config", json={"ai_provider": "openai", "ai_model": "m",
                                     "ai_api_key": "k", "ai_prompt_cocktail": "p"})
    assert r.status_code == 200
    assert link.is_symlink()
    saved = dotenv_values(target)
    assert saved["AI_IMAGE_PROVIDER"] == "openai" and saved["AI_IMAGE_API_KEY"] == "k"
    assert saved["AI_PROMPT_COCKTAIL"] == "p"


@pytest.mark.parametrize("kind", ["ingredient", "cocktail"])
def test_prompt_template_requires_login(monkeypatch, tmp_path, kind):
    monkeypatch.setattr(app_module, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.delenv("BA_API_URL", raising=False)
    c = app_module.app.test_client()
    assert c.post("/config", json={f"ai_prompt_{kind}": "x"}).status_code == 401
    assert c.get("/config").get_json()[f"ai_prompt_{kind}"] == ""


def test_string_error_body(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "compatible")
    monkeypatch.setenv("AI_IMAGE_MODEL", "m")
    monkeypatch.setenv("AI_IMAGE_BASE_URL", "http://h/v1")
    capture(monkeypatch, Resp(400, json_data={"error": "model not loaded"}))
    assert gen(client).get_json()["error"] == "model not loaded"


def _png(mode, color, size=(64, 64), dot=None):
    from io import BytesIO

    from PIL import Image
    im = Image.new(mode, size, color)
    if dot:
        for x in range(24, 40):
            for y in range(24, 40):
                im.putpixel((x, y), dot)
    buf = BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _decode(r):
    from io import BytesIO

    from PIL import Image
    data = r.get_json()["image"].split(",", 1)[1]
    return Image.open(BytesIO(base64.b64decode(data))).convert("RGBA")


def gemini_returning(monkeypatch, b64):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("AI_IMAGE_API_KEY", "gk")
    body = {"candidates": [{"content": {"parts": [
        {"inlineData": {"mimeType": "image/png", "data": b64}}]}}]}
    capture(monkeypatch, Resp(json_data=body))


def test_transparent_cuts_out_white_background(client, monkeypatch):
    gemini_returning(monkeypatch, _png("RGB", (250, 250, 250), dot=(40, 160, 40)))
    r = client.post("/api/ai/image", json={"prompt": "a lime", "transparent": True})
    im = _decode(r)
    assert r.get_json()["image"].startswith("data:image/png;base64,")
    assert im.getpixel((0, 0))[3] == 0          # background gone
    assert im.getpixel((32, 32)) == (40, 160, 40, 255)  # subject kept


def test_transparent_keeps_enclosed_white(client, monkeypatch):
    # White inside the subject isn't connected to the edge, so it stays opaque.
    b64 = _png("RGB", (250, 250, 250), dot=(40, 160, 40))
    from io import BytesIO

    from PIL import Image
    im = Image.open(BytesIO(base64.b64decode(b64)))
    for x in range(30, 34):
        for y in range(30, 34):
            im.putpixel((x, y), (255, 255, 255))
    buf = BytesIO()
    im.save(buf, "PNG")
    gemini_returning(monkeypatch, base64.b64encode(buf.getvalue()).decode())
    r = client.post("/api/ai/image", json={"prompt": "x", "transparent": True})
    assert _decode(r).getpixel((32, 32))[3] == 255


def test_transparent_leaves_real_alpha_untouched(client, monkeypatch):
    b64 = _png("RGBA", (0, 0, 0, 0), dot=(40, 160, 40, 255))
    gemini_returning(monkeypatch, b64)
    r = client.post("/api/ai/image", json={"prompt": "x", "transparent": True})
    assert r.get_json()["image"] == f"data:image/png;base64,{b64}"


def test_not_transparent_skips_cut_out(client, monkeypatch):
    b64 = _png("RGB", (250, 250, 250))
    gemini_returning(monkeypatch, b64)
    assert gen(client).get_json()["image"] == f"data:image/png;base64,{b64}"


@pytest.mark.parametrize("model,transparent,expect", [
    ("gpt-image-1", True, True),
    ("gpt-image-1", False, False),
    ("dall-e-3", True, False),
])
def test_openai_background_param(client, monkeypatch, model, transparent, expect):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("AI_IMAGE_MODEL", model)
    monkeypatch.setenv("AI_IMAGE_API_KEY", "k")
    calls = capture(monkeypatch, Resp(json_data={"data": [{"b64_json": _png("RGBA", (0, 0, 0, 0))}]}))
    client.post("/api/ai/image", json={"prompt": "x", "transparent": transparent})
    sent = calls[0][1]["json"]
    assert (sent.get("background") == "transparent") is expect


def capture_get(monkeypatch, resp):
    calls = []

    def get(url, **kw):
        calls.append((url, kw))
        return resp

    monkeypatch.setattr(app_module.http, "get", get)
    return calls


def models(client, **body):
    return client.post("/api/ai/models", json=body)


def test_models_openai_filters_image_models(client, monkeypatch):
    data = {"data": [{"id": i} for i in
                     ("gpt-5", "gpt-image-2", "dall-e-3", "whisper-1", "gpt-image-1-mini", "chatgpt-image-latest")]}
    calls = capture_get(monkeypatch, Resp(json_data=data))
    r = models(client, provider="openai", api_key="sk-typed")
    assert r.get_json() == {"models": ["chatgpt-image-latest", "dall-e-3", "gpt-image-1-mini", "gpt-image-2"],
                            "default": "gpt-image-2"}
    assert calls[0][1]["headers"]["Authorization"] == "Bearer sk-typed"


def test_models_gemini_filters_image_generate_content(client, monkeypatch):
    data = {"models": [
        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-flash-image", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/imagen-4.0-generate-001", "supportedGenerationMethods": ["predict"]},
    ]}
    capture_get(monkeypatch, Resp(json_data=data))
    r = models(client, provider="gemini", api_key="gk")
    assert r.get_json()["models"] == ["gemini-2.5-flash-image"]


def test_models_uses_saved_key_only_for_saved_provider(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("AI_IMAGE_API_KEY", "sk-saved")
    calls = capture_get(monkeypatch, Resp(json_data={"data": []}))
    assert models(client, provider="openai").status_code == 200
    assert calls[0][1]["headers"]["Authorization"] == "Bearer sk-saved"
    r = models(client, provider="gemini")
    assert r.status_code == 400 and len(calls) == 1


def test_models_compatible_lists_all(client, monkeypatch):
    calls = capture_get(monkeypatch, Resp(json_data={"data": [{"id": "flux"}, {"id": "sdxl"}]}))
    r = models(client, provider="compatible", base_url="http://h:8080/v1/")
    assert r.get_json()["models"] == ["flux", "sdxl"]
    assert calls[0][0] == "http://h:8080/v1/models"


def test_models_provider_error_passed_through(client, monkeypatch):
    capture_get(monkeypatch, Resp(401, json_data={"error": {"message": "Incorrect API key"}}))
    r = models(client, provider="openai", api_key="bad")
    assert r.status_code == 502 and r.get_json()["error"] == "Incorrect API key"


def test_models_requires_login(monkeypatch):
    c = app_module.app.test_client()
    assert c.post("/api/ai/models", json={"provider": "openai"}).status_code == 401


def test_openai_transparency_unsupported_retries_opaque(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("AI_IMAGE_MODEL", "gpt-image-2")
    monkeypatch.setenv("AI_IMAGE_API_KEY", "k")
    replies = [Resp(400, json_data={"error": {"message": "Transparent background is not supported for this model."}}),
               Resp(json_data={"data": [{"b64_json": _png("RGB", (250, 250, 250), dot=(40, 160, 40))}]})]
    calls = []

    def post(url, **kw):
        calls.append(kw["json"])
        return replies.pop(0)

    monkeypatch.setattr(app_module.http, "post", post)
    r = client.post("/api/ai/image", json={"prompt": "x", "transparent": True})
    assert r.status_code == 200
    assert calls[0]["background"] == "transparent" and "background" not in calls[1]
    assert _decode(r).getpixel((0, 0))[3] == 0  # cut-out made it transparent


def test_openai_other_errors_not_retried(client, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("AI_IMAGE_API_KEY", "k")
    calls = capture(monkeypatch, Resp(400, json_data={"error": {"message": "No credits remaining"}}))
    r = client.post("/api/ai/image", json={"prompt": "x", "transparent": True})
    assert r.status_code == 502 and len(calls) == 1
