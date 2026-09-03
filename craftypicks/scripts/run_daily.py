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

# Pitcher projections. Optional like everything else.
try:
    import pitchers as pitch_mod  # noqa: E402
    import homers as homers_mod   # noqa: E402
    import batters as batters_mod # noqa: E402
except Exception as _pitch_err:                              # noqa: BLE001
    # All three are cleared, not just the first. They are imported together
    # for brevity, but a failure part-way through would otherwise leave the
    # later names undefined, and `if homers_mod` further down would raise
    # NameError -- turning an optional board into a broken daily run.
    pitch_mod = None
    homers_mod = None
    batters_mod = None
    print(f"!! pitcher board unavailable ({_pitch_err})", file=sys.stderr)

# Full-board ratings. Optional too, but this is the piece that makes the
# numbers checkable in weeks instead of years.
try:
    import slate as slate_mod  # noqa: E402
except Exception as _slate_err:                              # noqa: BLE001
    slate_mod = None
    print(f"!! slate rating unavailable ({_slate_err})", file=sys.stderr)

# The board is the site's main page. It is still guarded like everything else
# here: a failure to price must not stop the card going out.
try:
    import board as board_mod   # noqa: E402
    import leagues              # noqa: E402
except Exception as _board_err:                              # noqa: BLE001
    board_mod = None
    leagues = None
    print(f"!! board unavailable ({_board_err})", file=sys.stderr)
from odds_client import BudgetExhausted, OddsAPIError, OddsClient  # noqa: E402

# Yesterday's finals, from the free sources. Optional like everything else:
# the card must go out whether or not ESPN answered.
try:
    import results         # noqa: E402
    import results_store   # noqa: E402
except Exception as _rs_err:                                 # noqa: BLE001
    results = None
    results_store = None
    print(f"!! results store unavailable ({_rs_err})", file=sys.stderr)


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

    # Already posted today? Then this is a retry of a scheduled run that
    # already succeeded, and it must not spend a second set of credits.
    # GitHub's scheduler is unreliable enough that the workflow fires several
    # times in the 9 AM hour; this is what makes that safe.
    posted = load_json(DATA / "plays.json", {})
    forced = os.environ.get("CRAFTYPICKS_FORCE", "").strip() == "1"
    if (posted.get("date") == today and not forced
            and os.environ.get("CRAFTYPICKS_MOCK", "").strip() != "1"):
        print(f"-- already posted a card for {today} at "
              f"{posted.get('generated_at', 'an earlier run')}; nothing to do.")
        print("   (set CRAFTYPICKS_FORCE=1 to re-run anyway)")
        return 0

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
    # Declared out here on purpose: sections 3b and 3c read them, and an odds
    # failure inside the try must not leave those names undefined.
    candidates: list[dict] = []
    prop_events: list[dict] = []
    slate_rows: list[dict] = []
    boards: dict[str, list[dict]] = {}
    # Declared out here for the same reason as the names above: the results
    # store reads it long after this try block, and an odds failure must not
    # leave it undefined.
    in_season: list[str] = []
    try:
        in_season = client.in_season_sports()
        print(f"-- in season: {', '.join(in_season) or 'nothing'}")
        for sport in in_season:
            # Free look at the schedule before spending anything. A league
            # with no games today gets skipped entirely instead of costing
            # a credit per market for a board we'd throw away.
            try:
                upcoming = client.events(sport)
                if not find_plays.todays_games(upcoming):
                    print(f"   {sport}: no games today — skipped "
                          f"({len(upcoming)} upcoming), 0 credits spent")
                    continue
            except OddsAPIError as e:
                print(f"   {sport}: schedule check failed ({e}); pulling odds anyway",
                      file=sys.stderr)

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

            # Price the whole board for this league, not only the plays. This is
            # free: the odds were already pulled above, and nothing here calls
            # the API.
            if board_mod:
                lg = leagues.by_sport_key(sport)
                if lg:
                    try:
                        boards[lg.short] = board_mod.build(games, lg.short)
                        print(f"   board: {len(boards[lg.short])} {lg.short} "
                              f"game(s) priced")
                    except Exception as e:                       # noqa: BLE001
                        print(f"!! board failed for {sport}: {e}", file=sys.stderr)

            # Rate every game on the board, not just the ones we'd bet.
            if slate_mod and sport == "baseball_mlb":
                try:
                    import screen_config as _scfg
                    slate_rows = slate_mod.build(
                        games, now.strftime("%m/%d/%Y"), _scfg.SEASON)
                    if slate_rows:
                        print(f"   slate: rated {len(slate_rows)} game(s)")
                except Exception as e:                       # noqa: BLE001
                    print(f"   !! slate failed ({type(e).__name__}: {e})",
                          file=sys.stderr)

                # The board already has this game priced; slate has it rated.
                # Same event ids, so the two join cleanly.
                # Guarded like every other module call in this loop. The board
                # going out without our number is a worse day than usual; the
                # card not going out at all is a broken morning.
                if board_mod and lg and boards.get(lg.short):
                    try:
                        n = board_mod.merge_model(boards[lg.short],
                                                  slate_rows, "slate")
                        print(f"   board: {n} {lg.short} game(s) carry "
                              f"our number")
                    except Exception as e:                   # noqa: BLE001
                        print(f"   !! merge failed ({type(e).__name__}: {e})",
                              file=sys.stderr)

            # Props: per-event, so strictly capped. See config.PROP_MAX_EVENTS.
            # The whole block is wrapped: a prop market that's missing, shaped
            # unexpectedly, or unavailable for a given game must never cost us
            # the card.
            prop_cost = config.PROP_MAX_EVENTS * len(getattr(config, "PROP_MARKETS", []) or [])
            spare = config.spare_credits(client.credits_remaining,
                                         now.date(), len(in_season))
            if (props and getattr(config, "PROP_MARKETS", None)
                    and sport in getattr(config, "PROP_SPORTS", [])
                    and games
                    and spare < prop_cost):
                print(f"   props: skipped — {client.credits_remaining} credits left, "
                      f"{config.days_until_reset(now.date())} days to reset, "
                      f"spare after reserving the card is {spare}, props need {prop_cost}")
            elif (props and getattr(config, "PROP_MARKETS", None)
                    and sport in getattr(config, "PROP_SPORTS", [])
                    and games):
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

    # --------------------------------------------------- 3c. pitcher board
    if pitch_mod and prop_events:
        try:
            import screen_config as _scfg
            # Not `history`, and not `ratings` either. `history` holds the play
            # log loaded at the top of this function and statsmod.compute()
            # below builds the whole track-record page from it -- rebinding it
            # here fed 101 pitcher rows to the record page, which is why the
            # site read "0-0-0, 101 pending" while history.json held seven
            # graded plays. `ratings` is taken by the slate block further down.
            # Every list in this function gets its own name from now on.
            pitch_ratings = load_json(DATA / "pitcher_ratings.json", {"pitchers": []})["pitchers"]
            todays = pitch_mod.build(prop_events, now.strftime("%m/%d/%Y"),
                                     _scfg.SEASON)
            known = {(r.get("pitcher_id"), r.get("date")) for r in pitch_ratings}
            for row in todays:
                if (row.get("pitcher_id"), row.get("date")) not in known:
                    pitch_ratings.append(dict(row))
            pitch_mod.grade(pitch_ratings, _scfg.SEASON)
            pitch_summary = pitch_mod.summary(pitch_ratings)
            save_json(DATA / "pitcher_ratings.json", {"pitchers": pitch_ratings})

            keys = {(r.get("pitcher_id"), r.get("date")) for r in todays}
            board = [r for r in pitch_ratings
                     if (r.get("pitcher_id"), r.get("date")) in keys] or todays
            board.sort(key=lambda r: r.get("commence_time") or "")
            save_json(DATA / "pitchers.json", {
                "date": today,
                "date_label": f"{now:%A, %B %-d, %Y}",
                "pitchers": board,
                "summary": pitch_summary,
            })
            if pitch_summary.get("mae") is not None:
                print(f"-- pitchers: avg miss {pitch_summary['mae']} K on "
                      f"{pitch_summary['graded']} graded "
                      f"(line missed by {pitch_summary['line_mae']})")
        except Exception as e:                               # noqa: BLE001
            print(f"!! pitcher board failed ({type(e).__name__}: {e})",
                  file=sys.stderr)

    # -------------------------------------------------- 3d. home-run board
    # Deliberately not inside the prop block above. That one only runs when
    # prop events were bought; this one needs nothing but the free schedule,
    # and a page that disappears on a day the props were skipped would look
    # broken rather than thrifty.
    if homers_mod and "baseball_mlb" in in_season:
        try:
            import screen_config as _hcfg
            import mlb_api as _hapi
            hr_starters = _hapi.probable_starters(now.strftime("%m/%d/%Y"))
            hr_rows = homers_mod.build(hr_starters, _hcfg.SEASON)
            if hr_rows:
                save_json(DATA / "homers.json", {
                    "date": today,
                    "date_label": f"{now:%A, %B %-d, %Y}",
                    "starters": hr_rows,
                })
                print(f"-- homers: {len(hr_rows)} starter(s) on the board")

            # The batter board is a projection, so it is stored and graded
            # from the first night. Grading costs nothing: the leaderboard is
            # refetched here anyway, and a batter's season total against the
            # total recorded when he was projected answers the question.
            bat_hist = load_json(DATA / "batter_ratings.json",
                                 {"batters": []})["batters"]
            table = batters_mod.all_batters(_hcfg.SEASON)
            settled = batters_mod.grade(bat_hist, table)
            bat_rows = batters_mod.build(hr_starters, _hcfg.SEASON)
            known = {(r.get("batter_id"), r.get("commence_time"))
                     for r in bat_hist}
            for row in bat_rows:
                if (row.get("batter_id"), row.get("commence_time")) not in known:
                    bat_hist.append(dict(row))
            bat_summary = batters_mod.summary(bat_hist)
            save_json(DATA / "batter_ratings.json", {"batters": bat_hist})
            if bat_rows:
                save_json(DATA / "batters.json", {
                    "date": today,
                    "date_label": f"{now:%A, %B %-d, %Y}",
                    "batters": bat_rows,
                    "summary": bat_summary,
                })
                print(f"-- batters: {len(bat_rows)} rated, {settled} graded")
                if bat_summary.get("expected") is not None:
                    print(f"   calibration: promised "
                          f"{bat_summary['expected']}%, delivered "
                          f"{bat_summary['actual']}% on "
                          f"{bat_summary['graded']} bat(s)")
        except Exception as e:                               # noqa: BLE001
            print(f"!! home-run board failed ({type(e).__name__}: {e})",
                  file=sys.stderr)

    # ------------------------------------------------------- 3b. rated board
    if slate_mod:
        try:
            ratings = load_json(DATA / "ratings.json", {"games": []})["games"]
            known = {r.get("event_id") for r in ratings}
            for row in slate_rows:
                if row.get("event_id") not in known:
                    ratings.append(dict(row))
            # Grade any rated game we now have a final score for.
            mlb_scores = scores_by_sport.get("baseball_mlb")
            if mlb_scores is None and any(not r.get("result") for r in ratings):
                try:
                    mlb_scores = grader.score_map(client.scores("baseball_mlb"))
                except (BudgetExhausted, OddsAPIError):
                    mlb_scores = None
            if mlb_scores:
                n = slate_mod.grade(ratings, mlb_scores)
                print(f"-- slate: graded {n} rated game(s)")
            summary_doc = slate_mod.summary(ratings)
            save_json(DATA / "ratings.json", {"games": ratings})
            # Publish the stored rows, not the freshly built ones: the stored
            # copy is the one grading writes finals onto, so a late run picks
            # up scores for games that have already ended today.
            todays = {r.get("event_id") for r in slate_rows}
            board = [r for r in ratings if r.get("event_id") in todays] or slate_rows
            board.sort(key=lambda r: r.get("commence_time") or "")
            save_json(DATA / "slate.json", {
                "date": today,
                "date_label": f"{now:%A, %B %-d, %Y}",
                "games": board,
                "summary": summary_doc,
            })
            if summary_doc.get("brier") is not None:
                print(f"-- slate: Brier {summary_doc['brier']} on "
                      f"{summary_doc['graded']} graded ratings"
                      + (f" (market {summary_doc['market_brier']})"
                         if summary_doc.get("market_brier") else ""))
        except Exception as e:                               # noqa: BLE001
            print(f"!! slate bookkeeping failed ({type(e).__name__}: {e})",
                  file=sys.stderr)

    if results and results_store and leagues:
        yesterday = (now.date() - timedelta(days=1)).isoformat()

        for short in leagues.ORDER:
            # Only leagues that actually played. Two credits a day for a sport
            # that is out of season buys an empty list.
            sport_key = leagues.LEAGUES[short].sport_key
            if sport_key not in in_season:
                continue
            # finals() knows which source each league uses; it only needs
            # the client for the paid ones, and MLB never touches it.
            def fetch(lg, day, _c=client):
                return results.finals(lg, day, client=_c)
            # append_day swallows a failed fetch itself, but not a bug in its
            # own merge. Nothing below this line catches an exception, and the
            # card has to go out.
            try:
                gained = results_store.append_day(short, yesterday,
                                                  fetch=fetch)
                if gained:
                    print(f"-- results: +{gained} {short} final(s) "
                          f"for {yesterday}")
            except Exception as e:                           # noqa: BLE001
                print(f"!! storing {short} results failed "
                      f"({type(e).__name__}: {e})", file=sys.stderr)

    # MLB already carries a richer number from the slate -- Elo plus the
    # starting pitcher -- so it is rated above and deliberately skipped here.
    # Everything else gets plain Elo once its store is deep enough.
    if board_mod and results_store and leagues:
        for short, rows in boards.items():
            if short == "mlb" or not rows:
                continue
            # Guarded like every other module call in this file. A league
            # going unrated is a worse board; an exception here is no card
            # at all, because nothing below this catches it.
            try:
                # Named `stored`, not `history`: `history` is the play log
                # this function writes to stats.json further down.
                stored = results_store.load(short)
                rated, skipped = board_mod.elo_model(rows, stored, short)
                # Printed whenever there is a store to rate from, including
                # when nothing was rated. The likeliest reason for a zero is
                # that ESPN and the Odds API spell the clubs differently, and
                # that failure is otherwise completely silent — the feature
                # just never appears.
                if stored:
                    n = board_mod.merge_model(rows, rated, "elo") if rated else 0
                    print(f"-- ratings: {n} {short} game(s) rated from "
                          f"{len(stored)} stored result(s)"
                          + (f", {skipped} skipped for unknown or thin clubs"
                             if skipped else ""))
                # MLB fills these from StatsAPI in slate.py. Every other
                # league has no free source, so it uses the same stored
                # finals the Elo model just read.
                f = board_mod.merge_form(rows, stored)
                print(f"-- form: {f} {short} card(s) carry a streak and a "
                      f"season series")
            except Exception as e:                           # noqa: BLE001
                print(f"!! rating {short} failed "
                      f"({type(e).__name__}: {e})", file=sys.stderr)

    if board_mod and boards:
        doc = board_mod.document(
            boards, now.isoformat(timespec="seconds"), today)
        (DATA / "board.json").write_text(
            json.dumps(doc, indent=1), encoding="utf-8")
        total = sum(doc["counts"].values())
        print(f"-- board.json: {total} game(s) across "
              f"{len(doc['leagues'])} league(s)")

    # ------------------------------------------------------------- 4. stats
    site_stats = statsmod.compute(history)
    save_json(DATA / "stats.json", site_stats)
    print(f"-- record {site_stats['record']} | {site_stats['units']:+}u | ROI {site_stats['roi']:+}%")

    # ------------------------------------------------------ 4b. credit report
    if not client.mock:
        left, used = client.credits_remaining, client.credits_used_this_run
        if left is not None:
            days = config.days_until_reset(now.date())
            pace = left / days if days else float(left)
            print(f"-- credits: {used} spent this run, {left} left, "
                  f"{days} day(s) to reset — {pace:.1f}/day available")
            if used > pace:
                print(f"   !! this run cost more than the daily pace. At {used}/day "
                      f"the allowance runs out in {left // max(1, used)} day(s).")

    # ------------------------------------------------------------- 5. build
    sys.path.insert(0, str(ROOT / "_src"))
    import build  # noqa: E402
    build.build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
