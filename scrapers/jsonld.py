"""Generic scraper for pages that embed a schema.org Recipe as JSON-LD."""

import json
import re

from . import register
from .base import Scraper, make_draft
from .ingredients import parse_line


def _is_recipe(node):
    t = node.get("@type")
    return t == "Recipe" or (isinstance(t, list) and "Recipe" in t)


def _find_recipe(data):
    if isinstance(data, list):
        for item in data:
            r = _find_recipe(item)
            if r:
                return r
    elif isinstance(data, dict):
        if _is_recipe(data):
            return data
        for key in ("@graph", "mainEntity"):
            if key in data:
                r = _find_recipe(data[key])
                if r:
                    return r
    return None


def _name_of(v):
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        return _name_of(v.get("name") or v.get("url") or "")
    if isinstance(v, list):
        names = [n for n in (_name_of(x) for x in v) if n]
        return ", ".join(names)
    return ""


def _first_image(v):
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get("url") or v.get("contentUrl")
    if isinstance(v, list):
        for x in v:
            r = _first_image(x)
            if r:
                return r
    return None


def _steps(v):
    if isinstance(v, str):
        return [s.strip() for s in re.split(r"\r?\n+", v) if s.strip()]
    if isinstance(v, dict):
        if "itemListElement" in v:
            return _steps(v["itemListElement"])
        return _steps(v.get("text") or v.get("name") or "")
    if isinstance(v, list):
        out = []
        for x in v:
            out.extend(_steps(x))
        return out
    return []


def _tags(data):
    raw = []
    for key in ("recipeCategory", "keywords"):
        v = data.get(key)
        if isinstance(v, str):
            raw.extend(v.split(","))
        elif isinstance(v, list):
            raw.extend(str(x) for x in v)
    seen, out = set(), []
    for t in raw:
        t = t.strip()
        if t and t.lower() != "beverage" and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


@register
class JsonLdScraper(Scraper):
    name = "jsonld"

    def matches(self, url):
        return super().matches(url) if self.domains else True

    def clean_ingredient_line(self, line):
        """Hook: tidy a raw ingredient line before parsing."""
        return line

    def post_process(self, draft, data):
        """Hook: adjust the draft using the raw Recipe data."""
        return draft

    def _recipe(self, soup):
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or tag.get_text(), strict=False)
            except ValueError:
                continue
            r = _find_recipe(data)
            if r:
                return r
        return None

    def scrape(self, url, soup):
        data = self._recipe(soup)
        if not data:
            return None
        steps = _steps(data.get("recipeInstructions"))
        instructions = (
            steps[0]
            if len(steps) == 1
            else "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
        )
        ingredients = []
        raw_lines = data.get("recipeIngredient") or []
        if isinstance(raw_lines, str):
            raw_lines = [raw_lines]
        for line in raw_lines:
            line = self.clean_ingredient_line(str(line))
            if not line.strip():
                continue
            ing = parse_line(line)
            ing["sort"] = len(ingredients) + 1
            ingredients.append(ing)
        img = _first_image(data.get("image"))
        draft = make_draft(
            name=_name_of(data.get("name")),
            instructions=instructions,
            description=(data.get("description") or None),
            source=url,
            tags=_tags(data),
            images=[{"uri": img, "copyright": None}] if img else [],
            author=_name_of(data.get("author")) or None,
            ingredients=ingredients,
        )
        return self.post_process(draft, data)
