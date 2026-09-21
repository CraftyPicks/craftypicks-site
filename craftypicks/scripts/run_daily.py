#!/usr/bin/env python3
"""The whole daily job, in order:

    1. free upkeep — tidy the repo, settle stored win probabilities
    2. pull today's odds for the leagues that are in season
    3. price and rate every board from those odds
    4. rebuild the static site from those files

Safe to run more than once a day: the free work is idempotent, and a marker
file stops a retry buying a second set of odds.

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
# find_plays is imported for todays_games() only -- the day filter every
# board shares. The play-selection half of this program is gone.
import find_plays          # noqa: E402
import grade as grader     # noqa: E402
import tidy                # noqa: E402

# Props are an optional extra. If props.py is missing or won't import, the
# game boards still have to go out — a nice-to-have must never be able to
# take down the thing the site exists for.
try:
    import props           # noqa: E402
except Exception as _props_err:                              # noqa: BLE001
    props = None
    print(f"!! props module unavailable ({_props_err}); sides only", file=sys.stderr)

# Pitcher projections. Optional like everything else.
try:
    import pitchers as pitch_mod  # noqa: E402
    import homers as homers_mod   # noqa: E402
    import batters as batters_mod # noqa: E402
    import hits as hits_mod       # noqa: E402
    import projection             # noqa: E402
except Exception as _pitch_err:                              # noqa: BLE001
    # All are cleared, not just the first. They are imported together for
    # brevity, but a failure part-way through would otherwise leave the
    # later names undefined, and `if homers_mod` further down would raise
    # NameError -- turning an optional board into a broken daily run.
    pitch_mod = None
    homers_mod = None
    batters_mod = None
    hits_mod = None
    projection = None
    print(f"!! pitcher board unavailable ({_pitch_err})", file=sys.stderr)

# The first-seven board. Imported on its own, not with the pitcher group:
# it is the newest board and the only one that reads linescores, so a
# failure here must cost this board and nothing beside it.
try:
    import f7 as f7_mod        # noqa: E402
    import linescore           # noqa: E402
except Exception as _f7_err:                                 # noqa: BLE001
    f7_mod = None
    linescore = None
    print(f"!! f7 board unavailable ({_f7_err})", file=sys.stderr)

# Full-board ratings. Optional too, but this is the piece that makes the
# numbers checkable in weeks instead of years.
try:
    import slate as slate_mod  # noqa: E402
except Exception as _slate_err:                              # noqa: BLE001
    slate_mod = None
    print(f"!! slate rating unavailable ({_slate_err})", file=sys.stderr)

# The board is the site's main page. It is still guarded like everything else
# here: a failure to price one league must not stop the rest.
try:
    import board as board_mod   # noqa: E402
    import leagues              # noqa: E402
except Exception as _board_err:                              # noqa: BLE001
    board_mod = None
    leagues = None
    print(f"!! board unavailable ({_board_err})", file=sys.stderr)
from odds_client import BudgetExhausted, OddsAPIError, OddsClient  # noqa: E402

# Yesterday's finals, from the free sources. Optional like everything else:
# the boards go out whether or not ESPN answered.
try:
    import results         # noqa: E402
    import results_store   # noqa: E402
    import form_store      # noqa: E402
    import board_ratings   # noqa: E402
except Exception as _rs_err:                                 # noqa: BLE001
    results = None
    results_store = None
    form_store = None
    board_ratings = None
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


# The "we already bought odds today" marker. See the guard in main().
RUN_MARKER = DATA / "last_run.json"

CREDIT_LOG = DATA / "credits.json"
CREDIT_LOG_KEEP = 60


def credit_history() -> list[dict]:
    """What each recent day actually cost, oldest first.

    This exists so the props reserve can be measured instead of guessed.
    See config.daily_reserve for why the guess was wrong.
    """
    doc = load_json(CREDIT_LOG, {})
    days = doc.get("days") if isinstance(doc, dict) else None
    return days if isinstance(days, list) else []


def record_credits(date_str: str, spent: int, left, extras: int = 0) -> None:
    """One row per day. A re-run on the same day replaces that day's row
    rather than appending a second one, or a morning with three manual
    dispatches would read as three expensive days.

    `core` is the day's cost with the optional extras taken out, and it is
    the number the reserve is built from. Reserving against total spend
    creates a loop that shuts the extras off: the 2026-09-07 12:16 run
    bought props for the first time in three days, its 17 credits became a
    22/day reserve, and that reserve would have skipped props the next
    morning -- the reserve using props spend as its reason to stop buying
    props. A reserve exists to protect the game boards. Only they belong in
    it."""
    days = [d for d in credit_history() if d.get("date") != date_str]
    days.append({"date": date_str, "spent": int(spent),
                 "core": max(0, int(spent) - int(extras or 0)),
                 "left": None if left is None else int(left)})
    save_json(CREDIT_LOG, {"days": days[-CREDIT_LOG_KEEP:]})


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


def _rebuild_pages() -> None:
    """Regenerate the static site from whatever is on disk right now.

    Section 4 does this at the end of a full run. The early return after the
    guard needs it too: a win probability settled a moment ago has to reach
    the calibration strip today rather than waiting for tomorrow.
    """
    sys.path.insert(0, str(ROOT / "_src"))
    import build  # noqa: PLC0415
    build.build()


def main() -> int:
    now = local_now()
    today = now.date().isoformat()
    print(f"== Craftypicks daily run — {now:%Y-%m-%d %H:%M %Z}")

    # Every win probability the non-MLB boards have published, and whether it
    # came true. Loaded here so section 0 can grade it for free.
    board_rated = load_json(DATA / "board_ratings.json",
                            {"ratings": []})["ratings"]

    # ------------------------------------------------- 0. the free upkeep
    # Everything here costs nothing -- local file work and StatsAPI -- and is
    # idempotent, so it runs on EVERY invocation, before the guard below.
    #
    # It used to sit after the guard, which was the wrong boundary: the guard
    # exists to stop a retry buying a second set of odds, and it was also
    # stopping the parts that keep the public numbers honest. On 2026-09-11,
    # when GitHub dropped all three morning attempts, eleven stray files
    # stayed at the repo root and the settled probabilities stayed ungraded,
    # while the 14:21 retry the day before reported "nothing to do".
    try:
        tidy.run(DATA.parent.parent, DATA)
    except Exception as e:                                   # noqa: BLE001
        print(f"!! tidy failed: {e}", file=sys.stderr)

    settled = 0

    # The win probabilities the non-MLB boards published, settled against the
    # finals the store already holds. Free -- results_store is filled by the
    # boards job and, for the NFL, from nflverse -- so it belongs up here
    # with the rest of the upkeep rather than behind the credit guard.
    #
    # The leagues come from the stored rows, not from today's board: a rating
    # published on Sunday is graded on Monday, when that league may have no
    # games at all.
    if board_ratings is not None and results_store is not None:
        try:
            finals = {lg: results_store.load(lg)
                      for lg in sorted({r.get("league") for r in board_rated
                                        if r.get("league")})}
            settled = board_ratings.grade(board_rated, finals)
            if settled:
                save_json(DATA / "board_ratings.json",
                          {"ratings": board_rated})
                print(f"-- ratings: graded {settled} stored "
                      f"probability(ies)")
            for lg in sorted(finals):
                scored = board_ratings.summary(board_rated, lg)
                if scored["graded"]:
                    market = (f" (market {scored['market_brier']})"
                              if scored["market_brier"] is not None else "")
                    print(f"-- ratings: {lg} Brier {scored['brier']} on "
                          f"{scored['graded']} graded{market}")
        except Exception as e:                               # noqa: BLE001
            print(f"!! rating grades failed ({type(e).__name__}: {e})",
                  file=sys.stderr)

    # Already bought odds today? Then this is a retry of a scheduled run that
    # already succeeded, and it must not spend a second set of credits.
    # GitHub's scheduler is unreliable enough that the workflow fires several
    # times in the 9 AM hour; this is what makes that safe.
    #
    # The marker is its own file rather than a board document, because
    # run_boards.py writes board.json on its own schedule and this run would
    # then read that as "I already went".
    #
    # Note what is above this line and what is below it: free work runs
    # always, paid work runs once.
    marker = load_json(RUN_MARKER, {})
    forced = os.environ.get("CRAFTYPICKS_FORCE", "").strip() == "1"
    if (marker.get("date") == today and not forced
            and os.environ.get("CRAFTYPICKS_MOCK", "").strip() != "1"):
        print(f"-- odds for {today} were already bought at "
              f"{marker.get('at', 'an earlier run')}; nothing more to buy.")
        print("   (set CRAFTYPICKS_FORCE=1 to re-run anyway)")
        # The pages still get rebuilt: a probability settled a moment ago has
        # to reach the calibration strip today, not tomorrow morning.
        if settled:
            _rebuild_pages()
        return 0

    try:
        client = OddsClient()
    except OddsAPIError as e:
        print(f"!! {e}", file=sys.stderr)
        return 1
    if client.mock:
        print("-- MOCK MODE: synthetic odds, no credits spent")

    # Finals are pulled on demand further down -- the slate grader asks for
    # MLB scores only when it has a rated game still waiting on one, and
    # results_store fetches the rest from the free sources. Nothing needs a
    # blanket scores call any more.
    scores_by_sport: dict[str, dict] = {}

    # -------------------------------------------------------------- 2. odds
    # Declared out here on purpose: sections 3b and 3c read them, and an odds
    # failure inside the try must not leave those names undefined.
    prop_events: list[dict] = []
    slate_rows: list[dict] = []
    boards: dict[str, list[dict]] = {}
    # Declared out here for the same reason as the names above: the results
    # store reads it long after this try block, and an odds failure must not
    # leave it undefined.
    in_season: list[str] = []
    # What the optional extras cost this run, so the reserve can be built on
    # the game boards alone. See record_credits.
    extra_credits = 0
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
            not_today = len(all_games) - len(games)
            print(f"   {sport}: {len(games)} games today "
                  f"({not_today} not today, skipped)")

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
                # board not going out at all is a broken morning.
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
            # the rest of the run.
            prop_cost = config.PROP_MAX_EVENTS * len(getattr(config, "PROP_MARKETS", []) or [])
            spare = config.spare_credits(client.credits_remaining,
                                         now.date(), len(in_season),
                                         credit_history(),
                                         client.credits_used_this_run)
            if (props and getattr(config, "PROP_MARKETS", None)
                    and sport in getattr(config, "PROP_SPORTS", [])
                    and games
                    and spare < prop_cost):
                per_day, why = config.daily_reserve(credit_history(),
                                                   len(in_season))
                print(f"   props: skipped — {client.credits_remaining} credits left, "
                      f"{config.days_until_reset(now.date())} days to reset, "
                      f"reserving {per_day}/day ({why}), "
                      f"spare after reserving the boards is {spare}, props need {prop_cost}")
            elif (props and getattr(config, "PROP_MARKETS", None)
                    and sport in getattr(config, "PROP_SPORTS", [])
                    and games):
                try:
                    targets = props.pick_events(games, config.PROP_MAX_EVENTS)
                    extra_credits += len(targets) * len(config.PROP_MARKETS)
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
                except Exception as e:                       # noqa: BLE001
                    print(f"   !! props failed ({type(e).__name__}: {e}) — "
                          "continuing without them", file=sys.stderr)
    except BudgetExhausted as e:
        print(f"!! {e}", file=sys.stderr)
    except OddsAPIError as e:
        print(f"!! {e}", file=sys.stderr)

    if client.credits_remaining is not None:
        print(f"-- API credits: {client.credits_used_this_run} used this run, "
              f"{client.credits_remaining} left this month")

    # ----------------------------------------------------- 3. the run marker
    # Written as soon as the odds are in hand, which is the thing the guard
    # is protecting. Everything below this line is free work on data already
    # bought, so a crash in a board still leaves the marker honest: the
    # credits were spent, and a retry must not spend them again.
    save_json(RUN_MARKER, {
        "date": today,
        "at": now.isoformat(timespec="seconds"),
        "mock": client.mock,
    })

    # --------------------------------------------------- 3c. pitcher board
    # No longer gated on prop_events. The projection is StatsAPI only, so a
    # morning the credit reserve declined to buy props is still a morning we
    # can publish and score a number for every probable starter -- and it is
    # the morning the board mattered most, because there was nothing else on
    # that page.
    if pitch_mod:
        try:
            import screen_config as _scfg
            # Not `ratings` either -- that name is taken by the slate block
            # further down. Every list in this function gets its own name:
            # an earlier rebinding fed 101 pitcher rows to a page that was
            # reading a different list entirely.
            pitch_ratings = load_json(DATA / "pitcher_ratings.json", {"pitchers": []})["pitchers"]
            # The MLB board rows go in so every starter gets his fixture,
            # not just the ones a prop was bought on. Without this an
            # unpriced starter carried event_id None and the game board
            # could not find him.
            todays = pitch_mod.build(prop_events, now.strftime("%m/%d/%Y"),
                                     _scfg.SEASON,
                                     board_rows=boards.get("mlb"))
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
                msg = (f"-- pitchers: avg miss {pitch_summary['mae']} K on "
                       f"{pitch_summary['graded']} graded")
                if pitch_summary.get("line_mae") is not None:
                    msg += (f" (line missed by {pitch_summary['line_mae']} on "
                            f"{pitch_summary['priced']} priced)")
                print(msg)
            priced_today = sum(1 for r in todays if r.get("line") is not None)
            print(f"   pitchers: {len(todays)} starter(s) on the board, "
                  f"{priced_today} with a posted line")
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

            # The hits board, beside the batter board and not inside its
            # `if bat_rows:` -- a sibling page must not vanish just because
            # the home-run board came up empty. It reuses `table` and
            # `hr_starters` fetched above rather than asking StatsAPI again;
            # mlb_api's process cache would answer a repeat request for free
            # anyway, but there is no reason to pretend to need one.
            if hits_mod:
                hit_hist = load_json(DATA / "hit_ratings.json",
                                     {"batters": []})["batters"]
                hit_settled = hits_mod.grade(hit_hist, table)
                hit_rows = hits_mod.build(hr_starters, _hcfg.SEASON)
                hit_added = projection.merge(hit_hist, hit_rows,
                                             ("batter_id", "commence_time"))
                hit_summary = hits_mod.summary(hit_hist)
                save_json(DATA / "hit_ratings.json", {"batters": hit_hist})
                if hit_rows:
                    save_json(DATA / "hits.json", {
                        "date": today,
                        "date_label": f"{now:%A, %B %-d, %Y}",
                        "batters": hit_rows,
                        "summary": hit_summary,
                    })
                    print(f"-- hits: {len(hit_rows)} rated, {hit_added} new, "
                          f"{hit_settled} graded")
        except Exception as e:                               # noqa: BLE001
            print(f"!! home-run board failed ({type(e).__name__}: {e})",
                  file=sys.stderr)

    # -------------------------------------------------- 3e. first seven
    # Built here as well as in run_boards, for the same reason every other
    # MLB board is: the boards job runs on :30 crons that GitHub drops on
    # busy days, and a board with only one path goes stale silently while
    # its siblings are rebuilt here and look current. That is exactly what
    # happened on 2026-09-21. Free -- StatsAPI only -- and idempotent: merge
    # never overwrites a published row and grade never re-grades one, so
    # running it from both jobs cannot double anything.
    if f7_mod and linescore and "baseball_mlb" in in_season:
        try:
            import screen_config as _fcfg
            import mlb_api as _fapi
            f7_starters = _fapi.probable_starters(now.strftime("%m/%d/%Y"))
            f7_data = f7_mod.inputs(_fcfg.SEASON)
            f7_hist = load_json(DATA / "f7_ratings.json", {"rows": []})["rows"]
            f7_settled = f7_mod.grade(f7_hist,
                                      linescore.by_club(f7_data["rows"]))
            f7_rows = f7_mod.build(f7_starters, _fcfg.SEASON, data=f7_data)
            f7_added = f7_mod.merge(f7_hist, f7_rows)
            f7_summary = f7_mod.summary(f7_hist, f7_data.get("league_f7"))
            save_json(DATA / "f7_ratings.json", {"rows": f7_hist})
            if f7_rows:
                save_json(DATA / "f7.json", {
                    "date": today,
                    "date_label": f"{now:%A, %B %-d, %Y}",
                    "rows": f7_rows,
                    "summary": f7_summary,
                })
                print(f"-- f7: {len(f7_rows)} club-game(s), {f7_added} new, "
                      f"{f7_settled} graded")
        except Exception as e:                               # noqa: BLE001
            print(f"!! f7 board failed ({type(e).__name__}: {e})",
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
            # boards have to go out.
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
            # going unrated is a worse board; an exception here is no board
            # at all, because nothing below this catches it.
            try:
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
                # The Elo above reads the whole store, because a rating
                # wants every game it can get. The RECORD does not: handed
                # three seasons it answered "25-9" for a club that is 1-0,
                # under a label saying Record. Head-to-head keeps the long
                # view -- two clubs that meet once a year have no season
                # series worth the name.
                season = form_store.since_season_start(stored, today)
                f = board_mod.merge_form(rows, season)
                if short == "nba":
                    try:
                        import nba_history                   # noqa: PLC0415
                        warn = nba_history.report(f, len(rows))
                        if warn:
                            print(warn, file=sys.stderr)
                    except Exception:                        # noqa: BLE001
                        pass
                # setdefault, not get: merge_form skips a row entirely when
                # a club has not played yet, so in the opening weeks there
                # is no detail block to hang this on -- and the head-to-head
                # is exactly what the board has to show in those weeks.
                h2h = 0
                for board_row in rows:
                    met = form_store.series(stored, board_row.get("home"),
                                            board_row.get("away"))
                    if met:
                        board_row.setdefault("detail", {})["series"] = met
                        h2h += 1
                print(f"-- h2h: {h2h} {short} card(s) carry previous "
                      f"meetings")

                # Store what we just published, so it can be graded later.
                # The MLB number has been scored since the slate was built;
                # every other league's has never been checked at all, which
                # is the one thing this site is not allowed to do.
                if board_ratings is not None:
                    fresh = board_ratings.record(rows, short)
                    n_new = board_ratings.merge(board_rated, fresh)
                    if n_new:
                        save_json(DATA / "board_ratings.json",
                                  {"ratings": board_rated})
                        print(f"-- ratings: stored {n_new} {short} "
                              f"probability(ies) to grade later")
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

    # ------------------------------------------------------- 4. credit report
    if not client.mock:
        left, used = client.credits_remaining, client.credits_used_this_run
        if left is not None:
            days = config.days_until_reset(now.date())
            pace = left / days if days else float(left)
            print(f"-- credits: {used} spent this run, {left} left, "
                  f"{days} day(s) to reset — {pace:.1f}/day available")
            record_credits(now.date().isoformat(), used, left, extra_credits)
            per_day, why = config.daily_reserve(credit_history(),
                                                len(in_season))
            print(f"   reserving {per_day}/day for the rest of the cycle ({why})")
            if used > pace:
                print(f"   !! this run cost more than the daily pace. At {used}/day "
                      f"the allowance runs out in {left // max(1, used)} day(s).")

    # ------------------------------------------------------------- 5. build
    _rebuild_pages()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
