"""NBA box scores from sportsdataverse's free release files.

Why not stats.nba.com
---------------------
It blocks datacenter IPs. nba_api's own issue tracker has years of "works on
my laptop, ConnectionResetError on EC2", labelled a third-party problem by
its maintainers, and every workaround ends at a residential proxy -- which
costs money and would put a paid dependency in the middle of a free site.

sportsdataverse publishes the same ESPN data as GitHub release assets. That
is the identical mechanism nflverse uses and the NFL boards have relied on
since they were built: a public CDN, no key, no rate limit, and no reason for
an Actions runner to be treated differently from anyone else.

Verified rather than assumed
----------------------------
Every claim below was checked against the real file before this was written:

    player_box_2026.csv   200 OK   16.9 MB   34,883 rows   57 columns
    28,801 stat lines · 583 players · 1,326 games
    2025-10-21 -> 2026-06-13   season_type 2/3/5 = regular/playoffs/play-in

Two traps found that way, both of which would have shipped silently:

  * `did_not_play` is the STRING "true"/"false", lower case. Comparing it to
    "False" matched nothing, and the first version of this parser returned an
    empty board rather than an error.
  * The season is labelled by its ENDING year. `player_box_2026.csv` is the
    2025-26 season, so the season starting in October 2026 is 2027. Reading
    that as a calendar year would fetch last season's file all year.

The .csv is 16.9 MB and there is no .csv.gz; the .parquet is 0.6 MB but
reading it needs a dependency, and this repo installs nothing. Bandwidth is
cheaper than the zero-dependency property.
"""
from __future__ import annotations

import csv
import io
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

RELEASE = ("https://github.com/sportsdataverse/sportsdataverse-data/"
           "releases/download")
PLAYER_BOX = RELEASE + "/espn_nba_player_boxscores/player_box_{season}.csv"

# The three stats the board projects, and the column each lives in.
FIELDS = {"points": "points", "assists": "assists", "rebounds": "rebounds"}

# ESPN's season types. 2 is the regular season; 3 is the playoffs and 5 the
# play-in. A projection built for a regular-season game should not be trained
# on a seven-game series where rotations shorten to eight men.
REGULAR = "2"

# The thirty clubs, as ESPN abbreviates them. The filter is not paranoia: the
# All-Star Game is dated inside the regular season AND carries season_type 2,
# and it fields teams called STARS, STRIPES and WORLD. Left in, they became
# clubs in the defence table -- "STARS allow 32.7 points a game" -- and put
# an exhibition line into every participating star's average.
CLUBS = frozenset((
    "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GS",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NO", "NY",
    "OKC", "ORL", "PHI", "PHX", "POR", "SA", "SAC", "TOR", "UTAH", "WSH",
))

_cache: dict = {}


def season_for(today: str) -> int:
    """The season label covering `today` (ISO date).

    The file is named for the season's ENDING year, so a game played in
    October 2026 is in player_box_2027.csv. October is the cut: anything from
    the 1st of October belongs to the season that ends the following summer.
    """
    year, month = int(today[:4]), int(today[5:7])
    return year + 1 if month >= 10 else year


def fetch(season: int, timeout: int = 120) -> list[dict]:
    """One season's player box scores. Cached per season for the run."""
    if season in _cache:
        return _cache[season]
    url = PLAYER_BOX.format(season=season)
    req = urllib.request.Request(
        url, headers={"User-Agent": "craftypicks/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        # Said out loud, then swallowed: an empty board is better than a
        # daily run that dies, and silence would make this look like a night
        # with no games.
        print(f"!! nba: {url} failed ({type(e).__name__}: {e})",
              file=sys.stderr)
        _cache[season] = []
        return []
    rows = parse(list(csv.DictReader(io.StringIO(text))))
    _cache[season] = rows
    return rows


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse(rows, regular_only: bool = True) -> list[dict]:
    """Every line a player actually played, oldest first.

    A did-not-play row carries empty strings rather than zeros, and counting
    those as zero-point games would drag every average toward nothing and
    make an injured star look cold rather than absent.
    """
    out = []
    for r in rows or []:
        if str(r.get("did_not_play", "")).strip().lower() != "false":
            continue
        if regular_only and str(r.get("season_type", "")).strip() != REGULAR:
            continue
        line = {"player_id": str(r.get("athlete_id") or "").strip(),
                "name": (r.get("athlete_display_name") or "").strip(),
                "team": (r.get("team_abbreviation") or "").strip(),
                "opponent": (r.get("opponent_team_abbreviation") or "").strip(),
                "date": (r.get("game_date") or "").strip(),
                "game_id": (r.get("game_id") or "").strip(),
                "minutes": _num(r.get("minutes")),
                "position": (r.get("athlete_position_abbreviation")
                             or "").strip(),
                "starter": str(r.get("starter", "")).strip().lower() == "true"}
        values = {k: _num(r.get(col)) for k, col in FIELDS.items()}
        if not line["player_id"] or values["points"] is None:
            continue
        # Both sides have to be real clubs. One exhibition line in a star's
        # last ten is a quarter of the strip on his card.
        if line["team"] not in CLUBS or line["opponent"] not in CLUBS:
            continue
        line.update(values)
        out.append(line)
    # ESPN's file is not in date order -- the first Jokic row in it is his
    # third game. Anything that takes "the last ten" has to sort first.
    out.sort(key=lambda x: (x["date"], x["game_id"]))
    return out


def recent(rows, player_id: str, field: str, limit: int = 10) -> list[dict]:
    """One player's last `limit` games, oldest first, in strip shape."""
    got = [r for r in rows if r["player_id"] == str(player_id)
           and r.get(field) is not None]
    return [{"date": r["date"], "opponent": r["opponent"],
             "value": r[field]} for r in got[-limit:]]


def vs_opponent(rows, player_id: str, opponent: str, field: str) -> dict | None:
    """What this player has done against this club, in the rows given.

    Worth showing in basketball in a way it is not in most sports: two clubs
    meet three or four times a season, so a handful of meetings is a real
    sample of a real matchup -- a particular defender, a particular scheme --
    rather than the two or three plate appearances a baseball card has to
    hedge about.

    None when they have not met. An average over nothing is not a zero.
    """
    got = [r[field] for r in rows
           if r["player_id"] == str(player_id)
           and r["opponent"] == opponent
           and r.get(field) is not None]
    if not got:
        return None
    return {"games": len(got),
            "per_game": round(sum(got) / len(got), 1),
            "best": max(got), "worst": min(got)}


def player_rates(rows, field: str, min_games: int = 5) -> dict[str, dict]:
    """{player id: per-game average, games, name, team} for one stat."""
    bucket: dict[str, list] = {}
    meta: dict[str, dict] = {}
    for r in rows:
        if r.get(field) is None:
            continue
        bucket.setdefault(r["player_id"], []).append(r[field])
        # position comes along because nfl_data.blend -- which this reuses
        # rather than reimplements -- carries it through.
        meta[r["player_id"]] = {"name": r["name"], "team": r["team"],
                                "position": r.get("position", "")}
    out = {}
    for pid, values in bucket.items():
        if len(values) < min_games:
            continue
        out[pid] = {"per_game": sum(values) / len(values),
                    "games": len(values), **meta[pid]}
    return out


def defence(rows, field: str) -> dict[str, float]:
    """{team: the stat it allows per game}, across all opposing players.

    Summed per game first, then averaged over games. Averaging the per-player
    lines instead would answer "what does the average opponent score against
    them", which moves with how many men a club plays, not with its defence.
    """
    per_game: dict[str, dict[str, float]] = {}
    for r in rows:
        if r.get(field) is None or not r["opponent"]:
            continue
        per_game.setdefault(r["opponent"], {}).setdefault(r["game_id"], 0.0)
        per_game[r["opponent"]][r["game_id"]] += r[field]
    return {team: sum(games.values()) / len(games)
            for team, games in per_game.items() if games}


# The position buckets ESPN actually publishes. Not PG/SG/SF/PF/C: those
# appear on 110 of 34,883 box-score rows and 1 of 537 roster rows, so a
# five-way split would be 99.7% guesswork wearing a precise-looking label.
POSITIONS = ("G", "F", "C")


def bucket(position: str) -> str:
    """G, F or C. Anything else is unknown and counted nowhere."""
    p = (position or "").strip().upper()
    if p in POSITIONS:
        return p
    # The handful of finer labels that do appear, folded to their family.
    return {"PG": "G", "SG": "G", "SF": "F", "PF": "F"}.get(p, "")


def defence_by_position(rows, field: str) -> dict[str, dict[str, float]]:
    """{team: {G/F/C: the stat it allows per game to that position}}.

    Team-level "points allowed" hides the shape of a defence: a club can be
    stingy overall and still leak to centres, and a reader looking at a
    centre wants the second number, not the first.

    Summed per game per position first, then averaged over games, for the
    same reason the team version is -- a per-player average moves with how
    many men a club plays rather than with how it defends.
    """
    tally: dict[str, dict[str, dict[str, float]]] = {}
    for r in rows:
        if r.get(field) is None or not r["opponent"]:
            continue
        pos = bucket(r.get("position", ""))
        if not pos:
            continue
        games = tally.setdefault(r["opponent"], {}).setdefault(pos, {})
        games[r["game_id"]] = games.get(r["game_id"], 0.0) + r[field]
    return {team: {pos: sum(g.values()) / len(g)
                   for pos, g in by_pos.items() if g}
            for team, by_pos in tally.items()}


def league_by_position(allowed: dict[str, dict[str, float]]
                       ) -> dict[str, float]:
    """The league average allowed to each position."""
    out = {}
    for pos in POSITIONS:
        vals = [v[pos] for v in allowed.values() if pos in v]
        if vals:
            out[pos] = sum(vals) / len(vals)
    return out


def league_rate(allowed: dict[str, float]) -> float:
    return (sum(allowed.values()) / len(allowed)) if allowed else 0.0


def _self_test() -> None:
    # --- the season label, which is not the calendar year -------------------
    assert season_for("2026-10-21") == 2027, \
        "a game in October 2026 is in the 2027 file"
    assert season_for("2026-06-13") == 2026
    assert season_for("2025-10-01") == 2026
    assert season_for("2026-09-30") == 2026, "September is still last season"

    # --- the did_not_play trap ---------------------------------------------
    raw = [
        {"athlete_id": "1", "athlete_display_name": "A Player",
         "team_abbreviation": "DEN", "opponent_team_abbreviation": "GS",
         "game_date": "2025-10-23", "game_id": "g2", "minutes": "41.0",
         "points": "21", "assists": "10", "rebounds": "13",
         "starter": "true", "did_not_play": "false", "season_type": "2",
         "athlete_position_abbreviation": "C"},
        {"athlete_id": "1", "athlete_display_name": "A Player",
         "team_abbreviation": "DEN", "opponent_team_abbreviation": "PHX",
         "game_date": "2025-10-21", "game_id": "g1", "minutes": "38.0",
         "points": "30", "assists": "4", "rebounds": "9",
         "starter": "true", "did_not_play": "false", "season_type": "2"},
        # Did not play: empty strings, and the flag is lower case. Counting
        # this as a 0-point game would make an injured man look cold.
        {"athlete_id": "1", "athlete_display_name": "A Player",
         "team_abbreviation": "DEN", "opponent_team_abbreviation": "LAL",
         "game_date": "2025-10-25", "game_id": "g3", "minutes": "",
         "points": "", "assists": "", "rebounds": "",
         "starter": "false", "did_not_play": "true", "season_type": "2"},
        # The playoffs are a different game: eight-man rotations, and a
        # regular-season projection must not be trained on them.
        {"athlete_id": "1", "athlete_display_name": "A Player",
         "team_abbreviation": "DEN", "opponent_team_abbreviation": "MIN",
         "game_date": "2026-05-01", "game_id": "p1", "minutes": "44.0",
         "points": "40", "assists": "6", "rebounds": "11",
         "starter": "true", "did_not_play": "false", "season_type": "3"},
        {"athlete_id": "2", "athlete_display_name": "B Player",
         "team_abbreviation": "GS", "opponent_team_abbreviation": "DEN",
         "game_date": "2025-10-23", "game_id": "g2", "minutes": "30.0",
         "points": "11", "assists": "2", "rebounds": "4",
         "starter": "false", "did_not_play": "false", "season_type": "2"},
    ]
    rows = parse(raw)
    assert len(rows) == 3, rows
    assert all(r["points"] is not None for r in rows)
    assert not any(r["date"] == "2026-05-01" for r in rows), "no playoffs"
    # Sorted, because the file is not: the first row in it is not the first
    # game played, and "the last ten" would otherwise be ten arbitrary games.
    assert [r["date"] for r in rows] == ["2025-10-21", "2025-10-23",
                                         "2025-10-23"]
    assert parse(raw, regular_only=False)[-1]["date"] == "2026-05-01"

    # --- recent, rates, defence ---------------------------------------------
    last = recent(rows, "1", "points")
    assert [r["value"] for r in last] == [30.0, 21.0], last
    assert last[-1]["opponent"] == "GS"

    rates = player_rates(rows, "points", min_games=2)
    assert abs(rates["1"]["per_game"] - 25.5) < 1e-9
    assert rates["1"]["games"] == 2 and rates["1"]["team"] == "DEN"
    # nfl_data.blend reads a position off every row it is handed.
    assert "position" in rates["1"]
    assert "2" not in player_rates(rows, "points", min_games=2), \
        "one game is not a rate"

    # Defence is summed per game, then averaged over games. Averaging the
    # player lines instead would move with how many men a club plays.
    allowed = defence(rows, "points")
    assert abs(allowed["GS"] - 21.0) < 1e-9, allowed
    assert abs(allowed["PHX"] - 30.0) < 1e-9
    assert abs(allowed["DEN"] - 11.0) < 1e-9
    assert abs(league_rate(allowed) - (21 + 30 + 11) / 3) < 1e-9
    assert league_rate({}) == 0.0

    # --- the All-Star Game, which says it is a regular-season game ---------
    # Real payload, real trap: 2026-02-15 carries season_type 2 and fields
    # clubs called STARS, STRIPES and WORLD.
    allstar = dict(raw[0], team_abbreviation="STARS",
                   opponent_team_abbreviation="STRIPES",
                   game_date="2026-02-15", game_id="as1")
    assert parse([allstar]) == [], "an exhibition is not a regular-season game"
    # And it is dropped from whichever side is fake, not just the first.
    assert parse([dict(raw[0], opponent_team_abbreviation="WORLD")]) == []
    assert len(CLUBS) == 30, sorted(CLUBS)

    # --- allowed by position ------------------------------------------------
    # ESPN gives G/F/C and nothing finer. The finer labels that do turn up
    # fold into their family rather than being dropped or invented.
    assert bucket("G") == "G" and bucket("PG") == "G" and bucket("SG") == "G"
    assert bucket("PF") == "F" and bucket("SF") == "F" and bucket("F") == "F"
    assert bucket("C") == "C"
    assert bucket("") == "" and bucket("DH") == "" and bucket(None) == ""

    pos_rows = [
        {"player_id": "1", "opponent": "GS", "game_id": "g1", "position": "C",
         "points": 20.0},
        {"player_id": "2", "opponent": "GS", "game_id": "g1", "position": "C",
         "points": 10.0},
        {"player_id": "3", "opponent": "GS", "game_id": "g1", "position": "G",
         "points": 8.0},
        {"player_id": "1", "opponent": "GS", "game_id": "g2", "position": "C",
         "points": 40.0},
    ]
    by_pos = defence_by_position(pos_rows, "points")
    # Two centres for 30 in one game, one for 40 in the next: 35 a game.
    assert by_pos["GS"]["C"] == 35.0, by_pos
    assert by_pos["GS"]["G"] == 8.0
    # A position with no rows is absent, not zero.
    assert "F" not in by_pos["GS"]
    lg = league_by_position(by_pos)
    assert lg["C"] == 35.0 and "F" not in lg
    assert league_by_position({}) == {}
    # A row with no position counts nowhere rather than into a bucket.
    assert defence_by_position(
        [dict(pos_rows[0], position="")], "points") == {}

    # --- against one opponent ------------------------------------------------
    vs = vs_opponent(rows, "1", "GS", "points")
    assert vs == {"games": 1, "per_game": 21.0, "best": 21.0,
                  "worst": 21.0}, vs
    assert vs_opponent(rows, "1", "BOS", "points") is None, \
        "clubs that have not met have no average, not an average of zero"
    assert vs_opponent(rows, "999", "GS", "points") is None
    assert vs_opponent([], "1", "GS", "points") is None

    # A row with no player id, or an unreadable score, is dropped rather than
    # counted as a zero.
    assert parse([dict(raw[0], athlete_id="")]) == []
    assert parse([dict(raw[0], points="")]) == []
    assert parse([]) == [] and parse(None) == []

    print("nba_data self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
