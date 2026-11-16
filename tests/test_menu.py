import pytest

import app as app_module
import menu
from tests.test_import_routes import Resp

BA = "http://ba.test"
BASE = "https://sugar.example"

COCKTAILS = [
    {
        "id": 1,
        "slug": "cider-sour",
        "name": "Cider Sour",
        "description": "Bright and appley.",
        "instructions": "Shake.",
        "garnish": "Apple fan",
        "glass": {"name": "Coupe"},
        "method": {"name": "Shake"},
        "abv": 18.5,
        "created_user": {"name": "Secret Person"},
        "images": [{"id": 77}],
        "ingredients": [
            {
                "sort": 2,
                "amount": 22.5,
                "units": "ml",
                "ingredient": {"name": "Lemon Juice"},
            },
            {"sort": 1, "amount": 45, "units": "ml", "ingredient": {"name": "Bourbon"}},
            {
                "sort": 3,
                "amount": 1,
                "amount_max": 2,
                "units": "dashes",
                "ingredient": {"name": "Angostura"},
                "optional": True,
            },
        ],
    },
    {
        "id": 2,
        "slug": "maple-old-fashioned",
        "name": "Maple Old Fashioned",
        "images": [],
        "ingredients": [],
    },
]


EXTRA = [
    {
        "id": i,
        "slug": f"drink-{i}",
        "name": f"Drink {i}",
        "images": [],
        "ingredients": [],
    }
    for i in range(3, 10)
]
CATALOG = {c["id"]: c for c in COCKTAILS + EXTRA}


class FakeBA:
    """Bar Assistant with one collection (5) whose members can change."""

    def __init__(self, members=(1, 2)):
        self.members = list(members)
        self.created = []

    def get(self, url, **kw):
        if url == f"{BA}/api/collections/5":
            return Resp(
                json_data={
                    "data": {
                        "id": 5,
                        "name": "Thanksgiving 2026",
                        "description": "Fall favorites",
                        # No "cocktails": BA may leave them out of the detail.
                    }
                }
            )
        if url == f"{BA}/api/collections/404":
            return Resp(404, json_data={})
        if url == f"{BA}/api/cocktails":
            assert kw["params"]["filter[collection_id]"] == 5
            return Resp(json_data={"data": [CATALOG[i] for i in self.members]})
        if url == f"{BA}/api/images/77/thumb":
            r = Resp()
            r.content = b"\xff\xd8jpeg"
            return r
        raise AssertionError(f"unexpected GET {url}")

    def put(self, url, json=None, **kw):
        assert url == f"{BA}/api/collections/5/cocktails"
        self.members = list(json["cocktails"])
        return Resp(204)

    def post(self, url, json=None, **kw):
        assert url == f"{BA}/api/collections"
        self.created.append(json)
        # The spec documents only a Location header, so send no body.
        return Resp(201, headers={"Location": f"{BA}/api/collections/5"})


@pytest.fixture
def ba(monkeypatch):
    fake = FakeBA()
    for verb in ("get", "put", "post"):
        monkeypatch.setattr(app_module.http, verb, getattr(fake, verb))
    return fake


@pytest.fixture
def env(monkeypatch, tmp_path, ba):
    app_module.app.config["TESTING"] = True
    monkeypatch.setattr(app_module, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.setenv("BA_API_URL", BA)
    # setenv (not delenv) so teardown restores them: the app writes os.environ.
    monkeypatch.setenv("MENU_COLLECTION_ID", "")
    return tmp_path


@pytest.fixture
def owner(env):
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s["ba_token"] = "tok"
    return c


@pytest.fixture
def guest(env):
    return app_module.app.test_client()


def publish(owner):
    r = owner.post("/api/menu/publish", json={"collection_id": 5, "public_base": BASE})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_owner_routes_need_login(guest):
    assert guest.get("/api/menu").status_code == 401
    assert guest.post("/api/menu/publish", json={"collection_id": 5}).status_code == 401


def test_publish_snapshots_collection(owner, env):
    state = publish(owner)
    assert state["published"]["title"] == "Thanksgiving 2026"
    assert state["published"]["count"] == 2
    assert state["url"] == f"{BASE}/menu"
    snap = menu.load(menu.menu_dir(str(env / ".env")))
    cider = snap["cocktails"][0]
    # Only what the public pages show; nobody's account details.
    assert "created_user" not in cider and "id" not in cider
    assert [i["name"] for i in cider["ingredients"]] == [
        "Bourbon",
        "Lemon Juice",
        "Angostura",
    ]
    assert cider["ingredients"][0]["amount"] == "1 ½ oz"
    assert cider["ingredients"][2]["amount"] == "1–2 dashes"
    assert cider["image"] == "cider-sour.jpg"
    assert snap["cocktails"][1]["image"] is None


def test_publish_rejects_bad_input(owner, ba):
    bad = [
        {"collection_id": "5", "public_base": BASE},
        {"collection_id": 5, "public_base": "javascript:alert(1)"},
    ]
    for body in bad:
        assert owner.post("/api/menu/publish", json=body).status_code == 400
    ba.members = []
    r = owner.post("/api/menu/publish", json={"collection_id": 5, "public_base": BASE})
    assert r.status_code == 400
    ba.members = list(CATALOG)
    r = owner.post("/api/menu/publish", json={"collection_id": 5, "public_base": BASE})
    assert r.status_code == 400 and "at most" in r.get_json()["error"]


def test_republish_drops_unused_photos(owner, env, ba):
    publish(owner)
    ba.members = [2]
    publish(owner)
    assert not (env / "menu" / "cider-sour.jpg").exists()


def test_public_pages_need_no_login_and_ignore_old_keys(owner, guest):
    publish(owner)
    for path in ("/menu", "/menu/r/cider-sour", "/menu/img/cider-sour"):
        assert guest.get(path).status_code == 200
        assert guest.get(path + "?key=from-an-old-link").status_code == 200


def test_board_shows_menu_with_qr_to_recipe(owner, guest):
    publish(owner)
    r = guest.get("/menu")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Thanksgiving 2026" in html and "Maple Old Fashioned" in html
    # The board shows the drink's own description, not an ingredient list.
    assert "Bright and appley." in html and "Lemon Juice" not in html
    assert "<svg" in html and "key=" not in html
    assert "data-menu-board" in html  # what the TV's reload check looks for
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["Cache-Control"] == "no-store"
    assert "--inset: 5" in html
    assert "--inset: 15" in guest.get("/menu?inset=99").get_data(as_text=True)


def test_recipe_and_image_only_for_menu_cocktails(owner, guest):
    publish(owner)
    r = guest.get("/menu/r/cider-sour")
    assert r.status_code == 200 and "Apple fan" in r.get_data(as_text=True)
    assert guest.get("/menu/r/not-on-menu").status_code == 404
    img = guest.get("/menu/img/cider-sour")
    assert img.status_code == 200 and img.data == b"\xff\xd8jpeg"
    assert guest.get("/menu/img/maple-old-fashioned").status_code == 404
    assert guest.get("/menu/img/..%2F.env").status_code == 404


def test_board_before_anything_published(owner, guest):
    state = owner.get("/api/menu").get_json()
    assert state["published"] is None and state["url"] is None
    assert state["collection"] is None
    r = guest.get("/menu")
    assert r.status_code == 200 and "No menu has been published" in r.get_data(
        as_text=True
    )


def toggle(owner, cocktail_id, on):
    return owner.post(
        "/api/menu/cocktails",
        json={"cocktail_id": cocktail_id, "on": on, "public_base": BASE},
    )


def test_publish_remembers_the_menu_collection(owner):
    state = publish(owner)
    assert state["collection"] == {
        "id": 5,
        "name": "Thanksgiving 2026",
        "drinks": [
            {"id": 1, "name": "Cider Sour"},
            {"id": 2, "name": "Maple Old Fashioned"},
        ],
        "cocktail_ids": [1, 2],
    }
    assert app_module.os.environ["MENU_COLLECTION_ID"] == "5"


def test_menu_state_reports_a_collection_it_cannot_load(owner, ba, monkeypatch):
    # A silent failure used to look like "no menu" and hid the add buttons.
    owner.post("/api/menu/collection", json={"collection_id": 5})
    real_get = ba.get

    def get(url, **kw):
        if url.endswith("/api/cocktails"):
            return Resp(500, json_data={})
        return real_get(url, **kw)

    monkeypatch.setattr(app_module.http, "get", get)
    state = owner.get("/api/menu").get_json()
    assert state["collection"] is None
    assert "lookup failed" in state["collection_error"]


def test_toggle_needs_a_menu_collection(owner):
    r = toggle(owner, 3, True)
    assert r.status_code == 400 and "Manage → Holiday Menu" in r.get_json()["error"]


def test_toggle_adds_and_removes_then_republishes(owner, ba, env):
    publish(owner)
    r = toggle(owner, 3, True)
    assert r.status_code == 200
    assert ba.members == [1, 2, 3]
    assert r.get_json()["published"]["count"] == 3
    assert r.get_json()["collection"]["cocktail_ids"] == [1, 2, 3]
    toggle(owner, 3, True)  # already on: no duplicate
    assert ba.members == [1, 2, 3]
    r = toggle(owner, 1, False)
    assert ba.members == [2, 3] and r.get_json()["published"]["count"] == 2
    names = [
        c["name"] for c in menu.load(menu.menu_dir(str(env / ".env")))["cocktails"]
    ]
    assert names == ["Maple Old Fashioned", "Drink 3"]


def test_adding_keeps_the_drinks_already_there(owner, ba):
    # Regression: members come from the cocktail filter, never an empty detail.
    ba.members = [1, 2, 4]
    owner.post("/api/menu/collection", json={"collection_id": 5})
    toggle(owner, 3, True)
    assert ba.members == [1, 2, 4, 3]


def test_a_failed_member_lookup_changes_nothing(owner, ba, monkeypatch):
    owner.post("/api/menu/collection", json={"collection_id": 5})
    real_get = ba.get

    def get(url, **kw):
        if url.endswith("/api/cocktails"):
            return Resp(500, json_data={})
        return real_get(url, **kw)

    monkeypatch.setattr(app_module.http, "get", get)
    assert toggle(owner, 3, True).status_code == 502
    assert ba.members == [1, 2]


def test_toggle_refuses_a_seventh_drink(owner, ba):
    ba.members = [1, 2, 3, 4, 5, 6]
    publish(owner)
    r = toggle(owner, 7, True)
    assert r.status_code == 400 and "already has 6" in r.get_json()["error"]
    assert ba.members == [1, 2, 3, 4, 5, 6]


def test_emptying_the_menu_keeps_the_last_board(owner, ba):
    ba.members = [1]
    publish(owner)
    r = toggle(owner, 1, False)
    assert r.status_code == 200 and ba.members == []
    assert "still shows" in r.get_json()["publish_error"]
    assert r.get_json()["published"]["count"] == 1


def test_choose_or_create_the_menu_collection(owner, ba):
    r = owner.post("/api/menu/collection", json={"collection_id": 5})
    assert r.status_code == 200 and r.get_json()["collection"]["id"] == 5
    assert (
        owner.post("/api/menu/collection", json={"collection_id": 404}).status_code
        == 404
    )
    r = owner.post("/api/menu/collection", json={"name": " Christmas 2026 "})
    assert r.status_code == 200
    assert ba.created == [{"name": "Christmas 2026", "description": None}]
    assert app_module.os.environ["MENU_COLLECTION_ID"] == "5"


def test_new_owner_routes_need_login(guest):
    assert guest.post("/api/menu/collection", json={"name": "x"}).status_code == 401
    assert toggle(guest, 1, True).status_code == 401


def test_blurb_prefers_the_description_then_spirits_first():
    assert menu.blurb({"description": "America&#039;s best", "ingredients": []}) == (
        "America's best"
    )

    def i(name, strength=0, optional=False):
        return {"name": name, "strength": strength, "optional": optional}

    c = {
        "description": "",
        "ingredients": [
            i("Cranberries"),
            i("Orange juice"),
            i("Sugar"),
            i("Bourbon Whiskey", 40),
            i("Apple"),
            i("Apple"),
            i("Bitters", 45, optional=True),
        ],
    }
    assert menu.blurb(c) == "Made with Bourbon Whiskey, Cranberries and Orange juice."
    assert menu.blurb({"description": "", "ingredients": [i("Apple"), i("apple")]}) == (
        "Made with Apple."
    )
    assert menu.blurb({"description": "", "ingredients": []}) == ""


def test_publish_decodes_entities_and_keeps_strength(env):
    slim = menu.slim_cocktail(
        {
            "slug": "x",
            "description": "Test Kitchen&#039;s &amp; more",
            "ingredients": [{"ingredient": {"name": "Rye", "strength": 45}}],
        }
    )
    assert slim["description"] == "Test Kitchen's & more"
    assert slim["ingredients"][0]["strength"] == 45


def test_fmt_amount():
    assert menu.fmt_amount(30, None, "ml") == "1 oz"
    assert menu.fmt_amount(7.5, None, "ml") == "¼ oz"
    assert menu.fmt_amount(2, None, "dashes") == "2 dashes"
    assert menu.fmt_amount(None, None, "") == ""
    assert menu.fmt_amount(1, None, "whole") == "1 whole"
