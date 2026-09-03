"""Rate every starter with a posted strikeout line, and keep score.

Same bargain as the MLB board: publish a number for every pitcher we can see,
not just the ones that become plays, and grade all of them. A screen that
posts two bets a day takes years to prove anything. Ten rated starters a
night produces a few hundred graded projections a month, and the average
miss is a claim precise enough to be wrong.

The projection is deliberately trivial:

    strikeouts = (K/9 / 9) x expected innings x opponent strikeout factor

No park, no weather, no catcher framing, no umpire. Those all move a
strikeout total slightly; none move it as much as which lineup he faces and
how long he stays in, and every extra input is another thing that can be
quietly wrong.

Everything here is free — MLB's game log carries the last-ten strip, the
vs-opponent line and the grading, and the prop odds were already pulled for
the scanner.
"""
from __future__ import annotations

from datetime import datetime, timezone

import config
import screen_config as scfg
import mlb_api
import matchup
import screen_source

# Expected innings for a starting pitcher. Modern starters average a shade
# over five; a high-strikeout arm is trusted slightly deeper. Getting this
# wrong is the single easiest way to produce a nonsense projection — an
# assumption of six innings puts every number roughly half a strikeout high.
IP_STANDARD = 5.3
IP_HIGH_K = 5.5
HIGH_K_PER_9 = 11.0

# League-average team strikeouts per game, used to turn the opponent's rate
# into a multiplier. Recomputed from the teams we look at each night rather
# than hardcoded, with this as the fallback.
LEAGUE_K_PER_GAME = 8.45

RECENT_STARTS = 10

# A projection this far from a posted line is our error, not an opportunity —
# the same guard the MLB board uses on win probability. A dozen books do not
# misprice a strikeout total by two and a half.
SUSPECT_GAP = 2.5


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def recent_starts(pitcher_id: int, season: int, limit: int = RECENT_STARTS) -> list[dict]:
    """The pitcher's most recent starts, oldest first."""
    out = []
    for sp in mlb_api.season_game_log(pitcher_id, season):
        stat = sp.get("stat") or {}
        if _num(stat.get("gamesStarted")) < 1:
            continue                       # relief outings aren't comparable
        out.append({
            "date": sp.get("date"),
            "opponent": (sp.get("opponent") or {}).get("name"),
            "strikeouts": int(_num(stat.get("strikeOuts"))),
            "innings": round(mlb_api._innings(stat.get("inningsPitched")), 1),
        })
    return out[-limit:]


def project(k_per_9: float | None, opp_k_per_game: float | None,
            league: float = LEAGUE_K_PER_GAME) -> float | None:
    if not k_per_9 or k_per_9 <= 0:
        return None
    innings = IP_HIGH_K if k_per_9 >= HIGH_K_PER_9 else IP_STANDARD
    factor = (opp_k_per_game / league) if (opp_k_per_game and league) else 1.0
    return round((k_per_9 / 9.0) * innings * factor, 1)


def opponent_split(table: dict, summary: dict, team_id: int,
                   hand: str) -> dict | None:
    """This lineup's strikeout rate against the hand the starter throws.

    None when there is no hand to measure against or the club is missing from
    the table, because a card that guesses is worse than a card that omits.

    rank_all rides along because it is what makes the split worth printing:
    Washington is 18th against everybody and 24th against right-handers, and
    only the second number applies to a right-hander.
    """
    hand_key = matchup.key_for(hand)
    if not hand_key:
        return None
    club = (table or {}).get(team_id) or {}
    if hand_key not in club:
        return None
    stats = (summary or {}).get(hand_key) or {}
    return {
        "k_pct": club[hand_key]["k_pct"],
        "pa": club[hand_key]["pa"],
        "rank": (stats.get("rank") or {}).get(team_id),
        "rank_all": ((summary or {}).get("all") or {}).get("rank", {}).get(team_id),
        "of": stats.get("n"),
        "league_mean": stats.get("mean"),
    }


def build(prop_events: list[dict], date_str: str, season: int,
          verbose: bool = True) -> list[dict]:
    """One rated row per starter who has a posted strikeout line."""
    if not prop_events:
        return []

    starters = mlb_api.probable_starters(date_str)
    if not starters:
        if verbose:
            print("   pitchers: no probable starters listed")
        return []
    by_name = {screen_source.normalize(s["name"]): s for s in starters}

    # The hand each starter throws with, and how every club hits that hand.
    # Both are single free requests. The projection does not use either --
    # scripts/study_matchup.py measured the signal against 86 finished starts
    # and found no detectable edge over the posted line -- so these are shown
    # to the reader and kept out of the number.
    try:
        hands = mlb_api.pitch_hands(s["pitcher_id"] for s in starters)
    except Exception:                                        # noqa: BLE001
        hands = {}
    try:
        k_table = mlb_api.team_k_splits(season)
    except Exception:                                        # noqa: BLE001
        k_table = {}
    k_summary = matchup.summarise(k_table)

    # League average from tonight's opponents, so the multiplier is relative
    # to the teams actually on the board rather than a stale constant.
    opp_rates: dict[int, float] = {}
    for s in starters:
        rate = mlb_api.team_k_per_game(s["opponent_id"], season)
        if rate:
            opp_rates[s["opponent_id"]] = rate
    league = (sum(opp_rates.values()) / len(opp_rates)) if opp_rates else LEAGUE_K_PER_GAME
    ranked = sorted(opp_rates.items(), key=lambda kv: -kv[1])
    rank_of = {tid: i + 1 for i, (tid, _r) in enumerate(ranked)}

    rows = []
    for event in prop_events:
        for player, quote in screen_source.lines_for_event(event).items():
            starter = by_name.get(player)
            if not starter:
                continue
            pid = starter["pitcher_id"]
            season_stats = mlb_api.pitcher_season(pid, season)
            opp_rate = opp_rates.get(starter["opponent_id"])
            projection = project(season_stats.get("k_per_9"), opp_rate, league)
            if projection is None:
                continue

            starts = recent_starts(pid, season)
            line = quote["line"]
            cleared = [s["strikeouts"] > line for s in starts]
            gap = round(projection - line, 1)

            try:
                vs = mlb_api.pitcher_vs_team(pid, starter["opponent_id"],
                                                season, verbose=False)
            except Exception:                                # noqa: BLE001
                vs = None

            rows.append({
                "pitcher_id": pid,
                "name": starter["name"],
                "team": starter["team"],
                "opponent": starter["opponent"],
                "opponent_id": starter["opponent_id"],
                "event_id": event.get("id"),
                "commence_time": event.get("commence_time"),
                "date": date_str,
                "line": line,
                "over_odds": quote.get("over"),
                "under_odds": quote.get("under"),
                "books": quote.get("books"),
                "projection": projection,
                "gap": gap,
                "suspect": abs(gap) > SUSPECT_GAP,
                "k_pct": season_stats.get("k_pct"),
                "k_per_9": season_stats.get("k_per_9"),
                "era": season_stats.get("era"),
                "w": season_stats.get("w"),
                "l": season_stats.get("l"),
                "innings": season_stats.get("innings"),
                "opp_k_per_game": opp_rate,
                "opp_k_rank": rank_of.get(starter["opponent_id"]),
                "opp_teams_ranked": len(ranked),
                "recent": starts,
                "recent_over": sum(cleared),
                "recent_n": len(starts),
                "last5_over": sum(cleared[-5:]),
                "last5_n": len(cleared[-5:]),
                "vs_opp": vs,
                "hand": hands.get(pid, ""),
                "opp_split": opponent_split(k_table, k_summary,
                                            starter["opponent_id"],
                                            hands.get(pid, "")),
                "matchup": matchup.verdict(k_table, k_summary,
                                           starter["opponent_id"],
                                           hands.get(pid, "")),
                "actual": None,
            })

    rows.sort(key=lambda r: r.get("commence_time") or "")
    if verbose:
        print(f"   pitchers: rated {len(rows)} starter(s), "
              f"league K/game {league:.2f}")
    return rows


def grade(history: list[dict], season: int, verbose: bool = True) -> int:
    """Fill in what each rated starter actually did. Free — the same game log."""
    graded = 0
    for row in history:
        if row.get("actual") is not None or not row.get("pitcher_id"):
            continue
        target = _iso_date(row.get("commence_time")) or _us_date(row.get("date"))
        if not target:
            continue
        for sp in mlb_api.season_game_log(row["pitcher_id"], season):
            if str(sp.get("date")) != target:
                continue
            stat = sp.get("stat") or {}
            if _num(stat.get("gamesStarted")) < 1:
                continue
            row["actual"] = int(_num(stat.get("strikeOuts")))
            row["actual_innings"] = round(
                mlb_api._innings(stat.get("inningsPitched")), 1)
            row["graded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            graded += 1
            break
    if verbose and graded:
        print(f"-- pitchers: graded {graded} projection(s)")
    return graded


def _iso_date(commence: str | None) -> str | None:
    """The local calendar date a game was played on."""
    if not commence:
        return None
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(str(commence).replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(config.TIMEZONE)).date().isoformat()
    except Exception:                                        # noqa: BLE001
        return None


def _us_date(date_str: str | None) -> str | None:
    try:
        return datetime.strptime(str(date_str), "%m/%d/%Y").date().isoformat()
    except (TypeError, ValueError):
        return None


def summary(history: list[dict]) -> dict:
    """How wrong the projections are, and whether the line beats them."""
    done = [r for r in history if r.get("actual") is not None]
    if not done:
        return {"rated": len(history), "graded": 0, "mae": None,
                "line_mae": None, "over_rate": None, "called_right": None,
                "buckets": []}

    mae = sum(abs(r["actual"] - r["projection"]) for r in done) / len(done)
    line_mae = sum(abs(r["actual"] - r["line"]) for r in done) / len(done)

    # Of the starters we called over, how many went over? Ties on the line
    # can't happen — books post halves — but a projection can sit exactly on
    # it, and those are excluded rather than counted as a call.
    calls = [r for r in done if abs(r["projection"] - r["line"]) >= 0.1]
    right = sum(1 for r in calls
                if (r["projection"] > r["line"]) == (r["actual"] > r["line"]))

    # Buckets are built from `calls`, not from every graded start. A
    # projection landing exactly on the posted number isn't a lean, so
    # counting it in the sample while it can never be scored as correct
    # would drag the tightest bucket down for no reason.
    buckets = []
    # The id is what the site renders from; the English label stays in the
    # file so an old stats reader (or a human opening the JSON) still gets a
    # sentence rather than a key.
    for lo, hi, bid, label in ((0.0, 0.5, "bk_half", "within half a strikeout"),
                               (0.5, 1.0, "bk_half_one", "half to one"),
                               (1.0, 2.0, "bk_one_two", "one to two"),
                               (2.0, 99.0, "bk_two_plus", "more than two")):
        inside = [r for r in calls if lo <= abs(r["projection"] - r["line"]) < hi]
        hit = sum(1 for r in inside
                  if (r["projection"] > r["line"]) == (r["actual"] > r["line"]))
        buckets.append({"id": bid, "label": label, "n": len(inside), "right": hit,
                        "pct": round(hit / len(inside) * 100, 1) if inside else 0.0})

    return {
        "rated": len(history),
        "graded": len(done),
        "mae": round(mae, 2),
        "line_mae": round(line_mae, 2),
        "over_rate": round(sum(1 for r in done if r["actual"] > r["line"])
                           / len(done) * 100, 1),
        "called_right": round(right / len(calls) * 100, 1) if calls else None,
        "calls": len(calls),
        "buckets": buckets,
    }
