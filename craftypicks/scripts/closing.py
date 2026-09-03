#!/usr/bin/env python3
"""Capture a late line on every posted play, and score it against our number.

Why this exists: win/loss takes thousands of bets to prove anything, because
coin flips are loud. Whether the market moved TOWARD our number is visible in
a couple of hundred plays, because it measures the price instead of the
outcome. If we're consistently getting a better number than the market
settles on, the edge is real even during a losing month. If we're not, no
amount of winning proves anything — we just ran hot.

Run a few hours after the card posts, close to when games start:

    ODDS_API_KEY=xxx python scripts/closing.py

Two things keep it inside the free tier: it asks only for the markets
actually on today's card, and it stands down entirely when the month's
credits are running low. The morning card always takes priority.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent
DATA = ROOT / "data"

import config              # noqa: E402
import find_plays          # noqa: E402
import odds_math as om     # noqa: E402
from odds_client import BudgetExhausted, OddsAPIError, OddsClient  # noqa: E402

# Don't spend the month's last credits on measurement — the card matters more.
SNAPSHOT_CREDIT_FLOOR = 120
# A "late line" only means something if it was taken near tip-off.
MAX_MINUTES_BEFORE = 240


def load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def save(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def closing_consensus(game: dict, market_key: str, side: str,
                      point: float | None, exclude_book: str | None = None) -> dict | None:
    """The market's vig-free opinion of `side`, at snapshot time.

    `exclude_book` drops the book we actually bet, exactly as the scanner
    does when it finds the play. This has to match on both ends or the
    comparison is rigged: we always take the best price on the board, and the
    best price beats a consensus that includes it every single time, with or
    without skill.
    """
    books = find_plays._fresh_books(game.get("bookmakers") or [])
    if exclude_book:
        books = [b for b in books if b.get("key") != exclude_book]

    # Player props are shaped differently: one market holds every pitcher,
    # the player sits in `description`, and `side` looks like "Name Over".
    # Matching them by outcome name the way sides are matched finds nothing,
    # so prop plays silently never got a closing line at all.
    if market_key.startswith("pitcher_") or market_key.startswith("batter_"):
        return _prop_consensus(books, side, point)
    fair_probs, best_dec, best_price, best_book = [], 0.0, None, None
    points_seen = []

    for book in books:
        market = next((m for m in book.get("markets", [])
                       if m.get("key") == market_key), None)
        if not market:
            continue
        outcomes = [o for o in market.get("outcomes", []) if o.get("price") is not None]
        if len(outcomes) != 2:
            continue

        if market_key != "h2h":
            anchor = find_plays._anchor_point(outcomes, game, market_key)
            if anchor is None:
                continue
            points_seen.append(anchor)
            # Only compare books sitting on the number we actually bet.
            ours = next((o for o in outcomes if o.get("name") == side), None)
            if ours is None or ours.get("point") is None or point is None:
                continue
            if abs(float(ours["point"]) - float(point)) > 1e-9:
                continue

        a, b = outcomes
        fa, fb = om.devig_pair(a["price"], b["price"], config.DEVIG_METHOD)
        for outcome, fair in ((a, fa), (b, fb)):
            if outcome.get("name") != side:
                continue
            fair_probs.append(fair)
            dec = om.american_to_decimal(outcome["price"])
            if dec > best_dec:
                best_dec, best_price, best_book = dec, float(outcome["price"]), book.get("title")

    if not fair_probs:
        return None
    fair = sum(fair_probs) / len(fair_probs)
    result = {
        "books": len(fair_probs),
        "fair_prob": round(fair, 5),
        "fair_price": om.prob_to_american(fair),
        "best_price": best_price,
        "best_book": best_book,
    }
    if points_seen:
        result["consensus_point"] = max(set(points_seen), key=points_seen.count)
    return result


def _prop_consensus(books: list[dict], side: str, point: float | None) -> dict | None:
    """Closing consensus for a player prop.

    `side` arrives as "Tarik Skubal Over" (scanner) or "Tarik Skubal Over"
    (screens) — player name then Over/Under. We split off the direction and
    match the remainder against each outcome's `description`, at the same
    number we actually bet.
    """
    if not side or point is None:
        return None
    parts = str(side).rsplit(" ", 1)
    if len(parts) != 2:
        return None
    player, direction = parts[0].strip().lower(), parts[1].strip().lower()
    if direction not in ("over", "under"):
        return None

    fairs, best_dec, best_price, best_book = [], 0.0, None, None
    for book in books:
        for market in book.get("markets", []):
            pair, our_price = {}, None
            for o in market.get("outcomes", []):
                desc = str(o.get("description", "")).strip().lower()
                if desc != player:
                    continue
                if o.get("point") is None or abs(float(o["point"]) - float(point)) > 1e-9:
                    continue
                nm = str(o.get("name", "")).lower()
                if nm.startswith("over"):
                    pair["over"] = float(o["price"])
                elif nm.startswith("under"):
                    pair["under"] = float(o["price"])
                if nm.startswith(direction):
                    our_price = float(o["price"])
            if "over" in pair and "under" in pair:
                fo, fu = om.devig_pair(pair["over"], pair["under"], config.DEVIG_METHOD)
                fairs.append(fo if direction == "over" else fu)
                if our_price is not None:
                    dec = om.american_to_decimal(our_price)
                    if dec > best_dec:
                        best_dec, best_price = dec, our_price
                        best_book = book.get("title")
    if not fairs:
        return None
    fair = sum(fairs) / len(fairs)
    return {"books": len(fairs), "fair_prob": round(fair, 5),
            "fair_price": om.prob_to_american(fair),
            "best_price": best_price, "best_book": best_book}


def minutes_until(iso: str | None, now: datetime) -> float | None:
    if not iso:
        return None
    try:
        start = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((start - now).total_seconds() / 60.0, 1)


# A play may only be captured once -- close_status is set and never cleared --
# so capturing early spends the only chance on a number that is not a closing
# number. Six NFL plays were snapshotted nineteen days before kickoff in
# August; the scoring gate below correctly threw all six away, and because they
# were already marked captured they could never be re-taken. The window is now
# enforced at capture time, not only at scoring time.
CAPTURE_WINDOW_MINUTES = MAX_MINUTES_BEFORE


def awaiting_close(history: list[dict], now: datetime) -> list[dict]:
    """Plays whose closing line should be taken on this run.

    Ungraded, not yet captured, and inside the window: at most
    CAPTURE_WINDOW_MINUTES before first pitch and no more than an hour after
    it. A play outside the window is left alone so a later run can take it,
    rather than being spent on a number taken days out.
    """
    out = []
    for p in history:
        if p.get("result") or p.get("close_status") is not None:
            continue
        mins = minutes_until(p.get("commence_time"), now)
        if mins is None:
            continue
        if -60 < mins <= CAPTURE_WINDOW_MINUTES:
            out.append(p)
    return out


def _self_test() -> None:
    base = datetime(2026, 9, 1, 21, 0, tzinfo=timezone.utc)

    def play(hours_ahead, **kw):
        start = base + timedelta(hours=hours_ahead)
        return {"commence_time": start.isoformat().replace("+00:00", "Z"),
                "pick": f"+{hours_ahead}h", **kw}

    hist = [
        play(2),            # inside the window -- take it
        play(0.5),          # about to start -- take it
        play(-0.5),         # just started -- still counts
        play(-3),           # long underway -- too late
        play(5),            # tonight but not yet close -- leave for a later run
        play(19 * 24),      # the August NFL case -- must never be taken now
        play(2, result="win"),          # already graded
        play(2, close_status="captured"),  # already taken
    ]
    got = [p["pick"] for p in awaiting_close(hist, base)]
    assert got == ["+2h", "+0.5h", "+-0.5h"], got
    assert "+456h" not in got, "a game nineteen days out is not a closing line"
    assert "+5h" not in got, "leave it pending; a later run can still take it"
    print("closing self-test: the capture window holds")


def main() -> int:
    now = datetime.now(timezone.utc)
    history = load(DATA / "history.json", {"plays": []})["plays"]

    pending = awaiting_close(history, now)
    if not pending:
        print("-- nothing to snapshot: no ungraded plays awaiting a late line")
        return 0

    needed: dict[str, set] = defaultdict(set)
    for p in pending:
        needed[p["sport_key"]].add(p["market"])
    print(f"-- {len(pending)} play(s) awaiting a late line across "
          f"{len(needed)} sport(s)")
    for sport, markets in needed.items():
        print(f"   {sport}: {', '.join(sorted(markets))}")

    try:
        client = OddsClient()
    except OddsAPIError as e:
        print(f"!! {e}", file=sys.stderr)
        return 1

    captured = skipped = 0
    for sport, markets in needed.items():
        if (client.credits_remaining is not None
                and client.credits_remaining < SNAPSHOT_CREDIT_FLOOR):
            print(f"!! only {client.credits_remaining} credits left; skipping the "
                  "snapshot so the morning card keeps running")
            break
        try:
            games = {g["id"]: g for g in client.odds(sport, markets=sorted(markets))}
        except (BudgetExhausted, OddsAPIError) as e:
            print(f"!! {sport} snapshot failed: {e}", file=sys.stderr)
            continue

        for play in [p for p in pending if p["sport_key"] == sport]:
            game = games.get(play.get("event_id"))
            if not game:
                play["close_status"] = "unavailable"
                skipped += 1
                continue
            snap = closing_consensus(game, play["market"], play["side"],
                                     play.get("point"), play.get("book_key"))
            if not snap:
                play["close_status"] = "no_match"
                skipped += 1
                continue

            mins = minutes_until(game.get("commence_time"), now)
            play["close_status"] = "captured"
            play["close_captured_at"] = now.isoformat(timespec="seconds")
            play["close_minutes_before"] = mins
            play["close_books"] = snap["books"]
            play["close_fair_price"] = snap["fair_price"]
            play["close_best_price"] = snap["best_price"]
            # Level: what our price is worth against the late consensus.
            close_edge = om.expected_value_pct(snap["fair_prob"], play["price"])
            play["close_edge"] = round(close_edge, 2)
            # Movement: how much BETTER that got between posting and tip-off.
            # This is the real signal. The level alone is always positive —
            # we take the best number on the board by definition — so only
            # the change tells us whether the market came to us or ran away.
            play["clv_ev"] = round(close_edge - float(play.get("edge_pct", 0.0)), 2)
            if snap.get("consensus_point") is not None and play.get("point") is not None:
                play["close_point"] = snap["consensus_point"]
                play["point_move"] = round(float(snap["consensus_point"]) - float(play["point"]), 2)
            captured += 1
            arrow = "↑" if play["clv_ev"] > 0 else "↓"
            print(f"   {arrow} {play.get('pick','?'):<26} posted "
                  f"{om.format_american(play['price'])} | edge at post "
                  f"{float(play.get('edge_pct',0)):+.1f}% → at close "
                  f"{close_edge:+.1f}% | moved {play['clv_ev']:+.2f}%"
                  f"  ({mins:.0f} min out)")

    save(DATA / "history.json", {"plays": history})
    print(f"-- captured {captured}, unavailable {skipped}")
    if client.credits_remaining is not None:
        print(f"-- credits: {client.credits_used_this_run} used, "
              f"{client.credits_remaining} left this month")

    scored = [p for p in history if p.get("clv_ev") is not None
              and (p.get("close_minutes_before") or 0) <= MAX_MINUTES_BEFORE]
    if scored:
        beat = sum(1 for p in scored if p["clv_ev"] > 0)
        avg = sum(p["clv_ev"] for p in scored) / len(scored)
        print(f"-- running CLV: {beat}/{len(scored)} plays beat the close "
              f"({beat/len(scored)*100:.1f}%), average {avg:+.2f}%")
        if len(scored) < 100:
            print(f"   ({len(scored)} plays is far too few to conclude anything — "
                  "this needs a couple hundred)")
    else:
        print("-- no plays yet inside the "
              f"{MAX_MINUTES_BEFORE}-minute window, so nothing is scored")

    # Refresh the public numbers so the record page reflects tonight's capture
    # rather than waiting for tomorrow morning's run.
    import stats as statsmod                                  # noqa: E402
    save(DATA / "stats.json", statsmod.compute(history))
    sys.path.insert(0, str(ROOT / "_src"))
    import build                                              # noqa: E402
    build.build()
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        _self_test()
        raise SystemExit(0)
    raise SystemExit(main())
