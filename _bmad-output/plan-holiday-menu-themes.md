---
title: 'Holiday menu themes: pick a theme that styles the TV board'
type: 'feature'
ticket: ''
created: '2026-11-17'
status: 'built'
baseline_revision: 'ebc0d3b9523eeab9b692aa6ccc75319c36967107'
route: 'full'
route_source: 'auto'
risk: 'low'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The holiday menu board always wears the same gold-and-brown look, whatever the occasion.

**Approach:** Add a theme choice to Manage → Holiday Menu (saved with the title/subtitle). Publishing copies the theme into the snapshot, and `/menu` applies its colors, title font, badge line ("The bar is open" today), and a drawn SVG emblem (plus an optional ring of small emblems around the badge). 21 themes as previewed at https://claude.ai/artifact/JwMHMN5bhjXTqpdsKxLzD8: Classic (today's look), New Year's Eve, Lunar New Year, Valentine's Day, Mardi Gras, St. Patrick's Day, Easter, Fourth of July, Halloween, Thanksgiving, Hanukkah, Christmas, Game Day, Birthday, Wedding & Anniversary, Winter, Spring, Summer, Autumn, Speakeasy, Neon Night.

**Decisions (2026-11-17):** Keep all 21 themes. The QR recipe page (`/menu/r/<slug>`) gets the full theme too: background from the badge's dark color, accent color on section labels, theme font on the drink name, and the emblem beside the menu title line. Classic leaves the recipe page exactly as it is today. New menus start as Classic and the theme is chosen by hand, with no automatic suggestion. Keep the ring of icons around the badge on the themes that have one.

## Boundaries & Constraints

**Always:**
- Theme `classic` renders the board exactly as today (same colors, Fraunces, "The bar is open", no emblem).
- Unknown, missing, or removed theme id (old snapshots, old `list.json`, bad POST) → `classic`; never an error on the public board.
- Theme definitions live in one place server-side (`menu.THEMES`); the UI dropdown is filled from `/api/menu` state, not a second copy.
- Emblems are inline SVG; fonts load from Google Fonts like today, only the selected theme's font.
- Same role gate as other menu actions (admins/moderators).

**Never:**
- No image files, uploads, or AI-generated art for themes. No animation added to the board.
- No change to layouts, tile text, QR codes, page flipping, or the reload poller.
- No per-user custom colors or theme editor.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Pick a theme | POST `/api/menu/title` with `theme: "halloween"` | Saved in `list.json`; next publish shows Halloween board | — |
| Bad theme id | `theme: "nope"` | 400 "Unknown theme" | Nothing saved |
| No theme sent | POST title without `theme` | Existing theme kept | — |
| Old snapshot | `menu.json` without `theme` | Board renders Classic | — |
| Saved but not published | theme changed, no publish | Board unchanged until publish (like title) | — |
| Striped lines | Christmas / Mardi Gras / Fourth | Grid lines striped; badge ring uses first color | — |

</frozen-after-approval>

## Code Map

- `menu.py` -- add `THEMES` (ordered dict id → name, group `holiday`/`generic`, `line` list, `accent`, `shade` "r,g,b", `badge` [a,b], `font`, `weight`, `scale`, `eyebrow`, `motif`, `halo`, `halo_colors`, `glow`), `MOTIFS` (id → {f, s, rule} 24×24 paths), `theme(id)` → resolved dict (fallback classic) plus derived `line_bg` CSS and `font_url`. Copy values/paths verbatim from the mockup's `THEMES`/`MOTIFS` (`/tmp/claude-1000/-home-scott-develop-sugar-rim/1e191bfe-cf2e-4892-9e41-3fae125f09e0/scratchpad/themes/template.html`; if gone, re-read the artifact URL above). Classic = current `menu.html` values.
- `app.py:561-583` `_menu_list` -- default/seeded list gains `"theme": "classic"`; stored lists without it read as classic.
- `app.py:604-620` `_menu_state` -- `menu.theme` plus `themes: [{id, name, group}]` for the dropdown.
- `app.py:669-698` `_publish` -- write `theme` id into snapshot.
- `app.py:731-743` `menu_set_title` -- accept optional `theme`, validate against `menu.THEMES`, keep existing when absent.
- `app.py:866-878` `menu_board` -- pass `theme=menu.theme(snap.get("theme"))`.
- `templates/menu.html` -- replace hard-coded `--gold`, `--gold-text`, `--shade`, badge gradient, tile fallback, `.page` background, `Fraunces` on `.name`/`.badge h1` with CSS vars from `theme`; font `<link>` from `theme.font_url`; eyebrow text from theme; emblem `<svg>` above `<small>`; halo spans positioned with `calc(50% + cos * var(--m) * .64)` as in the mockup; `.glow` class when set. Keep `.badge i` subtitle in Fraunces italic.
- `app.py:890-896` `menu_recipe` + `templates/menu_recipe.html` -- pass `theme` (non-classic only changes things): `--bg` = `badge[1]`, `--accent`/`--accent2` = theme accent, `h1` in theme font (+ font link), emblem svg inline before `.from` text. Classic: render identical to today.
- `static/js/app.js:3453-3540` `HolidayMenu._html`/`_loadMenu`/`saveTitle` -- add a Theme `<select id="cfg-menu-theme">` (optgroups "Holidays and events" / "Any time of year") under Subtitle; fill from `state.themes`, select `state.menu.theme`; `saveTitle` sends `theme`. Saving it uses the existing Save button.
- `tests/test_menu.py:368-412` -- title-route tests pattern to extend; `FakeBA`/fixtures already in place.

## Tasks & Acceptance

**Execution:**
- [ ] `menu.py` -- `THEMES`, `MOTIFS`, `theme()` -- single source of theme data.
- [ ] `app.py` -- theme in list default/seed, state, title route validation, publish snapshot, board render -- carry the choice end to end.
- [ ] `templates/menu.html` -- theme-driven CSS vars, font link, eyebrow, emblem, halo, glow -- apply the look.
- [ ] `templates/menu_recipe.html` -- themed bg, accent, name font, emblem; Classic unchanged -- QR page matches the board.
- [ ] `static/js/app.js` -- Theme select in Holiday Menu dialog -- let the user choose.
- [ ] `tests/test_menu.py` -- each I/O row; Classic board HTML contains `The bar is open` and `#c9a24a`; Halloween board contains its eyebrow and emblem svg; every `THEMES` entry renders `/menu` with 200 and its motif/halo ids exist in `MOTIFS`.

**Acceptance Criteria:**
- Given an admin picks Christmas and publishes, when the TV loads `/menu`, then the board shows candy-striped lines, a green badge with a tree emblem, "Merry and bright", and Playfair Display title, matching the mockup.
- Given the current production snapshot (no theme), when this ships, then `/menu` looks the same as before.
- Given a Halloween menu is published, when a guest scans a QR code, then the recipe page shows the dark purple background, orange accents, Creepster drink name and pumpkin emblem.
- Given the Holiday Menu dialog opens, then the Theme dropdown lists all 21 themes in two groups with the saved one selected.

## Implementation Notes

## Plan Change Log

## Review Triage Log

**Pass 1 (quick lens):** high 0 / medium 0 / low 5 / false 0 / maybe-false 0; 1 low rejected.

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | Badge ring uses badge[1] rgb, not `shade` as in mockup | low | patch | Confirmed in `theme()`; ring for non-Classic switches to `shade`, Classic keeps 26,13,7. |
| 2 | Halo spills off-screen on single-drink pages | low | patch | `.page.n1 .badge` sits at top inset; ring radius .64m puts top icons at ~0.6-1.9vh. Hide halo on n1. |
| 3 | Striped row's "badge ring uses first color" untested | low | patch | Test only checked gradient; add `--gold: #c0262d` assertion. |
| 4 | Classic font stack gained Georgia fallback | low | patch | `--font` adds Georgia; revert to `'<font>', serif`. |
| 5 | Theme change dropped silently when title empty | low | rejected | Title is filled from state on open; emptying it is rare and existing behavior; fix adds UI branching. |
| 6 | Only Classic has a `tile` key, undocumented | low | patch | Add `tile` to THEMES header comment. |

## Design Notes

Line stripes: `repeating-linear-gradient(45deg, c1 0 1.6vh, c2 1.6vh 3.2vh, …)` on `.page` background; single color stays a plain color. Badge ring/rules use `line[0]`. Font names with spaces go into the Google Fonts URL with `+`, weight from `weight` (default 600). `scale` multiplies the title/name font sizes to even out faces of different widths.

## Verification

**Commands:**
- `.venv/bin/python -m pytest -q` -- expected: all pass
- `ruff check . && ruff format --check .` -- expected: clean
- `npm run format:check` -- expected: clean

**Manual checks (if no CLI):**
- Run the app, publish with Classic, Christmas, Neon Night; screenshot `/menu` at 1920×1080 and compare to the mockup.
