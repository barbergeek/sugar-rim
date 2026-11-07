---
title: 'Recipe import: fuzzy ingredient matching with user selection'
type: 'feature'
ticket: ''
created: '2026-11-01'
status: 'done'
baseline_revision: '7f5624744ce737c388ee3381ef179c20fd90bb49'
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

**Problem:** Bar Assistant v5.15.4 import links ingredients by exact lowercase name and creates a new one when nothing matches. A recipe ingredient "Bourbon" therefore becomes a new, duplicate ingredient instead of the bar's existing "Bourbon Whiskey" on the shelf.

**Decisions:** Preselect the top candidate when it is a confident match (score ≥ 0.8); otherwise default to "use name as typed". Candidates come from all of the bar's ingredients, with shelf ones boosted and marked.

**Approach:**
- After scraping, fuzzy-match each ingredient name against the bar's existing ingredients on the server.
- In the review modal, every ingredient row shows ranked suggestions and the user picks one, or keeps the name as typed.
- The posted ingredient name is the chosen existing ingredient's exact name, so BA's exact match links it.

## Boundaries & Constraints

**Always:**
- Matching logic is a pure, stdlib-only function, unit-tested with pytest.
- The candidate pool is all of the bar's ingredients. Shelf ingredients (`in_shelf` or `in_bar_shelf`) rank higher when scores tie closely, and the UI marks them.
- The user can override every row, including choosing "use name as typed" to create a new ingredient.
- All ingredient names rendered in the UI go through `escHtml`.

**Never:**
- No changes to Bar Assistant, the draft2 format, or how `/api/import/cocktail` posts.
- No ingredient IDs in the draft. Linking stays name-based.
- No new Python or JS dependencies.
- No ingredient creation or shelf changes from the review modal.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Partial name | "Bourbon"; bar has "Bourbon Whiskey" (shelf) and "Rye Whiskey" | "Bourbon Whiskey" ranks first with a shelf mark | — |
| Exact (case/space) | "simple syrup"; bar has "Simple Syrup" | Top candidate scores 1.0 | — |
| Plural / punctuation | "Limes", "Angostura bitters"; bar has "Lime", "Angostura Bitters" | Each is matched to the existing ingredient | — |
| No match | "Unicorn tears" | No candidates; the row keeps "use name as typed" | — |
| Shelf tie-break | "Vermouth"; bar has "Sweet Vermouth" (shelf) and "Dry Vermouth" (not on shelf) | The shelf one ranks first | — |
| Match fetch fails | BA unreachable or errors on the match call | The review modal still opens with plain name inputs, as today | Toast warning; import still works |
| User overrides | User picks the 2nd candidate, or "use name as typed" | The posted name equals that choice exactly | — |
| Many ingredients | Bar has more than one page of ingredients | All pages are considered | — |

</frozen-after-approval>

## Code Map

- `app.py`:
  - `_logged_in` (:45), `ba_url`, and `ba_headers` (bar context) are the helpers to use.
  - `_ba_scrape` (~:522) shows the pattern for calling BA directly with `http.post` and a timeout.
  - The import routes are at ~:536 and ~:573. Add the new route next to them.
  - BA `GET /ingredients` paginates (default 50, no cap on `per_page`), and each item has `id`, `name`, `in_shelf` and `in_bar_shelf`. Response `meta.last_page` gives the page count.
- `scrapers/draft2.py` and `scrapers/base.py` show the pure-module style. The new module goes at `scrapers/match.py`. It is not a scraper, so do not register it.
- `static/js/app.js` `Importer` (~:2585):
  - `_ingRow(ing, idx)` renders each row.
  - `_review(draft, scraper)` opens a loading modal, awaits `_loadLists()`, then renders. Its `loading.isConnected` guard must cover the extra await too.
  - `_collect()` builds the posted ingredients from `.imp-ing-name`.
- Reuse `get`/`post`, `escHtml`, `qs`, `el`, `Toast`, and the `cf-ing-*` classes.
- `static/css/style.css` was already unformatted at baseline: add rules only, never run Prettier on it. The existing import rules are `.imp-ing-name` and `.imp-image-row`.
- `tests/test_import_routes.py`: its `client` fixture and `Resp` fake are the patterns to reuse for route tests.

## Tasks & Acceptance

**Execution:**
- [ ] `scrapers/match.py` -- add `rank(name, candidates, limit=5)` over `[{id, name, on_shelf}]`. It returns at most `limit` items `{id, name, on_shelf, score}` with `score` ≥ 0.5, best first.
  - Normalize names: lowercase, strip accents and punctuation, singularize trailing "s".
  - Score: exact normalized = 1.0; all query tokens contained in the candidate = high, minus a length penalty; otherwise a blend of `difflib` ratio and token overlap.
  - The shelf bonus is small, enough to break near-ties only.
- [ ] `app.py` -- `POST /api/import/match {names: [str]}` → `{matches: [[candidate…] per name]}`.
  - Login required; 400 unless `names` is a list of strings (cap 50).
  - Fetch every page of BA `/ingredients` with `per_page=500` and a 10s timeout per call. BA errors give 502 `{error}`.
- [ ] `static/js/app.js`:
  - In `_review`, call `/api/import/match` with the draft ingredient names after `_loadLists`. On failure, show a toast and continue without suggestions.
  - In `_ingRow`, add a `<select class="imp-ing-match">` under the name. Its options are "Use name as typed" (value `""`) followed by the candidates labelled `Name · on shelf` / `Name`. Preselect the top candidate when its score ≥ 0.8, else "Use name as typed".
  - In `_collect`, use the selected candidate's exact name when the select is non-empty, else the name input.
- [ ] `static/css/style.css` -- minimal styling for `.imp-ing-match`.
- [ ] `tests/test_match.py` -- unit tests for each matrix row that `rank` covers.
- [ ] `tests/test_import_routes.py` -- route tests: pagination across 2 pages, auth, bad input, and the BA error giving 502.

**Acceptance Criteria:**
- Given the Gobble Gobble Punch import and a bar whose shelf has "Bourbon Whiskey", when the review modal opens, then the bourbon row preselects "Bourbon Whiskey · on shelf". Saving posts `name: "Bourbon Whiskey"` for that row.
- Given the match call fails, when the review modal opens, then the rows behave exactly as in 1.7.1 and save still works.

## Implementation Notes

- Implemented by subagent. New files: `scrapers/match.py` and `tests/test_match.py`. Changed: `app.py` (`POST /api/import/match`), `static/js/app.js` (`_matchSelect`, `_ingRow`, `_review`, `_collect`), `static/css/style.css` (`.imp-ing-match` only), and `tests/test_import_routes.py`.
- Scores:
  - Query tokens contained in the candidate: 0.95 − 0.05 per extra token.
  - Candidate tokens contained in the query: 0.85 − 0.05 per extra token.
  - Otherwise: 0.6 × difflib ratio + 0.4 × Jaccard.
  - The shelf bonus is +0.03 and affects the sort only.
- A row with no candidates renders no select. A chosen candidate takes precedence over a hand-edited name input.
- Verification:
  - pytest: 69 passed. ruff check/format and Prettier on `app.js` are clean.
  - Headless Chrome against a stubbed BA (scratchpad `e2e/e2e_match.py`, not committed): preselect, override to "as typed", match failure with toast plus plain rows plus a working save, and an escaped hostile candidate name all PASS, with no page errors.
- Matrix coverage: the partial, exact, plural, no-match and shelf rows are in `tests/test_match.py`, and the many-ingredients row is `test_match_paginates`. The fetch-fails and user-override rows are covered by the headless check, since the repo has no JS harness.

## Plan Change Log

## Review Triage Log

**Pass 1 (quick lens):** 9 findings: medium 2, low 7, false 0, maybe-false 0. 5 routed to patch, 4 rejected.

| # | Finding | Verdict | Route | Evidence |
|---|---------|---------|-------|----------|
| 1 | `_score` has a `cs <= qs` branch (not in the plan) that preselects the wrong ingredient | medium | patch | Reproduced: "Lime juice"→"Lime" and "Orange slices"→"Orange" both score 0.80, which meets the preselect threshold. Fix: delete the branch so these fall through to the blend. |
| 2 | A one-token generic name preselects a more specific product ("Gin"→"Sloe Gin" 0.9, "Lime"→"Lime Juice" 0.9) | low | reject | Reproduced. This is the plan's literal containment rule (the same one that gives "Bourbon"→"Bourbon Whiskey"), and it only fires when the bar lacks the plain ingredient. The choice is visible and overridable under the user's "preselect confident match" decision. A fix needs a word-order heuristic, so it is more than a direct correction. Raised with the user as a possible follow-up. |
| 3 | Preselect checks only `matches[0].score`, but the order includes the shelf bonus | low | patch | A shelf candidate at 0.78 ranks above a non-shelf one at 0.80, so nothing is preselected. Fix: `findIndex(score ≥ 0.8)`. |
| 4 | Editing the name input is silently ignored while a candidate is selected | medium | patch | `_collect` takes `picked \|\| input`, and the UI gives no hint of that. Fix: typing in the input resets the select to "as typed". |
| 5 | The pagination loop has no overall deadline | low | reject | With `per_page=500` a bar is typically 1 page, and a slow or misbehaving BA is not demonstrated. A fix adds a guard. |
| 6 | Name strings have no length cap | low | reject | Only the logged-in single user can call this route. A fix adds a guard. |
| 7 | More than 50 ingredients always fails matching | low | reject | No cocktail recipe has more than 50 ingredients (CLAUDE.md: no handling for impossible scenarios). The fallback toast still lets the import proceed. |
| 8 | `normalize` drops non-decomposable and non-Latin letters | low | patch | "Brøndum" still matches itself exactly, but Cyrillic names produce no tokens and therefore no suggestions. Fix: tokenize with a Unicode word regex. |
| 9 | The 502 test checks only the status, not the `{error}` body | low | patch | The test asserts only `status_code`. Fix: also assert `"error"` in the JSON. The branch-coverage part of this finding is moot after #1. |

**Pass 1 patches applied** by the implementer and re-verified:
- pytest: 71 passed. ruff and Prettier are clean.
- The headless check passes 9/9, with new cases:
  - "Fresh lime juice" is offered "Lime Juice" but not preselected.
  - Typing in a preselected row resets it to "as typed".

## Design Notes

Matching is done on the server so it is testable with pytest; the repo has no JS test harness. It uses a separate route rather than enriching `/api/import/scrape`, so the scrape's time budget is unchanged (gunicorn timeout 30s, and the fetch plus the BA fallback already use up to about 25s). It also keeps working when the scrape fell back to BA.

Score examples (target ordering, not exact values): "bourbon" → "Bourbon Whiskey" ≈ 0.9; "bourbon" → "Rye Whiskey" < 0.5 (dropped); "limes" → "Lime" = 1.0.

## Verification

**Commands:**
- `uv run --no-project --with-requirements requirements-dev.txt python -m pytest -q` -- expected: all pass
- `uvx ruff check scrapers tests && uvx ruff format --check scrapers tests` -- expected: clean
- `npx prettier --check static/js/app.js` -- expected: clean

**Manual checks (if no CLI):**
- Headless-browser check against a stubbed BA (the scratchpad e2e pattern): the bourbon row preselects the shelf match, an override posts the chosen name, and a failed match call still lets the review modal open.

