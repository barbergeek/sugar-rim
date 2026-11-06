---
title: 'Recipe import UI: input and review modals'
type: 'feature'
ticket: ''
created: '2026-10-31'
status: 'built'
baseline_revision: '7a30bebe4846dc6039d2edcdf5ba03dd10d964a1'
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

**Problem:** The recipe-import backend (`POST /api/import/scrape`, `POST /api/import/cocktail`) is merged, but the UI has no way to use it.

**Decision:** The image is shown as a link to the image (opens in a new tab, `rel="noopener noreferrer"`) with an "Include image" checkbox, checked by default. There is no preview, because the CSP blocks external images.

**Approach:** Add an "Import Recipe" card to the Manage view. It opens a modal where the user enters a URL, or a URL plus pasted page HTML. The returned draft appears in an editable review modal. Save posts the edited draft to `/api/import/cocktail`, then opens the new cocktail.

## Boundaries & Constraints

**Always:**
- Every scraped value inserted into HTML goes through `escHtml`, including in attribute values. Scraped content is untrusted.
- Use the existing `post()`, `Modal`, `Toast` and form CSS classes. Vanilla JS, no build step.
- The edited draft keeps the schema-v4 shape the backend returned, including `source`, `author` and `description`. The UI only overwrites the fields it shows.

**Never:**
- No backend or CSP changes.
- No ingredient picker or matching UI. Bar Assistant matches and creates ingredients by name.
- No changes to the existing cocktail create/edit form.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| URL import | A valid recipe URL | Spinner, then the review modal prefilled. A badge names the scraper used. | — |
| Paste HTML | "Paste HTML instead" toggled, URL + HTML | Same review modal, with no server fetch | — |
| Scrape error | 400/422/502 from the scrape route | The input modal stays open with the URL kept. A toast shows the server's `error` text. | Toast |
| Edit and save | User renames an ingredient, removes a row, unchecks the image | The posted draft reflects the edits: the row is gone, `images: []`, and `sort` is renumbered 1..n | — |
| Save success | 201 `{id}` | Toast "Cocktail imported", modal closes, Cocktails view opens the new cocktail | — |
| Save error | 4xx/5xx | The review modal stays open with the edits intact | Toast with the error |
| Hostile content | Draft name `<img src=x onerror=alert(1)>` | Rendered as literal text in inputs and labels. No script runs. | — |
| Empty name | User clears the name | Save is blocked | Toast "Name is required" |

</frozen-after-approval>

## Code Map

- `templates/index.html:98-113` `view-manage` `.manage-grid`. Add a `.manage-card` after "New Cocktail" with icon `download` and `onclick="App.importer.show()"`.
- `static/js/app.js`:
  - `:5-35` `api/post`, which throws `Error(data.error || data.message)`.
  - `:53` `escHtml`. `:164` `Toast.show/err`.
  - `:182-207` `Modal.open(title, bodyHtml, footerHtml)`, `Modal.close()`, `el()`.
  - `Cocktails._showForm` (`:1240-1315`) is the markup and style reference. Reuse `form-group`, `form-label`, `text-input`, `form-row`, `btn btn-ghost/btn-primary`, `loading-row`/`spinner`, and the `cf-units-list` datalist values.
  - `_renderFormIngredients` (`:1319-1345`) has the row markup classes `cf-ing-row`, `cf-ing-row-name`, `cf-ing-remove`, `cf-ing-row-fields`, `cf-ing-amount/unit/note`, `cf-ing-opt-label`. In import rows the name is an `<input>`, not a span.
  - `Cocktails._glasses/_methods` are cached lists that the review modal can reuse (fetch `/api/glasses` and `/api/methods` the same way if they are unset).
  - After save, mirror `_submitForm`'s create branch: `Cocktails.load(); Cocktails.open(id)`, with `Nav.go('cocktails')` first, because import starts from Manage.
  - `:2585-2599` the `App` registry. Add `importer: Importer`.
- `static/css/style.css`: the `.cf-ing-*` rules (`:847-930`). Add only what the name input and image row need.
- Draft shape from the scrape route: `{data: {name, instructions, description, source, garnish, glass, method, tags[], images[{uri, copyright}], author, ingredients[{name, amount, amount_max, units, note, optional, sort}]}, scraper}`. `glass` and `method` are name strings.
- CSP (`app.py:85-92`) is `img-src 'self' data:`, so external images can't be previewed (see the Decision in Intent). Only `http(s):` image URIs may be rendered as links.

## Tasks & Acceptance

**Execution:**
- [ ] `static/js/app.js` -- new `Importer` module.
  - `show()`: the input modal, with a URL field and a "Paste HTML instead" toggle that reveals a textarea.
  - `_scrape()`: posts to `/api/import/scrape`, then shows the review.
  - `_review(draft, scraper)`: inputs for name, description, instructions, garnish, tags (comma-separated), and glass/method selects (by name, preselecting the draft value when it matches). Plus ingredient rows (name, amount, units, note, optional, remove) and the image row.
  - `_collect()` and `_save()`, which posts `{draft}` to `/api/import/cocktail`.
  - Register it in `App`.
- [ ] `templates/index.html` -- the Manage card.
- [ ] `static/css/style.css` -- minimal additions for the name input and image row.

**Acceptance Criteria:**
- Given the Gobble Gobble Punch page HTML pasted with its URL, when the user saves without edits, then a cocktail named "Gobble Gobble Punch" opens with 7 ingredients.
- Given the review modal, when the user removes one ingredient row and saves, then the posted draft has 6 ingredients with `sort` 1..6.

## Implementation Notes

- `npm run format` reformatted all of `style.css`, which was already unformatted at the baseline. That 400-line churn was reverted, and only the two new rules (`.imp-ing-name`, `.imp-image-row`) were re-applied. `app.js` passes Prettier. `templates/` is outside the project's format scope.
- `pytest`: 54 passed, with no backend change.
- Matrix check, run once in headless Chrome by a throwaway Playwright script against a stub BA (scratchpad `e2e/e2e.py`, not committed because the repo has no JS test harness):
  - Paste HTML, edit and save (6 ingredients, `sort` 1..6, `images: []`), save success, scrape error, save error, empty name, and hostile content all PASS.
  - The hostile-content check ran with `bypass_csp`, so `escHtml` alone stopped the injection.
  - "URL import" was only exercised through the shared code path. Its fetch branch is covered by the backend tests.

## Plan Change Log

## Review Triage Log

**Pass 1 (quick lens):** 6 findings: medium 3, low 3, false 0, maybe-false 0. All routed to patch.

| # | Finding | Verdict | Route | Evidence |
|---|---------|---------|-------|----------|
| 1 | An edited amount is parsed lossily ("1/2" → 1, cleared → 0), and a stale `amount_max` contradicts it | medium | patch | `parseFloat("1/2") === 1`, and `...base` carries `amount_max`. Fractions are a common way to type amounts. |
| 2 | Back → Import alters the pasted HTML and URL | medium | patch | `escHtml` decodes entities through a textarea before re-escaping (app.js:53-64), so `&lt;` comes back as `<` in the refilled textarea. |
| 3 | A late scrape or `_loadLists` overwrites another modal the user opened | medium | patch | `_review` calls `Modal.open` unconditionally. A scrape plus the BA fallback can take up to about 25s, which leaves time to cancel and open another modal. |
| 4 | Null fields posted as `''` (description, garnish, units, note) | low | patch | `_collect` uses `.value.trim()` without `\|\| null`. `_submitForm` normalizes them. The fix is a direct correction. |
| 5 | Ingredient rows with an empty name are posted | low | patch | Clearing an editable name posts `name: ''`, and BA's matcher creates or matches by name. The fix is a direct filter. |
| 6 | Images the user never saw are posted when no checkbox is rendered | low | patch | `images: imgBox && !imgBox.checked ? [] : orig.images`. The fix is a direct correction: send only the shown image. |

**Pass 1 patches applied** by the implementer and re-verified: the headless-Chrome matrix script passes 7/7 again, `pytest` 54 passed, Prettier is clean on `app.js`, and `_parseAmount` was spot-checked in node ("1/2" → 0.5, "1 1/2" → 1.5, "" and "1/0" and "a splash" → null).

## Verification

**Commands:**
- `npm run format:check` -- expected: clean (run `npm run format` first)
- `pytest -q` -- expected: still all pass (no backend change)

**Manual checks (if no CLI):**
- Run the app logged in to Bar Assistant. In Manage → Import Recipe, paste `tests/fixtures/foodnetwork_gobble_gobble_punch.html` with its URL, review it, remove one row, and save. Confirm the cocktail opens in sugar-rim with 6 ingredients.
- Import a page whose JSON-LD name is `<img src=x onerror=alert(1)>`. No alert should appear.
