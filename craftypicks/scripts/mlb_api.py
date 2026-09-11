"""Client for MLB's free StatsAPI — probable starters, game logs, team rates.

Named `screen_mlb.py` until 2026-08-28, which was wrong in a way that nearly
cost us: it is not a screen, and four modules depend on it for data. It was
renamed so that retiring the strikeout screens cannot take the MLB board and
the pitcher props down with them.

Ported from the V2.2 project to stdlib urllib so the repo keeps its
zero-dependency property — GitHub Actions installs nothing, which is one
less thing that can break at 9am.

The expensive call is vs_roster(): one request per batter. Callers must
gate it behind the cheap filters, which is what screen_source does.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://statsapi.mlb.com/api/v1"
PAUSE = 0.12
_cache: dict = {}


def _get(path: str, **params):
    key = (path, tuple(sorted(params.items())))
    if key in _cache:
        return _cache[key]
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "craftypicks-screens/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        # Swallowed on purpose -- a board that is missing tonight is better
        # than a daily run that dies. But it is said out loud, because an
        # unreachable endpoint and a genuinely empty slate produce the same
        # empty list downstream, and only this line tells them apart.
        print(f"!! statsapi {path} failed ({type(e).__name__}: {e})",
              file=sys.stderr)
        _cache[key] = None
        return None
    _cache[key] = data
    time.sleep(PAUSE)
    return data


def probable_starters(date_str: str) -> list[dict]:
    """Today's probable pitchers. date_str is MM/DD/YYYY."""
    data = _get("/schedule", sportId=1, date=date_str,
                hydrate="probablePitcher,team") or {}
    out = []
    for day in data.get("dates", []):
        for game in day.get("games", []):
            teams = game.get("teams", {})
            for side, other in (("home", "away"), ("away", "home")):
                pitcher = (teams.get(side) or {}).get("probablePitcher")
                if not pitcher:
                    continue
                try:
                    out.append({
                        "pitcher_id": pitcher["id"],
                        "name": pitcher.get("fullName", "?"),
                        "hand": (pitcher.get("pitchHand") or {}).get("code", ""),
                        "team": teams[side]["team"].get("abbreviation")
                                or teams[side]["team"]["name"],
                        "team_id": teams[side]["team"]["id"],
                        "opponent": teams[other]["team"].get("abbreviation")
                                    or teams[other]["team"]["name"],
                        "opponent_id": teams[other]["team"]["id"],
                        # Which dugout he is in. The home club's park is the
                        # one the ball has to leave, and without this a caller
                        # has to guess which of the two names is hosting.
                        "is_home": side == "home",
                        "game_time": game.get("gameDate", ""),
                    })
                except (KeyError, TypeError):
                    continue
    return out


EMPTY_PITCHER = {"k_pct": None, "k_per_9": None, "innings": 0.0, "era": None,
                 "w": None, "l": None, "hr": None, "hr_per_9": None,
                 "bf": None, "h": None, "k": None, "bb": None, "whip": None}


def parse_pitcher_season(payload) -> dict:
    """A starter's season line, from a /people/{id}/stats payload.

    Pure, so it can be tested without the network. The fetch is next door.
    """
    data = payload or {}
    splits = (data.get("stats") or [{}])[0].get("splits") or []
    if not splits:
        return dict(EMPTY_PITCHER)
    s = splits[0].get("stat", {})
    bf = s.get("battersFaced") or 0
    k = s.get("strikeOuts") or 0
    ip = _innings(s.get("inningsPitched"))
    try:
        era = float(s.get("era")) if s.get("era") not in (None, "-.--") else None
    except (TypeError, ValueError):
        era = None
    wins, losses = s.get("wins"), s.get("losses")
    hr = s.get("homeRuns")
    hits = s.get("hits")
    bb = s.get("baseOnBalls")
    try:
        whip = float(s.get("whip")) if s.get("whip") not in (None, "-.--") else None
    except (TypeError, ValueError):
        whip = None
    if whip is None and ip and hits is not None and bb is not None:
        whip = (float(hits) + float(bb)) / ip
    return {
        "k_pct": (k / bf) if bf else None,
        "k_per_9": (k * 9 / ip) if ip else None,
        "innings": ip,
        "era": era,
        "bf": int(bf) if bf else None,
        "hr": int(hr) if hr is not None else None,
        # StatsAPI publishes homeRunsPer9 as a string, but it is derived from
        # the same two numbers we already have and rounds to two places.
        # Recomputing keeps the precision and avoids parsing "-.--".
        "hr_per_9": (float(hr) * 9 / ip) if (hr is not None and ip) else None,
        "h": int(hits) if hits is not None else None,
        "k": int(k) if k else None,
        "bb": int(bb) if bb is not None else None,
        # WHIP arrives as a string and can be "-.--", exactly like ERA. It is
        # also just (H + BB) / IP, and both inputs are in this same payload,
        # so a string that will not parse is computed rather than dropped.
        "whip": whip,
        "w": int(wins) if wins is not None else None,
        "l": int(losses) if losses is not None else None,
    }


def pitcher_season(pitcher_id: int, season: int) -> dict:
    """Season K%, K/9, innings, ERA, hits and home runs allowed, and record.

    The record is display-only and deliberately so: a starter's W-L says more
    about the lineup behind him than about him. Cleveland's Bibee sits at
    5-14 with a 3.88 ERA. It is on the card because readers look for it, and
    nowhere near the projection.
    """
    return parse_pitcher_season(_get(
        f"/people/{pitcher_id}/stats", stats="season",
        season=season, group="pitching"))


def _innings(value) -> float:
    """StatsAPI writes innings as 5.1 / 5.2 meaning 5⅓ / 5⅔, not 5.1 decimal."""
    if value is None:
        return 0.0
    whole, _, thirds = str(value).partition(".")
    try:
        return float(whole) + (float(thirds or 0) / 3.0)
    except ValueError:
        return 0.0


def team_k_per_game(team_id: int, season: int) -> float | None:
    """How often the opposing lineup strikes out per game."""
    data = _get(f"/teams/{team_id}/stats", stats="season",
                season=season, group="hitting") or {}
    splits = (data.get("stats") or [{}])[0].get("splits") or []
    if not splits:
        return None
    s = splits[0].get("stat", {})
    games = s.get("gamesPlayed") or 0
    k = s.get("strikeOuts") or 0
    return (k / games) if games else None


def team_hr_per_game(team_id: int, season: int) -> float | None:
    """How often this lineup goes deep. Free, one request, display-only.

    Mirrors team_k_per_game deliberately: the home-run page is the strikeout
    page's argument applied to a different number, and using a different
    denominator for it would make the two incomparable.
    """
    data = _get(f"/teams/{team_id}/stats", stats="season",
                season=season, group="hitting") or {}
    splits = (data.get("stats") or [{}])[0].get("splits") or []
    if not splits:
        return None
    s = splits[0].get("stat", {})
    games = s.get("gamesPlayed") or 0
    hr = s.get("homeRuns") or 0
    return (hr / games) if games else None


def team_roster(team_id: int, season: int) -> list[int]:
    """Active roster, position players only. Ids alone, for vs_roster."""
    return [p["id"] for p in roster_detail(team_id, season)]


def roster_detail(team_id: int, season: int) -> list[dict]:
    """Active roster as {id, name, position}, position players only.

    The position was always in this payload -- it is what filters the
    pitchers out -- and was then thrown away. The hitters table needs it,
    so it is kept.
    """
    data = _get(f"/teams/{team_id}/roster", rosterType="active",
                season=season) or {}
    out = []
    for p in data.get("roster", []):
        pos = (p.get("position") or {}).get("abbreviation") or ""
        if pos == "P":
            continue
        person = p.get("person") or {}
        if person.get("id"):
            out.append({"id": person["id"],
                        "name": person.get("fullName") or "",
                        "position": pos})
    return out


def lineup_vs(pitcher_id: int, team_id: int, season: int,
              limit: int = 9) -> list[dict]:
    """Each hitter's career line against this starter.

    One free request per hitter, and the roster call is cached for the run,
    so a whole board costs requests rather than credits.

    A hitter who has never faced him is KEPT, with every figure None. The
    reference screenshot prints a row of dashes for exactly this, and it is
    the right call: "has never faced him" is information, and dropping the
    row would silently shorten one club's table against the other's.

    Ordered by plate appearances against him, most first, because we do not
    have the batting order -- see the note in lineup_note.
    """
    out = []
    for player in roster_detail(team_id, season):
        s = vs_batter(pitcher_id, player["id"], season) or {}
        pa = s.get("plateAppearances") or 0
        ab = s.get("atBats") or 0
        h = s.get("hits")
        out.append({
            "id": player["id"], "name": player["name"],
            "position": player["position"],
            "pa": pa or None,
            "ab": ab or None,
            "h": h if pa else None,
            "hr": s.get("homeRuns") if pa else None,
            "rbi": s.get("rbi") if pa else None,
            "k": s.get("strikeOuts") if pa else None,
            "avg": (h / ab) if (ab and h is not None) else None,
        })
    out.sort(key=lambda r: (r["pa"] or 0), reverse=True)
    return out[:limit]


def _first_split(data):
    for block in (data or {}).get("stats", []):
        for split in block.get("splits", []):
            s = split.get("stat", {})
            if s.get("plateAppearances"):
                return s
    return None


def vs_batter(pitcher_id: int, batter_id: int, season: int = 0):
    """One hitter's career line against one pitcher.

    The person in the path is the BATTER and the group is "hitting". That
    is not a detail -- it is the whole thing, and two shipped versions of
    this function got it wrong because it was reasoned about rather than
    measured. research/probe_bvp.py settled it on 2026-09-08 by asking
    StatsAPI seven ways about a real matchup (Angel Martinez vs Brandon
    Young, 3 PA):

        batter id,  group=hitting,  vsPlayerTotal   1 split,  3 PA   <-- this
        pitcher id, group=pitching, vsPlayerTotal   1 split,  0 PA
        pitcher id, group=hitting,  vsPlayerTotal   0 splits, 0 PA   <-- shipped

    The last line is what this site sent for every batter in every game,
    which is why every card read "has not faced". Asking a PITCHER for his
    "hitting" line against a batter is a question with no answer, and
    StatsAPI answered it honestly with nothing.

    Note the pitching variant returns a split with no plate appearances
    rather than no split at all -- so the guard has to be on PA, not on the
    presence of a split.

    `season` is accepted and ignored. vsPlayerTotal is the career total,
    which is what every caller wants, and the parameter is kept only so the
    call sites do not all have to change.
    """
    return _first_split(
        _get(f"/people/{batter_id}/stats", stats="vsPlayerTotal",
             group="hitting", opposingPlayerId=pitcher_id))


def vs_roster(pitcher_id: int, opponent_team_id: int, season: int):
    """Career line against the whole opposing roster. One call per batter."""
    from screen_models import VsRoster
    agg = VsRoster()
    for batter_id in team_roster(opponent_team_id, season):
        s = vs_batter(pitcher_id, batter_id, season)
        if not s:
            continue
        agg.pa += s.get("plateAppearances", 0) or 0
        agg.k += s.get("strikeOuts", 0) or 0
        agg.ab += s.get("atBats", 0) or 0
        agg.h += s.get("hits", 0) or 0
        agg.doubles += s.get("doubles", 0) or 0
        agg.triples += s.get("triples", 0) or 0
        agg.hr += s.get("homeRuns", 0) or 0
        agg.bb += s.get("baseOnBalls", 0) or 0
        agg.hbp += s.get("hitByPitch", 0) or 0
        agg.sf += s.get("sacFlies", 0) or 0
        agg.batters_seen += 1
        agg.faced.append(batter_id)
    return agg


def batter_vs_pitcher(batter_id: int, pitcher_id: int, season: int):
    """One hitter's career line against one starter, or None.

    The same call the lineup table makes, for the boards whose row already
    IS one batter against one named pitcher. Returns None rather than a row
    of zeroes when they have never met: zero-for-zero and "never faced" look
    identical once formatted, and only one of them is true.
    """
    if not (batter_id and pitcher_id):
        return None
    s = vs_batter(pitcher_id, batter_id, season) or {}
    pa = s.get("plateAppearances") or 0
    if not pa:
        return None
    ab, h = s.get("atBats") or 0, s.get("hits") or 0
    return {"pa": pa, "ab": ab, "h": h,
            "hr": s.get("homeRuns"), "rbi": s.get("rbi"),
            "k": s.get("strikeOuts"), "bb": s.get("baseOnBalls"),
            "avg": (h / ab) if ab else None}


def attach_bvp(rows: list[dict], season: int, verbose: bool = True) -> int:
    """Put a career batter-vs-pitcher line on each row that names a pitcher.

    Called after the board has been cut to its top few per game, so the cost
    is one free request per printed row rather than per rated batter. Every
    call is wrapped: this is a display extra and must never cost the board.
    """
    got = 0
    for r in rows:
        try:
            r["bvp"] = batter_vs_pitcher(r.get("batter_id"),
                                        r.get("pitcher_id"), season)
        except Exception:                                    # noqa: BLE001
            r["bvp"] = None
        if r.get("bvp"):
            got += 1
    if verbose:
        print(f"   bvp: {got}/{len(rows)} batter(s) have faced their starter")
    return got


def team_index(season: int) -> dict:
    """{normalised team name: mlb team id}, for joining odds-feed names."""
    data = _get("/teams", sportId=1, season=season) or {}
    out = {}
    for team in data.get("teams", []):
        tid = team.get("id")
        for label in (team.get("name"), team.get("teamName"),
                      team.get("clubName"), team.get("shortName")):
            if label and tid:
                out[str(label).strip().lower()] = tid
    return out



# --------------------------------------------------- pitcher vs one opponent
def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _get_reporting(path: str, **params):
    """Like _get, but says why it failed. Used only by the vs-opponent probe,
    where a silent None is the difference between 'never faced them' and
    'we're calling this endpoint wrong'."""
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "craftypicks-screens/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:180]
        except Exception:                                    # noqa: BLE001
            pass
        return None, f"HTTP {e.code} {body}"
    except (urllib.error.URLError, TimeoutError) as e:
        return None, f"{type(e).__name__}: {e}"
    except json.JSONDecodeError:
        return None, "response was not JSON"


def _totals(rows: list) -> dict | None:
    """Sum however many appearance rows into one line."""
    starts = innings = earned = strikeouts = 0.0
    for sp in rows:
        s = sp.get("stat") or {}
        starts += _num(s.get("gamesStarted"))
        innings += _innings(s.get("inningsPitched"))
        earned += _num(s.get("earnedRuns"))
        strikeouts += _num(s.get("strikeOuts"))
    if innings <= 0:
        return None
    return {"starts": int(starts), "innings": round(innings, 1),
            "era": round(earned * 9 / innings, 2), "strikeouts": int(strikeouts)}


# The vsTeam split family is the direct way to ask this question, but the
# exact stat-type and parameter combination that answers is something this
# repo has never been able to verify — statsapi is unreachable from where
# these files get written. So it is tried first and, when it stays silent,
# the same figure is rebuilt from the game log, which is a far more ordinary
# endpoint and filters on an opponent field rather than a query parameter.
_VS_CANDIDATES = [
    {"stats": "vsTeamTotal", "group": "pitching"},
    {"stats": "vsTeam", "group": "pitching"},
    {"stats": "vsTeamTotal", "group": "pitching", "_season": True},
    {"stats": "vsTeam", "group": "pitching", "_season": True},
]
_vs_direct: dict | None = None   # the candidate that answered, once known
_vs_direct_dead = False
_vs_probe_done = False


def _try_direct(pitcher_id: int, opponent_team_id: int, season: int,
                verbose: bool) -> dict | None:
    global _vs_direct, _vs_direct_dead, _vs_probe_done
    if _vs_direct_dead:
        return None

    candidates = [_vs_direct] if _vs_direct else _VS_CANDIDATES
    for cand in candidates:
        params = {k: v for k, v in cand.items() if not k.startswith("_")}
        params.update(opposingTeamId=opponent_team_id, sportId=1)
        if cand.get("_season"):
            params["season"] = season
        data, err = _get_reporting(f"/people/{pitcher_id}/stats", **params)
        rows = []
        for block in (data or {}).get("stats") or []:
            rows.extend(block.get("splits") or [])
        if verbose and not _vs_probe_done:
            label = f"stats={cand['stats']}{'+season' if cand.get('_season') else ''}"
            print(f"      vs-probe {label}: "
                  + (err if err else f"{len(rows)} split(s)"))
        totals = _totals(rows)
        if totals:
            if not _vs_direct:
                _vs_direct = cand
                print(f"   slate: vs-opponent via stats={cand['stats']}")
            return totals

    if not _vs_direct:
        _vs_direct_dead = True
        if verbose:
            print("   slate: vsTeam split gave nothing; using the game log instead")
    _vs_probe_done = True
    return None


def season_game_log(pitcher_id: int, season: int) -> list:
    """Every appearance this season, newest last. Cached per pitcher-season,
    so the vs-opponent line and the last-ten strip share one request."""
    data = _get(f"/people/{pitcher_id}/stats", stats="gameLog",
                group="pitching", season=season, sportId=1)
    rows = []
    for block in (data or {}).get("stats") or []:
        rows.extend(block.get("splits") or [])
    rows.sort(key=lambda sp: str(sp.get("date") or ""))
    return rows


def batter_game_log(batter_id: int, season: int) -> list:
    """Every game this hitter has played this season, oldest first.

    The pitching twin of this call has been in use since the strikeout strip
    was built; this is the same endpoint with group="hitting", which is the
    only thing that changes which stat object comes back. Cached per
    batter-season by _get, so a hitter who appears on both the home-run board
    and the hits board costs one request, not two.
    """
    data = _get(f"/people/{batter_id}/stats", stats="gameLog",
                group="hitting", season=season, sportId=1)
    rows = []
    for block in (data or {}).get("stats") or []:
        rows.extend(block.get("splits") or [])
    rows.sort(key=lambda sp: str(sp.get("date") or ""))
    return rows


def _from_game_log(pitcher_id: int, opponent_team_id: int,
                   seasons: list[int]) -> dict | None:
    """Rebuild the same line by filtering this pitcher's appearances.

    One request per pitcher-season regardless of opponent, and the season's
    log is cached, so both halves of a matchup share the fetch.
    """
    rows, spanned = [], []
    for year in seasons:
        appearances = season_game_log(pitcher_id, year)
        if appearances:
            spanned.append(year)
        for sp in appearances:
            if (sp.get("opponent") or {}).get("id") == opponent_team_id:
                rows.append(sp)
    totals = _totals(rows)
    if totals and spanned:
        totals["span"] = (f"{min(spanned)}" if min(spanned) == max(spanned)
                          else f"{min(spanned)}–{max(spanned)}")
        totals["source"] = "gameLog"
    return totals


def pitcher_vs_team(pitcher_id: int, opponent_team_id: int, season: int,
                    verbose: bool = True) -> dict | None:
    """This starter's line against tonight's opponent, or None.

    Context for a reader only. It is not an input to the rating and must
    never become one: these samples are small enough that the difference
    between a 2.10 and a 5.40 is usually four innings of luck.
    """
    if not pitcher_id or not opponent_team_id:
        return None
    direct = _try_direct(pitcher_id, opponent_team_id, season, verbose)
    if direct:
        direct.setdefault("source", "vsTeam")
        return direct
    return _from_game_log(pitcher_id, opponent_team_id, [season - 1, season])


def parse_hands(payload) -> dict[int, str]:
    """Pitcher id -> "L" / "R" / "". A person with no pitchHand is blank."""
    out = {}
    for person in (payload or {}).get("people", []) or []:
        pid = person.get("id")
        if pid is None:
            continue
        out[int(pid)] = (person.get("pitchHand") or {}).get("code") or ""
    return out


def pitch_hands(pitcher_ids) -> dict[int, str]:
    """Which way each of these pitchers throws. One free request for the slate.

    Not folded into probable_starters(): the schedule's probablePitcher
    hydration carries no pitchHand at all, which is why every card's
    home_hand has been an empty string since the board shipped. Asking per
    pitcher would be a request each; /people takes the whole day at once.
    """
    ids = sorted({int(p) for p in pitcher_ids if p})
    if not ids:
        return {}
    return parse_hands(_get("/people", personIds=",".join(str(i) for i in ids)))


# The last-ten record hides among sixteen split records; this is its type.
LAST_TEN = "lastTen"


def parse_standings(payload) -> dict[int, dict]:
    """Team id -> record, streak and last ten."""
    out = {}
    for record in (payload or {}).get("records", []) or []:
        for tr in record.get("teamRecords", []) or []:
            tid = (tr.get("team") or {}).get("id")
            if tid is None:
                continue
            last10 = {}
            for sr in ((tr.get("records") or {}).get("splitRecords") or []):
                if sr.get("type") == LAST_TEN:
                    last10 = sr
                    break
            out[int(tid)] = {
                "w": int(tr.get("wins") or 0),
                "l": int(tr.get("losses") or 0),
                "streak": (tr.get("streak") or {}).get("streakCode") or "",
                "l10_w": int(last10.get("wins") or 0),
                "l10_l": int(last10.get("losses") or 0),
            }
    return out


def standings(season: int, date_str: str) -> dict[int, dict]:
    """The table as it stood on the MORNING of date_str (YYYY-MM-DD).

    Verified: date=2026-09-01 returns the Padres at 73-65, which is what the
    board recorded at 9am that day; date=2026-08-31 returns 72-65. So the
    board passes its own date and gets the table its reader expects, with
    that evening's games still unplayed.

    One free request covers all thirty clubs across both leagues.
    """
    return parse_standings(_get("/standings", leagueId="103,104",
                                season=season, date=date_str,
                                standingsTypes="regularSeason"))


def parse_series(payload) -> list[dict]:
    """Completed meetings, oldest first."""
    out = []
    for day in (payload or {}).get("dates", []) or []:
        date = day.get("date") or ""
        for game in day.get("games", []) or []:
            if (game.get("status") or {}).get("abstractGameState") != "Final":
                continue
            teams = game.get("teams") or {}
            away, home = teams.get("away") or {}, teams.get("home") or {}
            a_id = (away.get("team") or {}).get("id")
            h_id = (home.get("team") or {}).get("id")
            if a_id is None or h_id is None:
                continue
            out.append({
                "date": date or (game.get("gameDate") or "")[:10],
                "away_id": int(a_id), "away_runs": int(away.get("score") or 0),
                "home_id": int(h_id), "home_runs": int(home.get("score") or 0),
            })
    out.sort(key=lambda g: g["date"])
    return out


def season_series(team_id: int, opponent_id: int, season: int,
                  through: str) -> list[dict]:
    """Regular-season meetings on or before `through` (YYYY-MM-DD).

    gameType="R" is not optional. Without it the Padres-Reds series came back
    with an extra game and the first was a 14-3 exhibition on 8 March 2026.
    The runner probe checks for a March game precisely to catch its removal.
    """
    return parse_series(_get("/schedule", sportId=1, gameType="R",
                             startDate=f"{season}-01-01", endDate=through,
                             teamId=team_id, opponentId=opponent_id))


# 30 clubs x 2 splits = 60 rows, and this endpoint pages at 50 by default.
# The first read of it in development came back ten rows short with no error
# and no warning; the missing clubs were simply absent.
SPLIT_PAGE_LIMIT = 100


def parse_k_splits(payload) -> dict[int, dict]:
    """Team id -> strikeout rate against each hand.

    A club missing either half is dropped rather than half-reported: a card
    showing a rate against righties and nothing against lefties invites the
    reader to assume the missing one is zero.
    """
    splits = (((payload or {}).get("stats") or [{}])[0] or {}).get("splits") or []
    out: dict[int, dict] = {}
    for split in splits:
        tid = (split.get("team") or {}).get("id")
        code = (split.get("split") or {}).get("code")
        stat = split.get("stat") or {}
        pa = stat.get("plateAppearances")
        if tid is None or code not in ("vr", "vl") or not pa:
            continue
        k = float(stat.get("strikeOuts") or 0)
        out.setdefault(int(tid), {})["vR" if code == "vr" else "vL"] = {
            "k_pct": 100.0 * k / float(pa),
            "k": int(k),
            "pa": int(pa),
        }
    return {tid: v for tid, v in out.items() if "vL" in v and "vR" in v}


def team_k_splits(season: int) -> dict[int, dict]:
    """Every club's strikeout rate against right- and left-handers.

    One free request for the whole league. limit is mandatory --
    see SPLIT_PAGE_LIMIT.
    """
    return parse_k_splits(_get("/teams/stats", stats="statSplits",
                               sitCodes="vr,vl", season=season,
                               group="hitting", sportIds=1,
                               limit=SPLIT_PAGE_LIMIT))


def _self_test() -> None:
    """Parsers only. Every fetch is split from its parser so this needs no
    network -- the live endpoints are checked by the probe workflow instead."""
    # ---- handedness. The schedule does not carry pitchHand; /people does.
    people = {"people": [
        {"id": 681190, "fullName": "Randy Vasquez", "pitchHand": {"code": "R"}},
        {"id": 666157, "fullName": "Nick Lodolo", "pitchHand": {"code": "L"}},
        {"id": 999999, "fullName": "No Hand Listed"},
    ]}
    hands = parse_hands(people)
    assert hands[681190] == "R" and hands[666157] == "L", hands
    assert hands[999999] == "", "a missing pitchHand is blank, not a crash"
    assert parse_hands({}) == {} and parse_hands(None) == {}

    # ---- standings: the last ten hides among sixteen splitRecords.
    st = {"records": [{"teamRecords": [
        {"team": {"id": 135}, "wins": 73, "losses": 65,
         "streak": {"streakCode": "W1"},
         "records": {"splitRecords": [
             {"type": "home", "wins": 41, "losses": 28},
             {"type": "lastTen", "wins": 5, "losses": 5}]}},
        {"team": {"id": 113}, "wins": 65, "losses": 73,
         "streak": {"streakCode": "L1"},
         "records": {"splitRecords": [{"type": "lastTen",
                                       "wins": 4, "losses": 6}]}}]}]}
    table = parse_standings(st)
    assert table[135] == {"w": 73, "l": 65, "streak": "W1",
                          "l10_w": 5, "l10_l": 5}, table[135]
    assert table[113]["streak"] == "L1"
    bare = parse_standings({"records": [{"teamRecords": [
        {"team": {"id": 1}, "wins": 1, "losses": 2,
         "streak": {}, "records": {}}]}]})
    assert bare[1] == {"w": 1, "l": 2, "streak": "",
                       "l10_w": 0, "l10_l": 0}, bare
    assert parse_standings(None) == {}

    # ---- the season series. Only finals, oldest first.
    sched = {"dates": [
        {"date": "2026-08-31", "games": [{
            "status": {"abstractGameState": "Final"},
            "teams": {"away": {"team": {"id": 135}, "score": 5},
                      "home": {"team": {"id": 113}, "score": 0}}}]},
        {"date": "2026-06-08", "games": [{
            "status": {"abstractGameState": "Final"},
            "teams": {"away": {"team": {"id": 113}, "score": 2},
                      "home": {"team": {"id": 135}, "score": 6}}}]},
        {"date": "2026-09-02", "games": [{
            "status": {"abstractGameState": "Preview"},
            "teams": {"away": {"team": {"id": 135}, "score": None},
                      "home": {"team": {"id": 113}, "score": None}}}]}]}
    series = parse_series(sched)
    assert [g["date"] for g in series] == ["2026-06-08", "2026-08-31"], series
    assert series[0]["home_id"] == 135 and series[0]["home_runs"] == 6
    assert series[1]["away_runs"] == 5
    assert len(series) == 2, "a Preview game is not a result"
    assert parse_series({}) == []

    # ---- K% splits. Real 2026 figures, so these are checkable on the site.
    raw = {"stats": [{"splits": [
        {"team": {"id": 113}, "split": {"code": "vr"},
         "stat": {"strikeOuts": 1015, "plateAppearances": 3989}},
        {"team": {"id": 113}, "split": {"code": "vl"},
         "stat": {"strikeOuts": 307, "plateAppearances": 1230}},
        {"team": {"id": 141}, "split": {"code": "vr"},
         "stat": {"strikeOuts": 693, "plateAppearances": 3665}},
        {"team": {"id": 141}, "split": {"code": "vl"},
         "stat": {"strikeOuts": 311, "plateAppearances": 1510}},
        {"team": {"id": 999}, "split": {"code": "vr"},
         "stat": {"strikeOuts": 1, "plateAppearances": 10}}]}]}
    ks = parse_k_splits(raw)
    assert round(ks[113]["vR"]["k_pct"], 1) == 25.4, ks[113]
    assert ks[113]["vR"]["pa"] == 3989
    assert ks[113]["vR"]["k"] == 1015, "the raw count is kept so the combined "\
                                       "rate can be summed rather than averaged"
    assert round(ks[141]["vL"]["k_pct"], 1) == 20.6, ks[141]
    assert 999 not in ks, "a club with only one of the two splits is dropped"
    assert parse_k_splits({}) == {}

    # ---- pitcher season line. hits ride along with everything else in the
    # same payload; only the parsing was ever missing.
    payload = {"stats": [{"splits": [{"stat": {
        "battersFaced": 700, "strikeOuts": 180, "inningsPitched": "170.1",
        "era": "3.45", "homeRuns": 22, "hits": 150,
        "wins": 11, "losses": 7}}]}]}
    row = parse_pitcher_season(payload)
    assert row["bf"] == 700, row
    assert row["h"] == 150, row          # hits allowed, the new field
    assert row["hr"] == 22, row
    assert row["w"] == 11 and row["l"] == 7, row
    assert abs(row["k_pct"] - 180 / 700) < 1e-12, row
    assert abs(row["innings"] - 170.333) < 0.01, row

    # A pitcher with no season line returns the empty shape, not a KeyError,
    # and every caller reads it with .get() anyway.
    empty = parse_pitcher_season({"stats": [{"splits": []}]})
    assert empty["h"] is None and empty["bf"] is None, empty
    assert set(empty) == set(EMPTY_PITCHER), empty

    # A missing hits field is None, not zero. Zero would read as a pitcher
    # who has never allowed a hit and would rank top of every board.
    no_hits = parse_pitcher_season({"stats": [{"splits": [{"stat": {
        "battersFaced": 100, "inningsPitched": "25.0"}}]}]})
    assert no_hits["h"] is None, no_hits

    # The empty template must not be handed out by reference; a caller that
    # mutated it would corrupt every later empty result.
    a = parse_pitcher_season({})
    a["h"] = 999
    assert parse_pitcher_season({})["h"] is None, "EMPTY_PITCHER was shared"

    # --- batter vs pitcher: the exact payload research/probe_bvp.py pulled
    # back on 2026-09-08, trimmed to the fields we read. The point of the
    # fixture is the URL, not the arithmetic: two shipped versions of
    # vs_batter asked the wrong person for the wrong group and returned
    # nothing for every batter in every game, and nothing in this file
    # noticed. Now the call itself is asserted.
    seen = {}

    def _fake_get(path, **params):
        seen["path"], seen["params"] = path, params
        if path != "/people/682657/stats":
            return None
        if params.get("group") != "hitting":
            return None
        return {"stats": [{"splits": [{"stat": {
            "plateAppearances": 3, "atBats": 3, "hits": 2, "doubles": 1,
            "homeRuns": 0, "rbi": 0, "strikeOuts": 0, "baseOnBalls": 0,
            "hitByPitch": 0, "sacFlies": 0, "triples": 0,
            "avg": ".667"}}]}]}

    real_get = globals()["_get"]
    globals()["_get"] = _fake_get
    try:
        got = vs_batter(687064, 682657, 2026)
        assert seen["path"] == "/people/682657/stats", (
            "the BATTER is the person in the path, not the pitcher: "
            f"{seen['path']}")
        assert seen["params"]["group"] == "hitting", seen["params"]
        assert seen["params"]["opposingPlayerId"] == 687064, seen["params"]
        assert seen["params"]["stats"] == "vsPlayerTotal", seen["params"]
        assert "season" not in seen["params"], \
            "vsPlayerTotal is the career total; a season would narrow it"
        assert got and got["plateAppearances"] == 3, got

        line = batter_vs_pitcher(682657, 687064, 2026)
        assert line["pa"] == 3 and line["h"] == 2 and line["ab"] == 3, line
        assert abs(line["avg"] - 2 / 3) < 1e-9, line
        assert line["rbi"] == 0 and line["k"] == 0, line

        # Never faced: None, not a row of zeroes. The two look identical
        # once formatted and only one of them is true.
        assert batter_vs_pitcher(694197, 687064, 2026) is None
        # attach_bvp survives it and says so.
        rows = [{"batter_id": 682657, "pitcher_id": 687064},
                {"batter_id": 694197, "pitcher_id": 687064},
                {"batter_id": None, "pitcher_id": 687064}]
        assert attach_bvp(rows, 2026, verbose=False) == 1
        assert rows[0]["bvp"]["pa"] == 3 and rows[1]["bvp"] is None
    finally:
        globals()["_get"] = real_get

    print("mlb_api self-test: every parser holds, pitcher season included")


if __name__ == "__main__":
    _self_test()
