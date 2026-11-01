"""Base class for recipe scrapers.

Scrapers are pure: they take ``(url, soup)`` and return a draft dict or None.
They must never do network I/O.
"""

from urllib.parse import urlparse


def make_draft(**fields):
    """Return a flat recipe draft with defaults filled in (see draft2.py for BA's format)."""
    draft = {
        "name": "",
        "instructions": "",
        "description": None,
        "source": None,
        "garnish": None,
        "glass": None,
        "method": None,
        "tags": [],
        "images": [],
        "author": None,
        "ingredients": [],
    }
    draft.update(fields)
    return draft


class Scraper:
    name = ""
    domains = ()

    def matches(self, url):
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in self.domains)

    def scrape(self, url, soup):
        """Return a draft dict, or None if this scraper finds no recipe."""
        raise NotImplementedError
