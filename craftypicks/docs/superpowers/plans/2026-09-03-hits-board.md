# Hits Board and Shared Projection Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the MLB "Hits" board — every dangerous bat's chance of at least one hit tonight, free and graded — on a shared projection engine that the NFL boards will later reuse, and fix the league field that collapses the MLB sub-nav on the pitcher page.

**Architecture:** A new `scripts/projection.py` holds the four things every projection board does identically: dedupe-append to a history file, grade a counting stat, report calibration, report mean error. It knows nothing about any sport — callers pass field names. `scripts/batters.py` is migrated onto it first, because migrating working code with a passing self-test is how we find out the module is right. Then `scripts/hits.py` is a second, thin caller of the same engine.

**Tech Stack:** Python 3.11 standard library only. MLB StatsAPI (free, no key). Static HTML built by `_src/build.py` with `{{TOKEN}}` substitution.

## Scope

This plan covers the spec's tasks 1–4 only: the nav fix, the nflverse probe, the shared engine, and the MLB hits board. **It ships working software on its own.**

The NFL boards (`nfl_data.py`, `nfl_yards.py`, `nfl_td.py` and their four pages) are deliberately **not** planned here. Their field names come from the probe in Task 2, and this environment cannot reach nflverse to learn them. Writing steps against guessed column names is exactly the invented-detail failure this format forbids. A second plan gets written once Task 2's log has been read.

## Global Constraints

- **No new paid data.** Nothing in this plan may call The Odds API. The daily credit spend must not change by one credit.
- **Python 3.11 standard library only.** No new dependencies. `urllib.request` and `json`, as everywhere else.
- **No book line on this board.** It shows our number and grades it.
- **Every projection is graded, whether or not it becomes a play.**
- **Tests are `_self_test()` at the bottom of the module, run with `python3 scripts/<module>.py`.** This repo has no pytest and no `tests/` directory. Do not introduce either.
- **Parsers must be pure and testable offline.** Split every reader into a thin fetch (`_get`) and a pure parse. This sandbox cannot reach `statsapi.mlb.com`, so any code that can only be tested online cannot be tested at all.
- **`limit=100` on `statSplits`, `gameType=R` on `/schedule`, `playerPool=All` on the hitting leaderboard.** Each of these has silently corrupted data on this site before.
- **A full build must pass `python3 scripts/palette.py`.** `--dim` is 3.0:1 and may only caption something whose meaning is carried elsewhere on the card.
- **f-strings:** Python 3.11 cannot reuse the outer quote character inside an expression, cannot contain a backslash, and cannot split an expression across adjacent literals. Precompute the value into a local variable before the f-string.
- **Archives you hand the user contain source files only** — no built HTML, and nothing under `.github/workflows` (`GITHUB_TOKEN` cannot write those and the apply-update workflow rejects the archive).

---

## File Structure

| File | Responsibility |
|---|---|
| `research/probe_nfl.py` (create) | Print what the nflverse feed actually contains. Diagnostic only; writes nothing. |
| `.github/workflows/probe-nfl.yml` (create) | Run the probe in Actions, where the network works. |
| `scripts/projection.py` (create) | Sport-agnostic: `merge`, `grade_counting`, `calibration`, `error_summary`. |
| `scripts/batters.py` (modify) | Migrated onto `projection.py`; its own grading and calibration deleted. |
| `scripts/hits.py` (create) | The hit-chance model. Mirrors `batters.py` in shape. |
| `scripts/mlb_api.py` (modify) | `pitcher_season()` gains hits allowed. |
| `_src/build.py` (modify) | Nav fix, `hits.html` in `PAGES` and `VIEWS`, one new assertion. |
| `_src/render.py` (modify) | `hit_cards()`, `hit_calibration()`. |
| `_src/i18n.py` (modify) | `nav_hits` and the page's copy keys. |
| `_src/hits.body.html` (create) | The page's prose. |
| `scripts/run_boards.py` (modify) | Builds the hits board alongside homers and batters. |

---

## Task 1: Restore the MLB sub-navigation

The Pitchers prop page declares no league, so `view_row()` returns an empty
string and the reader loses every tab in the second row. Its two siblings
declare `"mlb"` correctly. This is one word, and it ships on its own.

**Files:**
- Modify: `craftypicks/_src/build.py:61` and the assertion block near line 691

**Interfaces:**
- Consumes: nothing
- Produces: nothing. No other task depends on this.

- [ ] **Step 1: Write the failing test**

In `_src/build.py`, find the assertion block that begins
`assert "pitchers.html" in mlb`. Add immediately after it:

```python
    # Every page a league lists as one of its views must claim that league.
    # view_row() opens with `if not page.league: return ""`, so a page that
    # forgets it renders no second row at all -- the reader lands on it and
    # every sibling tab vanishes. This shipped once, on pitchers.html.
    for _league, _views in VIEWS.items():
        for _href, _key in _views:
            _page = PAGES.get(_href)
            assert _page is not None, f"{_href} is in VIEWS but not PAGES"
            assert _page.league == _league, (
                f"{_href} is listed under {_league} but declares "
                f"league={_page.league!r}; its sub-nav will be empty")
```

- [ ] **Step 2: Run the build to verify the assertion fails**

```bash
cd craftypicks && python3 _src/build.py
```

Expected: `AssertionError: pitchers.html is listed under mlb but declares league=None; its sub-nav will be empty`

- [ ] **Step 3: Make the fix**

In `_src/build.py` line 61, change the fourth argument from `None` to `"mlb"`:

```python
    "pitchers.html": Page("pitchers.html", "pitchers", "pitchers", "mlb"),
```

- [ ] **Step 4: Run the build to verify it passes**

```bash
cd craftypicks && python3 _src/build.py && python3 scripts/palette.py
```

Expected: pages build with no AssertionError; palette reports no failures.

- [ ] **Step 5: Confirm the tabs are actually in the HTML**

```bash
cd craftypicks && grep -c 'nav2' pitchers.html && grep -o 'Home runs\|HR allowed\|Board\|Form' pitchers.html | sort -u
```

Expected: a non-zero count, and all four labels present. Before the fix, the second nav row is empty.

- [ ] **Step 6: Commit**

```bash
git add craftypicks/_src/build.py
git commit -m "fix: the pitcher page claims MLB, so its sub-nav renders

view_row() returns an empty string for a page with no league, so the
Pitchers prop page dropped every sibling tab and left the reader with
only the browser's back button. Its two siblings had it right.

The new assertion checks the direction the old ones did not: every page
a league lists as a view must claim that league."
```

---

## Task 2: Probe the nflverse feed

Diagnostic only. It writes nothing, commits nothing, and exists so that the
NFL plan is written against field names that were read rather than guessed.
Runs in Actions because this sandbox reaches only the Craftypicks repo.

**Files:**
- Create: `research/probe_nfl.py`
- Create: `.github/workflows/probe-nfl.yml`

**Interfaces:**
- Consumes: nothing
- Produces: a log, read by a human before the NFL plan is written. No code depends on it.

- [ ] **Step 1: Write the probe**

Create `research/probe_nfl.py`:

```python
#!/usr/bin/env python3
"""What does the nflverse feed actually contain?

Diagnostic only. Reads public files, writes nothing, commits nothing.
Run it from the Actions tab and read the log.

It exists because the NFL boards must be built against field names that
were read rather than guessed, and the environment the plan was written in
could not reach any host but GitHub.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import urllib.error
import urllib.request

RELEASES = "https://api.github.com/repos/nflverse/nflverse-data/releases"
UA = {"User-Agent": "craftypicks-probe/1.0"}


def get(url: str, want_json: bool = True):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"  !! {url} -> {type(e).__name__}: {e}")
        return None
    if want_json:
        return json.loads(raw.decode("utf-8"))
    return raw


def main() -> int:
    print("== releases")
    rels = get(RELEASES)
    if not rels:
        print("   nflverse unreachable. Try ESPN instead; see the spec.")
        return 1
    for rel in rels[:20]:
        names = [a["name"] for a in rel.get("assets", [])]
        print(f"  {rel['tag_name']:24} {len(names):3} assets")
        for n in names[:6]:
            print(f"      {n}")

    # The asset we expect to carry weekly player lines.
    target = None
    for rel in rels:
        for a in rel.get("assets", []):
            if a["name"] in ("player_stats.csv.gz", "stats_player_week.csv.gz",
                             "player_stats_2026.csv.gz"):
                target = a
                break
        if target:
            break
    if not target:
        print("\n!! no player-stats asset matched the expected names.")
        print("   Read the asset list above and pick one by hand.")
        return 1

    print(f"\n== reading {target['name']}")
    raw = get(target["browser_download_url"], want_json=False)
    if raw is None:
        return 1
    text = gzip.decompress(raw).decode("utf-8", "replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    print(f"   {len(rows):,} rows")
    print(f"   columns ({len(reader.fieldnames or [])}):")
    for c in reader.fieldnames or []:
        print(f"      {c}")

    if rows:
        print("\n== one full row, verbatim")
        for k, v in rows[0].items():
            print(f"   {k:32} {v!r}")

    print("\n== rows per season")
    seasons: dict = {}
    for r in rows:
        s = r.get("season") or "?"
        seasons[s] = seasons.get(s, 0) + 1
    for s in sorted(seasons, key=str)[-6:]:
        print(f"   {s}: {seasons[s]:,}")

    print("\n== can we get team defence from this file?")
    print("   opponent column present:",
          any(c in (reader.fieldnames or [])
              for c in ("opponent_team", "opponent", "def_team")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify it fails cleanly with no network**

```bash
cd /tmp/cps && python3 research/probe_nfl.py; echo "exit=$?"
```

Expected in this sandbox: `!! https://api.github.com/... -> URLError: ...` then `nflverse unreachable`, `exit=1`. It must not raise a traceback. If it does, fix the handler before continuing — a probe that crashes tells you nothing.

- [ ] **Step 3: Write the workflow**

Create `.github/workflows/probe-nfl.yml`:

```yaml
name: Probe NFL data

# Diagnostic only. Reads public files, writes nothing, commits nothing.
# Run it once from the Actions tab and paste the log back.

on:
  workflow_dispatch:

jobs:
  probe:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Ask nflverse what it has
        shell: bash
        run: |
          set -o pipefail
          python3 research/probe_nfl.py 2>&1
```

- [ ] **Step 4: Commit**

```bash
git add research/probe_nfl.py .github/workflows/probe-nfl.yml
git commit -m "research: probe what the nflverse feed actually contains

Diagnostic only. The NFL boards must be built against field names read
rather than guessed, and the sandbox the plan was written in reaches no
host but this repo."
```

- [ ] **Step 5: Hand the workflow to the user by hand**

`.github/workflows/probe-nfl.yml` cannot go in an update archive —
`GITHUB_TOKEN` may not write that path and the apply-update workflow rejects
any archive containing one. Send the file separately and tell the user to
add it via **Add file → Create new file** at exactly
`.github/workflows/probe-nfl.yml`, then run **Probe NFL data** from the
Actions tab and paste back the log.

---

## Task 3: The shared projection engine

Four functions every projection board needs, none of which know what a sport
is. Callers pass field names.

**Files:**
- Create: `craftypicks/scripts/projection.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `merge(history: list[dict], rows: list[dict], key_fields: tuple[str, ...]) -> int`
  - `grade_counting(history: list[dict], totals: dict, *, id_key: str, at_key: str, verdict_key: str, total_key: str) -> int`
  - `calibration(history: list[dict], *, verdict_key: str, chance_key: str = "chance", edges: tuple = DEFAULT_EDGES) -> dict`
  - `error_summary(history: list[dict], *, actual_key: str, projection_key: str) -> dict`
  - `DEFAULT_EDGES: tuple[tuple[float, float], ...]`

`calibration` returns `{"graded": int, "expected": float|None, "actual": float|None, "buckets": list[dict]}` where each bucket is `{"label": str, "n": int, "expected": float, "actual": float}`. Percentages, rounded to one decimal.

`error_summary` returns `{"graded": int, "mae": float|None, "bias": float|None, "baseline_mae": float|None}`.

- [ ] **Step 1: Write the failing test**

Create `craftypicks/scripts/projection.py` with only this at the bottom, and no implementation above it:

```python
def _self_test() -> None:
    # merge appends only what it has not seen
    hist: list = []
    rows = [{"id": 1, "when": "T1", "chance": 0.2},
            {"id": 2, "when": "T1", "chance": 0.1}]
    assert merge(hist, rows, ("id", "when")) == 2
    assert merge(hist, rows, ("id", "when")) == 0, "merge must be idempotent"
    assert len(hist) == 2

    # grade_counting settles a row once, and only once
    hist = [{"id": 1, "at": 10, "hit": None},
            {"id": 2, "at": 4, "hit": None},
            {"id": 3, "at": 7, "hit": None}]
    totals = {1: {"n": 11}, 2: {"n": 4}}          # 3 is absent
    n = grade_counting(hist, totals, id_key="id", at_key="at",
                       verdict_key="hit", total_key="n")
    assert n == 2, n
    assert hist[0]["hit"] is True                  # 11 > 10
    assert hist[1]["hit"] is False                 # 4 == 4
    assert hist[2]["hit"] is None                  # never seen, never graded
    assert grade_counting(hist, totals, id_key="id", at_key="at",
                          verdict_key="hit", total_key="n") == 0

    # calibration reports promised against delivered, not a win rate
    hist = [{"chance": 0.5, "hit": True}, {"chance": 0.5, "hit": False},
            {"chance": 0.1, "hit": False}, {"chance": 0.1, "hit": False}]
    c = calibration(hist, verdict_key="hit")
    assert c["graded"] == 4
    assert c["expected"] == 30.0, c["expected"]
    assert c["actual"] == 25.0, c["actual"]
    assert [b["n"] for b in c["buckets"]] == [2, 2]

    # an ungraded history says so rather than dividing by zero
    empty = calibration([{"chance": 0.5, "hit": None}], verdict_key="hit")
    assert empty == {"graded": 0, "expected": None, "actual": None,
                     "buckets": []}, empty

    # error_summary: mean absolute error, signed bias, and the naive baseline
    hist = [{"proj": 100.0, "actual": 110.0, "baseline": 105.0},
            {"proj": 100.0, "actual": 80.0, "baseline": 90.0}]
    e = error_summary(hist, actual_key="actual", projection_key="proj")
    assert e["graded"] == 2
    assert e["mae"] == 15.0, e["mae"]
    assert e["bias"] == -5.0, e["bias"]            # projected 5 high on average
    print("projection self-test: the engine holds")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd craftypicks && python3 scripts/projection.py
```

Expected: `NameError: name 'merge' is not defined`

- [ ] **Step 3: Write the implementation**

Insert above `_self_test`:

```python
"""What every projection board on this site does identically.

Four things, none of which know what a sport is:

  * merge      -- append tonight's rows to the running history, once each
  * grade      -- settle a row against a season counting stat
  * calibration-- what was promised against what happened
  * error      -- how wrong a continuous projection was, against a baseline

The field names are arguments rather than constants because the boards
disagree about them and always will: a batter "homered", a receiver "scored",
a quarterback threw for a number that is not a verdict at all. Passing the
names in is what keeps this file from growing a branch per sport.
"""
from __future__ import annotations

# The calibration buckets. Wide on purpose: narrow buckets on a few hundred
# rows report noise as though it were miscalibration.
DEFAULT_EDGES = ((0.0, 0.08), (0.08, 0.12), (0.12, 0.18), (0.18, 1.01))


def merge(history: list[dict], rows: list[dict],
          key_fields: tuple[str, ...]) -> int:
    """Append rows the history has not seen. Returns how many were added.

    Idempotent by construction: the boards are rebuilt several times a day
    and every rebuild re-projects the same players for the same games. A row
    is identified by the caller's key fields -- typically the player and the
    game -- and never stored twice.
    """
    seen = {tuple(r.get(f) for f in key_fields) for r in history}
    added = 0
    for row in rows:
        key = tuple(row.get(f) for f in key_fields)
        if key in seen:
            continue
        seen.add(key)
        history.append(dict(row))
        added += 1
    return added


def grade_counting(history: list[dict], totals: dict, *, id_key: str,
                   at_key: str, verdict_key: str, total_key: str) -> int:
    """Settle rows whose event is visible in a season counting stat.

    The trick that makes this free: the leaderboard is refetched anyway, so
    a player's season total now against the total stored when he was
    projected says whether the thing happened. No extra request, and no way
    to quietly skip finding out.

    A row is graded once. A player missing from the totals is left ungraded
    rather than recorded as a miss -- absent is not the same as no.
    """
    graded = 0
    for row in history:
        if row.get(verdict_key) is not None:
            continue
        now = totals.get(row.get(id_key))
        if not now:
            continue
        before = row.get(at_key)
        if before is None:
            continue
        row[verdict_key] = bool(now[total_key] > before)
        graded += 1
    return graded


def calibration(history: list[dict], *, verdict_key: str,
                chance_key: str = "chance",
                edges: tuple = DEFAULT_EDGES) -> dict:
    """What was promised against what happened.

    Not a win rate. A model that says 12% should be right about 12% of the
    time, and the honest test is whether the group it called 12% delivered
    12% -- not whether the top name came in.
    """
    done = [r for r in history if r.get(verdict_key) is not None]
    if not done:
        return {"graded": 0, "expected": None, "actual": None, "buckets": []}
    exp = sum(r[chance_key] for r in done) / len(done)
    act = sum(1 for r in done if r[verdict_key]) / len(done)
    buckets = []
    for lo, hi in edges:
        grp = [r for r in done if lo <= r[chance_key] < hi]
        if not grp:
            continue
        b_exp = sum(r[chance_key] for r in grp) / len(grp)
        b_act = sum(1 for r in grp if r[verdict_key]) / len(grp)
        buckets.append({
            "label": f"{lo * 100:.0f}-{min(hi, 1.0) * 100:.0f}%",
            "n": len(grp),
            "expected": round(b_exp * 100, 1),
            "actual": round(b_act * 100, 1),
        })
    return {"graded": len(done), "expected": round(exp * 100, 1),
            "actual": round(act * 100, 1), "buckets": buckets}


def error_summary(history: list[dict], *, actual_key: str,
                  projection_key: str, baseline_key: str = "baseline") -> dict:
    """How wrong a continuous projection was.

    Reports the naive baseline beside it -- the player's own average with no
    opponent adjustment -- because a projection that cannot beat that has an
    adjustment that is decoration, and the page should be able to say so.

    Bias is signed: negative means the projections ran high.
    """
    done = [r for r in history if r.get(actual_key) is not None
            and r.get(projection_key) is not None]
    if not done:
        return {"graded": 0, "mae": None, "bias": None, "baseline_mae": None}
    n = len(done)
    mae = sum(abs(r[actual_key] - r[projection_key]) for r in done) / n
    bias = sum(r[actual_key] - r[projection_key] for r in done) / n
    base = [r for r in done if r.get(baseline_key) is not None]
    base_mae = (sum(abs(r[actual_key] - r[baseline_key]) for r in base)
                / len(base)) if base else None
    return {"graded": n, "mae": round(mae, 2), "bias": round(bias, 2),
            "baseline_mae": round(base_mae, 2) if base_mae is not None else None}
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/projection.py
```

Expected: `projection self-test: the engine holds`

- [ ] **Step 5: Commit**

```bash
git add craftypicks/scripts/projection.py
git commit -m "feat: the projection engine the boards share

Merge, grade, calibrate, measure error. Field names are arguments, not
constants, because the boards disagree about them and always will --
which is what keeps this file from growing a branch per sport."
```

---

## Task 4: Migrate the home-run board onto the engine

Prove the engine on working code with a passing self-test before a second
caller depends on it. If `batters.py` still passes afterwards, the engine is
right; if it does not, the engine is wrong and we learn it here rather than
in the hits board.

**Files:**
- Modify: `craftypicks/scripts/batters.py`

**Interfaces:**
- Consumes: `projection.merge`, `projection.grade_counting`, `projection.calibration` from Task 3
- Produces: `batters.grade(history, table) -> int` and `batters.summary(history) -> dict` keep their existing signatures and return shapes. `run_daily.py` and `run_boards.py` call them and must not change.

- [ ] **Step 1: Record what the current behaviour is**

```bash
cd craftypicks && python3 scripts/batters.py
```

Expected: `batters self-test: the model holds and grades itself`

This is the baseline. It must still print after the migration.

- [ ] **Step 2: Replace the two function bodies**

In `scripts/batters.py`, add to the imports at the top:

```python
import projection
```

Replace the entire body of `grade()` with a delegation, keeping the
signature and the docstring's first line:

```python
def grade(history: list[dict], table: dict[int, dict]) -> int:
    """Fill in whether each projected batter has homered since.

    Free, and that is the whole reason it is done this way: the leaderboard
    is refetched every morning, so a batter's season total today against the
    total stored when he was projected answers the question with no extra
    request and no way to quietly skip it.
    """
    return projection.grade_counting(
        history, table, id_key="batter_id", at_key="hr_at_projection",
        verdict_key="homered", total_key="hr")
```

Replace the entire body of `summary()`:

```python
def summary(history: list[dict]) -> dict:
    """Calibration: what was promised against what happened.

    Not a win rate. A model that says 12% should be right about 12% of the
    time, and the honest test of it is whether the group it called 12%
    homered 12% of the time -- not whether the top name went deep.
    """
    return projection.calibration(history, verdict_key="homered")
```

- [ ] **Step 3: Run the self-test to verify nothing changed**

```bash
cd craftypicks && python3 scripts/batters.py
```

Expected: `batters self-test: the model holds and grades itself` — identical to Step 1.

- [ ] **Step 4: Verify the live data still grades identically**

The repository has a real `data/batter_ratings.json`. Grading it through both paths must agree:

```bash
cd craftypicks && python3 - <<'PY'
import sys, json; sys.path.insert(0, "scripts")
import batters
hist = json.load(open("data/batter_ratings.json"))["batters"]
s = batters.summary(hist)
print("graded", s["graded"], "expected", s["expected"],
      "actual", s["actual"], "buckets", len(s["buckets"]))
PY
```

Expected: runs without error and reports the same `graded` count as the board page currently shows. A `KeyError` here means the engine's field names are wrong.

- [ ] **Step 5: Commit**

```bash
git add craftypicks/scripts/batters.py
git commit -m "refactor: the home-run board grades through the shared engine

Migrated first, on purpose. The engine is proven against working code
with a passing self-test before a second board depends on it."
```

---

## Task 5: Carry hits through the parsers

The payloads already contain hits. Both parsers throw them away. This is a
parser change, not a second request — the credit cost of this task is zero
and the request count is unchanged.

**Files:**
- Modify: `craftypicks/scripts/batters.py` (`parse_batters`)
- Modify: `craftypicks/scripts/mlb_api.py` (`parse_pitcher_season` / `pitcher_season`)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `batters.parse_batters(payload)` rows gain `"h": int` alongside the existing `"hr"` and `"pa"`.
  - `mlb_api.pitcher_season(pid, season)` gains `"h"` (hits allowed) alongside the existing `"hr"`, `"bf"`, `"w"`, `"l"`, `"hr_per_9"`.

- [ ] **Step 1: Write the failing test**

In `scripts/batters.py`, inside `_self_test()`, find the block that builds
`payload` and asserts on `parse_batters`. Add after the existing assertions:

```python
    # Hits ride along in the same payload as home runs. They were being
    # parsed and dropped; nothing extra is requested for them.
    assert table[1]["h"] == 150, table[1]
    assert table[3]["h"] == 40, table[3]      # traded: two lines, summed
```

and add `"hits"` to the stat dicts in that same payload so the fixture can
support the assertion — `{"homeRuns": 40, "plateAppearances": 600}` becomes
`{"homeRuns": 40, "plateAppearances": 600, "hits": 150}`, the second line
gains `"hits": 90`, and the two traded lines gain `"hits": 25` and
`"hits": 15`.

- [ ] **Step 2: Run it to verify it fails**

```bash
cd craftypicks && python3 scripts/batters.py
```

Expected: `KeyError: 'h'`

- [ ] **Step 3: Carry hits through `parse_batters`**

In `scripts/batters.py`, in `parse_batters`, the row initialiser currently
reads:

```python
            "name": player.get("fullName", ""), "hr": 0, "pa": 0,
```

Change it to:

```python
            "name": player.get("fullName", ""), "hr": 0, "pa": 0, "h": 0,
```

and beside the existing `row["hr"] += int(stat.get("homeRuns") or 0)` add:

```python
        row["h"] += int(stat.get("hits") or 0)
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/batters.py
```

Expected: `batters self-test: the model holds and grades itself`

- [ ] **Step 5: Split the pitcher reader into fetch and parse**

`pitcher_season` fuses the request and the parsing, so nothing about it can
be tested without the network — which this sandbox does not have. That
breaks this plan's own testability constraint, and it is the function we are
about to change. Split it first.

In `scripts/mlb_api.py`, replace `pitcher_season` with these two:

```python
EMPTY_PITCHER = {"k_pct": None, "k_per_9": None, "innings": 0.0, "era": None,
                 "w": None, "l": None, "hr": None, "hr_per_9": None,
                 "bf": None, "h": None}


def parse_pitcher_season(payload) -> dict:
    """A starter's season line, from a /people/{id}/stats payload.

    Pure, so it can be tested without the network. The fetch is next door.
    """
    data = payload or {}
    splits = (data.get("stats") or [{}])[0].get("splits") or []
    if not splits:
        return dict(EMPTY_PITCHER)
    s = splits[0].get("stat", {})
    bf = s.get("battersFaced") or 0
    k = s.get("strikeOuts") or 0
    ip = _innings(s.get("inningsPitched"))
    try:
        era = float(s.get("era")) if s.get("era") not in (None, "-.--") else None
    except (TypeError, ValueError):
        era = None
    hr = s.get("homeRuns")
    hits = s.get("hits")
    return {
        "k_pct": (k / bf) if bf else None,
        "k_per_9": (k * 9 / ip) if ip else None,
        "innings": ip,
        "era": era,
        "bf": int(bf) if bf else None,
        "hr": int(hr) if hr is not None else None,
        "hr_per_9": (int(hr) * 9 / ip) if (hr is not None and ip) else None,
        "h": int(hits) if hits is not None else None,
        "w": s.get("wins"),
        "l": s.get("losses"),
    }


def pitcher_season(pitcher_id: int, season: int) -> dict:
    """Season K%, K/9, innings, ERA, hits and home runs allowed, and record.

    The record is display-only and deliberately so: a starter's W-L says more
    about the lineup behind him than about him. It is on the card because
    readers look for it, and nowhere near the projection.
    """
    return parse_pitcher_season(_get(
        f"/people/{pitcher_id}/stats", stats="season",
        season=season, group="pitching"))
```

Keep whatever the existing function returned for `w`, `l` and `hr_per_9`
identical — the pitcher board and the prop cards read those today.

- [ ] **Step 6: Test the parser behaviourally**

Add a `_self_test` to `scripts/mlb_api.py` if it has none, or extend the
existing one:

```python
def _self_test() -> None:
    payload = {"stats": [{"splits": [{"stat": {
        "battersFaced": 700, "strikeOuts": 180, "inningsPitched": "170.1",
        "era": "3.45", "homeRuns": 22, "hits": 150,
        "wins": 11, "losses": 7}}]}]}
    row = parse_pitcher_season(payload)
    assert row["bf"] == 700, row
    assert row["h"] == 150, row          # hits allowed, the new field
    assert row["hr"] == 22, row
    assert row["w"] == 11 and row["l"] == 7, row
    assert abs(row["k_pct"] - 180 / 700) < 1e-12, row
    assert abs(row["innings"] - 170.333) < 0.01, row

    # A pitcher with no season line returns the empty shape, not a KeyError,
    # and every caller reads it with .get() anyway.
    empty = parse_pitcher_season({"stats": [{"splits": []}]})
    assert empty["h"] is None and empty["bf"] is None, empty
    assert set(empty) == set(EMPTY_PITCHER), empty

    # A missing hits field is None, not zero. Zero would read as a pitcher
    # who has never allowed a hit and would rank top of every board.
    no_hits = parse_pitcher_season({"stats": [{"splits": [{"stat": {
        "battersFaced": 100, "inningsPitched": "25.0"}}]}]})
    assert no_hits["h"] is None, no_hits

    # The empty template must not be handed out by reference; a caller that
    # mutated it would corrupt every later empty result.
    a = parse_pitcher_season({})
    a["h"] = 999
    assert parse_pitcher_season({})["h"] is None, "EMPTY_PITCHER was shared"

    print("mlb_api self-test: the pitcher parser holds")


if __name__ == "__main__":
    _self_test()
```

Run it:

```bash
cd craftypicks && python3 scripts/mlb_api.py
```

Expected: `mlb_api self-test: the pitcher parser holds`

Then confirm the callers still work:

```bash
cd craftypicks && python3 scripts/batters.py && python3 scripts/pitchers.py 2>/dev/null; \
  python3 -c "import sys; sys.path.insert(0,'scripts'); import pitchers, homers, batters; print('callers import clean')"
```

Expected: `callers import clean`

- [ ] **Step 7: Commit**

```bash
git add craftypicks/scripts/batters.py craftypicks/scripts/mlb_api.py
git commit -m "feat: the parsers keep the hits they were already fetching

Both payloads carried hits and both parsers dropped them. This is a
parser change, not a second request: the credit cost is zero and the
request count is unchanged."
```

---

## Task 6: The hit-chance model

**Files:**
- Create: `craftypicks/scripts/hits.py`

**Interfaces:**
- Consumes: `batters.parse_batters` rows with `"h"` (Task 5); `mlb_api.pitcher_season` with `"h"` (Task 5); `projection.grade_counting`, `projection.calibration` (Task 3)
- Produces:
  - `hit_chance(batter_rate: float, pitcher_rate: float, league: float, park: float, pa_per_game: float) -> float`
  - `league_rate(table: dict) -> float`
  - `park_factors(season: int) -> dict[int, dict]` — each value `{"factor": float, "raw": float, "home_games": int}`, matching `batters.park_factors` exactly
  - `build(starters: list[dict], season: int) -> list[dict]`
  - `grade(history: list[dict], table: dict) -> int`
  - `summary(history: list[dict]) -> dict`
  - Each row from `build`: `{"batter_id", "name", "team_id", "team", "h", "pa", "hit_rate", "pa_per_game", "chance", "vs", "vs_hand", "vs_h_per_bf", "park", "park_raw", "league_rate", "commence_time", "h_at_projection", "got_hit"}`

**Field names that are easy to get wrong, taken from `batters.build`:**
`"team"` comes from the *starter's* row as `s.get("opponent")`, not from the
batter table — `parse_batters` rows carry `team_id` and no abbreviation.
`"commence_time"` comes from `s.get("game_time")`; the starter rows do not
have a `commence_time` key, and reading one would store `None` and silently
break both the dedupe key and the card grouping.

- [ ] **Step 1: Write the failing test**

Create `craftypicks/scripts/hits.py` containing only this:

```python
def _self_test() -> None:
    # A league-average batter against a league-average pitcher returns the
    # league rate. If this fails the model is not log5.
    lg = 0.25
    assert abs(odds_ratio(lg, lg, lg) - lg) < 1e-12

    # Doubling both sides quadruples the rate -- not triples, not doubles.
    assert abs(odds_ratio(2 * lg, 2 * lg, lg) - 4 * lg) < 1e-12

    # A zero league rate cannot divide, and must not raise.
    assert odds_ratio(0.3, 0.3, 0.0) == 0.0

    # Chance rises with plate appearances and never reaches certainty.
    a = hit_chance(0.25, 0.25, 0.25, 1.0, 3.0)
    b = hit_chance(0.25, 0.25, 0.25, 1.0, 4.5)
    assert 0.0 < a < b < 1.0, (a, b)

    # Four plate appearances at a flat 25% is 1 - 0.75^4.
    flat = hit_chance(0.25, 0.25, 0.25, 1.0, 4.0)
    assert abs(flat - (1 - 0.75 ** 4)) < 1e-9, flat

    # No plate appearances, no chance -- and no ZeroDivisionError.
    assert hit_chance(0.25, 0.25, 0.25, 1.0, 0.0) == 0.0

    # A friendly park raises it, a hostile park lowers it.
    hot = hit_chance(0.25, 0.25, 0.25, 1.10, 4.0)
    cold = hit_chance(0.25, 0.25, 0.25, 0.90, 4.0)
    assert cold < flat < hot, (cold, flat, hot)

    # The league rate is total hits over total plate appearances, and
    # batters under the floor still count toward it.
    table = {1: {"h": 150, "pa": 600}, 2: {"h": 5, "pa": 20}}
    assert abs(league_rate(table) - 155 / 620) < 1e-12

    # An empty table cannot divide by zero.
    assert league_rate({}) == 0.0

    # Grading and calibration ride on the shared engine.
    hist = [{"batter_id": 1, "h_at_projection": 100, "got_hit": None,
             "chance": 0.75}]
    assert grade(hist, {1: {"h": 101}}) == 1
    assert hist[0]["got_hit"] is True
    assert summary(hist)["graded"] == 1
    print("hits self-test: the model holds and grades itself")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd craftypicks && python3 scripts/hits.py
```

Expected: `NameError: name 'odds_ratio' is not defined`

- [ ] **Step 3: Write the model**

Insert above `_self_test`:

```python
"""Which batters are most likely to get a hit tonight, and why.

The same shape as the home-run board, and deliberately so -- the model is
the odds ratio, sometimes called log5:

    rate = batter_H_per_PA * pitcher_H_per_BF / league_H_per_PA

A batter who hits twice as often as average, against a pitcher who allows
hits twice as often, is four times as likely as the league -- not three, and
not one and a half. That relation is the whole model. The park multiplies
it, and his plate appearances turn a per-PA rate into a per-game chance.

Everything it needs is already on the wire. The batter leaderboard and the
starter's line are fetched for the home-run board anyway; this reads the
hits column of the same payloads. The board costs nothing to add.

The park factor is computed on hits, not borrowed from the home-run board.
Coors inflates both, but not by the same multiple, and reusing that factor
would be a quiet error that nothing would ever surface.

What it does NOT have is a lineup card. Lineups post about two hours before
first pitch and this runs in the morning, so "the best bats" means the club's
most dangerous regulars, not tonight's nine. The page says so.
"""
from __future__ import annotations

import batters as batters_mod
import mlb_api
import projection

# A starter throws about five and a bit innings of nine, so he faces roughly
# this share of a lineup's plate appearances. The rest meet a bullpen, which
# is modelled as league-average rather than pretended not to exist.
SHARE_VS_STARTER = 0.58

# One season of home-and-away splits is a noisy park factor: half a season in
# each column, and the same lineups on both sides of it. Half weight is
# conservative and stated rather than tuned.
PARK_REGRESSION = 0.5

# Below this a season line is not a rate, it is a sample. Such batters still
# count toward the league total; they are just never ranked.
MIN_PA = 100

# How many names per club the page shows.
TOP_N = 3


def odds_ratio(batter: float, pitcher: float, league: float) -> float:
    """The log5 combination of two rates against a league baseline."""
    if league <= 0:
        return 0.0
    return max(0.0, batter * pitcher / league)


def hit_chance(batter_rate: float, pitcher_rate: float, league: float,
               park: float, pa_per_game: float) -> float:
    """Probability this batter gets at least one hit tonight.

    The starter and the bullpen are separate terms. Both are multiplied by
    the park, because the park applies to the whole game and not only to the
    portion of it the starter is in.
    """
    if pa_per_game <= 0:
        return 0.0
    p_start = min(0.99, odds_ratio(batter_rate, pitcher_rate, league) * park)
    p_pen = min(0.99, batter_rate * park)
    pa_s = pa_per_game * SHARE_VS_STARTER
    pa_p = pa_per_game * (1.0 - SHARE_VS_STARTER)
    return 1.0 - ((1.0 - p_start) ** pa_s) * ((1.0 - p_pen) ** pa_p)


def league_rate(table: dict) -> float:
    """Hits per plate appearance across the whole league.

    Every batter counts toward this, including those under MIN_PA. They are
    part of the league; they are simply not ranked.
    """
    pa = sum(r.get("pa", 0) for r in table.values())
    if pa <= 0:
        return 0.0
    return sum(r.get("h", 0) for r in table.values()) / pa


def grade(history: list[dict], table: dict) -> int:
    """Fill in whether each projected batter has since got a hit."""
    return projection.grade_counting(
        history, table, id_key="batter_id", at_key="h_at_projection",
        verdict_key="got_hit", total_key="h")


def summary(history: list[dict]) -> dict:
    """Calibration: what was promised against what happened."""
    return projection.calibration(history, verdict_key="got_hit")
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/hits.py
```

Expected: `hits self-test: the model holds and grades itself`

- [ ] **Step 5: Commit**

```bash
git add craftypicks/scripts/hits.py
git commit -m "feat: the hit-chance model

Log5 on hits, park-adjusted, split between the starter and the bullpen.
The park factor is computed on hits rather than borrowed from the
home-run board -- Coors inflates both, but not by the same multiple."
```

---

## Task 7: `park_factors` and `build`

Split from Task 6 because these two touch the network and the rest of the
model does not. A reviewer can accept the arithmetic and reject the fetching.

**Files:**
- Modify: `craftypicks/scripts/hits.py`

**Interfaces:**
- Consumes: `hits.hit_chance`, `hits.league_rate` (Task 6); `batters_mod.all_batters` (existing); `mlb_api.pitcher_season` with `"h"` (Task 5)
- Produces: `parse_park(hitting, pitching) -> dict[int, dict]`, `park_factors(season) -> dict[int, dict]`, `build(starters, season) -> list[dict]`

- [ ] **Step 1: Write the failing test**

Add to `_self_test()` in `scripts/hits.py`, before the final `print`:

```python
    # parse_park regresses half-way to neutral: a raw 1.20 becomes 1.10.
    raw = {113: 1.20, 135: 0.80}
    reg = {k: 1.0 + (v - 1.0) * PARK_REGRESSION for k, v in raw.items()}
    assert abs(reg[113] - 1.10) < 1e-12, reg
    assert abs(reg[135] - 0.90) < 1e-12, reg

    # build returns nothing rather than raising when there is no data.
    assert build([], 2026) == []
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd craftypicks && python3 scripts/hits.py
```

Expected: `NameError: name 'build' is not defined`

- [ ] **Step 3: Write the fetchers**

Append to `scripts/hits.py`, above `_self_test`:

```python
def parse_park(hitting, pitching) -> dict[int, dict]:
    """Hits at home against hits away, both sides of the ball, regressed.

    Both sides matter: a park that helps hitters helps the visitors too, so
    counting only the home club's bats would read a good offence as a good
    park. Adding the two makes the ratio a property of the ground.

    Returns the same shape as batters.park_factors -- factor, raw, and the
    home game count, which build() needs to turn a season plate-appearance
    total into a per-game rate without asking for it separately.
    """
    home: dict = {}
    away: dict = {}
    games: dict = {}
    for payload in (hitting, pitching):
        stats = (payload or {}).get("stats") or []
        splits = stats[0].get("splits", []) if stats else []
        for sp in splits:
            tid = (sp.get("team") or {}).get("id")
            code = ((sp.get("split") or {}).get("code") or "").lower()
            stat = sp.get("stat") or {}
            gp = int(stat.get("gamesPlayed") or 0)
            if tid is None or code not in ("h", "a") or not gp:
                continue
            tid = int(tid)
            per_game = int(stat.get("hits") or 0) / gp
            if code == "h":
                home[tid] = home.get(tid, 0.0) + per_game
                games[tid] = gp
            else:
                away[tid] = away.get(tid, 0.0) + per_game

    out: dict = {}
    for tid, h in home.items():
        a = away.get(tid)
        if not a:
            continue
        raw = h / a
        out[tid] = {"factor": 1.0 + (raw - 1.0) * PARK_REGRESSION,
                    "raw": raw,
                    "home_games": games.get(tid, 0)}
    return out


def park_factors(season: int) -> dict[int, dict]:
    """Every club's hit park factor, in two requests.

    Both are calls the home-run board already makes, so on a run that builds
    both boards these come out of mlb_api's cache and cost nothing at all.

    limit=100 is not optional: statSplits pages at 50 by default, and thirty
    clubs across two splits is sixty rows. Ten would vanish in silence, and
    the missing parks would read as neutral rather than as missing.
    """
    hitting = mlb_api._get("/teams/stats", stats="statSplits", sitCodes="h,a",
                           season=season, group="hitting", sportIds=1,
                           limit=100)
    pitching = mlb_api._get("/teams/stats", stats="statSplits", sitCodes="h,a",
                            season=season, group="pitching", sportIds=1,
                            limit=100)
    return parse_park(hitting, pitching)


def build(starters: list[dict], season: int) -> list[dict]:
    """The best bats in each of tonight's games, with a hit chance attached.

    `starters` is what mlb_api.probable_starters returns, and each row here
    is a batter facing the OTHER club's starter -- so a batter's opponent is
    the pitcher listed against his own team.

    Returns an empty list rather than raising when anything it needs is
    missing. An empty board says nothing; a traceback stops the daily run.
    """
    if not starters:
        return []
    table = batters_mod.all_batters(season)
    if not table:
        return []
    league = league_rate(table)
    if league <= 0:
        return []
    parks = park_factors(season)

    # Games played per club, so a season plate-appearance total becomes a
    # per-game rate. Taken from the park splits, which counted them already.
    games = {tid: v["home_games"] * 2 for tid, v in parks.items()}

    by_team: dict = {}
    for pid, r in table.items():
        if r["pa"] >= MIN_PA and r["team_id"]:
            by_team.setdefault(r["team_id"], []).append((pid, r))

    rows = []
    for s in starters:
        opp_id = s.get("opponent_id")
        pitcher = mlb_api.pitcher_season(s.get("pitcher_id"), season) or {}
        bf = pitcher.get("bf") or 0
        p_rate = ((pitcher["h"] / bf)
                  if (bf and pitcher.get("h") is not None) else None)
        if p_rate is None:
            continue
        # The park belongs to the home club, and the starter's row says which
        # side he is on: if he is away, his own club is not the host.
        home_id = s.get("team_id") if s.get("is_home") else opp_id
        park_row = parks.get(home_id) or {}
        park = park_row.get("factor", 1.0)

        cand = []
        for pid, b in by_team.get(opp_id, []):
            gp = games.get(opp_id) or 0
            if not gp:
                continue
            pa_pg = b["pa"] / gp
            rate = b["h"] / b["pa"]
            cand.append({
                "batter_id": pid, "name": b["name"], "team_id": opp_id,
                "team": s.get("opponent"), "h": b["h"], "pa": b["pa"],
                "hit_rate": rate, "pa_per_game": pa_pg,
                "chance": hit_chance(rate, p_rate, league, park, pa_pg),
                "vs": s.get("name"), "vs_hand": s.get("hand", ""),
                "vs_h_per_bf": p_rate,
                "park": park, "park_raw": park_row.get("raw"),
                "league_rate": league,
                "commence_time": s.get("game_time"),
                "h_at_projection": b["h"], "got_hit": None,
            })
        cand.sort(key=lambda r: r["chance"], reverse=True)
        rows.extend(cand[:TOP_N])

    rows.sort(key=lambda r: r["chance"], reverse=True)
    return rows
```

Three field names here are inherited from `batters.build` and are easy to get
wrong. `"team"` is `s.get("opponent")`, because `parse_batters` rows carry
only `team_id` and no abbreviation. `"commence_time"` is `s.get("game_time")`,
because that is what the starter rows call it — reading `commence_time` from
them stores `None`, which silently breaks both the dedupe key and the card
grouping. And the pitcher's rate reads `pitcher["h"]`, the hits allowed added
in Task 5, not `pitcher["hr"]`.

- [ ] **Step 4: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/hits.py
```

Expected: `hits self-test: the model holds and grades itself`

- [ ] **Step 5: Test `build` behaviourally, with the network stubbed**

Three field names here fail silently rather than raising, so they need a
test that reads the output rather than the source. Add to `_self_test()` in
`scripts/hits.py`, before the final `print`:

```python
    # build(), with every fetch stubbed. The three fields checked here are
    # the ones a careless copy from batters.build gets wrong, and none of
    # them would raise -- each would just produce a quietly wrong board.
    import mlb_api as _api
    _real_ps, _real_ab, _real_pf = (_api.pitcher_season,
                                    batters_mod.all_batters, park_factors)
    try:
        _api.pitcher_season = lambda pid, yr: {"bf": 700, "h": 175, "hr": 20}
        batters_mod.all_batters = lambda yr: {
            7: {"name": "A Batter", "team_id": 119, "h": 150, "pa": 600},
            8: {"name": "Bench Guy", "team_id": 119, "h": 5, "pa": 20},
        }
        globals()["park_factors"] = lambda yr: {
            135: {"factor": 1.0, "raw": 1.0, "home_games": 81}}
        rows = build([{"pitcher_id": 1, "name": "A Pitcher", "team_id": 135,
                       "opponent_id": 119, "opponent": "LAD", "is_home": True,
                       "hand": "R", "game_time": "2026-09-04T22:00:00Z"}], 2026)
    finally:
        _api.pitcher_season, batters_mod.all_batters = _real_ps, _real_ab
        globals()["park_factors"] = _real_pf

    assert len(rows) == 1, f"the 20-PA bench bat must not be ranked: {rows}"
    r = rows[0]
    assert r["commence_time"] == "2026-09-04T22:00:00Z", r["commence_time"]
    assert r["team"] == "LAD", r["team"]
    assert abs(r["vs_h_per_bf"] - 175 / 700) < 1e-12, r["vs_h_per_bf"]
    assert abs(r["pa_per_game"] - 600 / 162) < 1e-9, r["pa_per_game"]
    assert 0.55 < r["chance"] < 0.85, f"a .250 bat should be near 70%: {r}"
    assert r["got_hit"] is None and r["h_at_projection"] == 150, r

    # No starters, no rows -- and no exception.
    assert build([], 2026) == []
```

- [ ] **Step 6: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/hits.py
```

Expected: `hits self-test: the model holds and grades itself`

- [ ] **Step 7: Commit**

```bash
git add craftypicks/scripts/hits.py
git commit -m "feat: hit park factors and the board build

Both requests are the ones the home-run board already makes, so on a run
that builds both they come out of the cache and cost nothing."
```

---

## Task 8: The page, and the run that fills it

**Files:**
- Create: `craftypicks/_src/hits.body.html`
- Modify: `craftypicks/_src/build.py` (PAGES, VIEWS, TITLES)
- Modify: `craftypicks/_src/i18n.py`
- Modify: `craftypicks/_src/render.py`
- Modify: `craftypicks/scripts/run_boards.py`

**Interfaces:**
- Consumes: `hits.build`, `hits.grade`, `hits.summary` (Tasks 6–7); `projection.merge` (Task 3)
- Produces: `data/hits.json`, `data/hit_ratings.json`, and the page `hits.html`

- [ ] **Step 1: Add the navigation label**

In `_src/i18n.py`, beside `"nav_batters"`, add:

```python
    "nav_hits":      {"en": "Hits", "es": "Hits"},
```

and beside the batter board's copy keys add:

```python
    "hit_empty":     {"en": "No probable starters listed yet. This board "
                            "fills in once tonight's pitchers are announced.",
                      "es": "Aún no hay lanzadores probables. Esta pizarra se "
                            "llena cuando se anuncien los abridores."},
    "hit_season":    {"en": "{h} hits in {pa} PA ({rate}%)",
                      "es": "{h} hits en {pa} AP ({rate}%)"},
    "hit_facing":    {"en": "Facing {who}{hand} — allows a hit to {rate}% "
                            "of the batters he faces",
                      "es": "Contra {who}{hand} — permite hit al {rate}% "
                            "de los bateadores"},
    "hit_park":      {"en": "Park {v}", "es": "Estadio {v}"},
    "hit_ungraded":  {"en": "Not graded yet. Every projection on this board "
                            "is settled the next morning.",
                      "es": "Aún sin calificar. Cada proyección se resuelve "
                            "a la mañana siguiente."},
```

- [ ] **Step 2: Register the page**

In `_src/build.py`, in `PAGES`, beside `"batters.html"`, add:

```python
    "hits.html":     Page("hits.html",     "hits",     "hits",     "mlb"),
```

In `TITLES`, beside the batters entry, add:

```python
    "hits.html": {"en": f"Hits — {config.SITE_NAME}",
                  "es": f"Hits — {config.SITE_NAME}"},
```

In `VIEWS`, add `("hits.html", "nav_hits")` to the MLB list, after
`("batters.html", "nav_batters")`:

```python
            + ([("pitchers.html", "nav_pitchers"),
                ("batters.html", "nav_batters"),
                ("hits.html", "nav_hits"),
                ("homers.html", "nav_homers")]
```

- [ ] **Step 3: Write the card renderer**

In `_src/render.py`, beside `batter_cards`, add:

```python
def hit_cards(rows: list[dict]) -> str:
    """Tonight's best chances of a hit, grouped by the game they appear in."""
    if not rows:
        return f'<div class="empty-board">{_("hit_empty")}</div>'
    games: dict = {}
    for r in rows:
        games.setdefault((r.get("commence_time"), r.get("vs")), []).append(r)

    out = []
    for (when, pitcher), group in games.items():
        club = esc(_nickname(group[0].get("team")))
        hand = group[0].get("vs_hand") or ""
        hand_txt = (f' ({_("mx_right") if hand == "R" else _("mx_left")})'
                    if hand in ("L", "R") else "")
        park = group[0].get("park") or 1.0
        park_cls = "good" if park > 1.03 else "bad" if park < 0.97 else ""
        vs_rate = f"{(group[0].get('vs_h_per_bf') or 0) * 100:.1f}"
        bats = "".join(f"""
          <div class="bat">
            <div class="bat-n">{esc(b.get('name',''))}</div>
            <div class="bat-c"><b>{b['chance'] * 100:.1f}%</b></div>
            <div class="bat-w">{_("hit_season",
                h=b.get('h', 0), pa=f"{b.get('pa', 0):,}",
                rate=f"{b.get('hit_rate', 0) * 100:.1f}")}</div>
          </div>""" for b in group)
        accent = team_color(group[0].get('team')) or 'var(--line-2)'
        out.append(f"""
        <article class="pb-card bat-card" style="--accent:{accent}">
          <div class="pb-top">
            <span>{club} &middot; {esc(game_time(when))}</span>
            <span class="bat-park {park_cls}">{_("hit_park",
                v=f"{park:.2f}")}</span>
          </div>
          <div class="pb-body">
            <div class="bat-vs">{_("hit_facing",
                who=esc(pitcher or "?"), hand=hand_txt, rate=vs_rate)}</div>
            {bats}
          </div>
        </article>""")
    return '<div class="pb-grid">' + "".join(out) + "</div>"
```

Note `accent` and `vs_rate` are computed before the f-string. Python 3.11
cannot reuse the outer quote character inside an f-string expression, and
this has broken this build three times.

Add the calibration block, delegating to the batter version's markup:

```python
def hit_calibration(summary: dict) -> str:
    """What the model promised against what happened. Not a win rate."""
    n = (summary or {}).get("graded") or 0
    if not n:
        return f'<p class="pnl-note">{_("hit_ungraded")}</p>'
    return batter_calibration(summary)
```

- [ ] **Step 4: Write the page copy**

Create `craftypicks/_src/hits.body.html`:

```html
<div class="wrap">
  <p class="kicker">{{DATE_LABEL}} &middot; {{HIT_COUNT}}</p>
  <h1>Hits</h1>
  <p class="lede">Each club's most dangerous regulars, and the chance
  each one gets at least one hit tonight. The number is our own: the
  batter's hit rate against the starter's, measured against the league,
  adjusted for the park, over the plate appearances he can expect.</p>

  <p>There is no book line beside it, and that is deliberate — this board
  costs nothing to produce. It reads the hits column of payloads the home
  run board already fetches.</p>

  <p>What it does not have is a lineup card. Lineups post about two hours
  before first pitch and this runs in the morning, so these are the club's
  most dangerous regulars, not tonight's nine. A rested batter is still
  listed.</p>

  {{HIT_CARDS}}

  <h2>How it has done</h2>
  <p>Every projection here is graded the next morning, whether or not
  anyone bet it. What matters is not the record but the calibration: a
  group called 70% should get a hit about 70% of the time.</p>

  {{HIT_CALIBRATION}}
</div>
```

- [ ] **Step 5: Wire the tokens**

In `_src/build.py`, find where `batters.html` loads `data/batters.json` and
substitutes `{{BAT_CARDS}}`. Add the parallel block for hits, substituting
`{{HIT_CARDS}}` with `R.hit_cards(...)`, `{{HIT_CALIBRATION}}` with
`R.hit_calibration(...)`, `{{DATE_LABEL}}` with the document's `date_label`,
and `{{HIT_COUNT}}` with the row count phrased as `"N batters rated"`.

- [ ] **Step 6: Build and check the guard**

```bash
cd craftypicks && python3 _src/build.py && python3 scripts/palette.py && test -s hits.html && echo "hits.html built"
```

Expected: the build runs, palette reports no failures, `hits.html built`.

If palette rejects a selector, change the colour to `--muted` rather than
exempting the rule. The guard has been right every time it has fired.

- [ ] **Step 7: Build the board in the daily boards run**

In `scripts/run_boards.py`, add `import hits as hits_mod` and
`import projection` beside the existing imports, and after the batter block
add — at the same indentation as the batter block, **not nested inside it**:

```python
    # ---------------------------------------------------------- hits
    hit_hist = load_json(DATA / "hit_ratings.json", {"batters": []})["batters"]
    hit_settled = hits_mod.grade(hit_hist, table)
    hit_rows = hits_mod.build(starters, season)
    hit_added = projection.merge(hit_hist, hit_rows,
                                 ("batter_id", "commence_time"))
    hit_summary = hits_mod.summary(hit_hist)
    save_json(DATA / "hit_ratings.json", {"batters": hit_hist})

    if hit_rows:
        save_json(DATA / "hits.json", {
            "date": today,
            "date_label": label,
            "batters": hit_rows,
            "summary": hit_summary,
        })
        print(f"-- hits: {len(hit_rows)} rated, {hit_added} new, "
              f"{hit_settled} graded")
    else:
        print("!! hits: no lineup cleared the plate-appearance floor",
              file=sys.stderr)
```

`table` is the batter leaderboard already fetched for the batter board.
Reusing it is what keeps this free: no new request.

- [ ] **Step 8: Verify the boards run end to end, offline**

```bash
cd craftypicks && python3 - <<'PY'
import sys, json, tempfile, pathlib, shutil
sys.path.insert(0, "scripts")
tmp = pathlib.Path(tempfile.mkdtemp()); (tmp / "data").mkdir()
import run_boards as rb, mlb_api, batters, hits
rb.DATA = tmp / "data"
S = [{"pitcher_id": 1, "name": "A Pitcher", "team_id": 135,
      "opponent_id": 119, "opponent": "LAD", "is_home": True, "hand": "R",
      "game_time": "2026-09-04T22:00:00Z"}]
mlb_api.probable_starters = lambda d: S
# A .250 hitter with 600 PA over 81*2 games.
T = {7: {"name": "A Batter", "team_id": 119, "hr": 30, "h": 150, "pa": 600}}
batters.all_batters = lambda y: T
batters.build = lambda s, y: []
# Both clubs, not just the pitching one: build() derives its games-played
# map from parks and looks it up by the BATTING club, so a stub covering
# only team 135 silently returns an empty board.
hits.park_factors = lambda y: {
    135: {"factor": 1.0, "raw": 1.0, "home_games": 81},
    119: {"factor": 1.0, "raw": 1.0, "home_games": 81}}
mlb_api.pitcher_season = lambda p, y: {"bf": 700, "h": 175, "hr": 20}
assert rb.main() == 0
d = json.loads((tmp / "data" / "hits.json").read_text())
assert d["batters"], "no hit rows written"
row = d["batters"][0]
assert row["commence_time"] == "2026-09-04T22:00:00Z", row["commence_time"]
assert row["team"] == "LAD", row["team"]
print("hits rows:", len(d["batters"]),
      "| top chance:", round(row["chance"] * 100, 1), "%")
assert 60 < row["chance"] * 100 < 80, "a .250 hitter should land near 70%"
assert rb.main() == 0
h = json.loads((tmp / "data" / "hit_ratings.json").read_text())["batters"]
assert len(h) == 1, f"dedupe failed: {len(h)}"
print("OK: written once, deduped on the second run")
shutil.rmtree(tmp)
PY
```

Expected: a plausible chance (a .250 hitter over 4.3 PA should land near 70%), then `OK: written once, deduped on the second run`.

- [ ] **Step 9: Commit**

```bash
git add craftypicks/_src craftypicks/scripts/run_boards.py
git commit -m "feat: the Hits board

Each club's most dangerous regulars and their chance of at least one hit,
from the hits column of payloads the home-run board already fetches. No
book line, no new request, graded the next morning like everything else."
```

- [ ] **Step 10: Package for the user**

Source files only. No built HTML — an archive containing built pages
overwrote the user's newer pages once already. No workflow files —
`GITHUB_TOKEN` cannot write them and apply-update rejects the archive.

```bash
cd /tmp && rm -rf pkg hits.zip && mkdir -p pkg/craftypicks/scripts pkg/craftypicks/_src
cp /tmp/cps/craftypicks/scripts/{projection.py,hits.py,batters.py,mlb_api.py,run_boards.py} pkg/craftypicks/scripts/
cp /tmp/cps/craftypicks/_src/{build.py,render.py,i18n.py,hits.body.html} pkg/craftypicks/_src/
cd pkg && zip -qr /tmp/hits.zip . && unzip -l /tmp/hits.zip
```

Then tell the user: delete the previous zip, upload this one, run
**Apply update**, then **Build home-run boards**.

---

## Self-Review

**Spec coverage.** §1 nav fix → Task 1. §2 MLB data → Task 5. §2 NFL probe →
Task 2. §3 binary model → Tasks 6–7. §5 grading and calibration → Tasks 3–4,
8. §6 file structure → Tasks 3, 6, 8. §7 error handling → Task 7 Step 3
(`build` returns `[]`), Task 8 Step 7 (indentation called out explicitly).
§8 testing → every task's self-test.

**Gap, accepted deliberately:** §3's NFL models, §4's cold start and §6's NFL
files have no task here. They are the second plan, gated on Task 2's log.
This is stated at the top rather than left for a reader to discover.

**Gap, accepted:** §5's `error_summary` is written and tested in Task 3 but
has no caller until the NFL yardage boards exist. It is built now because
the engine is being written now and splitting it across two plans would mean
touching the file twice.

**Corrections made during this review, against the real code:**

1. `park_factors` returns `dict[int, dict]` with `factor`, `raw` and
   `home_games` — not floats. The draft's float version would have thrown
   `AttributeError` at `parks.get(id).get("factor")`.
2. `pa_per_game` comes from `pa / (home_games * 2)`, as in `batters.build`.
   The draft hardcoded `4.3` and called `team_hr_per_game` only to discard
   the result — a request paid for and thrown away.
3. `"commence_time"` reads `s.get("game_time")`. The draft read
   `s.get("commence_time")`, which the starter rows do not have. It would
   have stored `None` and broken the dedupe key and the card grouping
   without raising anything.
4. `"team"` reads `s.get("opponent")`. The draft read it from the batter
   table, which carries only `team_id`.

All four were silent failures, not crashes, which is why Task 7 Step 5
asserts on them directly.

**Type consistency.** `grade_counting(history, totals, *, id_key, at_key,
verdict_key, total_key)` — Task 3 defines it, Tasks 4 and 6 call it with
exactly those keywords. `merge(history, rows, key_fields)` — Task 3 defines,
Task 8 calls. `hits.build/grade/summary` — Task 6 declares, Tasks 7 and 8
use. Row field names in Task 6's Interfaces block match Task 7's `build` and
Task 8's renderer: `h`, `pa`, `hit_rate`, `chance`, `vs`, `vs_hand`,
`vs_h_per_bf`, `park`, `commence_time`, `h_at_projection`, `got_hit`.
