"""What goes into the public play log, and what counts as already in it.

The bug this file was written for
---------------------------------
run_daily posted today's card into the log with

    existing_ids = {p["id"] for p in history if p["posted_date"] == today}

which only ever saw plays posted THIS morning. A play the card recommended
again the next morning -- the same event, the same market, the same side,
still the best number on the board -- had a different posted_date, so it
was not recognised and was appended a second time.

Two NFL plays in the log are already in it twice for exactly that reason.
Both are ungraded, so the duplicate is currently invisible; the moment they
settle, one bet is counted as two, with twice the stake and twice the
profit. A log that double-counts is worse than no log.

A play is one bet. It is identified by event, market and side -- which is
what `id` already is -- and it is in the log once, from the first morning it
was posted, whatever it was worth on later mornings.
"""
from __future__ import annotations


def dedupe(history: list[dict]) -> int:
    """Collapse repeated postings of the same ungraded play. Returns the
    number of entries dropped.

    Keeps the FIRST posting, not the last: the log's claim is "we said this
    on this morning at this price", and the earliest entry is the one that
    claim belongs to. A later, better price would flatter the record for a
    bet that was actually taken a day earlier.

    Graded plays are never touched. Two graded entries with one id would be
    a different and much worse bug, and quietly deleting one would hide it.
    """
    seen: set = set()
    keep: list[dict] = []
    dropped = 0
    for play in history:
        pid = play.get("id")
        if pid and not play.get("result"):
            if pid in seen:
                dropped += 1
                continue
            seen.add(pid)
        keep.append(play)
    if dropped:
        history[:] = keep
    return dropped


def post(history: list[dict], card: list[dict], today: str,
         posted_at: str) -> int:
    """Add today's card to the log, once per bet. Returns entries added."""
    dedupe(history)
    known = {p.get("id") for p in history if p.get("id")}
    added = 0
    for play in card:
        play["posted_date"] = today
        play["posted_at"] = posted_at
        play["result"] = None
        play["profit"] = 0.0
        if play["id"] in known:
            continue
        known.add(play["id"])
        history.append(dict(play))
        added += 1
    return added


def _self_test() -> None:
    # --- the exact shape of the live bug ------------------------------------
    # Same play, two mornings, two posted_dates. The old rule compared ids
    # only within one posted_date and so never saw the first entry.
    monday = {"id": "evt-h2h-Saints", "posted_date": "2026-08-24",
              "price": 120, "result": None}
    log = [dict(monday)]
    added = post(log, [{"id": "evt-h2h-Saints", "price": 135}],
                 "2026-08-25", "2026-08-25T10:33:58-04:00")
    assert added == 0, log
    assert len(log) == 1, log
    # The first morning's price is what the log claims, not the better one.
    assert log[0]["price"] == 120
    assert log[0]["posted_date"] == "2026-08-24"

    # --- self-healing on the duplicates already written ---------------------
    dirty = [dict(monday), dict(monday, posted_date="2026-08-25", price=135),
             {"id": "evt-h2h-Browns", "posted_date": "2026-08-24",
              "result": None}]
    assert dedupe(dirty) == 1
    assert [p["id"] for p in dirty] == ["evt-h2h-Saints", "evt-h2h-Browns"]
    assert dirty[0]["posted_date"] == "2026-08-24"

    # --- what must NOT be collapsed -----------------------------------------
    # A graded play is a fact about a day. Two graded entries with one id is
    # a worse bug than the one this fixes, and silently deleting one would
    # hide it rather than surface it.
    graded = [{"id": "x", "result": "win", "profit": 0.9},
              {"id": "x", "result": "loss", "profit": -1.0}]
    assert dedupe(graded) == 0 and len(graded) == 2

    # A settled play does not block the same fixture's id being posted again
    # -- it cannot happen for one event, but the rule should be about what is
    # still open, not about everything the log has ever held.
    reopened = [{"id": "y", "result": "loss"}]
    assert post(reopened, [{"id": "y"}], "2026-09-01", "t") == 0

    # A play with no id is never merged away on the strength of a missing key.
    anon = [{"id": None, "result": None}, {"id": None, "result": None}]
    assert dedupe(anon) == 0 and len(anon) == 2

    # --- a normal morning ---------------------------------------------------
    fresh: list[dict] = []
    n = post(fresh, [{"id": "a"}, {"id": "b"}], "2026-09-10", "stamp")
    assert n == 2 and len(fresh) == 2
    assert all(p["result"] is None and p["profit"] == 0.0 for p in fresh)
    assert all(p["posted_date"] == "2026-09-10" for p in fresh)
    # Two of the same id inside ONE card is also a duplicate.
    same = post(fresh, [{"id": "c"}, {"id": "c"}], "2026-09-10", "stamp")
    assert same == 1, fresh

    print("play_log self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
