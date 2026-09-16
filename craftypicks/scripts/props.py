"""Pitcher prop scanning.

Props differ from sides in two ways that matter:

  * They live on a per-event endpoint, one game at a time, and cost a credit
    per market per event. On the free tier that limits us to a handful of
    games a day — see PROP_MAX_EVENTS.
  * A single prop market contains many players. Outcomes carry a
    `description` holding the player name, so Over/Under pairs have to be
    matched on player AND number. Pairing them the way we pair sides would
    de-vig one pitcher's over against a different pitcher's under and
    manufacture nonsense.

The value method is otherwise identical: de-vig each book's pair, average
across the others, and look for a book out of line with that consensus.
"""
from __future__ import annotations

from collections import defaultdict

import config
import find_plays
import odds_math as om

PROP_LABEL = {
    "pitcher_strikeouts": "Strikeouts",
    "pitcher_outs": "Outs recorded",
    "pitcher_hits_allowed": "Hits allowed",
    "pitcher_earned_runs": "Earned runs",
    "pitcher_walks": "Walks",
}


def reasons_for(play: dict) -> list[str]:
    return [
        f"Vig-free consensus across <b>{play['books_counted']} books</b> is "
        f"{om.format_american(play['fair_price'])}",
        f"Best number on the board is <b>{om.format_american(play['price'])} "
        f"at {play['book']}</b>",
        f"<b>{play['books_shorter']} of {play['books_counted']}</b> books price "
        "this shorter than we're getting it",
        f"Expected value at that price: <b>+{play['edge_pct']:.1f}%</b> per unit risked",
    ]


def pick_events(games: list[dict], limit: int) -> list[dict]:
    """Which games to spend prop credits on.

    Earliest starts first — those are the ones a reader can still act on by
    the time they read the card, and it's a rule that can't be accused of
    cherry-picking after the fact.
    """
    ordered = sorted(games, key=lambda g: g.get("commence_time") or "")
    return ordered[:limit]
