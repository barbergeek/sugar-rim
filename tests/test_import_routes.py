from pathlib import Path

import pytest
import requests

import app as app_module
from scrapers.fetch import UrlNotAllowed, fetch_html

FIXTURE = (
    Path(__file__).parent / "fixtures" / "foodnetwork_gobble_gobble_punch.html"
).read_text()
URL = (
    "https://www.foodnetwork.com/recipes/geoffrey-zakarian/gobble-gobble-punch-4536808"
)


class Resp:
    def __init__(self, status=200, text="", json_data=None, headers=None):
        self.status_code = status
        self.text = text
        self._json = json_data
        self.headers = headers or {}
        self.encoding = "utf-8"
        self.ok = status < 400

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def iter_content(self, n):
        yield self.text.encode()

    def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    app_module.app.config["TESTING"] = True
    monkeypatch.setenv("BA_API_URL", "http://ba.test")
    monkeypatch.setattr(app_module, "_is_public_http_url", lambda u: "private" not in u)
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s["ba_token"] = "tok"
    return c


def fake_get(pages):
    """pages: {url: Resp}; robots.txt defaults to 404."""
    calls = []

    def get(url, **kw):
        calls.append(url)
        if url in pages:
            return pages[url]
        if url.endswith("/robots.txt"):
            return Resp(404)
        raise AssertionError(f"unexpected GET {url}")

    get.calls = calls
    return get


def test_logged_out():
    c = app_module.app.test_client()
    assert c.post("/api/import/scrape", json={"url": URL}).status_code == 401
    assert c.post("/api/import/cocktail", json={"draft": {}}).status_code == 401


def test_scrape_url(client, monkeypatch):
    monkeypatch.setattr(requests, "get", fake_get({URL: Resp(text=FIXTURE)}))
    r = client.post("/api/import/scrape", json={"url": URL})
    assert r.status_code == 200
    assert r.json["scraper"] == "foodnetwork"
    assert len(r.json["data"]["ingredients"]) == 7


def test_scrape_pasted_html(client, monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: pytest.fail("no fetch expected")
    )
    r = client.post("/api/import/scrape", json={"url": URL, "html": FIXTURE})
    assert r.json["scraper"] == "foodnetwork"


def test_ssrf_url_and_redirect(client, monkeypatch):
    assert (
        client.post("/api/import/scrape", json={"url": "http://private/x"}).status_code
        == 400
    )
    hop = Resp(302, headers={"Location": "http://private/secret"})
    monkeypatch.setattr(requests, "get", fake_get({URL: hop}))
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("no BA fallback"))
    r = client.post("/api/import/scrape", json={"url": URL})
    assert r.status_code == 400 and r.json["error"] == "URL not allowed"


def test_blocked_falls_back_to_ba(client, monkeypatch):
    monkeypatch.setattr(requests, "get", fake_get({URL: Resp(403)}))
    seen = {}

    def post(url, **kw):
        seen.update(url=url, json=kw["json"])
        schema = {"recipe": {"name": "BA draft"}, "ingredients": []}
        return Resp(200, json_data={"data": {"schema": schema}})

    monkeypatch.setattr(requests, "post", post)
    r = client.post("/api/import/scrape", json={"url": URL})
    assert r.json["scraper"] == "bar-assistant"
    assert r.json["data"]["name"] == "BA draft"
    assert seen["json"] == {"source": URL}
    assert seen["url"].endswith("/api/import/scrape")


def test_robots_disallow_falls_back_then_422(client, monkeypatch):
    robots = Resp(text="User-agent: *\nDisallow: /")
    monkeypatch.setattr(
        requests, "get", fake_get({"https://www.foodnetwork.com/robots.txt": robots})
    )
    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp(400, json_data={}))
    r = client.post("/api/import/scrape", json={"url": URL})
    assert r.status_code == 422 and "pasting" in r.json["error"].lower()


def test_no_local_recipe_uses_ba_html_content(client, monkeypatch):
    page = "https://example.com/p"
    monkeypatch.setattr(
        requests, "get", fake_get({page: Resp(text="<html>nothing</html>")})
    )
    seen = {}

    def post(url, **kw):
        seen.update(kw["json"])
        return Resp(200, json_data={"data": {"schema": {"recipe": {"name": "BA"}}}})

    monkeypatch.setattr(requests, "post", post)
    r = client.post("/api/import/scrape", json={"url": page})
    assert r.json["scraper"] == "bar-assistant"
    assert seen == {"source": page, "html_content": "<html>nothing</html>"}

    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp(400, json_data={}))
    r = client.post("/api/import/scrape", json={"url": page})
    assert r.status_code == 422 and r.json["error"] == "No recipe found on this page"


def test_import_cocktail_location_and_errors(client, monkeypatch):
    seen = {}

    def post(url, **kw):
        seen.update(url=url, json=kw["json"])
        return Resp(
            201, json_data={}, headers={"Location": "http://ba.test/api/cocktails/42"}
        )

    monkeypatch.setattr(requests, "post", post)
    r = client.post("/api/import/cocktail", json={"draft": {"name": "X"}})
    assert (r.status_code, r.json) == (201, {"id": 42})
    assert seen["json"]["duplicate_actions"] == "none"
    assert seen["json"]["source"]["recipe"]["name"] == "X"

    monkeypatch.setattr(
        requests, "post", lambda *a, **k: Resp(201, json_data={"data": {"id": 7}})
    )
    assert client.post("/api/import/cocktail", json={"draft": {}}).json == {"id": 7}

    monkeypatch.setattr(
        requests, "post", lambda *a, **k: Resp(422, json_data={"message": "bad"})
    )
    r = client.post("/api/import/cocktail", json={"draft": {}})
    assert (r.status_code, r.json) == (422, {"message": "bad"})


def test_fetch_html_rejects_disallowed():
    with pytest.raises(UrlNotAllowed):
        fetch_html("http://private/x", lambda u: False)


def test_missing_url_or_draft(client):
    assert client.post("/api/import/scrape", json={}).status_code == 400
    assert client.post("/api/import/cocktail", json={"draft": "x"}).status_code == 400


def test_fetch_error_returns_502(client, monkeypatch):
    monkeypatch.setattr(requests, "get", fake_get({URL: Resp(404)}))
    r = client.post("/api/import/scrape", json={"url": URL})
    assert r.status_code == 502 and "HTTP 404" in r.json["error"]


def test_ba_unreachable_during_fallback(client, monkeypatch):
    monkeypatch.setattr(requests, "get", fake_get({URL: Resp(403)}))

    def post(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "post", post)
    r = client.post("/api/import/scrape", json={"url": URL})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "exc,msg",
    [
        (requests.ConnectionError("down"), "Cannot reach Bar Assistant"),
        (requests.Timeout("slow"), "slow"),
    ],
)
def test_import_cocktail_ba_errors(client, monkeypatch, exc, msg):
    def post(*a, **k):
        raise exc

    monkeypatch.setattr(requests, "post", post)
    r = client.post("/api/import/cocktail", json={"draft": {}})
    assert r.status_code == 502 and msg in r.json["error"]


def test_import_cocktail_non_json_and_missing_id(client, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp(500, text="boom"))
    r = client.post("/api/import/cocktail", json={"draft": {}})
    assert (r.status_code, r.json) == (500, {"error": "boom"})

    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp(201, text=""))
    r = client.post("/api/import/cocktail", json={"draft": {}})
    assert r.status_code == 502 and "no cocktail id" in r.json["error"]


def _ing(id, name, shelf=False):
    return {"id": id, "name": name, "in_shelf": shelf, "in_bar_shelf": False}


def test_match_paginates(client, monkeypatch):
    calls = []

    def get(url, **kw):
        calls.append(kw["params"]["page"])
        if kw["params"]["page"] == 1:
            return Resp(
                json_data={"data": [_ing(1, "Rye Whiskey")], "meta": {"last_page": 2}}
            )
        return Resp(
            json_data={
                "data": [_ing(2, "Bourbon Whiskey", True)],
                "meta": {"last_page": 2},
            }
        )

    monkeypatch.setattr(requests, "get", get)
    r = client.post("/api/import/match", json={"names": ["Bourbon", "Unicorn"]})
    assert r.status_code == 200
    assert calls == [1, 2]
    m = r.json["matches"]
    assert m[0][0]["name"] == "Bourbon Whiskey" and m[0][0]["on_shelf"]
    assert m[1] == []


def test_match_auth_and_bad_input(client):
    assert (
        app_module.app.test_client()
        .post("/api/import/match", json={"names": []})
        .status_code
        == 401
    )
    for bad in ({}, {"names": "x"}, {"names": [1]}, {"names": ["a"] * 51}):
        assert client.post("/api/import/match", json=bad).status_code == 400


def test_match_ba_errors_502(client, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp(500))
    r = client.post("/api/import/match", json={"names": ["a"]})
    assert r.status_code == 502 and "error" in r.json

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(requests, "get", boom)
    r = client.post("/api/import/match", json={"names": ["a"]})
    assert r.status_code == 502 and "error" in r.json
