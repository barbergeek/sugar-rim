"""Recipe scraper registry.

Site-specific scrapers are tried first (in registration order), the generic
JSON-LD scraper last. To add a site: create a module with a ``Scraper``
subclass decorated with ``@register`` and import it below.
"""

from bs4 import BeautifulSoup

from .base import Scraper, make_draft

_REGISTRY = []


class NoRecipeFound(Exception):
    pass


def register(cls):
    _REGISTRY.append(cls())
    return cls


def scrape(url, html):
    """Return ``(draft, scraper_name)`` or raise NoRecipeFound."""
    soup = BeautifulSoup(html, "html.parser")
    # Generic scrapers (no domains) go last; sort is stable.
    ordered = sorted(_REGISTRY, key=lambda s: not s.domains)
    for scraper in ordered:
        if not scraper.matches(url):
            continue
        draft = scraper.scrape(url, soup)
        if draft:
            return draft, scraper.name
    raise NoRecipeFound(url)


# Site modules self-register on import. The generic scraper must be imported
# too; ordering is handled in scrape().
from . import (
    foodnetwork,  # noqa: F401
    jsonld,  # noqa: F401
)

__all__ = ["NoRecipeFound", "Scraper", "make_draft", "register", "scrape"]
