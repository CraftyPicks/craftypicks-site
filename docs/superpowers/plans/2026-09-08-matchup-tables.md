# Matchup Tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two tables from the reference screenshots — a head-to-head starter comparison, and each club's hitters against tonight's opposing starter, career — on the MLB game card, and the per-batter half on the home run and hits boards.

**Architecture:** Both are free StatsAPI. The starter comparison needs three more fields out of a payload `parse_pitcher_season` already receives and discards. The hitter table is `vs_batter()` once per hitter — the same call the pitcher panel uses, which has worked career-wide since the `season=` parameter came off it on 2026-09-07.

**Tech Stack:** Python 3.11 stdlib, the existing `_group_card` / `pk` section vocabulary. No new dependencies, no paid credits.

## Global Constraints

- Free data only. `vs_batter` is one request per hitter; a 15-game board at 9 hitters a side is ~270 requests and roughly 30s, and no credits.
- Every network call stays wrapped. A StatsAPI outage must never cost the card.
- **We do not have real lineups.** They post about two hours before first pitch and the daily job runs at 9am. The table shows each club's regulars — the same set the hits board rates — and says so. Printing a batting order we do not have would be a lie the reader cannot check.
- Sample sizes here are tiny. The reference shows `1-5`, `1-4`, `2-4` — five plate appearances is not a measurement, and half the rows are blank. The table prints the dashes rather than hiding the row, and never derives a verdict from it.

---

### Task 1: three more fields off a payload we already fetch

**Files:**
- Modify: `craftypicks/scripts/mlb_api.py:86` (`EMPTY_PITCHER`), `:91` (`parse_pitcher_season`)

**Interfaces:**
- Produces: `parse_pitcher_season` gains `"k"`, `"bb"`, `"whip"`.

`whip` arrives as a string and can be `"-.--"`, exactly like `era`. It is also
just `(H + BB) / IP`, so when the string does not parse it is computed rather
than dropped — the two inputs are already in the same payload.

- [ ] **Step 1: Write the failing test**

```python
def test_whip_falls_back_to_its_own_definition():
    payload = {"stats": [{"splits": [{"stat": {
        "inningsPitched": "156.1", "hits": 97, "baseOnBalls": 65,
        "strikeOuts": 221, "whip": "-.--"}}]}]}
    got = parse_pitcher_season(payload)
    assert got["k"] == 221 and got["bb"] == 65
    assert abs(got["whip"] - (97 + 65) / (156 + 1 / 3)) < 1e-9
```

- [ ] **Step 2: Run it and watch it fail** — `python3 scripts/mlb_api.py`
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run it and watch it pass**
- [ ] **Step 5: Commit**

---

### Task 2: the starter comparison

**Files:**
- Modify: `craftypicks/_src/render.py` (`_starters_block`)
- Modify: `craftypicks/_src/base.css`, `craftypicks/_src/i18n.py`

Eight rows, both starters, the label down the middle — W-L, ERA, WHIP, IP,
H, K, BB, HR. The centre column is what makes it readable: two stat blocks
side by side make the reader hunt for which number pairs with which, and a
shared label column removes the hunt.

The better number in each row is marked, and "better" is per-row: high is
good for K, low is good for everything else here. No colour on W-L — a
starter's record is mostly a report on the lineup behind him, which is
already why it sits at the top and out of the projection.

- [ ] Steps 1–5 as above.

---

### Task 3: the hitters, career, against tonight's starter

**Files:**
- Modify: `craftypicks/scripts/mlb_api.py` (`team_roster`, new `lineup_vs`)

**Interfaces:**
- `team_roster(team_id, season)` returns `[{"id", "name", "position"}]` rather than bare ids. The position is already in the payload and already read — it is what filters pitchers out — and then thrown away.
- `lineup_vs(pitcher_id, team_id, season, limit=9) -> list[dict]` with `pa, ab, h, hr, rbi, k, avg` per hitter, `None` where he has never faced him.

`vs_roster` keeps working unchanged: it is rewritten to consume the richer
`team_roster` rather than duplicating the walk.

- [ ] Steps 1–5 as above.

---

### Task 4: the table on the game card

**Files:** `craftypicks/_src/render.py`, `_src/i18n.py`, `_src/base.css`

One table per club inside the game card's disclosure, under the starter
comparison. Columns follow the reference: hitter and position, H-AB, HR,
RBI, K, AVG. A hitter with no history gets `—` across, not a hidden row:
"has never faced him" is information, and dropping the row would silently
shorten one club's table.

- [ ] Steps 1–5 as above.

---

### Task 5: the same line on the home run and hits boards

**Files:** `craftypicks/scripts/batters.py`, `scripts/hits.py`, `_src/render.py`

Those boards already rate one batter against one named starter, so each
row wants its own single line rather than a whole table. Both scripts have
`pitcher_id` in scope at the point the row is built and simply do not store
it; storing it is the whole change on the data side.

- [ ] Steps 1–5 as above.

## Self-Review

- Coverage: screenshot one is Tasks 1–2, screenshot two is Tasks 3–4, and the user's "for HR and hits" is Task 5.
- The lineup caveat is stated in the constraints and printed on the page, not left implicit.
- Type consistency: `lineup_vs` returns `avg` as a float or None; the renderer formats. No formatting in the data layer.
