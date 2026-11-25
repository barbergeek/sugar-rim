import copy
import os

import pytest

import app as app_module
import menu
from tests.test_import_routes import Resp

BA = "http://ba.test"
BASE = "https://sugar.example"
DENIED = "Only bar admins and moderators can manage the holiday menu"
AI_DENIED = "Only bar admins and moderators can change AI settings"

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
        "images": [{"id": 77, "file_path": "cocktails/1/cider-sour_Ab12Cd.jpg"}],
        "ingredients": [
            # Shelf flags as BA's cocktail detail gives them.
            {
                "sort": 2,
                "amount": 22.5,
                "units": "ml",
                "ingredient": {"id": 102, "name": "Lemon Juice"},
                "in_bar_shelf": False,
            },
            {
                "sort": 1,
                "amount": 45,
                "units": "ml",
                "ingredient": {"id": 101, "name": "Bourbon"},
                "in_bar_shelf": False,
                "in_bar_shelf_as_variant": True,
                "variants_in_shelf": [{"id": 201, "name": "Buffalo Trace"}],
            },
            {
                "sort": 3,
                "amount": 1,
                "amount_max": 2,
                "units": "dashes",
                "ingredient": {"id": 103, "name": "Angostura"},
                "optional": True,
                "in_bar_shelf": True,
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
    for i in range(3, 15)
]
CATALOG = {c["id"]: c for c in COCKTAILS + EXTRA}


class FakeBA:
    """Bar Assistant with a cocktail catalog and a configurable user role."""

    def __init__(self):
        self.role = 1
        self.deleted = set()  # cocktail ids BA no longer returns
        self.uploads_down = False
        self.lookup_down = False
        self.images = {}  # cocktail id -> images after a save
        self.files = {}  # extra /uploads paths -> bytes
        self.put_status = 200
        self.detail_down = False
        self.strengths = {}  # ingredient id -> strength, for /ingredients
        self.ingredients_down = False
        self.ingredient_lookups = 0

    def request(self, method, url, **kw):
        if method == "GET":
            return self.get(url, **kw)
        assert method == "PUT" and url.startswith(f"{BA}/api/cocktails/"), url
        return Resp(self.put_status, json_data={"data": {}})

    def get(self, url, **kw):
        if url == f"{BA}/api/bars/1":
            if self.role is None:
                return Resp(500, json_data={})
            return Resp(json_data={"data": {"id": 1, "access": {"role_id": self.role}}})
        if url == f"{BA}/api/cocktails":
            if self.lookup_down:
                return Resp(500, json_data={})
            ids = [int(i) for i in kw["params"]["filter[id]"].split(",")]
            # BA returns them in its own order, not the one asked for.
            return Resp(
                json_data={
                    "data": [
                        c
                        for c in sorted(CATALOG.values(), key=lambda c: -c["id"])
                        if c["id"] in ids and c["id"] not in self.deleted
                    ]
                }
            )
        if url == f"{BA}/api/ingredients":
            self.ingredient_lookups += 1
            if isinstance(self.ingredients_down, Exception):
                raise self.ingredients_down
            if self.ingredients_down:
                return Resp(500, json_data={})
            ids = [int(i) for i in kw["params"]["filter[id]"].split(",")]
            return Resp(json_data={"data": [{"id": i, "strength": self.strengths.get(i, 0)}
                                            for i in ids]})
        if url.startswith(f"{BA}/api/cocktails/"):
            key = url.rsplit("/", 1)[-1]
            if isinstance(self.detail_down, Exception):
                raise self.detail_down
            if self.detail_down:
                return Resp(500, json_data={})
            for c in CATALOG.values():
                if key in (c["slug"], str(c["id"])) and c["id"] not in self.deleted:
                    images = self.images.get(c["id"], c["images"])
                    return Resp(json_data={"data": {**c, "images": images}})
            return Resp(404, json_data={})
        path = url.removeprefix(f"{BA}/uploads/")
        if path in self.files:
            r = Resp()
            r.content = self.files[path]
            return r
        if url == f"{BA}/uploads/cocktails/1/cider-sour_Ab12Cd.jpg":
            if self.uploads_down:
                return Resp(404)
            r = Resp()
            r.content = b"\xff\xd8full-size"
            return r
        if url == f"{BA}/api/images/77/thumb":
            r = Resp()
            r.content = b"\xff\xd8thumb"
            return r
        if url.startswith(f"{BA}/uploads/") or url.startswith(f"{BA}/api/images/"):
            return Resp(404)
        raise AssertionError(f"unexpected GET {url}")


@pytest.fixture
def ba(monkeypatch):
    fake = FakeBA()
    for verb in ("get", "request"):
        monkeypatch.setattr(app_module.http, verb, getattr(fake, verb))
    return fake


@pytest.fixture
def env(monkeypatch, tmp_path, ba):
    app_module.app.config["TESTING"] = True
    monkeypatch.setattr(app_module, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.setenv("BA_API_URL", BA)
    # setenv (not delenv) so teardown restores them: the app writes os.environ.
    monkeypatch.setenv("BA_BAR_ID", "1")
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


def put_list(env, ids, title="Thanksgiving 2026", subtitle="Fall favorites"):
    menu.save_list(
        menu.menu_dir(str(env / ".env")),
        {"title": title, "subtitle": subtitle, "cocktail_ids": ids},
    )


def publish(owner, env=None, ids=None):
    if ids is not None:
        put_list(env, ids)
    r = owner.post("/api/menu/publish", json={"public_base": BASE})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


@pytest.fixture
def listed(env):
    """A saved menu of drinks 1 and 2."""
    put_list(env, [1, 2])
    return env


def test_routes_need_login(guest):
    assert guest.get("/api/menu").status_code == 401
    assert guest.post("/api/menu/publish", json={}).status_code == 401
    assert guest.post("/api/menu/title", json={"title": "x"}).status_code == 401
    assert toggle(guest, 1, True).status_code == 401


ROUTES = [
    ("get", "/api/menu", None),
    ("post", "/api/menu/title", {"title": "x"}),
    ("post", "/api/menu/publish", {"public_base": BASE}),
    ("post", "/api/menu/cocktails", {"cocktail_id": 3, "on": True, "public_base": BASE}),
    ("post", "/api/menu/cocktails/set", {"cocktail_ids": [1], "public_base": BASE}),
    ("post", "/api/menu/suggest", {"occasion": "x"}),
    ("get", "/api/menu/ingredients", None),
]


@pytest.mark.parametrize("role", [3, 4, None])
@pytest.mark.parametrize("body", [{"api_url": "https://evil.test"}, {"api_token": "t"},
                                  {"bar_id": 2}])
def test_other_roles_cannot_change_the_connection(owner, ba, env, role, body):
    ba.role = role
    r = owner.post("/config", json=body)
    assert r.status_code == 403
    assert r.get_json()["error"] == app_module.CONN_DENIED
    assert os.getenv("BA_API_URL") == BA and os.getenv("BA_BAR_ID") == "1"
    assert not (env / ".env").exists()


@pytest.mark.parametrize("role", [1, 2])
def test_admins_and_moderators_change_the_connection(owner, ba, env, role):
    ba.role = role
    assert owner.post("/config", json={"bar_id": 2}).status_code == 200
    assert os.getenv("BA_BAR_ID") == "2"


def test_first_bar_pick_is_open_while_none_is_set(owner, ba, env, monkeypatch):
    ba.role = 4
    monkeypatch.setenv("BA_BAR_ID", "")
    assert owner.post("/config", json={"bar_id": 1}).status_code == 200
    assert os.getenv("BA_BAR_ID") == "1"


@pytest.mark.parametrize("role", [3, 4, None])
def test_other_roles_are_refused_and_nothing_is_written(owner, ba, env, role):
    ba.role = role
    for verb, path, body in ROUTES:
        r = getattr(owner, verb)(path, **({"json": body} if body else {}))
        assert r.status_code == 403, path
        assert r.get_json()["error"] == DENIED
    assert not (env / "menu").exists()
    r = owner.post("/config", json={"menu_page_seconds": "9"})
    assert r.status_code == 403 and r.get_json()["error"] == DENIED
    for key in app_module.AI_FIELDS:
        r = owner.post("/config", json={key: "9"})
        assert r.status_code == 403, key
        assert r.get_json()["error"] == AI_DENIED
    assert app_module.os.getenv("MENU_PAGE_SECONDS") != "9"
    assert not (env / ".env").exists() or "9" not in (env / ".env").read_text()
    r = owner.get("/api/ai/settings")
    assert r.status_code == 403 and r.get_json()["error"] == AI_DENIED
    r = owner.post("/api/ai/models", json={"provider": "compatible", "base_url": "http://x/v1"})
    assert r.status_code == 403 and r.get_json()["error"] == AI_DENIED


def test_moderator_manages_the_menu(owner, ba, listed):
    ba.role = 2
    assert owner.get("/api/menu").status_code == 200
    assert owner.post("/api/menu/title", json={"title": "Winter"}).status_code == 200
    assert toggle(owner, 3, True).get_json()["published"]["count"] == 3
    assert owner.post("/api/menu/publish", json={"public_base": BASE}).status_code == 200
    assert owner.post("/config", json={"menu_page_seconds": 9}).status_code == 200


def test_role_is_checked_on_every_request(owner, ba, listed):
    assert owner.get("/api/menu").status_code == 200
    ba.role = 3
    assert owner.get("/api/menu").status_code == 403


def test_no_bar_selected_is_not_permitted(owner, monkeypatch):
    monkeypatch.setenv("BA_BAR_ID", "")
    r = owner.get("/api/menu")
    assert r.status_code == 400 and "No bar selected" in r.get_json()["error"]


def test_ai_settings_never_return_a_key(owner, ba, monkeypatch):
    for k, v in {"AI_IMAGE_PROVIDER": "openai", "AI_IMAGE_MODEL": "m",
                 "AI_IMAGE_BASE_URL": "", "AI_IMAGE_API_KEY": "sk-secret",
                 "AI_PROMPT_INGREDIENT": "pi", "AI_PROMPT_COCKTAIL": "pc",
                 "TYPESAFE_API_KEY": "ts-secret", "TYPESAFE_ENABLED": "1",
                 "MENU_SUGGEST_MODEL": "chat"}.items():
        monkeypatch.setenv(k, v)
    ba.role = 2
    r = owner.get("/api/ai/settings")
    assert r.status_code == 200
    assert "sk-secret" not in r.get_data(as_text=True)
    assert "ts-secret" not in r.get_data(as_text=True)
    assert r.get_json() == {
        "ai_provider": "openai", "ai_model": "m", "ai_base_url": "", "ai_key_set": True,
        "ai_prompt_ingredient": "pi", "ai_prompt_cocktail": "pc",
        "typesafe_key_set": True, "typesafe_enabled": True, "menu_suggest_model": "chat",
        "engine": "TypeSafe Jev",
    }


def test_ai_settings_show_no_engine(owner, ba, monkeypatch):
    for k in ("AI_IMAGE_PROVIDER", "AI_IMAGE_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.setenv(k, "")
    cfg = owner.get("/api/ai/settings").get_json()
    assert cfg["engine"] is None and cfg["ai_key_set"] is False
    assert cfg["typesafe_key_set"] is False


def test_ai_settings_need_login(guest):
    assert guest.get("/api/ai/settings").status_code == 401


def test_admin_saves_ai_settings(owner, ba, env, monkeypatch):
    for k in ("AI_IMAGE_PROVIDER", "AI_IMAGE_API_KEY", "MENU_SUGGEST_MODEL"):
        monkeypatch.setenv(k, "")  # so teardown restores what the app writes
    r = owner.post("/config", json={"ai_provider": "openai", "ai_api_key": "k",
                                    "menu_suggest_model": "chat"})
    assert r.status_code == 200
    assert app_module.os.environ["MENU_SUGGEST_MODEL"] == "chat"


def test_typesafe_switch_saves_and_keeps_the_key(owner, ba, env, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-old")
    monkeypatch.setenv("TYPESAFE_ENABLED", "1")
    assert owner.post("/config", json={"typesafe_enabled": False}).status_code == 200
    cfg = owner.get("/api/ai/settings").get_json()
    assert cfg["typesafe_enabled"] is False and cfg["typesafe_key_set"] is True
    assert cfg["engine"] != "TypeSafe Jev"
    assert owner.post("/config", json={"typesafe_enabled": True}).status_code == 200
    assert owner.get("/api/ai/settings").get_json()["engine"] == "TypeSafe Jev"


def test_one_save_keeps_saved_keys(owner, ba, env, monkeypatch):
    # The exact body App.ai.save() sends with both key fields left blank.
    monkeypatch.setenv("AI_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("AI_IMAGE_API_KEY", "sk-old")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-old")
    for k in ("AI_IMAGE_MODEL", "AI_IMAGE_BASE_URL", "MENU_SUGGEST_MODEL",
              "AI_PROMPT_INGREDIENT", "AI_PROMPT_COCKTAIL"):
        monkeypatch.setenv(k, "x")
    r = owner.post("/config", json={
        "ai_provider": "openai", "ai_model": "m", "ai_base_url": "", "ai_api_key": "",
        "menu_suggest_model": "chat", "ai_prompt_ingredient": "", "ai_prompt_cocktail": "",
    })
    assert r.status_code == 200
    cfg = owner.get("/api/ai/settings").get_json()
    assert cfg["ai_key_set"] is True and cfg["typesafe_key_set"] is True
    assert cfg["ai_model"] == "m" and cfg["menu_suggest_model"] == "chat"
    assert cfg["ai_prompt_ingredient"] == "" and cfg["ai_prompt_cocktail"] == ""


def test_publish_snapshots_the_list_in_order(owner, env, ba):
    put_list(env, [3, 1, 2])  # BA hands them back newest-first; the list wins
    state = publish(owner)
    assert state["published"]["title"] == "Thanksgiving 2026"
    assert state["published"]["count"] == 3
    assert state["url"] == f"{BASE}/menu"
    snap = menu.load(menu.menu_dir(str(env / ".env")))
    assert [c["name"] for c in snap["cocktails"]] == [
        "Drink 3",
        "Cider Sour",
        "Maple Old Fashioned",
    ]
    assert snap["subtitle"] == "Fall favorites" and "collection_id" not in snap
    cider = snap["cocktails"][1]
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
    assert snap["cocktails"][2]["image"] is None


def test_publish_rejects_bad_input(owner, env):
    put_list(env, [1, 2])
    r = owner.post("/api/menu/publish", json={"public_base": "javascript:alert(1)"})
    assert r.status_code == 400
    put_list(env, [])
    r = owner.post("/api/menu/publish", json={"public_base": BASE})
    assert r.status_code == 400
    put_list(env, list(CATALOG))
    r = owner.post("/api/menu/publish", json={"public_base": BASE})
    assert r.status_code == 400 and "at most" in r.get_json()["error"]


def test_republish_drops_unused_photos(owner, env):
    publish(owner, env, [1, 2])
    publish(owner, env, [2])
    assert not (env / "menu" / "cider-sour.jpg").exists()
    assert (env / "menu" / "list.json").exists()


def test_public_pages_need_no_login_and_ignore_old_keys(owner, guest, listed):
    publish(owner)
    for path in ("/menu", "/menu/r/cider-sour", "/menu/img/cider-sour"):
        assert guest.get(path).status_code == 200
        assert guest.get(path + "?key=from-an-old-link").status_code == 200


def test_board_shows_menu_with_qr_to_recipe(owner, guest, listed):
    publish(owner)
    r = guest.get("/menu")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Thanksgiving 2026" in html and "Maple Old Fashioned" in html
    # The first sentence of the description, and the main ingredients
    # (spirits first, optional ones left out).
    assert "Bright and appley." in html
    assert "Bourbon · Lemon Juice</p>" in html and "Angostura" not in html
    assert "18% ABV" in html and "Coupe" in html
    assert "<svg" in html and "key=" not in html
    assert "data-menu-board" in html  # what the TV's reload check looks for
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["Cache-Control"] == "no-store"
    assert "--inset: 5" in html
    assert "--inset: 15" in guest.get("/menu?inset=99").get_data(as_text=True)


def test_recipe_and_image_only_for_menu_cocktails(owner, guest, listed):
    publish(owner)
    r = guest.get("/menu/r/cider-sour")
    assert r.status_code == 200 and "Apple fan" in r.get_data(as_text=True)
    assert guest.get("/menu/r/not-on-menu").status_code == 404
    img = guest.get("/menu/img/cider-sour")
    assert img.status_code == 200 and img.data == b"\xff\xd8full-size"
    assert guest.get("/menu/img/maple-old-fashioned").status_code == 404
    assert guest.get("/menu/img/..%2F.env").status_code == 404


def test_fresh_install_is_an_empty_menu_called_menu(owner, guest):
    state = owner.get("/api/menu").get_json()
    assert state["published"] is None and state["url"] is None
    assert state["menu"] == {
        "title": "Menu",
        "subtitle": "",
        "theme": "classic",
        "drinks": [],
        "cocktail_ids": [],
    }
    r = guest.get("/menu")
    assert r.status_code == 200 and "No menu has been published" in r.get_data(
        as_text=True
    )


def test_first_run_seeds_the_list_from_the_snapshot(owner, env):
    snapshot = {
        "title": "Thanksgiving Cocktails",
        "subtitle": "Fall",
        "public_base": BASE,
        "cocktails": [
            {"slug": "maple-old-fashioned"},
            {"slug": "gone-from-ba"},
            {"slug": "cider-sour"},
        ],
    }
    directory = menu.menu_dir(str(env / ".env"))
    app_module.os.makedirs(directory)
    menu.save(directory, snapshot)
    state = owner.get("/api/menu").get_json()
    assert state["menu"]["title"] == "Thanksgiving Cocktails"
    assert state["menu"]["subtitle"] == "Fall"
    assert state["menu"]["cocktail_ids"] == [2, 1]
    assert menu.load_list(directory)["cocktail_ids"] == [2, 1]


def toggle(owner, cocktail_id, on):
    return owner.post(
        "/api/menu/cocktails",
        json={"cocktail_id": cocktail_id, "on": on, "public_base": BASE},
    )


def test_state_lists_the_drinks_in_list_order(owner, env):
    put_list(env, [2, 1])
    assert owner.get("/api/menu").get_json()["menu"] == {
        "title": "Thanksgiving 2026",
        "subtitle": "Fall favorites",
        "drinks": [
            {"id": 2, "name": "Maple Old Fashioned"},
            {"id": 1, "name": "Cider Sour"},
        ],
        "theme": "classic",
        "cocktail_ids": [2, 1],
    }


def test_a_failed_lookup_is_an_error_not_an_empty_menu(owner, ba, listed):
    ba.lookup_down = True
    assert owner.get("/api/menu").status_code == 502
    assert toggle(owner, 3, True).status_code == 502
    assert menu.load_list(menu.menu_dir(str(listed / ".env")))["cocktail_ids"] == [1, 2]


def test_title_route_renames_without_publishing(owner, listed):
    r = owner.post("/api/menu/title", json={"title": " Christmas ", "subtitle": " Merry "})
    assert r.status_code == 200
    assert r.get_json()["menu"]["title"] == "Christmas"
    assert r.get_json()["menu"]["subtitle"] == "Merry"
    assert r.get_json()["menu"]["cocktail_ids"] == [1, 2]
    assert r.get_json()["published"] is None
    assert owner.post("/api/menu/title", json={"title": " "}).status_code == 400


def test_toggle_adds_and_removes_then_republishes(owner, env):
    put_list(env, [1, 2])
    r = toggle(owner, 3, True)
    assert r.status_code == 200
    assert r.get_json()["published"]["count"] == 3
    assert r.get_json()["menu"]["cocktail_ids"] == [1, 2, 3]
    toggle(owner, 3, True)  # already on: no duplicate
    list_path = menu.menu_dir(str(env / ".env"))
    assert menu.load_list(list_path)["cocktail_ids"] == [1, 2, 3]
    r = toggle(owner, 1, False)
    assert r.get_json()["published"]["count"] == 2
    names = [c["name"] for c in menu.load(list_path)["cocktails"]]
    assert names == ["Maple Old Fashioned", "Drink 3"]


def test_toggle_on_a_fresh_install_starts_the_menu(owner, env):
    r = toggle(owner, 1, True)
    assert r.status_code == 200 and r.get_json()["menu"]["title"] == "Menu"
    assert r.get_json()["published"]["count"] == 1


def test_a_cocktail_deleted_in_ba_is_hidden_and_dropped_on_save(owner, ba, env):
    put_list(env, [1, 2, 3])
    ba.deleted = {2}
    assert owner.get("/api/menu").get_json()["menu"]["cocktail_ids"] == [1, 3]
    toggle(owner, 4, True)
    directory = menu.menu_dir(str(env / ".env"))
    assert menu.load_list(directory)["cocktail_ids"] == [1, 3, 4]


def test_saving_the_title_drops_cocktails_deleted_in_ba(owner, ba, env):
    put_list(env, [1, 2, 3])
    ba.deleted = {2}
    assert owner.post("/api/menu/title", json={"title": "X"}).status_code == 200
    directory = menu.menu_dir(str(env / ".env"))
    assert menu.load_list(directory)["cocktail_ids"] == [1, 3]


def test_toggle_refuses_a_thirteenth_drink(owner, env):
    put_list(env, list(range(1, 13)))
    r = toggle(owner, 13, True)
    assert r.status_code == 400 and "already has 12" in r.get_json()["error"]
    assert len(menu.load_list(menu.menu_dir(str(env / ".env")))["cocktail_ids"]) == 12


def test_set_cocktails_replaces_the_list(owner, listed):
    r = owner.post(
        "/api/menu/cocktails/set",
        json={"cocktail_ids": [4, 3, 4], "public_base": BASE},
    )
    assert r.status_code == 200 and r.get_json()["menu"]["cocktail_ids"] == [4, 3]
    assert r.get_json()["published"]["count"] == 2


def test_publish_falls_back_to_the_thumbnail(owner, guest, ba, listed):
    ba.uploads_down = True
    publish(owner)
    assert guest.get("/menu/img/cider-sour").data == b"\xff\xd8thumb"


def test_a_long_menu_pages_and_shows_the_speed_setting(owner, guest, env):
    put_list(env, list(range(1, 9)))
    state = publish(owner)
    assert state["per_page"] == 6 and state["max_drinks"] == 12
    html = guest.get("/menu").get_data(as_text=True)
    assert html.count('<section class="page n4') == 2  # 8 drinks: 4 + 4
    assert html.count("<b class=") == 4  # two dots in each screen's badge


def test_emptying_the_menu_keeps_the_last_board(owner, env):
    put_list(env, [1])
    publish(owner)
    r = toggle(owner, 1, False)
    assert r.status_code == 200 and r.get_json()["menu"]["cocktail_ids"] == []
    assert "still shows" in r.get_json()["publish_error"]
    assert r.get_json()["published"]["count"] == 1


def test_tagline_is_the_first_sentence_of_the_description():
    assert menu.tagline({"description": "America&#039;s best. Since 1862."}) == (
        "America's best."
    )
    assert menu.tagline({"description": ""}) == ""
    assert menu.tagline({}) == ""


def test_key_ingredients_put_spirits_first_and_skip_staples():
    def i(name, strength=0, optional=False):
        return {"name": name, "strength": strength, "optional": optional}

    c = {
        "ingredients": [
            i("Water"),
            i("Cranberries"),
            i("Orange juice"),
            i("Sugar"),
            i("Bourbon Whiskey", 40),
            i("Apple"),
            i("Apple"),
            i("Bitters", 45, optional=True),
        ],
    }
    assert menu.key_ingredients(c) == ["Bourbon Whiskey", "Cranberries", "Orange juice"]
    assert menu.key_ingredients({"ingredients": [i("Apple"), i("apple")]}) == ["Apple"]
    assert menu.key_ingredients({"ingredients": []}) == []


def test_board_pages_split_evenly_with_a_tile_each():
    def sizes(n):
        return [len(p) for p in menu.board_pages([{"n": k} for k in range(n)])]

    assert sizes(0) == []
    assert sizes(1) == [1] and sizes(6) == [6]
    assert sizes(7) == [4, 3] and sizes(12) == [6, 6]
    for n in range(1, menu.PER_PAGE + 1):
        tiles = [c["tile"] for c in menu.board_pages([{}] * n)[0]]
        assert len(tiles) == n and all(
            t["h"] in "lcr" and t["v"] in "tb" for t in tiles
        )


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


def test_page_seconds_setting_reaches_the_board(owner, guest, monkeypatch, listed):
    monkeypatch.setenv("MENU_PAGE_SECONDS", "")
    publish(owner)
    assert "PAGE_SECONDS = 15;" in guest.get("/menu").get_data(as_text=True)
    assert owner.post("/config", json={"menu_page_seconds": 8}).status_code == 200
    assert owner.get("/api/menu").get_json()["page_seconds"] == 8
    assert "PAGE_SECONDS = 8;" in guest.get("/menu").get_data(as_text=True)
    assert "PAGE_SECONDS = 30;" in guest.get("/menu?seconds=30").get_data(as_text=True)
    owner.post("/config", json={"menu_page_seconds": 1})  # clamped
    assert owner.get("/api/menu").get_json()["page_seconds"] == 3
    guest_cfg = app_module.app.test_client().post(
        "/config", json={"menu_page_seconds": 9}
    )
    assert guest_cfg.status_code == 401


def test_qr_codes_use_short_links_to_each_recipe(owner, guest, listed):
    publish(owner)
    html = guest.get("/menu").get_data(as_text=True)
    assert "/m/1" not in html  # the link is encoded in the code, not printed
    r = guest.get("/m/1")
    assert r.status_code == 302 and r.headers["Location"].endswith("/menu/r/cider-sour")
    assert guest.get("/m/2").headers["Location"].endswith("/menu/r/maple-old-fashioned")
    assert guest.get("/m/3").status_code == 404
    assert guest.get("/m/0").status_code == 404


# ── Themes ──


def set_theme(owner, theme):
    return owner.post("/api/menu/title", json={"title": "T", "theme": theme})


def test_theme_is_saved_with_the_title_and_listed_for_the_dropdown(owner, listed):
    r = set_theme(owner, "halloween")
    assert r.status_code == 200
    state = r.get_json()
    assert state["menu"]["theme"] == "halloween"
    assert len(state["themes"]) == 21
    assert {t["group"] for t in state["themes"]} == {"holiday", "generic"}
    assert menu.load_list(menu.menu_dir(str(listed / ".env")))["theme"] == "halloween"


def test_unknown_theme_is_refused_and_nothing_saved(owner, listed):
    assert set_theme(owner, "nope").status_code == 400
    assert set_theme(owner, ["x"]).status_code == 400
    assert owner.get("/api/menu").get_json()["menu"]["theme"] == "classic"


def test_title_without_a_theme_keeps_the_existing_one(owner, listed):
    set_theme(owner, "christmas")
    r = owner.post("/api/menu/title", json={"title": "Again"})
    assert r.get_json()["menu"]["theme"] == "christmas"


def test_theme_reaches_the_board_only_on_publish(owner, guest, listed):
    publish(owner)
    set_theme(owner, "halloween")
    assert "Trick or treat" not in guest.get("/menu").get_data(as_text=True)
    owner.post("/api/menu/publish", json={"public_base": BASE})
    html = guest.get("/menu").get_data(as_text=True)
    assert "Trick or treat" in html and 'class="emblem"' in html and "Creepster" in html


def test_classic_and_old_snapshots_render_as_before(owner, guest, listed):
    publish(owner)
    html = guest.get("/menu").get_data(as_text=True)
    assert "The bar is open" in html and "#c9a24a" in html and "Fraunces" in html
    assert 'class="emblem"' not in html and 'class="halo"' not in html
    directory = menu.menu_dir(str(listed / ".env"))
    snap = menu.load(directory)
    snap.pop("theme", None)
    menu.save(directory, snap)
    assert "The bar is open" in guest.get("/menu").get_data(as_text=True)
    snap["theme"] = "removed-theme"
    menu.save(directory, snap)
    assert guest.get("/menu").status_code == 200


def test_striped_themes_stripe_the_lines(owner, guest, listed):
    set_theme(owner, "christmas")
    publish(owner)
    html = guest.get("/menu").get_data(as_text=True)
    assert "repeating-linear-gradient(45deg, #c0262d 0vh 1.6vh, #f5efe6 1.6vh 3.2vh)" in html
    assert "--gold: #c0262d" in html
    assert "Merry and bright" in html and "Playfair+Display" in html


def test_every_theme_renders_and_its_motifs_exist(owner, guest, listed):
    publish(owner)
    directory = menu.menu_dir(str(listed / ".env"))
    snap = menu.load(directory)
    for tid, t in menu.THEMES.items():
        assert not t["motif"] or t["motif"] in menu.MOTIFS
        assert not t["halo"] or t["halo"] in menu.MOTIFS
        menu.save(directory, {**snap, "theme": tid})
        assert guest.get("/menu").status_code == 200, tid
        assert guest.get("/menu/r/cider-sour").status_code == 200, tid


def test_recipe_page_takes_the_theme_but_classic_is_unchanged(owner, guest, listed):
    set_theme(owner, "halloween")
    publish(owner)
    html = guest.get("/menu/r/cider-sour").get_data(as_text=True)
    assert "Creepster" in html and "--bg: #0c0412" in html and "<svg" in html
    set_theme(owner, "classic")
    owner.post("/api/menu/publish", json={"public_base": BASE})
    html = guest.get("/menu/r/cider-sour").get_data(as_text=True)
    assert "--bg: #0a0b1e" in html and "--accent: #ff2e63" in html and "<svg" not in html


# ── Photo refresh on cocktail save ────────────────────────────────────────────

NEW_IMG = {"id": 88, "file_path": "cocktails/2/maple_New.jpg"}


def save_cocktail(owner, cid, **body):
    return owner.put(f"/api/cocktails/{cid}", json={"name": "x", **body})


def snap_of(env):
    return menu.load(menu.menu_dir(str(env / ".env")))


def test_a_photo_added_after_publishing_reaches_the_board(owner, guest, ba, listed):
    publish(owner)
    board = guest.get("/menu").get_data(as_text=True)
    assert "/menu/img/maple-old-fashioned" not in board
    ba.images[2] = [NEW_IMG]
    ba.files[NEW_IMG["file_path"]] = b"\xff\xd8maple"
    assert save_cocktail(owner, 2).status_code == 200
    html = guest.get("/menu").get_data(as_text=True)
    v = menu.image_version(b"\xff\xd8maple")
    assert f'src="/menu/img/maple-old-fashioned?v={v}"' in html
    assert guest.get("/menu/img/maple-old-fashioned").data == b"\xff\xd8maple"
    page = guest.get("/menu/r/maple-old-fashioned").get_data(as_text=True)
    assert f"/menu/img/maple-old-fashioned?v={v}" in page
    assert "id" not in snap_of(listed)["cocktails"][1]


def test_a_replaced_photo_gets_a_new_version(owner, guest, ba, listed):
    publish(owner)
    old_v = snap_of(listed)["cocktails"][0]["image_v"]
    board = guest.get("/menu").get_data(as_text=True)
    assert f"/menu/img/cider-sour?v={old_v}" in board
    ba.images[1] = [NEW_IMG]
    ba.files[NEW_IMG["file_path"]] = b"\xff\xd8regenerated"
    save_cocktail(owner, 1)
    new_v = snap_of(listed)["cocktails"][0]["image_v"]
    assert new_v != old_v
    board = guest.get("/menu").get_data(as_text=True)
    assert f"/menu/img/cider-sour?v={new_v}" in board
    assert guest.get("/menu/img/cider-sour").data == b"\xff\xd8regenerated"


def test_a_regenerated_photo_wins_over_the_old_one_still_attached(
    owner, guest, ba, listed
):
    publish(owner)
    # BA keeps the old image (same sort) until the SPA deletes it after the PUT.
    ba.images[1] = [COCKTAILS[0]["images"][0], NEW_IMG]
    ba.files[NEW_IMG["file_path"]] = b"\xff\xd8regenerated"
    save_cocktail(owner, 1, images=[NEW_IMG["id"]])
    assert guest.get("/menu/img/cider-sour").data == b"\xff\xd8regenerated"


def test_a_removed_photo_shows_the_initial(owner, guest, ba, listed):
    publish(owner)
    ba.images[1] = []
    save_cocktail(owner, 1)
    entry = snap_of(listed)["cocktails"][0]
    assert entry["image"] is None and "image_v" not in entry
    assert not (listed / "menu" / "cider-sour.jpg").exists()
    assert guest.get("/menu/img/cider-sour").status_code == 404
    assert '<div class="initial">C</div>' in guest.get("/menu").get_data(as_text=True)


def test_saving_a_cocktail_off_the_menu_leaves_the_snapshot(owner, ba, listed):
    publish(owner)
    path = listed / "menu" / "menu.json"
    before = path.read_bytes()
    ba.images[3] = [NEW_IMG]
    ba.files[NEW_IMG["file_path"]] = b"\xff\xd8other"
    assert save_cocktail(owner, 3).status_code == 200
    assert path.read_bytes() == before


def test_saving_before_any_publish_writes_nothing(owner, ba, env):
    ba.images[1] = [NEW_IMG]
    assert save_cocktail(owner, 1).status_code == 200
    assert not (env / "menu").exists()


def test_a_failed_save_does_not_refresh(owner, ba, listed):
    publish(owner)
    before = (listed / "menu" / "menu.json").read_bytes()
    ba.put_status = 422
    ba.images[1] = []
    assert save_cocktail(owner, 1).status_code == 422
    assert (listed / "menu" / "menu.json").read_bytes() == before


@pytest.mark.parametrize("failure", ["detail", "unreachable", "download", "disk"])
def test_a_failed_refresh_keeps_the_old_photo(
    owner, guest, ba, listed, failure, monkeypatch
):
    publish(owner)
    before = (listed / "menu" / "menu.json").read_bytes()
    if failure == "detail":
        ba.detail_down = True
    elif failure == "unreachable":
        ba.detail_down = app_module.http.exceptions.ConnectionError("down")
    elif failure == "download":
        ba.images[1] = [NEW_IMG]  # neither the original nor a thumbnail downloads
    else:

        def full_disk(*a):
            raise OSError("disk full")

        monkeypatch.setattr(menu, "save", full_disk)
    r = save_cocktail(owner, 1)
    assert r.status_code == 200 and r.get_json() == {"data": {}}
    assert (listed / "menu" / "menu.json").read_bytes() == before
    assert guest.get("/menu/img/cider-sour").data == b"\xff\xd8full-size"


def test_a_save_changes_only_the_photo_not_unpublished_edits(owner, guest, ba, listed):
    publish(owner)
    published_at = snap_of(listed)["published_at"]
    put_list(listed, [2, 1])
    set_theme(owner, "halloween")  # also retitles the list "T"
    ba.images[2] = [NEW_IMG]
    ba.files[NEW_IMG["file_path"]] = b"\xff\xd8maple"
    save_cocktail(owner, 2)
    snap = snap_of(listed)
    assert snap["published_at"] == published_at and snap["title"] == "Thanksgiving 2026"
    slugs = [c["slug"] for c in snap["cocktails"]]
    assert slugs == ["cider-sour", "maple-old-fashioned"]
    html = guest.get("/menu").get_data(as_text=True)
    assert "Trick or treat" not in html and "Thanksgiving 2026" in html
    assert "/menu/img/maple-old-fashioned?v=" in html


def test_old_snapshots_without_a_version_render_as_before(owner, guest, listed):
    publish(owner)
    directory = menu.menu_dir(str(listed / ".env"))
    snap = menu.load(directory)
    snap["cocktails"][0].pop("image_v")
    menu.save(directory, snap)
    assert 'src="/menu/img/cider-sour"' in guest.get("/menu").get_data(as_text=True)


# ── Ingredient checklist ──────────────────────────────────────────────────────


def line(iid, name, optional=False, **flags):
    return {"ingredient": {"id": iid, "name": name}, "optional": optional, **flags}


def drink(name, *lines):
    return {"name": name, "ingredients": list(lines)}


def amt(line_, amount, units, amount_max=None):
    return {**line_, "amount": amount, "amount_max": amount_max, "units": units}


def test_checklist_has_one_row_per_ingredient_with_each_drinks_amount():
    rows = menu.ingredient_checklist(
        [
            drink("Cider Sour", amt(line(1, "Lemon Juice", in_bar_shelf=True), 22.5, "ml")),
            drink("Whiskey Sour", amt(line(1, "Lemon Juice", in_bar_shelf=True), 1, "oz")),
        ]
    )
    assert rows == [
        {
            "id": 1,
            "name": "Lemon Juice",
            "drinks": ["Cider Sour", "Whiskey Sour"],
            "uses": [
                {"drink": "Cider Sour", "amount": 22.5, "amount_max": None,
                 "units": "ml", "optional": False, "batch": False},
                {"drink": "Whiskey Sour", "amount": 1, "amount_max": None,
                 "units": "oz", "optional": False, "batch": False},
            ],
            "optional": False,
            "status": "on_shelf",
            "via": "",
        }
    ]


def test_checklist_keeps_ranges_and_missing_amounts_as_the_recipe_gives_them():
    rows = menu.ingredient_checklist(
        [
            drink(
                "A",
                amt(line(1, "Angostura"), 1, " dashes ", amount_max=2),
                line(2, "Mint"),
            )
        ]
    )
    uses = {r["name"]: r["uses"][0] for r in rows}
    assert (uses["Angostura"]["amount"], uses["Angostura"]["amount_max"]) == (1, 2)
    assert uses["Angostura"]["units"] == "dashes"
    assert uses["Mint"]["amount"] is None and uses["Mint"]["units"] == ""


# Real recipes from the bar (BA v5.15.4).
PUNCH = drink(
    "Spiced Cranberry-Orange Punch",
    *[
        amt(line(i, name), n, units)
        for i, (n, units, name) in enumerate(
            [
                (7, "oz", "Water"),
                (1, "cup", "Sugar"),
                (1, "piece", "Ginger"),
                (1, "sprigs", "Rosemary"),
                (1, "stick", "Cinnamon"),
                (2, "whole", "Star Anise"),
                (12, "oz", "Cranberries"),
                (68, "oz", "Club Soda"),
                (12, "oz", "Cranberry Juice"),
                (12, "oz", "Orange Juice"),
            ],
            1,
        )
    ],
)
PUNCH["tags"] = [{"name": "Punch"}]
SANGRIA = drink(
    "Sangria",
    amt(line(20, "Red Wine"), 1, "bottle"),
    amt(line(21, "Orange"), 1, "whole"),
)
HIGHBALL = drink(
    "Highball",
    amt(line(30, "Whisky"), 60, "ml"),
    amt(line(31, "Club Soda"), 210, "ml"),
    amt(line(32, "Bitters"), 2, "dashes"),
)


def test_batch_drinks_are_told_apart_from_single_ones():
    assert menu.is_batch(PUNCH)
    assert menu.is_batch({**PUNCH, "tags": []})  # by volume too: about 3.6 l
    assert not menu.is_batch(HIGHBALL)  # about 270 ml
    assert menu.is_batch(drink("Nog", amt(line(1, "Milk"), 1000, "ml")))
    assert menu.is_batch(drink("Jug", amt(line(1, "Lemonade"), 1, "Pitcher")))
    assert menu.is_batch(drink("Tub", amt(line(1, "Cider"), 1, "quart")))
    assert not menu.is_batch(drink("Odd", amt(line(1, "Rum"), "a splash", "oz")))
    assert not menu.is_batch(drink("Empty"))


def test_a_bottle_or_ice_alone_doesnt_make_a_batch():
    michelada = drink(
        "Michelada",
        amt(line(1, "Beer"), 1, "bottle"),
        amt(line(2, "Lime Juice"), 15, "ml"),
    )
    mai_tai = drink(
        "Disgruntled Mai Tai",
        amt(line(3, "Underberg"), 1, "bottle"),
        amt(line(4, "Orgeat"), 0.5, "oz"),
    )
    tiki = drink(
        "Spindrift",
        amt(line(5, "Crushed ice"), 600, "ml"),
        amt(line(6, "Rum"), 2, "fl oz"),
    )
    small = drink("Small", amt(line(7, "Wine"), 0.2, "liter"))
    for d in (michelada, mai_tai, tiki, small, SANGRIA):
        assert not menu.is_batch(d), d["name"]


def test_a_batch_or_punch_tag_makes_a_batch():
    assert menu.is_batch({**SANGRIA, "tags": [{"name": "Punch"}]})
    assert menu.is_batch({**HIGHBALL, "tags": [{"name": "Party batch"}]})
    assert not menu.is_batch({**HIGHBALL, "tags": [{"name": "Highball"}]})


def test_checklist_lines_say_per_drink_or_per_batch():
    rows = menu.ingredient_checklist([PUNCH, SANGRIA, HIGHBALL])
    soda = next(r for r in rows if r["name"] == "Club Soda" and r["id"] == 8)
    assert [(u["drink"], u["amount"], u["units"], u["batch"]) for u in soda["uses"]] == [
        ("Spiced Cranberry-Orange Punch", 68, "oz", True)
    ]
    by_drink = {u["drink"]: u["batch"] for r in rows for u in r["uses"]}
    assert by_drink == {
        "Spiced Cranberry-Orange Punch": True,
        "Sangria": False,
        "Highball": False,
    }


def test_checklist_decodes_entities_in_drink_names():
    rows = menu.ingredient_checklist([drink("America&#039;s Punch", line(1, "Rum"))])
    assert rows[0]["drinks"] == ["America's Punch"]
    assert rows[0]["uses"][0]["drink"] == "America's Punch"


def test_checklist_via_falls_back_when_ba_names_nothing():
    rows = menu.ingredient_checklist(
        [
            drink(
                "A",
                line(1, "Bourbon", in_bar_shelf_as_variant=True, variants_in_shelf=[]),
                line(
                    2,
                    "Rye",
                    in_bar_shelf_as_substitute=True,
                    substitutes=[{"ingredient": {"name": "Scotch"}, "in_bar_shelf": False}],
                ),
            )
        ]
    )
    assert {r["name"]: (r["status"], r["via"]) for r in rows} == {
        "Bourbon": ("probably", "you have a variant"),
        "Rye": ("probably", "a substitute"),
    }


def test_checklist_joins_different_reasons_once_each():
    complex_ = {"in_bar_shelf_as_complex_ingredient": True}
    variant = {
        "in_bar_shelf_as_variant": True,
        "variants_in_shelf": [{"name": "Buffalo Trace"}],
    }
    rows = menu.ingredient_checklist(
        [
            drink("A", line(1, "Bourbon", **variant)),
            drink("B", line(1, "Bourbon", **complex_)),
            drink("C", line(1, "Bourbon", **variant)),
        ]
    )
    assert rows[0]["via"] == (
        "you have Buffalo Trace; can be made from what's on the shelf"
    )


def test_checklist_status_follows_ba_shelf_matching():
    variant = line(
        1,
        "Bourbon",
        in_bar_shelf_as_variant=True,
        variants_in_shelf=[{"name": "Buffalo Trace"}],
    )
    substitute = line(
        2,
        "Bourbon Whiskey",
        in_bar_shelf_as_substitute=True,
        substitutes=[
            {"ingredient": {"name": "Rye"}, "in_bar_shelf": True},
            {"ingredient": {"name": "Scotch"}, "in_bar_shelf": False},
        ],
    )
    complex_ = line(3, "Honey Syrup", in_bar_shelf_as_complex_ingredient=True)
    missing = line(4, "Cranberries", in_bar_shelf_as_substitute=False)
    on = line(5, "Angostura", in_bar_shelf=True)
    rows = menu.ingredient_checklist(
        [drink("A", variant, substitute, complex_, missing, on)]
    )
    by = {r["name"]: (r["status"], r["via"]) for r in rows}
    assert by == {
        "Bourbon": ("probably", "you have Buffalo Trace"),
        "Bourbon Whiskey": ("probably", "substitute: Rye"),
        "Honey Syrup": ("probably", "can be made from what's on the shelf"),
        "Cranberries": ("missing", ""),
        "Angostura": ("on_shelf", ""),
    }


def test_checklist_takes_the_worst_line():
    rows = menu.ingredient_checklist(
        [
            drink(
                "A",
                line(
                    1,
                    "Rye",
                    in_bar_shelf_as_substitute=True,
                    substitutes=[
                        {"ingredient": {"name": "Bourbon"}, "in_bar_shelf": True}
                    ],
                ),
            ),
            drink("B", line(1, "Rye")),
            drink("C", line(2, "Gin", in_bar_shelf=True)),
            drink(
                "D",
                line(
                    2,
                    "Gin",
                    in_bar_shelf_as_complex_ingredient=True,
                ),
            ),
        ]
    )
    assert [(r["name"], r["status"], r["via"]) for r in rows] == [
        ("Rye", "missing", ""),
        ("Gin", "probably", "can be made from what's on the shelf"),
    ]


def test_checklist_marks_optional_only_when_every_drink_does():
    rows = menu.ingredient_checklist(
        [
            drink("A", line(1, "Bitters", True), line(2, "Soda", True)),
            drink("B", line(1, "Bitters", True), line(2, "Soda", False)),
        ]
    )
    assert {r["name"]: r["optional"] for r in rows} == {"Bitters": True, "Soda": False}


def test_checklist_puts_missing_and_probable_first_alphabetically():
    rows = menu.ingredient_checklist(
        [
            drink(
                "A",
                line(1, "apple", in_bar_shelf=True),
                line(2, "Zest"),
                line(3, "Bourbon", in_bar_shelf_as_complex_ingredient=True),
                line(4, "Amaro", in_bar_shelf_as_complex_ingredient=True),
                line(5, "cherry"),
                line(6, "Banana", in_bar_shelf=True),
            )
        ]
    )
    assert [r["name"] for r in rows] == [
        "cherry",
        "Zest",
        "Amaro",
        "Bourbon",
        "apple",
        "Banana",
    ]


def test_checklist_of_no_drinks_is_empty():
    assert menu.ingredient_checklist([]) == []
    assert menu.ingredient_checklist([drink("A")]) == []


def test_ingredients_route_reads_each_drink_detail(owner, ba, listed, monkeypatch):
    monkeypatch.setitem(
        CATALOG,
        2,
        {
            **CATALOG[2],
            "ingredients": [
                line(102, "Lemon Juice", in_bar_shelf=True),
                line(104, "Maple Syrup", True, in_bar_shelf=True),
            ],
        },
    )
    r = owner.get("/api/menu/ingredients")
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["drinks"] == 2
    assert [(x["name"], x["status"], x["optional"]) for x in d["rows"]] == [
        ("Lemon Juice", "missing", False),
        ("Bourbon", "probably", False),
        ("Angostura", "on_shelf", True),
        ("Maple Syrup", "on_shelf", True),
    ]
    assert d["rows"][0]["drinks"] == ["Cider Sour", "Maple Old Fashioned"]
    assert [(u["drink"], u["amount"], u["units"], u["batch"]) for u in d["rows"][0]["uses"]] == [
        ("Cider Sour", 22.5, "ml", False),
        ("Maple Old Fashioned", None, "", False),
    ]
    assert d["rows"][2]["uses"][0]["amount_max"] == 2
    assert d["rows"][1]["via"] == "you have Buffalo Trace"


def test_ingredients_route_with_an_empty_menu(owner, env):
    put_list(env, [])
    r = owner.get("/api/menu/ingredients")
    assert r.status_code == 200 and r.get_json() == {"rows": [], "drinks": 0}


def test_ingredients_route_skips_a_drink_deleted_in_ba(owner, ba, listed):
    ba.deleted.add(1)
    r = owner.get("/api/menu/ingredients")
    assert r.status_code == 200 and r.get_json() == {"rows": [], "drinks": 1}


@pytest.mark.parametrize("failure", ["5xx", "unreachable"])
def test_ingredients_route_fails_loudly_when_ba_does(owner, ba, listed, failure):
    ba.detail_down = (
        True
        if failure == "5xx"
        else app_module.http.exceptions.ConnectionError("down")
    )
    r = owner.get("/api/menu/ingredients")
    assert r.status_code == 502 and "rows" not in r.get_json()
    assert r.get_json()["error"]


def test_kiosk_drinks_list_is_open_to_members_in_menu_order(
    owner, ba, env, monkeypatch
):
    ba.role = 3
    put_list(env, [2, 1, 3])
    seen = []
    fake_get = app_module.http.get

    def spy(url, **kw):
        seen.append(kw.get("params"))
        return fake_get(url, **kw)

    monkeypatch.setattr(app_module.http, "get", spy)
    r = owner.get("/api/menu/drinks")
    assert r.status_code == 200
    body = r.get_json()
    assert body["title"] == "Thanksgiving 2026"
    assert [c["id"] for c in body["data"]] == [2, 1, 3]
    assert body["data"][1]["name"] == "Cider Sour"
    lookup = next(p for p in seen if p and p.get("filter[id]") == "2,1,3")
    assert lookup["include"] == "images,ratings"


def test_kiosk_drinks_leave_out_ones_deleted_in_ba(owner, ba, env):
    put_list(env, [3, 1, 2])
    ba.deleted = {1}
    data = owner.get("/api/menu/drinks").get_json()["data"]
    assert [c["id"] for c in data] == [3, 2]


def test_kiosk_drinks_empty_when_never_set_up_or_emptied(owner, env):
    r = owner.get("/api/menu/drinks")
    assert r.status_code == 200 and r.get_json()["data"] == []
    put_list(env, [])
    r = owner.get("/api/menu/drinks")
    assert r.status_code == 200 and r.get_json()["data"] == []


def test_kiosk_drinks_need_login(guest, listed):
    r = guest.get("/api/menu/drinks")
    assert r.status_code == 401 and r.get_json() == {"error": "unauthorized"}


@pytest.mark.parametrize("failure", ["5xx", "unreachable"])
def test_kiosk_drinks_report_a_failed_lookup(owner, ba, listed, monkeypatch, failure):
    if failure == "5xx":
        ba.lookup_down = True
    else:

        def down(url, **kw):
            if url == f"{BA}/api/cocktails":
                raise app_module.http.exceptions.ConnectionError("down")
            return ba.get(url, **kw)

        monkeypatch.setattr(app_module.http, "get", down)
    r = owner.get("/api/menu/drinks")
    assert r.status_code == 502 and r.get_json()["error"]


# ── Preview ───────────────────────────────────────────────────────────────────


def test_preview_shows_the_board_without_saving_or_publishing(owner, ba, env):
    r = owner.get(
        "/menu/preview?title=Christmas+2026&subtitle=Merry&theme=christmas&ids=1"
    )
    page = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Christmas 2026" in page and "Merry" in page and "Cider Sour" in page
    assert '/api/images/77/thumb' in page  # BA's photo, nothing copied
    assert not os.path.exists(os.path.join(menu.menu_dir(str(env / ".env")), "menu.json"))


@pytest.mark.parametrize("role", [3, 4, None])
def test_preview_is_for_admins_and_moderators(owner, ba, role):
    ba.role = role
    assert owner.get("/menu/preview?ids=1").status_code == 403


def test_preview_needs_a_login(guest, ba):
    assert guest.get("/menu/preview?ids=1").status_code == 401


# ── ABV estimate for batch cocktails


def abv_line(ing_id, amount, units):
    return {"amount": amount, "units": units, "ingredient": {"id": ing_id, "name": f"I{ing_id}"}}


BATCH = {
    "id": 641,
    "slug": "bourbon-cranberry",
    "name": "Bourbon-Cranberry",
    "images": [],
    "method": {"name": "Build", "dilution_percentage": 10},
    "abv": 0,
    "ingredients": [
        abv_line(1, 4, "cups"),
        abv_line(2, 1, "cup"),
        abv_line(3, 2, "Cups"),
        abv_line(4, 3, "whole"),
    ],
}
BATCH_STRENGTHS = {1: 40, 2: 0, 3: 0, 4: 0}


@pytest.fixture
def batch(monkeypatch, ba):
    # A copy: the fake hands out catalog dicts, and publish writes abv into them.
    monkeypatch.setitem(CATALOG, BATCH["id"], copy.deepcopy(BATCH))
    ba.strengths = BATCH_STRENGTHS
    return BATCH


def test_detail_serves_the_estimate(owner, ba, batch):
    r = owner.get("/api/cocktails/641")
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["abv"] == 20.78
    assert [(i["amount"], i["units"]) for i in data["ingredients"]] == [
        (i["amount"], i["units"]) for i in BATCH["ingredients"]
    ]
    assert CATALOG[641]["abv"] == 0  # the fake's catalog entry is untouched
    assert ba.ingredient_lookups == 1


def test_detail_of_a_regular_drink_makes_no_lookup(owner, ba):
    r = owner.get("/api/cocktails/cider-sour")
    assert r.status_code == 200 and r.get_json()["data"]["abv"] == 18.5
    assert ba.ingredient_lookups == 0


@pytest.mark.parametrize("down", [True, app_module.http.exceptions.ConnectionError("down")])
def test_failed_strength_lookup_keeps_ba_value(owner, ba, batch, down):
    ba.ingredients_down = down
    r = owner.get("/api/cocktails/bourbon-cranberry")
    assert r.status_code == 200 and r.get_json()["data"]["abv"] == 0


def test_detail_404_passes_through(owner, ba):
    r = owner.get("/api/cocktails/no-such-drink")
    assert r.status_code == 404
    assert ba.ingredient_lookups == 0


CIDER_PUNCH = {
    "id": 642,
    "slug": "cider-punch",
    "name": "Cider Punch",
    "images": [],
    "method": {"name": "Build", "dilution_percentage": 10},
    "abv": 33.33,  # BA skips the cup of juice
    "ingredients": [abv_line(5, 1, "cup"), abv_line(6, 2, "oz")],
}


def test_publish_writes_the_estimate(owner, guest, ba, env, batch, monkeypatch):
    monkeypatch.setitem(CATALOG, CIDER_PUNCH["id"], copy.deepcopy(CIDER_PUNCH))
    ba.strengths = {**BATCH_STRENGTHS, 5: 0, 6: 40}
    publish(owner, env, [641, 642, 1])
    snap = menu.load(menu.menu_dir(str(env / ".env")))
    assert [c["abv"] for c in snap["cocktails"]] == [20.78, 7.36, 18.5]
    assert ba.ingredient_lookups == 1
    page = guest.get("/menu").get_data(as_text=True)
    assert "21% ABV" in page and "Zero proof" not in page


def test_preview_shows_the_estimate(owner, ba, env, batch):
    page = owner.get("/menu/preview?ids=641").get_data(as_text=True)
    assert "21% ABV" in page and "Zero proof" not in page
    assert ba.ingredient_lookups == 1
