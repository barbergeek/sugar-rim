import pytest
import requests

from scrapers import fetch
from scrapers.fetch import FetchBlocked, FetchError, fetch_html

PAGE = "https://site.test/recipe"
ROBOTS = "https://site.test/robots.txt"


class Resp:
    def __init__(self, status=200, chunks=(b"<html></html>",), headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.encoding = None
        self._chunks = chunks

    def iter_content(self, n):
        for c in self._chunks:
            if isinstance(c, Exception):
                raise c
            yield c

    def close(self):
        pass


def serve(monkeypatch, pages):
    """pages: {url: Resp | Exception}; robots.txt defaults to 404."""

    def get(url, **kw):
        r = pages.get(url, Resp(404) if url.endswith("/robots.txt") else None)
        if r is None:
            raise AssertionError(f"unexpected GET {url}")
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(requests, "get", get)


def allow_all(url):
    return True


def test_ok_uses_declared_charset(monkeypatch):
    r = Resp(
        chunks=("café".encode("latin-1"),),
        headers={"Content-Type": "text/html; charset=latin-1"},
    )
    r.encoding = "latin-1"
    serve(monkeypatch, {PAGE: r})
    assert fetch_html(PAGE, allow_all) == "café"


def test_redirect_followed(monkeypatch):
    serve(
        monkeypatch,
        {
            PAGE: Resp(301, headers={"Location": "/moved"}),
            "https://site.test/moved": Resp(chunks=(b"moved",)),
        },
    )
    assert fetch_html(PAGE, allow_all) == "moved"


def test_too_many_redirects(monkeypatch):
    serve(monkeypatch, {PAGE: Resp(302, headers={"Location": PAGE})})
    with pytest.raises(FetchError, match="Too many redirects"):
        fetch_html(PAGE, allow_all)


@pytest.mark.parametrize("status", [403, 429])
def test_blocked_status(monkeypatch, status):
    serve(monkeypatch, {PAGE: Resp(status)})
    with pytest.raises(FetchBlocked):
        fetch_html(PAGE, allow_all)


def test_other_http_error(monkeypatch):
    serve(monkeypatch, {PAGE: Resp(404)})
    with pytest.raises(FetchError, match="HTTP 404"):
        fetch_html(PAGE, allow_all)


def test_network_error(monkeypatch):
    serve(monkeypatch, {PAGE: requests.ConnectionError("refused")})
    with pytest.raises(FetchError):
        fetch_html(PAGE, allow_all)


def test_stream_error(monkeypatch):
    serve(monkeypatch, {PAGE: Resp(chunks=(b"x", requests.ConnectionError("reset")))})
    with pytest.raises(FetchError):
        fetch_html(PAGE, allow_all)


def test_size_cap(monkeypatch):
    big = b"x" * (fetch.MAX_BYTES // 2 + 1)
    serve(monkeypatch, {PAGE: Resp(chunks=(big, big))})
    with pytest.raises(FetchError, match="too large"):
        fetch_html(PAGE, allow_all)


def test_overall_deadline(monkeypatch):
    serve(monkeypatch, {PAGE: Resp(chunks=(b"a", b"b", b"c"))})
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(fetch.time, "monotonic", lambda: next(clock))
    with pytest.raises(FetchError, match="Timed out"):
        fetch_html(PAGE, allow_all)


def test_robots_disallow(monkeypatch):
    serve(monkeypatch, {ROBOTS: Resp(chunks=(b"User-agent: *\nDisallow: /recipe",))})
    with pytest.raises(FetchBlocked, match="robots.txt"):
        fetch_html(PAGE, allow_all)


def test_robots_allows_other_paths(monkeypatch):
    serve(
        monkeypatch,
        {
            ROBOTS: Resp(chunks=(b"User-agent: *\nDisallow: /private",)),
            PAGE: Resp(chunks=(b"ok",)),
        },
    )
    assert fetch_html(PAGE, allow_all) == "ok"


@pytest.mark.parametrize(
    "robots", [Resp(500), Resp(401), requests.ConnectionError("down")]
)
def test_robots_unavailable_or_refused_blocks(monkeypatch, robots):
    serve(monkeypatch, {ROBOTS: robots})
    with pytest.raises(FetchBlocked):
        fetch_html(PAGE, allow_all)


def test_robots_redirect_is_guarded(monkeypatch):
    serve(
        monkeypatch,
        {ROBOTS: Resp(301, headers={"Location": "http://internal/robots.txt"})},
    )
    with pytest.raises(fetch.UrlNotAllowed):
        fetch_html(PAGE, lambda u: "internal" not in u)
