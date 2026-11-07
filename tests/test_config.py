import pytest
import requests

import app as app_module
from tests.test_import_routes import Resp

OLD = "http://wrong.test"


@pytest.fixture
def anon(monkeypatch, tmp_path):
    app_module.app.config["TESTING"] = True
    monkeypatch.setattr(app_module, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.setenv("BA_API_URL", OLD)
    return app_module.app.test_client()


def login_post(monkeypatch, result):
    def post(url, **kw):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(app_module.http, "post", post)


def test_config_stays_gated_and_explains_fix(anon):
    r = anon.post("/config", json={"api_url": "http://evil.test"})
    assert r.status_code == 401
    assert "BA_API_URL" in r.get_json()["error"]
    assert anon.get("/config").get_json()["api_url"] == OLD


def test_login_unreachable_explains_fix(anon, monkeypatch):
    login_post(monkeypatch, requests.exceptions.ConnectionError("no route"))
    r = anon.post("/api/auth/login", json={"email": "a@b.c", "password": "x"})
    assert r.status_code == 502
    err = r.get_json()["error"]
    assert OLD in err and "BA_API_URL" in err


def test_login_non_ba_reply_explains_fix(anon, monkeypatch):
    real = requests.Response()
    real.status_code, real._content = 200, b"<html>some other app</html>"
    login_post(monkeypatch, real)
    r = anon.post("/api/auth/login", json={"email": "a@b.c", "password": "x"})
    assert r.status_code == 502
    assert "didn't answer like Bar Assistant" in r.get_json()["error"]


def test_login_bad_credentials_passes_ba_error_through(anon, monkeypatch):
    login_post(monkeypatch, Resp(400, json_data={"message": "Unable to authenticate."}))
    r = anon.post("/api/auth/login", json={"email": "a@b.c", "password": "x"})
    assert r.status_code == 400
    assert r.get_json()["message"] == "Unable to authenticate."


def test_blank_env_var_does_not_shadow_saved_value(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("BA_API_URL=http://saved.test\nBA_BAR_ID=3\n")
    monkeypatch.setenv("BA_API_URL", "")
    monkeypatch.setenv("BA_BAR_ID", "7")
    app_module._load_env(str(env))
    assert app_module.os.environ["BA_API_URL"] == "http://saved.test"
    assert app_module.os.environ["BA_BAR_ID"] == "7"
