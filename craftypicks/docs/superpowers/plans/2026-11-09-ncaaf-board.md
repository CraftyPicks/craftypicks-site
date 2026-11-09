# NCAAF board — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A free (ESPN-only) NCAAF board: next 7 days of FBS games, FPI win % vs market, ESPN spread, Team Stats detail (ATS, Points, Points Against, Turnovers, Takeaways, Yards per Play).

**Architecture:** `espn_cfb.py` parses ESPN football (reusing `espn_cbb.parse_event/parse_odds`). `ncaaf.py` owns the store, team sheet, FPI model, rows, grading and the daily run. `run_daily.py` calls it above the odds guard. `build.py` publishes `ncaaf/index.html` on the shared league template, injected beside (not inside) the Odds-API board so no credits are ever spent. NCAAF is deliberately NOT added to `leagues.LEAGUES`/`config.LEAGUES`: those drive Odds API purchases.

**Tech Stack:** Python 3.11 stdlib, static HTML.

## Global Constraints

- Free sources only; zero Odds API credits.
- Full team names; preview at 390px before shipping; zip without `.github/`.
- `_self_test()` per module; tests on fixtures shaped from real ESPN payloads.

---

### Task 1: `scripts/espn_cfb.py`
Produces `parse_box(summary) -> {tid: {"pts","tov","yds","plays"}}`, `parse_power(payload, kind="fpi") -> {tid: {"rating","rank"}}`, fetchers `scoreboard(day)` (None on failure), `summary(eid)`, `fpi(season)`.
- [ ] Self-test first (synthetic + real sportsdataverse fixtures), red, implement, green.

### Task 2: `scripts/ncaaf.py`
Produces `team_sheet(store, power) -> {name_key: {...stats: ats, pts, opp, giv, tak, ypp}}`, `win_prob(fpi_home, fpi_away, neutral) -> float`, `board_rows(store, power, day) -> [row]` (board-card shape + `line_note` + `team_stats`), `grade(history, store)`, `summary(history)`, `daily(day, data, fetch)`.
Constants: `HOME_EDGE=2.5`, `MARGIN_SD=14.0`, `WINDOW_DAYS=7`, season months Aug–Jan.
- [ ] Self-test first, red, implement, green.

### Task 3: daily wiring
- [ ] `_test_run_order.py`: `ncaaf_mod.daily(` above the guard. Red → wire section 0c → green.

### Task 4: pages
- [ ] Render test first: NCAAF card uses full names, shows `line_note`, Team Stats with the six football rows and "FPI #"; NCAAB unchanged.
- [ ] Build test first: `ncaaf/index.html` in PAGES/TITLES/VIEWS and the sport row.
- [ ] Implement; green.

### Task 5: verify and ship
- [ ] Full sweep, palette guard, 390px preview incl. the sport row, upstream diff check, zip.
