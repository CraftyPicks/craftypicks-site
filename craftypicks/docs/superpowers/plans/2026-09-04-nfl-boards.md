# NFL Player Boards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four free, graded NFL boards — passing, rushing and receiving yards, and anytime touchdown — built on nflverse data whose field names were read from a probe rather than guessed.

**Architecture:** `nfl_data.py` downloads and parses two public files and derives team defence from one of them. `nfl_yards.py` projects a continuous total; `nfl_td.py` projects a probability. Both store, grade and score through the existing `projection.py`. Pages follow the Hits board exactly.

**Tech Stack:** Python 3.11 standard library only. nflverse GitHub release assets (gzipped CSV, no key). Static HTML built by `_src/build.py`.

## Global Constraints

- **No new paid data.** Nothing here may call The Odds API. The daily credit spend must not change by one credit.
- **Python 3.11 standard library only.** `urllib.request`, `csv`, `gzip`, `io`, `json`. No pandas, no requests.
- **No book line on these boards.** They show our number and grade it.
- **Every projection is graded, whether or not it becomes a play.**
- **Nothing is graded before its game has finished.** `projection.game_over` is the gate. Grading a projection early writes a permanent wrong answer; this shipped once on the MLB boards and must not ship again.
- **Tests are `_self_test()` at the bottom of the module, run with `python3 scripts/<module>.py`.** No pytest, no `tests/` directory.
- **Parsers pure, fetches thin.** This sandbox reaches no host but the Craftypicks repo, so anything testable only online is untestable.
- **`season_type == "REG"` and a non-blank `player_id` are mandatory filters.** The 2025 file contains rows with no player at all.
- **A blank numeric field is `None`, never `0`.** A quarterback with no line did not throw for zero yards.
- **`python3 _src/build.py` runs the registry invariants; `python3 scripts/palette.py` must pass.** `--dim` is 3.0:1 and may only caption meaning carried elsewhere.
- **f-strings:** Python 3.11 cannot reuse the outer quote character inside an expression and cannot contain a backslash. Precompute into a local variable.
- **Archives contain source only** — no built HTML, nothing under `.github/workflows`.

---

## What the probe established

Verified by two runs in Actions; do not re-derive these.

| Fact | Consequence |
|---|---|
| `player_stats.csv.gz` newest season is **2024** | Never use it. It is deprecated. |
| `stats_player_week_2025.csv.gz` exists: 19,422 rows, 150 cols | This is the source. |
| `stats_player_week_2026.csv.gz` **absent** | Blend weight `w` is 0 until it appears. |
| `depth_charts_2026` newest snapshot is **2026-03-22** | Dropped. Nothing fetches it. |
| `games.csv` has `home_qb_name` / `away_qb_name` | Starting QB comes free with the schedule. |
| `games.csv` has 272 REG games for 2026, opening 2026-09-09 | Five days out, not one. |
| Last row of the weekly file has a blank `player_id` | Filter it, or league averages sag. |
| Missing numerics arrive as `''` | Parse to `None`, exclude from rates. |

Asset URLs are found by listing every release with `?per_page=100` and paging — the same walk `research/probe_nfl.py` already does. Reuse that shape; do not hardcode a download URL, because the release host path changes.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/nfl_data.py` (create) | Asset discovery, download, pure parsers, team-defence aggregation, the 2025/2026 blend. |
| `scripts/nfl_yards.py` (create) | Passing, rushing, receiving. One model, three categories. |
| `scripts/nfl_td.py` (create) | Anytime touchdown, Poisson. |
| `scripts/run_boards.py` (modify) | Builds the four NFL boards beside the MLB ones. |
| `_src/build.py` (modify) | Four pages in `PAGES`, `VIEWS`, titles. |
| `_src/render.py` (modify) | `yard_cards`, `td_cards`, `yard_accuracy`. |
| `_src/i18n.py` (modify) | Nav labels and page copy, `en` and `es`. |
| `_src/nfl_passing.body.html` and three siblings (create) | Page copy. |

Pages are `nfl/passing.html`, `nfl/rushing.html`, `nfl/receiving.html`, `nfl/td.html` — under `nfl/`, matching `nfl/form.html` and leaving room for `nba/points.html` later.

---

## Task 1: Read the nflverse files

**Files:**
- Create: `craftypicks/scripts/nfl_data.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `asset_urls() -> dict[str, str]` — every release asset name mapped to its download URL
  - `fetch_csv_gz(url: str) -> list[dict] | None`
  - `parse_weekly(rows: list[dict]) -> list[dict]` — cleaned REG rows with real players
  - `parse_schedule(rows: list[dict], season: int) -> list[dict]`
  - `num(value) -> float | None` — blank-safe numeric parse
  - `WEEKLY_FIELDS: tuple[str, ...]`

- [ ] **Step 1: Write the failing test**

Create `craftypicks/scripts/nfl_data.py` containing only this:

```python
def _self_test() -> None:
    # A blank is not a zero. A quarterback with no line did not throw for
    # zero yards -- he has no line, and averaging a zero in would be a lie.
    assert num("") is None
    assert num(None) is None
    assert num("0") == 0.0
    assert num("60") == 60.0
    assert num("6.24877") == 6.24877
    assert num("not a number") is None

    raw = [
        # A real line.
        {"player_id": "00-0000003", "player_display_name": "A Runner",
         "position": "RB", "position_group": "RB", "team": "MIA",
         "opponent_team": "DEN", "season": "2025", "week": "1",
         "season_type": "REG", "game_id": "2025_01_MIA_DEN",
         "passing_yards": "0", "rushing_yards": "60", "receiving_yards": "7",
         "passing_tds": "0", "rushing_tds": "1", "receiving_tds": "0",
         "attempts": "0", "carries": "16", "targets": "1", "receptions": "1"},
        # Postseason: excluded, because a rate built on it mixes two
        # different populations of opponent.
        {"player_id": "00-0000003", "player_display_name": "A Runner",
         "position": "RB", "position_group": "RB", "team": "MIA",
         "opponent_team": "NE", "season": "2025", "week": "22",
         "season_type": "POST", "game_id": "2025_22_MIA_NE",
         "passing_yards": "0", "rushing_yards": "80", "receiving_yards": "0",
         "passing_tds": "0", "rushing_tds": "1", "receiving_tds": "0",
         "attempts": "0", "carries": "20", "targets": "0", "receptions": "0"},
        # No player at all. The real file ends with one of these.
        {"player_id": "", "player_display_name": "", "position": "",
         "position_group": "", "team": "SEA", "opponent_team": "NE",
         "season": "2025", "week": "22", "season_type": "POST",
         "game_id": "2025_22_SEA_NE",
         "passing_yards": "0", "rushing_yards": "0", "receiving_yards": "0",
         "passing_tds": "0", "rushing_tds": "0", "receiving_tds": "0",
         "attempts": "0", "carries": "0", "targets": "0", "receptions": "0"},
    ]
    weekly = parse_weekly(raw)
    assert len(weekly) == 1, f"REG + real players only: {weekly}"
    w = weekly[0]
    assert w["player_id"] == "00-0000003"
    assert w["rushing_yards"] == 60.0
    assert w["opponent_team"] == "DEN"
    assert w["week"] == 1 and w["season"] == 2025

    games = [
        {"game_id": "2026_01_NE_SEA", "season": "2026", "game_type": "REG",
         "week": "1", "gameday": "2026-09-09", "gametime": "20:15",
         "away_team": "NE", "home_team": "SEA",
         "home_qb_id": "00-0011", "home_qb_name": "Home Passer",
         "away_qb_id": "00-0022", "away_qb_name": "Away Passer",
         "roof": "outdoors", "stadium": "Lumen Field"},
        # A different season, and a preseason game: neither belongs.
        {"game_id": "2025_01_A_B", "season": "2025", "game_type": "REG",
         "week": "1", "gameday": "2025-09-05", "gametime": "20:15",
         "away_team": "A", "home_team": "B", "home_qb_id": "", "home_qb_name": "",
         "away_qb_id": "", "away_qb_name": "", "roof": "dome", "stadium": "X"},
        {"game_id": "2026_00_C_D", "season": "2026", "game_type": "PRE",
         "week": "0", "gameday": "2026-08-10", "gametime": "19:00",
         "away_team": "C", "home_team": "D", "home_qb_id": "", "home_qb_name": "",
         "away_qb_id": "", "away_qb_name": "", "roof": "dome", "stadium": "Y"},
    ]
    sched = parse_schedule(games, 2026)
    assert len(sched) == 1, f"2026 regular season only: {sched}"
    g = sched[0]
    assert g["home_team"] == "SEA" and g["away_team"] == "NE"
    assert g["home_qb_name"] == "Home Passer"
    assert g["week"] == 1
    # An ISO timestamp, because projection.game_over parses one to decide
    # whether a result may be judged yet.
    assert g["commence_time"].startswith("2026-09-09T20:15"), g["commence_time"]

    # A game with no listed time still sorts and still grades -- it just
    # grades later. Missing must never mean "grade it now".
    noon = parse_schedule([dict(games[0], gametime="")], 2026)[0]
    assert noon["commence_time"].startswith("2026-09-09T23:59"), noon

    print("nfl_data self-test: the parsers hold")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd craftypicks && python3 scripts/nfl_data.py
```

Expected: `NameError: name 'num' is not defined`

- [ ] **Step 3: Write the implementation**

Insert above `_self_test`:

```python
"""The free NFL feed, and what is worth keeping from it.

nflverse publishes one gzipped CSV per season of per-player, per-week
lines, plus a schedule. No key, no rate limit, no scraping.

Two things in this data will quietly ruin a rate if they are not handled,
and both were found by probing rather than by reading documentation:

  * the weekly file contains rows with no player at all -- a team, an
    opponent and zeros -- and counting them drags every league average down

  * a missing number arrives as an empty string, not a zero. A quarterback
    with no passing line did not throw for zero yards; he has no line, and
    averaging a zero in is a lie the model cannot see

What this deliberately does NOT read is the depth chart. depth_charts_2026
exists, but its newest snapshot is from March, four months before the
season, so it cannot say who starts. The schedule names the starting
quarterback, and last season's carries and targets say who gets the ball --
both more current than an offseason chart.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

RELEASES = "https://api.github.com/repos/nflverse/nflverse-data/releases"
UA = {"User-Agent": "craftypicks/1.0"}

# The columns the boards use. The file has 150; carrying the rest would
# mean every future reader wondering which ones matter.
WEEKLY_FIELDS = (
    "passing_yards", "rushing_yards", "receiving_yards",
    "passing_tds", "rushing_tds", "receiving_tds",
    "attempts", "carries", "targets", "receptions",
)

_cache: dict = {}


def _get(url: str, want_json: bool = True):
    if url in _cache:
        return _cache[url]
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        # Said out loud on purpose: an unreachable feed and an empty season
        # produce the same empty list downstream, and only this line tells
        # them apart.
        print(f"!! nflverse {url} failed ({type(e).__name__}: {e})",
              file=sys.stderr)
        _cache[url] = None
        return None
    out = json.loads(raw.decode("utf-8")) if want_json else raw
    _cache[url] = out
    return out


def num(value) -> float | None:
    """A numeric field, or None if it is blank or unparseable.

    Deliberately not `float(value or 0)`. Blank means no line, and a zero
    would be counted as a performance.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def asset_urls() -> dict[str, str]:
    """Every release asset name mapped to its download URL.

    Paged, because GitHub returns 30 per page by default and this repo has
    thousands of assets across dozens of releases. Unpaged, the release
    holding the file we want can simply be absent, and the failure looks
    like a clean "not found" rather than a truncated list.
    """
    out: dict[str, str] = {}
    page = 1
    while True:
        batch = _get(f"{RELEASES}?per_page=100&page={page}")
        if batch is None:
            return {}
        if not batch:
            break
        for rel in batch:
            for a in rel.get("assets", []):
                out[a["name"]] = a["browser_download_url"]
        if len(batch) < 100:
            break
        page += 1
    return out


def fetch_csv_gz(url: str) -> list[dict] | None:
    raw = _get(url, want_json=False)
    if raw is None:
        return None
    text = gzip.decompress(raw).decode("utf-8", "replace")
    return list(csv.DictReader(io.StringIO(text)))


def fetch_csv(url: str) -> list[dict] | None:
    raw = _get(url, want_json=False)
    if raw is None:
        return None
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))))


def parse_weekly(rows: list[dict]) -> list[dict]:
    """Regular-season lines belonging to an actual player.

    Both filters matter. A blank player_id is a row with no player, which
    the real file ends with. Postseason rows are excluded because a rate
    built across both mixes two different populations of opponent.
    """
    out = []
    for r in rows or []:
        pid = (r.get("player_id") or "").strip()
        if not pid or (r.get("season_type") or "").strip().upper() != "REG":
            continue
        row = {
            "player_id": pid,
            "name": (r.get("player_display_name") or "").strip(),
            "position": (r.get("position") or "").strip(),
            "position_group": (r.get("position_group") or "").strip(),
            "team": (r.get("team") or "").strip(),
            "opponent_team": (r.get("opponent_team") or "").strip(),
            "season": int(num(r.get("season")) or 0),
            "week": int(num(r.get("week")) or 0),
            "game_id": (r.get("game_id") or "").strip(),
        }
        for f in WEEKLY_FIELDS:
            row[f] = num(r.get(f))
        out.append(row)
    return out


def parse_schedule(rows: list[dict], season: int) -> list[dict]:
    """This season's regular-season games, with their starting passers.

    commence_time is built here rather than at the point of use, because
    projection.game_over needs one timestamp per row to decide whether a
    result may be judged. A game with no listed kickoff gets 23:59, which
    makes it grade late rather than early -- an ungraded row is missing
    from the record, a wrongly graded one is a lie in it.
    """
    out = []
    for r in rows or []:
        if int(num(r.get("season")) or 0) != season:
            continue
        if (r.get("game_type") or "").strip().upper() != "REG":
            continue
        day = (r.get("gameday") or "").strip()
        if not day:
            continue
        clock = (r.get("gametime") or "").strip() or "23:59"
        if len(clock) == 5:
            clock = f"{clock}:00"
        out.append({
            "game_id": (r.get("game_id") or "").strip(),
            "week": int(num(r.get("week")) or 0),
            "gameday": day,
            "commence_time": f"{day}T{clock}+00:00",
            "away_team": (r.get("away_team") or "").strip(),
            "home_team": (r.get("home_team") or "").strip(),
            "home_qb_id": (r.get("home_qb_id") or "").strip(),
            "home_qb_name": (r.get("home_qb_name") or "").strip(),
            "away_qb_id": (r.get("away_qb_id") or "").strip(),
            "away_qb_name": (r.get("away_qb_name") or "").strip(),
            "roof": (r.get("roof") or "").strip(),
            "stadium": (r.get("stadium") or "").strip(),
        })
    out.sort(key=lambda g: (g["week"], g["commence_time"]))
    return out
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/nfl_data.py
```

Expected: `nfl_data self-test: the parsers hold`

- [ ] **Step 5: Commit**

```bash
git add craftypicks/scripts/nfl_data.py
git commit -m "feat: read the free NFL feed

Two traps the probe exposed and this handles: rows with no player at all,
which the weekly file ends with, and blanks that are not zeros. A missing
line averaged in as zero is a lie the model cannot see.

Does not read the depth charts. Their newest snapshot is from March."
```

---

## Task 2: Rates, defence, and the cold start

**Files:**
- Modify: `craftypicks/scripts/nfl_data.py`

**Interfaces:**
- Consumes: `parse_weekly`, `num` (Task 1)
- Produces:
  - `player_rates(weekly, field) -> dict[str, dict]` — per player: `{"name","team","position","total","games","per_game"}`
  - `defence(weekly, field) -> dict[str, float]` — per team, that field allowed per game
  - `league_mean(table, key) -> float`
  - `blend(current, prior, k=BLEND_K) -> dict[str, dict]`
  - `BLEND_K: int`

- [ ] **Step 1: Write the failing test**

Add to `_self_test()` in `scripts/nfl_data.py`, before the final `print`:

```python
    # Rates are per game played, not per week of the season. A player who
    # missed six weeks is not a worse player for it.
    weekly = parse_weekly([
        {"player_id": "p1", "player_display_name": "Runner One",
         "position": "RB", "position_group": "RB", "team": "MIA",
         "opponent_team": "DEN", "season": "2025", "week": "1",
         "season_type": "REG", "game_id": "g1", "rushing_yards": "100",
         "carries": "20", "rushing_tds": "1"},
        {"player_id": "p1", "player_display_name": "Runner One",
         "position": "RB", "position_group": "RB", "team": "MIA",
         "opponent_team": "NE", "season": "2025", "week": "2",
         "season_type": "REG", "game_id": "g2", "rushing_yards": "50",
         "carries": "10", "rushing_tds": "0"},
        {"player_id": "p2", "player_display_name": "Runner Two",
         "position": "RB", "position_group": "RB", "team": "BUF",
         "opponent_team": "DEN", "season": "2025", "week": "1",
         "season_type": "REG", "game_id": "g3", "rushing_yards": "40",
         "carries": "8", "rushing_tds": "0"},
    ])
    rates = player_rates(weekly, "rushing_yards")
    assert rates["p1"]["games"] == 2
    assert rates["p1"]["per_game"] == 75.0, rates["p1"]
    assert rates["p1"]["team"] == "MIA" and rates["p1"]["name"] == "Runner One"

    # Defence is what a team ALLOWED, keyed by opponent_team, and it is per
    # game the defence played -- not per opposing player line, or a team
    # that faced a deep receiving corps would look generous.
    dfn = defence(weekly, "rushing_yards")
    assert dfn["DEN"] == 140.0, dfn      # 100 + 40 in one week
    assert dfn["NE"] == 50.0, dfn

    # The blend. Four games of this season equal all of last season.
    prior = {"p1": {"name": "Runner One", "team": "MIA", "position": "RB",
                    "total": 1000.0, "games": 16, "per_game": 62.5}}
    cur = {"p1": {"name": "Runner One", "team": "MIA", "position": "RB",
                  "total": 300.0, "games": 4, "per_game": 75.0}}
    # w = 4/(4+4) = 0.5 -> halfway between 75 and 62.5
    mixed = blend(cur, prior)
    assert abs(mixed["p1"]["per_game"] - 68.75) < 1e-9, mixed["p1"]
    assert mixed["p1"]["weight"] == 0.5

    # Week 1: no current season at all, so the blend is entirely last year
    # and says so, rather than silently reporting a made-up number.
    week1 = blend({}, prior)
    assert week1["p1"]["per_game"] == 62.5
    assert week1["p1"]["weight"] == 0.0

    # A player with no prior and no current cannot be projected. A rookie
    # is omitted rather than guessed at.
    assert blend({}, {}) == {}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd craftypicks && python3 scripts/nfl_data.py
```

Expected: `NameError: name 'player_rates' is not defined`

- [ ] **Step 3: Write the implementation**

Insert above `_self_test`:

```python
# Four games of this season weigh the same as all of last season. Stated,
# not tuned -- and written where the grading can later argue with it.
BLEND_K = 4


def player_rates(weekly: list[dict], field: str) -> dict[str, dict]:
    """Each player's per-game rate in one category.

    Per game PLAYED, not per week of the season: a player who missed six
    weeks with an injury is not a worse player for it, and dividing by 17
    would say he was.

    A row where the field is None does not count as a game. That is the
    point of parsing blanks to None -- a receiver with no receiving line
    did not catch for zero yards that week, the line is simply absent.
    """
    out: dict[str, dict] = {}
    for r in weekly:
        value = r.get(field)
        if value is None:
            continue
        row = out.setdefault(r["player_id"], {
            "name": r["name"], "team": r["team"],
            "position": r["position"], "total": 0.0, "games": 0})
        row["total"] += value
        row["games"] += 1
        # The most recent club wins, so a traded player is listed where he
        # now plays rather than where he started the year.
        row["team"] = r["team"]
    for row in out.values():
        row["per_game"] = row["total"] / row["games"] if row["games"] else 0.0
    return out


def defence(weekly: list[dict], field: str) -> dict[str, float]:
    """What each team allowed per game in one category.

    Keyed by opponent_team, which is the defence's own abbreviation on an
    offensive player's row. Divided by games rather than by opposing player
    lines: a team that happened to face a four-receiver offence should not
    read as generous because the yardage was split more ways.
    """
    totals: dict[str, float] = {}
    games: dict[str, set] = {}
    for r in weekly:
        value = r.get(field)
        opp = r.get("opponent_team")
        if value is None or not opp:
            continue
        totals[opp] = totals.get(opp, 0.0) + value
        games.setdefault(opp, set()).add(r["game_id"])
    return {t: totals[t] / len(games[t]) for t in totals if games.get(t)}


def league_mean(table: dict, key: str) -> float:
    """The average of one key across a table. Zero for an empty table."""
    values = [v[key] for v in table.values() if v.get(key) is not None]
    return sum(values) / len(values) if values else 0.0


def blend(current: dict[str, dict], prior: dict[str, dict],
          k: int = BLEND_K) -> dict[str, dict]:
    """This season's rate shaded toward last season's, by how much exists.

        w = games_this_season / (games_this_season + k)

    In week one w is zero and the number is entirely last season. Each row
    carries its own weight so the page can say so out loud, because a board
    that hides its weakest moment is worse than one that names it.

    A player with neither line is omitted. A rookie has no rate, and
    inventing one would put a number on the page that nothing supports.
    """
    out: dict[str, dict] = {}
    for pid in set(current) | set(prior):
        cur = current.get(pid)
        old = prior.get(pid)
        cur_games = cur["games"] if cur else 0
        w = cur_games / (cur_games + k) if (cur_games or k) else 0.0
        if cur and old:
            rate = w * cur["per_game"] + (1.0 - w) * old["per_game"]
        elif cur:
            rate = cur["per_game"]
            w = 1.0
        elif old:
            rate = old["per_game"]
            w = 0.0
        else:
            continue
        base = cur or old
        out[pid] = {
            "name": base["name"], "team": base["team"],
            "position": base["position"], "per_game": rate, "weight": round(w, 3),
            "games": cur_games, "prior_games": old["games"] if old else 0,
        }
    return out
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/nfl_data.py
```

Expected: `nfl_data self-test: the parsers hold`

- [ ] **Step 5: Commit**

```bash
git add craftypicks/scripts/nfl_data.py
git commit -m "feat: NFL rates, team defence, and the cold start blend

Rates are per game played, not per week: a player who missed six weeks is
not worse for it. Defence is per game the defence played, not per opposing
line, or facing a four-receiver offence would read as being good at
stopping people.

In week one the blend weight is zero and the number is entirely last
season. Every row carries its weight so the page can admit that."
```

---

## Task 3: The yardage boards

**Files:**
- Create: `craftypicks/scripts/nfl_yards.py`

**Interfaces:**
- Consumes: `nfl_data.player_rates`, `defence`, `league_mean`, `blend`, `parse_weekly`, `parse_schedule`, `asset_urls`, `fetch_csv_gz`, `fetch_csv` (Tasks 1–2); `projection.merge`, `error_summary`, `game_over`
- Produces:
  - `CATEGORIES: dict[str, dict]`
  - `project(rate: float, opp_allowed: float, league: float) -> float`
  - `build(season: int, category: str, week: int | None = None) -> list[dict]`
  - `grade(history: list[dict], weekly: list[dict], category: str) -> int`
  - `summary(history: list[dict]) -> dict`
  - Row shape: `{"player_id","name","team","opponent","position","projection","baseline","per_game","weight","opp_allowed","league_allowed","def_factor","week","commence_time","game_id","actual"}`

- [ ] **Step 1: Write the failing test**

Create `craftypicks/scripts/nfl_yards.py` containing only this:

```python
def _self_test() -> None:
    # An average defence leaves the player's own rate untouched.
    assert project(80.0, 100.0, 100.0) == 80.0

    # A defence allowing 20% more than the league lifts him 20%.
    assert abs(project(80.0, 120.0, 100.0) - 96.0) < 1e-9

    # A league mean of zero cannot divide, and must not raise. With nothing
    # to compare against, the player's own rate is the honest answer.
    assert project(80.0, 120.0, 0.0) == 80.0

    # A defence that has allowed nothing yet is not infinitely good; with
    # no evidence the adjustment is neutral rather than zeroing him out.
    assert project(80.0, 0.0, 100.0) == 80.0

    # Three categories, each naming the column it reads and the one that
    # decides who is worth listing.
    assert set(CATEGORIES) == {"passing", "rushing", "receiving"}
    assert CATEGORIES["passing"]["field"] == "passing_yards"
    assert CATEGORIES["rushing"]["field"] == "rushing_yards"
    assert CATEGORIES["receiving"]["field"] == "receiving_yards"
    assert CATEGORIES["rushing"]["volume"] == "carries"
    assert CATEGORIES["receiving"]["volume"] == "targets"

    # Grading matches on the player and the game, and records the signed
    # error. A game with no line yet stays ungraded.
    hist = [{"player_id": "p1", "game_id": "g9", "projection": 80.0,
             "actual": None},
            {"player_id": "p2", "game_id": "g9", "projection": 60.0,
             "actual": None}]
    weekly = [{"player_id": "p1", "game_id": "g9", "rushing_yards": 95.0}]
    assert grade(hist, weekly, "rushing") == 1
    assert hist[0]["actual"] == 95.0
    assert hist[1]["actual"] is None, "no line means no verdict"
    assert grade(hist, weekly, "rushing") == 0, "graded once"

    s = summary(hist)
    assert s["graded"] == 1
    assert s["mae"] == 15.0, s

    print("nfl_yards self-test: the model holds and grades itself")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd craftypicks && python3 scripts/nfl_yards.py
```

Expected: `NameError: name 'project' is not defined`

- [ ] **Step 3: Write the model**

Insert above `_self_test`:

```python
"""Projected passing, rushing and receiving yards, and how wrong they were.

One model, three categories. The number is the player's own per-game rate,
blended between this season and last, multiplied by how much the defence he
faces allows relative to the league:

    projection = rate * (opponent_allowed_per_game / league_allowed_per_game)

There is no book line beside it, and that is deliberate -- a posted line is
what makes the pitcher board cost money. What replaces it is the baseline:
the same player's rate with NO opponent adjustment, stored on every row.
If the adjusted number cannot beat that, the adjustment is decoration, and
the page is built to reveal that rather than hide it.

The defensive term is not regressed in this first version. With no line to
disagree with, an unregressed number is easier to read the grading of, and
the grading is what will say whether regression is needed.
"""
from __future__ import annotations

import nfl_data
import projection

# Per category: the yardage column, the column that decides who is worth
# listing, and how many names per team the board shows.
CATEGORIES = {
    "passing":   {"field": "passing_yards",   "volume": "attempts",
                  "td_field": "passing_tds",   "per_team": 1,
                  "label": "Passing yards"},
    "rushing":   {"field": "rushing_yards",   "volume": "carries",
                  "td_field": "rushing_tds",   "per_team": 2,
                  "label": "Rushing yards"},
    "receiving": {"field": "receiving_yards", "volume": "targets",
                  "td_field": "receiving_tds", "per_team": 3,
                  "label": "Receiving yards"},
}

# Below this a season line is a sample, not a rate.
MIN_GAMES = 4


def project(rate: float, opp_allowed: float, league: float) -> float:
    """A player's rate, adjusted for the defence he faces.

    Returns the unadjusted rate when there is nothing to compare against.
    A defence with no record is not a perfect defence, and zeroing a player
    out on the strength of no evidence would be the worst kind of wrong --
    confident and unfounded.
    """
    if league <= 0 or opp_allowed <= 0:
        return rate
    return rate * (opp_allowed / league)


def grade(history: list[dict], weekly: list[dict], category: str) -> int:
    """Record what each projected player actually did.

    Matched on the player and the game, so a player projected twice in a
    season is graded against the right week. A game with no line in the
    feed yet stays ungraded rather than being recorded as zero.
    """
    field = CATEGORIES[category]["field"]
    actuals = {}
    for r in weekly:
        value = r.get(field)
        if value is None:
            continue
        actuals[(r.get("player_id"), r.get("game_id"))] = value
    graded = 0
    for row in history:
        if row.get("actual") is not None:
            continue
        key = (row.get("player_id"), row.get("game_id"))
        if key not in actuals:
            continue
        row["actual"] = actuals[key]
        graded += 1
    return graded


def summary(history: list[dict]) -> dict:
    """How wrong the projections were, against the unadjusted baseline."""
    return projection.error_summary(
        history, actual_key="actual", projection_key="projection")
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/nfl_yards.py
```

Expected: `nfl_yards self-test: the model holds and grades itself`

- [ ] **Step 5: Commit**

```bash
git add craftypicks/scripts/nfl_yards.py
git commit -m "feat: the NFL yardage model

Rate times how much the defence allows relative to the league. Every row
also stores the unadjusted baseline, so the grading can say whether the
adjustment earns its place rather than assuming it does.

A defence with no record is treated as neutral, not as perfect. Zeroing a
player out on no evidence is the worst kind of wrong: confident and
unfounded."
```

---

## Task 4: `build` for the yardage boards

**Files:**
- Modify: `craftypicks/scripts/nfl_yards.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3
- Produces: `season_weekly(season) -> list[dict]`, `schedule(season) -> list[dict]`, `build(season, category, week=None) -> list[dict]`

- [ ] **Step 1: Write the failing test**

Add to `_self_test()` in `scripts/nfl_yards.py`, before the final `print`:

```python
    # build(), with every download stubbed. This is the only way it can be
    # tested in an environment with no network.
    real_weekly, real_sched = season_weekly, schedule
    try:
        globals()["season_weekly"] = lambda yr: (
            [] if yr == 2026 else [
                {"player_id": "qb1", "name": "Home Passer", "team": "SEA",
                 "position": "QB", "opponent_team": "NE", "season": 2025,
                 "week": w, "game_id": f"a{w}", "passing_yards": 300.0,
                 "attempts": 35.0, "passing_tds": 2.0}
                for w in range(1, 9)
            ] + [
                {"player_id": "qb2", "name": "Away Passer", "team": "NE",
                 "position": "QB", "opponent_team": "SEA", "season": 2025,
                 "week": w, "game_id": f"b{w}", "passing_yards": 200.0,
                 "attempts": 30.0, "passing_tds": 1.0}
                for w in range(1, 9)
            ])
        globals()["schedule"] = lambda yr: [{
            "game_id": "2026_01_NE_SEA", "week": 1, "gameday": "2026-09-09",
            "commence_time": "2026-09-09T20:15:00+00:00",
            "away_team": "NE", "home_team": "SEA",
            "home_qb_id": "qb1", "home_qb_name": "Home Passer",
            "away_qb_id": "qb2", "away_qb_name": "Away Passer",
            "roof": "outdoors", "stadium": "Lumen Field"}]
        rows = build(2026, "passing", week=1)
    finally:
        globals()["season_weekly"] = real_weekly
        globals()["schedule"] = real_sched

    assert len(rows) == 2, f"one passer a side: {rows}"
    by_id = {r["player_id"]: r for r in rows}
    home = by_id["qb1"]
    assert home["team"] == "SEA" and home["opponent"] == "NE"
    assert home["commence_time"] == "2026-09-09T20:15:00+00:00"
    assert home["actual"] is None and home["week"] == 1
    assert home["game_id"] == "2026_01_NE_SEA"
    # No 2026 file exists, so the weight must be exactly zero and the
    # baseline must be last season's raw rate.
    assert home["weight"] == 0.0, home
    assert home["baseline"] == 300.0, home
    # SEA's defence allowed 200/game, NE's allowed 300/game, league mean 250.
    # Home passer faces NE: 300 * (300/250) = 360.
    assert abs(home["projection"] - 360.0) < 1e-6, home

    # An empty schedule is a quiet board, not a traceback.
    try:
        globals()["schedule"] = lambda yr: []
        assert build(2026, "passing") == []
    finally:
        globals()["schedule"] = real_sched
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd craftypicks && python3 scripts/nfl_yards.py
```

Expected: `NameError: name 'season_weekly' is not defined`

- [ ] **Step 3: Write the fetchers and `build`**

Insert above `_self_test`:

```python
def season_weekly(season: int) -> list[dict]:
    """One season of per-player weekly lines, or an empty list.

    An empty list is the correct answer for a season that has not started:
    stats_player_week_2026.csv.gz does not exist until the first week is
    played, and that is what makes the blend weight zero rather than an
    error.
    """
    assets = nfl_data.asset_urls()
    url = assets.get(f"stats_player_week_{season}.csv.gz")
    if not url:
        return []
    return nfl_data.parse_weekly(nfl_data.fetch_csv_gz(url) or [])


def schedule(season: int) -> list[dict]:
    assets = nfl_data.asset_urls()
    url = assets.get("games.csv")
    if not url:
        return []
    return nfl_data.parse_schedule(nfl_data.fetch_csv(url) or [], season)


def _next_week(games: list[dict]) -> int | None:
    """The earliest week that has not finished yet."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    upcoming = [g for g in games
                if not projection.game_over(g, now)]
    return min((g["week"] for g in upcoming), default=None)


def build(season: int, category: str, week: int | None = None) -> list[dict]:
    """One rated row per player worth listing in the coming week's games.

    Returns an empty list rather than raising whenever anything it needs is
    missing. An empty board says nothing; a traceback stops the run.
    """
    if category not in CATEGORIES:
        return []
    spec = CATEGORIES[category]
    games = schedule(season)
    if not games:
        return []
    if week is None:
        week = _next_week(games)
        if week is None:
            return []
    games = [g for g in games if g["week"] == week]
    if not games:
        return []

    prior_weekly = season_weekly(season - 1)
    cur_weekly = season_weekly(season)
    if not prior_weekly and not cur_weekly:
        return []

    field, volume = spec["field"], spec["volume"]
    rates = nfl_data.blend(nfl_data.player_rates(cur_weekly, field),
                           nfl_data.player_rates(prior_weekly, field))
    vols = nfl_data.blend(nfl_data.player_rates(cur_weekly, volume),
                          nfl_data.player_rates(prior_weekly, volume))
    allowed = nfl_data.defence(cur_weekly or prior_weekly, field)
    league = (sum(allowed.values()) / len(allowed)) if allowed else 0.0

    by_team: dict[str, list] = {}
    for pid, row in rates.items():
        if (row["games"] + row["prior_games"]) < MIN_GAMES:
            continue
        by_team.setdefault(row["team"], []).append((pid, row))

    rows = []
    for game in games:
        for side, opp in (("home", "away"), ("away", "home")):
            team = game[f"{side}_team"]
            other = game[f"{opp}_team"]
            opp_allowed = allowed.get(other, 0.0)

            if category == "passing":
                # The schedule names the starter, which beats any guess.
                pid = game[f"{side}_qb_id"]
                picked = [(pid, rates[pid])] if pid in rates else []
            else:
                picked = sorted(
                    by_team.get(team, []),
                    key=lambda kv: vols.get(kv[0], {}).get("per_game", 0.0),
                    reverse=True)[:spec["per_team"]]

            for pid, row in picked:
                rows.append({
                    "player_id": pid,
                    "name": row["name"],
                    "team": team,
                    "opponent": other,
                    "position": row["position"],
                    "per_game": round(row["per_game"], 1),
                    "baseline": round(row["per_game"], 1),
                    "projection": round(
                        project(row["per_game"], opp_allowed, league), 1),
                    "weight": row["weight"],
                    "opp_allowed": round(opp_allowed, 1),
                    "league_allowed": round(league, 1),
                    "def_factor": round(opp_allowed / league, 3) if league else 1.0,
                    "week": game["week"],
                    "game_id": game["game_id"],
                    "commence_time": game["commence_time"],
                    "actual": None,
                })
    rows.sort(key=lambda r: (r["commence_time"], -r["projection"]))
    return rows
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/nfl_yards.py
```

Expected: `nfl_yards self-test: the model holds and grades itself`

- [ ] **Step 5: Commit**

```bash
git add craftypicks/scripts/nfl_yards.py
git commit -m "feat: build the NFL yardage boards

The starting quarterback comes from the schedule, which names him. Runners
and receivers are ranked by blended volume -- carries and targets -- rather
than by a depth chart whose newest snapshot is from March."
```

---

## Task 5: The touchdown board

**Files:**
- Create: `craftypicks/scripts/nfl_td.py`

**Interfaces:**
- Consumes: `nfl_data.*` (Tasks 1–2), `nfl_yards.season_weekly`, `nfl_yards.schedule`, `projection.*`
- Produces: `td_chance(rate, opp_allowed, league) -> float`, `build(season, week=None) -> list[dict]`, `grade(history, weekly) -> int`, `summary(history) -> dict`, `TD_EDGES`

- [ ] **Step 1: Write the failing test**

Create `craftypicks/scripts/nfl_td.py` containing only this:

```python
def _self_test() -> None:
    import math

    # Poisson, because a player has no fixed number of chances to score.
    # A rate of 0.5 against an average defence: 1 - e^-0.5.
    assert abs(td_chance(0.5, 100.0, 100.0) - (1 - math.exp(-0.5))) < 1e-12

    # A defence allowing double the league doubles the rate, not the chance.
    doubled = td_chance(0.5, 200.0, 100.0)
    assert abs(doubled - (1 - math.exp(-1.0))) < 1e-12
    assert doubled < 2 * td_chance(0.5, 100.0, 100.0), \
        "a probability must not scale linearly"

    # Never certain, never negative, monotone in the rate.
    assert 0.0 < td_chance(0.01, 100.0, 100.0) < td_chance(2.0, 100.0, 100.0) < 1.0

    # Nothing to compare against leaves the rate alone.
    assert abs(td_chance(0.5, 100.0, 0.0) - (1 - math.exp(-0.5))) < 1e-12
    assert abs(td_chance(0.5, 0.0, 100.0) - (1 - math.exp(-0.5))) < 1e-12

    # A player who has never scored gets zero, not a floor invented for him.
    assert td_chance(0.0, 100.0, 100.0) == 0.0

    # Buckets are touchdown-scale. Most anytime chances sit under 40%, so
    # the home-run board's edges would put nearly every row in one bucket
    # and the calibration table would say nothing.
    assert TD_EDGES[0][0] == 0.0
    assert TD_EDGES[-1][1] > 1.0, "the top bucket must include a chance of 1"
    for (lo1, hi1), (lo2, hi2) in zip(TD_EDGES, TD_EDGES[1:]):
        assert hi1 == lo2, "buckets must be contiguous"

    # Grading: rushing and receiving touchdowns both count, and passing
    # ones do not -- a quarterback who throws three has not scored.
    hist = [{"player_id": "p1", "game_id": "g1", "scored": None,
             "chance": 0.4},
            {"player_id": "p2", "game_id": "g1", "scored": None,
             "chance": 0.3},
            {"player_id": "p3", "game_id": "g1", "scored": None,
             "chance": 0.2}]
    weekly = [
        {"player_id": "p1", "game_id": "g1", "rushing_tds": 1.0,
         "receiving_tds": 0.0, "passing_tds": 0.0},
        {"player_id": "p2", "game_id": "g1", "rushing_tds": 0.0,
         "receiving_tds": 0.0, "passing_tds": 3.0},
    ]
    assert grade(hist, weekly) == 2
    assert hist[0]["scored"] is True
    assert hist[1]["scored"] is False, "throwing three is not scoring"
    assert hist[2]["scored"] is None, "no line, no verdict"
    assert grade(hist, weekly) == 0

    s = summary(hist)
    assert s["graded"] == 2

    print("nfl_td self-test: the model holds and grades itself")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd craftypicks && python3 scripts/nfl_td.py
```

Expected: `NameError: name 'td_chance' is not defined`

- [ ] **Step 3: Write the model**

Insert above `_self_test`:

```python
"""Each player's chance of scoring a touchdown, and whether he did.

Poisson rather than the odds ratio the baseball boards use, and for a
concrete reason: a batter has a countable number of plate appearances, so a
per-chance probability compounds over them. A running back has no fixed
number of opportunities to score. What he has is a rate per game, and the
question "did at least one happen" is what Poisson answers:

    lambda = touchdowns_per_game * (opponent_allowed / league_allowed)
    chance = 1 - exp(-lambda)

Passing touchdowns are deliberately excluded from the verdict. A
quarterback who throws three has not scored one, and the market this board
mirrors -- anytime touchdown scorer -- agrees.
"""
from __future__ import annotations

import math

import nfl_data
import nfl_yards
import projection

# Touchdown-scale buckets. Most anytime chances sit under 40%, so the
# home-run board's edges would drop nearly every row into one bucket and
# the calibration table would have nothing to say.
TD_EDGES = ((0.0, 0.10), (0.10, 0.20), (0.20, 0.30),
            (0.30, 0.45), (0.45, 1.01))

MIN_GAMES = 4
PER_TEAM = 4

# The two that count as scoring, and the one that does not.
SCORING = ("rushing_tds", "receiving_tds")


def td_chance(rate: float, opp_allowed: float, league: float) -> float:
    """Probability of at least one touchdown, Poisson.

    Returns the unadjusted chance when there is nothing to compare
    against. A defence with no record is not a perfect defence.
    """
    if rate <= 0:
        return 0.0
    lam = rate
    if league > 0 and opp_allowed > 0:
        lam = rate * (opp_allowed / league)
    return 1.0 - math.exp(-lam)


def grade(history: list[dict], weekly: list[dict]) -> int:
    """Whether each projected player scored. Passing touchdowns do not count."""
    scored: dict = {}
    for r in weekly:
        values = [r.get(f) for f in SCORING]
        if all(v is None for v in values):
            continue
        total = sum(v for v in values if v is not None)
        scored[(r.get("player_id"), r.get("game_id"))] = total > 0
    graded = 0
    for row in history:
        if row.get("scored") is not None:
            continue
        key = (row.get("player_id"), row.get("game_id"))
        if key not in scored:
            continue
        row["scored"] = bool(scored[key])
        graded += 1
    return graded


def summary(history: list[dict]) -> dict:
    """Calibration: what was promised against what happened."""
    return projection.calibration(history, verdict_key="scored",
                                  edges=TD_EDGES)
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/nfl_td.py
```

Expected: `nfl_td self-test: the model holds and grades itself`

- [ ] **Step 5: Add `build` and its test**

Add to `_self_test()`, before the final `print`:

```python
    # build(), with the downloads stubbed.
    real_weekly, real_sched = nfl_yards.season_weekly, nfl_yards.schedule
    try:
        nfl_yards.season_weekly = lambda yr: ([] if yr == 2026 else [
            {"player_id": "rb1", "name": "A Runner", "team": "SEA",
             "position": "RB", "opponent_team": "NE", "season": 2025,
             "week": w, "game_id": f"a{w}", "rushing_tds": 1.0,
             "receiving_tds": 0.0, "carries": 18.0, "targets": 2.0}
            for w in range(1, 9)])
        nfl_yards.schedule = lambda yr: [{
            "game_id": "2026_01_NE_SEA", "week": 1, "gameday": "2026-09-09",
            "commence_time": "2026-09-09T20:15:00+00:00",
            "away_team": "NE", "home_team": "SEA",
            "home_qb_id": "", "home_qb_name": "", "away_qb_id": "",
            "away_qb_name": "", "roof": "outdoors", "stadium": "Lumen Field"}]
        rows = build(2026, week=1)
    finally:
        nfl_yards.season_weekly = real_weekly
        nfl_yards.schedule = real_sched

    assert len(rows) == 1, rows
    r = rows[0]
    assert r["player_id"] == "rb1" and r["team"] == "SEA"
    assert r["opponent"] == "NE"
    assert r["scored"] is None
    assert r["weight"] == 0.0, "no 2026 file yet"
    assert 0.0 < r["chance"] < 1.0
    assert r["commence_time"] == "2026-09-09T20:15:00+00:00"
```

Then insert above `_self_test`:

```python
def build(season: int, week: int | None = None) -> list[dict]:
    """One rated row per likely scorer in the coming week's games."""
    games = nfl_yards.schedule(season)
    if not games:
        return []
    if week is None:
        week = nfl_yards._next_week(games)
        if week is None:
            return []
    games = [g for g in games if g["week"] == week]
    if not games:
        return []

    all_rows = nfl_yards.season_weekly(season) + \
        nfl_yards.season_weekly(season - 1)
    if not all_rows:
        return []

    # Rushing and receiving scores summed into one rate per player: the
    # market does not care which way he got there. Done once, over both
    # seasons, and split apart afterwards by the season already on each row.
    combined = [
        dict(r, any_td=sum(v for v in (r.get(f) for f in SCORING)
                           if v is not None))
        for r in all_rows]
    cur_rows = [r for r in combined if r["season"] == season]
    old_rows = [r for r in combined if r["season"] == season - 1]
    rates = nfl_data.blend(nfl_data.player_rates(cur_rows, "any_td"),
                           nfl_data.player_rates(old_rows, "any_td"))
    allowed = nfl_data.defence(combined, "any_td")
    league = (sum(allowed.values()) / len(allowed)) if allowed else 0.0

    by_team: dict[str, list] = {}
    for pid, row in rates.items():
        if (row["games"] + row["prior_games"]) < MIN_GAMES:
            continue
        by_team.setdefault(row["team"], []).append((pid, row))

    rows = []
    for game in games:
        for side, opp in (("home", "away"), ("away", "home")):
            team = game[f"{side}_team"]
            other = game[f"{opp}_team"]
            opp_allowed = allowed.get(other, 0.0)
            picked = sorted(by_team.get(team, []),
                            key=lambda kv: kv[1]["per_game"],
                            reverse=True)[:PER_TEAM]
            for pid, row in picked:
                rows.append({
                    "player_id": pid,
                    "name": row["name"],
                    "team": team,
                    "opponent": other,
                    "position": row["position"],
                    "per_game": round(row["per_game"], 3),
                    "chance": td_chance(row["per_game"], opp_allowed, league),
                    "weight": row["weight"],
                    "opp_allowed": round(opp_allowed, 2),
                    "league_allowed": round(league, 2),
                    "week": game["week"],
                    "game_id": game["game_id"],
                    "commence_time": game["commence_time"],
                    "scored": None,
                })
    rows.sort(key=lambda r: (r["commence_time"], -r["chance"]))
    return rows
```

- [ ] **Step 6: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/nfl_td.py && python3 scripts/nfl_yards.py && python3 scripts/nfl_data.py
```

Expected: all three self-tests print their success lines.

- [ ] **Step 7: Commit**

```bash
git add craftypicks/scripts/nfl_td.py
git commit -m "feat: the anytime touchdown model

Poisson, not the odds ratio the baseball boards use: a batter has a
countable number of plate appearances, a running back has no fixed number
of chances to score.

Passing touchdowns do not count toward the verdict. A quarterback who
throws three has not scored one, and the market agrees."
```

---

## Task 6: Four pages, and the run that fills them

**Files:**
- Create: `craftypicks/_src/nfl_passing.body.html`, `nfl_rushing.body.html`, `nfl_receiving.body.html`, `nfl_td.body.html`
- Modify: `craftypicks/_src/build.py`, `_src/render.py`, `_src/i18n.py`, `scripts/run_boards.py`

**Interfaces:**
- Consumes: `nfl_yards.build/grade/summary`, `nfl_td.build/grade/summary`, `projection.merge`, `projection.repair_premature`
- Produces: `data/nfl_passing.json`, `nfl_rushing.json`, `nfl_receiving.json`, `nfl_td.json`, plus a `*_ratings.json` store for each; and the four pages

- [ ] **Step 1: Add the nav labels and copy**

In `_src/i18n.py`, add:

```python
    "nav_pass":     {"en": "Passing", "es": "Pases"},
    "nav_rush":     {"en": "Rushing", "es": "Carreras"},
    "nav_recv":     {"en": "Receiving", "es": "Recepciones"},
    "nav_nfltd":    {"en": "Touchdowns", "es": "Touchdowns"},
    "nfl_empty":    {"en": "No games scheduled yet. This board fills in "
                           "once the week's fixtures are posted.",
                     "es": "Aún no hay partidos. Esta pizarra se llena "
                           "cuando se publiquen los encuentros."},
    "nfl_lastyear": {"en": "Running entirely on last season. Every "
                           "projection here is {n} game(s) of this season "
                           "old.",
                     "es": "Basado por completo en la temporada pasada."},
    "nfl_vs":       {"en": "vs {opp} — allows {allowed} a game, league "
                           "average {league}",
                     "es": "vs {opp} — permite {allowed} por partido"},
    "nfl_ungraded": {"en": "Not graded yet. Every projection on this board "
                           "is settled once its game has finished.",
                     "es": "Aún sin calificar."},
```

- [ ] **Step 2: Register the four pages**

In `_src/build.py`, in `PAGES`:

```python
    "nfl/passing.html":   Page("nfl/passing.html",   "nflpass", "nfl", "nfl"),
    "nfl/rushing.html":   Page("nfl/rushing.html",   "nflrush", "nfl", "nfl"),
    "nfl/receiving.html": Page("nfl/receiving.html", "nflrecv", "nfl", "nfl"),
    "nfl/td.html":        Page("nfl/td.html",        "nfltd",   "nfl", "nfl"),
```

In `VIEWS`, the NFL list becomes board, form, then the four. Note the
existing comprehension only adds prop tabs for MLB; extend it so NFL gets
its own four rather than making the MLB branch conditional in two ways:

```python
VIEWS: dict[str, list[tuple[str, str]]] = {
    short: ([(f"{short}/index.html", "nav_board"),
             (f"{short}/form.html", "nav_form")]
            + _EXTRA_VIEWS.get(short, []))
    for short in leagues.ORDER
}
```

with, above it:

```python
# The extra views each league has beyond its board and its form table.
# Keyed rather than branched, because the branch version already grew a
# condition that read "has_props AND short == mlb" and would have grown
# another for every sport added.
_EXTRA_VIEWS: dict[str, list[tuple[str, str]]] = {
    "mlb": [("pitchers.html", "nav_pitchers"),
            ("batters.html", "nav_batters"),
            ("hits.html", "nav_hits"),
            ("homers.html", "nav_homers")],
    "nfl": [("nfl/passing.html", "nav_pass"),
            ("nfl/rushing.html", "nav_rush"),
            ("nfl/receiving.html", "nav_recv"),
            ("nfl/td.html", "nav_nfltd")],
}
```

Add the four titles to the titles map, following the `"hits.html"` entry's shape, with English and Spanish both reading e.g. `f"Passing yards — {config.SITE_NAME}"`.

The build's own invariants already assert that every page in a league's
`VIEWS` declares that league. These four declare `"nfl"`, so they pass; if
one is mistyped the build fails rather than shipping an empty sub-nav.

- [ ] **Step 3: Write the renderers**

In `_src/render.py`, add:

```python
def yard_cards(rows: list[dict], unit: str = "yds") -> str:
    """Projected yardage, grouped by game."""
    if not rows:
        return f'<div class="empty-board">{_("nfl_empty")}</div>'
    games: dict = {}
    for r in rows:
        games.setdefault((r.get("commence_time"), r.get("game_id")), []).append(r)

    out = []
    for (when, _gid), group in games.items():
        head = f"{esc(group[0].get('team',''))} &middot; {esc(game_time(when))}"
        opp = esc(group[0].get("opponent", ""))
        allowed = f"{group[0].get('opp_allowed', 0):.0f}"
        league = f"{group[0].get('league_allowed', 0):.0f}"
        men = "".join(f"""
          <div class="bat">
            <div class="bat-n">{esc(p.get('name',''))}
              <span class="pos">{esc(p.get('position',''))}</span></div>
            <div class="bat-c"><b>{p.get('projection', 0):.0f}</b>
              <span class="unit">{esc(unit)}</span></div>
            <div class="bat-w">{p.get('baseline', 0):.0f} {esc(unit)}
              unadjusted</div>
          </div>""" for p in group)
        out.append(f"""
        <article class="pb-card bat-card">
          <div class="pb-top"><span>{head}</span></div>
          <div class="pb-body">
            <div class="bat-vs">{_("nfl_vs", opp=opp, allowed=allowed,
                                   league=league)}</div>
            {men}
          </div>
        </article>""")
    return '<div class="pb-grid">' + "".join(out) + "</div>"


def td_cards(rows: list[dict]) -> str:
    """Anytime touchdown chances, grouped by game."""
    if not rows:
        return f'<div class="empty-board">{_("nfl_empty")}</div>'
    games: dict = {}
    for r in rows:
        games.setdefault((r.get("commence_time"), r.get("game_id")), []).append(r)
    out = []
    for (when, _gid), group in games.items():
        head = f"{esc(group[0].get('team',''))} &middot; {esc(game_time(when))}"
        opp = esc(group[0].get("opponent", ""))
        allowed = f"{group[0].get('opp_allowed', 0):.2f}"
        league = f"{group[0].get('league_allowed', 0):.2f}"
        men = "".join(f"""
          <div class="bat">
            <div class="bat-n">{esc(p.get('name',''))}
              <span class="pos">{esc(p.get('position',''))}</span></div>
            <div class="bat-c"><b>{p.get('chance', 0) * 100:.1f}%</b></div>
          </div>""" for p in group)
        out.append(f"""
        <article class="pb-card bat-card">
          <div class="pb-top"><span>{head}</span></div>
          <div class="pb-body">
            <div class="bat-vs">{_("nfl_vs", opp=opp, allowed=allowed,
                                   league=league)}</div>
            {men}
          </div>
        </article>""")
    return '<div class="pb-grid">' + "".join(out) + "</div>"


def yard_accuracy(summary: dict) -> str:
    """Mean error against the unadjusted baseline, like for like."""
    n = (summary or {}).get("graded") or 0
    if not n:
        return f'<p class="pnl-note">{_("nfl_ungraded")}</p>'
    mae = summary.get("mae")
    base = summary.get("baseline_mae")
    comp = summary.get("mae_on_baseline_rows")
    bits = [f"<strong>{mae}</strong> yards off, on average, over {n} projections."]
    if base is not None and comp is not None:
        verdict = ("the opponent adjustment is earning its place"
                   if comp < base else
                   "the opponent adjustment is not earning its place")
        bits.append(f"On the {summary.get('baseline_n')} where a baseline "
                    f"exists: <strong>{comp}</strong> adjusted against "
                    f"<strong>{base}</strong> unadjusted &mdash; {verdict}.")
    return '<p class="pnl-note">' + " ".join(bits) + "</p>"
```

`yard_accuracy` compares `mae_on_baseline_rows` against `baseline_mae`, never against `mae`. Those two are computed over different row sets, and comparing them was a defect found in review on the MLB side.

- [ ] **Step 4: Write the four body files**

Create `craftypicks/_src/nfl_passing.body.html`:

```html
<div class="wrap">
  <p class="kicker">{{DATE_LABEL}} &middot; {{NFL_COUNT}}</p>
  <h1>Passing yards</h1>
  <p class="lede">Each starting quarterback's projected passing yards, and
  the number behind it: his own per-game rate, adjusted for how much the
  defence he faces gives up relative to the league.</p>

  <p>There is no book line beside it. This board costs nothing to produce
  &mdash; it reads a public file of weekly stats and the published
  schedule. What sits where a line would be is the unadjusted number: the
  same quarterback with no opponent adjustment at all. If the adjusted
  figure cannot beat that one over time, the adjustment is decoration, and
  the accuracy note below will say so.</p>

  {{NFL_NOTE}}
  {{NFL_CARDS}}

  <h2>How it has done</h2>
  {{NFL_ACCURACY}}
</div>
```

Create the rushing, receiving and touchdown bodies with the same structure.
Rushing's lede: "The backs most likely to carry the ball, and the yards
each is projected for." Receiving's: "The most-targeted receivers in each
game, and their projected yards." Touchdowns' lede: "Each player's chance
of scoring at least once, from how often he scores and how often the
defence he faces allows it," and its "How it has done" section says the
test is calibration, not a record: a group called 25% should score about
25% of the time.

- [ ] **Step 5: Wire the tokens**

In `_src/build.py`, beside the `hits.html` block, add a loop over the four
NFL pages: each loads its `data/<name>.json`, substitutes `{{NFL_CARDS}}`
with `R.yard_cards(...)` (or `R.td_cards(...)` for the touchdown page),
`{{NFL_ACCURACY}}` with `R.yard_accuracy(...)` (or `R.batter_calibration(...)`
for touchdowns, whose summary is a calibration), `{{DATE_LABEL}}` with the
document's `date_label`, `{{NFL_COUNT}}` with a count phrased
`"N players rated"`, and `{{NFL_NOTE}}` with the cold-start warning when
every row has `weight == 0` — using the `nfl_lastyear` key — and an empty
string otherwise.

- [ ] **Step 6: Build and check the guards**

```bash
cd craftypicks && python3 _src/build.py && python3 scripts/palette.py \
  && for f in nfl/passing nfl/rushing nfl/receiving nfl/td; do
       test -s "$f.html" && echo "$f.html built"; done
```

Expected: the build runs, invariants pass, palette reports no failures, and
all four pages exist. If palette rejects a selector, change the colour to
`--muted` rather than exempting the rule.

- [ ] **Step 7: Build the boards in the boards run**

In `scripts/run_boards.py`, add `import nfl_yards`, `import nfl_td`, and a
block AFTER the MLB blocks, at the same indentation — not nested inside any
`if` belonging to another board:

```python
    # ---------------------------------------------------------- NFL
    # Guarded as a whole: the NFL feed is a third party, and a bad day
    # there must not cost the MLB boards their run.
    try:
        nfl_weekly = nfl_yards.season_weekly(NFL_SEASON)
        for name, cat in (("nfl_passing", "passing"),
                          ("nfl_rushing", "rushing"),
                          ("nfl_receiving", "receiving")):
            store = DATA / f"{name}_ratings.json"
            hist = load_json(store, {"rows": []})["rows"]
            fixed = projection.repair_premature(hist, verdict_key="actual")
            if fixed:
                print(f"-- {name}: reset {fixed} premature verdict(s)")
            settled = nfl_yards.grade(hist, nfl_weekly, cat)
            rows = nfl_yards.build(NFL_SEASON, cat)
            added = projection.merge(hist, rows, ("player_id", "game_id"))
            save_json(store, {"rows": hist})
            if rows:
                save_json(DATA / f"{name}.json", {
                    "date": today, "date_label": label, "rows": rows,
                    "summary": nfl_yards.summary(hist)})
                print(f"-- {name}: {len(rows)} rated, {added} new, "
                      f"{settled} graded")

        store = DATA / "nfl_td_ratings.json"
        hist = load_json(store, {"rows": []})["rows"]
        fixed = projection.repair_premature(hist, verdict_key="scored")
        if fixed:
            print(f"-- nfl_td: reset {fixed} premature verdict(s)")
        settled = nfl_td.grade(hist, nfl_weekly)
        rows = nfl_td.build(NFL_SEASON)
        added = projection.merge(hist, rows, ("player_id", "game_id"))
        save_json(store, {"rows": hist})
        if rows:
            save_json(DATA / "nfl_td.json", {
                "date": today, "date_label": label, "rows": rows,
                "summary": nfl_td.summary(hist)})
            print(f"-- nfl_td: {len(rows)} rated, {added} new, "
                  f"{settled} graded")
    except Exception as e:                                   # noqa: BLE001
        print(f"!! NFL boards failed ({type(e).__name__}: {e})",
              file=sys.stderr)
```

Define `NFL_SEASON = 2026` near the top of `run_boards.py`, beside the
existing season constant, with a comment that it is the calendar year the
season starts in.

- [ ] **Step 8: Verify the whole run offline**

```bash
cd craftypicks && python3 - <<'CHECK'
import sys, json, tempfile, pathlib, shutil
sys.path.insert(0, "scripts")
tmp = pathlib.Path(tempfile.mkdtemp()); (tmp / "data").mkdir()
import run_boards as rb, mlb_api, nfl_yards, nfl_td
rb.DATA = tmp / "data"
mlb_api.probable_starters = lambda d: []          # MLB quiet today

WEEK = [{"player_id": "rb1", "name": "A Runner", "team": "SEA",
         "position": "RB", "opponent_team": "NE", "season": 2025,
         "week": w, "game_id": f"a{w}", "rushing_yards": 90.0,
         "carries": 18.0, "targets": 2.0, "receiving_yards": 15.0,
         "rushing_tds": 1.0, "receiving_tds": 0.0, "passing_yards": None,
         "attempts": None, "passing_tds": 0.0} for w in range(1, 9)]
nfl_yards.season_weekly = lambda yr: ([] if yr == 2026 else WEEK)
nfl_yards.schedule = lambda yr: [{
    "game_id": "2026_01_NE_SEA", "week": 1, "gameday": "2026-09-09",
    "commence_time": "2026-09-09T20:15:00+00:00",
    "away_team": "NE", "home_team": "SEA", "home_qb_id": "", "home_qb_name": "",
    "away_qb_id": "", "away_qb_name": "", "roof": "outdoors", "stadium": "X"}]
assert rb.main() == 0
d = json.loads((tmp / "data" / "nfl_rushing.json").read_text())
print("rushing rows:", len(d["rows"]), "| first:", d["rows"][0]["name"],
      d["rows"][0]["projection"], "| weight:", d["rows"][0]["weight"])
assert d["rows"], "no NFL rows written"
assert d["rows"][0]["weight"] == 0.0, "week 1 must be entirely last season"
assert rb.main() == 0
h = json.loads((tmp / "data" / "nfl_rushing_ratings.json").read_text())["rows"]
assert len(h) == len(d["rows"]), f"dedupe failed: {len(h)}"
# Nothing may be graded: the game is in the future.
assert all(r["actual"] is None for r in h), "graded before kickoff"
print("OK: written once, deduped, and nothing judged before kickoff")
shutil.rmtree(tmp)
CHECK
```

Expected: rows written, `weight: 0.0`, and `OK: written once, deduped, and nothing judged before kickoff`.

- [ ] **Step 9: Run every self-test and build**

```bash
cd craftypicks && for m in projection nfl_data nfl_yards nfl_td hits batters mlb_api homers; do
  python3 "scripts/$m.py" || exit 1; done \
  && python3 _src/build.py && python3 scripts/palette.py
```

Expected: every self-test prints its success line, the build runs, palette passes.

- [ ] **Step 10: Commit**

```bash
git add craftypicks/_src craftypicks/scripts/run_boards.py
git commit -m "feat: the four NFL boards

Passing, rushing and receiving yards, and anytime touchdown. Free, graded,
and honest about running on last season until this one has games in it.

VIEWS is now a keyed table rather than a branch: the old comprehension
already read 'has_props AND short == mlb' and would have grown a condition
for every sport added."
```

---

## Self-Review

**Spec coverage.** Amendment §1–2 (correct asset, no 2026 file) → Task 1
Step 3 and Task 4's `season_weekly`. §3 (depth charts dropped, QB from
schedule) → Task 4's passing branch. §4 (season opens 2026-09-09) → the
fixture in Task 4. Both traps (blank `player_id`, blanks ≠ zeros) → Task 1's
`parse_weekly` and `num`, each with a test. Cold start → Task 2's `blend`
and the `nfl_lastyear` note in Task 6. Grading → Tasks 3 and 5, gated by
`projection.game_over` through `repair_premature` and verified in Task 6
Step 8.

**Deliberate omissions.** `games.csv`'s `spread_line` and `total_line` are
recorded in the spec as out of scope; nothing here reads them. Depth charts
are fetched by nothing.

**Type consistency.** `nfl_data.blend` returns rows with `per_game`,
`weight`, `games`, `prior_games`, `name`, `team`, `position` — Tasks 4 and 5
read exactly those. `nfl_yards.build` rows carry `projection`, `baseline`,
`actual`; `nfl_td.build` rows carry `chance`, `scored`. The two grade
functions key on `("player_id", "game_id")`, which is also the `merge` key
in Task 6, and the same pair `projection.merge` expects.

**One edge found and fixed before dispatch.** `nfl_td.build` originally
branched on whether both seasons existed before concatenating them, which
was correct but unreadable. Concatenating unconditionally — either list may
be empty — and splitting afterwards on the season already carried by each
row says the same thing in a form a reader can check at a glance.
