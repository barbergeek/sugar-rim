from pathlib import Path

import pytest
from bs4 import BeautifulSoup

import scrapers
from scrapers.base import Scraper, make_draft

FIXTURE = Path(__file__).parent / "fixtures" / "foodnetwork_gobble_gobble_punch.html"
URL = (
    "https://www.foodnetwork.com/recipes/geoffrey-zakarian/gobble-gobble-punch-4536808"
)


def test_foodnetwork_fixture():
    draft, name = scrapers.scrape(URL, FIXTURE.read_text())
    assert name == "foodnetwork"
    assert draft["name"] == "Gobble Gobble Punch"
    assert draft["author"] == "Geoffrey Zakarian"
    assert len(draft["ingredients"]) == 7
    assert draft["instructions"].startswith("Put ice into a punch bowl")
    assert len(draft["images"]) == 1
    assert draft["garnish"] == "orange slices and freshly ground nutmeg"
    assert draft["source"] == URL
    assert "Bourbon" in draft["tags"] and "Punch Recipes" in draft["tags"]
    assert [i["sort"] for i in draft["ingredients"]] == list(range(1, 8))


def test_generic_jsonld_on_other_domain():
    _, name = scrapers.scrape("https://example.com/x", FIXTURE.read_text())
    assert name == "jsonld"


def test_no_recipe():
    with pytest.raises(scrapers.NoRecipeFound):
        scrapers.scrape("https://example.com/x", "<html><body>hi</body></html>")


def test_graph_and_numbered_instructions():
    html = """<script type="application/ld+json">{"@graph":[{"@type":"WebPage"},
    {"@type":["Recipe","Thing"],"name":"X","author":"Bob","image":"http://i/x.jpg",
    "recipeIngredient":["2 oz gin"],"recipeCategory":"Beverage",
    "recipeInstructions":[{"@type":"HowToSection","itemListElement":[
    {"@type":"HowToStep","text":"Stir."},{"@type":"HowToStep","text":"Strain."}]}]}]}</script>"""
    draft, _ = scrapers.scrape("https://example.com/x", html)
    assert draft["instructions"] == "1. Stir.\n2. Strain."
    assert draft["author"] == "Bob"
    assert draft["tags"] == []
    assert draft["images"][0]["uri"] == "http://i/x.jpg"


def test_registered_site_scraper_wins_over_generic():
    class Dummy(Scraper):
        name = "dummy"
        domains = ("dummy.test",)

        def scrape(self, url, soup):
            return make_draft(name="from dummy")

    scrapers.register(Dummy)
    try:
        draft, name = scrapers.scrape("https://www.dummy.test/r", FIXTURE.read_text())
        assert (name, draft["name"]) == ("dummy", "from dummy")
    finally:
        scrapers._REGISTRY.pop()


def test_scrapers_take_soup():
    soup = BeautifulSoup(FIXTURE.read_text(), "html.parser")
    assert (
        scrapers.foodnetwork.FoodNetworkScraper().scrape(URL, soup)["name"]
        == "Gobble Gobble Punch"
    )


def test_string_ingredient_and_list_name():
    html = """<script type="application/ld+json">{"@type":"Recipe","name":["Fizz","x"],
    "recipeIngredient":"2 oz gin","recipeInstructions":"Shake."}</script>"""
    draft, _ = scrapers.scrape("https://example.com/x", html)
    assert draft["name"] == "Fizz, x"
    assert [i["name"] for i in draft["ingredients"]] == ["Gin"]
