import os
import secrets
from flask import Flask, jsonify, request, render_template
import requests as http
from dotenv import load_dotenv, set_key

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")


def ba_headers():
    """Headers with bar ID — for bar-scoped endpoints."""
    token  = os.getenv("BA_API_TOKEN", "")
    bar_id = os.getenv("BA_BAR_ID", "")
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if bar_id:
        h["Bar-Assistant-Bar-Id"] = bar_id
    return h


def auth_headers():
    """Auth-only headers — no bar ID. For endpoints addressed by URL parameter."""
    token = os.getenv("BA_API_TOKEN", "")
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def ba_url(path):
    base = os.getenv("BA_API_URL", "").rstrip("/")
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
        "api_url":   os.getenv("BA_API_URL", ""),
        "token_set": bool(os.getenv("BA_API_TOKEN", "")),
        "bar_id":    os.getenv("BA_BAR_ID", ""),
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


# ── Bars ──────────────────────────────────────────────────────────────────────

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


# ── Favorites ─────────────────────────────────────────────────────────────────
# Uses filter[favorites]=1 on the cocktails endpoint — only needs cocktails.read.

@app.route("/api/favorites")
def favorites():
    return proxy("GET", "/cocktails", params={"filter[favorites]": "1", "per_page": "100"})


# ── Profile ───────────────────────────────────────────────────────────────────
# Requires ability:* on the token. Used for display only; failures are non-fatal.

@app.route("/api/profile")
def profile():
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
    return proxy("GET", "/methods")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
