---
title: 'Holiday menu ingredient checklist with shelf status'
type: 'feature'
created: '2026-11-21'
status: 'done'
baseline_revision: '30f36e0b5f821f2cb7022e08e04617879e28fe78'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: [oversized]
deferred:
  - summary: >-
      The checklist's frontend (grouping, per drink/per batch text, check-off persistence and pruning) has no automated test.
    evidence: |-
      The repo has no JS test harness (package.json has only Prettier scripts); review demonstrated a renamed group key or inverted batch label would pass every test.
    location: >-
      static/js/app.js HolidayMenu.openChecklist / _renderChecklist
    severity: low
  - summary: >-
      No CI job runs pytest or Prettier; the only workflow builds the Docker image.
    evidence: |-
      .github/workflows/docker.yml is the only workflow; tests protect changes only when run by hand. Pre-existing.
    location: >-
      .github/workflows/docker.yml
    severity: low
---

<intent-contract>

## Intent

**Problem:** Before a party there's no single list of everything the holiday menu's drinks need. The admin has to open each recipe and check the shelf by hand.

**Approach:** Manage → Holiday Menu gets an **Ingredient Checklist** view. It lists every ingredient used by the drinks on the menu (the saved list, not only what's published), each with a check-off box, the amount each drink needs, whether that amount is per drink or for a batch (e.g. the Spiced Cranberry-Orange Punch), and the app's judgment of whether it's on the bar shelf. That judgment comes from Bar Assistant's own matching: the exact ingredient, a variant of it, a substitute, or the parts to make it.

## Boundaries & Constraints

**Always:**
- **One row per ingredient.** Each BA ingredient appears once, with one line per drink that uses it: the drink's name, its amount (`amount`, `amount_max` as a range, `units`, shown in the viewer's oz/ml preference via `UnitPref.convert`) and **per drink** or **per batch**. A line with no amount shows the drink name only.
- **Batch:** BA has no servings field, so a drink is a batch when (1) any tag name contains "batch" or "punch" (the override: tag a recipe Batch in BA), or (2) any line's unit is quart, gallon or pitcher (singular or plural), or (3) its liquid lines total more than 500 ml: units ml, cl, dl, oz/fl oz/ounce(s), cup(s), tbsp, tsp, shot(s), l/liter(s)/litre(s); lines whose ingredient is ice are skipped and "bottle" adds nothing (its size varies). The rule lives in one function so it can be tuned.
- **Optional ingredients** are included and marked "optional" only when every drink using it lists it as optional.
- **Each row's status is exactly one of:**
  - **On the shelf:** the line's `in_bar_shelf` is true.
  - **Probably:** covered by an on-shelf variant (`in_bar_shelf_as_variant`, naming `variants_in_shelf`), an on-shelf substitute (`in_bar_shelf_as_substitute`, naming the substitutes whose `in_bar_shelf` is true), or parts on the shelf (`in_bar_shelf_as_complex_ingredient`). The row says which.
  - **Not on the shelf:** none of the above.
- **A row's status is the worst across its lines**, so a substitute that covers one drink doesn't hide that another drink lacks it.
- **Missing and probable rows come before on-shelf rows**, and rows are alphabetical within each group.
- **Check-offs** live in this browser's localStorage, are dropped for ingredients no longer on the list, and survive reloads.
- **Access:** admins and moderators only, like every `/api/menu` route.
- **Data source:** every menu drink is read from BA's cocktail detail. BA list responses lack the variant, substitute and complex flags.

**Never:**
- No AI or TypeSafe calls; the judgment is BA's shelf matching.
- No writes to BA: the checklist doesn't touch the shelf or the shopping list.
- No public or unauthenticated route.
- No summed totals across drinks, and no scaling by guest count: amounts are as each recipe gives them.
- No garnish prose: `garnish` is free text, not ingredients.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Shared ingredient | Two menu drinks use Lemon Juice | One row with two lines, "Cider Sour: ¾ oz per drink" and "Whiskey Sour: 1 oz per drink" | — |
| Batch drink | Punch: 68 oz club soda, 12 oz juice, 1 cup sugar… | Its lines say "per batch" | — |
| Bottle unit | Michelada: 1 bottle beer, no batch tag | Per drink | — |
| Batch tag | Recipe tagged "Punch" or "Batch" | Batch | — |
| Ice | Tiki drink with 600 ml crushed ice | Per drink (ice not counted) | — |
| Single drink | Highball totalling about 270 ml | Per drink | — |
| Range / no amount | `amount` 1, `amount_max` 2 dashes / no amount | "1–2 dashes" / name only | — |
| On shelf | Line `in_bar_shelf` true | Status on the shelf | — |
| Variant | Recipe says Bourbon; shelf has Buffalo Trace (variant) | Probably, "you have Buffalo Trace" | — |
| Substitute | Line not on shelf; substitute Rye on shelf | Probably, "substitute: Rye" | — |
| Complex | Ingredient's parts are on the shelf | Probably, "can be made from what's on the shelf" | — |
| Missing | No flag true | Not on the shelf | — |
| Mixed lines | Drink A covered by a substitute, drink B not | Not on the shelf (worst wins) | — |
| Optional everywhere vs. once | Optional in all lines / required in one | Marked optional / not optional | — |
| Empty menu | No drinks on the list | Empty list; UI says the menu has no drinks | — |
| Drink deleted in BA | Detail returns 404 | That drink skipped | — |
| BA failure | Detail returns 5xx or is unreachable | 502 JSON error, never an empty list | Shown in the view |
| Not admin or moderator | role 3/4 | 403 with the standard menu message | — |

</intent-contract>

## Code Map

- `app.py:525-930` Holiday menu section. `_menu_route` (role check plus MenuError/BA_ERRORS as JSON) and `_menu_list()` (the saved `cocktail_ids`) are reused. Add the route `GET /api/menu/ingredients` beside `menu_status` (around line 737). Detail lookup: `http.get(ba_url(f"/cocktails/{id}"), headers=ba_headers(), timeout=...)`. A 404 is skipped; any other non-ok raises `MenuError(..., 502)` (pattern: `_menu_list` seeding, `_menu_cocktails`).
- `menu.py`: add a pure `ingredient_checklist(cocktails)` that returns rows `{id, name, drinks, optional, status, via}`, sorted. Model it on `slim_cocktail` and `key_ingredients` for reading BA ingredient lines (`i["ingredient"]["name"]`, `optional`, `sort`).
- `menu_suggest.py:139` `missing_ingredients`: read-only reference for the app's existing shelf rule (`in_bar_shelf`).
- **BA detail fields**, read-only evidence from BA v5 `CocktailIngredientResource`. Each `ingredients[]` line carries:
  - `in_bar_shelf`, `in_bar_shelf_as_variant`, `in_bar_shelf_as_substitute`, `in_bar_shelf_as_complex_ingredient`
  - `variants_in_shelf[]` with `name`
  - `substitutes[]` with `ingredient.name` and `in_bar_shelf`
  - `optional` and `ingredient {id, name}`

  The list endpoint returns only `in_bar_shelf`; the others appear only on detail (`loadDefaultRelations`).
- `static/js/app.js:3447` `HolidayMenu`:
  - Add a "Ingredient Checklist" button after `#hm-drinks` in `_html()`.
  - The view opens with `Modal.open(title, body, footer)`, with a Back button calling `this.show()` (pattern: `_openSuggestion` / `backFromSuggestion`).
  - Check-off state follows `ShoppingList` at `static/js/app.js:2681`: `CHECK_KEY`, `_loadChecked`/`_saveChecked` with try/catch, pruned to current ids, and `sl-row` markup with the `check_circle` / `radio_button_unchecked` icons.
- `static/css/style.css:3159-3230` `.sl-*` styles: reuse them, adding only what the status labels need.
- `tests/test_menu.py`:
  - Fixtures `FakeBA`, `owner`, `listed`, `put_list`, `ROUTES`.
  - FakeBA already serves cocktail detail by id (added in 30f36e0); extend its catalog entries with shelf flags.
  - Add the new route to `ROUTES` so the role test covers it.

## Tasks & Acceptance

**Execution:**
- `menu.py`: add `ingredient_checklist(cocktails)` per the Always rules, with a separate pure `is_batch(cocktail)`. Each row's uses carry `{drink, amount, amount_max, units, optional, batch}`. It's pure, so it can be unit tested.
- `app.py`: add `GET /api/menu/ingredients` under `_menu_route`. It returns `{"rows": [...], "drinks": <count read>}` from the saved list in list order, using details.
- `static/js/app.js`: add the HolidayMenu checklist button and view, with grouped headers (Not on the shelf / Probably / On the shelf), a "N of M checked" line, the drink names and optional tag on each row, the `via` text, and localStorage check-offs.
- `static/css/style.css`: add minimal styles for the group headers and status text, then run `npm run format`.
- `tests/test_menu.py`: unit tests for `ingredient_checklist` covering each matrix row, and route tests for the empty, 404, 502 and role cases.

**Acceptance Criteria:**
- Given a holiday menu of two drinks, when an admin opens Manage → Holiday Menu → Ingredient Checklist, then every required and optional ingredient of both drinks appears once with a status and a check-off box.
- Given the admin has checked some rows, when they close and reopen the checklist, then those rows are still checked, and checks for ingredients no longer on the menu are gone.

## Spec Change Log

- 2026-11-21 — Scott, after the first implementation: BA's shelf matching is sufficient; add quantities, noting per drink vs. batch (e.g. Spiced Cranberry-Orange Punch). Amended the intent contract (approach, one-row rule, new batch rule, Never no longer forbids quantities), matrix (batch, bottle, single, range rows), and tasks. KEEP: everything already built for shelf status, grouping, check-offs, the route and its error handling.

- 2026-11-21 — Review pass: running the batch rule over the bar's 634 live BA recipes showed single drinks labelled batch (Michelada and Disgruntled Mai Tai via "bottle"; Spindrift via 600 ml crushed ice). The Batch rule's mechanism was the planner's derivation, not the user's words (the user asked only to "note if it's per drink or for a batch, like the spiced cranberry-orange punch"), so it was amended in place: BA tags containing batch/punch are the override, bottle no longer counts, ice is skipped, liters count as volume. Matrix rows updated. Known-bad state avoided: single drinks mislabelled per batch. KEEP: the 500 ml threshold, the one-function rule, the punch fixture as a batch.

## Review Triage Log

### 2026-11-21 — Review pass
- verdicts: 34 findings — high 0, medium 5, low 24, false 5, maybe-false 0
- findings:
  - `low` `patch` (blind) Drink names not decoded with `_text()` — fixed; entity test added.
  - `low` `reject` (blind) Detail lookups run sequentially with 15 s timeouts — at most 12 calls to BA on the same host (gimli); a slow BA already slows every page.
  - `low` `reject` (blind) Worst-status merge hides which drink needs the purchase — each row lists its drinks; worst-wins is the spec's rule for a shopping run.
  - `low` `reject` (blind) Check marks are global with no reset — spec'd per-browser state; checks for ingredients not on the menu are pruned; a reset button adds surface.
  - `low` `reject` (blind) Pruning on open can drop checks after a transient 404 — needs a drink deleted then restored in BA; rare.
  - `medium` `patch` (blind) Volume rule mishandles units (missing fl oz/tbsp/tsp/shot, liter vs l) — fixed: units added, liters count as volume; amount_max still ignored (low, unlikely).
  - `medium` `patch` (blind) "bottle" makes single drinks a batch — verified on the bar's 634 recipes (Michelada, Disgruntled Mai Tai); fixed: bottle no longer counts, batch tags added as the override.
  - `low` `reject` (blind) Rows not keyboard/screen-reader accessible — matches the existing shopping-list rows; a11y pass belongs to both together.
  - `false` `reject` (blind) Amount 0 is hidden — BA stores 0 for unmeasured lines (e.g. "0 whole Orange peels" in Bourbon-Cranberry Cocktail); showing "0 whole" would be wrong.
  - `low` `patch` (blind) Untested paths (via fallbacks, via join) — tests added; duplicate-line and non-404 4xx paths left (covered by the 5xx test's branch).
  - `low` `patch` (blind) "Probably" heading reads oddly — renamed "Probably on the shelf".
  - `false` `reject` (blind) No link from missing items to the shopping list — the spec's Never list excludes writes to BA; the user did not ask.
  - `false` `reject` (intent) The real punch's batch label is unverified — ran is_batch on all 634 live BA recipes: the Spiced Cranberry-Orange Punch is a batch (tag and ~3.6 L).
  - `low` `defer` (intent) Rendered strings and check-off behavior are untested — no JS harness; deferred.
  - `false` `reject` (intent) No totals or guest scaling (readings E2/E3) — the follow-up asked for "some kind of quantity" plus per drink vs batch, which is delivered; BA has no servings count to scale by.
  - `false` `reject` (intent) Garnish free text excluded — spec scope; garnishes that matter are usually ingredient lines in BA.
  - `low` `reject` (intent) Check-offs are per browser — spec'd; shared state would need server storage.
  - `medium` `patch` (intent) A single drink over 500 ml is labelled per batch — verified (Spindrift: 600 ml crushed ice); fixed: ice lines skipped. Live run now labels 11 recipes, all genuine batches.
  - `medium` `patch` (verification-gap) Fallback via texts never exercised — tests added for "you have a variant" and "a substitute".
  - `medium` `patch` (verification-gap) Joining via reasons across lines unpinned — test added (distinct reasons joined, duplicate listed once).
  - `low` `defer` (verification-gap) Frontend checklist behavior has no automated verification — same root as the intent finding; deferred.
  - `low` `defer` (verification-gap) No CI runs pytest — pre-existing; deferred.
  - `low` `reject` (verification-gap) Global localStorage key not scoped to a menu — duplicate of the blind finding; rejected.
  - `low` `patch` (edge) "l" vs "liter" inconsistency — fixed with the unit table change.
  - `low` `patch` (edge) Volume units outside the table — fixed (fl oz, ounce(s), tbsp, tsp, shot(s)).
  - `low` `reject` (edge) amount_max ignored in the total — a range straddling 500 ml is unlikely; the tag override covers it.
  - `low` `patch` (edge) Drink-name entities — same fix as the blind finding.
  - `low` `reject` (edge) Two drinks with the same name merge in `drinks` — `uses` keeps both lines; names on one menu are unique in practice.
  - `false` `reject` (edge) Ingredient line without an id is skipped — BA's CocktailIngredientResource always nests an ingredient with an id.
  - `low` `reject` (edge) Sequential lookups can outlast worker timeouts — same as the blind finding.
  - `low` `reject` (edge) Stale response race on fast Back/reopen — renders the same menu either way; cosmetic.
  - `low` `reject` (edge) Small ml amounts read "0 oz" — the app-wide UnitPref converter's existing rounding; out of this change.
  - `low` `reject` (edge) Inverted range when amount_max < amount — bad recipe data; not seen in the bar's 634 recipes.
  - `low` `reject` (edge) Prune after a transient 404 — same as the blind finding.

## Design Notes

"Whether you think it's on the shelf" is the app's best determination, so the checklist uses BA's own variant, substitute and complex matching as a **Probably** tier rather than an AI judgment. BA already encodes this, and it costs nothing per view. Worst-across-lines keeps the list honest for a shopping run.

## Verification

**Commands:**
- `source .venv/bin/activate && pytest -q`: expected, all pass.
- `ruff check app.py menu.py tests/test_menu.py`: expected, only the existing F401 for `url_for`.
- `npm run format:check`: expected, clean.

**Manual checks (if no CLI):**
- `node --check static/js/app.js` passes.

## Auto Run Result

Status: done

**Summary:** Manage → Holiday Menu → Ingredient Checklist lists every ingredient the saved menu's drinks use, once each, with a check-off box (kept in the browser), BA's shelf judgment (on the shelf / probably on the shelf, saying why / not on the shelf; worst line wins), and one line per drink with its amount in the viewer's oz/ml setting, marked per drink or per batch.

**Files changed:**
- `app.py` — `GET /api/menu/ingredients` (admins/moderators), reads each menu drink's BA detail; 404 skipped, other failures 502.
- `menu.py` — `ingredient_checklist()`, `is_batch()` with tag/bulk-unit/volume rule.
- `static/js/app.js` — checklist button and view in HolidayMenu with grouped rows and localStorage check-offs.
- `static/css/style.css` — group heading and use-line styles.
- `tests/test_menu.py` — 22 new tests and fixtures from real BA recipes.

**Review:** 34 findings. Patched 5 medium entries (batch rule: bottle and ice; unit table; two missing test paths) plus low fixes (drink-name entities, heading text). Deferred 2 (no JS tests; no CI running pytest). Rejected 22 with reasons in the triage log.

**Follow-up review recommended:** true — two or more medium entries were patched; the batch rule is a heuristic verified against the bar's live recipes but the rendered view has not been exercised in a browser.

**Verification:** `pytest -q` → 242 passed. `ruff check` → only pre-existing F401 (`url_for`). `npm run format:check` → clean. `node --check static/js/app.js` → ok. `is_batch` over all 634 live BA recipes → 11 batches, all genuine.

**Residual risks:** Sangria (1 bottle wine, untagged) now reads per drink until tagged Batch in BA; the view is untested in a browser.
