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


def fake_ba(cocktails=COCKTAILS, collection_ok=True):
    def get(url, **kw):
        if url == f"{BA}/api/collections/5":
            if not collection_ok:
                return Resp(404, json_data={})
            return Resp(
                json_data={
                    "data": {
                        "id": 5,
                        "name": "Thanksgiving 2026",
                        "description": "Fall favorites",
                    }
                }
            )
        if url == f"{BA}/api/cocktails":
            assert kw["params"]["filter[collection_id]"] == 5
            return Resp(json_data={"data": cocktails})
        if url == f"{BA}/api/images/77/thumb":
            r = Resp()
            r.content = b"\xff\xd8jpeg"
            return r
        raise AssertionError(f"unexpected GET {url}")

    return get


@pytest.fixture
def env(monkeypatch, tmp_path):
    app_module.app.config["TESTING"] = True
    monkeypatch.setattr(app_module, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.setenv("BA_API_URL", BA)
    monkeypatch.setenv(
        "MENU_KEY", ""
    )  # restored on teardown; the app writes os.environ
    monkeypatch.setattr(app_module.http, "get", fake_ba())
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


def key_of(state):
    return state["url"].split("key=")[1]


def test_owner_routes_need_login(guest):
    assert guest.get("/api/menu").status_code == 401
    assert guest.post("/api/menu/key").status_code == 401
    assert guest.post("/api/menu/publish", json={"collection_id": 5}).status_code == 401


def test_publish_snapshots_collection_and_makes_key(owner, env):
    state = publish(owner)
    assert state["published"]["title"] == "Thanksgiving 2026"
    assert state["published"]["count"] == 2
    assert state["url"].startswith(f"{BASE}/menu?key=")
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


def test_publish_rejects_bad_input(owner, monkeypatch):
    bad = [
        {"collection_id": "5", "public_base": BASE},
        {"collection_id": 5, "public_base": "javascript:alert(1)"},
    ]
    for body in bad:
        assert owner.post("/api/menu/publish", json=body).status_code == 400
    monkeypatch.setattr(app_module.http, "get", fake_ba(cocktails=[]))
    r = owner.post("/api/menu/publish", json={"collection_id": 5, "public_base": BASE})
    assert r.status_code == 400
    monkeypatch.setattr(app_module.http, "get", fake_ba(cocktails=COCKTAILS * 4))
    r = owner.post("/api/menu/publish", json={"collection_id": 5, "public_base": BASE})
    assert r.status_code == 400 and "at most" in r.get_json()["error"]


def test_republish_keeps_key_and_drops_unused_photos(owner, env, monkeypatch):
    key = key_of(publish(owner))
    monkeypatch.setattr(app_module.http, "get", fake_ba(cocktails=COCKTAILS[1:]))
    assert key_of(publish(owner)) == key
    assert not (env / "menu" / "cider-sour.jpg").exists()


def test_public_pages_need_the_key(owner, guest):
    publish(owner)
    for path in ("/menu", "/menu/r/cider-sour", "/menu/img/cider-sour"):
        assert guest.get(path).status_code == 404
        assert guest.get(path + "?key=wrong").status_code == 404


def test_board_shows_menu_with_qr_to_recipe(owner, guest):
    key = key_of(publish(owner))
    r = guest.get(f"/menu?key={key}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Thanksgiving 2026" in html and "Maple Old Fashioned" in html
    assert (
        "Bourbon · Lemon Juice" in html and "Angostura" not in html
    )  # optional left off
    assert "<svg" in html
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["Cache-Control"] == "no-store"
    assert "--inset: 5" in html
    assert "--inset: 15" in guest.get(f"/menu?key={key}&inset=99").get_data(
        as_text=True
    )


def test_recipe_and_image_only_for_menu_cocktails(owner, guest):
    key = key_of(publish(owner))
    r = guest.get(f"/menu/r/cider-sour?key={key}")
    assert r.status_code == 200 and "Apple fan" in r.get_data(as_text=True)
    assert guest.get(f"/menu/r/not-on-menu?key={key}").status_code == 404
    img = guest.get(f"/menu/img/cider-sour?key={key}")
    assert img.status_code == 200 and img.data == b"\xff\xd8jpeg"
    assert guest.get(f"/menu/img/maple-old-fashioned?key={key}").status_code == 404
    assert guest.get(f"/menu/img/..%2F.env?key={key}").status_code == 404


def test_non_ascii_key_is_not_found_not_a_crash(owner, guest):
    publish(owner)
    assert guest.get("/menu?key=%C3%A9").status_code == 404


def test_board_carries_the_reload_marker(owner, guest):
    key = key_of(publish(owner))
    assert "data-menu-board" in guest.get(f"/menu?key={key}").get_data(as_text=True)


def test_new_key_revokes_old_links(owner, guest):
    old = key_of(publish(owner))
    new = key_of(owner.post("/api/menu/key").get_json())
    assert new != old
    assert guest.get(f"/menu?key={old}").status_code == 404
    assert guest.get(f"/menu?key={new}").status_code == 200


def test_board_before_anything_published(owner, guest):
    state = owner.post("/api/menu/key").get_json()
    assert state == {"published": None, "url": None}
    r = guest.get(f"/menu?key={app_module.os.environ['MENU_KEY']}")
    assert r.status_code == 200 and "No menu has been published" in r.get_data(
        as_text=True
    )


def test_fmt_amount():
    assert menu.fmt_amount(30, None, "ml") == "1 oz"
    assert menu.fmt_amount(7.5, None, "ml") == "¼ oz"
    assert menu.fmt_amount(2, None, "dashes") == "2 dashes"
    assert menu.fmt_amount(None, None, "") == ""
    assert menu.fmt_amount(1, None, "whole") == "1 whole"
