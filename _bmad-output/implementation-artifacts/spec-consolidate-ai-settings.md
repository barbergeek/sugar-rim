---
title: 'One AI card under Manage for every AI key, model and prompt'
type: 'refactor'
created: '2026-11-23'
status: 'done'
baseline_commit: '0188649835ce0fef0d9c908d4cafccf836e04849'
route: 'dispatch'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** AI configuration is in three places: the provider, key and image model are under **Settings → AI Images**; the prompt templates are on the **Manage → AI Prompts** card; and the TypeSafe key and suggestion chat model are at the bottom of the **Manage → Holiday Menu** dialog. Nobody can find them all, and the labels contradict each other (the "AI Images" provider also powers menu suggestions). Subroutine #17.

**Approach:** Replace the **AI Prompts** Manage card with a single **AI** card. Its dialog holds every AI setting, in three sections: **Provider** (provider, base URL, API key, image model, chat model for suggestions), **Menu suggestions** (TypeSafe key, plus which engine suggestions will use), and **Image prompts** (the two templates). Remove the AI fields from Settings and from the Holiday Menu dialog.

## Boundaries & Constraints

**Always:**
- **Decision (2026-11-23): Only bar Admins and Moderators can view or change AI settings**, applying the same live role check as the holiday menu. The dialog has one **Save** for the whole card. A plain member who opens the card sees "Only bar admins and moderators can change AI settings" in place of the form, and `/config` returns 403 for every AI field they send.
- Keys stay write-only: the browser sees only "•••• (saved)", never the key itself.
- No `.env` variable names or `/config` field names change; existing installs keep their settings untouched.
- Provider behavior is unchanged: model dropdown loaded from `/api/ai/models` with the text-box fallback; a provider change with a blank key clears the old key; the compatible provider requires a base URL and a model.
- The Holiday Menu dialog still shows which engine suggestions will use (`_showEngine`). When none is set up, it points to **Manage → AI**. The server error in `menu_suggest_route` says the same.
- Prompt templates keep their reset-to-default and "save the default as blank" behavior.

**Never:**
- No new AI features, providers or settings.
- Don't touch the Settings sections that aren't AI (URL, bar, units, scale, versions).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Open card | Logged in, key saved | Fields filled, key shows "•••• (saved)", engine line shows current engine | N/A |
| Blank key save | Key field empty, same provider | Saved key kept | N/A |
| Compatible without base URL | provider=compatible, base blank | Not sent | "✗ Base URL and model are required" |
| Plain member | role 3/4 opens the card or POSTs an AI field | Error message instead of the form; nothing written | 403 |
| No engine | No TypeSafe key, no provider | Holiday Menu and AI card both say to set one up in Manage → AI | N/A |

</frozen-after-approval>

## Code Map

- `templates/index.html:144-147` -- AI Prompts manage card → becomes the AI card (`App.ai.show()`, icon `auto_awesome`).
- `static/js/app.js` `Settings` (~445-680) -- `_html` AI Images block, and `_load`/`_syncAi`/`_providerChanged`/`_aiModel`/`_loadModels`/`saveAi`. Move these to the new module, reusing them as they are; remove the AI parts from Settings.
- `static/js/app.js` `HolidayMenu._html` (~3490-3503), `_loadMenu` (typesafe/suggest-model lines), `_showEngine`, `saveSuggestSettings` -- remove the key and model inputs and their save; keep `hm-engine` and point its text at Manage → AI.
- `static/js/app.js` `AiPrompts` (~4183-4240) and `App.aiPrompts` -- merge into the new `Ai` module and register it as `App.ai`. `AiImage.templates` load at bootstrap (~4409) is unchanged.
- `app.py:551-565` `_menu_role_denied` -- give it an optional message argument (default `MENU_DENIED`) so AI can reuse it with `AI_DENIED`.
- `app.py:205-219` `get_config` -- leave it as is; bootstrap still reads the prompt templates from it for every user.
- `app.py` new `GET /api/ai/settings` (role-gated) -- returns provider, model, base URL, `ai_key_set`, both prompts, `typesafe_key_set`, `menu_suggest_model` and the engine label (`_suggest_engine()[0]` or null). Never returns a key.
- `app.py:222-245` `set_config` -- the role-gated key set becomes every AI field plus `menu_page_seconds`. `menu_page_seconds` keeps `MENU_DENIED`; AI fields get `AI_DENIED`.
- `app.py:921-924` -- error text → "Set up a TypeSafe key or an AI provider in Manage → AI".
- `tests/test_menu.py:214-252` -- the role test now covers AI fields too; `test_other_settings_stay_login_only` changes to use a non-AI field (e.g. `bar_id`). `tests/test_ai_image.py` uses the `client` fixture; check its role default so those tests stay green.

## Tasks & Acceptance

**Execution:**
- [x] `app.py` -- `AI_DENIED`, message-aware `_menu_role_denied`, `GET /api/ai/settings`, AI fields role-gated in `set_config`, new suggestion error text.
- [x] `static/js/app.js` -- new `Ai` module (dialog with the three sections, load from `/api/ai/settings`, model list, one save that posts every field to `/config` and updates `AiImage.templates`), built from the Settings AI code and `AiPrompts`; strip AI from `Settings` and `HolidayMenu`; update `_showEngine` text; register `App.ai`, drop `App.aiPrompts`.
- [x] `templates/index.html` -- card label "AI", `onclick="App.ai.show()"`.
- [x] `tests/` -- `/api/ai/settings` returns fields without any key, 403 for roles 3/4/None; `/config` refuses AI fields for a member and writes nothing.

**Acceptance Criteria:**
- Given the app, when I open Settings, then there is no AI section.
- Given the Holiday Menu dialog, then it has no key or model inputs, but still shows the engine line.
- Given Manage, then there is one **AI** card and no **AI Prompts** card, and it edits every setting the old locations did.

## Implementation Notes

- Implemented by a subagent from this spec; the coordinator then reworded the AI card's own "no engine" line ("…a TypeSafe key here or an AI provider above"), since pointing at Manage → AI from inside it made no sense.
- `_menu_state()` no longer returns `suggest.typesafe_key_set` / `suggest.model` (no reader left).
- `tests/test_ai_image.py` `client` fixture stubs `_menu_role_denied` (acts as admin); the real gate is tested in `tests/test_menu.py`.
- Review patch: GET `/config` drops the AI provider/model/base/key-set fields (the Code Map said leave it, but the frozen decision gates *viewing* too, and nothing read them). `/api/ai/models` is role-gated as well.

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | blind, edge, vgap | GET /config still serves AI provider/model/base/key-set to anyone | medium | Fields unread by frontend (only `ai_prompt_*` at app.js bootstrap); contradicts frozen "view" decision. patch |
| 2 | blind, vgap | `/api/ai/models` login-only; saved key can be sent to caller-chosen compatible base URL | high | app.py ai_models substitutes saved key when provider matches; `_list_image_models` sends Bearer to `base`. patch (role gate) |
| 3 | blind, edge | Refetch failure after successful POST shows "✗" | low | Same try block in `Ai.save`. Direct correction. patch |
| 4 | blind | Dialog stays open after save but button says "Cancel" | low | Met on every save; label change. patch |
| 5 | blind | Chat-model label lost "only when not TypeSafe" condition | low | Old label conditional; `_suggest_engine` prefers TypeSafe. patch (label) |
| 6 | blind | No way to clear a saved TypeSafe key | medium | Pre-existing (old Holiday Menu save also write-only). defer |
| 7 | vgap | JS save body only mirrored by hand in a Python test | maybe-false (medium) | No JS test harness in repo. defer |
| 8 | edge | Unknown provider in .env shows None and next save wipes it | low | Only the UI writes AI_IMAGE_PROVIDER, always a listed option; guard adds branches. rejected |
| 9 | edge | Modal closed mid-POST sends error to detached node | low | Rare; fix adds guards. rejected |
| 10 | edge | No bar selected → AI settings unavailable | low | Consequence of the approved role decision; bar is always set in practice. rejected |
| 11 | edge | BA outage shows "only admins" message | low | Pre-existing `_menu_role_denied` behavior, same for menu. rejected |
| 12 | edge | Non-admin told to use Manage → AI | false | `hm-engine` lives in the Holiday Menu dialog, which non-admins can't open. rejected |
| 13 | blind | Provider-change key clearing untested in new body | false | `test_provider_change_clears_key` covers the server path. rejected |
| 14 | blind | `test_admin_saves_ai_settings` asserts little | low | Test-quality only; other tests cover provider/key persistence. rejected |
| 15 | blind | First-run AI-field 401 untested | false | `test_ai_config_requires_login` posts ai_provider unconfigured/logged out → 401. rejected |
| 16 | blind | Holiday Menu engine line stale after AI save | false | Single modal: opening AI closes Holiday Menu; reopening reloads `/api/menu`. rejected |
| 17 | blind | `_menu_role_denied` name misleading | low | No named harm. rejected |
| 18 | blind | AI_DENIED literal duplicated in tests | low | Matches the file's existing `DENIED` pattern. rejected |
| 19 | blind | Role change for AI image settings not called out | false | Explicit user decision recorded in frozen block. rejected |

## Verification

**Commands:**
- `source .venv/bin/activate && pytest -q` -- expected: all pass
- `ruff check . && npm run format:check` -- expected: clean

**Manual checks:**
- Run the app; open Manage → AI; save the provider, key and prompts; reopen and check the values persisted and the key shows "•••• (saved)".
