---
title: 'Remember menu-suggestion judgments so a repeat occasion only judges new or changed drinks'
type: 'feature'
created: '2026-11-23'
status: 'done'
baseline_commit: '93203a095f2b42256e2735846159bda9860ce654'
route: 'dispatch'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every **Suggest a Menu** run judges all ~556 candidate drinks from scratch: ~9 s on TypeSafe, ~25-30 s on the chat model, and API cost each time. The chat model also returns a different menu on every run for the same drinks (four different menus in four runs on 2026-11-23). Subroutine #18.

**Approach:** Store each drink's answers per menu theme and engine. On a later run for the same theme and engine, reuse the stored answers for drinks whose recipe the engine would see is unchanged, and only ask about new or changed drinks. The picker (`assess`/`pick`) and the shelf logic don't change. Missing ingredients are still worked out live from the shelf, so shelf changes never need a fresh run.

## Boundaries & Constraints

**Always:**
- **Decision (2026-11-23): stored answers are keyed by the menu theme, not the occasion text.** The theme is the theme dropdown in the Holiday Menu dialog (`menu.THEMES` id, normalized with `menu.theme()`), sent along with the suggestion request.
  - Changing the occasion wording under the same theme reuses the stored answers.
  - The stored entry records the occasion text it was judged with. When that differs from the current text, the popup says so ("N remembered from 'Thanksgiving dinner'"), so you know when to start fresh.
- **Decision (2026-11-23): a "Start fresh" checkbox next to Suggest a Menu.** Ticking it ignores, and then replaces, the stored answers for that theme and engine. Answers never expire on their own.
- **Cache key:** the theme id, plus the engine identity, plus a version of the questions.
  - Engine identity is TypeSafe with its pinned `MODEL`, or the chat engine label, which already names the provider and model.
  - The questions version is a hash of `QUESTIONS` together with `llm_prompt()`. Changing the questions or the model starts a fresh cache on its own.
- **A drink counts as unchanged** when a hash of `drink_state(c)` (exactly what the engine is shown) matches the stored one. Edited recipes are judged again.
- **Stored answers are the raw per-drink answers** that `judge_fn` produces (the shape `assess` reads). Picks are never stored, so `pick()` always runs fresh.
- **Partial runs still count.** Answers judged before a cancel, error or deadline are saved, so the next run continues where this one stopped.
- **Storage:** one JSON file, `suggest-cache.json`, in `menu.menu_dir(ENV_PATH)` beside `list.json`, written atomically (tmp + `os.replace`).
  - Drinks no longer in the collection are pruned on save.
  - Only the 20 most recently used keys are kept.
- **Progress display:** stored answers are streamed as the first "judged" event, so the popup fills at once. The start event adds a `cached` count, and the popup shows "N remembered from last time" next to the judged count.

**Never:**
- No change to how drinks are scored or picked, or to the candidate filter.
- No new dependencies or database; no matching on the occasion text.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First run | No cache for key | All candidates judged; answers saved | N/A |
| Repeat run | Same occasion + engine, 3 drinks added, 1 edited | Only those 4 sent to the engine; same picks as a fresh run would give from the same answers | N/A |
| Wording differs, same theme | "Thanksgiving feast" after "Thanksgiving dinner", theme thanksgiving | Stored answers reused; popup names the stored occasion text | N/A |
| Start fresh | Checkbox ticked | Every candidate judged; stored answers for that key replaced | N/A |
| Engine switched | TypeSafe on → off | Separate cache; chat model judges all | N/A |
| Run cancelled midway | Popup closed after 200 judged | Those 200 saved | Save errors logged, never shown |
| Cache file corrupt/missing | Bad JSON | Treated as empty; run proceeds | Logged |

</frozen-after-approval>

## Code Map

- `menu_suggest.py`
  - `suggest_stream` (~511-570): give it a `cache` argument (a dict of id → `{"fp", "answers"}`) and an `on_save`-style hook, or return the updated cache. It splits `considered` into stored and to-judge, yields the stored answers first, and sends only the to-judge drinks to `judge_fn`.
  - `drink_state` (fingerprint source), `QUESTIONS`, `llm_prompt` (questions version), `MODEL`.
- `app.py`
  - `menu_suggest_route` (~921-958): build the key from `_suggest_engine()` and the request's `theme`, load and save the cache file around the stream (the save goes in the stream's `finally` so partial runs persist), and honor the request's `fresh` flag.
  - `_suggest_engine` (~636): the label already names the chat model; TypeSafe needs `menu_suggest.MODEL` added to the key.
- `menu.py`: `menu_dir`, plus the atomic-write pattern in `save_list` (~351) to copy for the cache file.
- `static/js/app.js` `HolidayMenu`: `suggestMenu` (~3465), stream handling (~3529), `_renderSuggestion` (~3809) for the "remembered" line. `_html` gets the Start fresh checkbox beside the Suggest a Menu button. The request sends `theme: el('cfg-menu-theme').value` and `fresh`.
- `tests/test_menu_suggest.py`: the `jev` fixture counts TypeSafe requests, which is the way to assert that only new or changed drinks are sent.

## Tasks & Acceptance

**Execution:**
- [x] `menu_suggest.py` -- cache key, fingerprint, the stored/to-judge split in `suggest_stream`, the `cached` count in the start event, and returning the merged cache with pruning.
- [x] `app.py` -- load/save `suggest-cache.json` atomically (corrupt = empty), call it from `menu_suggest_route` keyed by theme, save in `finally`, and honor `fresh`.
- [x] `static/js/app.js` -- show "N remembered from last time" (naming the stored occasion text when it differs) while running and when done; add the Start fresh checkbox; send `theme` and `fresh`.
- [x] `tests/test_menu_suggest.py` -- one test per matrix row: a repeat run sends only new or edited drinks; same theme with different wording; per-engine separation; start fresh; partial save; corrupt file.

**Acceptance Criteria:**
- Given a finished run with theme Thanksgiving, when I run it again with nothing changed, then no drinks are sent to the engine and the same menu appears straight away.
- Given the chat engine, when I repeat a run, then the picks match the previous run's picks (the stored answers are reused).

## Verification

**Commands:**
- `source .venv/bin/activate && pytest -q` -- expected: all pass
- `ruff check app.py menu_suggest.py menu.py tests && npm run format:check` -- expected: clean (except the existing unused `url_for` import)

**Manual checks:**
- On the dev server, run "Thanksgiving dinner" twice. The second run says "556 remembered" and finishes in about a second.

## Implementation Notes

- Implemented by a subagent. Stored answers are fed back in stored order, so a repeat run gives the same picks without changing `pick()`; a re-judged drink moves to the end.
- When the stored occasion wording differs, the start event carries `cached_occasion` and the popup names it.

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | blind, edge, vgap | Shared `.tmp` + unlocked read-modify-write in `_save_suggest_cache` | medium | Fixed tmp path; cancel + immediate re-run overlaps saves. patch (unique tmp + lock) |
| 2 | edge | Start fresh + cancel replaces complete answers with a few | medium | `fresh` loads `{}`, save replaces key. patch (merge over old on fresh) |
| 3 | blind, edge | Occasion label keeps old wording after any reuse; None saved if missing | low | `reused[0]` truthiness, not a majority; comment claims majority. patch |
| 4 | blind, edge | Compatible base URL not in identity; keys not bar-scoped (pruning wipes other bar) | low | Label is "AI provider {model}"; key lacks bid. Direct additions. patch |
| 5 | blind | Start fresh checkbox stays ticked → every later run re-judges | medium | Never unchecked in `suggestMenu`. patch |
| 6 | blind | Remembered drinks shown as "Just judged" | low | Stored answers emitted as a normal judged event. patch |
| 7 | vgap | Edited drink moving to cache end untested | medium | Reviewer removed `cache.pop` and all tests passed. patch (test) |
| 8 | blind, edge, vgap | Malformed stored `answers` with matching fp fails every run | low | Only reachable by hand-editing the file: `QUESTIONS` keys are hashed into the cache key. Guard adds branches. rejected |
| 9 | edge | Answers queued at cancel are dropped | low | At most a batch; drain logic adds complexity. rejected |
| 10 | blind | TypeSafe key includes `llm_prompt()` | low | Prompt edits only cost one fresh TypeSafe run. rejected |
| 11 | blind | Classic theme shares answers across unrelated occasions | false | User decision (theme is the key); popup names the stored occasion. rejected |
| 12 | blind | Rewrite whole file even when unchanged | low | ≈ 200 KB/key, 20 keys; negligible. rejected |
| 13 | blind | Checkbox placement / inline styles | low | Inline styles are this file's norm. rejected |
| 14 | edge | Chat scores are batch-relative; cached and newly judged drinks are on different scales | maybe-false (medium) | Prompt asks the model to spread 0-10 across each batch of 20; size of effect unmeasured. defer |
| 15 | vgap | JS sending `theme`/`fresh` untested | maybe-false (medium) | No JS test harness. defer |
