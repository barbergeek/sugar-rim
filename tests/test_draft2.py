from pathlib import Path

from scrapers import scrape
from scrapers.draft2 import from_draft2, to_draft2

FIXTURE = (
    Path(__file__).parent / "fixtures" / "foodnetwork_gobble_gobble_punch.html"
).read_text()
URL = (
    "https://www.foodnetwork.com/recipes/geoffrey-zakarian/gobble-gobble-punch-4536808"
)


def test_to_draft2_matches_ba_shape():
    draft, _ = scrape(URL, FIXTURE)
    doc = to_draft2(draft)
    recipe = doc["recipe"]
    assert recipe["name"] == "Gobble Gobble Punch"
    assert recipe["instructions"]
    assert len(recipe["ingredients"]) == len(doc["ingredients"]) == 7
    ids = [i["_id"] for i in doc["ingredients"]]
    assert len(set(ids)) == 7
    # Every recipe ingredient resolves to a named top-level ingredient.
    names = {i["_id"]: i["name"] for i in doc["ingredients"]}
    for ri in recipe["ingredients"]:
        assert names[ri["_id"]]
        assert "units" in ri  # BA indexes this key unconditionally
    assert "author" not in recipe


def test_to_draft2_defaults_for_sparse_draft():
    doc = to_draft2({"name": "X", "ingredients": [{"name": "Gin"}]})
    assert doc["recipe"]["instructions"] == ""
    assert doc["recipe"]["tags"] == [] and doc["recipe"]["images"] == []
    ri = doc["recipe"]["ingredients"][0]
    assert ri == {
        "_id": "ingredient-1",
        "amount": 0,
        "amount_max": None,
        "units": None,
        "note": None,
        "optional": False,
        "sort": 1,
    }


def test_round_trip():
    draft, _ = scrape(URL, FIXTURE)
    back = from_draft2(to_draft2(draft))
    for key in ("name", "instructions", "garnish", "tags", "images"):
        assert back[key] == draft[key]
    assert [i["name"] for i in back["ingredients"]] == [
        i["name"] for i in draft["ingredients"]
    ]


def test_from_draft2_ba_scrape_output():
    schema = {
        "recipe": {
            "_id": "negroni",
            "name": "Negroni",
            "instructions": "Stir.",
            "images": [{"uri": "https://x.test/a.jpg", "copyright": "X"}, {"uri": ""}],
            "ingredients": [
                {"_id": "gin", "amount": 30, "units": "ml", "sort": 1},
                {"_id": "campari", "amount": 30, "units": "ml", "optional": True},
            ],
        },
        "ingredients": [
            {"_id": "gin", "name": "Gin"},
            {"_id": "campari", "name": "Campari"},
        ],
    }
    d = from_draft2(schema)
    assert d["name"] == "Negroni" and d["author"] is None
    assert d["images"] == [{"uri": "https://x.test/a.jpg", "copyright": "X"}]
    assert [(i["name"], i["optional"], i["sort"]) for i in d["ingredients"]] == [
        ("Gin", False, 1),
        ("Campari", True, 2),
    ]


def test_from_draft2_empty():
    assert from_draft2({})["ingredients"] == []
