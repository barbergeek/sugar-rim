---
title: 'Holiday menu board picks up a cocktail photo added or replaced after publishing'
type: 'bugfix'
created: '2026-11-21'
status: 'done'
baseline_revision: '17f90815cc476b49b98fe72d3b9b11bf98af0a1f'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: []
deferred:
  - summary: >-
      Photos added or replaced outside sugar-rim (Salt Rim / BA API) still need a republish to reach the board.
    evidence: |-
      Only a sugar-rim PUT /api/cocktails/<cid> triggers _refresh_menu_photo; no hook sees BA-native edits. Intent ("created ... after the menu is displayed") does not exclude them.
    location: >-
      app.py update_cocktail
    severity: medium
  - summary: >-
      After a rename changes the slug, saves of that cocktail no longer refresh its board photo until republish.
    evidence: |-
      BA Cocktail uses spatie sluggable generateSlugsFrom(name, bar_id) with no doNotGenerateSlugsOnUpdate, so renames regenerate the slug; the snapshot is matched by slug only and stores no id (public).
    location: >-
      app.py _refresh_menu_photo
    severity: medium
---

<intent-contract>

## Intent

**Problem:** The TV board (`/menu`) and recipe pages (`/menu/r/<slug>`) serve a snapshot whose photos are copied only at publish time, so a cocktail image created or regenerated in sugar-rim after the menu is published never appears on the board. Even after a republish, the photo URL `/menu/img/<slug>` never changes and is cached for 300 s, so a replaced photo can stay stale on the TV.

**Approach:** When a cocktail is saved through sugar-rim (`PUT /api/cocktails/<cid>` succeeds) and that cocktail is on the published snapshot, re-copy just its photo into the snapshot. Version the photo URL with a content hash so browsers fetch the new file.

## Boundaries & Constraints

**Always:** Only the saved cocktail's `image`/photo fields in the existing snapshot change: title, subtitle, theme, drink order, text and `published_at` stay as published (unpublished list/title/theme edits must not leak to the board). The cocktail save response is returned unchanged; a photo-refresh failure is logged and leaves the old photo, never turning a successful save into an error. The snapshot stays free of BA ids and users (public).

**Never:** No full republish on cocktail save. No live BA calls from the public `/menu*` routes. Not covering images changed directly in Bar Assistant's own UI (no sugar-rim hook sees those; a manual republish still picks them up). No frontend JS changes.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Photo added | Published drink had no photo; PUT gives it image | Board renders `<img>` for it; `/menu/img/<slug>` serves new bytes | — |
| Photo replaced | Published drink's image regenerated | `/menu/img/<slug>` serves new bytes; `src` carries a different `?v=` | — |
| Photo removed | Saved cocktail now has no images | Snapshot entry drops its photo; board shows the initial | — |
| Not on menu | PUT for a cocktail absent from the snapshot | Snapshot file untouched | — |
| No snapshot | Menu never published | Nothing written | — |
| PUT fails | BA returns non-2xx | No refresh attempted; BA error returned as before | — |
| Refresh fails | Detail lookup/photo download fails after a good PUT | Save response unchanged; old photo kept | Logged warning |

</intent-contract>

## Code Map

- `app.py:436` `update_cocktail` -- proxies PUT to BA via `proxy()` (`app.py:163`, returns `(jsonify(data), status)`); hook the refresh after a 2xx.
- `app.py:657` `_menu_photo(img)` -- reuse: downloads the full-size photo, thumbnail fallback.
- `app.py:673` `_publish` -- reference for how photos are written (`menu.image_name(slug)` in `menu.menu_dir(ENV_PATH)`); set the same version field here so republished photos are versioned too.
- `menu.py:184-228` `load` / `save` / `find` -- snapshot I/O; `save` deletes `.jpg` files no longer referenced, so dropping `image` cleans the file.
- `templates/menu.html:157`, `templates/menu_recipe.html:62` -- `<img src="/menu/img/{{ c.slug }}">`; append `?v=` when the version field exists (old snapshots without it render as before).
- `app.py:911` `menu_image` -- unchanged; ignores the query string.
- `static/js/app.js:2005-2030` -- read-only evidence: the cocktail form uploads the new image, PUTs `images: [newId]`, then deletes old images, so the PUT is the moment the new photo is attached.
- `tests/test_menu.py` -- `FakeBA` (GET only; `/api/cocktails/<slug>` lookup), `publish`, `listed` fixtures to extend.

## Tasks & Acceptance

**Execution:**
- `app.py` -- add a helper that, given a cocktail id, loads the snapshot, fetches the cocktail with `include=images`, finds its snapshot entry by slug, rewrites/clears that entry's photo + version via `_menu_photo`, and saves; call it from `update_cocktail` after a 2xx, catching and logging failures. Record the version in `_publish` too. -- the fix.
- `menu.py` -- add a small content-hash version helper if it keeps app.py tidy. -- shared by publish and refresh.
- `templates/menu.html`, `templates/menu_recipe.html` -- add `?v={{ c.image_v }}` when present. -- cache busting.
- `tests/test_menu.py` -- tests for each I/O matrix row (fake PUT + detail GET in `FakeBA`). -- regression coverage.

**Acceptance Criteria:**
- Given a published menu where a drink has no photo, when that cocktail is saved via `PUT /api/cocktails/<id>` with a new image, then `GET /menu` shows an `<img>` for it without republishing.
- Given a published menu and an unpublished theme change, when a listed cocktail is saved, then `GET /menu` still shows the old theme.

## Spec Change Log

## Review Triage Log

### 2026-11-21 — Review pass
- verdicts: 27 findings — high 1, medium 7, low 11, false 6, maybe-false 2
- findings:
  - `medium` `patch` (blind) Lost update: snapshot loaded before network work, a publish in between gets overwritten and its photos deleted — fixed: lookup/download first, then load→modify→save with no network between.
  - `low` `patch` (blind) Photo overwritten in place; mid-write read or failed write corrupts the served file — fixed: write `.tmp` then `os.replace`.
  - `medium` `defer` (blind) Rename that regenerates the slug silently skips refresh — BA sluggable regenerates on update (verified on gimli); matching needs a non-public id mapping; deferred.
  - `low` `reject` (blind) Every save on a menu cocktail re-downloads the photo — BA is on the same LAN on gimli; unlikely to be felt; skip-if-unchanged adds branches.
  - `low` `reject` (blind) Broad except hides bugs (AttributeError/TypeError) — user outcome identical (save succeeds); narrowing risks 500s on a succeeded save.
  - `low` `reject` (blind) User not told when menu photo refresh fails — adds response surface; failures are logged.
  - `low` `reject` (blind) Versioned photo URLs could be cached immutable — optimisation, not a defect.
  - `false` `reject` (blind) DELETE /api/images doesn't refresh — no UI path deletes a cocktail image outside the replace flow (grep of static/js/app.js: deletes only follow a successful PUT).
  - `low` `reject` (blind) Weak/missing tests (id assertion, FakeBA.request assert message) — the id assertion guards the spec's no-ids-in-snapshot rule; message clarity is cosmetic.
  - `low` `reject` (blind) Docs don't say photo updates live while text needs republish — docstring states it; no user doc covers menu internals.
  - `medium` `defer` (edge) Rename changes slug → refresh skipped — same root cause as the blind rename finding; deferred.
  - `false` `reject` (edge) Empty BA slug falls back to str(id) — BA slugs are always generated (sluggable on name); never empty.
  - `medium` `patch` (edge) Concurrent publish/save read-modify-write — same root cause as blind lost update; fixed by the reorder.
  - `low` `patch` (edge) In-place write truncation/partial refresh — same root cause as blind in-place write; fixed by tmp+replace.
  - `low` `reject` (edge) Synchronous refresh can delay save up to ~60s — only when BA is slow/unreachable, which already slows the PUT itself.
  - `false` `reject` (edge) Entry lacking "slug" raises KeyError → 500 — every snapshot entry comes from slim_cocktail, which always sets slug.
  - `maybe-false` `reject` (edge) Claim: concurrent publish can revert title/theme — after the reorder the load→save window has no I/O beyond local disk; would only be low if real.
  - `maybe-false` `reject` (edge) Claim: save failure leaves new bytes under old image_v — would need menu.save to fail after os.replace; at most a 300 s stale cache, low.
  - `medium` `patch` (verification-gap) OSError path untested — fixed: `disk` case added to test_a_failed_refresh_keeps_the_old_photo.
  - `low` `patch` (verification-gap) Photo written before snapshot save — same root cause as in-place write; fixed.
  - `medium` `defer` (verification-gap) Slug change skips refresh — same root cause as rename; deferred.
  - `low` `reject` (verification-gap) Broad catch hides missed guards — same as blind broad-except; rejected.
  - `medium` `defer` (intent) Photos changed outside sugar-rim (Salt Rim/BA) not picked up — not caused by this change; intent does not exclude it; deferred.
  - `high` `patch` (intent) Ordering: refresh runs before the SPA deletes the old image; BA attachImages keeps old attached and both have sort=1, so images[0] is the old photo on regenerate — verified in BA source on gimli (HasImages::attachImages, images() orderBy sort; app.js uploads sort=1); fixed: pick the image whose id is first in the PUT body's `images`; regression test added.
  - `false` `reject` (intent) New photo shows only after the board's 5-minute reload — matches the board's existing reload design; "never shows" is what was broken.
  - `false` `reject` (intent) Narrowing to the photo field is an unstated scope choice — existing tests pin that title/theme reach the board only on publish; refreshing the photo alone preserves that.
  - `false` `reject` (intent) Pre-change snapshots lack `?v=` — the next republish or save versions them; no lasting harm.

## Design Notes

Hooking the save rather than polling BA keeps public routes BA-free and matches the snapshot model: only the photo, the one thing the user expects to "just appear", bypasses republish. Content hash (not BA image id) as the version keeps ids out of the public snapshot.

## Verification

**Commands:**
- `source .venv/bin/activate && pytest -q` -- expected: all pass
- `ruff check . && ruff format --check app.py menu.py tests/test_menu.py` -- expected: clean

## Auto Run Result

Status: done

**Summary:** Saving a cocktail in sugar-rim now re-copies its photo into the published holiday-menu snapshot when the drink is on it (photo only; unpublished title/theme/order edits still wait for publish). Board and recipe photo URLs carry a content-hash `?v=` so a replaced photo is refetched.

**Files changed:**
- `app.py` — `update_cocktail` calls new `_refresh_menu_photo(cid, image_ids)` after a 2xx; `_publish` records `image_v`.
- `menu.py` — `image_version()` content hash.
- `templates/menu.html`, `templates/menu_recipe.html` — `?v=` on photo URLs when present.
- `tests/test_menu.py` — fake PUT/detail in FakeBA; 11 new tests covering every matrix row, regenerate ordering, and disk failure.

**Review:** 27 findings. Patched 4 entries (1 high: regenerated photo picked the old image; 2 medium: lost update vs publish, missing OSError test; 1 low: in-place photo write). Deferred 2 (outside-sugar-rim photo changes; slug change after rename). Rejected 19 low/false/maybe-false with reasons in the triage log.

**Follow-up review recommended:** true — a `high` was patched; the fix relies on BA attaching (not replacing) images on PUT, verified from BA v5 source but only exercised against the fake BA, not a real regenerate on the TV.

**Verification:** `pytest -q` → 223 passed. `ruff check` → only pre-existing F401 (`url_for`, app.py:15). `ruff format --check` → app.py and tests/test_menu.py fail identically at baseline 17f90815cc476b49b98fe72d3b9b11bf98af0a1f (pre-existing).

**Residual risks:** a failed `.tmp` write leaves a harmless stray file; if `menu.save` fails after the photo swap, browsers may show the old cached photo up to 300 s.
