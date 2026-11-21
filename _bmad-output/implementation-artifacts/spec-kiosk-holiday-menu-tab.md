---
title: 'Kiosk Holiday Menu tab: one tap to the menu drinks'' recipes'
type: 'feature'
created: '2026-11-21'
status: 'done'
baseline_revision: 'b34b94d6a9350ae1b4cbda00b92266a7f694d638'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred:
  - summary: >-
      The kiosk Menu tab (nav button, view switch, cards, empty/error states, stale-load guard) has no automated test.
    evidence: |-
      No JS or browser test harness exists in the repo (package.json has only Prettier scripts); only the /api/menu/drinks route is tested. Inline script checked with node --check only.
    location: >-
      templates/kiosk.html KioskMenu.load
    severity: low
---

<intent-contract>

## Intent

**Problem:** On bar-pi (the `/kiosk` touchscreen behind the counter) there is no quick way to reach the holiday menu's drinks. The bartender has to search for each drink by name. The Holiday Menu screens are admin-only phone UI, and the public `/menu` board isn't linked from the kiosk.

**Approach:** Add a **Menu** tab to the kiosk nav. It lists the holiday menu's drinks, in menu order, as the kiosk's usual cocktail cards. Tapping a card opens the kiosk's normal recipe view, with units, servings and shelf dots, and **← Back** returns to the list.

## Boundaries & Constraints

**Always:**
- **Data source:** the drinks are the saved menu list (`_menu_list()["cocktail_ids"]`), in that order.
  - Every drink add, remove or set republishes, so these match the board.
  - Drinks deleted in BA are left out, the same as `_menu_cocktails`.
- **Access:** any logged-in user can read the list, not just admins and moderators. The kiosk's BA user may be a plain member, and drink names are already public on the board. Logged out gets 401, like the other `/api` routes.
- **Reuse, don't copy:** use the existing card renderer `Cocktails._card` and `Cocktails._enrichCards`, the existing detail view `App.cocktails.open(id)`, and `KioskScroll` drag-to-scroll.
- **Fresh data:** the list reloads every time the tab is opened, so menu edits made on the phone show up.
- The tab shows every menu drink, whether or not it's on the shelf. The kiosk's "Shelf only" toggle doesn't apply.

**Never:**
- No change to the phone UI (`templates/index.html`).
- No change to the public `/menu*` pages or to the admin Holiday Menu.
- No menu editing from the kiosk.
- No BA calls without the session token.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Menu has 5 drinks; kiosk user is a member (role 3) | `GET /api/menu/drinks` returns 200, `title`, and `data` holding the 5 cocktails in list order, with `images` and `ratings` included; the tab shows 5 cards | — |
| Deleted drink | One listed id is no longer in BA | That drink is left out, and the rest keep their order | — |
| Empty / never set up | No list and no snapshot, or the list is empty | 200 with `data: []`; the tab says there are no drinks on the holiday menu yet | — |
| Logged out | No session | 401 `{"error":"unauthorized"}` | — |
| BA down | The cocktail lookup fails | 502 JSON error; the tab shows the error text in its empty state | Shown inline |

</intent-contract>

## Code Map

- `app.py`, about line 785, by the `/api/menu` routes: add `GET /api/menu/drinks`.
  - Check `_logged_in()` and return 401 otherwise. Don't use `@_menu_route`, which is admin and moderator only.
  - Read `stored = _menu_list()`. Return `{"title": stored["title"], "data": _menu_cocktails(stored["cocktail_ids"], include="images,ratings")}`.
  - Catch `MenuError` (its `.status`) and `BA_ERRORS` (502) as JSON errors, the same way `_menu_route`'s wrapper does.
  - `_menu_cocktails` (about line 595) already orders the drinks, drops missing ones, and raises `MenuError(...,502)` on a failed lookup. `_menu_list` (568) seeds itself from the snapshot on first run.
- `templates/kiosk.html`:
  - **Nav (about line 255):** add `<button class="nav-btn" data-view="holiday-menu" onclick="App.nav.go('holiday-menu');KioskMenu.load()">` with icon `celebration` and label `Menu`. Put it after Favorites. Maintenance uses the same pattern. The nav is `flex:1` per item, so a 6th fits.
  - **New section:** `<section id="view-holiday-menu" class="view">`, modelled on `#view-favorites` (about line 88). It has a `.view-toolbar` with `<span class="toolbar-title" id="hm-kiosk-title">`, then `<div id="holiday-menu-list" class="card-grid">` and `<div id="holiday-menu-empty" class="empty-state hidden"><p></p></div>`.
  - **New `KioskMenu` object** next to `KioskShelf`. Its `load()`:
    - shows the spinner row, as `Favorites.load` does (`app.js` about line 2074)
    - calls `get('/api/menu/drinks')`
    - sets the title, falling back to "Holiday Menu"
    - renders `d.data.map(c => Cocktails._card(c))`, then `await Cocktails._enrichCards(d.data)`
    - shows the empty state, or the error message on failure
    - drops a response that is no longer the latest, using a sequence counter like `KioskApp._seq`
  - **Scrolling:** add `'holiday-menu-list'` to the id list in `KioskScroll.enableAll()` (about line 718).
- `static/js/app.js`, read only:
  - `Nav.go` override (about line 4276): a view that isn't hooked there needs nothing. Login gating already applies.
  - `Cocktails._card` (1365): its onclick runs `App.cocktails.open(id)`, which pushes the history, so Back returns to `holiday-menu`.
- `static/css/style.css`: `.kiosk-mode .card-grid` (about line 2057) already styles the grid. No change is expected.
- `tests/test_menu.py`: `FakeBA` and fixtures (`listed`, login helpers). Add route tests here.

## Tasks & Acceptance

**Execution:**
- `app.py`: add the `GET /api/menu/drinks` route per the Code Map. This gives the kiosk a menu list that any logged-in user can read.
- `templates/kiosk.html`: add the nav button, the section, `KioskMenu`, and the `enableAll` id. This is the kiosk entry point.
- `tests/test_menu.py`: add tests for each I/O matrix row except the UI half: happy path with a member role (order plus include param), deleted drink, empty, logged out, and BA failure. These are the regression tests.

**Acceptance Criteria:**
- Given a holiday menu with drinks, when the bartender taps **Menu** on the kiosk nav, then a card for each menu drink appears in menu order, and tapping one opens its full kiosk recipe view. **← Back** returns to the Menu list.
- Given a drink added to the menu on the phone, when the kiosk Menu tab is opened again, then the new drink is listed without reloading the page.

## Spec Change Log

## Review Triage Log

### 2026-11-21 — Review pass
- verdicts: 22 findings — high 0, medium 0, low 16, false 6, maybe-false 0
- findings:
  - `low` `patch` (blind) `_enrichCards` sends a detail GET per uncached card though the payload already has images/ratings — removed the call from `KioskMenu.load`.
  - `low` `reject` (blind) "Holiday Menu" fallback never shows; a never-set-up menu titles the toolbar "Menu" — still a sensible title over the empty message; a fix adds a special case.
  - `low` `reject` (blind) `KioskMenu.load()` runs when logged out and leaves "unauthorized" in the hidden view — same as Maintenance's pattern; the kiosk stays logged in and the next tap reloads.
  - `low` `reject` (blind) A member's GET can seed and write list.json on first run — writes exactly what an admin's first visit writes; one-time, and list.json already exists on gimli.
  - `low` `patch` (blind) Docstring's access reason ("names are public") understates what is returned — reworded to describe the saved list's full cocktails and why members may read them.
  - `low` `reject` (blind) Access tests cover only role 3 — the route never reads the role; extra parametrization guards nothing the code branches on.
  - `low` `patch` (blind) include-param assertion matched any GET — now asserts on the call with `filter[id] == "2,1,3"`.
  - `low` `reject` (blind) Raw exception text shown on the kiosk on BA errors — matches every other kiosk error toast; a friendly mapping adds branches.
  - `low` `reject` (blind) No retry control after a 502 — tapping Menu again reloads (load runs on every open).
  - `false` `reject` (blind) Six nav items may not fit at scale factor 2 — bar-pi runs `--force-device-scale-factor=1.5` (checked in ~/.config/labwc/autostart): 1280 CSS px ÷ 6 ≈ 213 px per item, and labels are short ("List", "Menu").
  - `low` `patch` (edge) Redundant per-card detail fetches — same root as the blind `_enrichCards` row; fixed by removing the call.
  - `false` `reject` (edge) A stale enrich fills same-id slots in other grids — moot once `_enrichCards` is gone; the card payload creates no slots.
  - `low` `reject` (edge) BA_BAR_ID unset gives a "lookup failed" 502, not "No bar selected" — the kiosk only runs against a configured bar; the message still surfaces.
  - `low` `reject` (edge) OSError from the seeding `save_list` gives an HTML 500 — one-time seed path, disk failure only; same as the admin routes.
  - `low` `reject` (edge) Concurrent first-run seeding shares list.json.tmp — pre-existing in `menu.save_list`, and only before list.json exists (it exists on gimli).
  - `false` `reject` (edge) list.json missing `title` raises KeyError — every writer (`save_list` callers) stores title; `_menu_state` reads `stored["title"]` the same way.
  - `low` `patch` (edge) `#view-holiday-menu` grid gets none of the Favorites layout rules — added `#view-holiday-menu` beside `#view-favorites` in all five list-grid selectors.
  - `false` `reject` (edge) Only role 3 tested — duplicate of the blind role finding; the route has no role branch.
  - `low` `patch` (verification-gap) The BA-unreachable (`BA_ERRORS`) branch was untested — test parametrized over 5xx and unreachable (ConnectionError).
  - `low` `defer` (verification-gap) Kiosk Menu tab UI has no automated test — no JS/browser harness in the repo; deferred.
  - `false` `reject` (intent) Reading B (link to the public /menu/r pages) not taken — the kiosk detail view (units, servings, shelf dots) better serves "make them behind the counter"; recorded in Design Notes.
  - `false` `reject` (intent) Kiosk reads the saved list, board reads the snapshot — every drink add/remove/set republishes (`_save_and_publish`), so the drink lists match; only an unpublished title can differ.

## Design Notes

A tab of the kiosk's own was chosen over linking to the public `/menu/r/<slug>` pages. Those pages are guest-facing and fixed at publish time. The kiosk detail view adds what someone making the drink needs: oz/ml, a servings scaler and shelf dots. It also matches how the rest of the kiosk works.

## Verification

**Commands:**
- `source .venv/bin/activate && pytest -q`: expected, all pass.
- `ruff check app.py`: expected, only the pre-existing F401 (`url_for`).
- `npm run format:check`: expected, clean.

**Manual checks (if no CLI):**
- Run the kiosk.html inline script through `node --check` (extract it first), or load `/kiosk` locally: the Menu tab lists the drinks, and a card opens the detail view.

## Auto Run Result

Status: done

**Summary:** The kiosk (bar-pi) has a **Menu** tab after Favorites. It lists the holiday menu's drinks in menu order as the kiosk's usual cocktail cards, and a tap opens the normal kiosk recipe view (units, servings, shelf dots), with ← Back returning to the list. A new `GET /api/menu/drinks` serves the saved menu list to any logged-in user, so the kiosk's BA user doesn't need admin or moderator rights.

**Files changed:**
- `app.py` — new `GET /api/menu/drinks` (login required, any role; JSON errors).
- `templates/kiosk.html` — Menu nav button, `#view-holiday-menu` section, `KioskMenu.load()` (reloads on every open, stale-load guard), drag-scroll id.
- `static/css/style.css` — `#view-holiday-menu` joins the Favorites list-grid and card-height rules.
- `tests/test_menu.py` — 6 route tests (member access and order, deleted drink, empty, logged out, 5xx and unreachable BA).

**Review:** 22 findings. Patched 6 low entries (redundant per-card fetches, grid layout, docstring, loose include assertion, untested unreachable branch). Deferred 1 (no UI test harness). Rejected 15 with reasons in the triage log.

**Follow-up review recommended:** false — no high or medium entries were patched (patched: 6 low).

**Verification:** `pytest -q` 248 passed; `ruff check app.py` only the pre-existing F401 (`url_for`); `npm run format:check` clean; kiosk inline script `node --check` ok.

**Residual risks:** not yet tapped through on the bar-pi itself.
