from datetime import date

import pytest

import app as app_module
import menu_suggest as ms
from tests.test_import_routes import Resp
from tests.test_menu import BASE, CATALOG

# ── Calendar and candidates (pure code) ───────────────────────────────────────


def test_default_occasion_follows_the_calendar():
    assert ms._thanksgiving(2026) == date(2026, 11, 26)
    assert ms._thanksgiving(2025) == date(2025, 11, 27)
    assert ms.default_occasion(date(2026, 11, 15)) == "Thanksgiving dinner"
    assert ms.default_occasion(date(2026, 11, 27)) == "Christmas"
    assert ms.default_occasion(date(2026, 12, 26)) == "New Year's Eve party"
    assert ms.default_occasion(date(2027, 1, 2)) == ""
    assert ms.default_occasion(date(2026, 6, 1)) == ""


def ing(iid, name, optional=False, flag=False):
    return {
        "optional": optional,
        "ingredient": {"id": iid, "name": name, "in_bar_shelf": flag},
    }


def test_missing_counts_like_the_shelf_dots():
    c = {
        "ingredients": [
            ing(1, "Gin"),
            ing(2, "Lime", flag=True),
            ing(3, "Bitters", optional=True),
            ing(4, "Maple"),
        ]
    }
    assert ms.missing_ingredients(c, {1}) == [{"id": 4, "name": "Maple"}]


def test_candidates_drop_far_drinks_and_sort_by_missing():
    near = {"id": 1, "name": "B", "ingredients": [ing(9, "X")]}
    ready = {"id": 2, "name": "A", "ingredients": [ing(1, "Gin")]}
    far = {"id": 3, "name": "C", "ingredients": [ing(7, "P"), ing(8, "Q"), ing(9, "X")]}
    empty = {"id": 4, "name": "D", "ingredients": []}
    pool = ms.candidates([near, far, ready, empty], {1})
    assert [c["id"] for c, _ in pool] == [2, 1]


def test_drink_state_is_what_a_person_would_read():
    s = ms.drink_state(CATALOG[1])
    assert s["name"] == "Cider Sour"
    assert s["ingredients"][0] == "1 ½ oz Bourbon"
    assert s["ingredients"][2] == "1–2 dashes Angostura (optional)"
    assert "id" not in s and "created_user" not in s


# ── Deciding (code over answers) ──────────────────────────────────────────────


def answers(
    fit=(0.0, 0.3, 0.7), batch=0.1, easy=0.5, alcohol=0.95, base="whiskey", base_p=0.9
):
    other = (1 - base_p) / 7
    probs = {
        k: (base_p if k == base else other) for k in ms.QUESTIONS["base"]["criteria"]
    }
    return {
        "fit": {
            "type": "score",
            "probabilities": {str(i): p for i, p in enumerate(fit)},
        },
        "batchable": {"type": "noul", "noul": batch},
        "approachable": {"type": "noul", "noul": easy},
        "alcoholic": {"type": "noul", "noul": alcohol},
        "base": {"type": "choice", "choice": base, "probabilities": probs},
    }


def drink(i, missing=0, abv=20, **kw):
    c = {"id": i, "name": f"D{i}", "abv": abv}
    return ms.assess(
        c, [{"id": 100 + n, "name": "x"} for n in range(missing)], answers(**kw)
    )


def test_assess_reads_answers_through_thresholds():
    d = drink(1, abv=None, alcohol=0.1, batch=0.9, easy=0.8)
    assert d["zero_proof"] and d["batchable"] and d["base"] is None
    assert d["tags"] == ["Seasonal", "Batchable", "Zero-proof", "Easy-drinking"]
    unsure = drink(2, abv=None, alcohol=0.5)
    assert not unsure[
        "zero_proof"
    ]  # between thresholds: not settled, so not zero-proof
    assert drink(3, base_p=0.4)["base"] is None  # unsure base doesn't block variety
    assert drink(4, fit=(0.8, 0.2, 0.0))["clash"]


def test_pick_reserves_roles_and_varies_base():
    ds = [
        drink(1, base="whiskey", fit=(0, 0, 1)),
        drink(
            2, base="whiskey", fit=(0, 0.1, 0.9)
        ),  # second whiskey: skipped for variety
        drink(3, base="rum", fit=(0, 0.5, 0.5)),
        drink(4, base="gin", fit=(0, 0.6, 0.4), batch=0.9),
        drink(5, abv=0, alcohol=0.05, fit=(0, 0.8, 0.2)),
        drink(6, base="vodka", fit=(0.9, 0.1, 0)),  # clashes with the occasion
    ]
    picks, alternates, unfilled = ms.pick(ds)
    assert [p["id"] for p in picks] == [5, 4, 1, 3]
    assert [p["role"] for p in picks] == ["zero_proof", "batchable", None, None]
    assert [a["id"] for a in alternates] == [2]
    assert unfilled == []


def test_pick_says_which_slots_went_unfilled_and_still_fills():
    ds = [drink(i, base="whiskey", fit=(0, 0, 1)) for i in range(1, 4)]
    picks, _, unfilled = ms.pick(ds)
    assert [p["id"] for p in picks] == [1, 2, 3]  # variety gave way to filling the menu
    assert "No zero-proof drink suits the occasion" in unfilled
    assert "No drink can be batched ahead" in unfilled
    assert any("Only 3 drinks" in u for u in unfilled)


def test_missing_ingredients_lower_the_rank():
    picks, alternates, _ = ms.pick(
        [drink(1, missing=2, base="rum"), drink(2, base="gin")], size=1
    )
    assert picks[0]["id"] == 2


# ── Asking TypeSafe ───────────────────────────────────────────────────────────


@pytest.fixture
def jev(monkeypatch):
    calls = []

    def post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        assert url == ms.API_URL and headers["Authorization"] == "Bearer k"
        name = json["state"]["drink"]["name"]
        r = Resp(
            json_data={
                "answers": answers(base="rum" if name == "Drink 3" else "whiskey")
            }
        )
        return r

    monkeypatch.setattr(ms.requests, "post", post)
    return calls


def test_suggest_asks_one_request_per_drink(jev):
    # Cider Sour is 2 purchases away (optional bitters don't count); Drink 3
    # lists no ingredients, so it isn't judged at all.
    cocktails = [CATALOG[1], CATALOG[3]]
    out = ms.suggest("k", "Thanksgiving dinner", cocktails, set())
    assert out["considered"] == 1 and out["total"] == 2
    assert len(jev) == out["considered"]
    assert jev[0]["model"] == ms.MODEL
    assert jev[0]["state"]["occasion"] == "Thanksgiving dinner"
    assert set(jev[0]["questions"]) == {
        "fit",
        "batchable",
        "approachable",
        "alcoholic",
        "base",
    }


def test_a_failed_call_fails_the_suggestion(monkeypatch):
    monkeypatch.setattr(ms.requests, "post", lambda *a, **k: Resp(500, text="boom"))
    with pytest.raises(ms.SuggestError, match="500"):
        ms.suggest("k", "x", [CATALOG[1]], set())


def test_rate_limit_is_retried(monkeypatch):
    replies = [
        Resp(429, headers={"retry-after": "0"}),
        Resp(json_data={"answers": answers()}),
    ]
    monkeypatch.setattr(ms.requests, "post", lambda *a, **k: replies.pop(0))
    assert ms._ask("k", {}) == answers()


def test_bad_key_is_named(monkeypatch):
    monkeypatch.setattr(ms.requests, "post", lambda *a, **k: Resp(401, text="no"))
    with pytest.raises(ms.SuggestError, match="rejected the API key"):
        ms._ask("k", {})


# ── Routes ────────────────────────────────────────────────────────────────────


def test_suggest_needs_a_key(owner):
    r = owner.post("/api/menu/suggest", json={"occasion": "Thanksgiving dinner"})
    assert r.status_code == 400 and "TypeSafe API key" in r.get_json()["error"]


def test_suggest_route_uses_shelf_and_library(owner, ba, monkeypatch, jev):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setenv("BA_BAR_ID", "1")
    real_get = ba.get

    def get(url, **kw):
        if url == "http://ba.test/api/bars/1/ingredients":
            return Resp(json_data={"data": [{"id": 1}], "meta": {"last_page": 1}})
        if (
            url == "http://ba.test/api/cocktails"
            and "filter[collection_id]" not in kw["params"]
        ):
            assert kw["params"]["include"] == "ingredients.ingredient,glass,method"
            gin = {
                "id": 3,
                "name": "Drink 3",
                "abv": 20,
                "ingredients": [ing(1, "Gin")],
            }
            return Resp(json_data={"data": [gin], "meta": {"last_page": 1}})
        return real_get(url, **kw)

    monkeypatch.setattr(app_module.http, "get", get)
    r = owner.post("/api/menu/suggest", json={"occasion": "  Thanksgiving   dinner "})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["occasion"] == "Thanksgiving dinner"
    assert [p["id"] for p in r.get_json()["picks"]] == [3]


def test_set_replaces_the_menu_and_publishes(owner, ba):
    owner.post("/api/menu/collection", json={"collection_id": 5})
    r = owner.post(
        "/api/menu/cocktails/set", json={"cocktail_ids": [3, 4, 3], "public_base": BASE}
    )
    assert r.status_code == 200 and ba.members == [3, 4]
    assert r.get_json()["published"]["count"] == 2
    bad = owner.post(
        "/api/menu/cocktails/set", json={"cocktail_ids": [], "public_base": BASE}
    )
    assert bad.status_code == 400


def test_typesafe_key_is_write_only(owner, monkeypatch, env):
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    assert owner.post("/config", json={"typesafe_api_key": " sk-1 "}).status_code == 200
    cfg = owner.get("/config").get_json()
    assert cfg["typesafe_key_set"] is True and "sk-1" not in str(cfg)
    assert app_module.os.environ["TYPESAFE_API_KEY"] == "sk-1"
