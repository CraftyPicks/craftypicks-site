"""Grade posted player props against the box score. Free.

Why this file exists
--------------------
grade.py grades a play by comparing two team scores, which is everything a
moneyline, a spread and a total need. A player prop needs a third number --
what the player actually did -- and grade.py had no way to get one, so
`grade_play` fell through to `return None` for any market it did not
recognise.

That was invisible while the card was mostly moneylines. It stopped being
invisible on 25 August 2026, after which every play the system posted was a
strikeout prop: twenty plays in the log, seven graded, and every single
ungraded one a prop. The public record had quietly stopped recording.

The number comes from the same free StatsAPI game log the pitchers board
already grades itself against -- no Odds API credits, no new dependency.
Plays posted from the screens now carry the pitcher's StatsAPI id, so they
need no lookup at all; the ones already in the log, and the ones the value
scanner finds off the odds feed, are resolved by name against that date's
probable starters.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config              # noqa: E402
import mlb_api             # noqa: E402
import odds_math as om     # noqa: E402

# market -> the StatsAPI game-log field that settles it. A market that is
# not in this table is not graded, and says so, rather than being guessed at
# from a similar-looking stat.
STAT_OF = {
    "pitcher_strikeouts": "strikeOuts",
    "pitcher_outs": "outs",
    "pitcher_hits_allowed": "hits",
    "pitcher_earned_runs": "earnedRuns",
    "pitcher_walks": "baseOnBalls",
}


def side_of(play: dict) -> str | None:
    """'over' or 'under', read from the side rather than assumed.

    The two sources write the side differently -- the screens produce
    "Freddy Peralta Over", the odds scanner "Freddy Peralta Over 4.5" -- so
    this looks for the word rather than for a position in the string.
    """
    words = str(play.get("side") or "").lower().split()
    for w in reversed(words):
        if w in ("over", "under"):
            return w
    return None


def grade_prop(play: dict, actual: float | None) -> str | None:
    """'win' | 'loss' | 'push', or None when it cannot be settled yet.

    A push is a real outcome here in a way it is not for a strikeout line at
    4.5: books do post whole numbers, and returning "loss" on an exact
    landing would quietly understate the record.
    """
    if actual is None:
        return None
    if play.get("market") not in STAT_OF:
        return None
    side = side_of(play)
    point = play.get("point")
    if side is None or point is None:
        return None
    actual, point = float(actual), float(point)
    if actual == point:
        return "push"
    return "win" if ((actual > point) == (side == "over")) else "loss"


def game_date(play: dict) -> str | None:
    """The local calendar date the game was played on."""
    commence = play.get("commence_time")
    if not commence:
        return None
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(str(commence).replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat()
    except Exception:                                        # noqa: BLE001
        return None


def _norm(name: str) -> str:
    """Names for matching only. The book writes 'Freddy Peralta'; StatsAPI
    agrees often enough that a fold of case and punctuation closes the gap,
    and a name that still does not match is left ungraded rather than
    matched to the wrong pitcher."""
    keep = [c for c in str(name).lower() if c.isalnum() or c == " "]
    return " ".join("".join(keep).split())


def player_id_for(play: dict, starters_on) -> int | None:
    """The play's own id if it has one, else that date's probable starters."""
    if play.get("player_id"):
        return int(play["player_id"])
    date = game_date(play)
    player = play.get("player")
    if not date or not player:
        return None
    index = starters_on(date)
    return index.get(_norm(player))


def starters_index(date: str) -> dict[str, int]:
    """name -> pitcher id, for one ISO date.

    One StatsAPI call, no key, no cost. Note the conversion: probable_starters
    takes MM/DD/YYYY, not ISO, and handing it an ISO date returns an empty
    schedule rather than an error -- which would have looked exactly like a
    day with no games and left every play on it silently ungraded.
    """
    us = datetime.strptime(date, "%Y-%m-%d").strftime("%m/%d/%Y")
    out = {}
    for s in mlb_api.probable_starters(us):
        if s.get("name") and s.get("pitcher_id"):
            out[_norm(s["name"])] = int(s["pitcher_id"])
    return out


def actual_for(play: dict, pid: int, season: int, game_log=None) -> float | None:
    """What the player did in that game, from his season log."""
    field = STAT_OF.get(play.get("market"))
    date = game_date(play)
    if not field or not date:
        return None
    log = (game_log or mlb_api.season_game_log)(pid, season)
    for sp in log:
        if str(sp.get("date")) != date:
            continue
        stat = sp.get("stat") or {}
        if field not in stat:
            return None
        try:
            return float(stat[field])
        except (TypeError, ValueError):
            return None
    return None


def pending(history: list[dict], now: str | None = None) -> list[dict]:
    """Prop plays with no result whose game has already started."""
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return [p for p in history
            if not p.get("result")
            and p.get("market") in STAT_OF
            and (p.get("commence_time") or "") < now]


def grade_pending(history: list[dict], season: int, verbose: bool = True,
                  starters_on=None, game_log=None) -> int:
    """Fill in results on every pending prop we can now settle.

    Both lookups are memoised per run: one call per date for the starter
    index, one per pitcher-season for the log, however many plays share
    them. Nothing here edits a price or removes a play -- a play that was
    posted is graded exactly as posted, which is the whole value of a
    public log.
    """
    todo = pending(history)
    if not todo:
        return 0

    date_cache: dict[str, dict] = {}
    log_cache: dict[tuple, list] = {}

    def starters(date):
        if date not in date_cache:
            try:
                date_cache[date] = (starters_on or starters_index)(date)
            except Exception as e:                           # noqa: BLE001
                if verbose:
                    print(f"!! props: starters for {date} failed ({e})",
                          file=sys.stderr)
                date_cache[date] = {}
        return date_cache[date]

    def log(pid):
        key = (pid, season)
        if key not in log_cache:
            try:
                log_cache[key] = (game_log or mlb_api.season_game_log)(pid, season)
            except Exception as e:                           # noqa: BLE001
                if verbose:
                    print(f"!! props: game log for {pid} failed ({e})",
                          file=sys.stderr)
                log_cache[key] = []
        return log_cache[key]

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    graded = 0
    unresolved = []
    for play in todo:
        pid = player_id_for(play, starters)
        if not pid:
            unresolved.append(play.get("player") or play.get("side"))
            continue
        # Remember it, so a play resolved by name today is resolved by id
        # for the rest of its life in the log.
        play["player_id"] = int(pid)
        actual = actual_for(play, pid, season, game_log=lambda p, s: log(p))
        result = grade_prop(play, actual)
        if not result:
            continue
        play["result"] = result
        play["profit"] = om.profit_units(play["price"],
                                         play.get("stake", 1.0), result)
        play["graded_at"] = now
        play["actual"] = actual
        play["final_score"] = f"{play.get('player')} {om._trim(actual)}"
        graded += 1

    if verbose:
        still = sum(1 for p in pending(history))
        print(f"-- props: graded {graded}; {still} still pending")
        if unresolved:
            print(f"   could not identify: {', '.join(sorted(set(unresolved))[:6])}")
    return graded


def _self_test() -> None:
    # --- the bug this file exists for ---------------------------------------
    # grade.py returns None for a prop market. If that ever stops being true
    # this module is redundant; until then, it is the whole reason it is here.
    import grade
    prop = {"market": "pitcher_strikeouts", "side": "Freddy Peralta Over",
            "point": 4.5, "home_team": "A", "away_team": "B", "price": -111}
    assert grade.grade_play(prop, {"completed": True,
                                   "scores": {"A": 3, "B": 1}}) is None

    # --- settling ------------------------------------------------------------
    assert grade_prop(prop, 6) == "win"
    assert grade_prop(prop, 4) == "loss"
    assert grade_prop(prop, None) is None, "a game not yet played is not a loss"
    under = dict(prop, side="Freddy Peralta Under")
    assert grade_prop(under, 4) == "win"
    assert grade_prop(under, 6) == "loss"
    # Books post whole numbers. Calling an exact landing a loss would
    # understate the record by a play every time it happened.
    whole = dict(prop, point=5.0)
    assert grade_prop(whole, 5) == "push"
    assert grade_prop(dict(whole, side="Under"), 5) == "push"
    # A market with no stat behind it is not guessed at.
    assert grade_prop(dict(prop, market="player_pass_tds"), 3) is None
    # Both sources write the side differently; both must read.
    assert side_of({"side": "Shane McClanahan Over 4.5"}) == "over"
    assert side_of({"side": "Tyler Glasnow Over"}) == "over"
    assert side_of({"side": "Boston Red Sox"}) is None

    # --- the date format probable_starters actually takes --------------------
    # It is MM/DD/YYYY, and an ISO date comes back as an empty schedule rather
    # than as an error: the failure would have looked like a day with no
    # games and left every play on it ungraded forever.
    seen = []
    _real = mlb_api.probable_starters
    mlb_api.probable_starters = lambda d: seen.append(d) or []
    try:
        starters_index("2026-09-08")
    finally:
        mlb_api.probable_starters = _real
    assert seen == ["09/08/2026"], seen

    # --- resolution ----------------------------------------------------------
    LOG = [{"date": "2026-09-08", "stat": {"strikeOuts": 7, "gamesStarted": 1}}]
    def fake_log(pid, season):
        return LOG if pid == 99 else []
    def fake_starters(date):
        return {"freddy peralta": 99} if date == "2026-09-08" else {}

    play = {"market": "pitcher_strikeouts", "side": "Freddy Peralta Over",
            "player": "Freddy Peralta", "point": 4.5, "price": -111,
            "stake": 1.0, "commence_time": "2026-09-08T23:16:00Z"}
    hist = [dict(play)]
    n = grade_pending(hist, 2026, verbose=False,
                      starters_on=fake_starters, game_log=fake_log)
    assert n == 1, hist
    assert hist[0]["result"] == "win" and hist[0]["actual"] == 7.0
    # Resolved once, remembered for good: the name lookup costs a request and
    # is the part most likely to break as a name is spelled differently.
    assert hist[0]["player_id"] == 99
    assert hist[0]["profit"] > 0

    # A play whose game has not started is not touched, and does not send us
    # looking for a box score that cannot exist.
    future = dict(play, commence_time="2099-01-01T00:00:00Z")
    assert pending([future]) == []

    # An already-graded play is never regraded -- a posted play is graded as
    # posted, once.
    done = dict(play, result="loss")
    assert pending([done]) == []

    # A name that does not match is left alone rather than matched to
    # whoever happens to be pitching that day.
    stranger = [dict(play, player="Nobody At All")]
    assert grade_pending(stranger, 2026, verbose=False,
                         starters_on=fake_starters, game_log=fake_log) == 0
    assert "result" not in stranger[0]

    print("grade_props self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
