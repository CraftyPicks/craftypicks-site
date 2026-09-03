"""The home-run board: which lineups go deep, against pitchers who allow it.

Free, entirely. Every number comes from MLB's own StatsAPI -- the starter's
home runs allowed per nine, and the opposing lineup's home runs per game --
and no Odds API credit is spent building this page.

That is also its limit, and the page says so. There are no home-run prices
here because a batter home-run market is billed per event, and this project
has not yet shown that its strikeout projection beats the line it is priced
against. Buying a second prop market before the first one has earned its keep
would be spending money to find out we were wrong twice.

So this is a matchup board, not a card. It says which lineups hit home runs
and which pitchers give them up. What a reader does with that is theirs.
"""
from __future__ import annotations

import statistics

import mlb_api

# How far from the league average a club or a pitcher has to sit before the
# matchup is worth naming. Half a standard deviation, the same band the
# strikeout matchup uses, so the two pages mean the same thing by "favourable".
BAND_SD = 0.5


def summarise(values: dict) -> dict:
    """Mean, spread and rank over a {key: number} map. Rank 1 is the largest."""
    clean = {k: v for k, v in (values or {}).items() if v is not None}
    if not clean:
        return {"mean": 0.0, "sd": 0.0, "rank": {}, "n": 0}
    order = sorted(clean, key=lambda k: -clean[k])
    return {
        "mean": statistics.mean(clean.values()),
        "sd": statistics.pstdev(clean.values()),
        "rank": {k: i + 1 for i, k in enumerate(order)},
        "n": len(clean),
    }


def verdict(value, stats: dict) -> str:
    """"favourable", "tough" or "neutral", from the pitcher's point of view.

    Favourable here means the ball leaves the park -- a lineup that homers a
    lot, or a pitcher who gives them up. The page is read by someone thinking
    about an over, so "favourable" is phrased from that side and labelled as
    such rather than left ambiguous.
    """
    if value is None or not stats or not stats.get("sd"):
        return "neutral"
    delta = value - stats["mean"]
    if delta >= stats["sd"] * BAND_SD:
        return "favourable"
    if delta <= -stats["sd"] * BAND_SD:
        return "tough"
    return "neutral"


def build(starters: list[dict], season: int, verbose: bool = True) -> list[dict]:
    """One row per probable starter, with the home-run matchup behind him.

    Requests: one per starter for his season line, one per opponent for the
    lineup rate. Both are free and both are cached inside mlb_api for the life
    of the process, so a slate where two starters face the same club costs one
    lookup, not two.
    """
    if not starters:
        return []

    lineup_rate: dict[int, float] = {}
    for s in starters:
        tid = s.get("opponent_id")
        if tid and tid not in lineup_rate:
            rate = mlb_api.team_hr_per_game(tid, season)
            if rate is not None:
                lineup_rate[tid] = rate
    lineup_stats = summarise(lineup_rate)

    seasons: dict[int, dict] = {}
    for s in starters:
        pid = s.get("pitcher_id")
        if pid and pid not in seasons:
            seasons[pid] = mlb_api.pitcher_season(pid, season) or {}
    allowed = {pid: v.get("hr_per_9") for pid, v in seasons.items()}
    pitcher_stats = summarise(allowed)

    rows = []
    for s in starters:
        pid, tid = s.get("pitcher_id"), s.get("opponent_id")
        st = seasons.get(pid) or {}
        # A pitcher with almost no innings has a rate but not a meaningful
        # one. Shown, never ranked, and never given a verdict.
        thin = (st.get("innings") or 0) < 20
        rows.append({
            "pitcher_id": pid,
            "name": s.get("name"),
            "hand": s.get("hand", ""),
            "team": s.get("team"),
            "opponent": s.get("opponent"),
            "opponent_id": tid,
            "commence_time": s.get("game_time"),
            "innings": st.get("innings"),
            "hr_allowed": st.get("hr"),
            "hr_per_9": st.get("hr_per_9"),
            "hr_per_9_rank": None if thin else pitcher_stats["rank"].get(pid),
            "pitchers_ranked": pitcher_stats["n"],
            "league_hr_per_9": pitcher_stats["mean"] or None,
            "opp_hr_per_game": lineup_rate.get(tid),
            "opp_hr_rank": lineup_stats["rank"].get(tid),
            "teams_ranked": lineup_stats["n"],
            "league_hr_per_game": lineup_stats["mean"] or None,
            "thin": thin,
            "lineup_verdict": verdict(lineup_rate.get(tid), lineup_stats),
            "pitcher_verdict": ("neutral" if thin
                                else verdict(st.get("hr_per_9"), pitcher_stats)),
        })

    rows.sort(key=lambda r: r.get("commence_time") or "")
    if verbose:
        print(f"   homers: {len(rows)} starter(s), league "
              f"{lineup_stats['mean']:.2f} HR/game, "
              f"{pitcher_stats['mean']:.2f} HR/9 allowed")
    return rows


def _self_test() -> None:
    vals = {1: 1.6, 2: 1.2, 3: 0.8}
    s = summarise(vals)
    assert round(s["mean"], 2) == 1.20, s["mean"]
    assert s["rank"] == {1: 1, 2: 2, 3: 3}, s["rank"]
    assert s["n"] == 3

    # Half a standard deviation either side of the mean is the neutral band.
    assert verdict(1.6, s) == "favourable"
    assert verdict(0.8, s) == "tough"
    assert verdict(1.2, s) == "neutral"

    # A missing number is never a verdict, and never a crash.
    assert verdict(None, s) == "neutral"
    assert verdict(1.6, {}) == "neutral"
    assert verdict(1.6, {"mean": 1.2, "sd": 0.0}) == "neutral", \
        "no spread means no ranking anyone against anyone"

    # None values are dropped before the statistics, not counted as zero.
    mixed = summarise({1: 2.0, 2: None, 3: 1.0})
    assert mixed["n"] == 2 and round(mixed["mean"], 2) == 1.50, mixed

    assert summarise({}) == {"mean": 0.0, "sd": 0.0, "rank": {}, "n": 0}
    assert build([], 2026, verbose=False) == []
    print("homers self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
