---
title: 'Estimate ABV for batch cocktails measured in cups, pints, quarts or gallons'
type: 'feature'
created: '2026-11-25'
status: 'done'
baseline_revision: '9d34b7e54b25b300852e7b2c673ba54cfa72a1de'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** Bar Assistant computes ABV only from lines in `cl, ml, oz, dash, shot, part, l, barspoon` (exact lowercase match, `Units::tryFrom`) and skips every other unit. Batch recipes written in cups or quarts (e.g. Bourbon-Cranberry: "4 cups Bourbon") come back with `abv` 0, so sugar-rim shows no ABV and the holiday menu board labels them "Zero proof".

**Approach:** sugar-rim computes its own ABV for these cocktails with BA's formula, converting the larger measures to ml for the calculation only, and replaces `abv` in the cocktail data it serves. Stored recipes and displayed amounts are untouched: 1 cup stays 1 cup.

## Boundaries & Constraints

**Always:**
- **Trigger:** recompute any cocktail with at least one line in a *large measure*, whichever line holds the alcohol: cup(s), c, pint(s), pt, quart(s), qt, gallon(s), gal, liter/liters/litre/litres (case-insensitive, trimmed). Otherwise BA's `abv` passes through unchanged, so ordinary cocktails never change.
- **Formula (BA's, `Utils::calculateAbv`):** each counted line's amount in ml; `alcohol = Σ ml·strength/100`; `diluted = Σ ml · (1 + dilution/100)`; `abv = round(alcohol/diluted·100, 2)`, 0.0 when `diluted <= 0`. Dilution is the cocktail's `method.dilution_percentage`.
- **Counted lines when recomputing:** BA's native units at BA's factors (ml 1, cl 10, oz 30, dash 0.3125, shot 30, part 30, l 1000, barspoon 5), plus large measures (US: cup 236.588, pint 473.176, quart 946.353, gallon 3785.41, liter-words 1000), spoon measures (tbsp/tablespoon(s) 14.787, tsp/teaspoon(s) 4.929) and spelling variants of BA units (dashes 0.3125, ounce/ounces/fl oz 30, parts 30, shots 30, barspoons 5). Unit match is case-insensitive. Every other unit (topup, whole, sprig, bottle, …) is skipped, as BA skips it. Lines with no numeric amount are skipped. `amount` (not `amount_max`) is used, as BA does.
- **No method → no recompute:** BA's `abv` (null) is kept, matching BA.
- **Strengths** come from BA `GET /ingredients?filter[id]=<comma ids>&per_page=100` (cocktail payloads carry only id/name/slug for ingredients). Fetched only for cocktails that have a large-measure line; one request per served payload.
- **Surfaces:** cocktail detail `GET /api/cocktails/<id_or_slug>` (SPA and kiosk detail views), the holiday-menu publish (`_publish`) so the board and `/menu/r/<slug>` get the estimate, and the board preview `/menu/preview` so it matches what publishing produces.
- **Failure is harmless:** if the strength lookup fails or errors, serve BA's data unchanged (never a 5xx because of the estimate).

**Never:**
- No writes to BA; no change to amounts/units in any response or display.
- No change to list endpoints or ABV sorting (BA sorts server-side on its stored value).
- No marking/labelling of the number as an estimate; no new settings.
- No recompute for cocktails without a large-measure line (e.g. "dashes" of bitters in a regular drink keep BA's value).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Batch in cups | Build (10%); 4 cup Bourbon @40, 1 cup OJ @0, 2 cup Cranberries @0, 3 whole Cinnamon | abv = 946.352·0.4 / (1656.116·1.1) ·100 → 20.78 | — |
| Mixed units | Build; 1 quart Cider @8, 2 oz Rum @40, 1 whole Apple | quart and oz both counted, whole skipped | — |
| Regular drink | Shake; 2 oz Gin @40, 2 dashes Bitters @45 | BA's `abv` returned unchanged, no strength fetch | — |
| Abbreviations | Build; 1 qt Cider @8, 4 ounces Rum @40 | qt and ounces both counted | — |
| Large measure on a non-alcoholic line | Build (10%); 1 cup OJ @0, 2 oz Gin @40 | recomputed: 24 / (296.588·1.1) ·100 → 7.36 | — |
| Batch with no alcohol | Build; 2 cup OJ @0, 1 cup Soda @0 | 0.0 | — |
| No method | method null, 2 cups Bourbon | BA's `abv` (null) unchanged | — |
| Strength lookup fails | BA /ingredients 500 or connection error | detail/publish served with BA's `abv` | logged warning only |
| BA detail 404 | unknown slug | BA's 404 body/status passed through | — |

</intent-contract>

## Code Map

- `app.py:453-455` -- `cocktail()` detail route; currently `return proxy("GET", ...)`. Wrap: on 2xx, apply estimate to `data`.
- `app.py:167-180` -- `proxy()` returns `(jsonify(data), status)`; reuse `http`, `ba_url`, `ba_headers` for the strength fetch rather than reshaping proxy.
- `app.py:709-739` -- `_publish()`; `raw` list from `_menu_cocktails(..., include="images,glass,method,ingredients.ingredient")` → apply estimate to `raw` before `menu.slim_cocktail`.
- `menu.py:72-97` -- `slim_cocktail` copies `c.get("abv")`; unchanged.
- `templates/menu.html:168-169` -- `abv == 0` → "Zero proof" (the visible bug); unchanged.
- `static/js/app.js:1423,3806` -- detail views render `c.abv`; unchanged.
- `tests/test_menu.py:78-155` -- `FakeBA` + `ba`/`env`/`owner` fixtures; `FakeBA.get` raises on unknown URLs, so add an `/api/ingredients` branch.
- BA reference (read-only, container `bar-assistant-bar-assistant-1`): `app/Models/Cocktail.php getABV`, `app/Utils.php calculateAbv`, `vendor/karlomikus/recipe-utils/src/UnitConverter/*`.

## Tasks & Acceptance

**Execution:**
- `abv.py` -- new pure module: unit→ml table, `needs_estimate(cocktail)` (has a large-measure line), `estimate(cocktail, strengths) -> float | None` (None = keep BA's value: no method, or no large-measure line). -- keeps the math testable without Flask.
- `app.py` -- add `_apply_abv_estimates(cocktails)`: picks cocktails where `needs_estimate`, fetches strengths for their ingredient ids in one BA call, sets `abv` where `estimate` returns a number; swallows `http` errors/non-2xx with a warning. Call it in `cocktail()` (2xx only), in `_publish()` on `raw`, and in `menu_preview()` on its `raw` before slimming. -- every surface that shows ABV.
- `tests/test_abv.py` -- unit tests for every I/O matrix row at the `abv.estimate` level, plus BA-parity check (Irish Coffee-style all-native input is not recomputed).
- `tests/test_menu.py` -- route tests: detail of a cup-measured cocktail returns the estimate and leaves the fake's catalog entry (`CATALOG[641]`) unmodified; strength lookup 500 and connection error return BA's value with 200; publish of two batch drinks with different ingredient ids plus one regular drink writes both estimates in one lookup and leaves the regular drink's ABV alone; `/menu` and `/menu/preview?ids=641` show "21% ABV" and no "Zero proof".

**Acceptance Criteria:**
- Given a cocktail with "4 cup Bourbon" and Build method, when the SPA detail view loads it via `/api/cocktails/<id>`, then the response's `abv` is the computed value and every ingredient's `amount`/`units` equal BA's.
- Given that cocktail is on the holiday menu, when the menu is published and `/menu` is rendered, then its card shows "21% ABV" (rounded) instead of "Zero proof".
- Given any cocktail with no large-measure line, when its detail is fetched, then no `/ingredients` request is made and `abv` equals BA's.
- Given Gobble Gobble Punch (cups of juice, spirits in ml), when its detail is fetched, then `abv` is recomputed with the cups counted.

## Spec Change Log

### 2026-11-25 — after review pass 1 (intent gap resolved by the user)
- Trigger: the finding was that batch drinks with juice in cups and spirits in oz/ml kept BA's wrong ABV (Gobble Gobble Punch 638 at 31.06, Spiced Cranberry-Orange Punch 589 at 0). The user chose "recalculate any cocktail with a large measure". Amended the intent-contract trigger, the matrix and the AC. The known-bad state this avoids is an estimate that only fires when the alcohol itself is measured in cups.
- Also amended from review: `/menu/preview` is a surface; unit spelling variants are added; tests now cover two batch drinks in one publish, the preview, and a non-vacuous catalog assertion.
- KEEP from the saved patch [spec-batch-cocktail-abv.patch](spec-batch-cocktail-abv.patch): the pure `abv.py` module shape, `_apply_abv_estimates` with one deduplicated `/ingredients?filter[id]=` lookup that swallows `BA_ERRORS` and non-2xx, the detail route wrapping `proxy()`, the FakeBA `/api/ingredients` branch (with `strengths`, `ingredients_down` as bool or Exception, `ingredient_lookups`), `FakeBA.request` forwarding GET to `get`, and the `batch` fixture's deepcopy into CATALOG.

## Review Triage Log

### 2026-11-25 — Review pass
- verdicts: 26 findings — high 1, medium 1, low 13, false 9, maybe-false 2
- findings:
  - `[false]` `[reject]` (intent) R2 "convert so BA computes it" not built; BA's stored abv stays 0 — the intent offers either route ("or"); R1 computes ABV without changing the displayed recipe.
  - `[medium]` `[patch]` (intent) `/menu/preview` never applies the estimate, so preview says "Zero proof" while the published board says "21% ABV" — confirmed at app.py menu_preview (same raw→slim path as _publish, no call). Moot this pass: intent_gap above it.
  - `[maybe-false]` `[reject]` (intent) menu_suggest.assess reads BA's abv — falls back to the TypeSafe alcohol judgment when abv is 0 (`alcoholic = bool(abv) or alcohol > YES`); settled by a suggest run that includes a batch drink. If true, low.
  - `[low]` `[reject]` (intent) lists and the ABV sort still use BA's value — no list view displays ABV (only static/js/app.js:1423,3806 detail views); fixing the sort needs server-side resorting, not a direct correction.
  - `[low]` `[reject]` (intent) "bottle"/"fifth" not converted — bottle size varies (3 lines in bar); adding a guessed size is not a direct correction.
  - `[medium]` `[patch]` (blind) preview misses the estimate — same as the intent finding; moot this pass.
  - `[false]` `[reject]` (blind) similar/ingredient-cocktails/menu-drinks views show BA's ABV — none of them renders abv (grep of static/js/app.js and templates).
  - `[high]` `[intent_gap]` (blind) a batch whose large measures are non-alcoholic keeps BA's wrong value — live bar 1: Gobble Gobble Punch (638) BA 31.06 with its cups of juice skipped, Spiced Cranberry-Orange Punch (589) BA 0, Charles Dickens' Punch, Pumpkin Pie Martini, Sex Work Is Real Work all excluded by the `strength > 0` trigger in the intent-contract. The user's intent ("batch cocktails that use larger measures") covers them; the contract narrowed it. Patch saved: [spec-batch-cocktail-abv.patch](spec-batch-cocktail-abv.patch).
  - `[low]` `[patch]` (blind) unit spellings missing (ounce(s), fl oz, parts, qt, pt, gal) — census of bar 1 finds only "parts" (1 line); table entries are a direct addition. Moot this pass.
  - `[low]` `[reject]` (blind) /ingredients per_page 100 without paging; missing ids count as 0 — all batch drinks in bar 1 together use 44 ingredients and a menu is capped at 12 drinks; a completeness guard adds a branch.
  - `[false]` `[reject]` (blind) the /ingredients lookup is unnecessary because include=ingredients.ingredient carries strength — verified live: nested ingredient has only id/name/slug; filter[id] comma list returned 44/44.
  - `[false]` `[reject]` (blind) fractional string amounts dropped — BA stores amount as a number.
  - `[low]` `[patch]` (blind) missing tests: several batch drinks in one publish, mixed batch/non-batch, lookup count on publish — same gap as the verification-gap finding; moot this pass.
  - `[low]` `[reject]` (blind) ruff format fails on test_menu.py / app.py — both files already fail `ruff format --check` at baseline 9d34b7e.
  - `[low]` `[reject]` (blind) spec untracked; docstring doesn't pin the BA version — the spec is committed at finalize; version pinning is documentation, not a defect.
  - `[low]` `[patch]` (edge) unit aliases qt/pt/gal/ounces/fl oz — same as the blind spelling finding; moot.
  - `[low]` `[reject]` (edge) a liquid line in an unknown unit is dropped from a recomputed drink — matches BA, which skips unknown units; bailing out would add a branch.
  - `[low]` `[reject]` (edge) ids missing from the lookup count as 0% — same as the paging finding.
  - `[false]` `[reject]` (edge) a BA ingredient row without `id` raises KeyError — BA always returns id.
  - `[false]` `[reject]` (edge) malformed method/ingredient makes estimate raise — BA returns dicts; no such state shown reachable.
  - `[medium]` `[patch]` (edge) preview shows "Zero proof" — same as the intent finding; moot.
  - `[maybe-false]` `[reject]` (edge, claim) "the two surfaces that show ABV" — the claim lives in the spec; rejected as a spec-edit finding, the underlying preview defect is logged above.
  - `[high]` `[intent_gap]` (edge, claim) AC "no /ingredients request without a large-measure alcoholic line" — unsatisfiable: strength is only known after the lookup. Same root cause as the trigger finding.
  - `[medium]` `[patch]` (verification-gap) no preview test for a batch drink — same as the preview finding; moot.
  - `[low]` `[patch]` (verification-gap) no test publishes two batch drinks, so the merged id lookup is unchecked — moot this pass.
  - `[low]` `[patch]` (verification-gap) `assert BATCH["abv"] == 0` is vacuous (fixture deep-copies) — should check CATALOG[641]; moot this pass.

### 2026-11-25 — Review pass 2
- verdicts: 20 findings — high 0, medium 0, low 12, false 7, maybe-false 1
- findings:
  - `[false]` `[reject]` (intent) the "convert so BA computes it" route is not built — carried: the intent offers either route; the user confirmed computing in sugar-rim.
  - `[low]` `[reject]` (intent) lists, ABV sort and BA's own UI keep BA's value — carried: no list view renders ABV; the reviewer also found the "ABV ↑/↓" sort options are for ingredients, not cocktails.
  - `[low]` `[reject]` (blind) a strength missing from the lookup counts as 0% — carried (paging/missing-id row): all batch drinks in bar 1 use 44 ingredients, 44/44 returned live; a completeness guard adds a branch.
  - `[false]` `[reject]` (blind) `i["id"]` KeyError — carried: BA always returns id.
  - `[false]` `[reject]` (blind) BA may ignore `filter[id]` on /ingredients — verified live this pass: 44 requested ids, 44 returned with correct strengths.
  - `[low]` `[reject]` (blind) dotted/abbreviated spellings (oz., tbsp., qt., floz) miss — census of bar 1 finds none; normalisation adds code for spellings not in use.
  - `[low]` `[reject]` (blind) oz at BA's 30 ml vs cups at exact US ml — matches BA for its native units by design; ~1.4% skew on oz lines, below display precision on the board.
  - `[maybe-false]` `[reject]` (blind) "c" could mean cl — census finds no "c" units; settled by a recipe that uses "c" for centilitre; if true, low.
  - `[low]` `[reject]` (blind) list/sort/filter keep BA's ABV — carried (same as the intent row).
  - `[low]` `[reject]` (blind) extra uncached /ingredients call with a 15 s timeout on batch detail views — only the 9 batch cocktails pay it; caching adds state.
  - `[false]` `[reject]` (blind) no "est." marker on the replaced value — not a defect; the intent asks for the ABV, and the spec rules out labelling.
  - `[low]` `[reject]` (blind) a large-measure line with no amount still triggers a recount — no such line in bar 1; result differs from BA only by spoon/variant lines.
  - `[low]` `[reject]` (blind) tests for empty strengths, malformed method, non-dict ingredient — inputs come from BA's typed payload; no reachable state shown.
  - `[low]` `[reject]` (verification-gap, other) no paging on the lookup — carried (paging row).
  - `[false]` `[reject]` (edge) KeyError on a row without id — carried.
  - `[false]` `[reject]` (edge) non-dict method or non-numeric dilution makes estimate raise — carried: BA returns a method object with integer dilution_percentage.
  - `[low]` `[reject]` (edge) per_page 100 — carried (paging row).
  - `[low]` `[reject]` (edge) absent id counted as 0% — carried (paging row).
  - `[low]` `[reject]` (edge) large line with no amount triggers — same as the blind row above.
  - `[false]` `[reject]` (edge, claim) errors escape the fallback — BA_ERRORS covers RequestException, ValueError, TypeError, AttributeError; the remaining cases are the KeyError/method rows above, unreachable with BA's payload.

## Design Notes

Trigger on any large-measure line (user decision 2026-11-25: "recalculate any cocktail with a large measure"). A census of bar 1 found `dashes` 41×, `teaspoon`/`tsp` 13× in ordinary drinks; triggering on those would silently shift ~40 regular cocktails' ABV. Once a cocktail *is* recomputed, spoon units are counted too, because batch recipes measure syrups and liqueurs in tbsp.

## Verification

**Commands:**
- `.venv/bin/python -m pytest -q` -- expected: all pass
- `ruff check . && ruff format --check abv.py app.py tests/test_abv.py` -- expected: clean

**Manual checks (if no CLI):**
- Against live BA with `~/.ba_dev_token`: detail of cocktail 641 returns non-zero `abv` and "4 cups"/"cup" units unchanged; cocktail 13 (Irish Coffee) `abv` still 9.92.

## Auto Run Result

Status: done (second run; the first run halted on an intent gap the user resolved: "recalculate any cocktail with a large measure").

**Change:** sugar-rim computes ABV with BA's formula for any cocktail with a cup/pint/quart/gallon/liter line and serves it on the cocktail detail route, the holiday-menu publish and the menu preview. Stored recipes and displayed amounts are unchanged.

**Files:**
- `abv.py` — new: unit→ml table, `needs_estimate`, `ingredient_ids`, `estimate`.
- `app.py` — `_apply_abv_estimates` (one `/ingredients?filter[id]=` lookup, falls back to BA's value on failure); called from `cocktail()`, `_publish()`, `menu_preview()`.
- `tests/test_abv.py` — new: every I/O matrix row, trigger spellings, variant units.
- `tests/test_menu.py` — FakeBA `/api/ingredients`, `batch` fixture, route tests for detail, failure fallback, 404, publish of two batch drinks plus a regular one, preview.

**Review:** pass 1 — 26 findings, intent gap (trigger) → user decision, spec amended, code re-derived; preview, unit variants and test gaps folded into the re-run. Pass 2 — 20 findings: 0 patches, 0 deferred, 20 rejected (reasons in the triage log).

**Follow-up review recommended:** false (no patches this pass).

**Verification:** `.venv/bin/python -m pytest -q` → 316 passed; `ruff check abv.py app.py tests/` clean; `ruff format --check abv.py tests/test_abv.py` clean (app.py and tests/test_menu.py already failed format at baseline). Live BA, bar 1: 9 of 633 cocktails recomputed — Bourbon-Cranberry 0→19.83, Charles Dickens' Punch 15.43→14.16, Gobble Gobble Punch 31.06→13.42, Mulled Apple Cider 0→6.84, Pumpkin Pie Martini 17.1→7.41, Sex Work Is Real Work 11.75→4.83, Spiced Bourbon with Red Wine 15.57→9.8, Spiced Cranberry-Orange Punch 0→0.0 (no alcoholic ingredient), Sunny's Rosemary Maple Bourbon Punch 0→14.55; Irish Coffee (13) untouched at 9.92.

**Residual risks:** the strength lookup is not paged (100 ids; bar 1's batch drinks use 44); BA's own UI, lists and sorting still use BA's stored ABV; the published holiday menu keeps old values until it is republished.
