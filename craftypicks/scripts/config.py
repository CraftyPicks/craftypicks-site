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

# Only post games starting today (in TIMEZONE below). The odds feed returns
# everything upcoming, so without this the card fills with Sunday's NFL games
# on a Tuesday. Two reasons that's bad: an edge measured four days out is
# mostly noise because the line still has to move, and a play that far ahead
# never lands inside the closing-line window, so it can never be scored.
SAME_DAY_ONLY = True

# ------------------------------------------------------------ player props --
# Props live on a per-event endpoint and cost one credit PER MARKET PER EVENT.
# A full MLB slate of two pitcher markets is ~900 credits a month against a
# free tier of 500, so on the free plan this has to stay tightly capped.
# Set PROP_MARKETS = [] to turn props off entirely.
# Strikeouts only. The screens read nothing else, and dropping pitcher_outs
# buys wider game coverage for fewer credits — more starters evaluated beats
# more markets on fewer games. Add "pitcher_outs" back if you want the price
# scanner hunting that market too, and lower PROP_MAX_EVENTS to compensate.
PROP_MARKETS = ["pitcher_strikeouts"]
PROP_SPORTS = ["baseball_mlb"]
PROP_MAX_EVENTS = 8            # games per day to pull props for
PROP_MIN_BOOKS = 4             # props are thinner than sides; expect fewer books
PROP_MIN_EDGE_PCT = 3.0        # and demand a bigger edge to compensate
PROP_CREDIT_FLOOR = 160        # don't touch props below this many credits left
MAX_PROPS_PER_DAY = 2          # keep props from crowding the whole card
REGIONS = "us"          # one region keeps the credit cost at 1x
ODDS_FORMAT = "american"

# ------------------------------------------------------------ play picking --
# A play is posted when the best price available beats the vig-free consensus
# fair price by at least this much, expressed as expected value in percent.
MIN_EDGE_PCT = 2.5

# A second, stricter gate: how many PERCENTAGE POINTS of true probability we
# think the market is wrong by. MIN_EDGE_PCT is a ratio, and ratios flatter
# longshots — a +200 dog clears 5% EV on a 1.7-point probability edge while a
# −200 favourite needs nearly 3. Requiring both means a dog has to be as
# genuinely mispriced as a favourite to make the card. Raise this to push the
# card further toward normal prices; drop it to 0 to disable.
MIN_EDGE_PP = 1.0

# Ceiling on believable edges. In a market priced by a dozen books, a 20%+
# edge is never real — it's a stale line, a mismatched number, or a book
# quoting something else. Anything above this is logged and thrown away.
MAX_EDGE_PCT = 12.0

# Books that haven't updated within this many minutes of the freshest book on
# the same game are ignored. Stale prices are the single biggest source of
# fake edges.
STALE_MINUTES = 25

# "power" corrects for books loading extra margin onto longshots.
# "proportional" is the naive method and will fill your card with +300 dogs.
DEVIG_METHOD = "power"

# Ignore games priced by fewer books than this — a thin consensus is not a
# consensus, it's noise.
MIN_BOOKS = 6

# Hard cap on how many plays go on the daily card, and per league. Keeping the
# card short is a feature: it stops a bad day from turning into 15 losses.
MAX_PLAYS_PER_DAY = 6
MAX_PLAYS_PER_LEAGUE = 3

# Slots reserved for the strikeout screens, on top of the daily cap. They run
# as a separate experiment and are judged on their own closing-line value, so
# they neither consume the scanner's allowance nor compete with it on edge.
SCREEN_EXTRA_SLOTS = 3

# Skip absurd prices. Long shots produce huge "edges" that are mostly noise.
# Price band. MAX_PRICE is the blunt lever for "stop showing me big dogs" —
# drop it to 150 for near-pick'em plays only, raise it to 250 to let longer
# prices back in. MIN_EDGE_PP above is the principled filter; this one is
# taste, and taste is allowed.
MIN_PRICE = -300
MAX_PRICE = 185

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

# Full-board extras. The vs-opponent line costs two free MLB requests per
# game and is display-only — set False if it ever slows the morning run.
SLATE_VS_OPPONENT = True

# ---- Credit pacing -----------------------------------------------------
# The Odds API bills credits as markets x regions per request, and the free
# tier is 500 a month. The core card (odds + scores) is cheap; player props
# are not — they are billed per event, so they are the item that decides
# whether the month lasts.
#
# Rather than a flat "stop below N" floor, the daily run reserves enough to
# post a card every remaining day of the cycle and spends props only out of
# what is genuinely left over. A quiet first week can no longer bankrupt the
# last one.
CREDIT_MONTHLY_ALLOWANCE = 500
CREDIT_RESET_DAY = 1           # day of month the allowance refills
CORE_CREDITS_PER_SPORT = len(MARKETS) + 2      # one odds pull + one scores pull


def days_until_reset(today) -> int:
    """Days left in this billing cycle, counting today."""
    import calendar
    day = min(CREDIT_RESET_DAY, calendar.monthrange(today.year, today.month)[1])
    if today.day < day:
        return day - today.day
    nxt_y, nxt_m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    day = min(CREDIT_RESET_DAY, calendar.monthrange(nxt_y, nxt_m)[1])
    from datetime import date
    return (date(nxt_y, nxt_m, day) - date(today.year, today.month, today.day)).days


def spare_credits(remaining, today, sports_in_season: int) -> int:
    """What's left after reserving a card for every remaining day.

    Returns a large number when the remaining balance is unknown, so a
    missing header never silently switches the extras off.
    """
    if remaining is None:
        return 10 ** 6
    reserve = CORE_CREDITS_PER_SPORT * max(1, sports_in_season) * days_until_reset(today)
    return int(remaining) - reserve
