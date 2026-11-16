"""Suggest a holiday menu: Jev judges each drink, code picks the set.

Everything an owner might want to audit or tune lives here: the questions
sent to TypeSafe's Jev model, the thresholds that read its answers, and the
rules that turn those answers into a menu.

Per drink, one TypeSafe request with state {occasion, drink} asks:
  fit           Score  how well the drink's flavors suit the occasion
  batchable     Noul   can it be mixed ahead for a group
  approachable  Noul   would an occasional cocktail drinker enjoy it
  alcoholic     Noul   does it contain alcohol (companion for `base`)
  base          Choice which spirit it is built on (read only when alcoholic)

Code then decides (see pick()): drop drinks that clash with the occasion,
rank the rest, reserve a zero-proof and a batchable slot, and avoid repeating
a base spirit.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

import menu

log = logging.getLogger(__name__)

API_URL = "https://api.typesafe.ai/v1/systemone"
# Pinned, not jev-latest: the thresholds below were set against this version.
MODEL = "jev-1.14.0"
WORKERS = 6
RETRIES = 3

MENU_SIZE = 4
MAX_MISSING = 2  # drinks needing more than this many purchases are left out
MAX_POOL = 250  # cap on drinks judged per suggestion (fewest missing first)
ALTERNATES = 8

YES, NO = 0.7, 0.3  # Noul thresholds; between them is "not settled"
CLASH_MAX = 0.5  # P(out of place) above this drops a drink
BASE_SURE = 0.5  # base spirit counts for variety only when this sure
W_APPROACHABLE = 0.3
W_MISSING = 0.15

# ── Questions ─────────────────────────────────────────────────────────────────

QUESTIONS = {
    "fit": {
        "type": "score",
        "instructions": "How well do the flavors of `drink` suit `occasion`?",
        "criteria": [
            "Its flavors would feel out of place at the occasion, like a frozen tropical "
            "drink at a winter holiday dinner",
            "It would suit the occasion about as well as any other time of year",
            "Its flavors are strongly associated with the occasion's season or traditions",
        ],
    },
    "batchable": {
        "type": "noul",
        "instructions": "Could `drink` be mixed in a large batch before guests arrive "
        "and served from a pitcher or punch bowl?",
        "criteria": {
            "true": "It keeps well once mixed, like a punch, a sangria, or a stirred or "
            "built drink such as a Manhattan or an Old Fashioned",
            "false": "It has to be made one at a time, because it is shaken with egg "
            "white or cream, blended with ice, or set alight",
        },
    },
    "approachable": {
        "type": "noul",
        "instructions": "Would a guest who rarely drinks cocktails likely enjoy `drink`?",
        "criteria": {
            "true": "Familiar, balanced flavors, like a sour, a spritz, a punch or a highball",
            "false": "Very bitter, very strong or an acquired taste, like an amaro-heavy, "
            "absinthe-forward or spirit-only drink",
        },
    },
    "alcoholic": {
        "type": "noul",
        "instructions": "Does `drink` contain an alcoholic ingredient?",
        "criteria": {
            "true": "It includes a spirit, liqueur, wine, beer, cider or fortified wine",
            "false": "Every ingredient is non-alcoholic, like juices, syrups, sodas, tea "
            "or non-alcoholic spirits",
        },
    },
    "base": {
        "type": "choice",
        "instructions": "Which spirit is `drink` built on?",
        "criteria": {
            "whiskey": "Bourbon, rye, Scotch, Irish or another whiskey",
            "rum": "White, aged, dark or spiced rum, or cachaça",
            "gin": "Gin or genever",
            "vodka": "Vodka",
            "agave": "Tequila or mezcal",
            "brandy": "Cognac, Armagnac, applejack, Calvados, pisco or another brandy",
            "wine": "Wine, sparkling wine, fortified wine or vermouth as the main ingredient",
            "liqueur": "A liqueur or an amaro as the main ingredient",
        },
    },
}

# ── Occasion default (calendar math stays in code) ────────────────────────────


def _thanksgiving(year):
    nov1 = date(year, 11, 1)
    first_thu = nov1 + timedelta(days=(3 - nov1.weekday()) % 7)
    return first_thu + timedelta(weeks=3)


def default_occasion(today=None):
    """The next of these holidays within 45 days, else ''."""
    today = today or date.today()
    days = []
    for year in (today.year, today.year + 1):
        days += [
            (_thanksgiving(year), "Thanksgiving dinner"),
            (date(year, 12, 25), "Christmas"),
            (date(year, 12, 31), "New Year's Eve party"),
        ]
    upcoming = sorted(d for d in days if 0 <= (d[0] - today).days <= 45)
    return upcoming[0][1] if upcoming else ""


# ── Candidates (code) ─────────────────────────────────────────────────────────


def missing_ingredients(cocktail, shelf_ids):
    """Required ingredients not on hand, by the same rule as the app's shelf
    dots: in the bar's ingredient list, or flagged in_bar_shelf."""
    out = []
    for i in cocktail.get("ingredients") or []:
        if i.get("optional"):
            continue
        ing = i.get("ingredient") or {}
        if (
            ing.get("id") in shelf_ids
            or ing.get("in_bar_shelf")
            or i.get("in_bar_shelf")
        ):
            continue
        out.append(
            {"id": ing.get("id"), "name": ing.get("name") or i.get("name") or ""}
        )
    return out


def candidates(cocktails, shelf_ids):
    """Drinks at most MAX_MISSING purchases away, fewest missing first."""
    pool = []
    for c in cocktails:
        if not c.get("ingredients"):
            continue
        missing = missing_ingredients(c, shelf_ids)
        if len(missing) <= MAX_MISSING:
            pool.append((c, missing))
    pool.sort(key=lambda p: (len(p[1]), p[0].get("name") or ""))
    return pool


def drink_state(c):
    """What a person would look at to judge the drink: no ids, no ratings."""
    slim = menu.slim_cocktail(c)
    return {
        "name": slim["name"],
        "ingredients": [
            " ".join(x for x in (i["amount"], i["name"]) if x)
            + (" (optional)" if i["optional"] else "")
            for i in slim["ingredients"]
        ],
        "method": slim["method"] or None,
        "glass": slim["glass"] or None,
        "description": slim["description"][:400] or None,
    }


# ── Asking Jev ────────────────────────────────────────────────────────────────


class SuggestError(Exception):
    pass


def _ask(api_key, payload):
    """One System One call. Failures raise; they are never read as answers."""
    for attempt in range(RETRIES):
        log.debug("TypeSafe request: %s", payload)
        try:
            r = requests.post(
                API_URL,
                json=payload,
                timeout=30,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        except requests.RequestException as e:
            raise SuggestError(f"Couldn't reach TypeSafe: {e}") from e
        if r.status_code == 429 and attempt < RETRIES - 1:
            time.sleep(min(float(r.headers.get("retry-after") or 2**attempt), 10))
            continue
        if r.status_code in (401, 403):
            raise SuggestError("TypeSafe rejected the API key")
        if not r.ok:
            raise SuggestError(f"TypeSafe error {r.status_code}: {r.text[:200]}")
        log.debug("TypeSafe answer: %s", r.text)
        return r.json()["answers"]
    raise SuggestError("TypeSafe is rate limiting; try again in a minute")


def judge(api_key, occasion, pool):
    """{cocktail id: answers} for every drink in pool, or SuggestError."""

    def one(c):
        payload = {
            "model": MODEL,
            "state": {"occasion": occasion, "drink": drink_state(c)},
            "questions": QUESTIONS,
        }
        return c["id"], _ask(api_key, payload)

    with ThreadPoolExecutor(WORKERS) as ex:
        return dict(ex.map(one, [c for c, _ in pool]))


# ── Deciding (code) ───────────────────────────────────────────────────────────


def assess(c, missing, a):
    """Turn one drink's answers into the facts pick() decides on."""
    fit = {int(k): v for k, v in a["fit"]["probabilities"].items()}
    clash, strong = fit.get(0, 0.0), fit.get(2, 0.0)
    abv = c.get("abv")
    alcohol = a["alcoholic"]["noul"]
    alcoholic = bool(abv) or alcohol > YES
    zero_proof = not abv and alcohol < NO
    base = None
    if alcoholic:
        top = max(a["base"]["probabilities"].items(), key=lambda kv: kv[1])
        base = top[0] if top[1] >= BASE_SURE else None
    batchable = a["batchable"]["noul"] > YES
    approachable = a["approachable"]["noul"]
    tags = []
    if strong > 0.5:
        tags.append("Seasonal")
    if batchable:
        tags.append("Batchable")
    if zero_proof:
        tags.append("Zero-proof")
    if approachable > YES:
        tags.append("Easy-drinking")
    return {
        "id": c["id"],
        "name": c.get("name") or "",
        "missing": missing,
        "tags": tags,
        "base": base,
        "clash": clash > CLASH_MAX,
        "fit": strong - clash,
        "zero_proof": zero_proof,
        "batchable": batchable,
        "value": strong
        - clash
        + W_APPROACHABLE * approachable
        - W_MISSING * len(missing),
    }


def pick(assessed, size=MENU_SIZE):
    """Choose the menu. Returns (picks, alternates, unfilled notes).

    1. Drop drinks that clash with the occasion.
    2. Reserve a slot for the best zero-proof drink that fits at least as well
       as any other time of year, and one for the best batchable drink.
    3. Fill the rest by value without repeating a base spirit.
    4. If variety runs out, fill by value anyway.
    """
    ranked = sorted((d for d in assessed if not d["clash"]), key=lambda d: -d["value"])
    picks, unfilled = [], []

    def take(d, role=None):
        picks.append({**d, "role": role})
        ranked.remove(d)

    zero = next((d for d in ranked if d["zero_proof"] and d["fit"] >= 0), None)
    if zero:
        take(zero, "zero_proof")
    else:
        unfilled.append("No zero-proof drink suits the occasion")
    batch = next((d for d in ranked if d["batchable"]), None)
    if batch and len(picks) < size:
        take(batch, "batchable")
    elif not batch:
        unfilled.append("No drink can be batched ahead")
    for d in list(ranked):
        if len(picks) >= size:
            break
        bases = {p["base"] for p in picks if p["base"]}
        if d["base"] is None or d["base"] not in bases:
            take(d)
    for d in list(ranked):
        if len(picks) >= size:
            break
        take(d)
    if len(picks) < size:
        unfilled.append(f"Only {len(picks)} drinks fit; buy more or widen the shelf")
    return picks, ranked[:ALTERNATES], unfilled


def suggest(api_key, occasion, cocktails, shelf_ids):
    pool = candidates(cocktails, shelf_ids)
    considered = pool[:MAX_POOL]
    answers = judge(api_key, occasion, considered) if considered else {}
    assessed = [assess(c, missing, answers[c["id"]]) for c, missing in considered]
    picks, alternates, unfilled = pick(assessed)
    return {
        "occasion": occasion,
        "considered": len(considered),
        "total": len(cocktails),
        "picks": picks,
        "alternates": alternates,
        "unfilled": unfilled,
    }
