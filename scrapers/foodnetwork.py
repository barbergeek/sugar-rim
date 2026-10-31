"""Food Network scraper. Documented example for adding a new site.

To add a site: create a module like this one, subclass ``JsonLdScraper`` (or
``Scraper`` and implement ``scrape`` with CSS selectors), set ``name`` and
``domains``, decorate with ``@register`` and import it in ``__init__.py``.
"""

import re

from . import register
from .jsonld import JsonLdScraper

_GARNISH_RE = re.compile(r"\bGarnish with ([^.]+?)\s*(?:\.|$)", re.IGNORECASE)


@register
class FoodNetworkScraper(JsonLdScraper):
    name = "foodnetwork"
    domains = ("foodnetwork.com",)

    def post_process(self, draft, data):
        m = _GARNISH_RE.search(draft["instructions"] or "")
        if m:
            draft["garnish"] = m.group(1).strip()
        return draft
