---
title: 'Editable AI image prompt template (ingredients) on the Manage screen'
type: 'feature'
ticket: ''
created: '2026-11-06'
status: 'built'
baseline_revision: '46f5474ade1a03e8b0683ef89279479265ed0593'
route: 'oneshot'
route_source: 'auto'
risk: 'low'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** The ingredient AI image prompt is hard-coded in `Ingredients._defaultPrompt` (`static/js/app.js`), so changing its style means editing code. A recipe (cocktail) template will be needed when the deferred cocktail-form AI image section is built.

**Approach:** Add an "AI Prompts" card to the Manage view. It opens a modal with one section per template; today there is only "Ingredient image prompt". The section has a textarea, the list of placeholders (`{name}`, `{description}`), Reset to default, and Save. The template is stored server-side in `.env` as `AI_PROMPT_INGREDIENT`, where empty means the built-in default. It is returned by `GET /config` and written through `POST /config` (login-gated, like the other `ai_*` fields). The ingredient form builds its pre-filled prompt from the saved template. The modal and storage are keyed by template name, so a `cocktail` template can be added later without restructuring. No cocktail template is built now.

Decisions (made autonomously, recorded for review):
- Storage is server-side, so all devices (kiosk and desktop) share one template, consistent with the other AI settings. Whitespace is collapsed to single spaces on save, which keeps `.env` single-line.
- Placeholders: `{name}` is the ingredient name, and `{description}` is the description's first sentence without trailing punctuation (the current behavior). After substitution, empty-placeholder artifacts (`, ,`, ` ,`, doubled spaces) are tidied. The default template reproduces today's prompt exactly when there is a description.

</intent-contract>

## Implementation Notes

Oneshot: about 90 lines across `app.py`, `static/js/app.js`, `templates/index.html` and tests. The pattern follows the existing `ai_*` config fields and `Modal`.

- `app.py` `get_config` adds `"ai_prompt_ingredient": os.getenv("AI_PROMPT_INGREDIENT", "")`. `set_config` adds `ai_prompt_ingredient` to the login-gated key list and saves it as `" ".join(str(v or "").split())`.
- `static/js/app.js`:
  - `AiImage` gains `DEFAULTS = { ingredient: 'Product photograph of {name}, {description}, including its key ingredient or two. Isolated on a plain pure white background, no shadow, soft even lighting, no text or labels.' }`, `templates = {}`, and `render(kind, vars)`.
  - `App.init` sets `AiImage.templates.ingredient` from `cfg.ai_prompt_ingredient`.
  - `Ingredients._defaultPrompt` uses `AiImage.render('ingredient', …)`.
  - A new `AiPrompts` modal (`App.aiPrompts.show()`) saves via `post('/config')` and updates `AiImage.templates`.
- `templates/index.html`: add an "AI Prompts" manage card (icon `auto_awesome`).

Implemented as planned. Files touched: `app.py` (get/set_config), `static/js/app.js` (AiImage.DEFAULTS/templates/render, Ingredients._defaultPrompt, AiPrompts, App.aiPrompts, App.init), `templates/index.html` (manage card), `tests/test_ai_image.py` (2 tests, AI_ENV cleanup).
Surprises: python-dotenv interpolates `${VAR}` even in single-quoted values on reload, so a template containing a literal `${…}` would be expanded after restart (negligible for prompts). Saving text identical to the default stores '' so future default changes still apply. `templates/index.html` already failed Prettier at baseline and is outside `npm run format` scope; ruff total unchanged (195 before/after).

## Verification

**Commands:**
- `.venv/bin/python -m pytest -q`: all pass, including new tests for the `/config` round-trip, whitespace collapse, and the anonymous write being rejected.
- `ruff check app.py tests/`: no new findings.
- `npx prettier --check static/js/app.js`: passes.

**Manual checks:**
- Manage → AI Prompts → edit and save → open an ingredient's edit form: the prompt reflects the template. Reset to default restores the built-in text.

## Review Triage Log

### 2026-11-06 — Review pass
- verdicts: 4 findings — high 0, medium 0, low 4, false 0, maybe-false 0
- findings:
  - `[low]` `[patch]` `AiImage.render` tidy left `,.` and a leading comma when `{description}` is empty in a user template. Fixed: drop a comma before `,`/`.` and strip leading commas/whitespace. Verified in Node: `"Photo of {name}, {description}. White"` → `"Photo of Gin. White"`.
  - `[low]` `[patch]` `k in vars` matched prototype keys (`{constructor}` was filled with function source). Fixed: `Object.hasOwn(vars, k)`. Verified: `{constructor}` is left as typed.
  - `[low]` `[reject]` Tidy rules also normalize a deliberate ` .`/` ,`/double space in the user's text. Unlikely in a prompt, and the fix (tidying only around placeholders) adds complexity.
  - `[low]` `[reject]` `escHtml` decodes entities, so a template containing literal `&amp;` would be decoded when re-saved. Unlikely in a prompt; the fix needs a new encode-only helper.

## Auto Run Result

- **Change:** Manage → "AI Prompts" card opens a modal for editing the ingredient image prompt template (`{name}`, `{description}`), with Reset to default and Save. The template is stored server-side as `AI_PROMPT_INGREDIENT` (empty = built-in default), exposed via `/config`, and writes are login-gated. The ingredient form's pre-filled prompt renders from it. `AiPrompts.SECTIONS` / `AiImage.DEFAULTS` are keyed by kind, so a `cocktail` template is one entry each later.
- **Files:**
  - `app.py`: `/config` read/write of `ai_prompt_ingredient`.
  - `static/js/app.js`: `AiImage.render`/templates, `AiPrompts` modal, init wiring, `_defaultPrompt` uses the template.
  - `templates/index.html`: Manage card.
  - `tests/test_ai_image.py`: round-trip and login tests.
- **Review:** 2 low patched, 0 deferred, 2 low rejected (reasons above). Patched counts: high 0, medium 0, low 2. Follow-up review recommended: false.
- **Verification:**
  - pytest: 121 passed.
  - ruff: 195 findings before and after (none new).
  - prettier on `static/js/app.js`: clean.
  - Node checks of `render` output: the default with a description is byte-identical to the old prompt.
  - The local instance's `/config` returns `ai_prompt_ingredient`.
- **Residual risks:**
  - The modal hasn't been clicked through in a browser.
  - A literal `${VAR}` in a template is expanded by python-dotenv when `.env` is reloaded after a restart.
