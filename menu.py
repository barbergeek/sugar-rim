"""Holiday menu: a published snapshot of one Bar Assistant collection.

The public menu pages (/menu, /menu/r/<slug>, /menu/img/<slug>) are reached
with a secret key, not a login, so they serve only this snapshot: what the
owner published, copied to disk, never a live Bar Assistant call.
"""

import json
import os
import re
import secrets

import segno

INSET_DEFAULT = 5  # % of the screen kept clear for TVs that overscan
INSET_MAX = 15


def menu_dir(env_path):
    """Snapshot dir beside the real .env (/config/menu in Docker)."""
    return os.path.join(os.path.dirname(os.path.realpath(env_path)), "menu")


def new_key():
    return secrets.token_urlsafe(16)


def key_ok(given, expected):
    # Bytes: compare_digest raises on non-ASCII str, which a crafted URL can send.
    return bool(given and expected) and secrets.compare_digest(
        str(given).encode(), str(expected).encode()
    )


def _fmt_oz(n):
    """Nearest quarter ounce, with fraction characters."""
    q = round(n * 4)
    whole, rem = divmod(q, 4)
    frac = ["", "¼", "½", "¾"][rem]
    if whole == 0:
        return frac or "0"
    return f"{whole} {frac}" if frac else str(whole)


def _fmt_one(amount, units):
    try:
        num = float(amount)
    except (TypeError, ValueError):
        return str(amount), units
    u = units.lower()
    if u == "ml":
        return _fmt_oz(num / 30), "oz"
    if u == "cl":
        return _fmt_oz(num * 10 / 30), "oz"
    return (str(int(num)) if num.is_integer() else f"{num:g}"), units


def fmt_amount(amount, amount_max, units):
    """'1 ½ oz', '2–3 dashes', or '' when there's no amount."""
    units = (units or "").strip()
    if amount in (None, "", 0) and not amount_max:
        return ""
    lo, unit = _fmt_one(amount, units)
    if amount_max:
        hi, _ = _fmt_one(amount_max, units)
        if hi != lo:
            lo = f"{lo}–{hi}"
    return f"{lo} {unit}".strip()


def _named(v):
    return (v.get("name") if isinstance(v, dict) else v) or ""


def slim_cocktail(c):
    """Only the fields the public pages show: never users, ids or ratings."""
    ings = sorted(c.get("ingredients") or [], key=lambda i: i.get("sort") or 0)
    return {
        "slug": c.get("slug") or str(c.get("id")),
        "name": c.get("name") or "",
        "description": (c.get("description") or "").strip(),
        "instructions": (c.get("instructions") or "").strip(),
        "garnish": (c.get("garnish") or "").strip(),
        "glass": _named(c.get("glass")),
        "method": _named(c.get("method")),
        "abv": c.get("abv"),
        "ingredients": [
            {
                "name": _named(i.get("ingredient")) or i.get("name") or "",
                "amount": fmt_amount(
                    i.get("amount"), i.get("amount_max"), i.get("units")
                ),
                "optional": bool(i.get("optional")),
                "note": (i.get("note") or "").strip(),
            }
            for i in ings
        ],
        "image": None,  # set by the publisher once the photo is saved
    }


def key_ingredients(cocktail, limit=4):
    return [i["name"] for i in cocktail["ingredients"] if not i["optional"]][:limit]


def image_name(slug):
    return re.sub(r"[^a-z0-9-]", "-", slug.lower()) + ".jpg"


def load(directory):
    try:
        with open(os.path.join(directory, "menu.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save(directory, snapshot):
    """Write menu.json atomically, then drop photos it no longer uses."""
    path = os.path.join(directory, "menu.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snapshot, f)
    os.replace(tmp, path)
    keep = {c["image"] for c in snapshot["cocktails"] if c.get("image")}
    for name in os.listdir(directory):
        if name.endswith(".jpg") and name not in keep:
            os.remove(os.path.join(directory, name))


def find(snapshot, slug):
    for c in (snapshot or {}).get("cocktails", []):
        if c["slug"] == slug:
            return c
    return None


def qr_svg(url):
    # Dark modules on a white quiet zone, so phones read it on a dark board.
    return segno.make(url, error="m").svg_inline(
        scale=4, dark="#111", light="#fff", omitsize=True
    )


def inset(raw):
    try:
        return max(0, min(INSET_MAX, int(raw)))
    except (TypeError, ValueError):
        return INSET_DEFAULT
