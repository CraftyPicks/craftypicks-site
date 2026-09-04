#!/usr/bin/env python3
"""Build the two home-run boards from free data only.

    python3 scripts/run_boards.py

Everything here comes from MLB's public StatsAPI, so this spends no Odds API
credits and can be run as often as you like. It exists because the daily job
guards itself: once today's card is committed, run_daily.py exits before it
reaches any of the board code, and the only way past that guard is
CRAFTYPICKS_FORCE=1, which re-buys the odds. So on any day the boards are
added, changed, or simply arrive late, this is the way to fill them in
without paying twice.

It writes:

    data/homers.json          tonight's starters, ranked by home runs allowed
    data/batters.json         tonight's batters, ranked by chance to go deep
    data/batter_ratings.json  every batter ever projected, for grading

Grading is free and idempotent: a batter's season home-run total tonight,
against his total on the night he was projected, answers whether he went
deep. Re-running only ever adds rows it has not seen.
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
        print("   Nothing to build yet; the boards keep whatever they hold.")
        return 0

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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
