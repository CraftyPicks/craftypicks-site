#!/usr/bin/env python3
"""Find out what MLB actually returns for 'this pitcher vs this team'.

This exists because the vs-opponent line on the Full Board keeps coming back
empty, and the machine that writes these files cannot reach statsapi.mlb.com
to check. Rather than guess at the endpoint a third time, this asks every
plausible form of the question from inside GitHub — where the API IS
reachable — and prints exactly what comes back, including HTTP errors and
the raw shape of the response.

Run it from the Actions tab. It writes nothing and costs nothing.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "craftypicks" / "scripts"))

BASE = "https://statsapi.mlb.com/api/v1"


def get(path, **params):
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "craftypicks-probe/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8")), None, url
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = ""
        return None, f"HTTP {e.code} :: {body}", url
    except Exception as e:                                   # noqa: BLE001
        return None, f"{type(e).__name__}: {e}", url


def rule(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


# ---------------------------------------------------------------- 1. a target
rule("1. Finding a real pitcher with a real opponent")
starter = None
for back in range(0, 8):
    day = date.today() - timedelta(days=back)
    data, err, url = get("/schedule", sportId=1, date=day.strftime("%m/%d/%Y"),
                         hydrate="probablePitcher,team")
    if err:
        print(f"  {day}: {err}")
        continue
    for d in (data or {}).get("dates", []):
        for g in d.get("games", []):
            teams = g.get("teams", {})
            for side, other in (("home", "away"), ("away", "home")):
                p = (teams.get(side) or {}).get("probablePitcher")
                if p and teams.get(other, {}).get("team", {}).get("id"):
                    starter = {"pid": p["id"], "name": p.get("fullName"),
                               "opp_id": teams[other]["team"]["id"],
                               "opp": teams[other]["team"].get("name"),
                               "date": str(day)}
                    break
            if starter:
                break
        if starter:
            break
    if starter:
        break

if not starter:
    print("  Could not find any probable pitcher in the last 8 days. Stopping.")
    sys.exit(0)
print(f"  {starter['name']} (id {starter['pid']}) vs {starter['opp']} "
      f"(id {starter['opp_id']})  [{starter['date']}]")

season = date.today().year

# --------------------------------------------------------- 2. the vsTeam family
rule("2. The vsTeam split family — every combination")
CANDIDATES = [
    {"stats": "vsTeamTotal", "group": "pitching"},
    {"stats": "vsTeam", "group": "pitching"},
    {"stats": "vsTeamTotal", "group": "pitching", "season": season},
    {"stats": "vsTeam", "group": "pitching", "season": season},
    {"stats": "vsTeam5Y", "group": "pitching"},
    {"stats": "vsTeamTotal", "group": "pitching", "season": season - 1},
]
for cand in CANDIDATES:
    params = dict(cand, opposingTeamId=starter["opp_id"], sportId=1)
    data, err, url = get(f"/people/{starter['pid']}/stats", **params)
    tag = ", ".join(f"{k}={v}" for k, v in cand.items())
    if err:
        print(f"  [{tag}] -> {err}")
        continue
    blocks = (data or {}).get("stats") or []
    splits = [s for b in blocks for s in (b.get("splits") or [])]
    print(f"  [{tag}] -> {len(blocks)} block(s), {len(splits)} split(s)")
    if splits:
        s0 = splits[0]
        print(f"       split keys: {sorted(s0.keys())}")
        print(f"       stat: {json.dumps(s0.get('stat', {}))[:260]}")
    elif blocks:
        print(f"       block keys: {sorted(blocks[0].keys())}  "
              f"type={blocks[0].get('type')}")

# ----------------------------------------------------------- 3. the game log
rule("3. The game log — the fallback the site now relies on")
for yr in (season, season - 1):
    data, err, url = get(f"/people/{starter['pid']}/stats", stats="gameLog",
                         group="pitching", season=yr, sportId=1)
    if err:
        print(f"  season {yr} -> {err}")
        print(f"       url: {url}")
        continue
    blocks = (data or {}).get("stats") or []
    splits = [s for b in blocks for s in (b.get("splits") or [])]
    print(f"  season {yr} -> {len(blocks)} block(s), {len(splits)} appearance(s)")
    if not splits:
        print(f"       raw top-level keys: {sorted((data or {}).keys())}")
        print(f"       url: {url}")
        continue
    s0 = splits[0]
    print(f"       split keys: {sorted(s0.keys())}")
    opp = s0.get("opponent")
    print(f"       opponent field: {json.dumps(opp)[:160] if opp else 'ABSENT'}")
    print(f"       stat sample: "
          f"{json.dumps({k: s0.get('stat', {}).get(k) for k in ('gamesStarted','inningsPitched','earnedRuns','strikeOuts')})}")
    hits = [s for s in splits
            if (s.get("opponent") or {}).get("id") == starter["opp_id"]]
    print(f"       appearances vs {starter['opp']}: {len(hits)}")

# ------------------------------------------------- 4. what the site computes
rule("4. What the site's own function returns right now")
try:
    import screen_mlb
    result = screen_mlb.pitcher_vs_team(starter["pid"], starter["opp_id"],
                                        season, verbose=True)
    print(f"\n  pitcher_vs_team(...) -> {result}")
    if result is None:
        print("  ^ this is why the line is blank on the card")
except Exception as e:                                       # noqa: BLE001
    print(f"  raised {type(e).__name__}: {e}")

print("\nDone. Paste this whole log back.")
