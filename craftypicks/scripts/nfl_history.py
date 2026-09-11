"""Every completed NFL game since 1999, from the file we already download.

Why this exists
---------------
The NFL game board carries no records, no head-to-head and no rating, while
the MLB board carries all three. That is not a rendering gap: board.py's
merge_form() and elo_model() are sport-agnostic and already wired for every
league, but they read the finals this project has collected for itself, and
`data/results/` held exactly one NFL game -- because the season started on
Thursday. Left alone the board would fill in over about ten weeks.

nflverse publishes all of it. `parse_schedule()` in nfl_data.py has been
downloading the same 2 MB games.csv every run since the yardage boards were
built, and keeping 6 of its 46 columns. The finished games in it are the
history the board was waiting to accumulate.

Sign convention, stated because it is a trap
--------------------------------------------
games.csv writes `spread_line` as POSITIVE when the HOME team is favoured,
which is the opposite of every sportsbook. Nothing here exposes it without
flipping it first; `line_for_home()` is the only place it is read.
"""
from __future__ import annotations

# nflverse abbreviation -> the club name the odds feed uses. The three
# relocations map to the current franchise on purpose: a Raiders-Chiefs
# head-to-head that stops in 2019 because the club moved is a worse answer
# than one that continues.
TEAM_NAMES = {
    "ARI": "Arizona Cardinals",      "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",       "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",      "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",     "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",         "DEN": "Denver Broncos",
    "DET": "Detroit Lions",          "GB": "Green Bay Packers",
    "HOU": "Houston Texans",         "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",   "KC": "Kansas City Chiefs",
    "LA": "Los Angeles Rams",        "LAC": "Los Angeles Chargers",
    "LV": "Las Vegas Raiders",       "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",      "NE": "New England Patriots",
    "NO": "New Orleans Saints",      "NYG": "New York Giants",
    "NYJ": "New York Jets",          "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",     "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",       "WAS": "Washington Commanders",
    # Relocated. Same franchise, earlier city.
    "OAK": "Las Vegas Raiders",      "SD": "Los Angeles Chargers",
    "STL": "Los Angeles Rams",
    # Spellings other feeds use for clubs already above.
    "LAR": "Los Angeles Rams",       "WSH": "Washington Commanders",
}


def club(abbr: str) -> str | None:
    return TEAM_NAMES.get((abbr or "").strip().upper())


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def finals(rows, seasons: int = 3) -> list[dict]:
    """Completed regular-season games, in results_store's shape.

    `seasons` bounds how far back to go. Three is enough for a record, a
    head-to-head and an Elo that has settled, and keeps data/results/nfl.json
    to a few hundred rows rather than seven thousand -- it is committed on
    every run, so its size is churn, not just disk.
    """
    done = [r for r in rows or []
            if (r.get("game_type") or "").strip().upper() == "REG"
            and _int(r.get("home_score")) is not None
            and _int(r.get("away_score")) is not None]
    if not done:
        return []
    latest = max(_int(r.get("season")) or 0 for r in done)
    out = []
    for r in done:
        season = _int(r.get("season")) or 0
        if season < latest - (seasons - 1):
            continue
        home, away = club(r.get("home_team")), club(r.get("away_team"))
        if not home or not away:
            continue
        out.append({
            "home": home, "away": away,
            "home_score": _int(r.get("home_score")),
            "away_score": _int(r.get("away_score")),
            "completed": True,
            "date": (r.get("gameday") or "").strip(),
        })
    out.sort(key=lambda g: g["date"])
    return out


def line_for_home(row) -> float | None:
    """The home team's spread the way a book writes it.

    games.csv states it positive-when-home-is-favoured. Every sportsbook
    writes the favourite as a negative number, so it is flipped here, once,
    and read nowhere else.
    """
    try:
        return -float(row.get("spread_line"))
    except (TypeError, ValueError):
        return None


def context(rows) -> dict[tuple, dict]:
    """{(date, away club, home club): the things only games.csv knows}.

    Rest days, whether it is a division game, the roof and the surface. None
    of it is in the odds feed and all of it is already downloaded.
    """
    out = {}
    for r in rows or []:
        home, away = club(r.get("home_team")), club(r.get("away_team"))
        day = (r.get("gameday") or "").strip()
        if not (home and away and day):
            continue
        out[(day, away, home)] = {
            "away_rest": _int(r.get("away_rest")),
            "home_rest": _int(r.get("home_rest")),
            "division": (r.get("div_game") or "").strip() in ("1", "1.0"),
            "roof": (r.get("roof") or "").strip(),
            "surface": (r.get("surface") or "").strip(),
            "stadium": (r.get("stadium") or "").strip(),
            "spread_line": line_for_home(r),
            "total_line": (lambda v: float(v) if v else None)(
                (r.get("total_line") or "").strip()),
        }
    return out


def _self_test() -> None:
    rows = [
        {"season": "2026", "game_type": "REG", "week": "1",
         "gameday": "2026-09-10", "away_team": "NE", "home_team": "SEA",
         "away_score": "10", "home_score": "13", "away_rest": "7",
         "home_rest": "7", "div_game": "0", "roof": "outdoors",
         "surface": "fieldturf", "stadium": "Lumen Field",
         "spread_line": "3", "total_line": "44.5"},
        {"season": "2026", "game_type": "REG", "week": "2",
         "gameday": "2026-09-17", "away_team": "DET", "home_team": "BUF",
         "away_score": "", "home_score": "", "spread_line": "3",
         "total_line": "51.5", "div_game": "0", "roof": "outdoors",
         "surface": "a_turf", "away_rest": "7", "home_rest": "7"},
        {"season": "2026", "game_type": "POST", "week": "19",
         "gameday": "2026-01-10", "away_team": "KC", "home_team": "BUF",
         "away_score": "20", "home_score": "24"},
        {"season": "2018", "game_type": "REG", "week": "3",
         "gameday": "2018-09-23", "away_team": "OAK", "home_team": "STL",
         "away_score": "13", "home_score": "27"},
    ]

    got = finals(rows)
    # One completed regular-season game in range. The unplayed week 2 game,
    # the playoff game and the 2018 game are all out for different reasons.
    assert len(got) == 1, got
    assert got[0] == {"home": "Seattle Seahawks",
                      "away": "New England Patriots",
                      "home_score": 13, "away_score": 10,
                      "completed": True, "date": "2026-09-10"}, got[0]
    # This is exactly the shape results_store already holds, so the Elo and
    # the form table need no new code path.
    import results_store
    assert results_store.merge([], got) == got

    # Relocations keep their franchise's history.
    old = finals(rows, seasons=20)
    assert any(g["home"] == "Los Angeles Rams"
               and g["away"] == "Las Vegas Raiders" for g in old), old

    # The sign trap. games.csv says +3 for a home favourite; a book says -3,
    # and a board that prints the raw column has every NFL number backwards.
    assert line_for_home(rows[0]) == -3.0
    assert line_for_home({"spread_line": "-2.5"}) == 2.5
    assert line_for_home({}) is None

    ctx = context(rows)[("2026-09-10", "New England Patriots",
                         "Seattle Seahawks")]
    assert ctx["away_rest"] == 7 and ctx["division"] is False
    assert ctx["roof"] == "outdoors" and ctx["surface"] == "fieldturf"
    assert ctx["spread_line"] == -3.0 and ctx["total_line"] == 44.5
    assert context([{"home_team": "NE"}]) == {}, "no date, no context"

    # A club the map does not know is dropped rather than guessed at, which
    # is what keeps a 33rd abbreviation from silently becoming a phantom
    # franchise with its own record.
    assert finals([dict(rows[0], home_team="XXX")]) == []
    assert club("xxx") is None and club("") is None
    assert club(" sea ") == "Seattle Seahawks"

    print("nfl_history self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
