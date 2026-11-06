---
title: 'Fix settings lockout: wrong BA URL blocks both saving the URL and logging in'
type: 'bugfix'
ticket: ''
created: '2026-11-06'
status: 'blocked'
baseline_revision: '689bb911dc8e7a3147afa34824793f57e32df3d2'
route: 'oneshot'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred:
  - summary: >-
      Add a test pinning that anonymous AI-settings writes return 401 once the fix and feat/ai-ingredient-images are merged.
    evidence: |-
      The planned test does not apply on main, which has no AI fields. The AI login check lives only on the feature branch.
    location: >-
      tests/test_config.py
    severity: low
  - summary: >-
      Setup wizard saveUrl replaces every server error with a generic reachability message.
    evidence: |-
      static/js/app.js SetupWizard.saveUrl catch block ignores e.message, so a 401 reads as "Could not reach that URL".
    location: >-
      static/js/app.js:518
    severity: low
---

<intent-contract>

## Intent

**Problem:** `POST /config` rejects every unauthenticated write once `BA_API_URL` is set (`_configured() and not _logged_in()` → 401). If the saved URL is wrong or unreachable, login fails too, because it goes to that same URL. The user can't log in to fix the URL and can't fix the URL without logging in; the only way out is editing `.env` by hand. Reproduced on a local instance whose `.env` held the Docker-internal `http://bar-assistant:8080/`.

**Approach:** Keep the login requirement only while the configured URL actually answers as a Bar Assistant server. When it doesn't (connection error, timeout, non-2xx, or a body without `data.version` from `/server/version`), treat the instance as not configured, so unauthenticated URL/bar writes are allowed again. AI settings always require login, as before. Make the remaining 401 message say what to do.

</intent-contract>

## Tasks & Acceptance

**Execution:**
- [ ] `app.py` -- add `_ba_reachable()`: GET `ba_url("/server/version")` with a short timeout; true only for a 2xx JSON body with `data.version`. In `set_config`, return 401 only when configured, not logged in, AND `_ba_reachable()`. Probe only in that case. Change that 401 body to `{"error": "Log in to change server settings."}`. Leave the AI-field login check unchanged.
- [ ] `tests/test_config.py` -- new tests (isolated `ENV_PATH`, `http.get` monkeypatched): reachable BA + anonymous → 401 and URL unchanged; connection error + anonymous → 200 and URL saved; non-BA response (404 / HTML) + anonymous → 200; logged-in → 200 with no probe; unreachable + anonymous AI fields → 401.

**Acceptance Criteria:**
- Given a running instance whose saved BA URL is unreachable and no session, when the user enters a correct URL in Settings → Save URL, then it shows "✓ Saved", and logging in then succeeds against the new URL.
- Given a reachable, correctly configured BA and no session, when anyone posts a new `api_url` to `/config`, then it returns 401 with the message "Log in to change server settings." and the URL is unchanged.

## Implementation Notes

Oneshot: one backend gate plus tests, well under 100 lines. Built on branch `fix/settings-url-lockout` from `main` in worktree `/home/scott/develop/sugar-rim-fix`. The bug is on `main`, so the fix stays separate from the unmerged `feat/ai-ingredient-images` branch.

Security tradeoff: while the configured BA is down, an anonymous LAN client can repoint the URL. That is the same exposure as first-run setup, and it only exists while the instance can't log anyone in anyway. While BA is healthy, the gate is as strict as before.

Implemented:
- `app.py`: added `_ba_reachable()`. It catches `RequestException`, `ValueError` and `AttributeError` rather than a blind `Exception`, so ruff's BLE001 stays at its baseline. The `set_config` gate now probes before it returns 401, and the 401 message is now actionable. I dropped the old comment's claim "(In prod … always gated)", which is no longer true.
- `tests/test_config.py`: 7 tests covering reachable, unreachable, three non-BA response shapes, logged in, and first run (both with no probe).
- Deviation: `main` has no AI-settings fields, so the planned "anonymous AI fields → 401" test doesn't apply on this branch. `feat/ai-ingredient-images` keeps its own separate AI login check (after the gate), so that branch stays safe once it rebases onto this fix.
- Live check on port 5001, with `.env` set to `http://bar-assistant:8080/`: anonymous save of `http://gimli.home:8082/api` → 200; login with bogus credentials → BA's own "Unable to authenticate" 400, which shows the request now reaches gimli; then an anonymous repoint → 401 "Log in to change server settings.".

## Plan Change Log

## Review Triage Log

### 2026-11-06 — Review pass
- verdicts: 8 findings — high 1, medium 1, low 5, false 1, maybe-false 0
- findings:
  - `[medium]` `[patch]` The probe's 5s timeout is shorter than login's 15s, so a slow but working BA opens the gate. — Real: `_ba_reachable` uses timeout=5 and `login()` uses 15. Moot, because the intent_gap below reverted the code.
  - `[high]` `[intent_gap]` Prod is HTTPS through Cloudflare, so any BA outage (Watchtower restart, redeploy, blip) lets an anonymous internet client repoint `BA_API_URL` and harvest the next login's credentials. — Real: the `app.py` cookie comment confirms prod is behind Cloudflare, and the gate now opens whenever the probe fails. The intent-contract Approach rested on a LAN-only premise. Choosing among the safe alternatives is the user's decision. (Patch since deleted; approach rejected.)
  - `[low]` `[reject]` Each anonymous POST /config makes an outbound probe (DoS). — Anonymous outbound proxying already exists (`/api/auth/login` at 15s, `/api/server/version`), so this adds no new class of exposure. Fixing it would mean adding rate limiting.
  - `[false]` `[reject]` `r.ok` accepts 1xx/3xx. — requests follows redirects, so the final status is never 3xx and 1xx never reaches the caller. A version payload is still required.
  - `[low]` `[defer]` No test pins the anonymous AI-field 401 for after the branches merge. — The deviation is documented. The check lives on `feat/ai-ingredient-images`.
  - `[low]` `[intent_gap]` `api_token` is also writable anonymously while BA is down, beyond the planned "URL/bar" scope. — Real (`set_config` writes `BA_API_TOKEN`; it is only read by the startup log). Which fields to open belongs in the same decision as the high finding.
  - `[low]` `[reject]` The test imports `Resp` from another test module. — It matches the existing `tests/test_ai_image.py` pattern.
  - `[low]` `[defer]` The setup wizard's `saveUrl` hides the server's 401 message behind "Could not reach that URL". — Pre-existing and not touched by the diff.

## Verification

**Commands:**
- `/home/scott/develop/sugar-rim/.venv/bin/python -m pytest -q` (in the worktree) -- expected: all pass, including the new tests
- `uvx ruff check app.py tests/test_config.py` -- expected: no new findings

**Manual checks (if no CLI):**
- Start the worktree app on a spare port, with `.env` pointing at an unreachable URL, and run the first AC through the HTTP surface (`POST /config`, then `POST /api/auth/login` reaching gimli).

## Auto Run Result

Status: blocked
Blocking condition: intent gap. The chosen approach (open the gate whenever the configured BA is unreachable) lets anyone on the internet repoint the URL during a BA outage, because prod is exposed through Cloudflare. The code is reverted. The working patch was discarded.

Unanswered questions:
1. Should an anonymous URL change be allowed only when the instance is accessed locally (localhost/LAN, not through Cloudflare)? If so, how can the app tell, given that a tunnel may present a private remote_addr?
2. Or should a URL seeded by the environment (docker) stay always gated, with only a UI-saved URL openable while unreachable?
3. Or should the fix be a clearer error and an "edit .env / restart" recovery path, leaving the gate strict?
4. If anonymous changes are opened in any form, should they cover only `api_url`, or also `bar_id`/`api_token`?

Files: none changed (worktree /home/scott/develop/sugar-rim-fix on branch fix/settings-url-lockout is clean at the baseline).
Verification before the revert: 86 tests passed; ruff showed no new findings; live HTTP check passed on port 5001.

### 2026-11-06 — Resolution (user chose option 1)

The gate stays strict. Instead, the errors now explain how to recover: the `/config` 401 and the login failures (BA unreachable, or a non-BA reply) name `BA_API_URL` in `.env` (`/config/.env` in Docker) and say to restart. Implemented uncommitted in worktree `/home/scott/develop/sugar-rim-fix` (`app.py`, plus new `tests/test_config.py` with 4 tests); 83 tests pass and ruff shows no new findings. The superseded patch was deleted.
