---
title: 'Cocktail form images (file / URL / AI) + inline AI errors'
type: 'feature'
ticket: ''
created: '2026-11-06'
status: 'built'
baseline_revision: 'af2b1917a9b2b009b5d61068cbf3560c5f3ded38'
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

**Problem:** The cocktail edit form has no image controls at all, so cocktail pictures can only be set in Bar Assistant itself. AI generation errors (quota exceeded, transparency rejected, etc.) appear only in a 2.8s toast, which is too brief to read.

**Approach:** Give the cocktail form the same image section the ingredient form has (choose file, paste URL, AI prompt + Generate), by moving the ingredient form's image code into one shared helper that both forms use. The cocktail prompt comes from a new editable `cocktail` template in Manage → AI Prompts. It is rendered from the cocktail's name, glass, ingredients and garnish, in a studio setting (not transparent). AI errors on both forms show inline under the Generate button. They stay until the next Generate attempt or until dismissed.

**Decisions:**
- Loose work (no initiative). Both goals ship in one plan; the user asked for them together.
- Default cocktail template: `Studio photograph of a {name} cocktail[ in a {glass}][, made with {ingredients}][, garnished with {garnish}]. Plain dark background, soft studio lighting, no text or labels.`
- Template syntax gains optional segments: text in `[ … ]` is dropped when any placeholder inside it is empty, and otherwise kept without the brackets. This works for both templates; the ingredient default is unchanged.
- Cocktail placeholders:
  - `{name}`
  - `{glass}`: the selected glass name
  - `{ingredients}`: the form's current ingredient names, comma-separated, in form order
  - `{garnish}`
- A new cocktail image replaces the old ones. The old images are deleted only after the cocktail save succeeds.
- The image section sits at the bottom of the cocktail form, after Ingredients.

## Boundaries & Constraints

**Always:**
- Cocktail generation calls `AiImage.generate(prompt, false)`.
- A generated or picked image reaches BA only on Save, through the existing `/api/images` and `/api/images/from-url` routes.
- The ingredient form keeps its current behavior: transparent generation, file/URL/AI mutually exclusive, and old images replaced.
- `AI_PROMPT_COCKTAIL` follows `AI_PROMPT_INGREDIENT` exactly: login-gated write, whitespace collapsed, empty means default.

**Never:**
- New Python dependencies or new backend routes.
- Changing the importer's image handling.
- Batch generation.
- Sending `images` in the cocktail PUT when no new image was chosen, because existing images must survive ordinary edits.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cocktail AI save | edit cocktail, Generate, Save | the PUT includes `images: [newId]`; old image ids are deleted after the PUT succeeds; the detail view shows the new image | — |
| Cocktail edit, no image change | edit name only, Save | the PUT has no `images` key; the existing image remains | — |
| Cocktail create with URL | new cocktail, paste URL, Create | `/api/images/from-url` is called, the POST includes `images: [id]` | upload failure → inline toast, form kept |
| Save fails after upload | PUT rejected | old images are NOT deleted | the existing error toast |
| Empty optional fields | no glass, no garnish, no ingredients | prompt `Studio photograph of a Negroni cocktail. Plain dark background, …` | — |
| AI error | provider returns a quota error | the message appears under Generate and stays; the next Generate clears it; × dismisses it | no toast |
| Config | `POST /config {ai_prompt_cocktail}` logged in / anonymous | saved and returned by `GET /config` / 401 | — |

</frozen-after-approval>

## Code Map

- `static/js/app.js:238` `AiImage`:
  - add a `cocktail` entry to `DEFAULTS`.
  - In `render`, before placeholder substitution, resolve `[ … ]` optional segments: drop a segment if any `{k}` inside maps to an empty or missing value, otherwise unwrap it. Keep `Object.hasOwn` and the existing tidy chain.
- `static/js/app.js:2057-2245` `Ingredients._showForm` / `_previewEl` / `_generate` / `_previewFile` / `_previewUrl` / `_submit`:
  - the source of the shared helper. Move the image markup, preview, generate and upload logic into a new `ImageField` object, parameterized by an id prefix (`if` for ingredients, `cf` for cocktails), with per-prefix state for the generated data URL and the stale-request token.
  - The ingredient form calls it, keeping its element ids (`if-img-preview`, `if-image-file`, `if-image-url`, `if-ai-prompt`, `if-ai-btn`, `if-existing-img-ids`) and its CSS classes (`.ing-form-img-*`, `.ing-ai-row`, `.ing-img-*`), so styles keep working.
  - The upload must return the new image id, or throw with a message the caller shows with the existing "Image upload failed:" / "Image URL failed:" prefixes.
- `static/js/app.js:1499-1576` `Cocktails._showForm`:
  - append the image section using `c?.images`, with the prompt pre-filled for an existing cocktail.
  - Generate builds the prompt (when the textarea is empty) from `cf-name`, the selected `cf-glass` option text (empty for "— none —"), `this._formIngredients` names after `_collectFormIngData()`, and `cf-garnish`.
- `static/js/app.js:1721` `Cocktails._submitForm`:
  - upload the image first (on failure: show the error, return).
  - Add `body.images = [id]` only when there is a new image.
  - After a successful PUT or POST, `Promise.allSettled` delete the old ids.
- `static/js/app.js:3291` `AiPrompts.SECTIONS`: add `{kind: 'cocktail', label: 'Cocktail image prompt', hint: …}`. The hint names the placeholders and the `[ ]` optional syntax; update the ingredient hint to mention `[ ]` too.
- `static/js/app.js:3507` `App.init`: also set `AiImage.templates.cocktail` from `cfg.ai_prompt_cocktail`.
- `app.py:191-247` `get_config` / `set_config`: add `ai_prompt_cocktail` ↔ `AI_PROMPT_COCKTAIL`, mirroring `ai_prompt_ingredient` (including the login-gated key list). A loop over the two kinds is fine.
- `static/css/style.css:784-850`: reuse the existing classes. Add only a small `.ai-error` style (error color, with a dismiss button) next to `.ing-ai-row`.
- `tests/test_ai_image.py:12,204-222`: add `AI_PROMPT_COCKTAIL` to `AI_ENV`, and extend or parametrize the two prompt-template tests over both kinds.
- Do not change: `Importer` (`app.js:~3180-3290`), `AiImage.generate`/`toBlob`, or the backend image routes.

## Tasks & Acceptance

**Execution:**
- [x] `app.py` -- add `ai_prompt_cocktail` to `/config` read/write and to the login-gated list -- parity with the ingredient template
- [x] `tests/test_ai_image.py` -- parametrize the round-trip and login tests over `ingredient`/`cocktail` -- covers the Config matrix row
- [x] `static/js/app.js` -- `AiImage`: add the cocktail default and `[ ]` optional segments -- covers the Empty optional fields row
- [x] `static/js/app.js` -- add `ImageField` (markup, preview, generate with inline error, upload) and switch `Ingredients` to it -- one implementation for both forms
- [x] `static/js/app.js` -- `Cocktails._showForm`/`_submitForm`: image section, prompt builder, upload, then save, then delete old -- covers the cocktail rows
- [x] `static/js/app.js` -- `AiPrompts.SECTIONS` cocktail entry and hints; `App.init` loads the cocktail template -- editable from Manage
- [x] `static/css/style.css` -- `.ai-error` style -- inline error display

**Acceptance Criteria:**
- Given Manage → AI Prompts, when it opens, then there are two sections, Ingredient and Cocktail, each with Reset to default, and saving persists both across a page reload.
- Given the ingredient form, when an image is chosen by file, by URL or by AI and saved, then it behaves as before: transparent AI images, and the old image is replaced.
- Given an AI error on either form, when it occurs, then no toast shows. The message stays under Generate until Generate is pressed again (cleared at start) or × is clicked.
- Given a cocktail whose ingredients were edited in the form, when Generate is pressed with an empty prompt, then the prompt reflects the current form ingredients and glass.

## Implementation Notes

- `ImageField.upload` throws errors that already carry the "Image upload failed:" / "Image URL failed:" prefix; callers just `Toast.err(e.message)`.
- Cocktail save: old images are deleted after the PUT/POST succeeds but before `open()` reloads the detail view, so the detail fetch cannot race the delete.
- Manual checks against the live instance were not run (they would write to the real BA on gimli).

## Plan Change Log

## Review Triage Log

### 2026-11-06 — Review pass
- verdicts: 3 findings — high 0, medium 0, low 3, false 0, maybe-false 0
- findings:
  - `[low]` `[patch]` After an edit that replaces the image, the cocktail list card keeps the deleted image's thumbnail (`_cardHtml` uses `c.images[0]`, and the list is reloaded only on create). Fixed: `if (!id || imageId) this.load()`.
  - `[low]` `[patch]` A failed PUT/POST after a successful upload orphans the new image in BA. Fixed: best-effort `del` of `imageId` in the save catch; old images untouched.
  - `[low]` `[patch]` `ImageField.upload` file/AI branch returned `undefined` silently when `/api/images` gave no id (carried over from the ingredient code; violates the plan's return-or-throw contract). Fixed: throw "No image ID returned from BA".

Matrix audit note: the Config row is covered by the parametrized pytest. The Empty-optional-fields row was verified by a Node render of the real `AiImage`, which is not a registered test. The cocktail save/error rows have no JS test harness in this repo and remain manual checks.

## Design Notes

Optional-segment rendering, as an example of the expected results (the default with vars `{name:'Negroni', glass:'', ingredients:'Gin, Campari', garnish:''}`):
`Studio photograph of a Negroni cocktail, made with Gin, Campari. Plain dark background, soft studio lighting, no text or labels.`

Deleting old images after the save, rather than before as the ingredient form does today, means a failed save never loses the current picture. The ingredient form's order is left alone: it's pre-existing behavior outside this intent.

## Verification

**Commands:**
- `.venv/bin/python -m pytest -q` -- expected: all pass, including the parametrized prompt-template tests
- `uvx ruff check . --statistics` -- expected: total unchanged from baseline (195)
- `npx prettier --check static/js/ static/css/style.css` -- expected: `app.js` clean (`style.css` already fails at baseline; must not get worse in the new lines)
- `node` snippet that evals `AiImage` from `app.js` and renders both defaults with full and empty vars -- expected: matches the matrix and the Design Notes example

**Manual checks:**
- In the running instance (`:5000`), edit a cocktail: generate, Save, and the detail view shows the new image. Edit again changing only the name: the image remains. Force an AI error (e.g. set the model to `gpt-image-2` with transparency on an ingredient): the message stays inline.
