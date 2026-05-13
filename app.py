import os
import secrets
from datetime import timedelta
from flask import Flask, jsonify, request, render_template, session, redirect, url_for
import requests as http
from dotenv import load_dotenv, set_key

load_dotenv()

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")

# Persist secret key in .env so sessions survive server restarts
_secret = os.getenv("SECRET_KEY")
if not _secret:
    _secret = secrets.token_hex(32)
    if not os.path.exists(ENV_PATH):
        open(ENV_PATH, "w").close()
    set_key(ENV_PATH, "SECRET_KEY", _secret)
    os.environ["SECRET_KEY"] = _secret

app = Flask(__name__)
app.secret_key = _secret
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)


def ba_headers():
    """Headers with bar ID — for bar-scoped endpoints."""
    token  = session.get("ba_token")
    bar_id = os.getenv("BA_BAR_ID", "")
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if bar_id:
        h["Bar-Assistant-Bar-Id"] = bar_id
    return h


def auth_headers():
    """Auth-only headers — no bar ID. For endpoints addressed by URL parameter."""
    token = session.get("ba_token")
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def ba_url(path):
    base = os.getenv("BA_API_URL", "").rstrip("/")
    if base and not base.endswith("/api"):
        base += "/api"
    return f"{base}/{path.lstrip('/')}"


def proxy(method, path, bar_ctx=True, **kwargs):
    url  = ba_url(path)
    hdrs = ba_headers() if bar_ctx else auth_headers()
    try:
        resp = http.request(method, url, headers=hdrs, timeout=15, **kwargs)
        try:
            data = resp.json()
        except Exception:
            data = {"error": resp.text}
        return jsonify(data), resp.status_code
    except http.exceptions.ConnectionError:
        return jsonify({"error": "Cannot reach Bar Assistant API. Check your API URL in Settings."}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def bar_id_or_err():
    bid = os.getenv("BA_BAR_ID", "")
    if not bid:
        return None, (jsonify({"error": "No bar selected. Go to Settings and set an active bar."}), 400)
    return bid, None


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Settings ──────────────────────────────────────────────────────────────────

@app.route("/config", methods=["GET"])
def get_config():
    return jsonify({
        "api_url":      os.getenv("BA_API_URL", ""),
        "bar_id":       os.getenv("BA_BAR_ID", ""),
        "is_logged_in": "ba_token" in session
    })


@app.route("/config", methods=["POST"])
def set_config():
    body = request.get_json(force=True)
    if not os.path.exists(ENV_PATH):
        open(ENV_PATH, "w").close()
    if "api_url" in body:
        set_key(ENV_PATH, "BA_API_URL", body["api_url"])
        os.environ["BA_API_URL"] = body["api_url"]
    if "api_token" in body and body["api_token"]:
        set_key(ENV_PATH, "BA_API_TOKEN", body["api_token"])
        os.environ["BA_API_TOKEN"] = body["api_token"]
    if "bar_id" in body:
        set_key(ENV_PATH, "BA_BAR_ID", str(body["bar_id"]))
        os.environ["BA_BAR_ID"] = str(body["bar_id"])
    return jsonify({"ok": True})


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route("/api/auth/login", methods=["POST"])
def login():
    body = request.get_json(force=True)
    url = ba_url("/auth/login")
    try:
        resp = http.post(url, json=body, headers={"Accept": "application/json"}, timeout=15)
        data = resp.json()
        if resp.ok:
            session.permanent = True
            session["ba_token"] = data["data"]["token"]
            session.pop("ba_user_id", None)  # cleared so it's re-fetched fresh
            return jsonify({"ok": True})
        return jsonify(data), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.pop("ba_token", None)
    session.pop("ba_user_id", None)
    return jsonify({"ok": True})


def get_user_id():
    if "ba_user_id" in session:
        return session["ba_user_id"]
    try:
        resp = http.get(ba_url("/profile"), headers=auth_headers(), timeout=10)
        if resp.ok:
            uid = resp.json().get("data", {}).get("id")
            if uid:
                session["ba_user_id"] = uid
                return uid
    except Exception:
        pass
    return None


# ── Users ─────────────────────────────────────────────────────────────────────

@app.route("/api/users", methods=["GET", "POST"])
def users():
    if request.method == "POST":
        return proxy("POST", "/users", bar_ctx=False, json=request.get_json(force=True))
    return proxy("GET", "/users", bar_ctx=False)


@app.route("/api/users/<uid>", methods=["GET", "PUT", "DELETE"])
def user(uid):
    if request.method == "PUT":
        return proxy("PUT", f"/users/{uid}", bar_ctx=False, json=request.get_json(force=True))
    if request.method == "DELETE":
        return proxy("DELETE", f"/users/{uid}", bar_ctx=False)
    return proxy("GET", f"/users/{uid}", bar_ctx=False)

@app.route("/api/bars")
def bars():
    return proxy("GET", "/bars", bar_ctx=False)


@app.route("/api/bars/<bar_id>/stats")
def bar_stats(bar_id):
    return proxy("GET", f"/bars/{bar_id}/stats", bar_ctx=False)


# ── Cocktails ─────────────────────────────────────────────────────────────────

@app.route("/api/cocktails")
def cocktails():
    params = request.args.to_dict(flat=False)

    # filter[on_shelf]=true checks personal shelf; filter[bar_shelf]=true checks bar stock.
    # To union both we make two requests and merge by unique cocktail id.
    if params.get("filter[on_shelf]") == ["true"]:
        base = {k: v for k, v in params.items() if k != "filter[on_shelf]"}
        hdrs = ba_headers()
        url  = ba_url("/cocktails")
        try:
            r1 = http.get(url, headers=hdrs, params={**base, "filter[on_shelf]": "true"}, timeout=15)
            r2 = http.get(url, headers=hdrs, params={**base, "filter[bar_shelf]": "true"}, timeout=15)
            d1 = r1.json() if r1.ok else {"data": []}
            d2 = r2.json() if r2.ok else {"data": []}
            seen, merged = set(), []
            for item in (d1.get("data") or []) + (d2.get("data") or []):
                if item["id"] not in seen:
                    seen.add(item["id"])
                    merged.append(item)
            result = d1 if r1.ok else d2
            result["data"] = merged
            if "meta" in result:
                result["meta"]["total"] = len(merged)
            return jsonify(result), 200
        except http.exceptions.ConnectionError:
            return jsonify({"error": "Cannot reach Bar Assistant API."}), 502

    return proxy("GET", "/cocktails", params=params)


@app.route("/api/cocktails/<id_or_slug>")
def cocktail(id_or_slug):
    return proxy("GET", f"/cocktails/{id_or_slug}")


@app.route("/api/cocktails", methods=["POST"])
def create_cocktail():
    return proxy("POST", "/cocktails", json=request.get_json(force=True))


@app.route("/api/cocktails/<cid>", methods=["PUT"])
def update_cocktail(cid):
    return proxy("PUT", f"/cocktails/{cid}", json=request.get_json(force=True))


@app.route("/api/cocktails/<cid>", methods=["DELETE"])
def delete_cocktail(cid):
    return proxy("DELETE", f"/cocktails/{cid}")


@app.route("/api/cocktails/<cid>/toggle-favorite", methods=["POST"])
def toggle_favorite(cid):
    return proxy("POST", f"/cocktails/{cid}/toggle-favorite")


@app.route("/api/cocktails/<cid>/ratings", methods=["POST"])
def rate_cocktail(cid):
    return proxy("POST", f"/cocktails/{cid}/ratings", json=request.get_json(force=True))


@app.route("/api/cocktails/<cid>/ratings", methods=["DELETE"])
def delete_rating(cid):
    return proxy("DELETE", f"/cocktails/{cid}/ratings")


@app.route("/api/cocktails/<cid>/similar")
def similar_cocktails(cid):
    return proxy("GET", f"/cocktails/{cid}/similar")


# ── Ingredients ───────────────────────────────────────────────────────────────

@app.route("/api/ingredients")
def ingredients():
    params = request.args.to_dict(flat=False)
    return proxy("GET", "/ingredients", params=params)


@app.route("/api/ingredients/<id_or_slug>")
def ingredient(id_or_slug):
    return proxy("GET", f"/ingredients/{id_or_slug}")


@app.route("/api/ingredients", methods=["POST"])
def create_ingredient():
    return proxy("POST", "/ingredients", json=request.get_json(force=True))


@app.route("/api/ingredients/<iid>", methods=["PUT"])
def update_ingredient(iid):
    return proxy("PUT", f"/ingredients/{iid}", json=request.get_json(force=True))


@app.route("/api/ingredients/<iid>", methods=["DELETE"])
def delete_ingredient(iid):
    return proxy("DELETE", f"/ingredients/{iid}")


@app.route("/api/ingredients/<iid>/cocktails")
def ingredient_cocktails(iid):
    return proxy("GET", f"/ingredients/{iid}/cocktails")


# ── Utensils ──────────────────────────────────────────────────────────────────

@app.route("/api/utensils")
def utensils():
    return proxy("GET", "/utensils")


@app.route("/api/utensils/<uid>")
def utensil(uid):
    return proxy("GET", f"/utensils/{uid}")


# ── Collections ───────────────────────────────────────────────────────────────

@app.route("/api/collections")
def collections():
    return proxy("GET", "/collections")


@app.route("/api/collections/<cid>")
def collection(cid):
    return proxy("GET", f"/collections/{cid}")


# ── Notes ─────────────────────────────────────────────────────────────────────

@app.route("/api/notes")
def notes():
    return proxy("GET", "/notes")


# ── Images ────────────────────────────────────────────────────────────────────

@app.route("/api/images/<iid>/thumb")
def image_thumb(iid):
    url = ba_url(f"/images/{iid}/thumb")
    try:
        resp = http.get(url, headers=auth_headers(), timeout=10)
        return resp.content, resp.status_code, {"Content-Type": resp.headers.get("Content-Type", "image/jpeg")}
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ── Bar shelf ─────────────────────────────────────────────────────────────────
# Uses /bars/{id}/... endpoints — bar ID is in the URL, no Bar-Assistant-Bar-Id
# header required, so bar_ctx=False. Requires ability:* on the token.

@app.route("/api/shelf")
def shelf():
    bid, err = bar_id_or_err()
    if err:
        return err
    return proxy("GET", f"/bars/{bid}/ingredients", bar_ctx=False)


@app.route("/api/shelf/batch", methods=["POST"])
def shelf_batch():
    bid, err = bar_id_or_err()
    if err:
        return err
    return proxy("POST", f"/bars/{bid}/ingredients/batch-store", bar_ctx=False, json=request.get_json(force=True))


@app.route("/api/shelf/batch-delete", methods=["POST"])
def shelf_batch_delete():
    bid, err = bar_id_or_err()
    if err:
        return err
    return proxy("POST", f"/bars/{bid}/ingredients/batch-delete", bar_ctx=False, json=request.get_json(force=True))


# ── Shopping list ─────────────────────────────────────────────────────────────

@app.route("/api/shopping-list")
def shopping_list():
    uid = get_user_id()
    if not uid:
        return jsonify({"error": "Could not determine user ID — are you logged in?"}), 400
    return proxy("GET", f"/users/{uid}/shopping-list")


@app.route("/api/shopping-list/batch", methods=["POST"])
def shopping_list_batch():
    uid = get_user_id()
    if not uid:
        return jsonify({"error": "Could not determine user ID — are you logged in?"}), 400
    return proxy("POST", f"/users/{uid}/shopping-list/batch-store", json=request.get_json(force=True))


@app.route("/api/shopping-list/batch-delete", methods=["POST"])
def shopping_list_batch_delete():
    uid = get_user_id()
    if not uid:
        return jsonify({"error": "Could not determine user ID — are you logged in?"}), 400
    return proxy("POST", f"/users/{uid}/shopping-list/batch-delete", json=request.get_json(force=True))


# ── Tokens ────────────────────────────────────────────────────────────────────

@app.route("/api/tokens", methods=["GET", "POST"])
def tokens():
    if request.method == "POST":
        return proxy("POST", "/tokens", bar_ctx=False, json=request.get_json(force=True))
    return proxy("GET", "/tokens", bar_ctx=False)


@app.route("/api/tokens/<tid>", methods=["DELETE"])
def delete_token(tid):
    return proxy("DELETE", f"/tokens/{tid}", bar_ctx=False)


# ── Favorites ─────────────────────────────────────────────────────────────────
@app.route("/api/favorites")
def favorites():
    uid = get_user_id()
    if not uid:
        return jsonify({"error": "Could not determine user ID — are you logged in?"}), 400
    return proxy("GET", f"/users/{uid}/cocktails/favorites", params={"per_page": "500"})


# ── Profile ───────────────────────────────────────────────────────────────────
# Requires ability:* on the token. Used for display only; failures are non-fatal.

@app.route("/api/profile", methods=["GET", "PUT"])
def profile():
    if request.method == "PUT":
        return proxy("PUT", "/profile", bar_ctx=False, json=request.get_json(force=True))
    return proxy("GET", "/profile", bar_ctx=False)


# ── Reference data ────────────────────────────────────────────────────────────

@app.route("/api/glasses")
def glasses():
    return proxy("GET", "/glasses")


@app.route("/api/tags")
def tags():
    return proxy("GET", "/tags")


@app.route("/api/methods")
def methods():
    return proxy("GET", "/cocktail-methods")


# ── Server ────────────────────────────────────────────────────────────────────

@app.route("/api/server/version")
def server_version():
    return proxy("GET", "/server/version", bar_ctx=False)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
