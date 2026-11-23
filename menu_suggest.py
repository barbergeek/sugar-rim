"""Suggest a holiday menu: a model judges each drink, code picks the set.

Everything an owner might want to audit or tune lives here: the questions
sent to TypeSafe's Jev model, the thresholds that read its answers, and the
rules that turn those answers into a menu.

Per drink, one TypeSafe request with state {occasion, drink} asks:
  fit           Score  how well the drink's flavors suit the occasion
  batchable     Noul   can it be mixed ahead for a group
  approachable  Noul   would an occasional cocktail drinker enjoy it
  alcoholic     Noul   does it contain alcohol (companion for `base`)
  base          Choice which spirit it is built on (read only when alcoholic)

Without a TypeSafe key, the same questions go to the chat model configured
for AI images (OpenAI, Gemini or OpenAI-compatible); see judge_llm().

Code then decides (see pick()): drop drinks that clash with the occasion,
rank the rest, reserve a zero-proof and a batchable slot, and avoid repeating
a base spirit.
"""

import json
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import requests

import menu

log = logging.getLogger(__name__)

API_URL = "https://api.typesafe.ai/v1/systemone"
# Pinned, not jev-latest: the thresholds below were set against this version.
MODEL = "jev-1.14.0"
WORKERS = 6
RETRIES = 3
DEADLINE = 60  # seconds for a whole suggestion; Cloudflare gives up near 100

MENU_SIZE = 4
MAX_MISSING = 2  # drinks needing more than this many purchases are left out

YES, NO = 0.7, 0.3  # Noul thresholds; between them is "not settled"
CLASH_MAX = 0.5  # P(out of place) above this drops a drink
BASE_SURE = 0.5  # base spirit counts for variety only when this sure
# Score: fit on a -5..10 scale (10 made for the occasion, 5 suits it like any
# other time of year, below 0 out of place), less these deductions.
W_HARD = 2.0  # most an acquired taste loses (scaled by how unlikely a novice enjoys it)
W_MISSING = 1.0  # per ingredient to buy

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
    """Drinks at most MAX_MISSING purchases away, newest first: recent additions
    are the likeliest to be meant for the occasion, so they're judged (and
    shown) first. Every one is judged; there is no cap."""
    pool = []
    for c in cocktails:
        if not c.get("ingredients"):
            continue
        missing = missing_ingredients(c, shelf_ids)
        if len(missing) <= MAX_MISSING:
            pool.append((c, missing))
    pool.sort(
        key=lambda p: (p[0].get("created_at") or "", p[0].get("id") or 0), reverse=True
    )
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
                timeout=15,
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


def judge(api_key, occasion, pool, on_answers=None):
    """{cocktail id: answers} for every drink in pool, or SuggestError."""

    def one(c):
        payload = {
            "model": MODEL,
            "state": {"occasion": occasion, "drink": drink_state(c)},
            "questions": QUESTIONS,
        }
        return {c["id"]: _ask(api_key, payload)}

    return _parallel(
        [lambda c=c: one(c) for c, _ in pool], WORKERS, DEADLINE, "TypeSafe", on_answers
    )


def _parallel(jobs, workers, deadline, who, on_answers=None):
    """Run jobs (each returns {id: answers}) and merge them, handing each job's
    answers to on_answers as it lands. Stop at the first failure (including one
    raised by on_answers) or the deadline and drop what's still queued, so a
    stuck API can't hold a web worker (the same one serving the TV board)."""
    ex = ThreadPoolExecutor(workers)
    futures = [ex.submit(job) for job in jobs]
    out = {}
    try:
        for f in as_completed(futures, timeout=deadline):
            got = f.result()
            out.update(got)
            if on_answers:
                on_answers(got)
        return out
    except TimeoutError as e:
        raise SuggestError(f"{who} took too long; try again in a minute") from e
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


# ── Asking a chat model instead (OpenAI, Gemini or OpenAI-compatible) ────────
# Used when there's no TypeSafe key but Settings → AI Images has a provider.
# The same QUESTIONS are put to the model, several drinks per request, and its
# answers are turned into the shape assess() reads, so pick() is unchanged.

LLM_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}
LLM_DEFAULT_MODELS = {"openai": "gpt-5.4-mini", "gemini": "gemini-2.5-flash"}
LLM_BATCH = 20  # drinks per request
LLM_WORKERS = 8
LLM_DEADLINE = 85  # chat models are slower; Cloudflare gives up near 100 s
LLM_SURE, LLM_UNSURE = 0.9, 0.1  # a yes/no answer read as a probability


def llm_prompt():
    """System prompt spelling out QUESTIONS, so both engines ask the same things."""
    fit, base = QUESTIONS["fit"], QUESTIONS["base"]
    lines = [
        "You judge cocktails for a holiday drinks menu. `occasion` names the "
        "occasion; answer every question below for each drink in `drinks`.",
        "",
        f"fit: {fit['instructions']} Rate it from 0 to 10:",
        *(f"  {n}: {level}" for n, level in zip((0, 5, 10), fit["criteria"])),
        "approachable: "
        + QUESTIONS["approachable"]["instructions"]
        + " Rate it from 0 to 10:",
        f"  0: {QUESTIONS['approachable']['criteria']['false']}",
        f"  10: {QUESTIONS['approachable']['criteria']['true']}",
        "Use the whole 0-10 scale for fit and approachable, so the drinks that suit "
        "best stand apart from those that merely suit.",
    ]
    for key in ("batchable", "alcoholic"):
        q = QUESTIONS[key]
        lines += [
            f"{key}: {q['instructions']} Answer true or false.",
            f"  true: {q['criteria']['true']}",
            f"  false: {q['criteria']['false']}",
        ]
    lines += [f"base: {base['instructions']} Answer one of:"]
    lines += [f"  {k}: {v}" for k, v in base["criteria"].items()]
    lines += [
        "  none: the drink has no alcohol",
        "",
        'Reply with JSON only: {"drinks": [{"id": <id>, "fit": 0-10, '
        '"approachable": 0-10, "batchable": bool, "alcoholic": bool, '
        '"base": "<option>"}]}, one entry for every drink.',
    ]
    return "\n".join(lines)


def _rating(v):
    """A 0-10 rating, or None (a bool is not a rating)."""
    ok = isinstance(v, int | float) and not isinstance(v, bool) and 0 <= v <= 10
    return v if ok else None


def llm_answers(d):
    """One model reply for a drink → the answers shape TypeSafe returns.

    The 0-10 ratings keep scores apart: 5 is "suits it like any other time of
    year", so below 5 is the chance it clashes and above 5 the chance it's
    strongly tied to the occasion."""
    fit, easy = _rating(d.get("fit")), _rating(d.get("approachable"))
    flags = [d.get(k) for k in ("batchable", "alcoholic")]
    options = list(QUESTIONS["base"]["criteria"])
    base = d.get("base")
    if fit is None or easy is None or not all(isinstance(f, bool) for f in flags):
        raise ValueError(f"unusable answer: {d}")
    if base not in options:
        base = None  # "none", or something off-list: no base for variety

    def noul(v):
        return {"type": "noul", "noul": LLM_SURE if v else LLM_UNSURE}

    clash, strong = max(0, 5 - fit) / 5, max(0, fit - 5) / 5
    other = (1 - LLM_SURE) / (len(options) - 1)
    return {
        "fit": {
            "type": "score",
            "probabilities": {"0": clash, "1": 1 - clash - strong, "2": strong},
        },
        "batchable": noul(flags[0]),
        "approachable": {"type": "noul", "noul": easy / 10},
        "alcoholic": noul(flags[1]),
        "base": {
            "type": "choice",
            "probabilities": {
                k: (LLM_SURE if k == base else (other if base else 1 / len(options)))
                for k in options
            },
        },
    }


def _ask_llm(llm, occasion, drinks):
    """One chat request for a batch; retried once if the reply is unusable."""
    body = {
        "model": llm["model"],
        "messages": [
            {"role": "system", "content": llm_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "occasion": occasion,
                        "drinks": [{"id": c["id"], **drink_state(c)} for c in drinks],
                    }
                ),
            },
        ],
        "response_format": {"type": "json_object"},
    }
    if llm["model"].startswith(("gpt-5", "o3", "o4")):
        body["reasoning_effort"] = "low"  # a quick judgment, not a long think
    url = llm["base_url"].rstrip("/") + "/chat/completions"
    want = {c["id"] for c in drinks}
    for attempt in range(2):
        log.debug("LLM request: %s", body)
        try:
            r = requests.post(
                url,
                json=body,
                timeout=LLM_DEADLINE,
                headers={"Authorization": f"Bearer {llm['api_key']}"},
            )
        except requests.RequestException as e:
            raise SuggestError(f"Couldn't reach {llm['label']}: {e}") from e
        if r.status_code in (401, 403):
            raise SuggestError(f"{llm['label']} rejected the API key")
        if not r.ok:
            raise SuggestError(f"{llm['label']} error {r.status_code}: {r.text[:200]}")
        log.debug("LLM answer: %s", r.text)
        try:
            reply = json.loads(r.json()["choices"][0]["message"]["content"])
            got = {
                d["id"]: llm_answers(d) for d in reply["drinks"] if d.get("id") in want
            }
            if set(got) == want:
                return got
        except (KeyError, IndexError, TypeError, ValueError) as e:
            log.debug("Unusable LLM reply: %s", e)
    raise SuggestError(f"{llm['label']} didn't answer for every drink; try again")


def judge_llm(llm, occasion, pool, on_answers=None):
    drinks = [c for c, _ in pool]
    batches = [drinks[i : i + LLM_BATCH] for i in range(0, len(drinks), LLM_BATCH)]
    jobs = [lambda b=b: _ask_llm(llm, occasion, b) for b in batches]
    return _parallel(jobs, LLM_WORKERS, LLM_DEADLINE, llm["label"], on_answers)


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
        # Expected fit, weighting the levels 10 / 5 / -5, so a drink sure to
        # clash scores -5 and one sure to be made for the occasion scores 10.
        "value": round(
            10 * strong
            + 5 * (1 - strong - clash)
            - 5 * clash
            - W_HARD * (1 - approachable)
            - W_MISSING * len(missing),
            1,
        ),
    }


def pick(assessed, size=MENU_SIZE):
    """Choose the menu. Returns (picks, alternates, unfilled notes).

    1. Never pick drinks that clash with the occasion.
    2. Reserve a slot for the best zero-proof drink that fits at least as well
       as any other time of year, and one for the best batchable drink.
    3. Fill the rest by score without repeating a base spirit.
    4. If variety runs out, fill by score anyway.

    Each pick's role says why it's there when a higher score was passed over:
    "zero_proof", "batchable" or "variety" (a spirit not yet on the menu);
    None when it simply scored best. Alternates are everything else, clashing
    drinks included, best score first.
    """
    by_score = sorted(assessed, key=lambda d: -d["value"])
    ranked = [d for d in by_score if not d["clash"]]
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
            passed_over = ranked and ranked[0]["value"] > d["value"]
            take(d, "variety" if passed_over else None)
    for d in list(ranked):
        if len(picks) >= size:
            break
        take(d)
    if len(picks) < size:
        unfilled.append(f"Only {len(picks)} drinks fit; buy more or widen the shelf")
    taken = {p["id"] for p in picks}
    return picks, [d for d in by_score if d["id"] not in taken], unfilled


def suggest_stream(judge_fn, occasion, cocktails, shelf_ids):
    """Yield events while the drinks are judged: "start" (how many will be),
    "judged" for each batch of answers (those drinks assessed, plus the menu
    picked so far), then "done" (the suggestion). judge_fn(occasion, pool,
    on_answers) is TypeSafe or a chat model. Closing the generator stops any
    further questions; a failure raises SuggestError."""
    pool = candidates(cocktails, shelf_ids)
    considered = pool
    by_id = {c["id"]: (c, missing) for c, missing in considered}
    head = {
        "occasion": occasion,
        "considered": len(considered),
        "total": len(cocktails),
    }
    yield {"type": "start", **head}
    events = queue.Queue()
    stop = threading.Event()

    def on_answers(got):
        if stop.is_set():
            raise SuggestError("Cancelled")  # ends _parallel, dropping queued calls
        events.put(("answers", got))

    def run():
        try:
            judge_fn(occasion, considered, on_answers)
            events.put(("end", None))
        except Exception as e:  # handed to the generator, which re-raises it
            events.put(("error", e))

    if considered:
        threading.Thread(target=run, daemon=True).start()
    else:
        events.put(("end", None))
    assessed = []
    try:
        while True:
            kind, val = events.get()
            if kind == "error":
                raise val
            if kind == "end":
                break
            new = [assess(*by_id[i], a) for i, a in val.items() if i in by_id]
            assessed += new
            picks, _, _ = pick(assessed)
            yield {
                "type": "judged",
                "judged": len(assessed),
                "drinks": new,
                "picks": [{"id": p["id"], "role": p["role"]} for p in picks],
            }
    finally:
        stop.set()
    picks, alternates, unfilled = pick(assessed)
    yield {
        "type": "done",
        **head,
        "picks": picks,
        "alternates": alternates,
        "unfilled": unfilled,
    }


def suggest(judge_fn, occasion, cocktails, shelf_ids):
    """The finished suggestion, without the progress events."""
    *_, done = suggest_stream(judge_fn, occasion, cocktails, shelf_ids)
    return {k: v for k, v in done.items() if k != "type"}
