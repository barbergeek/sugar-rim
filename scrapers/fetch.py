"""Polite, SSRF-guarded HTML fetch: honest UA, robots.txt, capped body.

Some sites (e.g. Food Network) 403 any client that doesn't look like a real
browser at the TLS level, regardless of User-Agent. When the honest fetch is
refused, we retry once with curl_cffi impersonating Chrome. robots.txt is still
checked with our own UA first, so a site that opts out is never fetched.
"""

import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from curl_cffi import requests as browser_requests

MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT = 15


class UrlNotAllowed(Exception):
    pass


class FetchBlocked(Exception):
    """Remote refused us (403/429) or robots.txt disallows."""


class FetchError(Exception):
    pass


def _requests_get(url, headers):
    return requests.get(
        url, headers=headers, timeout=TIMEOUT, stream=True, allow_redirects=False
    )


def _browser_get(url, headers):
    return browser_requests.get(
        url, impersonate="chrome", timeout=TIMEOUT, stream=True, allow_redirects=False
    )


_NET_ERRORS = (requests.RequestException, browser_requests.RequestsError)


def _get(url, headers, is_allowed, hop_check=None, get=_requests_get):
    """GET with manual redirects (each hop re-checked), a 5 MB cap and a 15s
    overall deadline. Returns (status, body, content_type, encoding)."""
    deadline = time.monotonic() + TIMEOUT
    for _ in range(MAX_REDIRECTS + 1):
        if not is_allowed(url):
            raise UrlNotAllowed(url)
        if hop_check:
            hop_check(url)
        try:
            r = get(url, headers)
        except _NET_ERRORS as e:
            raise FetchError(str(e)) from e
        try:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                url = urljoin(url, r.headers["Location"])
                continue
            body = b""
            if r.status_code < 300:
                try:
                    for chunk in r.iter_content(65536):
                        body += chunk
                        if len(body) > MAX_BYTES:
                            raise FetchError("Page is too large")
                        if time.monotonic() > deadline:
                            raise FetchError("Timed out")
                except _NET_ERRORS as e:
                    raise FetchError(str(e)) from e
            return r.status_code, body, r.headers.get("Content-Type", ""), r.encoding
        finally:
            r.close()
    raise FetchError("Too many redirects")


def _robots_allows(url, user_agent, is_allowed):
    p = urlparse(url)
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    try:
        status, body, _, _ = _get(robots_url, {"User-Agent": user_agent}, is_allowed)
    except FetchError as e:
        raise FetchBlocked(f"robots.txt unavailable: {e}") from e
    if status in (401, 403) or status >= 500:
        return False
    if status != 200:
        return True
    rp = RobotFileParser()
    rp.parse(body.decode("utf-8", errors="replace").splitlines())
    return rp.can_fetch(user_agent, url)


def fetch_html(url, is_allowed, user_agent="sugar-rim"):
    """Fetch ``url`` and return its HTML text."""
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"}

    def check_robots(hop):
        if not _robots_allows(hop, user_agent, is_allowed):
            raise FetchBlocked("robots.txt disallows fetching this URL")

    status, body, ct, encoding = _get(url, headers, is_allowed, check_robots)
    if status in (403, 429):
        status, body, ct, encoding = _get(
            url, headers, is_allowed, check_robots, _browser_get
        )
    if status in (403, 429):
        raise FetchBlocked(f"HTTP {status}")
    if status >= 300:
        raise FetchError(f"HTTP {status}")
    enc = encoding if "charset" in ct.lower() and encoding else "utf-8"
    return body.decode(enc, errors="replace")
