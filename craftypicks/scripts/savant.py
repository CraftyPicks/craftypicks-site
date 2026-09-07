#!/usr/bin/env python3
"""Expected wOBA for a starter against tonight's opposing roster.

PA, K% and AVG against a roster already come free from StatsAPI --
mlb_api.vs_roster() computes all three today. xwOBA does not, and cannot:
it is a Statcast quantity, expected wOBA from exit velocity and launch
angle, and StatsAPI carries no Statcast endpoint (research/probe_savant.py,
2026-09-07: statcast_percentile is 404, the player page is 2.7 MB of HTML,
and /people/{id}/stats?stats=statcast is a 400).

What does work is Savant's own search export. One request returns every
pitch a starter has thrown in a season as CSV -- 2,330 rows, 119 columns,
1.59 MB, 3.7s measured -- and it carries `batter`, so the pitcher-vs-batter
split can be computed here rather than asked for.

Three things about that CSV decide the shape of this module.

  * xwOBA is not one column. `estimated_woba_using_speedangle` is filled
    only for tracked batted balls; strikeouts and walks are blank but still
    belong in the denominator. Savant's own definition takes the estimate
    where it exists and the actual `woba_value` where it does not, over
    `woba_denom`. aggregate() does exactly that, so the number printed on
    the card is Savant's number and not something near it.

  * A finished season never changes. It is fetched once and cached forever;
    only the current season is refreshed, and only once a day.

  * A cold cache is expensive. Twenty-one starters back through the Statcast
    era is roughly 330 MB and over ten minutes, against a 30-minute job
    timeout. warm() therefore spends a fixed budget per run -- today's
    seasons first, because they are the only ones that can have changed,
    backfill with what is left -- and the panel prints the span it actually
    has rather than pretending to a depth it has not reached yet.

No key, no rate limit, no paid credits.
"""
from __future__ import annotations

import csv
import io
import json
import pathlib
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import results_store  # noqa: E402  (for _write_atomic)

DATA = HERE.parent / "data" / "savant"

UA = {"User-Agent": "craftypicks/1.0 (+https://craftypicks.org)"}

# Statcast begins in 2015. Nothing earlier exists to ask for.
FIRST_SEASON = 2015

# Season-fetches per run. Twelve is about 45 seconds and 20 MB at the
# measured rate, which is affordable beside a 30-minute timeout even on a
# morning when everything else is slow.
MAX_FETCHES = 12

# Stop walking backwards after this many consecutive seasons with no pitch
# in them. Two rather than one because a pitcher can miss a whole season to
# injury and still have thrown before it.
EMPTY_RUN = 2

# Below this many plate appearances the number is noise dressed as a
# measurement. The panel still shows it; it shows it dimmed.
THIN_PA = 50


def _num(value):
    """A CSV cell as a float, or None. Blank is not zero."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        out = float(text)
    except ValueError:
        return None
    # 'nan' and 'inf' parse as floats and would poison every average they
    # reach. nfl_data.num learned this the same way.
    return out if out == out and abs(out) != float("inf") else None


# --------------------------------------------------------------- the CSV --
def season_url(pitcher_id: int, season: int) -> str:
    return ("https://baseballsavant.mlb.com/statcast_search/csv"
            "?all=true&type=details&player_type=pitcher"
            f"&pitchers_lookup%5B%5D={int(pitcher_id)}"
            f"&game_date_gt={int(season)}-03-01"
            f"&game_date_lt={int(season)}-12-01")


def fetch_season(pitcher_id: int, season: int, timeout: int = 120):
    """One pitcher, one season, as CSV text. None on any failure.

    Deliberately separate from aggregate(): fusing fetch and parse is what
    made pitcher_season untestable offline, and this module can only ever
    be tested offline.
    """
    req = urllib.request.Request(season_url(pitcher_id, season), headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError,
            TimeoutError, OSError) as e:
        print(f"   !! savant {pitcher_id}/{season}: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return None


def aggregate(csv_text: str) -> dict[str, list[float]]:
    """{batter_id: [denominator, xwOBA numerator]} from one season of pitches.

    Savant's xwOBA: the estimate where the radar produced one, the actual
    wOBA weight where it did not. Rows with woba_denom of 0 -- every pitch
    that does not end a plate appearance, plus sacrifice bunts and
    intentional walks -- are not part of either total.
    """
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


# ------------------------------------------------------------- the cache --
def path_for(pitcher_id: int, season: int) -> pathlib.Path:
    """One file per pitcher per season.

    The obvious layout is one file per pitcher, and it is the wrong one. This
    cache is committed to the repository by the daily job, so the unit of
    storage is also the unit of churn: a single per-pitcher file rewrites a
    whole career every morning to record that one more September game
    happened. Split by season, a finished year is written once and never
    touched again, and only the current season's file changes daily.
    """
    return DATA / str(int(pitcher_id)) / f"{int(season)}.json"


def _blank() -> dict:
    return {"seasons": {}, "empty": [], "fetched": {}}


def load(pitcher_id: int) -> dict:
    """Every season cached for this pitcher, reassembled into one document.

    A corrupt season file is moved aside and skipped rather than raising.
    Unlike results_store, nothing here is irreplaceable -- Savant will hand
    the whole thing back on the next run, and losing a day of cache costs
    seconds. Losing the card would cost the morning.
    """
    doc = _blank()
    folder = DATA / str(int(pitcher_id))
    if not folder.is_dir():
        return doc
    for path in sorted(folder.glob("*.json")):
        year = path.stem
        try:
            one = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            try:
                path.replace(path.with_suffix(".json.bad"))
            except OSError:
                pass
            print(f"   !! savant cache {path.name} unreadable; refetching",
                  file=sys.stderr)
            continue
        if one.get("rows"):
            doc["seasons"][year] = one["rows"]
        elif one.get("empty"):
            doc["empty"].append(year)
        if one.get("fetched"):
            doc["fetched"][year] = one["fetched"]
    return doc


def save_season(pitcher_id: int, season: int, rows: dict, empty: bool,
                fetched: str) -> None:
    path = path_for(pitcher_id, season)
    path.parent.mkdir(parents=True, exist_ok=True)
    results_store._write_atomic(
        path, json.dumps({"rows": rows, "empty": empty, "fetched": fetched},
                         separators=(",", ":")))


def _wanted(doc: dict, season: int) -> list[int]:
    """Seasons still worth asking about, most valuable first.

    The current season leads because it is the only one that can have
    changed. Then the newest missing season, then older, stopping once
    EMPTY_RUN consecutive seasons came back with no pitches -- a pitcher who
    debuted in 2023 should not be asked about 2015 every morning forever.
    """
    have = set(doc.get("seasons") or {})
    empty = set(doc.get("empty") or [])
    out = [season]
    run = 0
    for yr in range(season - 1, FIRST_SEASON - 1, -1):
        key = str(yr)
        if key in empty:
            run += 1
            if run >= EMPTY_RUN:
                break
            continue
        run = 0
        if key not in have:
            out.append(yr)
    return out


def warm(pitcher_ids, season: int, today: str, budget: int = MAX_FETCHES,
         fetch=None, verbose: bool = True) -> int:
    """Spend a bounded number of Savant requests on the most valuable gaps.

    Two passes on purpose. The first gives every starter today's season,
    because a card built on a cache that stops at yesterday is wrong for
    every pitcher who has since started. Only once every starter is current
    does the leftover budget go on history, which is never wrong -- only
    absent.
    """
    fetch = fetch or fetch_season
    docs = {pid: load(pid) for pid in pitcher_ids}
    spent = 0

    def take(pid: int, yr: int) -> bool:
        nonlocal spent
        text = fetch(pid, yr)
        spent += 1
        doc = docs[pid]
        rows = aggregate(text) if text else {}
        # A finished season with nothing in it means he did not pitch that
        # year. The current season being empty in March means nothing at all,
        # so it is never recorded as such.
        empty = bool(not rows and yr < season)
        if rows:
            doc["seasons"][str(yr)] = rows
            if str(yr) in doc["empty"]:
                doc["empty"].remove(str(yr))
        elif empty and str(yr) not in doc["empty"]:
            doc["empty"].append(str(yr))
        doc["fetched"][str(yr)] = today
        # Written as it is fetched. A run that times out half way through
        # keeps what it paid for instead of throwing the whole pass away.
        save_season(pid, yr, rows, empty, today)
        return True

    # Pass one: today.
    for pid in pitcher_ids:
        if spent >= budget:
            break
        if docs[pid]["fetched"].get(str(season)) == today:
            continue
        take(pid, season)

    # Pass two: backfill, one season at a time.
    #
    # _wanted is recomputed after every fetch rather than listed once up
    # front. A pitcher who debuted in 2023 has no 2022, and a list taken
    # before the first fetch cannot know that -- it would spend the whole
    # budget walking him back to 2015 in a single run. Recomputing lets the
    # EMPTY_RUN rule end the walk as soon as the second empty year lands.
    # Round-robin rather than depth-first. Spending the whole leftover
    # budget on one starter's ten seasons would leave the other twenty cards
    # blank for days; one more season each per morning fills every card
    # shallowly first, which is the version a reader can use.
    done: set[int] = set()
    while spent < budget and len(done) < len(pitcher_ids):
        for pid in pitcher_ids:
            if spent >= budget:
                break
            if pid in done:
                continue
            rest = _wanted(docs[pid], season)[1:]
            if not rest:
                done.add(pid)
                continue
            take(pid, rest[0])

    if verbose:
        print(f"   savant: {spent} season-fetch(es), "
              f"{len(pitcher_ids)} starter(s) cached")
    return spent


# ---------------------------------------------------------------- the join --
def roster_xwoba(pitcher_id: int, batter_ids, doc: dict | None = None):
    """xwOBA against exactly these batters, and how many PA it rests on.

    batter_ids come from StatsAPI as ints; Savant's CSV column is a string.
    The join has to happen on one of them, and it happens on strings.
    """
    doc = doc if doc is not None else load(pitcher_id)
    wanted = {str(b) for b in batter_ids}
    den = num = 0.0
    for rows in (doc.get("seasons") or {}).values():
        for bid, pair in rows.items():
            if bid in wanted:
                den += pair[0]
                num += pair[1]
    return ((num / den if den else None), den)


def span(doc: dict) -> str:
    """The seasons actually cached, as '2019-2026'. Empty when nothing is."""
    years = sorted(int(y) for y in (doc.get("seasons") or {}))
    if not years:
        return ""
    return str(years[0]) if years[0] == years[-1] else f"{years[0]}–{years[-1]}"


# ---------------------------------------------------------------- tests --
CSV_FIXTURE = (
    "batter,events,woba_value,woba_denom,estimated_woba_using_speedangle\n"
    "111,field_out,0,1,0.150\n"
    "111,strikeout,0,1,\n"
    "111,walk,0.69,1,\n"
    "222,home_run,2.0,1,1.800\n"
    "222,,0,0,\n"
    ",field_out,0,1,0.500\n"
    "333,field_out,0,1,nan\n"
)


def _self_test() -> None:
    got = aggregate(CSV_FIXTURE)
    assert got["111"][0] == 3.0, got["111"]
    assert abs(got["111"][1] - 0.84) < 1e-9, got["111"]
    assert got["222"] == [1.0, 1.8], got["222"]
    assert "" not in got, "a row with no batter must not become a batter"
    # 'nan' must fall back to woba_value, not poison the total.
    assert got["333"] == [1.0, 0.0], got["333"]

    assert aggregate("") == {}
    assert aggregate("batter,woba_denom\n1,\n") == {}

    doc = {"seasons": {"2026": {"111": [3.0, 0.84], "999": [10.0, 5.0]}},
           "empty": [], "fetched": {}}
    x, pa = roster_xwoba(1, [111], doc)
    assert pa == 3.0 and abs(x - 0.28) < 1e-9, (x, pa)
    x, pa = roster_xwoba(1, [555], doc)
    assert x is None and pa == 0.0, (x, pa)
    # int ids from StatsAPI must join against the CSV's string ids.
    assert roster_xwoba(1, ["111"], doc) == roster_xwoba(1, [111], doc)

    assert span({"seasons": {"2019": {}, "2026": {}}}) == "2019–2026"
    assert span({"seasons": {"2026": {}}}) == "2026"
    assert span({"seasons": {}}) == ""

    # _wanted: current season always first, even when already held.
    d = {"seasons": {"2026": {}, "2025": {}}, "empty": [], "fetched": {}}
    w = _wanted(d, 2026)
    assert w[0] == 2026 and 2025 not in w, w
    assert w[1] == 2024, w
    # Two empties in a row stop the walk.
    d = {"seasons": {}, "empty": ["2024", "2023"], "fetched": {}}
    w = _wanted(d, 2026)
    assert w == [2026, 2025], w

    # warm(): today before history, and the budget is real.
    calls = []

    def fake(pid, yr):
        calls.append((pid, yr))
        return CSV_FIXTURE

    import tempfile
    global DATA
    keep = DATA
    try:
        DATA = pathlib.Path(tempfile.mkdtemp()) / "savant"
        spent = warm([99, 98], season=2026, today="2026-09-07", budget=3,
                     fetch=fake, verbose=False)
        assert spent == 3, spent
        assert calls[0] == (99, 2026) and calls[1] == (98, 2026), calls
        assert calls[2][1] == 2025, calls
        # Re-running the same day must not re-buy the current season.
        calls.clear()
        warm([99], season=2026, today="2026-09-07", budget=1, fetch=fake,
             verbose=False)
        assert calls and calls[0][1] != 2026, calls
        # The split-by-season layout has to survive a round trip, or the
        # cache silently re-buys every season every morning.
        back = load(99)
        assert "2026" in back["seasons"] and "2025" in back["seasons"], back
        assert back["fetched"]["2026"] == "2026-09-07", back["fetched"]
        assert back["seasons"]["2026"]["111"] == [3.0, 0.84], back["seasons"]

        # An empty finished season is remembered as empty, so the walk
        # backwards stops instead of asking again every day.
        calls.clear()
        warm([97], season=2026, today="2026-09-07", budget=4,
             fetch=lambda pid, yr: "" if yr < 2026 else CSV_FIXTURE,
             verbose=False)
        assert load(97)["empty"] == ["2024", "2025"], load(97)["empty"]
        calls.clear()
        warm([97], season=2026, today="2026-09-08", budget=4,
             fetch=lambda pid, yr: calls.append((pid, yr)) or CSV_FIXTURE,
             verbose=False)
        # 2026 refreshes (new day); the two known-empty years end the walk,
        # so nothing older is asked for.
        assert [c[1] for c in calls] == [2026], calls
    finally:
        DATA = keep

    print("savant: self-test ok")


if __name__ == "__main__":
    _self_test()
