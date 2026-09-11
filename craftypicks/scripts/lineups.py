"""Tonight's posted batting orders, from MLB's free StatsAPI.

Why the boards need this
------------------------
The home-run and hits boards rate a club's regulars -- every hitter on the
roster with enough plate appearances -- because at 9am nobody knows who is
playing. Lineups post roughly two to three hours before first pitch, and the
page has said so in small print ever since. That small print is an apology
for a board that is rating four hitters who are not in it.

Two payload shapes, because I have not seen either
--------------------------------------------------
StatsAPI exposes posted lineups in more than one place, and this sandbox
cannot reach statsapi.mlb.com to find out which one is populated when. Both
known shapes are parsed here:

  * /schedule?hydrate=lineups  ->  game["lineups"]["homePlayers"|"awayPlayers"],
    each a list of player objects with an "id".
  * /game/{pk}/boxscore        ->  teams["home"|"away"]["battingOrder"], a
    list of ids, which only fills in once the card is official.

parse() takes whichever it is handed and returns the same thing. Neither is
guessed at: a shape it does not recognise yields no lineup for that game, and
the board falls back to club regulars exactly as it does today. Run
probe_lineups.py in Actions to see which one actually answers, and when.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mlb_api             # noqa: E402

# A batting order is nine names. Anything shorter is a lineup that is still
# being entered, and half a lineup is worse than none: it would drop five
# real hitters off the board and look like a deliberate selection.
FULL_ORDER = 9


def _ids(players) -> list[int]:
    """Player ids out of either a list of ids or a list of player objects."""
    out = []
    for p in players or []:
        if isinstance(p, dict):
            pid = p.get("id")
        else:
            pid = p
        try:
            out.append(int(pid))
        except (TypeError, ValueError):
            continue
    return out


def parse(payload) -> dict[int, list[int]]:
    """{team id: [batter ids, in order]} for every game with a full lineup.

    Keyed by team rather than by game, because that is how the boards ask the
    question: a row is a hitter facing the other club's starter, and what it
    needs to know is whether HIS club has posted.
    """
    out: dict[int, list[int]] = {}
    for day in (payload or {}).get("dates") or []:
        for game in day.get("games") or []:
            teams = game.get("teams") or {}
            lineups = game.get("lineups") or {}
            box = game.get("boxscore") or {}
            for side in ("home", "away"):
                team_id = ((teams.get(side) or {}).get("team") or {}).get("id")
                if not team_id:
                    continue
                order = _ids(lineups.get(f"{side}Players"))
                if len(order) < FULL_ORDER:
                    order = _ids(((box.get("teams") or {}).get(side) or {})
                                 .get("battingOrder"))
                if len(order) >= FULL_ORDER:
                    out[int(team_id)] = order[:FULL_ORDER]
    return out


def fetch(date_str: str, verbose: bool = True) -> dict[int, list[int]]:
    """One request. date_str is MM/DD/YYYY, the way /schedule wants it."""
    payload = mlb_api._get("/schedule", sportId=1, date=date_str,
                           hydrate="lineups,team")
    table = parse(payload)
    if verbose:
        print(f"-- lineups: {len(table)} club(s) have posted a full order")
    return table


def _self_test() -> None:
    sched = {"dates": [{"games": [{
        "teams": {"home": {"team": {"id": 144}},
                  "away": {"team": {"id": 139}}},
        "lineups": {
            "homePlayers": [{"id": i} for i in range(1, 10)],
            "awayPlayers": [{"id": i} for i in range(101, 110)],
        }}]}]}
    table = parse(sched)
    assert table[144] == list(range(1, 10))
    assert table[139] == list(range(101, 110))

    # The boxscore shape, with ids rather than objects.
    box = {"dates": [{"games": [{
        "teams": {"home": {"team": {"id": 111}},
                  "away": {"team": {"id": 147}}},
        "boxscore": {"teams": {
            "home": {"battingOrder": list(range(1, 10))},
            "away": {"battingOrder": list(range(21, 30))}}}}]}]}
    assert parse(box)[111] == list(range(1, 10))
    assert parse(box)[147] == list(range(21, 30))

    # Half a lineup is not a lineup. Taking it would drop five real hitters
    # off the board and look like a selection rather than a gap.
    half = {"dates": [{"games": [{
        "teams": {"home": {"team": {"id": 144}}},
        "lineups": {"homePlayers": [{"id": i} for i in range(1, 6)]}}]}]}
    assert parse(half) == {}, parse(half)

    # More than nine -- a DH swap or a re-entry -- takes the first nine
    # rather than being refused.
    long_ = {"dates": [{"games": [{
        "teams": {"home": {"team": {"id": 144}}},
        "lineups": {"homePlayers": [{"id": i} for i in range(1, 13)]}}]}]}
    assert parse(long_)[144] == list(range(1, 10))

    # The schedule wins when both are present and full: it is the posted
    # card, the boxscore is the game in progress.
    both = {"dates": [{"games": [{
        "teams": {"home": {"team": {"id": 144}}},
        "lineups": {"homePlayers": [{"id": i} for i in range(1, 10)]},
        "boxscore": {"teams": {"home": {"battingOrder": list(range(50, 59))}}}
    }]}]}
    assert parse(both)[144][0] == 1

    # Nothing posted yet, a shape nobody recognises, an empty day: all the
    # same answer, which is the one that leaves the board on club regulars.
    assert parse({"dates": [{"games": [{"teams": {"home": {"team": {"id": 1}}}}]}]}) == {}
    assert parse({"dates": []}) == {} and parse({}) == {} and parse(None) == {}
    assert parse({"dates": [{"games": [{"lineups": {
        "homePlayers": [{"id": i} for i in range(9)]}}]}]}) == {}, \
        "no team id, no lineup -- it cannot be attached to anyone"

    # Ids arrive as strings from some encoders.
    strs = {"dates": [{"games": [{
        "teams": {"home": {"team": {"id": "144"}}},
        "lineups": {"homePlayers": [{"id": str(i)} for i in range(1, 10)]}}]}]}
    assert parse(strs)[144] == list(range(1, 10))

    print("lineups self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
