#!/usr/bin/env python3
"""Which StatsAPI call actually returns a batter-vs-pitcher line?

Diagnostic only. Reads public endpoints, writes nothing, commits nothing.

Why this exists: the site has shipped TWO versions of vs_batter() that
returned nothing, and both were reasoned about rather than measured,
because the sandbox this code is written in cannot reach statsapi.mlb.com.
The second one asks for

    /people/{PITCHER}/stats?stats=vsPlayerTotal&group=hitting
                           &opposingPlayerId={BATTER}

-- the PITCHER's id with group=hitting, which reads as "this pitcher's
BATTING line against that hitter". That is very likely the whole bug, and
"very likely" is exactly the standard that produced the last two failures.
So this asks the endpoint instead of asking me.

It finds a real matchup first -- today's probable starter and the club he
is actually facing -- so no permutation can pass or fail because the two
players never met.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

BASE = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "craftypicks-probe/1.0 (+https://craftypicks.org)"}
SEASON = 2026


def get(path: str, **params):
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"     !! {type(e).__name__}: {e}  <- {url[:120]}")
        return None


def splits(data):
    out = []
    for block in (data or {}).get("stats", []):
        out.extend(block.get("splits") or [])
    return out


def find_matchup():
    """A starter listed today (or yesterday), and the club he faces."""
    for back in range(0, 8):
        day = (date.today() - timedelta(days=back)).strftime("%m/%d/%Y")
        d = get("/schedule", sportId=1, date=day,
                hydrate="probablePitcher,team")
        for wrap in (d or {}).get("dates", []):
            for g in wrap.get("games", []):
                for side, other in (("home", "away"), ("away", "home")):
                    pp = (g["teams"][side].get("probablePitcher") or {})
                    if pp.get("id"):
                        opp = g["teams"][other]["team"]
                        print(f"  using {pp.get('fullName')} ({pp['id']}) "
                              f"vs {opp.get('name')} ({opp['id']}) on {day}")
                        return pp["id"], pp.get("fullName"), opp["id"]
    return None, None, None


def roster(team_id):
    d = get(f"/teams/{team_id}/roster", rosterType="active", season=SEASON)
    return [(p["person"]["id"], p["person"].get("fullName", "?"))
            for p in (d or {}).get("roster", [])
            if (p.get("position") or {}).get("abbreviation") != "P"]


def variants(pitcher, batter):
    """Every plausible shape, named. Order is 'most likely correct' first."""
    return [
        ("batter id, group=hitting, vsPlayerTotal",
         f"/people/{batter}/stats",
         dict(stats="vsPlayerTotal", group="hitting",
              opposingPlayerId=pitcher)),
        ("batter id, group=hitting, vsPlayer",
         f"/people/{batter}/stats",
         dict(stats="vsPlayer", group="hitting", opposingPlayerId=pitcher)),
        ("batter id, group=hitting, vsPlayerTotal + sportId",
         f"/people/{batter}/stats",
         dict(stats="vsPlayerTotal", group="hitting",
              opposingPlayerId=pitcher, sportId=1)),
        ("batter id, group=hitting, vsPlayerTotal + season",
         f"/people/{batter}/stats",
         dict(stats="vsPlayerTotal", group="hitting",
              opposingPlayerId=pitcher, season=SEASON)),
        ("pitcher id, group=pitching, vsPlayerTotal",
         f"/people/{pitcher}/stats",
         dict(stats="vsPlayerTotal", group="pitching",
              opposingPlayerId=batter)),
        ("pitcher id, group=pitching, vsPlayer",
         f"/people/{pitcher}/stats",
         dict(stats="vsPlayer", group="pitching", opposingPlayerId=batter)),
        ("WHAT WE SHIP NOW: pitcher id, group=hitting, vsPlayerTotal",
         f"/people/{pitcher}/stats",
         dict(stats="vsPlayerTotal", group="hitting",
              opposingPlayerId=batter)),
    ]


def main() -> int:
    print("== 1. find a real matchup")
    pid, pname, team = find_matchup()
    if not pid:
        print("no probable starter in the last week; stopping.")
        return 1

    print("\n== 2. walk that roster until a shape returns plate appearances")
    bats = roster(team)
    print(f"  {len(bats)} position player(s) on the roster")

    winner = None
    for bid, bname in bats[:6]:
        print(f"\n  -- {bname} ({bid}) vs {pname}")
        for label, path, params in variants(pid, bid):
            rows = splits(get(path, **params))
            pa = 0
            for s in rows:
                pa = max(pa, (s.get("stat") or {}).get("plateAppearances") or 0)
            mark = "  <<< HAS DATA" if pa else ""
            print(f"     {len(rows)} split(s), max PA {pa:<4} {label}{mark}")
            if pa and winner is None:
                winner = (label, path, params, rows)
        if winner:
            break

    print("\n== 3. what the winning shape actually returns")
    if not winner:
        print("  NOTHING returned plate appearances for any shape.")
        print("  That would mean batter-vs-pitcher is not reachable this way")
        print("  at all, and the panel should say so rather than print zeroes.")
        return 0
    label, path, params, rows = winner
    print(f"  {label}")
    print(f"  {path} {params}")
    stat = (rows[0].get("stat") or {})
    print(f"\n  fields available ({len(stat)}):")
    for k in sorted(stat):
        print(f"     {k:32} {stat[k]!r}")
    for want in ("plateAppearances", "atBats", "hits", "homeRuns",
                 "rbi", "strikeOuts", "baseOnBalls", "avg"):
        print(f"  {'OK ' if want in stat else 'MISSING'} {want}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
