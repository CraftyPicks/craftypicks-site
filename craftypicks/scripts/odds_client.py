"""Thin client for The Odds API v4, with credit accounting and a mock mode.

Mock mode (CRAFTYPICKS_MOCK=1, or no API key present) generates plausible
synthetic odds so the whole pipeline can be developed and tested without
spending a single credit.
"""
from __future__ import annotations

import json
import os
import random
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import config


class OddsAPIError(RuntimeError):
    pass


class BudgetExhausted(RuntimeError):
    pass


class OddsClient:
    def __init__(self, api_key: str | None = None, mock: bool | None = None):
        self.api_key = api_key or os.environ.get("ODDS_API_KEY", "").strip()
        env_mock = os.environ.get("CRAFTYPICKS_MOCK", "").strip() == "1"
        self.mock = env_mock if mock is None else mock
        if not self.api_key and not self.mock:
            raise OddsAPIError(
                "No ODDS_API_KEY set. Add it as a GitHub secret, or run with "
                "CRAFTYPICKS_MOCK=1 to use synthetic data."
            )
        self.credits_used_this_run = 0
        self.credits_remaining: int | None = None

    # ------------------------------------------------------------------ http
    def _get(self, path: str, params: dict) -> list | dict:
        params = {**params, "apiKey": self.api_key}
        url = f"{config.API_BASE}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "craftypicks/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                used = resp.headers.get("x-requests-last")
                remaining = resp.headers.get("x-requests-remaining")
                if used:
                    self.credits_used_this_run += int(used)
                if remaining is not None:
                    self.credits_remaining = int(remaining)
                return json.loads(body)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 401:
                raise OddsAPIError(f"API key rejected (401). {detail}") from e
            if e.code == 429:
                raise BudgetExhausted(f"Monthly credit quota exhausted (429). {detail}") from e
            raise OddsAPIError(f"HTTP {e.code} from odds API: {detail}") from e
        except urllib.error.URLError as e:
            raise OddsAPIError(f"Network error reaching odds API: {e.reason}") from e

    def _check_budget(self):
        if (
            self.credits_remaining is not None
            and self.credits_remaining < config.MIN_CREDITS_REMAINING
        ):
            raise BudgetExhausted(
                f"Only {self.credits_remaining} credits left this month; "
                f"floor is {config.MIN_CREDITS_REMAINING}. Stopping so the rest "
                "of the month still runs."
            )

    # ------------------------------------------------------------- endpoints
    def in_season_sports(self) -> list[str]:
        """Which of our configured leagues are currently active. Free call."""
        if self.mock:
            return _mock_in_season()
        data = self._get("/sports", {})
        active = {s["key"] for s in data if s.get("active")}
        wanted = set(config.LEAGUES) | set(config.LEAGUE_ALIASES)
        return sorted(wanted & active)

    def odds(self, sport_key: str, markets: list[str] | None = None) -> list[dict]:
        """Current odds for one league.

        Costs one credit per market per region, so the closing snapshot passes
        only the markets actually sitting on today's card rather than all
        three. On a 500-credit month that difference is what keeps a second
        daily pull affordable.
        """
        if self.mock:
            return _mock_odds(sport_key)
        self._check_budget()
        return self._get(
            f"/sports/{sport_key}/odds",
            {
                "regions": config.REGIONS,
                "markets": ",".join(markets or config.MARKETS),
                "oddsFormat": config.ODDS_FORMAT,
                "dateFormat": "iso",
            },
        )

    def events(self, sport_key: str) -> list[dict]:
        """Upcoming games with start times and no odds. COSTS NOTHING.

        Checking this first is what stops us paying three credits to pull a
        272-game NFL board in August and then discarding all of it because
        none of those games are today.
        """
        if self.mock:
            return [{"id": g["id"], "sport_key": sport_key,
                     "commence_time": g["commence_time"],
                     "home_team": g["home_team"], "away_team": g["away_team"]}
                    for g in _mock_odds(sport_key)]
        return self._get(f"/sports/{sport_key}/events", {"dateFormat": "iso"})

    def event_odds(self, sport_key: str, event_id: str, markets: list[str]) -> dict:
        """Player props for one game. Costs one credit per market, per event.

        This is the expensive call in the whole project — there is no bulk
        version — which is why the caller caps how many events it asks for.
        """
        if self.mock:
            return _mock_event_props(sport_key, event_id)
        self._check_budget()
        return self._get(
            f"/sports/{sport_key}/events/{event_id}/odds",
            {
                "regions": config.REGIONS,
                "markets": ",".join(markets),
                "oddsFormat": config.ODDS_FORMAT,
                "dateFormat": "iso",
            },
        )

    def scores(self, sport_key: str, days_from: int = 2) -> list[dict]:
        """Recent final scores for grading. Costs 2 credits with daysFrom."""
        if self.mock:
            return _mock_scores(sport_key)
        self._check_budget()
        return self._get(
            f"/sports/{sport_key}/scores",
            {"daysFrom": str(days_from), "dateFormat": "iso"},
        )


# ---------------------------------------------------------------- mock data --
_TEAMS = {
    "baseball_mlb": [
        "Seattle Mariners", "Houston Astros", "Cleveland Guardians", "Detroit Tigers",
        "Pittsburgh Pirates", "Chicago Cubs", "San Diego Padres", "San Francisco Giants",
        "Atlanta Braves", "Philadelphia Phillies", "Milwaukee Brewers", "St. Louis Cardinals",
    ],
    "americanfootball_nfl": [
        "Green Bay Packers", "Chicago Bears", "Houston Texans", "Minnesota Vikings",
        "Cincinnati Bengals", "Buffalo Bills",
    ],
    "basketball_nba": [
        "Memphis Grizzlies", "Denver Nuggets", "Miami Heat", "Boston Celtics",
        "Phoenix Suns", "Sacramento Kings",
    ],
    "basketball_ncaab": [
        "Purdue Boilermakers", "Michigan State Spartans", "Gonzaga Bulldogs",
        "Saint Mary's Gaels", "Houston Cougars", "Baylor Bears",
    ],
}
_BOOKS = [
    ("draftkings", "DraftKings"), ("fanduel", "FanDuel"), ("betmgm", "BetMGM"),
    ("williamhill_us", "Caesars"), ("betrivers", "BetRivers"), ("pointsbetus", "PointsBet"),
    ("bovada", "Bovada"), ("mybookieag", "MyBookie"), ("betonlineag", "BetOnline"),
]


def _mock_in_season() -> list[str]:
    return ["baseball_mlb", "americanfootball_nfl"]


def _mock_odds(sport_key: str) -> list[dict]:
    rng = random.Random(f"odds-{sport_key}-{datetime.now(timezone.utc):%Y-%m-%d}")
    teams = _TEAMS.get(sport_key, _TEAMS["baseball_mlb"])
    games = []
    now = datetime.now(timezone.utc)
    for i in range(0, len(teams) - 1, 2):
        away, home = teams[i], teams[i + 1]
        base_prob = rng.uniform(0.40, 0.60)          # home win probability
        spread = round(rng.uniform(-7.5, 7.5) * 2) / 2
        total = round(rng.uniform(6.5, 9.5) * 2) / 2 if "baseball" in sport_key else \
            round(rng.uniform(36.5, 48.5) * 2) / 2
        books = []
        # one book gets a deliberately generous price so the finder has
        # something to find in mock runs
        lucky = rng.randrange(len(_BOOKS))
        for bi, (key, title) in enumerate(_BOOKS):
            wobble = rng.uniform(-0.012, 0.012)
            edge_gift = 0.045 if bi == lucky else 0.0
            p_home = min(0.92, max(0.08, base_prob + wobble - edge_gift))
            books.append({
                "key": key, "title": title,
                "last_update": now.isoformat(),
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": home, "price": _to_american(p_home * 1.024)},
                        {"name": away, "price": _to_american((1 - p_home) * 1.024)},
                    ]},
                    {"key": "spreads", "outcomes": [
                        {"name": home, "price": _to_american(0.5 * 1.045 + wobble - edge_gift), "point": spread},
                        {"name": away, "price": _to_american(0.5 * 1.045 - wobble), "point": -spread},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "price": _to_american(0.5 * 1.045 + wobble), "point": total},
                        {"name": "Under", "price": _to_american(0.5 * 1.045 - wobble - edge_gift), "point": total},
                    ]},
                ],
            })
        games.append({
            "id": f"mock{sport_key}{i}",
            "sport_key": sport_key,
            "commence_time": (now + timedelta(hours=rng.randint(4, 11))).isoformat(),
            "home_team": home, "away_team": away,
            "bookmakers": books,
        })
    return games


def _mock_scores(sport_key: str) -> list[dict]:
    rng = random.Random(f"scores-{sport_key}-{datetime.now(timezone.utc):%Y-%m-%d}")
    teams = _TEAMS.get(sport_key, _TEAMS["baseball_mlb"])
    out = []
    for i in range(0, len(teams) - 1, 2):
        away, home = teams[i], teams[i + 1]
        hi = rng.randint(0, 9) if "baseball" in sport_key else rng.randint(10, 34)
        ai = rng.randint(0, 9) if "baseball" in sport_key else rng.randint(10, 34)
        out.append({
            "id": f"mock{sport_key}{i}",
            "sport_key": sport_key,
            "completed": True,
            "home_team": home, "away_team": away,
            "scores": [
                {"name": home, "score": str(hi)},
                {"name": away, "score": str(ai)},
            ],
        })
    return out


_PITCHERS = ["Logan Webb", "Zack Wheeler", "Tarik Skubal", "Corbin Burnes",
             "Framber Valdez", "Sonny Gray"]


def _mock_event_props(sport_key: str, event_id: str) -> dict:
    """Synthetic pitcher props, shaped like the real per-event response."""
    rng = random.Random(f"props-{event_id}")
    now = datetime.now(timezone.utc)
    pitchers = rng.sample(_PITCHERS, 2)
    # One number per pitcher, shared across books — which is how real prop
    # markets look. Randomising it per book means no player/number group ever
    # reaches the book minimum, and the scanner silently finds nothing.
    lines = {p: rng.choice([4.5, 5.5, 6.5]) for p in pitchers}
    books = []
    lucky = rng.randrange(len(_BOOKS))
    for bi, (key, title) in enumerate(_BOOKS):
        outcomes = []
        for pitcher in pitchers:
            point = lines[pitcher]
            wobble = rng.uniform(-0.015, 0.015)
            gift = 0.05 if bi == lucky else 0.0
            p_over = 0.5 + wobble
            outcomes.append({"name": "Over", "description": pitcher, "point": point,
                             "price": _to_american((p_over - gift) * 1.045)})
            outcomes.append({"name": "Under", "description": pitcher, "point": point,
                             "price": _to_american((1 - p_over) * 1.045)})
        books.append({"key": key, "title": title, "last_update": now.isoformat(),
                      "markets": [{"key": "pitcher_strikeouts", "outcomes": outcomes}]})
    return {"id": event_id, "sport_key": sport_key,
            "commence_time": (now + timedelta(hours=3)).isoformat(),
            "home_team": "Home Team", "away_team": "Away Team", "bookmakers": books}


def _to_american(prob: float) -> int:
    """Convert an implied probability into a rounded American price."""
    prob = min(0.95, max(0.05, prob))
    dec = 1 / prob
    if dec >= 2:
        return int(round((dec - 1) * 100 / 5) * 5)
    return int(round(-100 / (dec - 1) / 5) * 5)
