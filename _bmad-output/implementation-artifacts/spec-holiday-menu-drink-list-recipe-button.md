---
title: 'Holiday menu drink list gets the suggestion view''s Recipe button'
type: 'feature'
created: '2026-11-21'
status: 'done'
baseline_revision: '274069a607e1332a4cb31b74e8dcb2e8187af5ba'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred:
  - summary: >-
      The holiday menu's Recipe toggles (drink list and suggestion view) have no automated test in the repo.
    evidence: |-
      No JS test runner exists (package.json has only Prettier scripts; CI only builds the image). This build was checked with a throwaway Node vm harness running the real app.js against a stub DOM (11 checks, all passing), which is not committed.
    location: >-
      static/js/app.js HolidayMenu.toggleRecipe / _showDrinks
    severity: low
---

<intent-contract>

## Intent

**Problem:** In Manage → Holiday Menu, the list of drinks on the menu shows only names and a ✕. To see a drink's recipe, the admin has to leave the modal. The "Suggest a Menu" view already has a **Recipe ▾** button per row that expands the full recipe inline, and the user says it works fine.

**Approach:** Add the same **Recipe ▾ / ▴** button to each row of the menu's drink list, reusing the suggestion view's fetch-and-render code rather than writing a second recipe renderer.

## Boundaries & Constraints

**Always:**
- **Same component:** use the same button look (`btn btn-ghost btn-sm`, "Recipe ▾" closed, "Recipe ▴" open) and the same expanded markup, from `_recipeHtml`: photo, glass, method, ABV, description, ingredients with shelf dots and oz/ml amounts, instructions and garnish.
- **Same fetch and cache:** fetch `/api/cocktails/<id>` once into `App.cocktails._cache`, and show "Loading recipe…" and then the error text on failure.
- **Suggestion view unchanged:** its behavior stays exactly as it is today.
- **Several rows can be open at once.** Removing a drink drops its open state, and adding or removing a drink keeps the other open rows open.
- **The ✕ (take off menu) button** keeps working, and stays the last control on the row.

**Never:**
- No second copy of the recipe HTML or of the fetch logic.
- No backend changes.
- No changes to the published board or recipe pages.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Open | Click Recipe ▾ on a menu drink | Row shows "Loading recipe…" then the full recipe; button reads Recipe ▴ | — |
| Close | Click Recipe ▴ | Recipe collapses | — |
| Cached | Drink already fetched (e.g. opened in suggestions) | Recipe shows at once, no refetch | — |
| Fetch fails | `/api/cocktails/<id>` errors | Error text under the row | Shown inline |
| List changes | Add/remove another drink while one is open | Open one stays open | — |

</intent-contract>

## Code Map

- `static/js/app.js` `HolidayMenu`:
  - `_showDrinks(col)` (about line 4078): renders `#hm-drinks` rows as `<div class="hm-drink"><span>name</span><button ✕></div>`. Add the Recipe button and, when the row is open, the recipe below it.
  - `_suggestRow` (about line 3790): reference for the button markup.
  - `toggleRecipe(id)` (about line 3815): uses `this._sg.open`, `this._sg.recipeErr` and `this._renderSuggestion()`, so it's tied to the suggestion state.
  - `_recipeHtml(id)` (about line 3830): reads `this._sg.recipeErr`.
- **Generalize, don't copy:** give the shared code the open set, the error map and the re-render function as parameters, or as a small state object per list, so the suggestion view passes `this._sg` and `_renderSuggestion` and the menu list passes its own state and `_showDrinks`. The menu list's own state lives on `HolidayMenu` (an open `Set` and an error `Map`), and the drinks shown are `App.cocktails._menu.menu`.
- **Row layout:** `.hm-drink` (`static/css/style.css:761`) is a single flex row. The expanded recipe needs to sit below the name and buttons, so wrap the row or let it wrap, keeping the name and buttons on one line.

## Tasks & Acceptance

**Execution:**
- `static/js/app.js`: generalize `toggleRecipe` / `_recipeHtml` per the Code Map, wire the suggestion view to it unchanged in behavior, and add the button and expansion to `_showDrinks`.
- `static/css/style.css`: only what the row layout needs, then `npm run format`.

**Acceptance Criteria:**
- Given a holiday menu with drinks, when the admin opens Manage → Holiday Menu and clicks **Recipe ▾** on a drink, then that drink's full recipe appears under its row, identical to the one in Suggest a Menu.
- Given the Suggest a Menu view, when the admin uses its Recipe buttons, then they behave exactly as before.

## Spec Change Log

## Review Triage Log

### 2026-11-21 — Review pass
- verdicts: 18 findings — high 0, medium 0, low 17, false 1, maybe-false 0
- findings:
  - `low` `patch` (blind) `_mr` never reset, so open rows and stale errors return on modal reopen — fixed: `show()` starts with a fresh `_mr`.
  - `low` `patch` (blind) A failed recipe retries showing the old error — fixed: the error is cleared when a row opens (shared, so the suggestion view gets it too).
  - `low` `reject` (blind) 28px indent doesn't suit the menu list — kept so both recipes look identical, per the spec's same-component rule.
  - `low` `reject` (blind) Keyboard focus lost on toggle — same as the existing suggestion view; fixing one list only would make them differ.
  - `low` `reject` (blind) Recipe button lacks aria-expanded/label — same as the existing suggestion button; belongs to an accessibility pass over both.
  - `low` `reject` (blind) Inline button style duplicated instead of a class — matches the existing markup; a refactor adds churn for no user change.
  - `low` `reject` (blind) ✕ lacks type="button" and the nested markup is hard to read — cosmetic; the ✕ predates this change.
  - `low` `reject` (blind) `_recipeHtml` default argument hides a dependency on `_sg` — only the suggestion view relies on it, where `_sg` always exists.
  - `low` `reject` (blind) Loose `list` string and an indirect stale-render check — behaves correctly; harness checks both branches.
  - `low` `reject` (blind) Quick reopen before a fetch returns fetches twice — harmless duplicate GET, pre-existing in the suggestion view.
  - `low` `defer` (blind) No frontend test covers the new rules — no JS harness in the repo; checked with a throwaway Node harness; deferred.
  - `low` `patch` (edge) Retry after a failure shows the stale error — same fix as the blind finding.
  - `low` `patch` (edge) A re-added drink opens with its stale error — same root; fixed by clearing the error on open.
  - `low` `patch` (edge) Rows opened earlier come back expanded after reopening the modal — same fix as the blind `_mr` finding.
  - `low` `defer` (verification-gap) Recipe toggles are only checked by eye — same root as the blind test finding; deferred.
  - `false` `reject` (intent) Reading B (public TV board) is not touched — the request names the list in the suggest-a-menu screen's sibling, the admin Holiday Menu; the board already links recipes by QR code.
  - `low` `reject` (intent) Loading/error indent sized for the checkbox — duplicate of the blind indent finding.
  - `low` `defer` (intent) No test exercises the browser surface — duplicate of the test finding; deferred.

## Verification

**Commands:**
- `npm run format:check`: expected, clean.
- `node --check static/js/app.js`: expected, ok.
- `source .venv/bin/activate && pytest -q`: expected, all pass (no backend change).

**Manual checks (if no CLI):**
- Read the diff: there is one recipe renderer and one fetch path, and the suggestion view's calls pass its own state.

## Auto Run Result

Status: done

**Summary:** Each drink in Manage → Holiday Menu's drink list has the suggestion view's **Recipe ▾/▴** button, opening the same recipe card under the row. The shared `toggleRecipe` / `_recipeHtml` now take the list's own state, so there is one renderer and one fetch path.

**Files changed:**
- `static/js/app.js` — `_recipeList`, list-aware `toggleRecipe`, `_recipeHtml(id, recipeErr)`, Recipe button and expansion in `_showDrinks`, `_mr` reset in `show()`, error cleared on open.
- `static/css/style.css` — `.hm-drink` wraps a `.hm-drink-row` so the recipe sits below the name and buttons.

**Review:** 18 findings. Patched 2 low entries (stale error on retry; open state surviving a modal reopen). Deferred 1 (no JS tests). Rejected 12 with reasons above.

**Follow-up review recommended:** false — no high or medium entries were patched.

**Verification:** `npm run format:check` clean; `node --check` ok; `pytest -q` 242 passed; a throwaway Node vm harness running the real app.js against a stub DOM passed 11 checks covering every matrix row, the retry case, and the suggestion view's own state.

**Residual risks:** not clicked through in a real browser.
