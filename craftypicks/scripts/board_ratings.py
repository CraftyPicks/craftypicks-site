"""Score the win probabilities the non-MLB boards publish.

Why this exists
---------------
MLB's number is rated by slate.py and graded by it, so the record page can
say "Brier 0.2397 on 211 graded ratings (market 0.2375)" -- ours against the
market's, on the same games. Every other league's board publishes an Elo win
probability and nothing has ever checked it. That is the one habit this site
is built against: a claim nobody grades is a claim nobody can argue with.

It became urgent when the NFL board was seeded with three seasons of history.
Before that the Elo had almost nothing behind it and rarely appeared; now it
is on every card.

Free, on purpose
----------------
slate.grade settles against the Odds API's scores endpoint, which costs
credits. This settles against results_store -- the finished games the site
already keeps for its Elo, now filled from nflverse -- so grading a season of
NFL ratings costs nothing.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rate_mlb            # noqa: E402

# Kick-off is stored in UTC and a final is dated by whatever the results feed
# called that day. A Sunday night game starts 00:20 UTC on Monday, so the two
# legitimately differ by a day and matching on an exact date would grade
# nothing at all on the biggest slate of the week.
DAY_SLACK = 1


def _day(stamp: str) -> date | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(
            str(stamp).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(stamp)[:10])
        except ValueError:
            return None


def record(rows, league: str) -> list[dict]:
    """The publishable ratings on one league's board, as storable rows.

    Only rows that actually carry a probability. A board row with no model is
    a game we did not rate, and storing it as a zero would put a 0% call into
    the calibration.
    """
    out = []
    for row in rows or []:
        model = row.get("model") or {}
        prob = model.get("home_win_prob")
        if prob is None or not row.get("home") or not row.get("away"):
            continue
        out.append({
            "event_id": row.get("event_id"),
            "league": league,
            "home": row.get("home"),
            "away": row.get("away"),
            "commence_time": row.get("commence_time"),
            "home_win_prob": round(float(prob), 4),
            "market_home_prob": model.get("market_home_prob"),
            "source": model.get("source"),
            "result": None,
        })
    return out


def merge(history: list[dict], fresh: list[dict]) -> int:
    """Add ratings we have not stored. Never edits one already there.

    A rating is what we said before the game, so a second morning's version
    of the same fixture must not overwrite the first. That is the whole
    reason the number is worth grading.
    """
    seen = {(r.get("league"), r.get("event_id")) for r in history}
    added = 0
    for row in fresh:
        key = (row.get("league"), row.get("event_id"))
        if not row.get("event_id") or key in seen:
            continue
        seen.add(key)
        history.append(row)
        added += 1
    return added


def grade(history: list[dict], finals_by_league: dict) -> int:
    """Settle every ungraded rating we now have a final for. Free."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    graded = 0
    for row in history:
        if row.get("result"):
            continue
        finals = finals_by_league.get(row.get("league")) or []
        when = _day(row.get("commence_time"))
        for game in finals:
            if (game.get("home") != row.get("home")
                    or game.get("away") != row.get("away")):
                continue
            played = _day(game.get("date"))
            if when and played and abs((played - when).days) > DAY_SLACK:
                continue
            hs, as_ = game.get("home_score"), game.get("away_score")
            if hs is None or as_ is None or hs == as_:
                # A tie has no winner to score a probability against. The NFL
                # ties about twice a season; leaving it ungraded is right.
                break
            row["result"] = "home" if hs > as_ else "away"
            row["final"] = f"{as_}–{hs}"
            row["graded_at"] = now
            graded += 1
            break
    return graded


def summary(history: list[dict], league: str = "") -> dict:
    """Calibration and Brier, ours against the market's on the same games.

    Deliberately the same shape slate.summary returns, so the record page
    draws a league's calibration with the components it already has rather
    than growing a second set that means the same thing.
    """
    rows = [r for r in history if not league or r.get("league") == league]
    graded = [r for r in rows if r.get("result") in ("home", "away")]
    with_market = [r for r in graded
                   if r.get("market_home_prob") is not None]
    theirs = None
    if with_market:
        theirs = round(sum((r["market_home_prob"]
                            - (1.0 if r["result"] == "home" else 0.0)) ** 2
                           for r in with_market) / len(with_market), 4)
    return {
        "rated": len(rows),
        "graded": len(graded),
        "calibration": rate_mlb.calibration(graded),
        "brier": rate_mlb.brier(graded),
        "market_brier": theirs,
        "market_compared": len(with_market),
    }


def _self_test() -> None:
    board = [
        {"event_id": "e1", "home": "Buffalo Bills", "away": "Detroit Lions",
         "commence_time": "2026-09-14T00:20:00Z",
         "model": {"home_win_prob": 0.5923, "away_win_prob": 0.4077,
                   "market_home_prob": 0.57, "source": "elo"}},
        # No model: a game we did not rate. Storing it as 0% would put a call
        # we never made into the calibration.
        {"event_id": "e2", "home": "A", "away": "B", "model": None},
        {"event_id": "e3", "home": "C", "away": "D", "model": {}},
    ]
    fresh = record(board, "nfl")
    assert len(fresh) == 1, fresh
    assert fresh[0]["home_win_prob"] == 0.5923
    assert fresh[0]["result"] is None and fresh[0]["league"] == "nfl"

    history: list[dict] = []
    assert merge(history, fresh) == 1
    # A rating is what we said BEFORE the game. A second morning must not
    # overwrite it, or the number being graded is not the one published.
    assert merge(history, record(
        [dict(board[0], model={"home_win_prob": 0.80})], "nfl")) == 0
    assert history[0]["home_win_prob"] == 0.5923
    # The same fixture in another league is a different rating.
    assert merge(history, record(board, "nba")) == 1

    # --- grading, from the free results store -------------------------------
    # The Sunday night game kicks off 00:20 UTC on the Monday; the results
    # feed dates it the Sunday. Exact-date matching would grade nothing on
    # the biggest slate of the week.
    finals = {"nfl": [{"home": "Buffalo Bills", "away": "Detroit Lions",
                       "home_score": 24, "away_score": 20,
                       "date": "2026-09-13"}]}
    assert grade(history, finals) == 1
    assert history[0]["result"] == "home" and history[0]["final"] == "20–24"
    assert grade(history, finals) == 0, "grading twice is not two gradings"

    # A tie has no winner to score a probability against.
    tie = [dict(fresh[0], event_id="t1", result=None)]
    assert grade(tie, {"nfl": [{"home": "Buffalo Bills",
                                "away": "Detroit Lions", "home_score": 20,
                                "away_score": 20, "date": "2026-09-13"}]}) == 0
    assert tie[0].get("result") is None

    # A final three days later is a different week's fixture, not this one.
    late = [dict(fresh[0], event_id="l1", result=None)]
    assert grade(late, {"nfl": [{"home": "Buffalo Bills",
                                 "away": "Detroit Lions", "home_score": 24,
                                 "away_score": 20, "date": "2026-09-17"}]}) == 0

    # Reversed clubs is the return fixture, months away.
    back = [dict(fresh[0], event_id="b1", result=None)]
    assert grade(back, {"nfl": [{"home": "Detroit Lions",
                                 "away": "Buffalo Bills", "home_score": 24,
                                 "away_score": 20, "date": "2026-09-13"}]}) == 0

    # --- the summary ---------------------------------------------------------
    s = summary(history, "nfl")
    assert s["rated"] == 1 and s["graded"] == 1
    # We said 59.23% and the home side won: (1 - 0.5923)^2.
    assert abs(s["brier"] - round((1 - 0.5923) ** 2, 4)) < 1e-4, s["brier"]
    # The market said 57% on the same game, and is scored on the same games
    # only -- never on a wider set, which would flatter whichever had more.
    assert abs(s["market_brier"] - round((1 - 0.57) ** 2, 4)) < 1e-4
    assert s["market_compared"] == 1
    assert isinstance(s["calibration"], list) and s["calibration"]

    # An ungraded league summarises to zeros rather than raising.
    empty = summary(history, "ncaab")
    assert empty["rated"] == 0 and empty["graded"] == 0
    assert empty["brier"] is None and empty["market_brier"] is None

    print("board_ratings self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
