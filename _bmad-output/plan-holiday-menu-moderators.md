---
title: 'Holiday menu: admins and moderators manage it; menu list lives in sugar-rim'
type: 'feature'
ticket: ''
created: '2026-11-16'
status: 'built'
baseline_revision: '1281efde6b5ab23427d93778166787bfcf8e699c'
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

**Problem:** The holiday menu's drinks live in a Bar Assistant collection, and BA lets only a collection's owner read or edit it, so a Moderator (Parker) gets "Collection not found" and can't manage the menu. Meanwhile sugar-rim lets any logged-in user, even General/Guest, manage it.

**Approach:** Store the menu (title, subtitle, ordered cocktail ids) in sugar-rim next to the published snapshot instead of in a BA collection, and allow every menu action only for users whose role in the bar is Admin (1) or Moderator (2).

## Boundaries & Constraints

**Always:**
- Role comes from BA `GET /bars/{BA_BAR_ID}` → `data.access.role_id`, using the session user's token, checked on every gated request (no caching, so role changes apply at once).
- Gated: all `/api/menu*` routes and the `/config` keys `menu_page_seconds`, `menu_suggest_model`, `typesafe_api_key`. Not logged in → 401 as today. Logged in, other role → 403 `{"error": "Only bar admins and moderators can manage the holiday menu"}`.
- Menu cap (12), duplicate removal, and auto-republish after drink changes behave as today.
- One-time seed: if no stored menu list exists but a published snapshot does, seed title/subtitle from the snapshot and cocktail ids by resolving each snapshot slug through BA `GET /cocktails/{slug}`. Slugs that don't resolve are dropped.
- Writes to the stored list are atomic, as `menu.save` already does.

**Never:**
- No change to the public board (`/menu`, `/m/<n>`, `/menu/r/<slug>`, `/menu/img/<slug>`) or to snapshot cocktail shape.
- Don't touch BA collections, `/api/collections*` proxies, or other settings' auth (AI image keys etc. stay login-only).
- Don't delete `MENU_COLLECTION_ID` from anyone's `.env`; it's simply no longer read.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Moderator manages | role 2; add/remove drink, rename, publish, suggest+approve | Works exactly as for Admin | — |
| General/Guest | role 3/4; any `/api/menu*` or gated `/config` key | 403 with the message; nothing written | UI shows message, hides controls |
| Role lookup fails | BA `/bars/{id}` errors or no `BA_BAR_ID` | Treated as not permitted | 403 (or existing "No bar selected" 400) |
| First run after upgrade | snapshot with 3 drinks, no list file | `/api/menu` shows those 3 drinks and the snapshot title | Unresolvable slug skipped |
| Fresh install | no snapshot, no list | Empty menu titled "Menu" | — |
| Remove last drink | list becomes empty | List saved empty; board keeps last publish; `publish_error` explains | — |
| Cocktail deleted in BA | stored id no longer returned | Not shown; dropped from list on next save | Publish skips it |

</frozen-after-approval>

## Code Map

- `app.py:679-692` `_menu_route` -- add role check (403) after the login check.
- `app.py:221-235` `set_config` -- extend the menu-key guard to require the role.
- `app.py:535-598` `_set_env`, `_menu_collection_id`, `_ba_collection`, `_collection_drinks`, `_collection_ids`, `_menu_state` -- replace collection reads with the stored list. Drink names via BA `GET /cocktails?filter[id]=1,2,…&per_page=100` (verified on BA v5.15.4); keep stored order. `_menu_state` returns `menu: {title, subtitle, drinks, cocktail_ids}` in place of `collection`/`collection_error`.
- `app.py:643-676` `_publish` -- build from stored ids (same `filter[id]` + `include=images,glass,method,ingredients.ingredient`, reordered to list order); title/subtitle from the list; drop `collection_id` from the snapshot.
- `app.py:707-795` routes -- `menu_choose_collection` becomes `POST /api/menu/title {title, subtitle}`; `menu_publish` takes no collection id; `menu_toggle_cocktail`/`menu_set_cocktails`/`_sync_and_publish` write the list then publish. Keep `MenuError`/`BA_ERRORS` handling.
- `menu.py:184-202` `load`/`save` -- add `load_list`/`save_list` for `menu_dir/list.json` (`{title, subtitle, cocktail_ids}`), atomic via tmp + `os.replace`, creating the dir. `save` deletes unreferenced `*.jpg` only, so `list.json` is safe.
- `static/js/app.js:3447-3810` `HolidayMenu` -- replace the collection picker (`_fillMenuCollections`, `chooseMenu`, `createMenu`, `/api/collections` fetch in `_loadMenu`) with Title/Subtitle inputs + Save; read `state.menu` instead of `state.collection`; `publishMenu` sends only `public_base`; `approveSuggestion` saves a changed name via `/api/menu/title`. On a 403 from `/api/menu`, show the error message in place of the controls.
- `static/js/app.js:1571-1630` cocktail detail pill (`_loadMenu`, `_syncMenuBtn`, `toggleMenu`) -- read `_menu.menu`; hide the pill when `/api/menu` fails (403).
- `static/js/app.js:4-17` `api()` -- already throws `data.error` for non-401 errors; no change.
- `tests/test_menu.py` -- `FakeBA` (64-117) needs `/bars/1` (role configurable), `/cocktails?filter[id]`, and `/cocktails/<slug>`; fixtures `env`/`owner`/`guest` (113-142) gain a role. Collection-specific tests (choose/create collection, collection-cannot-load) are rewritten for the list.

## Tasks & Acceptance

**Execution:**
- [ ] `menu.py` -- add `load_list`/`save_list` -- sugar-rim-owned menu storage.
- [ ] `app.py` -- role helper + gate in `_menu_route` and `set_config`; list-based state, seed, publish, title route; remove collection helpers this makes unused -- core change.
- [ ] `static/js/app.js` -- Holiday Menu title/subtitle editor, `state.menu`, 403 handling in modal and detail pill -- UI follows the API.
- [ ] `tests/test_menu.py` -- update fakes/fixtures; tests for each I/O matrix row, including role 2 allowed, roles 3/4 refused (routes and `/config` keys), seeding from a snapshot, and order preserved in the published board.

**Acceptance Criteria:**
- Given Parker (Moderator) is logged in, when they open Manage → Holiday Menu, then they see the current menu's drinks and can add, remove, rename, suggest, and publish, and the public board updates.
- Given a General user is logged in, when they open Holiday Menu or a cocktail's detail, then they see "Only bar admins and moderators can manage the holiday menu" and no menu controls or "on menu" pill.
- Given production's current published "Thanksgiving Cocktails" menu (3 drinks), when an Admin first opens Holiday Menu after upgrade, then the same 3 drinks and title appear.

## Implementation Notes

## Plan Change Log

## Review Triage Log

### Pass 1 (quick lens) — high 0 · medium 0 · low 4 · false 2 · maybe-false 0 · (+1 found in my own diff read)

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 0 | `hm-add` search stays `display:none` after picker removal (own diff read) | high | patch | Only line revealing it was deleted; no other reference. Removed `display:none` in `_html`. |
| 1 | `menu_set_title` keeps BA-deleted ids in list.json | low | patch | Matrix says dropped "on next save"; one-line fix to resolve ids before save. Sent to implementer. |
| 2 | Toggle adds a nonexistent id without checking BA | low | reject | UI only offers ids from BA search; a phantom id is filtered from state and board and not counted toward the cap (toggle resolves first). Fix adds a guard. |
| 3 | Seed saves an empty list if every slug 404s | false | reject | All 3 production snapshot slugs return 200 from `GET /cocktails/{slug}` with bar 1; slugs are BA slugs (`menu.py:75`). |
| 4 | Malformed list.json → KeyError 500 | low | reject | Only reachable by hand-editing the file; fix adds guards. |
| 5 | Stale comments (app.py section header, menu.py docstring) | low | patch | Orphans of this change; direct correction. Sent to implementer. |
| 6 | approveSuggestion can rename then fail on set | low | reject | Same ordering as before the change (collection created first); rare failure, fix reorders calls with its own title/publish trade-off. |
| 7 | One failed `/api/menu` hides the detail pill until reload | low | reject | Plan specifies hiding on failure; only visible during a BA outage. |
| 8 | AC2 message not shown on cocktail detail | false | reject | Code map defines detail behaviour as "hide the pill"; the message appears in Holiday Menu, and the detail shows no pill, satisfying AC2. |

## Design Notes

Why a file, not a BA collection or a shared token: collections are owner-only in BA (`CollectionPolicy` show/edit require the owner's bar membership), and a shared token would make every menu edit run as one user. The snapshot already lives in `menu_dir`, so the editable list sits beside it.

Role lookup example:
```python
r = http.get(ba_url(f"/bars/{bid}"), headers=auth_headers(), timeout=10)
role = ((r.json().get("data") or {}).get("access") or {}).get("role_id") if r.ok else None
allowed = role in (1, 2)
```

## Verification

**Commands:**
- `.venv/bin/python -m pytest -q` -- expected: all pass
- `npm run format:check` -- expected: clean
- `.venv/bin/python -m ruff check .` (install ruff into the venv if missing) -- expected: clean

**Manual checks (if no CLI):**
- Local instance against gimli: log in as Scott, then as Parker; menu loads, edits, publishes for both.
