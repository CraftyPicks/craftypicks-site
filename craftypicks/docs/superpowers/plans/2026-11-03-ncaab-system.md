# NCAAB System tabs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two NCAAB sub-tabs (System, 1st Half) that post games passing ≥4 of the owner's checks, graded daily, plus full team names on every NCAAB card.

**Architecture:** `espn_cbb.py` fetches and parses ESPN (pure parsers, one thin fetch layer on `results._get`). `ncaab_system.py` owns the season game store, derives team profiles, runs the checklist, grades and summarises. `run_daily.py` gains section 3f. `render.py` + `build.py` publish two pages.

**Tech Stack:** Python 3.11 stdlib; static HTML via `{{TOKEN}}` bodies; existing card CSS.

## Global Constraints

- Free data only. No new Odds API spend.
- Python 3.11 standard library only; nothing installed on the runner.
- Every module carries `_self_test()` and runs as `python3 scripts/<mod>.py`.
- ESPN is unreachable from the development sandbox; tests run on fixtures shaped from real ESPN payloads (sportsdataverse-py `tests/fixtures/espn/*_mbb.json`, `fpi_nba.json`).
- Ships as a zip with no `.github/workflows/` content.
- A play posts at 4 or more ✓; n/a never counts as a pass.

## Verified ESPN shapes (from real fixtures)

- Scoreboard `events[].competitions[0]`: `competitors[]{homeAway, team{id, displayName, abbreviation}, score:"71", linescores[{value, period}]}`, `neutralSite`, `notes[]`, `odds[]` (may be absent); `events[].season{year,type}`, `status.type.completed`.
- Summary: `boxscore.teams[]{team{id}, homeAway, statistics[{name, displayValue}]}` with `totalRebounds`, `steals`, `totalTurnovers`; `boxscore.players[]{team{id}, statistics[0]{names:[MIN,PTS,...], athletes[{athlete{id}, didNotPlay, stats[]}]}}`; `header.competitions[0].competitors[]{homeAway, score, linescores[{displayValue}], team{id}}`; `pickcenter[]` (odds, may be empty).
- Team schedule: `events[].competitions[0].competitors[]{homeAway, team{id}, score{value}}`, `status.type.completed`.
- Power index: `categories[]{name:"bpi", names:[bpi, bpirank, ...]}`; `teams[]{team{id}, categories[]{name, values[]}}`; `pagination{pages}`.
- Odds block (ESPN standard): `details:"DUKE -7.5"|"EVEN"`, `spread`, `overUnder`, `homeTeamOdds{favorite, moneyLine}`, `awayTeamOdds{...}`.

---

### Task 1: ESPN parsers — `scripts/espn_cbb.py`

**Produces:**
- `parse_odds(odds: list, home_abbr: str) -> dict` → `{"spread_home": float|None, "ml_home": int|None, "ml_away": int|None, "total": float|None}`
- `parse_event(ev: dict) -> dict|None` → `{"event_id","date","season","season_type","neutral","postseason","completed","home":{"id","name","abbr"},"away":{...},"home_score","away_score","home_1h","away_1h", **odds}`
- `parse_box(summary: dict) -> dict` → `{team_id: {"reb","stl","tov","players":{pid: pts}}}`, plus `"_odds"` from pickcenter and `"_1h": {team_id: pts}`
- `parse_schedule(payload: dict) -> list[dict]` completed meetings `{"date","home_id","away_id","home_score","away_score"}`
- `parse_bpi(payload: dict) -> dict[str, int]` team id → rank (falls back to ranking by `bpi` value when no `bpirank`)
- fetchers `scoreboard(day)`, `summary(event_id)`, `schedule(team_id, season)`, `bpi(season)`; all return parsed values, never raise.

- [ ] Write `_self_test()` with synthetic payloads in exactly the shapes above: odds sign (away favourite → positive home spread; "EVEN" → 0.0; missing → None; fallback to `spread` + `favorite`), DNP players excluded, 1H from period-1 linescore, bpi rank fallback.
- [ ] Run, watch it fail; implement; run green.
- [ ] One-off (not committed): run the parsers over the real sportsdataverse fixtures in `/tmp/sdv` and check names/ids/box totals come out.

### Task 2: The system — `scripts/ncaab_system.py`

**Consumes:** Task 1 dict shapes.
**Produces:**
- `merge_games(store: dict, games: list[dict]) -> int`, `attach_box(store, event_id, box) -> None`
- `profiles(store) -> dict[team_id, Profile dict]` with `games, reb, stl, tov, forced, scorers14, ppg, ats{home,away}:[w,l], form{home,away}: [results newest first]`
- `meetings(store, h2h_cache, a, b) -> list` newest first
- `checks(game, side, tab, prof, bpi, meets) -> list[{"key","mark":"y"|"n"|"na","detail"}]`
- `candidates(game, tab, bpi) -> side|None` (1H skip when away ranks ≥50 places better)
- `build(slate, store, h2h, bpi) -> list[row]`; row = `{"tab","event_id","date","commence_time","home","away","side","line","ml","checks","passed","applicable","postseason","total"}`
- `grade(history, store) -> int`, `summary(history, tab) -> dict`
- constants: `MIN_PASS=4, REB_EDGE=3.0, ATS_RATE=0.55, ATS_MIN=4, BPI_SPREAD=10, BPI_CLOSE=15, H2H_MIN=3, SCORER_PPG=14.0, SCORERS_MIN=3, FORM_WINS=3, AWAY_WAY_BETTER=50, TOURNEY_TOP=25`

- [ ] Self-test first, built on a small synthetic season: each check flips ✓/✗/n/a at its threshold; candidate is away for System, home for 1H, skipped when away is 50+ BPI places better; play posts at exactly 4 ✓ and not at 3; System grade vs closing spread incl. push; 1H grade vs est. line; est. line = spread/2 rounded to .5; summary units at -110; postseason adds the scorer check and the unders note.
- [ ] Red → implement → green.

### Task 3: Daily job — `scripts/run_daily.py` section 3f

- [ ] Extend `_test_run_order.py`: `ncaab_sys.build(` present in run_daily.
- [ ] Section 3f, guarded `try/except` like 3e, gated on `"basketball_ncaab" in in_season` OR NCAAB season window (Nov–Apr): fetch scoreboards from the store's last day to today (cap 14 days), summaries for finals lacking a box (cap 400), BPI, home-team schedules for past 4 seasons not cached (cap 300); grade history; build today; save `data/ncaab_games.json`, `data/ncaab_h2h.json`, `data/ncaab_system.json`.

### Task 4: Pages + full names

- [ ] Run modern-web-guidance search for the checklist markup.
- [ ] Render test first: `system_cards(rows)` shows full names, play line, "5 of 7", each check with ✓/✗/–, "est." on 1H lines, empty state; `system_record(summary)`; NCAAB board card shows "Liberty Flames @ Pittsburgh Panthers" while MLB keeps nicknames.
- [ ] Implement `render.system_cards`, `render.system_record`, `_club(team, league)`; bodies `_src/ncaab_system.body.html`, `_src/ncaab_1h.body.html`; `build.py` PAGES/TITLES/_EXTRA_VIEWS; i18n keys; CSS for `.ck` list.
- [ ] build.py self-test green.

### Task 5: Verify and ship

- [ ] Full self-test sweep; palette guard.
- [ ] Build with a fixture `ncaab_system.json`; screenshot both tabs + NCAAB board at 390px.
- [ ] Zip `scripts/espn_cbb.py`, `scripts/ncaab_system.py`, `scripts/run_daily.py`, `scripts/_test_run_order.py`, `_src/*` changed files. No `.github/`.
