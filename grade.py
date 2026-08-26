"""Grade posted plays against final scores.

Nothing here ever edits a price or removes a play. A play that was posted is
graded exactly as posted — that's the entire value of keeping a public log.
"""
from __future__ import annotations

from datetime import datetime, timezone

import odds_math as om


def score_map(events: list[dict]) -> dict[str, dict]:
    """event_id -> {'completed': bool, 'scores': {team: int}}"""
    out = {}
    for ev in events:
        scores = {}
        for s in (ev.get("scores") or []):
            try:
                scores[s["name"]] = float(s["score"])
            except (KeyError, TypeError, ValueError):
                continue
        out[ev.get("id")] = {
            "completed": bool(ev.get("completed")),
            "scores": scores,
            "home_team": ev.get("home_team"),
            "away_team": ev.get("away_team"),
        }
    return out


def grade_play(play: dict, event: dict) -> str | None:
    """Return 'win' | 'loss' | 'push', or None if it can't be graded yet."""
    if not event or not event.get("completed"):
        return None
    scores = event.get("scores") or {}
    home, away = play.get("home_team"), play.get("away_team")
    if home not in scores or away not in scores:
        return None
    hs, as_ = scores[home], scores[away]

    market = play["market"]
    side = play["side"]

    if market == "h2h":
        picked = hs if side == home else as_
        other = as_ if side == home else hs
        if picked > other:
            return "win"
        if picked < other:
            return "loss"
        return "push"

    if market == "spreads":
        point = float(play["point"])
        picked = hs if side == home else as_
        other = as_ if side == home else hs
        margin = picked + point - other
        if margin > 0:
            return "win"
        if margin < 0:
            return "loss"
        return "push"

    if market == "totals":
        point = float(play["point"])
        total = hs + as_
        if total == point:
            return "push"
        over = side.lower().startswith("over")
        if (total > point) == over:
            return "win"
        return "loss"

    return None


def grade_pending(history: list[dict], scores_by_sport: dict[str, dict]) -> int:
    """Fill in results on any pending play we now have a final score for."""
    graded = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for play in history:
        if play.get("result"):
            continue
        events = scores_by_sport.get(play.get("sport_key")) or {}
        result = grade_play(play, events.get(play.get("event_id")))
        if not result:
            continue
        play["result"] = result
        play["profit"] = om.profit_units(play["price"], play.get("stake", 1.0), result)
        play["graded_at"] = now
        ev = events.get(play.get("event_id")) or {}
        sc = ev.get("scores") or {}
        if sc:
            play["final_score"] = (
                f"{play.get('away_team')} {om._trim(sc.get(play.get('away_team'), 0))}"
                f" — {play.get('home_team')} {om._trim(sc.get(play.get('home_team'), 0))}"
            )
        graded += 1
    return graded


def pending_sports(history: list[dict]) -> set[str]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        p["sport_key"] for p in history
        if not p.get("result") and (p.get("commence_time") or "") < now
    }
