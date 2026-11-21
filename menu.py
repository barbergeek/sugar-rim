"""Holiday menu: a menu list stored in sugar-rim, published as a snapshot.

Admins and moderators manage the list; the public menu pages (/menu,
/menu/r/<slug>, /menu/img/<slug>) need no login, so they serve only the
published snapshot of it, copied to disk, never a live Bar Assistant call.
"""

import hashlib
import html
import json
import math
import os
import re

import segno

INSET_DEFAULT = 5  # % of the screen kept clear for TVs that overscan
INSET_MAX = 15


def menu_dir(env_path):
    """Snapshot dir beside the real .env (/config/menu in Docker)."""
    return os.path.join(os.path.dirname(os.path.realpath(env_path)), "menu")


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


def _text(v):
    """Imported recipes can carry HTML entities ("America&#039;s"); decode them
    so pages show the character, not the code."""
    return html.unescape(v or "").strip()


def _named(v):
    return (v.get("name") if isinstance(v, dict) else v) or ""


def slim_cocktail(c):
    """Only the fields the public pages show: never users, ids or ratings."""
    ings = sorted(c.get("ingredients") or [], key=lambda i: i.get("sort") or 0)
    return {
        "slug": c.get("slug") or str(c.get("id")),
        "name": c.get("name") or "",
        "description": _text(c.get("description")),
        "instructions": _text(c.get("instructions")),
        "garnish": _text(c.get("garnish")),
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
                "strength": (i.get("ingredient") or {}).get("strength") or 0,
            }
            for i in ings
        ],
        "image": None,  # set by the publisher once the photo is saved
    }


def tagline(cocktail):
    """The board's one-liner: the first sentence of the drink's description."""
    text = _text(cocktail.get("description"))  # snapshots from before _text existed
    return re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0] if text else ""


PANTRY = {"water", "sugar", "simple syrup", "club soda", "soda water", "ice"}


def key_ingredients(cocktail, limit=3):
    """The board's ingredient line: spirits first, so the bourbon isn't lost
    behind sugar, and pantry staples left out."""
    names, seen = [], set()
    required = [
        i
        for i in cocktail["ingredients"]
        if not i["optional"] and i["name"] and i["name"].lower() not in PANTRY
    ]
    for i in sorted(required, key=lambda i: -(i.get("strength") or 0)):
        if i["name"].lower() not in seen:
            seen.add(i["name"].lower())
            names.append(i["name"])
    return names[:limit]


# Checklist status, worst first: a row takes the worst of its lines.
MISSING, PROBABLY, ON_SHELF = "missing", "probably", "on_shelf"
_RANK = {MISSING: 0, PROBABLY: 1, ON_SHELF: 2}


def _shelf_status(line):
    """(status, via) for one recipe line, by Bar Assistant's own shelf matching."""
    if line.get("in_bar_shelf"):
        return ON_SHELF, ""
    if line.get("in_bar_shelf_as_variant"):
        names = [v.get("name") for v in line.get("variants_in_shelf") or []]
        names = [n for n in names if n]
        return (
            PROBABLY,
            f"you have {', '.join(names)}" if names else "you have a variant",
        )
    if line.get("in_bar_shelf_as_substitute"):
        names = [
            _named(s.get("ingredient"))
            for s in line.get("substitutes") or []
            if s.get("in_bar_shelf")
        ]
        names = [n for n in names if n]
        return PROBABLY, f"substitute: {', '.join(names)}" if names else "a substitute"
    if line.get("in_bar_shelf_as_complex_ingredient"):
        return PROBABLY, "can be made from what's on the shelf"
    return MISSING, ""


# Batch rule: BA has no servings field, so a drink is a batch when it is
# tagged as one, any line is measured in a bulk unit, or its liquids come to
# more than BATCH_ML. A bottle isn't bulk: "1 bottle" of beer is one drink.
BATCH_ML = 500
BATCH_TAGS = ("batch", "punch")
BULK_UNITS = {"quart", "quarts", "gallon", "gallons", "pitcher", "pitchers"}
LIQUID_ML = {
    "ml": 1,
    "cl": 10,
    "dl": 100,
    "oz": 30,
    "fl oz": 30,
    "ounce": 30,
    "ounces": 30,
    "cup": 240,
    "cups": 240,
    "tbsp": 15,
    "tsp": 5,
    "shot": 45,
    "shots": 45,
    "l": 1000,
    "liter": 1000,
    "liters": 1000,
    "litre": 1000,
    "litres": 1000,
}
_ICE = re.compile(r"\bice\b", re.IGNORECASE)


def is_batch(cocktail):
    """True when the recipe makes a batch (a punch, a pitcher), not one drink."""
    tags = [_named(t).lower() for t in cocktail.get("tags") or []]
    if any(word in t for t in tags for word in BATCH_TAGS):
        return True
    total = 0
    for line in cocktail.get("ingredients") or []:
        unit = (line.get("units") or "").strip().lower()
        if unit in BULK_UNITS:
            return True
        if _ICE.search(_named(line.get("ingredient")) or line.get("name") or ""):
            continue  # crushed ice fills the glass but isn't a drink's volume
        try:
            total += float(line.get("amount") or 0) * LIQUID_ML.get(unit, 0)
        except (TypeError, ValueError):
            pass
    return total > BATCH_ML


def ingredient_checklist(cocktails):
    """One row per ingredient across the cocktails (BA detail responses):
    {id, name, drinks, uses, optional, status, via}. uses has one entry per
    recipe line, {drink, amount, amount_max, units, optional, batch}, as the
    recipe gives it (never summed). Optional only if every line using it is;
    status is the worst across its lines. Missing, then probably, then on the
    shelf; alphabetical within each."""
    rows = {}
    for c in cocktails:
        batch = is_batch(c)
        for line in c.get("ingredients") or []:
            ing = line.get("ingredient") or {}
            iid = ing.get("id")
            if iid is None:
                continue
            row = rows.setdefault(
                iid,
                {
                    "id": iid,
                    "name": _text(ing.get("name") or line.get("name")),
                    "drinks": [],
                    "uses": [],
                    "optional": True,
                    "status": ON_SHELF,
                    "via": [],
                },
            )
            name = _text(c.get("name"))
            if name not in row["drinks"]:
                row["drinks"].append(name)
            row["uses"].append(
                {
                    "drink": name,
                    "amount": line.get("amount"),
                    "amount_max": line.get("amount_max"),
                    "units": (line.get("units") or "").strip(),
                    "optional": bool(line.get("optional")),
                    "batch": batch,
                }
            )
            row["optional"] = row["optional"] and bool(line.get("optional"))
            status, via = _shelf_status(line)
            if _RANK[status] < _RANK[row["status"]]:
                row["status"] = status
            if via and via not in row["via"]:
                row["via"].append(via)
    out = []
    for row in rows.values():
        # The via text explains a "probably"; it would mislead on the others.
        via = "; ".join(row["via"]) if row["status"] == PROBABLY else ""
        out.append({**row, "via": via})
    return sorted(out, key=lambda r: (_RANK[r["status"]], r["name"].lower()))


PER_PAGE = 6  # drinks on one board screen; a longer menu pages through screens

# Board tiles on a 6-column x 2-row grid, by how many drinks a screen shows:
# (grid columns, grid rows, text side l/c/r, text edge t/b, size). The title
# badge sits at the centre of the screen, where the tiles meet, so each
# drink's text keeps to its tile's outer edge.
LAYOUTS = {
    1: [("1/7", "1/3", "l", "b", "hero")],
    2: [("1/4", "1/3", "l", "b", "hero"), ("4/7", "1/3", "r", "b", "hero")],
    3: [
        ("1/4", "1/3", "l", "b", "hero"),
        ("4/7", "1/2", "r", "t", "wide"),
        ("4/7", "2/3", "r", "b", "wide"),
    ],
    4: [
        ("1/4", "1/2", "l", "t", "wide"),
        ("4/7", "1/2", "r", "t", "wide"),
        ("1/4", "2/3", "l", "b", "wide"),
        ("4/7", "2/3", "r", "b", "wide"),
    ],
    5: [
        ("1/3", "1/2", "l", "t", "narrow"),
        ("3/5", "1/2", "c", "t", "narrow"),
        ("5/7", "1/2", "r", "t", "narrow"),
        ("1/4", "2/3", "l", "b", "wide"),
        ("4/7", "2/3", "r", "b", "wide"),
    ],
    6: [
        ("1/3", "1/2", "l", "t", "narrow"),
        ("3/5", "1/2", "c", "t", "narrow"),
        ("5/7", "1/2", "r", "t", "narrow"),
        ("1/3", "2/3", "l", "b", "narrow"),
        ("3/5", "2/3", "c", "b", "narrow"),
        ("5/7", "2/3", "r", "b", "narrow"),
    ],
}


def board_pages(cards):
    """Split the cards into evenly sized screens (7 drinks are 4 + 3, not
    6 + 1) and give each card its tile on that screen."""
    if not cards:
        return []
    size = math.ceil(len(cards) / math.ceil(len(cards) / PER_PAGE))
    pages = []
    for start in range(0, len(cards), size):
        group = cards[start : start + size]
        pages.append(
            [
                {**c, "tile": dict(zip(("cols", "rows", "h", "v", "size"), t))}
                for c, t in zip(group, LAYOUTS[len(group)])
            ]
        )
    return pages


def image_name(slug):
    return re.sub(r"[^a-z0-9-]", "-", slug.lower()) + ".jpg"


def image_version(content):
    """A short content hash for the photo URL, so a replaced photo is refetched."""
    return hashlib.sha256(content).hexdigest()[:12]


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


def load_list(directory):
    """The editable menu (title, subtitle, cocktail_ids), or None if never saved."""
    try:
        with open(os.path.join(directory, "list.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_list(directory, menu_list):
    """Write list.json atomically. save() only deletes *.jpg, so it is safe."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "list.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(menu_list, f)
    os.replace(tmp, path)


def find(snapshot, slug):
    for c in (snapshot or {}).get("cocktails", []):
        if c["slug"] == slug:
            return c
    return None


def qr_svg(url):
    # Dark modules on a white quiet zone, so phones read it on a dark board.
    # A 2-module border (not 4) leaves more of the box for the code itself.
    return segno.make(url, error="m").svg_inline(
        scale=4, border=2, dark="#111", light="#fff", omitsize=True
    )


PAGE_SECONDS_DEFAULT = 15
PAGE_SECONDS_MIN, PAGE_SECONDS_MAX = 3, 600


def page_seconds(raw):
    """How long the TV board shows each page before flipping."""
    try:
        return max(PAGE_SECONDS_MIN, min(PAGE_SECONDS_MAX, int(raw)))
    except (TypeError, ValueError):
        return PAGE_SECONDS_DEFAULT


def inset(raw):
    try:
        return max(0, min(INSET_MAX, int(raw)))
    except (TypeError, ValueError):
        return INSET_DEFAULT


# Board themes. line: one color or several (striped grid lines); shade: the
# "r,g,b" of the dark fade behind tile text; badge: [light, dark] of the title
# badge; scale evens out title faces of different widths; halo: a small emblem
# ringed around the badge, in halo_colors when given. Classic is the original
# look. tile (tile fallback gradient, defaults to badge) and ring (badge outer
# ring "r,g,b", defaults to shade) are optional, set only on Classic.
# MOTIFS are 24x24 paths: f filled, s stroked.
THEMES = {
    "classic": {
        "tile": ["#4a2414", "#1a0d07"],
        "ring": "26,13,7",
        "name": "Classic",
        "group": "generic",
        "line": ["#c9a24a"],
        "accent": "#e2bd6b",
        "shade": "10,6,4",
        "badge": ["#3b1f12", "#1a0d07"],
        "font": "Fraunces",
        "weight": 600,
        "scale": 1,
        "eyebrow": "The bar is open",
        "motif": "",
        "halo": "",
        "halo_colors": [],
        "glow": False,
    },
    "new-years-eve": {
        "name": "New Year's Eve",
        "group": "holiday",
        "line": ["#d4af37"],
        "accent": "#f3d98b",
        "shade": "6,6,12",
        "badge": ["#24243a", "#07070d"],
        "font": "Limelight",
        "weight": 400,
        "scale": 1,
        "eyebrow": "Cheers to the new year",
        "motif": "burst",
        "halo": "confetti",
        "halo_colors": ["#f3d98b", "#e9e9f2", "#d4af37", "#b9a6ff"],
        "glow": False,
    },
    "lunar-new-year": {
        "name": "Lunar New Year",
        "group": "holiday",
        "line": ["#d4242b"],
        "accent": "#f2c14e",
        "shade": "22,3,3",
        "badge": ["#a21c1c", "#470606"],
        "font": "Cinzel",
        "weight": 600,
        "scale": 0.9,
        "eyebrow": "Happy Lunar New Year",
        "motif": "lantern",
        "halo": "lantern",
        "halo_colors": [],
        "glow": False,
    },
    "valentines": {
        "name": "Valentine's Day",
        "group": "holiday",
        "line": ["#e05a7a"],
        "accent": "#ffb3c4",
        "shade": "24,4,11",
        "badge": ["#76183a", "#2a0612"],
        "font": "Dancing Script",
        "weight": 700,
        "scale": 1.15,
        "eyebrow": "Made with love",
        "motif": "heart",
        "halo": "heart",
        "halo_colors": [],
        "glow": False,
    },
    "mardi-gras": {
        "name": "Mardi Gras",
        "group": "holiday",
        "line": ["#6a2c91", "#1f8a3b", "#e0b43a"],
        "accent": "#e8c04a",
        "shade": "14,4,20",
        "badge": ["#40165f", "#140620"],
        "font": "Abril Fatface",
        "weight": 400,
        "scale": 1,
        "eyebrow": "Laissez les bons temps rouler",
        "motif": "mask",
        "halo": "confetti",
        "halo_colors": ["#a35bd6", "#2fb257", "#e8c04a"],
        "glow": False,
    },
    "st-patricks": {
        "name": "St. Patrick's Day",
        "group": "holiday",
        "line": ["#3f9b4f"],
        "accent": "#a8d98a",
        "shade": "3,13,6",
        "badge": ["#1f5030", "#081a0e"],
        "font": "Fraunces",
        "weight": 600,
        "scale": 1,
        "eyebrow": "Sláinte",
        "motif": "shamrock",
        "halo": "shamrock",
        "halo_colors": [],
        "glow": False,
    },
    "easter": {
        "name": "Easter",
        "group": "holiday",
        "line": ["#c9b6e4"],
        "accent": "#f6d98b",
        "shade": "24,17,34",
        "badge": ["#5e4c80", "#271d3c"],
        "font": "Fraunces",
        "weight": 600,
        "scale": 1,
        "eyebrow": "Happy Easter",
        "motif": "egg",
        "halo": "flower",
        "halo_colors": ["#f6d98b", "#f3b6cf", "#bfe3c0", "#c9b6e4"],
        "glow": False,
    },
    "fourth-of-july": {
        "name": "Fourth of July",
        "group": "holiday",
        "line": ["#c8323f", "#f2f2f2", "#3c4f9a"],
        "accent": "#ff9c9c",
        "shade": "6,8,22",
        "badge": ["#22306a", "#0a0f26"],
        "font": "Bebas Neue",
        "weight": 400,
        "scale": 1.25,
        "eyebrow": "Happy Fourth",
        "motif": "star",
        "halo": "star",
        "halo_colors": ["#ffffff", "#ff8a8a", "#9fb6ff"],
        "glow": False,
    },
    "halloween": {
        "name": "Halloween",
        "group": "holiday",
        "line": ["#ff7a1a"],
        "accent": "#ffa64d",
        "shade": "11,4,15",
        "badge": ["#30163f", "#0c0412"],
        "font": "Creepster",
        "weight": 400,
        "scale": 1.1,
        "eyebrow": "Trick or treat",
        "motif": "pumpkin",
        "halo": "bat",
        "halo_colors": [],
        "glow": False,
    },
    "thanksgiving": {
        "name": "Thanksgiving",
        "group": "holiday",
        "line": ["#c8762b"],
        "accent": "#e9b264",
        "shade": "17,8,2",
        "badge": ["#5c3012", "#200f04"],
        "font": "Fraunces",
        "weight": 600,
        "scale": 1,
        "eyebrow": "Give thanks",
        "motif": "wheat",
        "halo": "leaf",
        "halo_colors": ["#e9b264", "#c8562b", "#a8702f"],
        "glow": False,
    },
    "hanukkah": {
        "name": "Hanukkah",
        "group": "holiday",
        "line": ["#4a7fd4"],
        "accent": "#d6e2f7",
        "shade": "4,8,22",
        "badge": ["#21418a", "#081633"],
        "font": "Cinzel",
        "weight": 600,
        "scale": 0.9,
        "eyebrow": "Happy Hanukkah",
        "motif": "davidstar",
        "halo": "",
        "halo_colors": [],
        "glow": False,
    },
    "christmas": {
        "name": "Christmas",
        "group": "holiday",
        "line": ["#c0262d", "#f5efe6"],
        "accent": "#e8c26a",
        "shade": "6,14,8",
        "badge": ["#21512f", "#0a1d10"],
        "font": "Playfair Display",
        "weight": 600,
        "scale": 1,
        "eyebrow": "Merry and bright",
        "motif": "tree",
        "halo": "snowflake",
        "halo_colors": ["#ffffff", "#e8c26a"],
        "glow": False,
    },
    "game-day": {
        "name": "Game Day",
        "group": "holiday",
        "line": ["#2f8a3e"],
        "accent": "#ffcf3f",
        "shade": "6,10,6",
        "badge": ["#1f4224", "#08160b"],
        "font": "Bebas Neue",
        "weight": 400,
        "scale": 1.25,
        "eyebrow": "Kickoff",
        "motif": "football",
        "halo": "",
        "halo_colors": [],
        "glow": False,
    },
    "birthday": {
        "name": "Birthday",
        "group": "holiday",
        "line": ["#ff5fa2"],
        "accent": "#ffd34d",
        "shade": "15,6,24",
        "badge": ["#4b2280", "#170833"],
        "font": "Fredoka",
        "weight": 600,
        "scale": 1,
        "eyebrow": "Happy birthday",
        "motif": "balloon",
        "halo": "confetti",
        "halo_colors": ["#ff5fa2", "#ffd34d", "#5fd3ff", "#9dff8a"],
        "glow": False,
    },
    "wedding": {
        "name": "Wedding & Anniversary",
        "group": "holiday",
        "line": ["#e7dccb"],
        "accent": "#e9d3a8",
        "shade": "15,13,10",
        "badge": ["#433c33", "#16130f"],
        "font": "Cormorant Garamond",
        "weight": 600,
        "scale": 1.1,
        "eyebrow": "Here's to love",
        "motif": "rings",
        "halo": "",
        "halo_colors": [],
        "glow": False,
    },
    "winter": {
        "name": "Winter",
        "group": "generic",
        "line": ["#a9cbe6"],
        "accent": "#cfe6f7",
        "shade": "6,12,21",
        "badge": ["#264564", "#0b1726"],
        "font": "Fraunces",
        "weight": 600,
        "scale": 1,
        "eyebrow": "Warm up",
        "motif": "snowflake",
        "halo": "snowflake",
        "halo_colors": [],
        "glow": False,
    },
    "spring": {
        "name": "Spring",
        "group": "generic",
        "line": ["#9cc98a"],
        "accent": "#f3c6d8",
        "shade": "10,17,10",
        "badge": ["#41623a", "#152212"],
        "font": "Fraunces",
        "weight": 600,
        "scale": 1,
        "eyebrow": "In bloom",
        "motif": "flower",
        "halo": "flower",
        "halo_colors": [],
        "glow": False,
    },
    "summer": {
        "name": "Summer",
        "group": "generic",
        "line": ["#f0a03c"],
        "accent": "#ffd27a",
        "shade": "4,17,17",
        "badge": ["#106060", "#042424"],
        "font": "Pacifico",
        "weight": 400,
        "scale": 0.9,
        "eyebrow": "Island time",
        "motif": "pineapple",
        "halo": "sun",
        "halo_colors": [],
        "glow": False,
    },
    "autumn": {
        "name": "Autumn",
        "group": "generic",
        "line": ["#b5541e"],
        "accent": "#e6a15a",
        "shade": "17,6,2",
        "badge": ["#602612", "#220b03"],
        "font": "Fraunces",
        "weight": 600,
        "scale": 1,
        "eyebrow": "Harvest season",
        "motif": "leaf",
        "halo": "leaf",
        "halo_colors": ["#e6a15a", "#c0502a", "#d9b44a"],
        "glow": False,
    },
    "speakeasy": {
        "name": "Speakeasy",
        "group": "generic",
        "line": ["#b08d57"],
        "accent": "#d8bb83",
        "shade": "6,6,6",
        "badge": ["#1f1d1a", "#050505"],
        "font": "Poiret One",
        "weight": 400,
        "scale": 1.1,
        "eyebrow": "Password accepted",
        "motif": "fan",
        "halo": "",
        "halo_colors": [],
        "glow": False,
    },
    "neon": {
        "name": "Neon Night",
        "group": "generic",
        "line": ["#ff2e93"],
        "accent": "#3ef0ff",
        "shade": "9,2,17",
        "badge": ["#1d0b31", "#07020f"],
        "font": "Monoton",
        "weight": 400,
        "scale": 0.8,
        "eyebrow": "Open late",
        "motif": "martini",
        "halo": "",
        "halo_colors": [],
        "glow": True,
    },
}

MOTIFS = {
    "burst": {
        "f": "",
        "s": "M12 2v5M12 17v5M2 12h5M17 12h5M4.9 4.9l3.5 3.5M15.6 15.6l3.5 3.5M4.9 19.1l3.5-3.5M15.6 8.4l3.5-3.5",
        "rule": "",
    },
    "star": {
        "f": "M12 2l2.9 6.6 7.1.6-5.4 4.7 1.7 7-6.3-3.8-6.3 3.8 1.7-7L2 9.2l7.1-.6z",
        "s": "",
        "rule": "",
    },
    "heart": {
        "f": "M12 21s-7.5-4.6-9.5-9.2C1 8.1 3.4 4.5 7 4.5c2.1 0 3.6 1.1 5 3 1.4-1.9 2.9-3 5-3 3.6 0 6 3.6 4.5 7.3C19.5 16.4 12 21 12 21z",
        "s": "",
        "rule": "",
    },
    "shamrock": {
        "f": "M12 11.5C9 9.5 8.2 3 12 3s3 6.5 0 8.5zM11.5 12c-2 3-8.5 3.8-8.5 0s6.5-3 8.5 0zM12.5 12c2-3 8.5-3.8 8.5 0s-6.5 3-8.5 0z",
        "s": "M12 12c.5 4 2 7 4 10",
        "rule": "",
    },
    "lantern": {
        "f": "M8 4h8v2H8zM8 18h8v2H8zM12 5.5c4.4 0 7 2.9 7 6.5s-2.6 6.5-7 6.5S5 15.6 5 12s2.6-6.5 7-6.5z",
        "s": "M12 1v3M12 20v3",
        "rule": "",
    },
    "mask": {
        "f": "M2 9c3-2 7-2 10 0 3-2 7-2 10 0-.5 5-3.5 7-6 7-2 0-3-1.5-4-3-1 1.5-2 3-4 3-2.5 0-5.5-2-6-7zM5 11.3a2 1.4 0 1 0 4 0 2 1.4 0 1 0-4 0zM15 11.3a2 1.4 0 1 0 4 0 2 1.4 0 1 0-4 0z",
        "s": "",
        "rule": "evenodd",
    },
    "egg": {
        "f": "M12 2c4 0 7 6.5 7 11.5S16 22 12 22s-7-3.5-7-8.5S8 2 12 2z",
        "s": "",
        "rule": "",
    },
    "flower": {
        "f": "M12 9.5a3.2 3.2 0 1 1 0-6.4 3.2 3.2 0 0 1 0 6.4zM14.4 11.2a3.2 3.2 0 1 1 6.1-2 3.2 3.2 0 0 1-6.1 2zM13.5 14a3.2 3.2 0 1 1 3.8 5.2 3.2 3.2 0 0 1-3.8-5.2zM10.5 14a3.2 3.2 0 1 1-3.8 5.2 3.2 3.2 0 0 1 3.8-5.2zM9.6 11.2a3.2 3.2 0 1 1-6.1-2 3.2 3.2 0 0 1 6.1 2z",
        "s": "",
        "rule": "",
    },
    "pumpkin": {
        "f": "",
        "s": "M12 7c-5 0-9 2.8-9 7s4 7 9 7 9-2.8 9-7-4-7-9-7zM12 7c-2.5 0-4 3.1-4 7s1.5 7 4 7 4-3.1 4-7-1.5-7-4-7zM12 7c0-2 .8-3.5 2.5-4.5",
        "rule": "",
    },
    "bat": {
        "f": "M12 10c-1-1.5-1.2-3-1.2-3L10 9C8 7 4 6 1 8c2 .5 3 2 3 4 1.5-1 3.5-1 5 .5 1-.8 2-1.3 3-1.3s2 .5 3 1.3c1.5-1.5 3.5-1.5 5-.5 0-2 1-3.5 3-4-3-2-7-1-9 1l-.8-2s-.2 1.5-1.2 3z",
        "s": "",
        "rule": "",
    },
    "wheat": {
        "f": "",
        "s": "M12 22V6M12 8c-2-1-3-3-3-5 2 1 3 3 3 5zM12 8c2-1 3-3 3-5-2 1-3 3-3 5zM12 12c-2-1-3-3-3-5 2 1 3 3 3 5zM12 12c2-1 3-3 3-5-2 1-3 3-3 5zM12 16c-2-1-3-3-3-5 2 1 3 3 3 5zM12 16c2-1 3-3 3-5-2 1-3 3-3 5z",
        "rule": "",
    },
    "leaf": {"f": "M12 2C6 8 6 15 12 21c6-6 6-13 0-19z", "s": "M12 6v17", "rule": ""},
    "davidstar": {
        "f": "",
        "s": "M12 2.5l8.2 14.2H3.8zM12 21.5L3.8 7.3h16.4z",
        "rule": "",
    },
    "tree": {
        "f": "M12 1.5l5 6.5h-2.6l4.6 5.5h-3.4L21 19H3l5.4-5.5H5l4.6-5.5H7zM10.5 19h3v3.5h-3z",
        "s": "",
        "rule": "",
    },
    "snowflake": {
        "f": "",
        "s": "M12 2v20M3.3 7l17.4 10M3.3 17l17.4-10M9.5 3.5L12 6l2.5-2.5M9.5 20.5L12 18l2.5 2.5M3.5 10.5L6.5 9 5.9 5.7M20.5 13.5L17.5 15l.6 3.3M3.5 13.5L6.5 15l-.6 3.3M20.5 10.5L17.5 9l.6-3.3",
        "rule": "",
    },
    "football": {
        "f": "",
        "s": "M4 20C4 11 11 4 20 4c0 9-7 16-16 16zM9 15l6-6M10.5 10.5l3 3M8.5 12.5l3 3M12.5 8.5l3 3",
        "rule": "",
    },
    "balloon": {
        "f": "M12 2c3.9 0 7 3.1 7 7.2 0 4.4-3.6 8-7 8.8-3.4-.8-7-4.4-7-8.8C5 5.1 8.1 2 12 2zM10.8 17.6h2.4l.6 1.4h-3.6z",
        "s": "M12 19c-1 1.5 1 2.5 0 4",
        "rule": "",
    },
    "confetti": {"f": "M10 9h4v6h-4z", "s": "", "rule": ""},
    "rings": {
        "f": "",
        "s": "M9 9.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zM15 9.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zM12 2l2 2.5-2 2.5-2-2.5z",
        "rule": "",
    },
    "pineapple": {
        "f": "",
        "s": "M12 9c3 0 5 2.9 5 6.5S15 22 12 22s-5-2.9-5-6.5S9 9 12 9zM8 12l8 8M16 12l-8 8M12 9V2M12 9L8.5 3.5M12 9l3.5-5.5",
        "rule": "",
    },
    "fan": {
        "f": "",
        "s": "M3 19a9 9 0 0 1 18 0zM12 19L5 13.4M12 19l-3.5-8.1M12 19V10M12 19l3.5-8.1M12 19l7-5.6M8 19a4 4 0 0 1 8 0",
        "rule": "",
    },
    "martini": {
        "f": "M14.5 7.5a1.5 1.5 0 1 0 0 .01z",
        "s": "M3 4h18l-9 10zM12 14v7M8 21h8",
        "rule": "",
    },
    "sun": {
        "f": "M12 7a5 5 0 1 1 0 10 5 5 0 0 1 0-10z",
        "s": "M12 1.5v3M12 19.5v3M1.5 12h3M19.5 12h3M4.6 4.6l2.1 2.1M17.3 17.3l2.1 2.1M4.6 19.4l2.1-2.1M17.3 6.7l2.1-2.1",
        "rule": "",
    },
}


STRIPE_VH = 1.6


def _line_bg(line):
    if len(line) == 1:
        return line[0]
    stops = [
        f"{c} {i * STRIPE_VH:g}vh {(i + 1) * STRIPE_VH:g}vh" for i, c in enumerate(line)
    ]
    return f"repeating-linear-gradient(45deg, {', '.join(stops)})"


def font_url(font, weight):
    """Google Fonts CSS URL: the theme's title face, plus Fraunces (subtitle
    italic, tile initials) and DM Sans (body), which every board uses."""
    families = ["Fraunces:ital,wght@0,600;1,400"]
    if font != "Fraunces":
        families.append(f"{font.replace(' ', '+')}:wght@{weight}")
    families.append("DM+Sans:wght@400;700")
    return (
        "https://fonts.googleapis.com/css2?family="
        + "&family=".join(families)
        + "&display=swap"
    )


def _halo_spots(t):
    colors = t["halo_colors"] or [None]
    spots = []
    for k in range(8):
        a = k / 8 * math.pi * 2 + math.pi / 8
        rot = (k * 47) % 180 if t["halo"] == "confetti" else (-18 if k % 2 else 14)
        spots.append(
            {
                "cos": round(math.cos(a), 3),
                "sin": round(math.sin(a), 3),
                "rot": rot,
                "color": colors[k % len(colors)],
            }
        )
    return spots


def theme(theme_id):
    """The theme for an id, with its derived CSS values. An unknown, missing or
    removed id gives Classic, so an old snapshot never breaks the board."""
    tid = theme_id if isinstance(theme_id, str) and theme_id in THEMES else "classic"
    t = {"id": tid, **THEMES[tid]}
    t["line_bg"] = _line_bg(t["line"])
    t["font_url"] = font_url(t["font"], t["weight"])
    t["motif_paths"] = MOTIFS.get(t["motif"])
    t["halo_paths"] = MOTIFS.get(t["halo"])
    t["tile"] = t.get("tile") or t["badge"]
    t["ring"] = t.get("ring") or t["shade"]
    t["halo_spots"] = _halo_spots(t) if t["halo"] else []
    return t
