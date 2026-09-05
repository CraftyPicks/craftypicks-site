#!/usr/bin/env python3
"""What differs between leagues: naming, routing, and which views exist.

One place for the facts that are not the same in every sport, so the renderer
never has to ask what sport it is looking at. A spread is a "run line" in
baseball and a "spread" everywhere else; MLB has a props page and college
basketball does not.

Deliberately holds no odds, no schedule and no ratings — it is configuration,
not data, and nothing here changes between one build and the next.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402


@dataclass(frozen=True)
class League:
    """One league's naming and routing facts.

    Does not say whether the league is in season. That changes daily and is
    answered by the Odds API's own /sports call, not by configuration.
    """
    short: str
    sport_key: str
    label: str
    spread_key: str      # i18n key for this league's word for a spread
    # Unused by build.py: _EXTRA_VIEWS there now keys each league's extra
    # pages directly, replacing the branch that used to read this field.
    # Left in place (out of scope for this pass) rather than deleted, so
    # its own self-test assertions below are the only thing exercising it.
    has_props: bool


# NCAAB is board-only on purpose: 110 games a night across three prop markets
# would cost more credits per month than the entire rest of the site.
LEAGUES: dict[str, League] = {
    "mlb":   League("mlb",   "baseball_mlb",        "MLB",
                    "mkt_run_line", True),
    "nba":   League("nba",   "basketball_nba",      "NBA",
                    "mkt_spread", True),
    "nfl":   League("nfl",   "americanfootball_nfl", "NFL",
                    "mkt_spread", True),
    "ncaab": League("ncaab", "basketball_ncaab",    "NCAAB",
                    "mkt_spread", False),
}

# Navigation order. Not alphabetical and not by popularity: it is the order
# these leagues came onto the site, which keeps the nav stable as seasons
# start and end rather than reshuffling under a returning reader.
ORDER = ("mlb", "nba", "nfl", "ncaab")


def by_sport_key(sport_key: str) -> League | None:
    """The league for an Odds API sport key, or None if we do not cover it.

    Resolves the aliases config keeps for pre-season feeds, so an NFL
    pre-season key lands on NFL rather than on nothing.

    Does not raise for an unknown key. The API adds sports we do not cover,
    and a daily job must skip those rather than die on them.
    """
    key = config.LEAGUE_ALIASES.get(sport_key, sport_key)
    for league in LEAGUES.values():
        if league.sport_key == key:
            return league
    return None


def market_label_key(short: str, market: str) -> str:
    """The i18n key naming a market as this league says it.

    Does not return the label itself. Reader-facing text lives in i18n and is
    resolved at render time in the page's own language; returning a string
    here would freeze the site into English.
    """
    if market == "spreads":
        league = LEAGUES.get(short)
        return league.spread_key if league else "mkt_spread"
    return {"h2h": "mkt_moneyline", "totals": "mkt_total"}.get(market, market)


def _self_test() -> None:
    # Every league config points at a sport key config actually pulls.
    for short, league in LEAGUES.items():
        assert league.short == short, f"{short} keyed under the wrong name"
        assert league.sport_key in config.LEAGUES, \
            f"{short}: {league.sport_key} is not in config.LEAGUES"

    # Every league config has a nav position, and every nav position exists.
    assert set(ORDER) == set(LEAGUES), "ORDER and LEAGUES disagree"

    # Baseball is the reason this module exists: its spread has another name.
    assert market_label_key("mlb", "spreads") == "mkt_run_line"
    assert market_label_key("nba", "spreads") == "mkt_spread"
    assert market_label_key("nfl", "spreads") == "mkt_spread"
    assert market_label_key("mlb", "h2h") == "mkt_moneyline"
    assert market_label_key("mlb", "totals") == "mkt_total"

    # An unknown league falls back rather than raising: a market label is not
    # worth taking the daily build down for.
    assert market_label_key("cricket", "spreads") == "mkt_spread"

    # Sport keys resolve, including the pre-season alias.
    assert by_sport_key("baseball_mlb").short == "mlb"
    assert by_sport_key("americanfootball_nfl_preseason").short == "nfl"
    assert by_sport_key("soccer_epl") is None

    # NCAAB is board-only and at least one league has props, or the props
    # page has no reason to exist.
    assert LEAGUES["ncaab"].has_props is False
    assert any(l.has_props for l in LEAGUES.values())

    # Every key this module hands out resolves to real copy in every language
    # the site can publish. A key with no entry renders as "[[mkt_run_line]]"
    # on the page rather than raising, so nothing else would catch this.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_src"))
    import i18n  # noqa: E402

    for short in ORDER:
        for market in ("h2h", "spreads", "totals"):
            key = market_label_key(short, market)
            for lang in i18n.ALL_LANGS:
                value = i18n.t(key, lang)
                assert not value.startswith("[["), \
                    f"{key} has no {lang} entry in i18n"

    print("leagues self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
