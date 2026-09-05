#!/usr/bin/env python3
"""Build every board that does not need an Odds API credit.

    python3 scripts/run_boards.py

MLB's side comes from the public StatsAPI; the NFL side from nflverse's free
CSV feed. Neither costs a credit, so both can be run as often as you like.
This exists because the daily job guards itself: once today's card is
committed, run_daily.py exits before it reaches any of the board code, and
the only way past that guard is CRAFTYPICKS_FORCE=1, which re-buys the odds.
So on any day a board is added, changed, or simply arrives late, this is the
way to fill it in without paying twice.

It writes seven public boards -- data/homers.json, batters.json, hits.json,
nfl_passing.json, nfl_rushing.json, nfl_receiving.json, and nfl_td.json --
each beside a *_ratings.json history of every row ever projected in that
category, which is what grading reads and appends to.

Grading is free and idempotent everywhere here: MLB settles a projection
against the same season leaderboard the build already fetches, and NFL
settles one against the same weekly feed, both gated on the game actually
being over. Re-running only ever adds rows it has not seen and grades rows
it has not yet graded.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent
DATA = ROOT / "data"

import config              # noqa: E402
import screen_config       # noqa: E402
import mlb_api             # noqa: E402
import homers as homers_mod    # noqa: E402
import batters as batters_mod  # noqa: E402
import hits as hits_mod        # noqa: E402
import projection              # noqa: E402
import results_store           # noqa: E402
import nfl_yards                # noqa: E402
import nfl_td                   # noqa: E402

# The calendar year the NFL season starts in -- 2026 covers the games
# played from September 2026 through early 2027.
NFL_SEASON = 2026


def load_json(path: Path, default):
    """Read a store, or quarantine it and start over if it will not parse.

    A half-written file (a run killed mid-write, before atomic saves existed)
    used to be silently treated as empty, and the very next save then
    overwrote it with tonight's rows only -- every prior graded row gone
    with no trace it had ever existed. Renaming the bad file aside keeps the
    evidence instead of destroying it, and the message on stderr makes the
    loss visible rather than quiet.
    """
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        bad = path.with_name(f"{path.name}.corrupt-{stamp}")
        try:
            os.replace(path, bad)
            where = f"; moved aside to {bad.name}"
        except OSError:
            where = ""
        print(f"!! {path.name} is corrupt{where}; starting from empty",
              file=sys.stderr)
        return default


def save_json(path: Path, payload) -> None:
    """Write a store in one step, or not at all.

    Reuses results_store's own atomic write (temp file + os.replace) rather
    than a second implementation of the same fix: path.write_text() truncates
    before it writes, so a run killed mid-save used to leave a half-written
    file for the next run's load_json to find.
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    results_store._write_atomic(path, text)


def main() -> int:
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    today = now.date().isoformat()
    label = f"{now:%A, %B %-d, %Y}"
    season = screen_config.SEASON
    print(f"== Craftypicks boards — {now:%Y-%m-%d %H:%M %Z}")

    starters = mlb_api.probable_starters(now.strftime("%m/%d/%Y"))
    print(f"-- schedule: {len(starters)} probable starter(s) listed")
    if not starters:
        # Not an error. MLB posts probables through the morning, and on an
        # off day there are none at all. Leaving yesterday's boards up would
        # be worse than leaving them empty, so nothing is written either way.
        # The NFL block below still runs -- an MLB off day must not cost the
        # NFL boards their run any more than an NFL failure should cost MLB's.
        print("   Nothing to build yet; the MLB boards keep whatever they hold.")
    else:
        # ---------------------------------------------------------- home runs allowed
        hr_rows = homers_mod.build(starters, season)
        if hr_rows:
            save_json(DATA / "homers.json", {
                "date": today,
                "date_label": label,
                "starters": hr_rows,
            })
            print(f"-- homers: {len(hr_rows)} starter(s) on the board")
        else:
            print("!! homers: no starter had enough innings to rate", file=sys.stderr)

        # ---------------------------------------------------------- batters
        history = load_json(DATA / "batter_ratings.json", {"batters": []})["batters"]
        repaired = projection.repair_premature(history, verdict_key="homered")
        if repaired:
            print(f"!! batter_ratings: reset {repaired} verdict(s) that were "
                  f"graded before their game had started", file=sys.stderr)
        table = batters_mod.all_batters(season)
        settled = batters_mod.grade(history, table)
        rows = batters_mod.build(starters, season)

        added = projection.merge(history, rows, ("batter_id", "commence_time"))
        summary = batters_mod.summary(history)
        save_json(DATA / "batter_ratings.json", {"batters": history})

        if rows:
            save_json(DATA / "batters.json", {
                "date": today,
                "date_label": label,
                "batters": rows,
                "summary": summary,
            })
            print(f"-- batters: {len(rows)} rated, {added} new, {settled} graded")
            if summary.get("expected") is not None:
                print(f"   calibration: promised {summary['expected']}%, "
                      f"delivered {summary['actual']}% on "
                      f"{summary['graded']} bat(s)")
        else:
            print("!! batters: no lineup cleared the plate-appearance floor",
                  file=sys.stderr)

        # ---------------------------------------------------------- hits
        hit_hist = load_json(DATA / "hit_ratings.json", {"batters": []})["batters"]
        hit_repaired = projection.repair_premature(hit_hist, verdict_key="got_hit")
        if hit_repaired:
            print(f"!! hit_ratings: reset {hit_repaired} verdict(s) that were "
                  f"graded before their game had started", file=sys.stderr)
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
