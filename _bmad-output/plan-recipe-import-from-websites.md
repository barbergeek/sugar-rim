---
title: 'Recipe import backend: pluggable website scrapers and import API'
type: 'feature'
ticket: ''
created: '2026-10-31'
status: 'built'
baseline_revision: '9cea94ca85f134084eb63def51d9a80c11efb827'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** sugar-rim has no recipe import. Bar Assistant's (BA) scraper covers only 15 sites. Its generic parser drops ingredient lines that have no unit, and it misreads pages like Food Network's (`https://www.foodnetwork.com/recipes/geoffrey-zakarian/gobble-gobble-punch-4536808`: list-valued author, lines like "One 750-milliliter bottle bourbon").

**Approach:** Add a Python `scrapers/` package with a registry of scraper classes, tried in order: site-specific scrapers, then generic JSON-LD. Each scraper returns a BA schema-v4 draft. Expose two Flask routes: one turns a URL or pasted HTML into a draft, the other saves a draft. Adding a site means adding one module with one class.

**Decisions:**
- Saving goes through BA `POST /api/import/cocktail`, which matches or creates ingredients and downloads images.
- When sugar-rim's own fetch is blocked (403/429 or robots.txt), fall back to BA `POST /api/import/scrape` with `{source: url}`. BA then fetches with its own identity and robots.txt check.
- When the local scrapers find no recipe in HTML we already have, fall back to BA scrape with `html_content`.
- The UI is deferred (see `deferred-work.md`). This plan ships the backend only.

## Boundaries & Constraints

**Always:**
- sugar-rim's fetch uses an honest User-Agent `sugar-rim/<version>` and honors robots.txt.
- Every fetch, and every redirect hop, passes `_is_public_http_url`.
- Fetches have a 15s timeout and a 5 MB body cap.
- Both routes require `_logged_in()`.
- Scrapers are pure: they take `(url, soup)` and return a draft or None, with no network I/O.

**Never:**
- No spoofed User-Agents or other bot-check circumvention.
- No headless browser.
- No frontend changes in this plan.
- No changes to existing routes.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Food Network fixture | Gobble Gobble Punch HTML + its URL | `scraper: "foodnetwork"`; name, author "Geoffrey Zakarian", 7 ingredients, instructions, 1 image, garnish "orange slices and freshly ground nutmeg" | — |
| Line parsing | "One 750-milliliter bottle bourbon, such as Four Roses" | 750 / "ml" / "Bourbon" / note "such as Four Roses" | — |
| Line parsing | "Half of a 750-milliliter bottle allspice dram, such as St. Elizabeth's" | 375 / "ml" / "Allspice dram" | — |
| Line parsing | "1/4 cup agave nectar ", "1 1/2 oz gin", "½ oz lime juice", "2-3 dashes bitters" | 0.25 cup; 1.5 oz; 0.5 oz; 2 (max 3) dash | — |
| Unitless line | "2 navel oranges, sliced" | 2 / null / "Navel oranges" / note "sliced" (kept, not dropped) | — |
| Unparseable line | "Ice" | null / null / "Ice" | — |
| Fetch blocked | Our fetch gets 403/429 or robots.txt disallows | BA scrape result returned, `scraper: "bar-assistant"` | If BA also fails: 422 with an error suggesting paste-HTML |
| No local recipe | HTML has no JSON-LD Recipe | BA scrape with `html_content` | If BA fails: 422 "No recipe found on this page" |
| SSRF | URL or a redirect that resolves to a private IP | 400 "URL not allowed" | No BA fallback |
| Logged out | Either route | 401 | — |

</frozen-after-approval>

## Code Map

- `app.py:40` `_logged_in()`.
- `app.py:48-69` `_is_public_http_url()`: reuse it per redirect hop.
- `app.py:106` `ba_headers()` and `app.py:127` `ba_url()`: use them for the BA calls.
- `app.py:134-147` `proxy()`: it turns non-JSON bodies into `{"error": text}`. Import-cocktail needs a direct `http.post` so it can read `Location`.
- `app.py:471-503` `/api/images/from-url`: style reference for a guarded fetch route. Don't modify it.
- `requests` is imported as `http`. App version: check `package.json` or the bump commit for the version string used in the UA.
- BA `POST /api/import/scrape` `{source, html_content?}` → `{data: {schema_version, schema, scraper_meta}}`. Failure returns 400.
- BA `POST /api/import/cocktail` `{source: <schema obj>, duplicate_actions: "none"}` → 201 + `Location: …/cocktails/<id>`.
- Schema v4 fields: name, instructions, description, source, garnish, glass, method, tags[], images[{uri, copyright}], author, ingredients[{name, amount, amount_max, units, note, optional, sort}].
- FN JSON-LD reference copy: `/tmp/claude-1000/-home-scott-develop-sugar-rim/621d0fa9-b217-488e-9eab-c22021ffe4ec/scratchpad/research/fn3.html`. Trim it to the Recipe `ld+json` script for the fixture.
- There is no test suite. CI only builds Docker. There is no ruff config (use the defaults).

## Tasks & Acceptance

**Execution:**
- [ ] `scrapers/base.py` -- `Scraper` base class with `name`, `domains`, `matches(url)`, and `scrape(url, soup) -> dict|None`, plus `make_draft(**fields)` that fills schema-v4 defaults.
- [ ] `scrapers/__init__.py` -- registry: a `register` decorator, `scrape(url, html) -> (draft, name)` (site matches first, generic last; parses the soup once), and `NoRecipeFound`. Imports the site modules so they self-register.
- [ ] `scrapers/ingredients.py` -- `parse_line(text)` per the matrix: ints, decimals, mixed and unicode fractions, ranges, word numbers ("one".."twelve", "a/an", "half of a"), `<n> <size>-<unit> bottle` multiplication, unit aliases normalized (oz, ml, cl, cup, tbsp, tsp, dash, drop, barspoon, part, splash), the first comma clause becomes the note, and the name is capitalized.
- [ ] `scrapers/jsonld.py` -- `JsonLdScraper`: `@graph` and list `@type`; author as str/dict/list; image as str/dict/list (take the first); instructions from str/HowToStep/HowToSection (numbered when >1); tags from recipeCategory+keywords (deduped, "beverage" dropped). Provides hooks `clean_ingredient_line(line)` and `post_process(draft, data)`.
- [ ] `scrapers/foodnetwork.py` -- `FoodNetworkScraper(JsonLdScraper)` for `foodnetwork.com`. `post_process` pulls the "Garnish with …" sentence into `garnish`. This is the documented example for new sites.
- [ ] `scrapers/fetch.py` -- `fetch_html(url, is_allowed)`: manual redirects (max 5, each re-checked), `urllib.robotparser`, streamed body capped at 5 MB, honest UA. Raises `UrlNotAllowed`, `FetchBlocked` (403/429 or robots), `FetchError`.
- [ ] `app.py` -- `POST /api/import/scrape` `{url, html?}` → `{data, scraper}`, with the BA fallbacks per the matrix. `POST /api/import/cocktail` `{draft}` → `{id}`, taken from `Location` or the body's `data.id`; BA errors pass through.
- [ ] `requirements.txt` -- add `beautifulsoup4`. `requirements-dev.txt` -- `-r requirements.txt` plus `pytest`.
- [ ] `tests/test_ingredients.py`, `tests/test_scrapers.py`, `tests/test_import_routes.py`, `tests/fixtures/foodnetwork_gobble_gobble_punch.html` -- cover the matrix rows. In route tests, mock `requests` for the BA and fetch calls, and use a Flask test client with the session set.
- [ ] `README.md` -- a short "Recipe import" section: the routes, and how to add a scraper (subclass, `@register`, fixture test).

**Acceptance Criteria:**
- Given a new module that subclasses `Scraper` with `@register` and is imported in `scrapers/__init__.py`, when a URL on its domain is scraped, then it wins over `JsonLdScraper`.
- Given a configured BA and a logged-in session, when a Food Network draft is posted to `/api/import/cocktail`, then the response is `{id}` and the cocktail exists in BA with 7 ingredients.

## Implementation Notes

- The implementer added `pytest.ini` (`testpaths = tests`) and `tests/__init__.py`. Without them, bare `pytest` collects the gitignored `_bmad/` tests.
- The registry orders scrapers by `not s.domains`: scrapers with no domains (generic) go last. A `generic` class flag was tried and dropped, because `JsonLdScraper` subclasses inherited it.
- Checked against BA `develop` source: `Cocktail::fromSchema4Array` reads the flat draft keys the plan uses. The `source` field may be an array.
- `ruff check app.py` reports 2 F401 errors (`redirect`, `url_for`). They already exist at the baseline and were left alone.

## Plan Change Log

## Review Triage Log

**Pass 1 (quick lens):** 14 findings: high 1, medium 5, low 5, false 2, maybe-false 1.

| # | Finding | Verdict | Route | Evidence |
|---|---------|---------|-------|----------|
| 1 | ingredients.py `lstrip("s ")` eats a leading "s" | high | patch | Reproduced: "…bottle sweet vermouth" gave "Weet vermouth" and "…cans soda water" gave "Oda water". |
| 2 | `_QTY_RE` rejects "2oz" (no space) | medium | patch | Reproduced: "2oz gin" gave amount None and name "2oz gin". This form is common on cocktail sites. |
| 3 | `_to_num` "1/0" → ZeroDivisionError → 500 | low | reject | Needs a literal x/0 in page data, which is unlikely, and the fix adds a guard. |
| 4 | `recipeIngredient` given as a str is iterated per character; a non-str `name` raises AttributeError | medium | patch | The code at jsonld.py assumes a list or str. `_name_of` already handles str/dict/list. |
| 5 | Non-string `html` in the request body → 500 | low | reject | Only reachable by a hand-crafted API call, and the fix adds a guard. |
| 6+7 | robots.txt: no redirect following, 5xx/errors treated as allowed, no size cap | medium | patch | Same root cause: robots.txt bypasses the guarded fetch path. This breaks the "honors robots.txt" and "5 MB cap" boundaries. |
| 8+9 | Timeouts can exceed gunicorn's 30s worker kill (Dockerfile:15, `--workers 1 --timeout 30`) | medium | patch | `import_cocktail` uses timeout=60 and `_ba_scrape` uses 30. Body reads have no total deadline. |
| 10 | Unknown charset → LookupError; `<meta charset>` ignored | low | reject | A rare server misconfiguration, and the fix adds branches. |
| 11 | 3xx without Location, or 300/304, returns an empty body | low | reject | The outcome is a "No recipe found" or BA fallback, which is acceptable. |
| 12 | E402 in `scrapers/__init__.py` | low | patch | Shows only with `--select E402`. The default `ruff check` passes. The fix is a noqa, since the bottom import is needed to avoid a circular import. |
| 13 | AC2 (live BA save with 7 ingredients) unverified | maybe-false | defer | Needs a manual run against the user's live Bar Assistant. Recorded for the user. |
| 14 | `.gitignore` change not in the plan | false | reject | The user explicitly chose to ignore `_bmad/` in this session (step 1). |
| — | `app.py` F401 at baseline | false | reject | Exists at the baseline, so not caused by this change. |

**Pass 1 patches applied** (by the implementer, then re-verified: 28 tests pass, `ruff check`/`ruff format --check` clean on `scrapers` and `tests`). Finding #12: the `# noqa: E402` was removed again, because the active ruff config does not enable E402 and flags the directive as unused (RUF100). Residual: robots.txt is re-checked on every redirect hop, each fetch with its own 15s deadline, so a hostile chain of slow redirects could still exceed the 30s gunicorn worker timeout.

## Design Notes

"Methods" are the input paths: URL fetch, pasted HTML, and the BA fallback. All of them return the same draft shape, so the deferred UI and any future method (bookmarklet, JSON paste) only add inputs. Site quirks live in scraper subclasses. JSON-LD sites override hooks; non-JSON-LD sites implement `scrape` with CSS selectors on the soup.

## Verification

**Commands:**
- `pip install -r requirements-dev.txt && pytest -q` -- expected: all pass
- `ruff check . && ruff format --check .` -- expected: clean

**Manual checks (if no CLI):**
- With the app running and logged in, POST the fixture HTML and URL to `/api/import/scrape` and inspect the draft. Then POST it to `/api/import/cocktail` and confirm the cocktail in BA.
