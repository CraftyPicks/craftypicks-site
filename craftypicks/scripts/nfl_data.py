"""The free NFL feed, and what is worth keeping from it.

nflverse publishes one gzipped CSV per season of per-player, per-week
lines, plus a schedule. No key, no rate limit, no scraping.

Two things in this data will quietly ruin a rate if they are not handled,
and both were found by probing rather than by reading documentation:

  * the weekly file contains rows with no player at all -- a team, an
    opponent and zeros -- and counting them drags every league average down

  * a missing number arrives as an empty string, not a zero. A quarterback
    with no passing line did not throw for zero yards; he has no line, and
    averaging a zero in is a lie the model cannot see

What this deliberately does NOT read is the depth chart. depth_charts_2026
exists, but its newest snapshot is from March, four months before the
season, so it cannot say who starts. The schedule names the starting
quarterback, and last season's carries and targets say who gets the ball --
both more current than an offseason chart.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import math
import sys
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

# nflverse's schedule publishes gametime in US Eastern, not UTC.
EASTERN = ZoneInfo("America/New_York")

RELEASES = "https://api.github.com/repos/nflverse/nflverse-data/releases"
UA = {"User-Agent": "craftypicks/1.0"}

# The columns the boards use. The file has 150; carrying the rest would
# mean every future reader wondering which ones matter.
WEEKLY_FIELDS = (
    "passing_yards", "rushing_yards", "receiving_yards",
    "passing_tds", "rushing_tds", "receiving_tds",
    "attempts", "carries", "targets", "receptions",
)

_cache: dict = {}


def _get(url: str, want_json: bool = True):
    if url in _cache:
        return _cache[url]
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        # Said out loud on purpose: an unreachable feed and an empty season
        # produce the same empty list downstream, and only this line tells
        # them apart.
        print(f"!! nflverse {url} failed ({type(e).__name__}: {e})",
              file=sys.stderr)
        _cache[url] = None
        return None
    out = json.loads(raw.decode("utf-8")) if want_json else raw
    _cache[url] = out
    return out


def num(value) -> float | None:
    """A numeric field, or None if it is blank or unparseable.

    Deliberately not `float(value or 0)`. Blank means no line, and a zero
    would be counted as a performance.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    # float() accepts "nan", "inf" and "Infinity". One NaN reaching a sum
    # makes the sum NaN, and every rate computed from it, silently and
    # forever -- there is no later point at which the page could notice.
    if not math.isfinite(value):
        return None
    return value


def asset_urls() -> dict[str, str]:
    """Every release asset name mapped to its download URL.

    Paged, because GitHub returns 30 per page by default and this repo has
    thousands of assets across dozens of releases. Unpaged, the release
    holding the file we want can simply be absent, and the failure looks
    like a clean "not found" rather than a truncated list.
    """
    out: dict[str, str] = {}
    page = 1
    while True:
        batch = _get(f"{RELEASES}?per_page=100&page={page}")
        if batch is None:
            # Everything or nothing. A partial listing would look like a
            # complete one to the caller, and the asset it wanted would be
            # reported absent rather than unreachable -- a false negative
            # that reads as a clean answer.
            return {}
        if not batch:
            break
        for rel in batch:
            for a in rel.get("assets", []):
                out[a["name"]] = a["browser_download_url"]
        if len(batch) < 100:
            break
        page += 1
    return out


def fetch_csv_gz(url: str) -> list[dict] | None:
    raw = _get(url, want_json=False)
    if raw is None:
        return None
    text = gzip.decompress(raw).decode("utf-8", "replace")
    return list(csv.DictReader(io.StringIO(text)))


def fetch_csv(url: str) -> list[dict] | None:
    """The plain-CSV twin of fetch_csv_gz, for assets nflverse does not gzip.

    games.csv is served uncompressed while the weekly stat files are not --
    the two feeds are not packaged the same way, and schedule() would raise
    an AttributeError forever if it kept reaching for the gzipped reader.
    """
    raw = _get(url, want_json=False)
    if raw is None:
        return None
    text = raw.decode("utf-8", "replace")
    return list(csv.DictReader(io.StringIO(text)))


def parse_weekly(rows: list[dict]) -> list[dict]:
    """Regular-season lines belonging to an actual player.

    Both filters matter. A blank player_id is a row with no player, which
    the real file ends with. Postseason rows are excluded because a rate
    built across both mixes two different populations of opponent.
    """
    out = []
    for r in rows or []:
        pid = (r.get("player_id") or "").strip()
        if not pid or (r.get("season_type") or "").strip().upper() != "REG":
            continue
        row = {
            "player_id": pid,
            "name": (r.get("player_display_name") or "").strip(),
            "position": (r.get("position") or "").strip(),
            "position_group": (r.get("position_group") or "").strip(),
            "team": (r.get("team") or "").strip(),
            "opponent_team": (r.get("opponent_team") or "").strip(),
            "season": int(num(r.get("season")) or 0),
            "week": int(num(r.get("week")) or 0),
            "game_id": (r.get("game_id") or "").strip(),
        }
        for f in WEEKLY_FIELDS:
            row[f] = num(r.get(f))
        out.append(row)
    return out


def _commence_time(day: str, gametime: str) -> str:
    """Kickoff as an aware ISO timestamp, in its real UTC offset.

    nflverse's gametime column is US Eastern, not UTC. Stamping it as if it
    were already UTC would show every card a kickoff about four hours
    early, and would shrink game_over's six-hour grading margin to roughly
    two real hours past actual kickoff -- which is exactly the gap that
    lets a still-live game get graded. Interpreting it as
    America/New_York and letting zoneinfo resolve standard vs. daylight
    time is the conservative direction: the only way this can be wrong is
    if nflverse is not in fact Eastern, and that failure pushes kickoff
    LATER here, never earlier -- grading late costs a rerun, grading early
    writes a permanent wrong answer.

    A missing or unparseable time falls back to 23:59 UTC exactly as
    before this fix, rather than being run through the timezone above too
    -- the fallback's job is only to grade late, and it already did.
    """
    clock = (gametime or "").strip()
    if clock:
        text = f"{clock}:00" if len(clock) == 5 else clock
        try:
            hour, minute, second = (int(p) for p in text.split(":"))
            year, month = int(day[0:4]), int(day[5:7])
            dom = int(day[8:10])
            local = datetime(year, month, dom, hour, minute, second,
                             tzinfo=EASTERN)
            return local.isoformat()
        except (ValueError, IndexError):
            pass
    return f"{day}T23:59:00+00:00"


def parse_schedule(rows: list[dict], season: int) -> list[dict]:
    """This season's regular-season games, with their starting passers.

    commence_time is built here rather than at the point of use, because
    projection.game_over needs one timestamp per row to decide whether a
    result may be judged. A game with no listed kickoff (or one that
    fails to parse) gets 23:59 UTC, which makes it grade late rather than
    early -- an ungraded row is missing from the record, a wrongly graded
    one is a lie in it. See _commence_time for the Eastern-vs-UTC choice.
    """
    out = []
    for r in rows or []:
        if int(num(r.get("season")) or 0) != season:
            continue
        if (r.get("game_type") or "").strip().upper() != "REG":
            continue
        day = (r.get("gameday") or "").strip()
        if not day:
            continue
        out.append({
            "game_id": (r.get("game_id") or "").strip(),
            "week": int(num(r.get("week")) or 0),
            "gameday": day,
            "commence_time": _commence_time(day, r.get("gametime")),
            "away_team": (r.get("away_team") or "").strip(),
            "home_team": (r.get("home_team") or "").strip(),
            "home_qb_id": (r.get("home_qb_id") or "").strip(),
            "home_qb_name": (r.get("home_qb_name") or "").strip(),
            "away_qb_id": (r.get("away_qb_id") or "").strip(),
            "away_qb_name": (r.get("away_qb_name") or "").strip(),
            "roof": (r.get("roof") or "").strip(),
            "stadium": (r.get("stadium") or "").strip(),
        })
    out.sort(key=lambda g: (g["week"], g["commence_time"]))
    return out


# Four games of this season weigh the same as all of last season. Stated,
# not tuned -- and written where the grading can later argue with it.
BLEND_K = 4


def player_rates(weekly: list[dict], field: str) -> dict[str, dict]:
    """Each player's per-game rate in one category.

    Per game PLAYED, not per week of the season: a player who missed six
    weeks with an injury is not a worse player for it, and dividing by 17
    would say he was.

    A row where the field is None does not count as a game. That is the
    point of parsing blanks to None -- a receiver with no receiving line
    did not catch for zero yards that week, the line is simply absent.
    """
    out: dict[str, dict] = {}
    max_week: dict[str, tuple] = {}
    for r in weekly:
        value = r.get(field)
        if value is None:
            continue
        player_id = r["player_id"]
        current_week = (r["season"], r["week"])
        row = out.setdefault(player_id, {
            "name": r["name"], "team": r["team"],
            "position": r["position"], "total": 0.0, "games": 0})
        row["total"] += value
        row["games"] += 1
        # The most recent club wins, so a traded player is listed where he
        # now plays rather than where he started the year.
        if current_week > max_week.get(player_id, (-1, -1)):
            max_week[player_id] = current_week
            row["team"] = r["team"]
    for row in out.values():
        row["per_game"] = row["total"] / row["games"] if row["games"] else 0.0
    return out


def defence_detail(weekly: list[dict], field: str) -> dict[str, dict]:
    """What each team allowed per game, and over how many games.

    Same arithmetic as defence(), but it keeps the game count, because a
    rate without its sample size cannot be blended against another season.
    """
    totals: dict[str, float] = {}
    games: dict[str, set] = {}
    for r in weekly:
        value = r.get(field)
        opp = r.get("opponent_team")
        if value is None or not opp:
            continue
        totals[opp] = totals.get(opp, 0.0) + value
        # game_id is unique across seasons; week is not. This function is
        # called on rows spanning multiple seasons, and week 1 of 2025 and
        # week 1 of 2026 must count as two separate games.
        games.setdefault(opp, set()).add(r["game_id"])
    return {
        t: {"per_game": totals[t] / len(games[t]), "games": len(games[t])}
        for t in totals if games.get(t)
    }


def defence(weekly: list[dict], field: str) -> dict[str, float]:
    """What each team allowed per game in one category.

    Keyed by opponent_team, which is the defence's own abbreviation on an
    offensive player's row. Divided by games rather than by opposing player
    lines: a team that happened to face a four-receiver offence should not
    read as generous because the yardage was split more ways.
    """
    return {t: v["per_game"] for t, v in defence_detail(weekly, field).items()}


def blend(current: dict[str, dict], prior: dict[str, dict],
          k: int = BLEND_K) -> dict[str, dict]:
    """This season's rate shaded toward last season's, by how much exists.

        w = games_this_season / (games_this_season + k)

    In week one w is zero and the number is entirely last season. Each row
    carries its own weight so the page can say so out loud, because a board
    that hides its weakest moment is worse than one that names it.

    A player with neither line is omitted. A rookie has no rate, and
    inventing one would put a number on the page that nothing supports.
    """
    out: dict[str, dict] = {}
    for pid in set(current) | set(prior):
        cur = current.get(pid)
        old = prior.get(pid)
        cur_games = cur["games"] if cur else 0
        w = cur_games / (cur_games + k) if (cur_games or k) else 0.0
        if cur and old:
            rate = w * cur["per_game"] + (1.0 - w) * old["per_game"]
        elif cur:
            rate = cur["per_game"]
            w = 1.0
        elif old:
            rate = old["per_game"]
            w = 0.0
        else:
            continue
        base = cur or old
        out[pid] = {
            "name": base["name"], "team": base["team"],
            "position": base["position"], "per_game": rate, "weight": round(w, 3),
            "games": cur_games, "prior_games": old["games"] if old else 0,
        }
    return out


def blend_defence(cur_weekly: list[dict], prior_weekly: list[dict],
                  field: str, k: int = BLEND_K) -> dict[str, dict]:
    """This season's defensive rate shaded toward last season's.

    The same shape of correction the offence gets, and for the same reason:
    one week of football is not a defence's true rate, and a team that gave
    up four hundred yards in a shootout is not a four-hundred-yard defence.

    Returns per team {"per_game", "games", "weight"} so a caller can say how
    much of the number is this season.
    """
    current = defence_detail(cur_weekly, field)
    prior = defence_detail(prior_weekly, field)
    out: dict[str, dict] = {}
    for team in set(current) | set(prior):
        cur = current.get(team)
        old = prior.get(team)
        cur_games = cur["games"] if cur else 0
        w = cur_games / (cur_games + k) if (cur_games or k) else 0.0
        if cur and old:
            rate = w * cur["per_game"] + (1.0 - w) * old["per_game"]
        elif cur:
            rate = cur["per_game"]
            w = 1.0
        elif old:
            rate = old["per_game"]
            w = 0.0
        else:
            continue
        out[team] = {"per_game": rate, "games": cur_games, "weight": round(w, 3)}
    return out


def _self_test() -> None:
    # A blank is not a zero. A quarterback with no line did not throw for
    # zero yards -- he has no line, and averaging a zero in would be a lie.
    assert num("") is None
    assert num(None) is None
    assert num("0") == 0.0
    assert num("60") == 60.0
    assert num("6.24877") == 6.24877
    assert num("not a number") is None
    # float() would accept every one of these. A NaN reaching a sum makes
    # the sum NaN and every rate built on it, with nothing to notice.
    for poison in ("nan", "NaN", "-nan", "inf", "-inf", "Infinity"):
        assert num(poison) is None, poison

    raw = [
        # A real line.
        {"player_id": "00-0000003", "player_display_name": "A Runner",
         "position": "RB", "position_group": "RB", "team": "MIA",
         "opponent_team": "DEN", "season": "2025", "week": "1",
         "season_type": "REG", "game_id": "2025_01_MIA_DEN",
         "passing_yards": "0", "rushing_yards": "60", "receiving_yards": "7",
         "passing_tds": "0", "rushing_tds": "1", "receiving_tds": "0",
         "attempts": "0", "carries": "16", "targets": "1", "receptions": "1"},
        # Postseason: excluded, because a rate built on it mixes two
        # different populations of opponent.
        {"player_id": "00-0000003", "player_display_name": "A Runner",
         "position": "RB", "position_group": "RB", "team": "MIA",
         "opponent_team": "NE", "season": "2025", "week": "22",
         "season_type": "POST", "game_id": "2025_22_MIA_NE",
         "passing_yards": "0", "rushing_yards": "80", "receiving_yards": "0",
         "passing_tds": "0", "rushing_tds": "1", "receiving_tds": "0",
         "attempts": "0", "carries": "20", "targets": "0", "receptions": "0"},
        # No player at all. The real file ends with one of these.
        {"player_id": "", "player_display_name": "", "position": "",
         "position_group": "", "team": "SEA", "opponent_team": "NE",
         "season": "2025", "week": "22", "season_type": "POST",
         "game_id": "2025_22_SEA_NE",
         "passing_yards": "0", "rushing_yards": "0", "receiving_yards": "0",
         "passing_tds": "0", "rushing_tds": "0", "receiving_tds": "0",
         "attempts": "0", "carries": "0", "targets": "0", "receptions": "0"},
    ]
    weekly = parse_weekly(raw)
    assert len(weekly) == 1, f"REG + real players only: {weekly}"
    w = weekly[0]
    assert w["player_id"] == "00-0000003"
    assert w["rushing_yards"] == 60.0
    assert w["opponent_team"] == "DEN"
    assert w["week"] == 1 and w["season"] == 2025

    games = [
        {"game_id": "2026_01_NE_SEA", "season": "2026", "game_type": "REG",
         "week": "1", "gameday": "2026-09-09", "gametime": "20:15",
         "away_team": "NE", "home_team": "SEA",
         "home_qb_id": "00-0011", "home_qb_name": "Home Passer",
         "away_qb_id": "00-0022", "away_qb_name": "Away Passer",
         "roof": "outdoors", "stadium": "Lumen Field"},
        # A different season, and a preseason game: neither belongs.
        {"game_id": "2025_01_A_B", "season": "2025", "game_type": "REG",
         "week": "1", "gameday": "2025-09-05", "gametime": "20:15",
         "away_team": "A", "home_team": "B", "home_qb_id": "", "home_qb_name": "",
         "away_qb_id": "", "away_qb_name": "", "roof": "dome", "stadium": "X"},
        {"game_id": "2026_00_C_D", "season": "2026", "game_type": "PRE",
         "week": "0", "gameday": "2026-08-10", "gametime": "19:00",
         "away_team": "C", "home_team": "D", "home_qb_id": "", "home_qb_name": "",
         "away_qb_id": "", "away_qb_name": "", "roof": "dome", "stadium": "Y"},
    ]
    sched = parse_schedule(games, 2026)
    assert len(sched) == 1, f"2026 regular season only: {sched}"
    g = sched[0]
    assert g["home_team"] == "SEA" and g["away_team"] == "NE"
    assert g["home_qb_name"] == "Home Passer"
    assert g["week"] == 1
    # An ISO timestamp, because projection.game_over parses one to decide
    # whether a result may be judged yet.
    assert g["commence_time"].startswith("2026-09-09T20:15"), g["commence_time"]

    # Finding 4: gametime is US Eastern, not UTC. 2026-09-09 20:15 Eastern
    # is daylight time (UTC-4), so its UTC equivalent is one day and four
    # hours later in the clock, not the same instant stamped "+00:00".
    import datetime as _dt
    parsed = _dt.datetime.fromisoformat(g["commence_time"])
    as_utc = parsed.astimezone(_dt.timezone.utc)
    assert as_utc.strftime("%Y-%m-%dT%H:%M") == "2026-09-10T00:15", as_utc
    # And it must still round-trip through the shared gate every board's
    # grading depends on.
    import projection as _projection
    before_kick = as_utc - _dt.timedelta(hours=1)
    after_final = as_utc + _dt.timedelta(hours=7)
    assert _projection.game_over(g, before_kick) is False
    assert _projection.game_over(g, after_final) is True

    # A game with no listed time still sorts and still grades -- it just
    # grades later. Missing must never mean "grade it now". The fallback
    # stays literal UTC rather than being run through Eastern too.
    noon = parse_schedule([dict(games[0], gametime="")], 2026)[0]
    assert noon["commence_time"] == "2026-09-09T23:59:00+00:00", noon

    # An unparseable gameday must not raise, and must still fall back to
    # the same late-not-early UTC placeholder.
    garbage_day = parse_schedule(
        [dict(games[0], gameday="garbage")], 2026)[0]
    assert garbage_day["commence_time"] == "garbageT23:59:00+00:00", \
        garbage_day

    # Rates are per game played, not per week of the season. A player who
    # missed six weeks is not a worse player for it.
    # Week 1: MIA at DEN, and BUF at NE. Week 2: MIA at NE.
    # Each team plays once a week, which is what makes a per-game
    # denominator meaningful.
    weekly = parse_weekly([
        {"player_id": "p1", "player_display_name": "Runner One",
         "position": "RB", "position_group": "RB", "team": "MIA",
         "opponent_team": "DEN", "season": "2025", "week": "1",
         "season_type": "REG", "game_id": "2025_01_MIA_DEN",
         "rushing_yards": "100", "carries": "20", "rushing_tds": "1"},
        {"player_id": "p1", "player_display_name": "Runner One",
         "position": "RB", "position_group": "RB", "team": "MIA",
         "opponent_team": "NE", "season": "2025", "week": "2",
         "season_type": "REG", "game_id": "2025_02_MIA_NE",
         "rushing_yards": "50", "carries": "10", "rushing_tds": "0"},
        {"player_id": "p2", "player_display_name": "Runner Two",
         "position": "RB", "position_group": "RB", "team": "BUF",
         "opponent_team": "NE", "season": "2025", "week": "1",
         "season_type": "REG", "game_id": "2025_01_BUF_NE",
         "rushing_yards": "40", "carries": "8", "rushing_tds": "0"},
    ])
    rates = player_rates(weekly, "rushing_yards")
    assert rates["p1"]["games"] == 2
    assert rates["p1"]["per_game"] == 75.0, rates["p1"]
    assert rates["p1"]["team"] == "MIA" and rates["p1"]["name"] == "Runner One"

    dfn = defence(weekly, "rushing_yards")
    assert dfn["DEN"] == 100.0, dfn        # one game, 100 allowed
    assert dfn["NE"] == 45.0, dfn          # two games, 40 + 50

    # The bug that made this fixture matter: game_id is unique across
    # seasons, week is not. Two seasons' week 1 must count as two games.
    two_seasons = parse_weekly([
        {"player_id": "p9", "player_display_name": "X", "position": "RB",
         "position_group": "RB", "team": "MIA", "opponent_team": "DEN",
         "season": "2025", "week": "1", "season_type": "REG",
         "game_id": "2025_01_MIA_DEN", "rushing_yards": "100"},
        {"player_id": "p9", "player_display_name": "X", "position": "RB",
         "position_group": "RB", "team": "MIA", "opponent_team": "DEN",
         "season": "2026", "week": "1", "season_type": "REG",
         "game_id": "2026_01_MIA_DEN", "rushing_yards": "60"},
    ])
    assert defence(two_seasons, "rushing_yards")["DEN"] == 80.0, \
        "two seasons' week 1 are two games, not one"

    # The blend. Four games of this season equal all of last season.
    prior = {"p1": {"name": "Runner One", "team": "MIA", "position": "RB",
                    "total": 1000.0, "games": 16, "per_game": 62.5}}
    cur = {"p1": {"name": "Runner One", "team": "MIA", "position": "RB",
                  "total": 300.0, "games": 4, "per_game": 75.0}}
    # w = 4/(4+4) = 0.5 -> halfway between 75 and 62.5
    mixed = blend(cur, prior)
    assert abs(mixed["p1"]["per_game"] - 68.75) < 1e-9, mixed["p1"]
    assert mixed["p1"]["weight"] == 0.5

    # Week 1: no current season at all, so the blend is entirely last year
    # and says so, rather than silently reporting a made-up number.
    week1 = blend({}, prior)
    assert week1["p1"]["per_game"] == 62.5
    assert week1["p1"]["weight"] == 0.0

    # A player with no prior and no current cannot be projected. A rookie
    # is omitted rather than guessed at.
    assert blend({}, {}) == {}

    # A blank field does not count as a game: if one row has the field and
    # the other does not, only the present one counts.
    blank_field = parse_weekly([
        {"player_id": "p_blank", "player_display_name": "Test",
         "position": "WR", "position_group": "WR", "team": "MIA",
         "opponent_team": "DEN", "season": "2025", "week": "1",
         "season_type": "REG", "game_id": "2025_01_MIA_DEN",
         "receiving_yards": "50", "targets": "5", "receptions": "3"},
        {"player_id": "p_blank", "player_display_name": "Test",
         "position": "WR", "position_group": "WR", "team": "MIA",
         "opponent_team": "NE", "season": "2025", "week": "2",
         "season_type": "REG", "game_id": "2025_02_MIA_NE",
         "receiving_yards": "", "targets": "0", "receptions": "0"},
    ])
    blank_rates = player_rates(blank_field, "receiving_yards")
    assert blank_rates["p_blank"]["games"] == 1, \
        f"only present values count as games: {blank_rates}"
    assert blank_rates["p_blank"]["per_game"] == 50.0

    # A traded player is listed by his latest week, regardless of row order.
    # Rows in week-1, then week-5 order:
    traded_early = parse_weekly([
        {"player_id": "p_trad", "player_display_name": "Traded",
         "position": "WR", "position_group": "WR", "team": "OLD",
         "opponent_team": "DEF1", "season": "2025", "week": "1",
         "season_type": "REG", "game_id": "2025_01_OLD_DEF1",
         "receiving_yards": "30", "targets": "3", "receptions": "2"},
        {"player_id": "p_trad", "player_display_name": "Traded",
         "position": "WR", "position_group": "WR", "team": "NEW",
         "opponent_team": "DEF2", "season": "2025", "week": "5",
         "season_type": "REG", "game_id": "2025_05_NEW_DEF2",
         "receiving_yards": "40", "targets": "4", "receptions": "3"},
    ])
    trade_rates_early = player_rates(traded_early, "receiving_yards")
    assert trade_rates_early["p_trad"]["team"] == "NEW", \
        f"player should be listed by latest week, not last row: {trade_rates_early}"
    # Same rows reversed: result must not change
    traded_late = parse_weekly([
        {"player_id": "p_trad", "player_display_name": "Traded",
         "position": "WR", "position_group": "WR", "team": "NEW",
         "opponent_team": "DEF2", "season": "2025", "week": "5",
         "season_type": "REG", "game_id": "2025_05_NEW_DEF2",
         "receiving_yards": "40", "targets": "4", "receptions": "3"},
        {"player_id": "p_trad", "player_display_name": "Traded",
         "position": "WR", "position_group": "WR", "team": "OLD",
         "opponent_team": "DEF1", "season": "2025", "week": "1",
         "season_type": "REG", "game_id": "2025_01_OLD_DEF1",
         "receiving_yards": "30", "targets": "3", "receptions": "2"},
    ])
    trade_rates_late = player_rates(traded_late, "receiving_yards")
    assert trade_rates_late["p_trad"]["team"] == "NEW", \
        f"order independence failed: {trade_rates_late}"

    # A rookie with current season only has weight 1.0 and current rate.
    rookie_cur = {"p_rook": {"name": "Rookie", "team": "MIA", "position": "WR",
                             "total": 200.0, "games": 3, "per_game": 66.667}}
    rookie_blend = blend(rookie_cur, {})
    assert rookie_blend["p_rook"]["weight"] == 1.0, \
        f"current-only rate should have full weight: {rookie_blend}"
    assert abs(rookie_blend["p_rook"]["per_game"] - 66.667) < 1e-3

    # blend_defence: the bug this exists to fix. A defence that allowed a
    # steady 100/game across 17 prior games must not be reset to a single
    # fluky 400-yard current game the moment the new season starts -- the
    # blended number must land between the two, and much nearer the prior.
    prior_def = parse_weekly([
        {"player_id": f"o{w}", "player_display_name": "Opp", "position": "RB",
         "position_group": "RB", "team": "OFF", "opponent_team": "STINGY",
         "season": "2025", "week": str(w), "season_type": "REG",
         "game_id": f"2025_{w:02d}_OFF_STINGY", "rushing_yards": "100"}
        for w in range(1, 18)
    ])
    cur_def = parse_weekly([
        {"player_id": "o99", "player_display_name": "Opp", "position": "RB",
         "position_group": "RB", "team": "OFF", "opponent_team": "STINGY",
         "season": "2026", "week": "1", "season_type": "REG",
         "game_id": "2026_01_OFF_STINGY", "rushing_yards": "400"}
    ])
    blended_def = blend_defence(cur_def, prior_def, "rushing_yards")
    d = blended_def["STINGY"]
    assert d["games"] == 1, d
    # w = 1/(1+4) = 0.2 -> 0.2*400 + 0.8*100 = 160
    assert abs(d["per_game"] - 160.0) < 1e-9, d
    assert d["per_game"] < 250.0, \
        f"one fluky game must not overwhelm 17 steady ones: {d}"
    assert d["weight"] == 0.2, d

    # Finding 1: fetch_csv is the plain-CSV twin of fetch_csv_gz. Both are
    # exercised here with only _get (the HTTP layer) stubbed, never the
    # parsing functions themselves -- stubbing the thing under test is how
    # a missing fetch_csv shipped undetected in the first place.
    real_get = _get
    try:
        _cache.clear()
        globals()["_get"] = lambda url, want_json=True: (
            gzip.compress(b"a,b\n1,2\n"))
        rows = fetch_csv_gz("https://example.invalid/x.csv.gz")
        assert rows == [{"a": "1", "b": "2"}], rows

        _cache.clear()
        globals()["_get"] = lambda url, want_json=True: b"a,b\n3,4\n"
        rows = fetch_csv("https://example.invalid/x.csv")
        assert rows == [{"a": "3", "b": "4"}], rows

        # An unreachable feed reads the same way through either reader:
        # None in, None out, never a traceback.
        _cache.clear()
        globals()["_get"] = lambda url, want_json=True: None
        assert fetch_csv("https://example.invalid/x.csv") is None
        assert fetch_csv_gz("https://example.invalid/x.csv.gz") is None
    finally:
        globals()["_get"] = real_get
        _cache.clear()

    print("nfl_data self-test: the parsers hold")


if __name__ == "__main__":
    _self_test()
