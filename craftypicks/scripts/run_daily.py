#!/usr/bin/env python3
"""The whole daily job, in order:

    1. grade every posted play that now has a final score
    2. pull today's odds for the leagues that are in season
    3. find the plays worth posting and write today's card
    4. recompute the public stats
    5. rebuild the static site from those files

Safe to run more than once a day — plays are deduped by id, and grading is
idempotent.

    python scripts/run_daily.py              # live, needs ODDS_API_KEY
    CRAFTYPICKS_MOCK=1 python scripts/run_daily.py    # synthetic data, 0 credits
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent
DATA = ROOT / "data"

import config              # noqa: E402
import find_plays          # noqa: E402
import grade as grader     # noqa: E402
import stats as statsmod   # noqa: E402
from odds_client import BudgetExhausted, OddsAPIError, OddsClient  # noqa: E402


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


def local_now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def main() -> int:
    now = local_now()
    today = now.date().isoformat()
    print(f"== Craftypicks daily run — {now:%Y-%m-%d %H:%M %Z}")

    history = load_json(DATA / "history.json", {"plays": []})["plays"]

    try:
        client = OddsClient()
    except OddsAPIError as e:
        print(f"!! {e}", file=sys.stderr)
        return 1
    if client.mock:
        print("-- MOCK MODE: synthetic odds, no credits spent")

    # ------------------------------------------------------------- 1. grade
    sports_to_grade = grader.pending_sports(history)
    scores_by_sport: dict[str, dict] = {}
    for sport in sorted(sports_to_grade):
        try:
            scores_by_sport[sport] = grader.score_map(client.scores(sport))
        except BudgetExhausted as e:
            print(f"!! {e}", file=sys.stderr)
            break
        except OddsAPIError as e:
            print(f"!! scores for {sport} failed: {e}", file=sys.stderr)
    graded = grader.grade_pending(history, scores_by_sport)
    print(f"-- graded {graded} play(s); {sum(1 for p in history if not p.get('result'))} still pending")

    # -------------------------------------------------------------- 2. odds
    card: list[dict] = []
    note = ""
    try:
        in_season = client.in_season_sports()
        print(f"-- in season: {', '.join(in_season) or 'nothing'}")
        candidates = []
        for sport in in_season:
            games = client.odds(sport)
            found = find_plays.find_candidates(games)
            print(f"   {sport}: {len(games)} games, {len(found)} qualifying edges")
            candidates.extend(found)
        card = find_plays.build_card(candidates)
    except BudgetExhausted as e:
        note = "Credit budget for the month is spent — no new plays until it resets."
        print(f"!! {e}", file=sys.stderr)
    except OddsAPIError as e:
        note = "The odds feed didn't respond this morning. No plays posted."
        print(f"!! {e}", file=sys.stderr)

    if client.credits_remaining is not None:
        print(f"-- API credits: {client.credits_used_this_run} used this run, "
              f"{client.credits_remaining} left this month")

    # ------------------------------------------------------- 3. today's card
    posted_at = now.isoformat(timespec="seconds")
    existing_ids = {p.get("id") for p in history if p.get("posted_date") == today}
    for play in card:
        play["posted_date"] = today
        play["posted_at"] = posted_at
        play["result"] = None
        play["profit"] = 0.0
        if play["id"] not in existing_ids:
            history.append(dict(play))

    summary = find_plays.summarize(card)
    plays_doc = {
        "generated_at": posted_at,
        "date": today,
        "date_label": f"{now:%A, %B %-d, %Y}",
        "post_time": config.POST_TIME_LABEL,
        "plays": card,
        "summary": summary,
        "note": note,
        "mock": client.mock,
    }
    save_json(DATA / "plays.json", plays_doc)
    save_json(DATA / "history.json", {"plays": history})
    print(f"-- card: {len(card)} play(s), {summary['units_risked']}u risked")

    # ------------------------------------------------------------- 4. stats
    site_stats = statsmod.compute(history)
    save_json(DATA / "stats.json", site_stats)
    print(f"-- record {site_stats['record']} | {site_stats['units']:+}u | ROI {site_stats['roi']:+}%")

    # ------------------------------------------------------------- 5. build
    sys.path.insert(0, str(ROOT / "_src"))
    import build  # noqa: E402
    build.build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
