import os
import re
import base64
import io
import math
import socket
import secrets
import logging
import ipaddress
from datetime import timedelta
from urllib.parse import urlparse
from flask import Flask, jsonify, request, render_template, session, redirect, url_for
import requests as http
from dotenv import load_dotenv, set_key
from PIL import Image, ImageChops, ImageDraw, ImageFilter

import scrapers
from scrapers.draft2 import from_draft2, to_draft2
from scrapers.match import rank as rank_ingredients
from scrapers.fetch import fetch_html, FetchBlocked, FetchError, UrlNotAllowed

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

APP_VERSION = "1.11.0"

app = Flask(__name__)
app.secret_key = _secret
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
# Cookie hardening. Secure is on by default (prod is HTTPS via Cloudflare);
# set SESSION_COOKIE_SECURE=0 for plain-HTTP local dev (see run.sh).
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "1") not in ("0", "false", "False"),
)


def _logged_in():
    return "ba_token" in session


def _configured():
    return bool(os.getenv("BA_API_URL"))


# Shown when a wrong Bar Assistant URL blocks login: the URL can't be changed
# from the UI without logging in (that would let anyone repoint it), so say how.
URL_FIX_HINT = ("If the Bar Assistant URL is wrong, set BA_API_URL in sugar-rim's .env "
                "(/config/.env in Docker) and restart sugar-rim.")


def _is_public_http_url(url):
    """True only for http(s) URLs that resolve to a public IP — blocks SSRF to
    loopback/private/link-local hosts (e.g. internal docker services, the LAN)."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except Exception:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # The UI relies on inline handlers/styles, so script/style keep 'unsafe-inline';
    # connect-src is still locked down (limits where injected JS could exfiltrate to)
    # and frame-ancestors/object-src/base-uri are hardened.
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://static.cloudflareinsights.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' http://localhost:8765 http://127.0.0.1:8765 https://cloudflareinsights.com; "
        "frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
    )
    return resp


def _asset_url(path):
    """Return a static URL with an mtime-based cache-buster."""
    abs_path = os.path.join(app.static_folder, path)
    try:
        ts = int(os.path.getmtime(abs_path))
    except OSError:
        ts = 0
    return f"/static/{path}?v={ts}"


app.jinja_env.globals["asset_url"] = _asset_url


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


@app.route("/kiosk")
def kiosk():
    return render_template("kiosk.html")


@app.route("/favicon.ico")
def favicon():
    return app.send_static_file("favicon.ico")


# ── Settings ──────────────────────────────────────────────────────────────────

@app.route("/config", methods=["GET"])
def get_config():
    return jsonify({
        "api_url":      os.getenv("BA_API_URL", ""),
        "bar_id":       os.getenv("BA_BAR_ID", ""),
        "is_logged_in": "ba_token" in session,
        "app_version":  APP_VERSION,
        "ai_provider":  os.getenv("AI_IMAGE_PROVIDER", ""),
        "ai_model":     os.getenv("AI_IMAGE_MODEL", ""),
        "ai_base_url":  os.getenv("AI_IMAGE_BASE_URL", ""),
        "ai_key_set":   bool(os.getenv("AI_IMAGE_API_KEY")),
        "ai_prompt_ingredient": os.getenv("AI_PROMPT_INGREDIENT", ""),
    })


@app.route("/config", methods=["POST"])
def set_config():
    # First-run setup (no API URL configured yet) may write unauthenticated so
    # the UI can bootstrap. Once configured, changing settings — which can
    # repoint the API URL and intercept credentials — requires a logged-in
    # session. (In prod BA_API_URL is seeded via env, so this is always gated.)
    if _configured() and not _logged_in():
        return jsonify({"error": "Log in to change server settings. " + URL_FIX_HINT}), 401
    body = request.get_json(force=True)
    if not _logged_in() and any(
            k in body for k in ("ai_provider", "ai_model", "ai_base_url", "ai_api_key",
                                "ai_prompt_ingredient")):
        return jsonify({"error": "unauthorized"}), 401
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
    if ("ai_provider" in body and not body.get("ai_api_key")
            and str(body["ai_provider"] or "").strip() != os.getenv("AI_IMAGE_PROVIDER", "")):
        set_key(ENV_PATH, "AI_IMAGE_API_KEY", "")
        os.environ["AI_IMAGE_API_KEY"] = ""
    for field, env in (("ai_provider", "AI_IMAGE_PROVIDER"), ("ai_model", "AI_IMAGE_MODEL"),
                       ("ai_base_url", "AI_IMAGE_BASE_URL")):
        if field in body:
            val = str(body[field] or "").strip()
            set_key(ENV_PATH, env, val)
            os.environ[env] = val
    if "ai_prompt_ingredient" in body:  # one line keeps .env simple; empty = default
        val = " ".join(str(body["ai_prompt_ingredient"] or "").split())
        set_key(ENV_PATH, "AI_PROMPT_INGREDIENT", val)
        os.environ["AI_PROMPT_INGREDIENT"] = val
    if body.get("ai_api_key"):  # write-only; blank keeps the existing key
        set_key(ENV_PATH, "AI_IMAGE_API_KEY", body["ai_api_key"])
        os.environ["AI_IMAGE_API_KEY"] = body["ai_api_key"]
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
    # Before RequestException: requests' JSONDecodeError subclasses both.
    except ValueError:  # non-JSON reply: something answered, but it isn't Bar Assistant
        msg = f"{os.getenv('BA_API_URL')} didn't answer like Bar Assistant. {URL_FIX_HINT}"
        return jsonify({"error": msg}), 502
    except http.exceptions.RequestException:
        msg = f"Can't reach Bar Assistant at {os.getenv('BA_API_URL')}. {URL_FIX_HINT}"
        return jsonify({"error": msg}), 502
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

    # Carry image + rating data in the list payload so the UI can render cards
    # without an extra detail fetch per cocktail (no N+1 on complete-set loads).
    params.setdefault("include", ["images,ratings"])

    # Union personal shelf (filter[on_shelf]) and bar stock (filter[bar_shelf]).
    # Fetch all results from both at once, merge, then self-paginate so meta is correct.
    if params.get("filter[on_shelf]") == ["true"]:
        per_page = int((params.get("per_page") or ["30"])[0])
        page     = int((params.get("page")     or ["1"])[0])
        base = {k: v for k, v in params.items()
                if k not in ("filter[on_shelf]", "page", "per_page")}
        hdrs = ba_headers()
        url  = ba_url("/cocktails")
        try:
            fetch = {**base, "per_page": 500, "page": 1}
            r1 = http.get(url, headers=hdrs, params={**fetch, "filter[on_shelf]": "true"}, timeout=15)
            r2 = http.get(url, headers=hdrs, params={**fetch, "filter[bar_shelf]": "true"}, timeout=15)
            d1 = r1.json() if r1.ok else {"data": [], "meta": {}}
            d2 = r2.json() if r2.ok else {"data": [], "meta": {}}
            seen, all_items = set(), []
            for item in (d1.get("data") or []) + (d2.get("data") or []):
                if item["id"] not in seen:
                    seen.add(item["id"])
                    all_items.append(item)

            # filter[bar_shelf] ignores filter[ingredient_name][], so post-filter the union.
            # Use ingredients[].ingredient.name — short_ingredients is always null in list responses.
            ing_filter = [n.lower() for n in base.get("filter[ingredient_name][]", [])]
            if ing_filter:
                def _has_ingredients(item):
                    names = [
                        i["ingredient"]["name"].lower()
                        for i in (item.get("ingredients") or [])
                        if i.get("ingredient")
                    ]
                    return all(any(req in n for n in names) for req in ing_filter)
                all_items = [item for item in all_items if _has_ingredients(item)]
            total     = len(all_items)
            last_page = max(1, math.ceil(total / per_page))
            start     = (page - 1) * per_page
            result    = d1 if r1.ok else (d2 if r2.ok else {"data": [], "meta": {}})
            result["data"] = all_items[start:start + per_page]
            result.setdefault("meta", {}).update({
                "total":        total,
                "per_page":     per_page,
                "current_page": page,
                "last_page":    last_page,
                "from":         start + 1 if all_items else 0,
                "to":           start + len(result["data"]),
            })
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
    # Carry image data in the list payload so cards render without a detail fetch.
    params.setdefault("include", ["images"])
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


@app.route("/api/images", methods=["POST"])
def upload_image():
    """Forward multipart image upload to BA. Omit Content-Type so requests sets the boundary."""
    hdrs = {k: v for k, v in ba_headers().items() if k != "Content-Type"}
    files = {key: (f.filename or "image.jpg", f.read(), f.content_type or "image/jpeg")
             for key, f in request.files.items()}
    try:
        resp = http.post(ba_url("/images"), headers=hdrs, files=files, data=request.form, timeout=30)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/images/from-url", methods=["POST"])
def image_from_url():
    """Download an image from a URL and upload it to BA."""
    if not _logged_in():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(force=True) or {}
    src_url = body.get("url", "").strip()
    if not src_url:
        return jsonify({"error": "url required"}), 400
    if not _is_public_http_url(src_url):
        return jsonify({"error": "URL not allowed"}), 400
    try:
        r = http.get(src_url, timeout=15,
                     headers={"User-Agent": "Mozilla/5.0 (compatible; sugar-rim/1.0)"})
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if not ct.startswith("image/"):
            return jsonify({"error": f"URL did not return an image (got {ct})"}), 422
        # Derive a filename with extension from the URL or content-type
        fname = src_url.split("/")[-1].split("?")[0] or ""
        if "." not in fname:
            ext = ct.split("/")[-1].replace("jpeg", "jpg")
            fname = f"image.{ext}"
        hdrs = {k: v for k, v in ba_headers().items() if k != "Content-Type"}
        files = {"images[0][image]": (fname, r.content, ct)}
        resp = http.post(ba_url("/images"), headers=hdrs, files=files,
                         data={"images[0][sort]": "1"}, timeout=30)
        ba_data = resp.json()
        if not resp.ok:
            return jsonify({"error": ba_data.get("message", "Image upload failed")}), resp.status_code
        return jsonify(ba_data), resp.status_code
    except http.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/images/<int:iid>", methods=["DELETE"])
def delete_image(iid):
    try:
        resp = http.delete(ba_url(f"/images/{iid}"), headers=ba_headers(), timeout=10)
        return ("", 204) if resp.status_code in (200, 204) else (jsonify(resp.json()), resp.status_code)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ── AI image generation ───────────────────────────────────────────────────────

class AIImageError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _provider_error(resp):
    try:
        err = resp.json().get("error")
        msg = err if isinstance(err, str) else (err or {}).get("message")
    except (ValueError, AttributeError):
        msg = None
    return msg or f"HTTP {resp.status_code}"


def _openai_style(url, prompt, model, key, b64_format, timeout, extra=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {"model": model, "prompt": prompt, "size": "1024x1024", "n": 1, **(extra or {})}
    if b64_format:
        payload["response_format"] = "b64_json"
    resp = http.post(url, headers=headers, json=payload, timeout=timeout)
    if not resp.ok:
        raise AIImageError(_provider_error(resp))
    item = ((resp.json().get("data")) or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"]), "image/png"
    if item.get("url"):
        r = http.get(item["url"], timeout=60)
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type", "image/png").split(";")[0].strip()
    raise AIImageError("no image returned")


def _gemini(prompt, model, key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    resp = http.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                     json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=120)
    if not resp.ok:
        raise AIImageError(_provider_error(resp))
    for cand in resp.json().get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                return base64.b64decode(inline["data"]), mime
    raise AIImageError("no image returned")


AI_DEFAULT_MODELS = {"openai": "gpt-image-2", "gemini": "gemini-2.5-flash-image"}


def _generate_image(prompt, transparent=False):
    """Dispatch to the configured provider; returns (bytes, mime)."""
    provider = os.getenv("AI_IMAGE_PROVIDER", "")
    model = os.getenv("AI_IMAGE_MODEL", "").strip()
    key = os.getenv("AI_IMAGE_API_KEY", "")
    base = os.getenv("AI_IMAGE_BASE_URL", "").strip()
    not_configured = AIImageError(
        "AI image provider not configured. Set it up in Settings.", 400)
    try:
        if provider == "openai":
            if not key:
                raise not_configured
            model = model or AI_DEFAULT_MODELS["openai"]
            url = "https://api.openai.com/v1/images/generations"
            dalle = model.startswith("dall-e")
            # Most gpt-image models can return real alpha; others fall back to the cut-out.
            extra = ({"background": "transparent", "output_format": "png"}
                     if transparent and model.startswith("gpt-image") else None)
            try:
                return _openai_style(url, prompt, model, key, dalle, 120, extra)
            except AIImageError as e:
                # Some gpt-image models reject transparency (e.g. gpt-image-2): retry
                # opaque and let the cut-out remove the background.
                if not extra or not re.search(r"background|transparen", str(e), re.IGNORECASE):
                    raise
                return _openai_style(url, prompt, model, key, dalle, 120)
        if provider == "gemini":
            if not key:
                raise not_configured
            return _gemini(prompt, model or AI_DEFAULT_MODELS["gemini"], key)
        if provider == "compatible":
            if not base or not model:
                raise not_configured
            return _openai_style(f"{base.rstrip('/')}/images/generations", prompt,
                                 model, key, True, 120)
    except http.exceptions.RequestException as e:
        raise AIImageError(str(e))
    raise not_configured


def _cut_out_background(data, mime):
    """Make the white background (and its grey shadow) that touches the image edges transparent,
    for providers (e.g. Gemini) that can't return alpha. Images that already have
    real transparency are returned unchanged."""
    im = Image.open(io.BytesIO(data))
    if im.convert("RGBA").getchannel("A").getextrema()[0] < 255:
        return data, mime
    rgb = im.convert("RGB")
    # Background = near-grey pixels connected to the edge: the white backdrop plus
    # the contact shadow Gemini draws even when told not to. Saturated subject
    # pixels stop the fill.
    r, g, b = rgb.split()
    lo = ImageChops.darker(ImageChops.darker(r, g), b)
    hi = ImageChops.lighter(ImageChops.lighter(r, g), b)
    grey = ImageChops.subtract(hi, lo).point(lambda v: 255 if v <= 32 else 0)
    w, h = grey.size
    edges = ([(x, y) for x in range(w) for y in (0, h - 1)]
             + [(x, y) for y in range(h) for x in (0, w - 1)])
    for xy in edges:
        if grey.getpixel(xy) == 255:
            ImageDraw.floodfill(grey, xy, 128)  # mark bg connected to the edge
    bg = grey.point(lambda v: 255 if v == 128 else 0).filter(ImageFilter.GaussianBlur(1))
    # In the background, white -> clear and grey -> translucent black, so the
    # shadow fades out instead of leaving a pale ring.
    shade = lo.point(lambda v: max(0, min(255, (245 - v) * 2)))
    alpha = Image.composite(shade, Image.new("L", rgb.size, 255), bg)
    rgb = Image.composite(Image.new("RGB", rgb.size), rgb, bg)
    rgb.putalpha(alpha)
    buf = io.BytesIO()
    rgb.save(buf, "PNG")
    return buf.getvalue(), "image/png"


def _list_image_models(provider, key, base):
    """Model ids the provider offers for image generation, sorted."""
    if provider == "openai":
        r = http.get("https://api.openai.com/v1/models",
                     headers={"Authorization": f"Bearer {key}"}, timeout=20)
        if not r.ok:
            raise AIImageError(_provider_error(r))
        ids = [m.get("id", "") for m in r.json().get("data") or []]
        return sorted(i for i in ids if i.startswith(("gpt-image", "chatgpt-image", "dall-e")))
    if provider == "gemini":
        r = http.get("https://generativelanguage.googleapis.com/v1beta/models",
                     headers={"x-goog-api-key": key}, params={"pageSize": 1000}, timeout=20)
        if not r.ok:
            raise AIImageError(_provider_error(r))
        return sorted(m["name"].removeprefix("models/") for m in r.json().get("models") or []
                      if "image" in m.get("name", "")
                      and "generateContent" in (m.get("supportedGenerationMethods") or []))
    if provider == "compatible":  # no way to tell image models apart; list them all
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        r = http.get(f"{base.rstrip('/')}/models", headers=headers, timeout=20)
        if not r.ok:
            raise AIImageError(_provider_error(r))
        return sorted(m.get("id", "") for m in r.json().get("data") or [] if m.get("id"))
    raise AIImageError("Choose a provider first.", 400)


@app.route("/api/ai/models", methods=["POST"])
def ai_models():
    if not _logged_in():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(force=True, silent=True) or {}
    provider = str(body.get("provider") or "").strip()
    base = str(body.get("base_url") or "").strip()
    key = str(body.get("api_key") or "")
    if not key and provider == os.getenv("AI_IMAGE_PROVIDER", ""):
        key = os.getenv("AI_IMAGE_API_KEY", "")  # saved key never leaves the server
    if provider in ("openai", "gemini") and not key:
        return jsonify({"error": "Enter an API key to load models."}), 400
    if provider == "compatible" and not base:
        return jsonify({"error": "Enter a base URL to load models."}), 400
    try:
        models = _list_image_models(provider, key, base)
    except AIImageError as e:
        return jsonify({"error": str(e)}), e.status
    except (http.exceptions.RequestException, ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"models": models, "default": AI_DEFAULT_MODELS.get(provider, "")})


@app.route("/api/ai/image", methods=["POST"])
def ai_image():
    if not _logged_in():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(force=True, silent=True) or {}
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    transparent = bool(body.get("transparent"))
    try:
        data, mime = _generate_image(prompt, transparent)
        if transparent:
            data, mime = _cut_out_background(data, mime)
    except AIImageError as e:
        return jsonify({"error": str(e)}), e.status
    b64 = base64.b64encode(data).decode()
    return jsonify({"image": f"data:{mime};base64,{b64}"})


# ── Recipe import ─────────────────────────────────────────────────────────────

def _ba_scrape(url, html=None):
    """Ask Bar Assistant to scrape; returns a draft dict or None on any failure."""
    payload = {"source": url}
    if html is not None:
        payload["html_content"] = html
    try:
        resp = http.post(ba_url("/import/scrape"), headers=ba_headers(), json=payload, timeout=10)
        if not resp.ok:
            return None
        return from_draft2(resp.json()["data"]["schema"])
    except (http.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError):
        return None


@app.route("/api/import/scrape", methods=["POST"])
def import_scrape():
    """Turn a URL (or pasted HTML) into a Bar Assistant schema-v4 draft."""
    if not _logged_in():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    html = body.get("html")
    if not url and html:
        # Pasted source: the URL is optional; take it from the page if present.
        url = scrapers.page_url(html) or ""
        if url and not _is_public_http_url(url):
            url = ""
    elif not url:
        return jsonify({"error": "url required"}), 400
    elif not _is_public_http_url(url):
        return jsonify({"error": "URL not allowed"}), 400

    if not html:
        try:
            html = fetch_html(url, _is_public_http_url, user_agent=f"sugar-rim/{APP_VERSION}")
        except UrlNotAllowed:
            return jsonify({"error": "URL not allowed"}), 400
        except FetchBlocked:
            draft = _ba_scrape(url)
            if draft:
                return jsonify({"data": draft, "scraper": "bar-assistant"})
            return jsonify({"error": "This site blocked the fetch. Try pasting the page HTML instead."}), 422
        except FetchError as e:
            return jsonify({"error": f"Could not fetch the page: {e}"}), 502

    try:
        draft, name = scrapers.scrape(url, html)
        return jsonify({"data": draft, "scraper": name})
    except scrapers.NoRecipeFound:
        pass
    draft = _ba_scrape(url, html=html)
    if draft:
        return jsonify({"data": draft, "scraper": "bar-assistant"})
    return jsonify({"error": "No recipe found on this page"}), 422


@app.route("/api/import/match", methods=["POST"])
def import_match():
    """Rank the bar's existing ingredients against each given name."""
    if not _logged_in():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    names = body.get("names")
    if (
        not isinstance(names, list)
        or len(names) > 50
        or not all(isinstance(n, str) for n in names)
    ):
        return jsonify({"error": "names must be a list of up to 50 strings"}), 400
    pool, page = [], 1
    try:
        while True:
            resp = http.get(ba_url("/ingredients"), headers=ba_headers(), timeout=10,
                            params={"per_page": 500, "page": page})
            if not resp.ok:
                return jsonify({"error": "Bar Assistant ingredient lookup failed"}), 502
            payload = resp.json()
            for i in payload.get("data") or []:
                pool.append({"id": i.get("id"), "name": i.get("name"),
                             "on_shelf": bool(i.get("in_shelf") or i.get("in_bar_shelf"))})
            last = ((payload.get("meta") or {}).get("last_page")) or 1
            if page >= last:
                break
            page += 1
    except (http.exceptions.RequestException, ValueError, AttributeError, TypeError) as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"matches": [rank_ingredients(n, pool) for n in names]})


@app.route("/api/import/cocktail", methods=["POST"])
def import_cocktail():
    """Save a draft to Bar Assistant; returns the new cocktail id."""
    if not _logged_in():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    draft = body.get("draft")
    if not isinstance(draft, dict):
        return jsonify({"error": "draft required"}), 400
    try:
        resp = http.post(ba_url("/import/cocktail"), headers=ba_headers(), timeout=25,
                         json={"source": to_draft2(draft), "duplicate_actions": "none"},
                         allow_redirects=False)
    except http.exceptions.ConnectionError:
        return jsonify({"error": "Cannot reach Bar Assistant API. Check your API URL in Settings."}), 502
    except http.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 502
    try:
        data = resp.json()
    except ValueError:
        data = {"error": resp.text}
    if resp.status_code >= 400:
        return jsonify(data), resp.status_code
    new_id = None
    m = re.search(r"/cocktails/(\d+)", resp.headers.get("Location", ""))
    if m:
        new_id = int(m.group(1))
    elif isinstance(data, dict) and isinstance(data.get("data"), dict):
        new_id = data["data"].get("id")
    if new_id is None:
        return jsonify({"error": "Import succeeded but no cocktail id was returned"}), 502
    return jsonify({"id": new_id}), 201


# ── Bar shelf ─────────────────────────────────────────────────────────────────
# Uses /bars/{id}/... endpoints — bar ID is in the URL, no Bar-Assistant-Bar-Id
# header required, so bar_ctx=False. Requires ability:* on the token.

@app.route("/api/shelf")
def shelf():
    bid, err = bar_id_or_err()
    if err:
        return err
    # Forward query params and default to a high per_page so the full shelf
    # comes back — BA's default page size otherwise truncates the list
    # (e.g. ingredients past "S" silently dropped). Mirrors the cocktails cap.
    params = request.args.to_dict(flat=False)
    params.setdefault("per_page", ["500"])
    return proxy("GET", f"/bars/{bid}/ingredients", bar_ctx=False, params=params)


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

@app.route("/api/glasses", methods=["GET", "POST"])
def glasses():
    if request.method == "POST":
        return proxy("POST", "/glasses", json=request.get_json(force=True))
    return proxy("GET", "/glasses")


@app.route("/api/glasses/<int:gid>", methods=["PUT", "DELETE"])
def glass_detail(gid):
    if request.method == "PUT":
        return proxy("PUT", f"/glasses/{gid}", json=request.get_json(force=True))
    return proxy("DELETE", f"/glasses/{gid}")


@app.route("/api/tags")
def tags():
    return proxy("GET", "/tags")


@app.route("/api/methods", methods=["GET", "POST"])
def methods():
    if request.method == "POST":
        return proxy("POST", "/cocktail-methods", json=request.get_json(force=True))
    return proxy("GET", "/cocktail-methods")


@app.route("/api/methods/<int:mid>", methods=["PUT", "DELETE"])
def method_detail(mid):
    if request.method == "PUT":
        return proxy("PUT", f"/cocktail-methods/{mid}", json=request.get_json(force=True))
    return proxy("DELETE", f"/cocktail-methods/{mid}")


# ── Server ────────────────────────────────────────────────────────────────────

@app.route("/api/server/version")
def server_version():
    return proxy("GET", "/server/version", bar_ctx=False)


def _log_startup():
    log = logging.getLogger(__name__)
    api_url   = os.getenv("BA_API_URL", "")
    bar_id    = os.getenv("BA_BAR_ID", "")
    has_token = bool(os.getenv("BA_API_TOKEN", ""))

    api_version = "unavailable"
    if api_url:
        try:
            r = http.get(
                ba_url("/server/version"),
                headers={"Accept": "application/json"},
                timeout=5,
            )
            if r.ok:
                api_version = r.json().get("data", {}).get("version", "unknown")
        except Exception:
            pass

    log.info("=" * 50)
    log.info("sugar-rim v%s", APP_VERSION)
    log.info("Bar Assistant API : %s", api_url or "not configured")
    log.info("BA API version    : %s", api_version)
    log.info("API token         : %s", "set" if has_token else "not set")
    log.info("Active bar ID     : %s", bar_id or "not set")
    log.info("=" * 50)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_log_startup()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
