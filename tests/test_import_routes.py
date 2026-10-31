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
        return Resp(200, json_data={"data": {"schema": {"name": "BA draft"}}})

    monkeypatch.setattr(requests, "post", post)
    r = client.post("/api/import/scrape", json={"url": URL})
    assert r.json == {"data": {"name": "BA draft"}, "scraper": "bar-assistant"}
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
        return Resp(200, json_data={"data": {"schema": {"name": "BA"}}})

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
    assert seen["json"] == {"source": {"name": "X"}, "duplicate_actions": "none"}

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
