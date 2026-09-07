# Savant Matchup Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put PA, K%, AVG and xwOBA for a starter against tonight's opposing roster onto the pitcher prop card, the way Baseball Savant shows it.

**Architecture:** Three of the four numbers already exist. `mlb_api.vs_roster()` aggregates every opposing batter's career line against the starter into `screen_models.VsRoster`, which computes `pa`, `k_pct` and `avg` today and has never been displayed. xwOBA is Statcast and StatsAPI does not carry it, so it comes from Baseball Savant's `statcast_search/csv` endpoint — free, no key, proven reachable from Actions by `research/probe_savant.py` on 2026-09-07. Savant is fetched per pitcher per season, aggregated to `(pitcher, batter) -> (xwoba_numerator, denominator)`, and cached one file per pitcher. Past seasons are immutable and fetched once; only the current season is refreshed.

**Tech Stack:** Python 3.11 standard library only. `urllib.request`, `csv`, `json`. No new dependencies.

## Global Constraints

- Python 3.11 standard library only. No new third-party packages.
- No paid API credits. Savant and StatsAPI are both free.
- The daily job has a 30-minute timeout. One Savant season-fetch measured 1.59 MB and 3.7s, so cold work must be budgeted per run, not run to completion.
- Every network call is wrapped: a Savant outage must never cost the card.
- `data/` files are written through `results_store._write_atomic`.
- The sandbox cannot reach Savant or StatsAPI. All tests run against fixtures.

---

### Task 1: `scripts/savant.py` — parse the Statcast CSV into a matchup aggregate

**Files:**
- Create: `craftypicks/scripts/savant.py`
- Test: `_self_test()` inside the module, run on import by the daily job

**Interfaces:**
- Produces:
  - `aggregate(csv_text: str) -> dict[str, list[float]]` — `{batter_id: [denom, numerator]}`
  - `season_url(pitcher_id: int, season: int) -> str`
  - `fetch_season(pitcher_id: int, season: int) -> str | None`

**The xwOBA definition, which the CSV makes exact:** a row counts when
`woba_denom` is non-zero. Its numerator is
`estimated_woba_using_speedangle` when that column is filled — every
tracked batted ball — and `woba_value` otherwise, which covers
strikeouts (0), walks (~0.69), hit-by-pitch, and the batted balls the
radar missed. This is Savant's own definition, not an approximation.

- [ ] **Step 1: Write the failing test**

```python
CSV = (
    "batter,events,woba_value,woba_denom,estimated_woba_using_speedangle\n"
    "111,field_out,0,1,0.150\n"          # tracked out
    "111,strikeout,0,1,\n"               # K: no estimate, actual 0
    "111,walk,0.69,1,\n"                 # BB: actual weight
    "222,home_run,2.0,1,1.800\n"         # tracked HR
    "222,,0,0,\n"                        # mid-PA pitch, ignored
)

def test_aggregate_splits_by_batter_and_prefers_the_estimate():
    got = aggregate(CSV)
    assert got["111"] == [3.0, 0.84]     # 0.150 + 0 + 0.69
    assert got["222"] == [1.0, 1.8]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python3 craftypicks/scripts/savant.py`
Expected: `NameError: name 'aggregate' is not defined`

- [ ] **Step 3: Implement**

```python
def aggregate(csv_text: str) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        den = _num(row.get("woba_denom"))
        if not den:
            continue
        bid = (row.get("batter") or "").strip()
        if not bid:
            continue
        est = _num(row.get("estimated_woba_using_speedangle"))
        num = est if est is not None else (_num(row.get("woba_value")) or 0.0)
        slot = out.setdefault(bid, [0.0, 0.0])
        slot[0] += den
        slot[1] += num
    return out
```

- [ ] **Step 4: Run it and watch it pass**

- [ ] **Step 5: Commit**

```bash
git add craftypicks/scripts/savant.py
git commit -m "feat: parse Savant's Statcast CSV into a pitcher-vs-batter xwOBA aggregate"
```

---

### Task 2: cache one file per pitcher, refresh only the current season

**Files:**
- Modify: `craftypicks/scripts/savant.py`
- Create at runtime: `craftypicks/data/savant/<pitcher_id>.json`

**Interfaces:**
- Produces:
  - `load(pitcher_id) -> dict` / `save(pitcher_id, doc) -> None`
  - `warm(pitcher_ids, season, today, budget=MAX_FETCHES) -> int`
  - `roster_xwoba(pitcher_id, batter_ids) -> tuple[float | None, float]`

**Shape on disk:**

```json
{"seasons": {"2026": {"683083": [12.0, 4.31]}},
 "empty":   ["2015", "2016"],
 "fetched": {"2026": "2026-09-07"}}
```

`empty` records seasons the pitcher did not appear in, so a cold cache
stops walking backwards instead of asking Savant for 2015 every morning
for a pitcher who debuted in 2023.

**Why a budget:** 21 starters × ten seasons is roughly 330 MB and over
ten minutes against a 30-minute job timeout. `warm()` spends its budget
on the current season for today's starters first, because that is the
only data that changes, and puts whatever is left into backfilling the
oldest missing season. The cache converges over a few days and the panel
prints the span it actually has.

- [ ] **Step 1: Write the failing test** (no network — `fetch_season` is stubbed)

```python
def test_warm_refreshes_today_before_backfilling():
    calls = []
    def fake(pid, season):
        calls.append((pid, season))
        return "batter,woba_value,woba_denom,estimated_woba_using_speedangle\n7,0,1,0.4\n"
    warm([99], season=2026, today="2026-09-07", budget=2, fetch=fake)
    assert calls[0] == (99, 2026)          # current season first, always
    assert len(calls) == 2                 # budget respected

def test_a_season_already_fetched_today_is_not_refetched():
    ...
def test_past_seasons_are_never_refetched():
    ...
```

- [ ] **Step 2: Run it and watch it fail**
- [ ] **Step 3: Implement `load` / `save` / `warm` / `roster_xwoba`**
- [ ] **Step 4: Run it and watch it pass**
- [ ] **Step 5: Commit**

---

### Task 3: put the four numbers on the row

**Files:**
- Modify: `craftypicks/scripts/pitchers.py:113-220` (`build`)
- Modify: `craftypicks/scripts/mlb_api.py:203` (`vs_roster` — return the batter ids it aggregated)

`vs_roster` already walks the opposing roster one free request per
batter, ~26–40 per starter. It currently returns only the aggregate.
It must also return the batter ids, because Savant is keyed by batter
and the join has to happen on the same roster StatsAPI used.

The row gains one key:

```python
"vs_roster": {"pa": 214, "k_pct": 0.241, "avg": 0.233,
              "xwoba": 0.298, "xwoba_pa": 187,
              "span": "2019–2026", "batters": 27},
```

`xwoba_pa` is deliberately separate from `pa`: Savant's denominator is
AB+BB+SF+HBP and the cache may be shallower than the StatsAPI career
line, so printing one PA count beside both numbers would be a lie.

- [ ] Steps 1–5 as above.

---

### Task 4: render the panel

**Files:**
- Modify: `craftypicks/_src/render.py:780` (`_matchup_panel`)
- Modify: `craftypicks/_src/base.css`
- Modify: `craftypicks/_src/i18n.py`

Four cells at the top of the existing collapsible detail, above the
"how this starter has done against this opponent" block, because it is
the wider and better-populated sample.

**The sample-size rule, which is the whole reason this is worth doing
carefully:** career xwOBA against an individual batter is usually 3–10
PA and is noise. The roster aggregate is not. The panel prints the
denominator beside the number and dims anything under 50, rather than
showing a confident-looking three-decimal figure built on nine plate
appearances.

- [ ] Steps 1–5 as above, plus a `palette.py` contrast check on any new colour.

---

### Task 5: fix the credit reserve that is skipping props

**Files:**
- Modify: `craftypicks/scripts/config.py:164-173` (`spare_credits`)
- Modify: `craftypicks/scripts/run_daily.py`
- Create at runtime: `craftypicks/data/credits.json`

Not part of the panel, but it is what stopped the pitcher board
refreshing on 2026-09-07, and the panel is worthless on a board that
does not build.

Observed: `356 credits left, 24 days to reset, spare ... is -4`.
The reserve is `5 × sports_in_season × days_left` = `5 × 3 × 24 = 360`.
The same log says NFL and NBA had no games and spent 0 credits. The
reserve books 5 credits a day for each of them for 24 days — about 240
credits held against sports that mostly will not play. Actual spend was
9. The formula assumed 15.

Replace the guess with the measurement. Append `{date, spent, remaining}`
each run; reserve the 75th percentile of the last 14 days' spend times
days left, falling back to the current formula until there are 5 days of
history.

- [ ] Steps 1–5 as above.

---

## Self-Review

- Spec coverage: PA, K%, AVG (Task 3, from existing `VsRoster`), xwOBA (Tasks 1–3), display (Task 4). The user chose career-cached depth and exactly these four columns.
- No placeholders: every network call has a fixture-driven test; `warm` takes `fetch` as a parameter precisely so it is testable offline.
- Type consistency: `aggregate` returns `dict[str, list[float]]` with string batter ids throughout, because the CSV column is a string and StatsAPI ids are ints — the join in Task 3 must `str()` the roster ids.
