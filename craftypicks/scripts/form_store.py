"""Record, streak, last ten and head to head, from finals we already stored.

MLB gets these from statsapi.mlb.com, which is free, complete from opening
day, and needs nothing from us. No other league here has an equivalent:
ESPN's scoreboard answers a GitHub runner with 403 Forbidden, and the paid
scores endpoint reaches back three days, not a season.

So the other three leagues compute the same three numbers from
data/results/<league>.json, which the daily job fills in as games finish. That
costs nothing extra and depends on no outside party staying friendly.

What it cannot do is know anything before we started storing. A league's first
morning has no streak and no series, and its last ten means nothing until a
club has played ten. That is a real limitation, not a bug, and the card is
built to show nothing rather than a number built on two games.

Keyed on club name rather than id, because the scores feed and the board rows
both speak names and inventing an id mapping would add a way to be wrong.
"""
from __future__ import annotations

LAST_N = 10


def _finals(games) -> list[dict]:
    """Completed games only, oldest first."""
    done = [g for g in (games or []) if g.get("completed")
            and g.get("home") and g.get("away")]
    done.sort(key=lambda g: g.get("date") or "")
    return done


def _won(game: dict, team: str) -> bool | None:
    """True if `team` won, False if it lost, None if it did not play.

    A tie returns False for both clubs. The NFL ties about twice a season and
    neither side may be credited with a win for it.
    """
    home, away = game.get("home"), game.get("away")
    hs, as_ = game.get("home_score"), game.get("away_score")
    if hs is None or as_ is None:
        return None
    if team == home:
        return hs > as_
    if team == away:
        return as_ > hs
    return None


def table(games) -> dict[str, dict]:
    """Club name -> record, streak and last ten.

    Same shape as mlb_api.parse_standings so the renderer has one code path
    and never has to know which league it is drawing.
    """
    done = _finals(games)
    results: dict[str, list[bool]] = {}
    for game in done:
        for team in (game.get("away"), game.get("home")):
            outcome = _won(game, team)
            if outcome is not None:
                results.setdefault(team, []).append(outcome)

    out = {}
    for team, seq in results.items():
        wins = sum(1 for w in seq if w)
        last = seq[-LAST_N:]
        # The streak runs backwards from the most recent game until the
        # result flips.
        run = 0
        for w in reversed(seq):
            if w != seq[-1]:
                break
            run += 1
        out[team] = {
            "w": wins,
            "l": len(seq) - wins,
            "streak": f'{"W" if seq[-1] else "L"}{run}',
            "l10_w": sum(1 for w in last if w),
            "l10_l": sum(1 for w in last if not w),
        }
    return out


def series(games, a: str, b: str) -> list[dict]:
    """Every stored meeting between two clubs, oldest first.

    Returns the shape mlb_api.parse_series is converted into: keyed on names,
    so the renderer treats "who won" the same way for every league.
    """
    pair = {a, b}
    out = []
    for game in _finals(games):
        if {game.get("home"), game.get("away")} != pair:
            continue
        out.append({
            "date": game.get("date") or "",
            "away": game.get("away"),
            "away_runs": int(game.get("away_score") or 0),
            "home": game.get("home"),
            "home_runs": int(game.get("home_score") or 0),
        })
    return out


def _self_test() -> None:
    games = [
        {"date": "2026-09-06", "away": "Chicago Bears", "away_score": 10,
         "home": "Green Bay Packers", "home_score": 24, "completed": True},
        {"date": "2026-09-13", "away": "Green Bay Packers", "away_score": 13,
         "home": "Chicago Bears", "home_score": 20, "completed": True},
        {"date": "2026-09-20", "away": "Chicago Bears", "away_score": 27,
         "home": "Detroit Lions", "home_score": 17, "completed": True},
        {"date": "2026-09-27", "away": "Detroit Lions", "away_score": 14,
         "home": "Chicago Bears", "home_score": 21, "completed": True},
        # Not final: ignored entirely, not counted as a loss.
        {"date": "2026-10-04", "away": "Chicago Bears", "away_score": 0,
         "home": "Green Bay Packers", "home_score": 0, "completed": False},
    ]
    t = table(games)
    assert t["Chicago Bears"] == {"w": 3, "l": 1, "streak": "W3",
                                  "l10_w": 3, "l10_l": 1}, t["Chicago Bears"]
    assert t["Green Bay Packers"]["streak"] == "L1", t["Green Bay Packers"]
    assert t["Detroit Lions"] == {"w": 0, "l": 2, "streak": "L2",
                                  "l10_w": 0, "l10_l": 2}, t["Detroit Lions"]

    many = [{"date": f"2026-01-{d:02d}", "away": "A", "away_score": 1,
             "home": "B", "home_score": 0, "completed": True}
            for d in range(1, 13)]
    assert table(many)["A"]["w"] == 12
    assert table(many)["A"]["l10_w"] == 10, "last ten is ten, not all of them"

    # A tie credits nobody with a win.
    tied = [{"date": "2026-11-01", "away": "A", "away_score": 3,
             "home": "B", "home_score": 3, "completed": True}]
    tt = table(tied)
    assert tt["A"]["w"] == 0 and tt["B"]["w"] == 0, tt

    ser = series(games, "Chicago Bears", "Green Bay Packers")
    assert [g["date"] for g in ser] == ["2026-09-06", "2026-09-13"], ser
    assert ser[0]["home"] == "Green Bay Packers" and ser[0]["home_runs"] == 24
    assert series(games, "Chicago Bears", "Nobody FC") == []

    # An empty store is empty, not an exception. This is the state every
    # league is in on the first morning after the scores fix lands.
    assert table([]) == {} and series([], "A", "B") == []
    print("form_store self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
