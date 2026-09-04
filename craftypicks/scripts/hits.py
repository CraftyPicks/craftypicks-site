"""Which batters are most likely to get a hit tonight, and why.

The same shape as the home-run board, and deliberately so -- the model is
the odds ratio, sometimes called log5:

    rate = batter_H_per_PA * pitcher_H_per_BF / league_H_per_PA

A batter who hits twice as often as average, against a pitcher who allows
hits twice as often, is four times as likely as the league -- not three, and
not one and a half. That relation is the whole model. The park multiplies
it, and his plate appearances turn a per-PA rate into a per-game chance.

Everything it needs is already on the wire. The batter leaderboard and the
starter's line are fetched for the home-run board anyway; this reads the
hits column of the same payloads. The board costs nothing to add.

The park factor is computed on hits, not borrowed from the home-run board.
Coors inflates both, but not by the same multiple, and reusing that factor
would be a quiet error that nothing would ever surface.

What it does NOT have is a lineup card. Lineups post about two hours before
first pitch and this runs in the morning, so "the best bats" means the club's
most dangerous regulars, not tonight's nine. The page says so.
"""
from __future__ import annotations

import batters as batters_mod
import mlb_api
import projection

# A starter throws about five and a bit innings of nine, so he faces roughly
# this share of a lineup's plate appearances. The rest meet a bullpen, which
# is modelled as league-average rather than pretended not to exist.
SHARE_VS_STARTER = 0.58

# One season of home-and-away splits is a noisy park factor: half a season in
# each column, and the same lineups on both sides of it. Half weight is
# conservative and stated rather than tuned.
PARK_REGRESSION = 0.5

# Below this a season line is not a rate, it is a sample. Such batters still
# count toward the league total; they are just never ranked.
MIN_PA = 100

# How many names per club the page shows.
TOP_N = 3


def odds_ratio(batter: float, pitcher: float, league: float) -> float:
    """The log5 combination of two rates against a league baseline."""
    if league <= 0:
        return 0.0
    return max(0.0, batter * pitcher / league)


def hit_chance(batter_rate: float, pitcher_rate: float, league: float,
               park: float, pa_per_game: float) -> float:
    """Probability this batter gets at least one hit tonight.

    The starter and the bullpen are separate terms. Both are multiplied by
    the park, because the park applies to the whole game and not only to the
    portion of it the starter is in.
    """
    if pa_per_game <= 0:
        return 0.0
    p_start = min(0.99, odds_ratio(batter_rate, pitcher_rate, league) * park)
    p_pen = min(0.99, batter_rate * park)
    pa_s = pa_per_game * SHARE_VS_STARTER
    pa_p = pa_per_game * (1.0 - SHARE_VS_STARTER)
    return 1.0 - ((1.0 - p_start) ** pa_s) * ((1.0 - p_pen) ** pa_p)


def league_rate(table: dict) -> float:
    """Hits per plate appearance across the whole league.

    Every batter counts toward this, including those under MIN_PA. They are
    part of the league; they are simply not ranked.
    """
    pa = sum(r.get("pa", 0) for r in table.values())
    if pa <= 0:
        return 0.0
    return sum(r.get("h", 0) for r in table.values()) / pa


# Hit chance clusters much tighter than home-run chance -- roughly 55% to
# 85% -- so DEFAULT_EDGES (scaled for single-digit-to-18% HR chances) would
# dump every row into its last bucket and the calibration table, the page's
# whole reason to exist, would report one number and call it a table.
HIT_EDGES = ((0.0, 0.55), (0.55, 0.65), (0.65, 0.72), (0.72, 0.80), (0.80, 1.01))


def grade(history: list[dict], table: dict) -> int:
    """Fill in whether each projected batter has since got a hit."""
    return projection.grade_counting(
        history, table, id_key="batter_id", at_key="h_at_projection",
        verdict_key="got_hit", total_key="h", settled=projection.game_over)


def summary(history: list[dict]) -> dict:
    """Calibration: what was promised against what happened."""
    return projection.calibration(history, verdict_key="got_hit",
                                  edges=HIT_EDGES)


def parse_park(hitting, pitching) -> dict[int, dict]:
    """Hits at home against hits away, both sides of the ball, regressed.

    Both sides matter: a park that helps hitters helps the visitors too, so
    counting only the home club's bats would read a good offence as a good
    park. Adding the two makes the ratio a property of the ground.

    All four splits -- hitting home, hitting away, pitching home, pitching
    away -- are required before a club is emitted. A club present in three
    of the four is not half a park factor, it is a wrong one: summing a
    two-sided numerator over a one-sided denominator produces a number that
    looks like a real factor and is not. Matches batters.parse_park.

    Returns the same shape as batters.park_factors -- factor, raw, and the
    home game count, which build() needs to turn a season plate-appearance
    total into a per-game rate without asking for it separately.
    """
    def collect(payload):
        out: dict[int, dict] = {}
        stats = (payload or {}).get("stats") or []
        splits = stats[0].get("splits", []) if stats else []
        for sp in splits:
            tid = (sp.get("team") or {}).get("id")
            code = ((sp.get("split") or {}).get("code") or "").lower()
            stat = sp.get("stat") or {}
            gp = int(stat.get("gamesPlayed") or 0)
            if tid is None or code not in ("h", "a") or not gp:
                continue
            out.setdefault(int(tid), {})[code] = {
                "hits": int(stat.get("hits") or 0), "g": gp}
        return out

    hit, pit = collect(hitting), collect(pitching)
    out: dict = {}
    for tid, h in hit.items():
        p = pit.get(tid) or {}
        if not all(k in h for k in ("h", "a")) or not all(k in p for k in ("h", "a")):
            continue
        home_g, away_g = h["h"]["g"], h["a"]["g"]
        if not home_g or not away_g:
            continue
        home = (h["h"]["hits"] + p["h"]["hits"]) / home_g
        away = (h["a"]["hits"] + p["a"]["hits"]) / away_g
        if not away:
            continue
        raw = home / away
        out[tid] = {"factor": 1.0 + (raw - 1.0) * PARK_REGRESSION,
                    "raw": raw,
                    "home_games": home_g}
    return out


def park_factors(season: int) -> dict[int, dict]:
    """Every club's hit park factor, in two requests.

    Both are calls the home-run board already makes, so on a run that builds
    both boards these come out of mlb_api's cache and cost nothing at all.

    limit=100 is not optional: statSplits pages at 50 by default, and thirty
    clubs across two splits is sixty rows. Ten would vanish in silence, and
    the missing parks would read as neutral rather than as missing.
    """
    hitting = mlb_api._get("/teams/stats", stats="statSplits", sitCodes="h,a",
                           season=season, group="hitting", sportIds=1,
                           limit=100)
    pitching = mlb_api._get("/teams/stats", stats="statSplits", sitCodes="h,a",
                            season=season, group="pitching", sportIds=1,
                            limit=100)
    return parse_park(hitting, pitching)


def build(starters: list[dict], season: int) -> list[dict]:
    """The best bats in each of tonight's games, with a hit chance attached.

    `starters` is what mlb_api.probable_starters returns, and each row here
    is a batter facing the OTHER club's starter -- so a batter's opponent is
    the pitcher listed against his own team.

    Returns an empty list rather than raising when anything it needs is
    missing. An empty board says nothing; a traceback stops the daily run.
    """
    if not starters:
        return []
    table = batters_mod.all_batters(season)
    if not table:
        return []
    league = league_rate(table)
    if league <= 0:
        return []
    parks = park_factors(season)

    # Games played per club, so a season plate-appearance total becomes a
    # per-game rate. Taken from the park splits, which counted them already.
    games = {tid: v["home_games"] * 2 for tid, v in parks.items()}

    by_team: dict = {}
    for pid, r in table.items():
        if r["pa"] >= MIN_PA and r["team_id"]:
            by_team.setdefault(r["team_id"], []).append((pid, r))

    rows = []
    for s in starters:
        opp_id = s.get("opponent_id")
        pitcher = mlb_api.pitcher_season(s.get("pitcher_id"), season) or {}
        bf = pitcher.get("bf") or 0
        p_rate = ((pitcher["h"] / bf)
                  if (bf and pitcher.get("h") is not None) else None)
        if p_rate is None:
            continue
        # The park belongs to the home club, and the starter's row says which
        # side he is on: if he is away, his own club is not the host.
        home_id = s.get("team_id") if s.get("is_home") else opp_id
        park_row = parks.get(home_id) or {}
        park = park_row.get("factor", 1.0)

        cand = []
        for pid, b in by_team.get(opp_id, []):
            gp = games.get(opp_id) or 0
            if not gp:
                continue
            pa_pg = b["pa"] / gp
            rate = b["h"] / b["pa"]
            cand.append({
                "batter_id": pid, "name": b["name"], "team_id": opp_id,
                "team": s.get("opponent"), "h": b["h"], "pa": b["pa"],
                "hit_rate": rate, "pa_per_game": pa_pg,
                "chance": hit_chance(rate, p_rate, league, park, pa_pg),
                "vs": s.get("name"), "vs_hand": s.get("hand", ""),
                "vs_h_per_bf": p_rate,
                "park": park, "park_raw": park_row.get("raw"),
                "league_rate": league,
                "commence_time": s.get("game_time"),
                "h_at_projection": b["h"], "got_hit": None,
            })
        cand.sort(key=lambda r: r["chance"], reverse=True)
        rows.extend(cand[:TOP_N])

    # Same order as the home-run board: by first pitch, then by chance
    # within a game. The renderer groups these into per-game cards, so
    # sorting by chance alone would order tonight's games by whoever has the
    # hottest bat -- two sibling pages listing the same slate differently.
    rows.sort(key=lambda r: (r.get("commence_time") or "", -r["chance"]))
    return rows


def _self_test() -> None:
    # A league-average batter against a league-average pitcher returns the
    # league rate. If this fails the model is not log5.
    lg = 0.25
    assert abs(odds_ratio(lg, lg, lg) - lg) < 1e-12

    # Doubling both sides quadruples the rate -- not triples, not doubles.
    assert abs(odds_ratio(2 * lg, 2 * lg, lg) - 4 * lg) < 1e-12

    # A zero league rate cannot divide, and must not raise.
    assert odds_ratio(0.3, 0.3, 0.0) == 0.0

    # Chance rises with plate appearances and never reaches certainty.
    a = hit_chance(0.25, 0.25, 0.25, 1.0, 3.0)
    b = hit_chance(0.25, 0.25, 0.25, 1.0, 4.5)
    assert 0.0 < a < b < 1.0, (a, b)

    # Four plate appearances at a flat 25% is 1 - 0.75^4.
    flat = hit_chance(0.25, 0.25, 0.25, 1.0, 4.0)
    assert abs(flat - (1 - 0.75 ** 4)) < 1e-9, flat

    # No plate appearances, no chance -- and no ZeroDivisionError.
    assert hit_chance(0.25, 0.25, 0.25, 1.0, 0.0) == 0.0

    # A friendly park raises it, a hostile park lowers it.
    hot = hit_chance(0.25, 0.25, 0.25, 1.10, 4.0)
    cold = hit_chance(0.25, 0.25, 0.25, 0.90, 4.0)
    assert cold < flat < hot, (cold, flat, hot)

    # The league rate is total hits over total plate appearances, and
    # batters under the floor still count toward it.
    table = {1: {"h": 150, "pa": 600}, 2: {"h": 5, "pa": 20}}
    assert abs(league_rate(table) - 155 / 620) < 1e-12

    # An empty table cannot divide by zero.
    assert league_rate({}) == 0.0

    # Grading and calibration ride on the shared engine.
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    hist = [{"batter_id": 1, "h_at_projection": 100, "got_hit": None,
             "chance": 0.75, "commence_time": past}]
    assert grade(hist, {1: {"h": 101}}) == 1
    assert hist[0]["got_hit"] is True
    assert summary(hist)["graded"] == 1

    # grade() is gated by game_over: a row whose game has not started yet
    # must not be graded, no matter what the leaderboard now says.
    early = [{"batter_id": 2, "h_at_projection": 50, "got_hit": None,
              "chance": 0.60, "commence_time": future}]
    assert grade(early, {2: {"h": 55}}) == 0
    assert early[0]["got_hit"] is None, "a future game must stay ungraded"

    # parse_park regresses half-way to neutral: a raw 1.20 becomes 1.10.
    raw = {113: 1.20, 135: 0.80}
    reg = {k: 1.0 + (v - 1.0) * PARK_REGRESSION for k, v in raw.items()}
    assert abs(reg[113] - 1.10) < 1e-12, reg
    assert abs(reg[135] - 0.90) < 1e-12, reg

    # parse_park requires all four splits. A club present in hitting home/away
    # but only pitching-home (pitching-away missing entirely, as SPLIT_PAGE_
    # LIMIT's own comment records this endpoint has done before) must be
    # omitted, not half-computed from a two-sided numerator over a one-sided
    # denominator.
    hitting_p = {"stats": [{"splits": [
        {"team": {"id": 200}, "split": {"code": "h"},
         "stat": {"hits": 100, "gamesPlayed": 70}},
        {"team": {"id": 200}, "split": {"code": "a"},
         "stat": {"hits": 80, "gamesPlayed": 70}}]}]}
    pitching_p = {"stats": [{"splits": [
        {"team": {"id": 200}, "split": {"code": "h"},
         "stat": {"hits": 90, "gamesPlayed": 70}}]}]}   # away missing
    assert parse_park(hitting_p, pitching_p) == {}, \
        "a club missing one split must be omitted, not half-computed"

    # A club with all four splits present is computed normally.
    pitching_full = {"stats": [{"splits": [
        {"team": {"id": 200}, "split": {"code": "h"},
         "stat": {"hits": 90, "gamesPlayed": 70}},
        {"team": {"id": 200}, "split": {"code": "a"},
         "stat": {"hits": 70, "gamesPlayed": 70}}]}]}
    full = parse_park(hitting_p, pitching_full)
    assert 200 in full, full
    # home = (100+90)/70, away = (80+70)/70, raw = 190/150
    assert abs(full[200]["raw"] - 190 / 150) < 1e-9, full[200]

    # build returns nothing rather than raising when there is no data.
    assert build([], 2026) == []

    # build(), with every fetch stubbed. The three fields checked here are
    # the ones a careless copy from batters.build gets wrong, and none of
    # them would raise -- each would just produce a quietly wrong board.
    import mlb_api as _api
    _real_ps, _real_ab, _real_pf = (_api.pitcher_season,
                                    batters_mod.all_batters, park_factors)
    try:
        _api.pitcher_season = lambda pid, yr: {"bf": 700, "h": 175, "hr": 20}
        batters_mod.all_batters = lambda yr: {
            7: {"name": "A Batter", "team_id": 119, "h": 150, "pa": 600},
            8: {"name": "Bench Guy", "team_id": 119, "h": 5, "pa": 20},
        }
        # games is derived from parks and looked up by the BATTING club
        # (opp_id), not the pitching one -- a stub covering only the
        # pitching club silently empties the board via games.get(opp_id).
        globals()["park_factors"] = lambda yr: {
            135: {"factor": 1.0, "raw": 1.0, "home_games": 81},
            119: {"factor": 1.0, "raw": 1.0, "home_games": 81}}
        rows = build([{"pitcher_id": 1, "name": "A Pitcher", "team_id": 135,
                       "opponent_id": 119, "opponent": "LAD", "is_home": True,
                       "hand": "R", "game_time": "2026-09-04T22:00:00Z"}], 2026)
    finally:
        _api.pitcher_season, batters_mod.all_batters = _real_ps, _real_ab
        globals()["park_factors"] = _real_pf

    assert len(rows) == 1, f"the 20-PA bench bat must not be ranked: {rows}"
    r = rows[0]
    assert r["commence_time"] == "2026-09-04T22:00:00Z", r["commence_time"]
    assert r["team"] == "LAD", r["team"]
    assert abs(r["vs_h_per_bf"] - 175 / 700) < 1e-12, r["vs_h_per_bf"]
    assert abs(r["pa_per_game"] - 600 / 162) < 1e-9, r["pa_per_game"]
    assert 0.55 < r["chance"] < 0.85, f"a .250 bat should be near 70%: {r}"
    assert r["got_hit"] is None and r["h_at_projection"] == 150, r

    # No starters, no rows -- and no exception.
    assert build([], 2026) == []

    print("hits self-test: the model holds and grades itself")


if __name__ == "__main__":
    _self_test()
