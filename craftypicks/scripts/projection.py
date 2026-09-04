"""What every projection board on this site does identically.

Four things, none of which know what a sport is:

  * merge      -- append tonight's rows to the running history, once each
  * grade      -- settle a row against a season counting stat
  * calibration-- what was promised against what happened
  * error      -- how wrong a continuous projection was, against a baseline

The field names are arguments rather than constants because the boards
disagree about them and always will: a batter "homered", a receiver "scored",
a quarterback threw for a number that is not a verdict at all. Passing the
names in is what keeps this file from growing a branch per sport.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# The calibration buckets. Wide on purpose: narrow buckets on a few hundred
# rows report noise as though it were miscalibration.
DEFAULT_EDGES = ((0.0, 0.08), (0.08, 0.12), (0.12, 0.18), (0.18, 1.01))

# A nine-inning game runs about three hours. Six is deliberately generous:
# grading a minute early is a permanent wrong answer (grade_counting locks a
# verdict in for good), while grading an hour late costs nothing but waiting
# for the next run. Lopsided costs call for a lopsided margin.
GAME_HOURS = 6.0


def _parse_ts(value):
    """An ISO timestamp as an aware datetime, or None if it cannot be one.

    An offset-naive string (no tzinfo) is treated as UTC rather than the
    local clock -- everything this site stores comes from an API that hands
    out UTC. A trailing 'Z' parses natively under Python 3.11's
    fromisoformat; nothing extra is needed for it here.

    Returns None rather than raising for a missing, non-string, or malformed
    value -- every caller wants "cannot tell" to mean "cannot tell", not a
    traceback out of a data-quality problem in one row.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def game_over(row: dict, now=None, *, time_key: str = "commence_time") -> bool:
    """Whether this row's game has finished, so its result can be judged.

    Six hours is deliberately generous -- a nine-inning game runs about
    three, and grading a minute early is a permanent wrong answer while
    grading an hour late costs nothing but a later run.

    A row with no start time is NOT settled. Refusing to judge it is the
    conservative direction: an ungraded row is missing from the record, a
    wrongly graded one is a lie in it.
    """
    dt = _parse_ts(row.get(time_key))
    if dt is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    return now >= dt + timedelta(hours=GAME_HOURS)


def repair_premature(history: list[dict], now=None, *, verdict_key: str,
                     time_key: str = "commence_time") -> int:
    """Reset a verdict that was written before its game could have ended.

    A row that carries a verdict but whose game start time is still in the
    FUTURE relative to `now` could only have been graded by a run that ran
    before game_over's gate existed -- reset it to None so a later run can
    judge it honestly.

    This can only catch rows whose game has NOT yet started. A row graded
    early for a game that has since finished looks identical to a correctly
    graded row from here and cannot be told apart; it stays wrong. This is a
    one-time repair for the bug's blast radius, not a substitute for
    game_over gating grade_counting going forward.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    reset = 0
    for row in history:
        if row.get(verdict_key) is None:
            continue
        dt = _parse_ts(row.get(time_key))
        if dt is None or dt <= now:
            continue            # not certainly future -- leave it alone
        row[verdict_key] = None
        reset += 1
    return reset


def merge(history: list[dict], rows: list[dict],
          key_fields: tuple[str, ...]) -> int:
    """Append rows the history has not seen. Returns how many were added.

    Idempotent by construction: the boards are rebuilt several times a day
    and every rebuild re-projects the same players for the same games. A row
    is identified by the caller's key fields -- typically the player and the
    game -- and never stored twice.
    """
    seen = {tuple(r.get(f) for f in key_fields) for r in history}
    added = 0
    for row in rows:
        key = tuple(row.get(f) for f in key_fields)
        if key in seen:
            continue
        seen.add(key)
        history.append(dict(row))
        added += 1
    return added


def grade_counting(history: list[dict], totals: dict, *, id_key: str,
                   at_key: str, verdict_key: str, total_key: str,
                   settled=None) -> int:
    """Settle rows whose event is visible in a season counting stat.

    The trick that makes this free: the leaderboard is refetched anyway, so
    a player's season total now against the total stored when he was
    projected says whether the thing happened. No extra request, and no way
    to quietly skip finding out.

    A row is graded once. A player missing from the totals is left ungraded
    rather than recorded as a miss -- absent is not the same as no.

    `settled`, when given, is a callable taking a row and returning True once
    that row's event is over and may be judged. A row for which it returns
    False is skipped with its verdict left at None, so a later run -- after
    the event has actually happened -- can grade it. Without it (the
    default) a row is graded the moment its total changes, which is exactly
    the bug this parameter exists to let a caller close: a season total is
    unchanged before the game starts, so `total > before` reads as a
    definite, permanent miss hours early. Pass game_over here.
    """
    graded = 0
    for row in history:
        if row.get(verdict_key) is not None:
            continue
        if settled is not None and not settled(row):
            continue
        now = totals.get(row.get(id_key))
        if now is None:
            continue
        before = row.get(at_key)
        if before is None:
            continue
        total_value = now.get(total_key)
        if total_value is None:
            continue
        row[verdict_key] = bool(total_value > before)
        graded += 1
    return graded


def calibration(history: list[dict], *, verdict_key: str,
                chance_key: str = "chance",
                edges: tuple = DEFAULT_EDGES) -> dict:
    """What was promised against what happened.

    Not a win rate. A model that says 12% should be right about 12% of the
    time, and the honest test is whether the group it called 12% delivered
    12% -- not whether the top name came in.
    """
    done = [r for r in history if r.get(verdict_key) is not None]
    if not done:
        return {"graded": 0, "expected": None, "actual": None, "buckets": []}
    exp = sum(r[chance_key] for r in done) / len(done)
    act = sum(1 for r in done if r[verdict_key]) / len(done)
    buckets = []
    for lo, hi in edges:
        grp = [r for r in done if lo <= r[chance_key] < hi]
        if not grp:
            continue
        b_exp = sum(r[chance_key] for r in grp) / len(grp)
        b_act = sum(1 for r in grp if r[verdict_key]) / len(grp)
        buckets.append({
            "label": f"{lo * 100:.0f}-{min(hi, 1.0) * 100:.0f}%",
            "n": len(grp),
            "expected": round(b_exp * 100, 1),
            "actual": round(b_act * 100, 1),
        })
    return {"graded": len(done), "expected": round(exp * 100, 1),
            "actual": round(act * 100, 1), "buckets": buckets}


def error_summary(history: list[dict], *, actual_key: str,
                  projection_key: str, baseline_key: str = "baseline") -> dict:
    """How wrong a continuous projection was.

    Reports the naive baseline beside it -- the player's own average with no
    opponent adjustment -- because a projection that cannot beat that has an
    adjustment that is decoration, and the page should be able to say so.

    Bias is signed: negative means the projections ran high.

    IMPORTANT: baseline_mae must only ever be compared against mae_on_baseline_rows,
    never against mae. When baseline coverage is partial, mae is computed over all
    rows with both actual and projection, but baseline_mae is computed only over
    the subset that also carry a baseline. Comparing them when baseline_n is less
    than graded would conflate different populations and yield a misleading result.
    """
    done = [r for r in history if r.get(actual_key) is not None
            and r.get(projection_key) is not None]
    if not done:
        return {"graded": 0, "mae": None, "bias": None, "baseline_n": 0,
                "baseline_mae": None, "mae_on_baseline_rows": None}
    n = len(done)
    mae = sum(abs(r[actual_key] - r[projection_key]) for r in done) / n
    bias = sum(r[actual_key] - r[projection_key] for r in done) / n
    base = [r for r in done if r.get(baseline_key) is not None]
    baseline_n = len(base)
    base_mae = (sum(abs(r[actual_key] - r[baseline_key]) for r in base)
                / baseline_n) if base else None
    mae_on_base_rows = (sum(abs(r[actual_key] - r[projection_key]) for r in base)
                        / baseline_n) if base else None
    return {"graded": n, "mae": round(mae, 2), "bias": round(bias, 2),
            "baseline_n": baseline_n,
            "baseline_mae": round(base_mae, 2) if base_mae is not None else None,
            "mae_on_baseline_rows": round(mae_on_base_rows, 2) if mae_on_base_rows is not None else None}


def _self_test() -> None:
    # merge appends only what it has not seen
    hist: list = []
    rows = [{"id": 1, "when": "T1", "chance": 0.2},
            {"id": 2, "when": "T1", "chance": 0.1}]
    assert merge(hist, rows, ("id", "when")) == 2
    assert merge(hist, rows, ("id", "when")) == 0, "merge must be idempotent"
    assert len(hist) == 2

    # grade_counting settles a row once, and only once
    hist = [{"id": 1, "at": 10, "hit": None},
            {"id": 2, "at": 4, "hit": None},
            {"id": 3, "at": 7, "hit": None}]
    totals = {1: {"n": 11}, 2: {"n": 4}}          # 3 is absent
    n = grade_counting(hist, totals, id_key="id", at_key="at",
                       verdict_key="hit", total_key="n")
    assert n == 2, n
    assert hist[0]["hit"] is True                  # 11 > 10
    assert hist[1]["hit"] is False                 # 4 == 4
    assert hist[2]["hit"] is None                  # never seen, never graded
    assert grade_counting(hist, totals, id_key="id", at_key="at",
                          verdict_key="hit", total_key="n") == 0

    # grade_counting: absent vs empty record are different
    hist = [{"id": 1, "at": 10, "hit": None},
            {"id": 2, "at": 4, "hit": None}]
    totals = {1: {}}                               # empty record for id 1
                                                   # id 2 is absent
    n = grade_counting(hist, totals, id_key="id", at_key="at",
                       verdict_key="hit", total_key="n")
    assert n == 0, f"empty record should be skipped, got {n}"
    assert hist[0]["hit"] is None                  # empty record skipped
    assert hist[1]["hit"] is None                  # absent player skipped

    # grade_counting with settled=game_over: the critical fix. A row whose
    # game is hours away must not be graded a miss just because his season
    # total has not moved yet -- it must stay ungraded until the game ends.
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    hist = [{"id": 1, "at": 10, "hit": None, "commence_time": future}]
    totals = {1: {"n": 10}}                         # unchanged: looks like a miss
    n = grade_counting(hist, totals, id_key="id", at_key="at",
                       verdict_key="hit", total_key="n", settled=game_over)
    assert n == 0, "a future game must not be graded at all"
    assert hist[0]["hit"] is None, "grading a game hours early is the bug"
    # Running it again, still before the game, changes nothing.
    n = grade_counting(hist, totals, id_key="id", at_key="at",
                       verdict_key="hit", total_key="n", settled=game_over)
    assert n == 0 and hist[0]["hit"] is None
    # Once the game is in the past, the same row grades normally.
    hist[0]["commence_time"] = past
    n = grade_counting(hist, totals, id_key="id", at_key="at",
                       verdict_key="hit", total_key="n", settled=game_over)
    assert n == 1 and hist[0]["hit"] is False, hist[0]

    # A missing or malformed commence_time is never settled -- refusing to
    # judge it is the conservative direction (see game_over's docstring).
    for bad_time in (None, "", "not-a-timestamp"):
        row = {"id": 5, "at": 1, "hit": None, "commence_time": bad_time}
        assert grade_counting([row], {5: {"n": 5}}, id_key="id", at_key="at",
                              verdict_key="hit", total_key="n",
                              settled=game_over) == 0
        assert row["hit"] is None, bad_time

    # game_over itself: boundary and malformed-input behaviour.
    now = datetime.now(timezone.utc)
    assert game_over({"commence_time": (now - timedelta(hours=6, minutes=1))
                      .isoformat()}, now) is True
    assert game_over({"commence_time": (now - timedelta(hours=5, minutes=59))
                      .isoformat()}, now) is False
    assert game_over({"commence_time": None}, now) is False
    assert game_over({}, now) is False
    # An offset-naive timestamp is treated as UTC, not the local clock.
    naive_past = (now - timedelta(hours=7)).replace(tzinfo=None).isoformat()
    assert game_over({"commence_time": naive_past}, now) is True
    # A trailing 'Z' parses under Python 3.11 with no special-casing needed.
    z_past = (now - timedelta(hours=7)).isoformat().replace("+00:00", "Z")
    assert game_over({"commence_time": z_past}, now) is True

    # repair_premature resets a future-dated verdict and leaves a past-dated
    # one alone -- it can only catch what is provably still ahead of `now`.
    hist = [{"id": 1, "hit": True, "commence_time": future},   # premature
            {"id": 2, "hit": False, "commence_time": past},    # legitimate
            {"id": 3, "hit": None, "commence_time": future},   # nothing to reset
            {"id": 4, "hit": True, "commence_time": None}]     # can't tell, leave it
    n = repair_premature(hist, verdict_key="hit")
    assert n == 1, n
    assert hist[0]["hit"] is None, "a future-dated verdict must be reset"
    assert hist[1]["hit"] is False, "a past-dated verdict must not be touched"
    assert hist[2]["hit"] is None
    assert hist[3]["hit"] is True, "an unparseable time cannot be proven premature"

    # calibration reports promised against delivered, not a win rate
    hist = [{"chance": 0.5, "hit": True}, {"chance": 0.5, "hit": False},
            {"chance": 0.1, "hit": False}, {"chance": 0.1, "hit": False}]
    c = calibration(hist, verdict_key="hit")
    assert c["graded"] == 4
    assert c["expected"] == 30.0, c["expected"]
    assert c["actual"] == 25.0, c["actual"]
    assert [b["n"] for b in c["buckets"]] == [2, 2]

    # an ungraded history says so rather than dividing by zero
    empty = calibration([{"chance": 0.5, "hit": None}], verdict_key="hit")
    assert empty == {"graded": 0, "expected": None, "actual": None,
                     "buckets": []}, empty

    # error_summary: mean absolute error, signed bias, and the naive baseline
    hist = [{"proj": 100.0, "actual": 110.0, "baseline": 105.0},
            {"proj": 100.0, "actual": 80.0, "baseline": 90.0}]
    e = error_summary(hist, actual_key="actual", projection_key="proj")
    assert e["graded"] == 2
    assert e["mae"] == 15.0, e["mae"]
    assert e["bias"] == -5.0, e["bias"]            # projected 5 high on average
    assert e["baseline_n"] == 2
    assert e["baseline_mae"] == 7.5, e["baseline_mae"]
    assert e["mae_on_baseline_rows"] == 15.0, e["mae_on_baseline_rows"]

    # error_summary: partial baseline coverage must compute on like populations
    hist = [{"proj": 100, "actual": 110, "baseline": 105},
            {"proj": 100, "actual": 80, "baseline": 90},
            {"proj": 50, "actual": 200}]          # no baseline, huge miss
    e = error_summary(hist, actual_key="actual", projection_key="proj")
    assert e["graded"] == 3, e["graded"]
    assert e["mae"] == 60.0, e["mae"]              # (10 + 20 + 150) / 3
    assert e["baseline_n"] == 2, e["baseline_n"]
    assert e["baseline_mae"] == 7.5, e["baseline_mae"]  # (5 + 10) / 2
    assert e["mae_on_baseline_rows"] == 15.0, e["mae_on_baseline_rows"]  # (10 + 20) / 2

    print("projection self-test: the engine holds")


if __name__ == "__main__":
    _self_test()
