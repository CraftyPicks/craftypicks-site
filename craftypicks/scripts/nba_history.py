"""Completed NBA games, for the board's records, head-to-head and rating.

The same fix the NFL board needed, from the same kind of file. board.py's
merge_form() and elo_model() are sport-agnostic and already wired for every
league; they read results_store, and `data/results/` has never held a single
NBA game. Seeding it from the published schedule -- which carries the score
of every finished game -- gives the NBA board a record and a head-to-head
from its first night instead of some time in January.

The name problem, and how it is handled
---------------------------------------
results_store is keyed by club NAME, because that is what the odds feed
writes on a board row. ESPN's schedule uses its own spelling. I checked all
of them against this site's own archived odds payloads: 27 of the 30 appear
there and every one matches ESPN exactly.

The three that never appeared -- the Clippers, the Kings and the Raptors --
could not be verified. Two are unambiguous. The Clippers are not: ESPN says
"LA Clippers" and most feeds say "Los Angeles Clippers". Both spellings are
therefore aliases of one club here, and `report(matched, total)` exists so
that a mismatch shows up as a line in the log rather than as a board that
quietly has no records on it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import nba_data            # noqa: E402

# Abbreviation -> the name a board row carries. Verified against archived
# odds payloads for every club except the three noted above.
TEAM_NAMES = {
    "ATL": "Atlanta Hawks",          "BKN": "Brooklyn Nets",
    "BOS": "Boston Celtics",         "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",          "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",       "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",        "GS": "Golden State Warriors",
    "HOU": "Houston Rockets",        "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers",   "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",      "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",        "MIN": "Minnesota Timberwolves",
    "NO": "New Orleans Pelicans",    "NY": "New York Knicks",
    "OKC": "Oklahoma City Thunder",  "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",     "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SA": "San Antonio Spurs",
    "SAC": "Sacramento Kings",       "TOR": "Toronto Raptors",
    "UTAH": "Utah Jazz",             "WSH": "Washington Wizards",
}

# One club, two spellings in the wild. Normalised so a stored final and a
# board row agree whichever the feed sends.
ALIASES = {
    "la clippers": "Los Angeles Clippers",
    "los angeles clippers": "Los Angeles Clippers",
}


def club(abbr: str) -> str | None:
    return TEAM_NAMES.get((abbr or "").strip().upper())


def canonical(name: str) -> str:
    """One spelling per club, so two sources can be compared."""
    return ALIASES.get((name or "").strip().lower(), (name or "").strip())


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def finals(schedule, seasons: int = 2) -> list[dict]:
    """Finished regular-season games, in results_store's shape.

    Two seasons, not three: 82 games a year means two is already 2,400
    results, and this file is committed on every run.
    """
    done = []
    for g in schedule or []:
        if not g.get("completed"):
            continue
        home, away = club(g.get("home")), club(g.get("away"))
        hs, as_ = _int(g.get("home_score")), _int(g.get("away_score"))
        if not home or not away or hs is None or as_ is None:
            continue
        done.append({"home": home, "away": away, "home_score": hs,
                     "away_score": as_, "completed": True,
                     "date": g.get("date", "")})
    done.sort(key=lambda g: g["date"])
    if not done or seasons <= 0:
        return done
    # Seasons run October to April, so "the last N" is counted from the
    # October before the most recent game rather than by calendar year.
    latest = done[-1]["date"]
    start_year = int(latest[:4]) - (0 if int(latest[5:7]) >= 10 else 1)
    cutoff = f"{start_year - (seasons - 1):04d}-10-01"
    return [g for g in done if g["date"] >= cutoff]


def report(matched: int, total: int) -> str:
    """What to print when the board and the store disagree about a name.

    Silence is the failure mode this guards against: an unmatched club shows
    up as a card with no record, which looks like a young season rather than
    a spelling mismatch, and stays that way all year.
    """
    if total and not matched:
        return ("!! nba: no card matched a stored club. The odds feed and "
                "ESPN may spell a club differently -- check nba_history."
                "TEAM_NAMES against the names on today's board.")
    return ""


def _self_test() -> None:
    sched = [
        {"home": "SA", "away": "NY", "home_score": "90", "away_score": "94",
         "completed": True, "date": "2026-04-10"},
        {"home": "LAC", "away": "SAC", "home_score": "112",
         "away_score": "108", "completed": True, "date": "2025-11-02"},
        # Not played yet.
        {"home": "SA", "away": "OKC", "home_score": "", "away_score": "",
         "completed": False, "date": "2026-10-20"},
        # A club the map does not know is dropped, not invented.
        {"home": "STARS", "away": "STRIPES", "home_score": "150",
         "away_score": "140", "completed": True, "date": "2026-02-15"},
    ]
    got = finals(sched)
    assert len(got) == 2, got
    assert got[0]["date"] == "2025-11-02", "oldest first"
    assert got[-1] == {"home": "San Antonio Spurs", "away": "New York Knicks",
                       "home_score": 90, "away_score": 94, "completed": True,
                       "date": "2026-04-10"}
    # results_store must be able to hold it without translation.
    import results_store
    assert results_store.merge([], got) == sorted(
        got, key=lambda r: (r["date"], r["home"]))

    # The season window counts from October, not from January: a game in
    # April 2026 belongs to the season that began in October 2025.
    old = dict(sched[0], date="2024-11-05")
    assert len(finals(sched + [old], seasons=1)) == 2, \
        "one season keeps 2025-10 onward"
    assert len(finals(sched + [old], seasons=2)) == 3

    # The Clippers, spelled either way, are one club.
    assert canonical("LA Clippers") == "Los Angeles Clippers"
    assert canonical("Los Angeles Clippers") == "Los Angeles Clippers"
    assert canonical("Boston Celtics") == "Boston Celtics"
    assert canonical("") == "" and canonical(None) == ""
    assert club("lac") == "Los Angeles Clippers"
    assert club("XXX") is None
    assert len(TEAM_NAMES) == 30 and len(set(TEAM_NAMES.values())) == 30

    # Every club the box scores know has a name here, or a board row for it
    # would silently have no record.
    assert set(TEAM_NAMES) == set(nba_data.CLUBS), \
        sorted(set(nba_data.CLUBS) ^ set(TEAM_NAMES))

    # The diagnostic speaks only when everything failed to match.
    assert report(0, 8).startswith("!!")
    assert report(8, 8) == "" and report(0, 0) == ""

    print("nba_history self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
