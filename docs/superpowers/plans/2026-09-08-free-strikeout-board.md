# Free Strikeout Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pitcher board every day, built from free StatsAPI, whether or not any prop odds were bought.

**Architecture:** The projection is already free — `project(k_per_9, opp_k_per_game, league)` uses nothing but StatsAPI. The only reason the board disappears on a no-props day is that `build()` iterates `prop_events` and reads `quote["line"]` as a required field. Invert it: iterate the probable starters, and treat the posted line as an optional decoration joined on when it happens to exist.

**Tech Stack:** Python 3.11 stdlib. No new data source, no new dependency, no credits.

## Global Constraints

- **Nothing here makes the projection better, and the page must not imply it does.** Measured on 185 graded starts: our average miss is 1.86 K against the posted line's 1.71, paired t = 3.26. The board exists to publish and score a number every day, not to claim it beats the market. The accuracy line stays on the page, and on a card with no posted line there is no edge, no lean and no verdict — because there is nothing to lean against.
- The posted line, when present, keeps its full treatment: gap, suspect flag, over/under record, prices.
- Grading is already line-agnostic and stays that way. A projection is scored against what the man actually did, which is free from the same game log.

---

### Task 1: `summary()` survives rows with no line

**Files:** `craftypicks/scripts/pitchers.py` (`summary`)

Do this first: it is the one place that would raise rather than degrade, and every later task writes rows it has to read.

`mae` is computed over every graded row. `line_mae` and `called_right` are computed over the graded rows **that have a line**, and the count for those is reported separately. Averaging two different populations under one `n` is the same mistake `error_summary` already had to fix once with `baseline_n`.

**Interfaces:**
- Produces: `summary()` gains `"priced"` — how many of the graded rows carried a posted line.

- [ ] **Step 1: Write the failing test**

```python
def test_summary_separates_the_priced_rows():
    hist = [
        {"projection": 5.0, "line": 4.5, "actual": 6},   # priced
        {"projection": 5.0, "line": None, "actual": 4},  # free board
    ]
    s = summary(hist)
    assert s["graded"] == 2 and s["priced"] == 1
    assert abs(s["mae"] - 1.0) < 1e-9          # over BOTH rows
    assert abs(s["line_mae"] - 1.5) < 1e-9     # over the priced row only
```

- [ ] **Step 2: Run it and watch it fail** — `python3 scripts/pitchers.py`, expect `TypeError` on `None`
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run it and watch it pass**
- [ ] **Step 5: Commit**

---

### Task 2: `build()` iterates starters, not prop events

**Files:** `craftypicks/scripts/pitchers.py` (`build`)

**Interfaces:**
- `build(prop_events, date_str, season, verbose=True)` keeps its signature. `prop_events` becomes optional context rather than the thing being looped: an empty list now yields a full board instead of `[]`.

The join goes the other way round. Build `quotes = {normalised name: (quote, event)}` from whatever prop events exist, then walk the starters and look each one up. A starter with no quote gets `line`, `over_odds`, `under_odds`, `books`, `gap` and `suspect` as `None`, and `event_id` / `commence_time` fall back to the starter's own `game_time`.

The last-ten strip needs a reference line. With no posted line it draws against **our projection** — "how often he has cleared the number we are publishing" — and the record label says so rather than naming a price that does not exist.

- [ ] Steps 1–5 as above, with a test that an empty `prop_events` still returns a rated board.

---

### Task 3: the daily job builds it every morning

**Files:** `craftypicks/scripts/run_daily.py`, `craftypicks/scripts/run_boards.py`

Today the call sits inside the props branch. It moves out, so the board is built from the probable starters whether or not the credit gate let props through. `run_boards.py` — the free, no-credit builder — gains the same call, so the board can be refreshed on a day the daily job has already posted.

- [ ] Steps 1–5 as above.

---

### Task 4: a card with no line

**Files:** `craftypicks/_src/render.py` (`pitcher_cards`), `_src/i18n.py`, `_src/base.css`

One number instead of two, no tick on the bar, and the footer says the line is not posted rather than printing a dash where a price goes. No edge chip: an edge against nothing is not a small edge, it is a category error.

- [ ] Steps 1–5 as above.

## Self-Review

- Spec coverage: the ask was "a pitcher board every day regardless of credits" — Tasks 2 and 3 do that, Task 1 stops it crashing, Task 4 stops it lying.
- Type consistency: `line` is `float | None` from Task 2 onward, and every reader (`summary`, `pitcher_cards`, `_strip`, the screens) is checked against that.
- The accuracy record is unchanged and still printed. Nothing in this plan touches the projection itself.
