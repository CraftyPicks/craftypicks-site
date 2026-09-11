#!/usr/bin/env python3
"""The free work must sit ABOVE the already-posted guard, the paid work below.

This is a source-order test rather than a behavioural one on purpose. What
went wrong was not a wrong value; it was a correct guard placed one section
too early, so grading, the play-log dedupe and the root tidy were all skipped
on any run that was not the one posting the day's card. Nothing raised,
nothing printed a warning, and the site simply stopped keeping its own record
up to date -- which is the failure the whole track-record page exists to make
impossible.

A behavioural test would need the Odds API. This one needs nothing, runs in
milliseconds, and fails loudly the moment someone moves a line back.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SOURCE = (Path(__file__).resolve().parent / "run_daily.py").read_text()


def line_of(pattern: str) -> int:
    """First line number matching `pattern`, 1-based. Raises if absent."""
    for i, line in enumerate(SOURCE.splitlines(), start=1):
        if re.search(pattern, line):
            return i
    raise AssertionError(f"run_daily.py no longer contains {pattern!r}")


def _self_test() -> None:
    guard = line_of(r'posted\.get\("date"\) == today')

    # Free and idempotent: local file work and StatsAPI. Always runs.
    for what, pattern in (
        ("the root tidy", r"tidy\.run\("),
        ("the play-log dedupe", r"play_log\.dedupe\("),
        ("prop grading", r"prop_grader\.grade_pending\("),
        ("loading the play log", r'load_json\(DATA / "history\.json"'),
    ):
        at = line_of(pattern)
        assert at < guard, (
            f"{what} is at line {at}, below the already-posted guard at "
            f"{guard}. It costs nothing and is idempotent, so it must run on "
            f"every invocation -- including the retries that exist because "
            f"GitHub's scheduler drops runs.")

    # Paid: every one of these spends Odds API credits. Once a day only.
    for what, pattern in (
        ("buying odds", r"client\.odds\("),
        ("buying scores", r"client\.scores\("),
        ("posting the card", r"play_log\.post\("),
    ):
        at = line_of(pattern)
        assert at > guard, (
            f"{what} is at line {at}, ABOVE the guard at {guard}. A dropped "
            f"or retried run would spend a second set of credits.")

    # The early return has to rebuild, or a prop graded on a retry sits in
    # history.json all day without reaching the track record page.
    tail = SOURCE[SOURCE.index('posted.get("date") == today'):]
    early = tail[:tail.index("return 0") + len("return 0")]
    assert "_rebuild_pages()" in early, (
        "the early return after the guard does not rebuild the pages, so "
        "anything graded on a retry would not reach the site until tomorrow")

    print("run_daily order self-test: free work above the guard, paid below")


if __name__ == "__main__":
    _self_test()
