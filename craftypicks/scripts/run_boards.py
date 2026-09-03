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


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        print(f"!! {path.name} is corrupt; starting from empty", file=sys.stderr)
        return default


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


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
    table = batters_mod.all_batters(season)
    settled = batters_mod.grade(history, table)
    rows = batters_mod.build(starters, season)

    known = {(r.get("batter_id"), r.get("commence_time")) for r in history}
    added = 0
    for row in rows:
        if (row.get("batter_id"), row.get("commence_time")) not in known:
            history.append(dict(row))
            added += 1
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
