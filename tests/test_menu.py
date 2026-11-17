import pytest

import app as app_module
import menu
from tests.test_import_routes import Resp

BA = "http://ba.test"
BASE = "https://sugar.example"
DENIED = "Only bar admins and moderators can manage the holiday menu"

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
        if url.startswith(f"{BA}/api/cocktails/"):
            slug = url.rsplit("/", 1)[-1]
            for c in CATALOG.values():
                if c["slug"] == slug and c["id"] not in self.deleted:
                    return Resp(json_data={"data": c})
            return Resp(404, json_data={})
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
        raise AssertionError(f"unexpected GET {url}")


@pytest.fixture
def ba(monkeypatch):
    fake = FakeBA()
    for verb in ("get",):
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
]


@pytest.mark.parametrize("role", [3, 4, None])
def test_other_roles_are_refused_and_nothing_is_written(owner, ba, env, role):
    ba.role = role
    for verb, path, body in ROUTES:
        r = getattr(owner, verb)(path, **({"json": body} if body else {}))
        assert r.status_code == 403, path
        assert r.get_json()["error"] == DENIED
    assert not (env / "menu").exists()
    for key in ("menu_page_seconds", "menu_suggest_model", "typesafe_api_key"):
        assert owner.post("/config", json={key: "9"}).status_code == 403
    assert app_module.os.getenv("MENU_PAGE_SECONDS") != "9"
    assert not (env / ".env").exists() or "9" not in (env / ".env").read_text()


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


def test_other_settings_stay_login_only(owner, ba):
    ba.role = 4
    assert owner.post("/config", json={"ai_model": "x"}).status_code == 200


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
