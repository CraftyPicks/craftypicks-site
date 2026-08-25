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

import gzip
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

# Props are an optional extra. If props.py is missing or won't import, the
# daily card still has to go out — a nice-to-have must never be able to take
# down the thing the site exists for.
try:
    import props           # noqa: E402
except Exception as _props_err:                              # noqa: BLE001
    props = None
    print(f"!! props module unavailable ({_props_err}); sides only", file=sys.stderr)

# The strikeout screens. Also optional — a rules system that fails to import
# must not stop the price scanner from posting.
try:
    import screen_source   # noqa: E402
except Exception as _screen_err:                             # noqa: BLE001
    screen_source = None
    print(f"!! screen system unavailable ({_screen_err})", file=sys.stderr)
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


def archive_board(sport: str, day: str, games: list[dict]) -> None:
    """Keep the raw odds response for the day.

    This costs nothing — it's the same API call we already made — and it is
    the single most valuable thing this project does long-term. Historical
    odds are the one input nobody hands out free. Every morning this runs,
    the archive is worth slightly more, and after a few months it can answer
    the question free data cannot: not "does this factor matter" but "does it
    matter more than the market already charges for it."
    """
    if not games:
        return
    path = DATA / "archive" / day
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sport": sport,
        "games": games,
    }
    # gzip keeps a year of daily boards down to tens of megabytes instead of
    # hundreds — worth it for something that only ever grows.
    with gzip.open(path / f"{sport}.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    print(f"   archived {len(games)} {sport} boards")


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
        prop_events: list[dict] = []
        for sport in in_season:
            all_games = client.odds(sport)
            archive_board(sport, today, all_games)
            games = find_plays.todays_games(all_games)
            dropped = len(all_games) - len(games)
            found = find_plays.find_candidates(games)
            print(f"   {sport}: {len(games)} games today "
                  f"({dropped} not today, skipped), {len(found)} qualifying edges")
            if getattr(find_plays, "REJECTED", None):
                for reason, count in find_plays.REJECTED.most_common():
                    print(f"      rejected — {reason}: {count}")
                near = sorted(getattr(find_plays, "NEAR_MISSES", []),
                              key=lambda n: -n[2])[:5]
                for side, price, ev, pp, gate in near:
                    print(f"      near miss ({gate}) {str(side)[:22]:<22} "
                          f"{price:>5}  EV {ev:>5.2f}%  pp {pp:>5.2f}")
            candidates.extend(found)

            # Props: per-event, so strictly capped. See config.PROP_MAX_EVENTS.
            # The whole block is wrapped: a prop market that's missing, shaped
            # unexpectedly, or unavailable for a given game must never cost us
            # the card.
            if (props and getattr(config, "PROP_MARKETS", None)
                    and sport in getattr(config, "PROP_SPORTS", [])
                    and games
                    and (client.credits_remaining is None
                         or client.credits_remaining > getattr(config, "PROP_CREDIT_FLOOR", 160))):
                try:
                    targets = props.pick_events(games, config.PROP_MAX_EVENTS)
                    print(f"   props: {len(targets)} event(s) × "
                          f"{len(config.PROP_MARKETS)} market(s) = "
                          f"{len(targets) * len(config.PROP_MARKETS)} credits")
                    for event in targets:
                        try:
                            detail = client.event_odds(sport, event["id"], config.PROP_MARKETS)
                        except (BudgetExhausted, OddsAPIError) as e:
                            print(f"     !! props for {event.get('id')}: {e}", file=sys.stderr)
                            break
                        # Kept so the screens can reuse this payload for free.
                        detail.setdefault("sport_key", sport)
                        prop_events.append(detail)
                        for market_key in config.PROP_MARKETS:
                            hits = props.scan_event(detail, market_key)
                            if hits:
                                print(f"     {market_key}: {len(hits)} edge(s)")
                            candidates.extend(hits)
                except Exception as e:                       # noqa: BLE001
                    print(f"   !! props failed ({type(e).__name__}: {e}) — "
                          "continuing with sides only", file=sys.stderr)
        for cand in candidates:
            cand.setdefault("source", "value")

        # The screens run on the games we already bought prop odds for, so
        # they cost nothing extra. Tagged separately so the record can judge
        # them against the price scanner rather than blending the two.
        if screen_source and prop_events:
            try:
                screen_plays = screen_source.build_plays(
                    prop_events, now.strftime("%m/%d/%Y"))
                candidates.extend(screen_plays)
            except Exception as e:                           # noqa: BLE001
                print(f"   !! screens failed ({type(e).__name__}: {e}) — "
                      "continuing without them", file=sys.stderr)

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
