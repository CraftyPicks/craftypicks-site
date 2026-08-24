"""Craftypicks configuration.

Everything you'd want to tune lives here. Edit these values, commit, and the
next daily run uses them.
"""

# ---------------------------------------------------------------- leagues ---
# Sport keys used by The Odds API. The pipeline only pulls leagues that the
# API reports as in-season, so leaving all four on year-round is fine and
# costs nothing extra.
LEAGUES = {
    "basketball_nba":  {"label": "NBA",   "short": "nba"},
    "americanfootball_nfl": {"label": "NFL", "short": "nfl"},
    "baseball_mlb":    {"label": "MLB",   "short": "mlb"},
    "basketball_ncaab": {"label": "NCAAB", "short": "ncaab"},
}

# Preseason / secondary keys that should be folded into the same tab as their
# parent league when they happen to be in season.
LEAGUE_ALIASES = {
    "americanfootball_nfl_preseason": "americanfootball_nfl",
}

# ---------------------------------------------------------------- markets ---
# h2h = moneyline, spreads = point spread, totals = over/under.
# COST WARNING: one credit per market per region per request.
MARKETS = ["h2h", "spreads", "totals"]
REGIONS = "us"          # one region keeps the credit cost at 1x
ODDS_FORMAT = "american"

# ------------------------------------------------------------ play picking --
# A play is posted when the best price available beats the vig-free consensus
# fair price by at least this much, expressed as expected value in percent.
MIN_EDGE_PCT = 2.0

# Ignore games priced by fewer books than this — a thin consensus is not a
# consensus, it's noise.
MIN_BOOKS = 6

# Hard cap on how many plays go on the daily card, and per league. Keeping the
# card short is a feature: it stops a bad day from turning into 15 losses.
MAX_PLAYS_PER_DAY = 6
MAX_PLAYS_PER_LEAGUE = 3

# Skip absurd prices. Long shots produce huge "edges" that are mostly noise.
MIN_PRICE = -350
MAX_PRICE = 400

# Flat staking. Every play is the same size — this is what keeps the record
# honest, and it is not negotiable in the grading math.
STAKE_UNITS = 1.0

# ------------------------------------------------------------ api budgeting --
# The Odds API free tier is 500 credits per month. Typical daily spend with
# 3 markets x 1 region across two in-season leagues is ~6 for odds plus ~4 for
# grading = ~10/day = ~300/month. This floor makes the run bail out rather
# than blow the whole month in one bad loop.
MIN_CREDITS_REMAINING = 40

API_BASE = "https://api.the-odds-api.com/v4"

# --------------------------------------------------------------- site copy --
SITE_NAME = "Craftypicks"
POST_TIME_LABEL = "9:00 AM ET"
TIMEZONE = "America/New_York"

# Paste your beehiiv embed URL here after creating the publication.
# Looks like: https://embeds.beehiiv.com/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
BEEHIIV_EMBED_URL = ""
