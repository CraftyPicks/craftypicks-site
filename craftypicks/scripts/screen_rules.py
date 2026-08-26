"""The two over screens. Pure functions — no network, no state.

Every rule returns both a verdict and the reason, so a rejected pitcher
tells you which condition killed it. That matters when you're debugging
why a play you expected didn't show up.
"""

from screen_config import (SCREEN_A, SCREEN_B, HARD_CAPS,
                           WOBA_WEIGHTS, MAX_SCREEN_PLAYS_PER_DAY)
from screen_models import Play


# ---- Hard caps: checked before any screen runs -------------------------

def violates_hard_cap(c, side, odds):
    """Returns a reason string if any universal rule blocks this bet.

    A threshold of None means the rule is switched off — the check is skipped
    rather than removed, so any ban can be restored by putting its number
    back in screen_config.
    """
    if c.line is None:
        return "no posted line"
    if HARD_CAPS["max_line"] is not None and c.line >= HARD_CAPS["max_line"]:
        return f"line {c.line} is at/above the {HARD_CAPS['max_line']} coin-flip tier"
    if HARD_CAPS["banned_line"] is not None and c.line == HARD_CAPS["banned_line"]:
        return f"{HARD_CAPS['banned_line']} lines are never bet"
    if odds is None:
        return "no odds posted"
    if HARD_CAPS["worst_juice"] is not None and odds < HARD_CAPS["worst_juice"]:
        return f"juice {odds:+d} is worse than {HARD_CAPS['worst_juice']}"
    return None


# ---- Shared: the Savant-equivalent roster check ------------------------

def _roster_check(c, cfg):
    """PA / K% / AVG / wOBA gate used by Screens A and B."""
    v = c.vs_roster
    # Every threshold here honours None as "don't gate on this", the same way
    # the lifted bans do. That matters more for this block than anywhere else:
    # these four conditions are evaluated on a sample of a few dozen plate
    # appearances, where the standard error on a batting average is roughly
    # eighty points — wide enough that a .270 cutoff sorts noise, not skill.
    if cfg["min_vs_pa"] is not None and v.pa < cfg["min_vs_pa"]:
        return f"only {v.pa} PA vs this roster (need {cfg['min_vs_pa']})"

    k_pct, avg = v.k_pct, v.avg
    woba = v.woba(WOBA_WEIGHTS)

    if cfg["min_vs_k_pct"] is not None:
        if k_pct is None or k_pct < cfg["min_vs_k_pct"]:
            return f"vs-roster K% {_pct(k_pct)} below {_pct(cfg['min_vs_k_pct'])}"
    if cfg["max_vs_avg"] is not None:
        if avg is None or avg >= cfg["max_vs_avg"]:
            return f"vs-roster AVG {_three(avg)} not under {_three(cfg['max_vs_avg'])}"
    if cfg["max_vs_woba"] is not None:
        if woba is None or woba >= cfg["max_vs_woba"]:
            return f"vs-roster wOBA {_three(woba)} not under {_three(cfg['max_vs_woba'])}"
    return None


def _pct(x):
    return "n/a" if x is None else f"{x*100:.1f}%"


def _three(x):
    return "n/a" if x is None else f"{x:.3f}"


# ---- Screen A: Standard Over (the proven core) -------------------------

def screen_a(c):
    """Returns (Play, None) or (None, reason)."""
    cfg = SCREEN_A
    odds = c.over_odds

    if gaps := c.missing():
        return None, "missing " + ", ".join(gaps)

    blocked = violates_hard_cap(c, "OVER", odds)
    if blocked:
        return None, blocked

    if c.k_pct < cfg["min_pitcher_k_pct"]:
        return None, f"season K% {_pct(c.k_pct)} below {_pct(cfg['min_pitcher_k_pct'])}"
    if c.opp_k_per_game < cfg["min_opp_k_per_game"]:
        return None, f"opponent K/game {c.opp_k_per_game:.2f} below {cfg['min_opp_k_per_game']}"
    if cfg["line_min"] is not None and c.line < cfg["line_min"]:
        return None, f"line {c.line} below {cfg['line_min']}"
    if cfg["line_max"] is not None and c.line > cfg["line_max"]:
        return None, f"line {c.line} above {cfg['line_max']}"
    if cfg["worst_juice"] is not None and odds < cfg["worst_juice"]:
        return None, f"juice {odds:+d} worse than {cfg['worst_juice']}"

    roster_fail = _roster_check(c, cfg)
    if roster_fail:
        return None, roster_fail

    return Play(
        candidate=c, screen="A", side="OVER", line=c.line, odds=odds,
        reasons=[
            f"season K% {_pct(c.k_pct)}",
            f"opponent K/game {c.opp_k_per_game:.2f}",
            f"vs roster: {c.vs_roster.pa} PA, K% {_pct(c.vs_roster.k_pct)}, "
            f"AVG {_three(c.vs_roster.avg)}, wOBA {_three(c.vs_roster.woba(WOBA_WEIGHTS))}",
        ],
    ), None


# ---- Screen B: Elite Over ----------------------------------------------

def screen_b(c):
    cfg = SCREEN_B
    odds = c.over_odds

    if gaps := c.missing():
        return None, "missing " + ", ".join(gaps)

    blocked = violates_hard_cap(c, "OVER", odds)
    if blocked:
        return None, blocked

    if c.pitcher_id in cfg["fade_list"]:
        return None, "on the fade list"
    if c.k_pct < cfg["min_pitcher_k_pct"]:
        return None, f"season K% {_pct(c.k_pct)} below {_pct(cfg['min_pitcher_k_pct'])}"
    if c.opp_k_per_game < cfg["min_opp_k_per_game"]:
        return None, f"opponent K/game {c.opp_k_per_game:.2f} below {cfg['min_opp_k_per_game']}"
    if cfg["line_max"] is not None and c.line > cfg["line_max"]:
        return None, f"line {c.line} above {cfg['line_max']}"

    # "Genuine high-strikeout arm, not an inflated K% ground-baller."
    if c.k_per_9 is None or c.k_per_9 < cfg["min_k_per_9"]:
        return None, f"K/9 {c.k_per_9 or 0:.1f} below {cfg['min_k_per_9']} — not a volume K arm"

    roster_fail = _roster_check(c, cfg)
    if roster_fail:
        return None, roster_fail

    return Play(
        candidate=c, screen="B", side="OVER", line=c.line, odds=odds,
        reasons=[
            f"season K% {_pct(c.k_pct)}, K/9 {c.k_per_9:.1f}",
            f"opponent K/game {c.opp_k_per_game:.2f}",
            f"posted at {odds:+d}",
        ],
    ), None


# ---- Orchestration -----------------------------------------------------

def evaluate_all(candidates):
    """Run every candidate through every screen. Returns (plays, rejections).

    Two rules about precedence, both deliberate:

    * A pitcher clearing both A and B is taken as A. A is the proven screen,
      B is marginal, so the higher-confidence one wins.
    * A pitcher A rejected *because of the daily cap* is out for the day —
      he does not get a second life under B. Previously he did, which meant
      five qualifiers produced five bets from a cap of two. A cap that any
      other screen can walk around is not a cap.
    """
    plays, rejections = [], []

    a_qualifiers = []
    for c in candidates:
        play, reason = screen_a(c)
        if play:
            a_qualifiers.append(play)
        else:
            rejections.append((c, "A", reason))

    # Daily cap: rank by opponent K/game, highest first, take the top N.
    a_qualifiers.sort(key=lambda p: p.candidate.opp_k_per_game, reverse=True)
    cap = SCREEN_A["max_bets_per_day"]
    capped_out = set()
    for i, play in enumerate(a_qualifiers):
        if i < cap:
            plays.append(play)
        else:
            capped_out.add(play.candidate.pitcher_id)
            rejections.append((play.candidate, "A",
                               f"qualified but ranked #{i+1}, daily cap is {cap}"))

    taken = {p.candidate.pitcher_id for p in plays}

    for c in candidates:
        if c.pitcher_id in taken or c.pitcher_id in capped_out:
            continue
        play, reason = screen_b(c)
        if play:
            plays.append(play)
            taken.add(c.pitcher_id)
        else:
            rejections.append((c, "B", reason))


    # Global cap across both screens, A first — the order of how much the
    # spec trusts them.
    order = {"A": 0, "B": 1}
    plays.sort(key=lambda p: (order.get(p.screen, 9),
                              -(p.candidate.opp_k_per_game or 0)))
    if len(plays) > MAX_SCREEN_PLAYS_PER_DAY:
        for extra in plays[MAX_SCREEN_PLAYS_PER_DAY:]:
            rejections.append((extra.candidate, extra.screen,
                               f"over the {MAX_SCREEN_PLAYS_PER_DAY}-play daily total"))
        plays = plays[:MAX_SCREEN_PLAYS_PER_DAY]

    return plays, rejections
