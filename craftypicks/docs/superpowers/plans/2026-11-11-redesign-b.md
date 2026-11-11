# Redesign "B": readable dark, picks first — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the approved preview (styles/BC3): higher-contrast dark palette, a header with a sport menu and underlined view tabs, and compact college pick cards with tiers, a best-bets filter, school names, logos and a Details button.

**Architecture:** Site-wide header and palette change in `_src/build.py` + `_src/base.css`. College cards are a new renderer in `_src/render.py` used for `ncaab`/`ncaaf` rows; other leagues keep their cards and inherit the palette. Team identity (ESPN id, colour, school name) is attached at build time from the ESPN stores. Tier = edge in points (`ats.BEST=6`, `ats.LEAN=3`); tier records come from the graded history.

## Global Constraints
- Free data only; Python stdlib; `_self_test()` per module; zip delivery without `.github/`.
- Preview at 390px before shipping; text ≥ 4.5:1; state never by colour alone.
- Logos from `https://a.espncdn.com/i/teamlogos/ncaa/500/{id}.png`, team-colour badge fallback.
- Nav: one `<nav>` per level, `aria-current="page"`; sport menu = `popover` with the visible list as the no-support fallback; Details = `<button aria-expanded aria-controls>`.

### Task 1: Header and nav (build.py, base.css)
- [ ] Test: sport menu button names the current sport; menu lists every sport with `aria-current` on one; views carry `aria-current`; About page has no current sport.
- [ ] Implement; build self-test green.

### Task 2: Palette (base.css)
- [ ] Raise `--panel`, `--line`, `--muted` toward the B palette; palette.py green.

### Task 3: Data (espn_cbb, ats, board_ratings, ncaaf, build)
- [ ] Test: ESPN `location` stored as `school`; `attach_teams` puts id/colour/school on NCAAB and NCAAF rows; `ats.tier()`; records by tier in both summaries.
- [ ] Implement; self-tests green.

### Task 4: College card (render.py, base.css, board.js)
- [ ] Test: banner with tier tag, logo `<img>` + fallback, school names, chips, result line, Details button + panel; tier tiles and the Best-bets-only toggle; non-college cards unchanged.
- [ ] Implement; render self-test green; toggle and Details tested in Playwright.

### Task 5: Verify and ship
- [ ] Sweep; 390px screenshots of NCAAB, NCAAF, MLB and an NBA props page; upstream check; zip.
