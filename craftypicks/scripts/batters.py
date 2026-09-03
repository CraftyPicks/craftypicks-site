"""Which batters are most likely to homer tonight, and why.

This is a projection, which makes it different from everything else added to
this site recently, and it is built to be judged from the first night rather
than a season later.

The model is the odds ratio, sometimes called log5, and it is three numbers:

    rate = batter_HR_per_PA * pitcher_HR_per_BF / league_HR_per_PA

A batter who homers twice as often as average, against a pitcher who allows
them twice as often as average, is four times as likely as the league to go
deep -- not three, and not one and a half. That relation is the whole model.
Then the park multiplies it, and the batter's own plate appearances turn a
per-PA rate into a per-game chance.

Everything it needs is free:

  * every batter's season line, in ONE request (playerPool=All returns a
    thousand of them; the default returns only the ~130 who qualify for a
    batting title, which would silently omit every platoon hitter)
  * every club's home and away splits, hitting and pitching, in two more
  * the starter's line, which the board already fetches

What it does NOT have is a lineup card. Lineups post about two hours before
first pitch and this runs in the morning, so "the best batters" means the
club's most dangerous regulars, not tonight's nine. A batter who is rested
will not be removed from the page, and the page says so.

Grading is free too, and that is the point of doing it this way: the batter
leaderboard is refetched every morning, so a batter's season home-run total
today minus the total stored yesterday says whether he homered. No extra
request, no scraping, and no way to quietly avoid finding out.
"""
from __future__ import annotations

import statistics

import mlb_api

# A starter throws about five and a bit innings of nine, so he faces roughly
# this share of a lineup's plate appearances. The rest meet a bullpen, which
# is modelled as league-average rather than pretended not to exist -- ignoring
# it would attribute a reliever's home run to the starter's matchup.
SHARE_VS_STARTER = 0.58

# One season of home-and-away splits is a noisy park factor: half a season of
# games in each column, and the same lineups on both sides of it. Published
# factors regress hard for exactly this reason. Half weight is conservative
# and stated rather than tuned.
PARK_REGRESSION = 0.5

# Below this a season line is not a rate, it is a sample. Such batters are
# still parsed -- they are part of the league totals -- but never ranked.
MIN_PA = 100

# How many names per club the page shows.
TOP_N = 3


def parse_batters(payload) -> dict[int, dict]:
    """Player id -> season home runs, plate appearances and club.

    A traded batter appears once per club. The lines are summed, because his
    home-run rate is a fact about him and not about who was paying him, and
    the club recorded is the last one seen so he shows up on tonight's team.
    """
    splits = (((payload or {}).get("stats") or [{}])[0] or {}).get("splits") or []
    out: dict[int, dict] = {}
    for sp in splits:
        player = sp.get("player") or {}
        pid = player.get("id")
        stat = sp.get("stat") or {}
        pa = stat.get("plateAppearances")
        if pid is None or not pa:
            continue
        row = out.setdefault(int(pid), {
            "name": player.get("fullName", ""), "hr": 0, "pa": 0,
            "team_id": None})
        row["hr"] += int(stat.get("homeRuns") or 0)
        row["pa"] += int(pa)
        team = (sp.get("team") or {}).get("id")
        if team:
            row["team_id"] = int(team)
    return out


def league_rate(table: dict[int, dict]) -> float:
    """Home runs per plate appearance across everybody who batted."""
    hr = sum(r["hr"] for r in table.values())
    pa = sum(r["pa"] for r in table.values())
    return (hr / pa) if pa else 0.0


def parse_park(hitting, pitching) -> dict[int, dict]:
    """Team id -> home-run park factor, from home and away splits.

    The factor is every home run in this club's home games -- hit and allowed
    -- per game, over the same figure on the road. Both halves matter: a park
    where the home side slugs and the visitors do not is a lineup, not a park.
    """
    def collect(payload, key):
        out: dict[int, dict] = {}
        splits = (((payload or {}).get("stats") or [{}])[0] or {}).get("splits") or []
        for sp in splits:
            tid = (sp.get("team") or {}).get("id")
            code = (sp.get("split") or {}).get("code")
            stat = sp.get("stat") or {}
            games = stat.get("gamesPlayed")
            if tid is None or code not in ("h", "a") or not games:
                continue
            out.setdefault(int(tid), {})[code] = {
                key: int(stat.get("homeRuns") or 0), "g": int(games)}
        return out

    hit, pit = collect(hitting, "hr"), collect(pitching, "hr")
    out = {}
    for tid, h in hit.items():
        p = pit.get(tid) or {}
        if not all(k in h for k in ("h", "a")) or not all(k in p for k in ("h", "a")):
            continue
        home_g, away_g = h["h"]["g"], h["a"]["g"]
        if not home_g or not away_g:
            continue
        home = (h["h"]["hr"] + p["h"]["hr"]) / home_g
        away = (h["a"]["hr"] + p["a"]["hr"]) / away_g
        if not away:
            continue
        raw = home / away
        out[tid] = {
            "raw": raw,
            # Regressed toward a neutral park. This is the number the model
            # multiplies by; `raw` is kept so the page can show both and a
            # reader can see how much was taken off.
            "factor": 1.0 + (raw - 1.0) * PARK_REGRESSION,
            "home_games": home_g,
        }
    return out


def odds_ratio(batter: float, pitcher: float, league: float) -> float:
    """The log5 combination of two rates against a league baseline."""
    if league <= 0:
        return 0.0
    return max(0.0, batter * pitcher / league)


def hr_chance(batter_rate: float, pitcher_rate: float, league: float,
              park: float, pa_per_game: float) -> float:
    """Probability this batter homers at least once tonight.

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


# ------------------------------------------------------------- fetchers ---
# Three requests for the whole league, all free.

def all_batters(season: int) -> dict[int, dict]:
    """Every batter's season line, in one request.

    playerPool=All is not optional. The default pool is batting-title
    qualifiers -- about 130 players -- which would silently drop every
    platoon bat and half the bench, and the page would look complete while
    missing the players most likely to be a surprise.
    """
    return parse_batters(mlb_api._get(
        "/stats", stats="season", group="hitting", season=season,
        sportId=1, playerPool="All", limit=1500))


def park_factors(season: int) -> dict[int, dict]:
    """Every club's home-run park factor, in two requests."""
    hitting = mlb_api._get("/teams/stats", stats="statSplits", sitCodes="h,a",
                           season=season, group="hitting", sportIds=1, limit=100)
    pitching = mlb_api._get("/teams/stats", stats="statSplits", sitCodes="h,a",
                            season=season, group="pitching", sportIds=1, limit=100)
    return parse_park(hitting, pitching)


def build(starters: list[dict], season: int, verbose: bool = True) -> list[dict]:
    """The best bats in each of tonight's games, with a chance attached.

    `starters` is what mlb_api.probable_starters returns, and each row here is
    a batter facing the OTHER club's starter -- so a batter's opponent is the
    pitcher listed against his own team.
    """
    if not starters:
        return []
    table = all_batters(season)
    if not table:
        return []
    league = league_rate(table)
    parks = park_factors(season)

    # Games played per club, so a season plate-appearance total becomes a
    # per-game rate. Taken from the park splits, which counted them already.
    games = {tid: v["home_games"] * 2 for tid, v in parks.items()}

    by_team: dict[int, list] = {}
    for pid, r in table.items():
        if r["pa"] >= MIN_PA and r["team_id"]:
            by_team.setdefault(r["team_id"], []).append((pid, r))

    rows = []
    for s in starters:
        # This starter's opponent is the club whose batters we are rating.
        opp_id = s.get("opponent_id")
        pitcher = mlb_api.pitcher_season(s.get("pitcher_id"), season) or {}
        bf = pitcher.get("bf") or 0
        p_rate = (pitcher["hr"] / bf) if (bf and pitcher.get("hr") is not None) else None
        if p_rate is None:
            continue
        # The park belongs to the home club, and the starter's row says which
        # side he is on: if he is away, his own club is not the host.
        home_id = s.get("team_id") if s.get("is_home") else opp_id
        park = (parks.get(home_id) or {}).get("factor", 1.0)

        cand = []
        for pid, b in by_team.get(opp_id, []):
            gp = games.get(opp_id) or 0
            if not gp:
                continue
            pa_pg = b["pa"] / gp
            chance = hr_chance(b["hr"] / b["pa"], p_rate, league, park, pa_pg)
            cand.append({
                "batter_id": pid, "name": b["name"], "team_id": opp_id,
                "team": s.get("opponent"), "hr": b["hr"], "pa": b["pa"],
                "hr_rate": b["hr"] / b["pa"], "pa_per_game": pa_pg,
                "chance": chance,
                "vs": s.get("name"), "vs_hand": s.get("hand", ""),
                "vs_hr_per_bf": p_rate,
                "park": park, "park_raw": (parks.get(home_id) or {}).get("raw"),
                "league_rate": league,
                "commence_time": s.get("game_time"),
                "hr_at_projection": b["hr"], "homered": None,
            })
        cand.sort(key=lambda c: -c["chance"])
        rows.extend(cand[:TOP_N])

    rows.sort(key=lambda r: (r.get("commence_time") or "", -r["chance"]))
    if verbose:
        print(f"   batters: {len(rows)} bat(s) rated, league "
              f"{league * 100:.2f}% HR per PA")
    return rows


def grade(history: list[dict], table: dict[int, dict]) -> int:
    """Fill in whether each projected batter has homered since.

    Free, and that is the whole reason it is done this way. The leaderboard is
    refetched every morning, so a batter's season total today against the
    total stored when he was projected answers the question with no extra
    request and no way to quietly skip it.

    A row is graded once. Returns how many were newly settled.
    """
    graded = 0
    for row in history:
        if row.get("homered") is not None:
            continue
        now = table.get(row.get("batter_id"))
        if not now:
            continue
        before = row.get("hr_at_projection")
        if before is None:
            continue
        row["homered"] = bool(now["hr"] > before)
        graded += 1
    return graded


def summary(history: list[dict]) -> dict:
    """Calibration: what was promised against what happened.

    Not a win rate. A model that says 12% should be right about 12% of the
    time, and the honest test of it is whether the group it called 12% homered
    12% of the time -- not whether the top name went deep.
    """
    done = [r for r in history if r.get("homered") is not None]
    if not done:
        return {"graded": 0, "expected": None, "actual": None, "buckets": []}
    exp = sum(r["chance"] for r in done) / len(done)
    act = sum(1 for r in done if r["homered"]) / len(done)
    buckets = []
    edges = [(0.0, 0.08), (0.08, 0.12), (0.12, 0.18), (0.18, 1.0)]
    for lo, hi in edges:
        grp = [r for r in done if lo <= r["chance"] < hi]
        if not grp:
            continue
        buckets.append({
            "label": f"{lo * 100:.0f}-{hi * 100:.0f}%",
            "n": len(grp),
            "expected": round(sum(r["chance"] for r in grp) / len(grp) * 100, 1),
            "actual": round(sum(1 for r in grp if r["homered"]) / len(grp) * 100, 1),
        })
    return {"graded": len(done), "expected": round(exp * 100, 1),
            "actual": round(act * 100, 1), "buckets": buckets}


def _self_test() -> None:
    payload = {"stats": [{"splits": [
        {"player": {"id": 1, "fullName": "Big Bat"}, "team": {"id": 113},
         "stat": {"homeRuns": 40, "plateAppearances": 600}},
        {"player": {"id": 2, "fullName": "Slap Hitter"}, "team": {"id": 113},
         "stat": {"homeRuns": 2, "plateAppearances": 500}},
        # Traded: two lines, one player, summed.
        {"player": {"id": 3, "fullName": "Moved On"}, "team": {"id": 135},
         "stat": {"homeRuns": 10, "plateAppearances": 200}},
        {"player": {"id": 3, "fullName": "Moved On"}, "team": {"id": 141},
         "stat": {"homeRuns": 5, "plateAppearances": 150}},
        # No plate appearances at all: not a rate, not counted.
        {"player": {"id": 4, "fullName": "Never Played"}, "team": {"id": 113},
         "stat": {"homeRuns": 0, "plateAppearances": 0}},
    ]}]}
    t = parse_batters(payload)
    assert t[1]["hr"] == 40 and t[1]["pa"] == 600
    assert t[3]["hr"] == 15 and t[3]["pa"] == 350, t[3]
    assert t[3]["team_id"] == 141, "a traded batter sits with his current club"
    assert 4 not in t, "a batter with no plate appearances is not a rate"

    lg = league_rate(t)
    assert round(lg, 5) == round(57 / 1450, 5), lg

    # ---- the odds ratio. Twice as good against twice as generous is four
    # times the league, not three and not one and a half.
    assert round(odds_ratio(0.06, 0.06, 0.03), 4) == 0.12
    assert odds_ratio(0.03, 0.03, 0.03) == 0.03, "average vs average is average"
    assert odds_ratio(0.05, 0.02, 0.0) == 0.0, "no league rate, no answer"

    # ---- the park factor, from home and away on both sides of the ball
    hitting = {"stats": [{"splits": [
        {"team": {"id": 115}, "split": {"code": "h"},
         "stat": {"homeRuns": 120, "gamesPlayed": 70}},
        {"team": {"id": 115}, "split": {"code": "a"},
         "stat": {"homeRuns": 80, "gamesPlayed": 70}}]}]}
    pitching = {"stats": [{"splits": [
        {"team": {"id": 115}, "split": {"code": "h"},
         "stat": {"homeRuns": 120, "gamesPlayed": 70}},
        {"team": {"id": 115}, "split": {"code": "a"},
         "stat": {"homeRuns": 80, "gamesPlayed": 70}}]}]}
    park = parse_park(hitting, pitching)
    # 240 home runs at home over 70 games against 160 away: a raw 1.50.
    assert round(park[115]["raw"], 2) == 1.50, park[115]
    # Halved toward neutral, because one season of splits is not a park.
    assert round(park[115]["factor"], 2) == 1.25, park[115]

    # A club missing half its splits is dropped rather than half-computed.
    assert parse_park(hitting, {"stats": [{"splits": []}]}) == {}

    # ---- the chance itself
    lgr = 0.030
    big = hr_chance(0.060, 0.040, lgr, 1.0, 4.2)
    small = hr_chance(0.005, 0.040, lgr, 1.0, 4.2)
    assert big > small, (big, small)
    assert 0.0 < big < 1.0
    # A hitter's park raises it; a pitcher's park lowers it.
    assert hr_chance(0.06, 0.04, lgr, 1.25, 4.2) > big
    assert hr_chance(0.06, 0.04, lgr, 0.80, 4.2) < big
    # More trips to the plate is more chance, and no trips is none.
    assert hr_chance(0.06, 0.04, lgr, 1.0, 5.0) > big
    assert hr_chance(0.06, 0.04, lgr, 1.0, 0) == 0.0
    # ---- grading, which costs nothing: today's season total against the
    # total recorded when the projection was made.
    hist = [
        {"batter_id": 1, "chance": 0.20, "hr_at_projection": 40, "homered": None},
        {"batter_id": 2, "chance": 0.05, "hr_at_projection": 2, "homered": None},
        {"batter_id": 9, "chance": 0.10, "hr_at_projection": 5, "homered": None},
        {"batter_id": 1, "chance": 0.20, "hr_at_projection": 39, "homered": True},
    ]
    now = {1: {"hr": 41, "pa": 610}, 2: {"hr": 2, "pa": 505}}
    n = grade(hist, now)
    assert n == 2, n
    assert hist[0]["homered"] is True, "41 against 40 is a home run"
    assert hist[1]["homered"] is False, "2 against 2 is not"
    assert hist[2]["homered"] is None, "a batter absent from the table waits"
    assert hist[3]["homered"] is True, "an already-graded row is not touched"
    assert grade(hist, now) == 0, "grading twice settles nothing new"

    # ---- calibration, not a win rate
    sm = summary(hist)
    assert sm["graded"] == 3, sm
    # Promised (20 + 5 + 20) / 3 = 15.0; delivered two of three.
    assert sm["expected"] == 15.0, sm["expected"]
    assert sm["actual"] == 66.7, sm["actual"]
    assert summary([])["graded"] == 0

    print("batters self-test: the model holds and grades itself")


if __name__ == "__main__":
    _self_test()
