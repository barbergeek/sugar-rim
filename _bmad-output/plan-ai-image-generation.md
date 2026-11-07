---
title: 'AI-generated ingredient images'
type: 'feature'
ticket: ''
created: '2026-11-04'
status: 'built'
baseline_revision: '689bb911dc8e7a3147afa34824793f57e32df3d2'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 1
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Many ingredients have no picture, or a poor one, and today the only way to set one is to upload a file or paste a URL.

**Approach:** Add an "AI image" option to the ingredient edit form's image section. It writes a prompt from the ingredient's name and description, which the user can edit, then generates a preview the user can regenerate. On Save, the preview replaces the current image through the existing upload path. Provider, model, base URL and API key are set in a new Settings section. The key lives only server-side in `.env`, like `BA_API_TOKEN`.

**Decisions:**
- Providers: OpenAI, Google Gemini, and "OpenAI-compatible" (a user-set base URL, e.g. a local server). API keys only; no subscription login. For compatible, the key is optional and the model is required. Private/LAN base URLs are allowed on purpose, since local servers are the point; the setting is login-gated like `api_url`.
- Split: the cocktail form's image section (file / URL / AI) is deferred to a follow-up (see `deferred-work.md`). The endpoint and frontend generate helper must be reusable by that follow-up.
- Loose work (no initiative).
- API key scope (review loop 1): saving a different provider with a blank key field clears the stored key; the same provider with a blank field keeps it. The key is never sent to a provider it wasn't saved with.
- Review loop 1: user chose to keep the implemented code and patch it rather than revert.

## Boundaries & Constraints

**Always:** The AI key is never returned to the browser; `/config` reports only `ai_key_set: bool`. All provider calls go through Flask. Generation and AI-settings writes require a logged-in session. A generated image reaches BA only when the user saves the form, so regenerating never leaves orphan BA images. A new image replaces the old ones, as the ingredient form already does.

**Never:** Batch or automatic generation over many items. Storing the key in the browser or in the session. New Python dependencies; call the provider REST APIs with `requests`. OAuth or account login flows. Cocktail form changes (deferred).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Generate OK | `POST /api/ai/image {prompt}`, provider + key set | `200 {image: "data:image/png;base64,…"}` | — |
| Not configured | no provider, no key (openai/gemini), or no base URL/model (compatible) | `400 {error: "AI image provider not configured…"}` | Form shows a toast pointing to Settings |
| Provider rejects | 401/400/content-policy from provider | `502 {error: <provider message>}` | Toast shows the message; form state is kept |
| Empty prompt | `{prompt: ""}` | `400 {error: "prompt required"}` | — |
| Not logged in | no session | `401` | Existing redirect to login |
| Compatible provider | provider `compatible`, base URL `http://192.168.1.5:8080/v1`, no key | `POST {base}/images/generations` with no `Authorization` header; same response handling as OpenAI | — |
| Settings save, blank key | `POST /config {ai_provider, ai_model, ai_api_key: ""}` | provider and model saved; existing key kept | — |

</frozen-after-approval>

## Code Map

- `app.py:182-214` -- `get_config`/`set_config`: return `ai_provider`, `ai_model`, `ai_base_url`, `ai_key_set`; accept `ai_api_key` as write-only (blank keeps it). Use `set_key` + `os.environ`, following the `api_token` pattern. Env: `AI_IMAGE_PROVIDER`, `AI_IMAGE_MODEL`, `AI_IMAGE_BASE_URL`, `AI_IMAGE_API_KEY`.
- `app.py:452-520` (Images section) -- add `POST /api/ai/image` and a `_generate_image(prompt) -> (bytes, mime)` helper that reads env and dispatches by provider. Reuse the `_logged_in()` guard, as in `image_from_url`.
- `static/js/app.js:238-300` (`Settings`) -- add an "AI Images" section to `_html()`, matching the existing section markup: a provider select (none / openai / gemini / compatible), a model input (placeholder shows the provider default), a base URL input (shown only for compatible), a password key input (placeholder "•••• (saved)" when `ai_key_set`), and a `saveAi()` button with a `cfg-status` message. Fill it in `_load()`.
- `static/js/app.js:1896-2005` (`Ingredients._showForm`/`_previewFile`/`_previewUrl`/`_submit`) -- add a prompt textarea `if-ai-prompt`, pre-filled from name and description, and a Generate button. Generating shows a spinner/disabled state, then sets the preview `src` to the returned data URL and keeps it in `this._aiImage`. File, URL, and generated are mutually exclusive: each clears the others. In `_submit`, a generated image is turned into a Blob and uploaded through the same `FormData` → `/api/images` branch as a file.
- Add a small `AiImage` object (`generate(prompt)` → data URL, `toBlob(dataUrl)`) near the other utilities, so the deferred cocktail work can reuse it.
- `static/css/style.css` -- reuse `.ing-form-img-*`; add minimal prompt-row styles only.
- `tests/test_import_routes.py` -- copy its `Resp` fake and `client` fixture pattern.
- `.env.example`, `docker-compose.yml` -- document the four env vars.
- Do not change: the `/api/images` upload proxy, `image_from_url`, `proxy()`.

## Tasks & Acceptance

**Execution:**
- [ ] `app.py` -- config fields, `/api/ai/image`, three provider adapters -- the core server path
- [ ] `tests/test_ai_image.py` -- one test per I/O matrix row (mock `app_module.http.post`, `monkeypatch.setenv`), plus Gemini response parsing, and a check that the key never appears in `/config` JSON -- locks in the secret-handling invariant
- [ ] `static/js/app.js` -- `AiImage` helper, Settings AI section, ingredient-form generate UI and submit branch
- [ ] `static/css/style.css` -- prompt row styles
- [ ] `.env.example`, `docker-compose.yml` -- new env vars

**Acceptance Criteria:**
- Given AI settings are saved, when the user reopens Settings, then the provider, model and base URL show, and the key field shows that a key is set without revealing it.
- Given an ingredient with an image, when the user generates, previews and saves, then the ingredient shows only the new image.
- Given the user edits the prompt before generating, then the provider receives the edited text.
- Given a generated preview the user did not want, when they press Cancel, then no image is created in BA.

## Review Triage Log

**Pass 1 (quick lens):** high 1, medium 3, low 5, false 0, maybe-false 0. 1 intent_gap (answered by the user, patched in place at their request), 8 patch, 1 rejected, 1 deferred.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | gunicorn `--timeout 30`, 1 sync worker kills generations >30s and blocks the app | high | patch | Dockerfile:15 confirmed; raise the timeout to 150 and add `--threads 4` |
| 2 | `_generate` writes into a closed or replaced modal (null throws; late result goes into another ingredient's form) | medium | patch | Elements are looked up by id after the await; `_showForm` resets `_aiImage`; add a request token plus a check that the form still exists |
| 3 | `_previewUrl` clears `_aiImage` before the empty-URL return, so the preview and the saved image disagree | low | patch | Move the clear after the empty check |
| 4 | New-ingredient prompt is stuck at "this ingredient" | low | patch | `i` is null at render time; leave the textarea empty for new items and build the prompt from the current name and description at Generate time |
| 5 | AI settings can be written unauthenticated on an unconfigured install | low | patch | `set_config` gate allows it when `BA_API_URL` is unset; the plan's Always rule requires login; reject AI fields without login |
| 6 | Stored key can't be cleared and gets sent to the compatible server | medium | intent_gap → patch | The user decided: clear on provider change |
| 7 | Compose `AI_IMAGE_*=${…:-}` empty values override UI-saved `.env` on restart | medium | patch | dotenv main.py:105 skips keys present in the environment; remove the four compose lines (the BA_* half is pre-existing → defer) |
| 8 | `_provider_error` drops string `error` fields | low | patch | `{"error":"msg"}` → AttributeError → "HTTP 4xx"; handle the str case |
| 9 | Bad base64 → 500 | low | reject | Needs a provider returning malformed base64; unlikely, and the fix adds a guard |
| 10 | Upload filename is always `.png` | low | patch | Derive the extension from `blob.type` |

## Design Notes

Provider adapters (each returns `(bytes, mime)`):
- **OpenAI**: `POST https://api.openai.com/v1/images/generations` `{model, prompt, size:"1024x1024", n:1}`, Bearer key → `data[0].b64_json`. Send `response_format:"b64_json"` only for `dall-e-*` models (`gpt-image-*` rejects it). Default model `gpt-image-1`.
- **OpenAI-compatible**: the same request against `{AI_IMAGE_BASE_URL.rstrip('/')}/images/generations`. Send `Authorization` only when a key is set, always send `response_format:"b64_json"`, and use a 120s timeout for local models. If the response has `data[0].url` instead, fetch the bytes.
- **Google Gemini**: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`, header `x-goog-api-key`, body `{contents:[{parts:[{text}]}]}` → the first `parts[].inlineData{mimeType,data}`. Default model `gemini-2.5-flash-image`.

Provider error message: OpenAI's `error.message` / Gemini's `error.message`, falling back to the HTTP status. If no image is in the response, return 502 "no image returned".

Default ingredient prompt: `"Product photograph of {name}{, description first sentence}. Isolated on a plain dark background, soft studio lighting, no text or labels."`

## Verification

**Commands:**
- `.venv/bin/pytest` -- expected: all pass, including the new tests
- `ruff check . && npm run format:check` -- expected: clean

**Manual checks:**
- Run the app with a real key, then generate and save an image on one ingredient.
