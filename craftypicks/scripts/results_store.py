#!/usr/bin/env python3
"""A growing store of finished games, one file per league."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DATA = HERE.parent / "data" / "results"

import results  # noqa: E402


def path_for(league: str) -> pathlib.Path:
    """Where one league's finished games are kept.

    One file per league rather than one big file: they are written on
    different days as seasons start and end, and a single file would rewrite
    every league's history every morning for no reason.

    Does not create the directory. Callers that write are the ones that make
    it, so a read of a league we have never stored stays side-effect free.
    """
    return DATA / f"{league}.json"


def load(league: str) -> list[dict]:
    """Every finished game stored for a league, oldest first.

    A league we have never stored is an empty list. A league whose file
    exists but does not parse is NOT: it raises, after moving the unreadable
    file aside to <name>.bad.

    That asymmetry is the whole point. Returning [] for a corrupt file let
    append_day merge one day's finals onto nothing and write the result back,
    turning a torn 300-game store into a 1-game store with no exception
    raised anywhere. Losing a morning's ratings is recoverable; losing a
    season of history is not. The daily job wraps this call, so the raise
    costs one league's card and nothing else.
    """
    path = path_for(league)
    if not path.exists():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        bad = path.with_suffix(path.suffix + ".bad")
        try:
            os.replace(path, bad)
        except OSError:                                      # noqa: BLE001
            bad = None
        print(f"!! {path.name} is not valid JSON"
              + (f"; moved aside to {bad.name}" if bad else "")
              + "; refusing to treat it as empty", file=sys.stderr)
        raise RuntimeError(
            f"{path.name} is corrupt; not overwriting a store that had "
            f"content") from e
    return doc.get("games") or []


def _key(row: dict) -> tuple:
    return (row.get("date"), row.get("home"), row.get("away"))


def merge(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Existing results plus new ones, deduplicated and sorted by date.

    A row already present is replaced by the fresh copy, so a score corrected
    hours after the final lands on top of the wrong one instead of beside it.
    Games that are not finished, or that carry no score, are dropped: Elo would
    read an in-progress 0-0 as a genuine tie.

    Does not verify that a team name matches any other source's spelling. That
    is what the probe workflow is for, and doing it here would mean carrying an
    alias map into a module whose job is storage.
    """
    out = {_key(r): r for r in existing}
    for row in fresh:
        if not row.get("completed"):
            continue
        if row.get("home_score") is None or row.get("away_score") is None:
            continue
        if not row.get("home") or not row.get("away") or not row.get("date"):
            continue
        out[_key(row)] = row
    return sorted(out.values(), key=lambda r: (r["date"], r["home"]))


def _write_atomic(path: pathlib.Path, text: str) -> None:
    """Replace a file's contents in one step, or not at all.

    write_text() truncates and then writes, so a kill, a timeout or a full
    disk between the two leaves a half-written file on disk. This job runs
    unattended every morning and its own reader treats an unparsable store as
    a reason to raise, so a torn write would cost a season of results.

    Writing a sibling temp file and os.replace()-ing it is atomic on every
    platform this runs on: a reader sees either the old file or the new one,
    never a prefix of the new one. The temp file is in the same directory
    because os.replace across filesystems is not atomic (and on Windows not
    permitted at all). A failed write removes its own temp file rather than
    leaving .tmp litter next to the store.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def append_day(league: str, date_str: str, fetch=results.finals) -> int:
    """Fetch one day's finals for a league and add them to the store.

    Returns how many rows the store gained. A failed fetch returns 0 and
    leaves the file exactly as it was — an unattended job that empties its own
    history because a third-party endpoint had a bad minute is worse than one
    that skips a day.

    Does not backfill. One day per run is the whole design: a season
    accumulates for one request a day rather than 170 in one morning.

    A corrupt store propagates load()'s RuntimeError rather than being
    quietly rebuilt from one day's games. The caller in run_daily guards this
    call, so the cost is one league's ratings for one morning.
    """
    existing = load(league)
    try:
        fresh = fetch(league, date_str)
    except Exception as e:                                   # noqa: BLE001
        print(f"!! results for {league} {date_str} unavailable "
              f"({type(e).__name__}: {e}); store left alone", file=sys.stderr)
        return 0

    merged = merge(existing, fresh)
    gained = len(merged) - len(existing)
    if gained or merged != existing:
        _write_atomic(path_for(league),
                      json.dumps({"league": league, "games": merged}, indent=1))
    return gained


def _self_test() -> None:
    a = {"date": "2026-09-01", "home": "H", "away": "A",
         "home_score": 5, "away_score": 3, "completed": True}
    b = {"date": "2026-09-01", "home": "C", "away": "D",
         "home_score": 1, "away_score": 2, "completed": True}

    # Merging is idempotent: the same day fetched twice stores one copy.
    assert len(merge([], [a, b])) == 2
    assert len(merge([a, b], [a, b])) == 2
    assert len(merge([a], [a, b])) == 2

    # A corrected score replaces the earlier row rather than sitting beside it.
    fixed = {**a, "home_score": 6}
    out = merge([a, b], [fixed])
    assert len(out) == 2
    assert [r for r in out if r["home"] == "H"][0]["home_score"] == 6

    # Unfinished games are not results and must never enter the store; Elo
    # would treat a 0-0 game in progress as a genuine tie.
    live = {"date": "2026-09-01", "home": "E", "away": "F",
            "home_score": 0, "away_score": 0, "completed": False}
    assert merge([], [live]) == []

    # A row missing a score is dropped rather than stored as zero.
    assert merge([], [{"date": "2026-09-01", "home": "G", "away": "H",
                       "completed": True}]) == []

    # The store stays sorted by date, so a reader can trust the order and
    # ratings.run gets its input in the order it expects.
    later = {**a, "date": "2026-09-02", "home": "X", "away": "Y"}
    assert [r["date"] for r in merge([later], [a])] == \
        ["2026-09-01", "2026-09-02"]

    # --- the store on disk -------------------------------------------------
    # Everything below writes to a temporary directory. The previous version
    # of this test read the real data directory, which does not exist in a
    # fresh checkout, so its only append_day assertion compared [] to [] and
    # the whole write path was untested.
    global DATA
    real_data = DATA
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            DATA = pathlib.Path(tmpdir) / "results"

            def two_games(league, day):
                return [a, b]

            # A successful fetch creates the file and stores both games.
            assert append_day("mlb", "2026-09-01", fetch=two_games) == 2
            assert path_for("mlb").exists(), "a successful fetch must write"
            assert len(load("mlb")) == 2

            # The atomic write leaves no temp file behind for the next run to
            # trip over or for git to see.
            assert list(DATA.glob("*.tmp")) == [], \
                "os.replace must consume the temp file"

            # Running the same day twice is idempotent on disk, not just in
            # merge(): an unchanged store must not even be rewritten.
            before_bytes = path_for("mlb").read_bytes()
            assert append_day("mlb", "2026-09-01", fetch=two_games) == 0
            assert path_for("mlb").read_bytes() == before_bytes

            # A failed fetch leaves a file that had content exactly as it was.
            def boom(league, day):
                raise RuntimeError("ESPN is down")

            assert append_day("mlb", "2026-09-01", fetch=boom) == 0
            assert path_for("mlb").read_bytes() == before_bytes, \
                "a failed fetch must not touch the store"

            # A write that fails partway leaves the previous store exactly as
            # it was, and no .tmp beside it. Simulated by failing the rename,
            # which is the step a plain write_text() does not have: there,
            # the old contents are already gone by the time anything can go
            # wrong, which is the torn-file case this whole function exists
            # to prevent.
            real_replace = os.replace

            def failing_replace(src, dst):
                raise OSError("disk full")

            os.replace = failing_replace
            try:
                _write_atomic(path_for("mlb"), '{"league": "mlb", "games": []}')
            except OSError:
                pass
            else:                                            # pragma: no cover
                raise AssertionError("the write must not silently succeed")
            finally:
                os.replace = real_replace
            assert path_for("mlb").read_bytes() == before_bytes, \
                "a failed write must not damage the store it was replacing"
            assert list(DATA.glob("*.tmp")) == [], \
                "a failed write cleans up after itself"

            # A league never stored reads as empty rather than raising.
            assert load("nfl") == []

            # A torn file is NOT an empty store. load() must refuse it, and
            # append_day must not rebuild the season from one day's games.
            torn = '{"league": "nba", "games": [{"date": "2026-'
            DATA.mkdir(parents=True, exist_ok=True)
            path_for("nba").write_text(torn, encoding="utf-8")
            try:
                load("nba")
            except RuntimeError:
                pass
            else:                                            # pragma: no cover
                raise AssertionError("a corrupt store must not read as empty")
            assert (DATA / "nba.json.bad").read_text(encoding="utf-8") == torn, \
                "the unreadable file is moved aside, never discarded"

            # And the same file, restored, is still not clobbered by a fetch:
            # append_day propagates rather than overwriting history.
            path_for("nba").write_text(torn, encoding="utf-8")
            try:
                append_day("nba", "2026-09-01", fetch=two_games)
            except RuntimeError:
                pass
            else:                                            # pragma: no cover
                raise AssertionError("append_day overwrote a corrupt store")
    finally:
        DATA = real_data

    print("results_store self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
