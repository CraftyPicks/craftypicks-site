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


# Every league that uses this store -- NFL, NBA, college basketball -- opens
# its season somewhere between August and November, so the first of July is
# the one date that separates "this season" from "last" for all three. MLB
# does not come through here; its records come from StatsAPI's standings.
SEASON_START_MONTH = 7


def since_season_start(games, today: str = "") -> list[dict]:
    """Only this season's games, for a record that means what it says.

    The store deliberately holds several seasons: an Elo rating needs the
    history, and so does a head-to-head between clubs that meet once a year.
    A club's RECORD does not. Handed the lot, form_store.table() answered
    "25-9" for a team that is 1-0, on a card whose label says Record -- a
    true number to a question nobody asked.
    """
    from datetime import date

    if today:
        try:
            now = date.fromisoformat(today[:10])
        except ValueError:
            now = date.today()
    else:
        now = date.today()
    start_year = now.year if now.month >= SEASON_START_MONTH else now.year - 1
    cutoff = f"{start_year:04d}-{SEASON_START_MONTH:02d}-01"
    return [g for g in (games or []) if (g.get("date") or "") >= cutoff]


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

    # --- this season only, for the record ----------------------------------
    seasons = [{"date": "2024-12-15", "home": "A", "away": "B",
                "home_score": 1, "away_score": 0, "completed": True},
               {"date": "2025-11-02", "home": "A", "away": "B",
                "home_score": 1, "away_score": 0, "completed": True},
               {"date": "2026-09-10", "home": "A", "away": "B",
                "home_score": 1, "away_score": 0, "completed": True}]
    # Mid-season: everything back to the July before. It is a cutoff, not a
    # window -- there is nothing after today in a store of finished games.
    assert [g["date"] for g in since_season_start(seasons, "2026-09-11")] \
        == ["2026-09-10"]
    assert [g["date"] for g in since_season_start(seasons, "2025-12-25")] \
        == ["2025-11-02", "2026-09-10"]
    # Before July, the season that began in the PREVIOUS calendar year is
    # still the current one -- a January playoff game belongs to it, and the
    # autumn before it is the same season, not the last one.
    winter = [{"date": "2024-12-15", "home": "A", "away": "B",
               "home_score": 1, "away_score": 0, "completed": True},
              {"date": "2025-11-02", "home": "A", "away": "B",
               "home_score": 1, "away_score": 0, "completed": True},
              {"date": "2026-01-10", "home": "A", "away": "B",
               "home_score": 2, "away_score": 1, "completed": True}]
    assert [g["date"] for g in since_season_start(winter, "2026-02-01")] \
        == ["2025-11-02", "2026-01-10"]
    assert since_season_start([], "2026-09-11") == []
    assert since_season_start(seasons, "not a date"), "a bad date is not fatal"

    # The point of the whole thing: one season in, not three.
    assert table(since_season_start(seasons, "2026-09-11"))["A"]["w"] == 1
    assert table(seasons)["A"]["w"] == 3
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
