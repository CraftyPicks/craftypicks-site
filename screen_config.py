"""Every threshold from the V2.2 spec, in one place.

Nothing in screens.py hardcodes a number. If you tune the system,
you tune it here and the tests tell you what broke.
"""

SEASON = 2026

# Screen plays are tagged separately in the record so their closing-line
# value can be compared against the price-based scanner's.
SOURCE_TAG = "screen"

# ---- Screen A: Standard Over ------------------------------------------
SCREEN_A = {
    "min_pitcher_k_pct": 0.20,
    "min_vs_pa": 30,
    "min_vs_k_pct": 0.20,
    "max_vs_avg": 0.270,
    "max_vs_woba": 0.300,
    "min_opp_k_per_game": 8.00,
    "line_min": None,         # was 5.0 — bans lifted, any number allowed
    "line_max": None,         # was 5.5
    "worst_juice": None,        # was -150
    "max_bets_per_day": 2,      # ranked by opponent K/game, highest first
}

# ---- Screen B: Elite 6.5 Over -----------------------------------------
SCREEN_B = {
    "min_pitcher_k_pct": 0.27,
    "min_vs_pa": 30,
    "min_vs_k_pct": 0.20,
    "max_vs_avg": 0.270,
    "max_vs_woba": 0.300,
    "min_opp_k_per_game": 8.00,
    "line_max": None,           # was 6.5
    "min_odds": None,           # was +100 (plus money only)
    "min_k_per_9": 9.5,         # proxy for "genuine high-strikeout arm"
    "fade_list": [],            # pitcher ids you've flagged as matchup-only
}

# ---- Screen C: Under ---------------------------------------------------
SCREEN_C = {
    "min_pitcher_k_pct": 0.20,
    "max_opp_k_per_game": 8.00,
    "line_min": None,           # was 5.5
    "preferred_k_pct_min": 0.24,
    "preferred_k_pct_max": 0.26,
    "high_k_exclude_at": None,  # was 0.27
}

# Total screen plays per day, across A, B and C together. Screen A's own cap
# only limited Screen A — pitchers it rejected reappeared under B, so five
# qualifiers produced five bets from a "cap" of two.
MAX_SCREEN_PLAYS_PER_DAY = 3

# ---- Hard caps: apply to every screen, no exceptions -------------------
# All lifted. None means "no limit" — every check below is skipped rather
# than deleted, so restoring any single ban is a one-line edit and the
# methodology page updates itself to match.
HARD_CAPS = {
    "max_line": None,           # was 7.5
    "banned_line": None,        # was 4.5
    "worst_juice": None,        # was -150
}

# wOBA linear weights. Update yearly from FanGraphs' guts table.
WOBA_WEIGHTS = {
    "bb": 0.690, "hbp": 0.720, "1b": 0.880,
    "2b": 1.247, "3b": 1.578, "hr": 2.031,
}

# Break-even win rates, for reporting only.
def break_even(odds: int) -> float:
    """Win rate needed to not lose money at American odds."""
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)
