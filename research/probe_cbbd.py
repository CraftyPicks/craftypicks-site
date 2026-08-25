#!/usr/bin/env python3
"""Probe v2 — what the free CollegeBasketballData tier actually gives us.

v1 had two flaws that this fixes:

  * it inspected the FIRST game returned, which was a D1-vs-non-D1 blowout
    nobody prices, so its empty lines array hid every question we cared
    about. This one hunts for games that actually carry lines.
  * every endpoint returns at most 3000 rows, so "3000 games" was the cap
    talking, not the season. This one walks date ranges to find the real
    coverage.

Still no analysis. Only facts about the data.

    CBBD_API_KEY=xxx python research/probe_cbbd.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, timedelta

API = "https://api.collegebasketballdata.com"
KEY = os.environ.get("CBBD_API_KEY", "").strip()


def call(path: str, **params) -> tuple[int, object]:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {KEY}",
        "Accept": "application/json",
        "User-Agent": "craftypicks-research/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            time.sleep(0.35)
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:                                  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def dump(label: str, obj: object, indent: str = "     ") -> None:
    if not isinstance(obj, dict):
        print(f"{indent}{label}: {str(obj)[:180]}")
        return
    print(f"{indent}{label}:")
    for k, v in obj.items():
        if isinstance(v, dict):
            print(f"{indent}  {k}:")
            for k2, v2 in v.items():
                print(f"{indent}    {k2:<26} = {v2}")
        elif isinstance(v, list):
            print(f"{indent}  {k:<28} = <list len={len(v)}> {str(v[:4])[:90]}")
        else:
            print(f"{indent}  {k:<28} = {v}")


def section(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def month_ranges(season: int):
    """A college season labelled 2025 runs Nov 2024 → Apr 2025."""
    start = date(season - 1, 11, 1)
    while start < date(season, 4, 30):
        nxt = (start.replace(day=28) + timedelta(days=8)).replace(day=1)
        yield start, min(nxt - timedelta(days=1), date(season, 4, 30))
        start = nxt


def main() -> int:
    if not KEY:
        print("No CBBD_API_KEY set.", file=sys.stderr)
        return 1
    print(f"key present: {KEY[:4]}…{KEY[-4:]} ({len(KEY)} chars)")

    # ------------------------------------------------- 1. lines, done right
    section("1. LINES — hunting for games that actually carry them")
    status, body = call("/lines", season=2025)
    print(f"   GET /lines?season=2025 → HTTP {status}, "
          f"{len(body) if isinstance(body, list) else '?'} rows (3000 = the cap)")

    if status != 200 or not isinstance(body, list):
        print(f"   BLOCKED: {body}")
        return 1

    with_lines = [g for g in body if g.get("lines")]
    print(f"   rows carrying at least one line: {len(with_lines)} of {len(body)}")

    if not with_lines:
        print("   None in this batch — trying a mid-January window, when every "
              "game on the board is priced.")
        st, bd = call("/lines", season=2025,
                      startDateRange="2025-01-10T00:00:00.000Z",
                      endDateRange="2025-01-20T00:00:00.000Z")
        if st == 200 and isinstance(bd, list):
            with_lines = [g for g in bd if g.get("lines")]
            print(f"   mid-January: {len(with_lines)} of {len(bd)} rows carry lines")

    if with_lines:
        g = with_lines[0]
        print(f"\n   example: {g.get('awayTeam')} @ {g.get('homeTeam')} "
              f"({g.get('awayScore')}-{g.get('homeScore')})")
        for i, ln in enumerate(g.get("lines", [])[:3]):
            dump(f"line entry {i}", ln)

        providers, open_spread, open_total, half_keys = Counter(), 0, 0, Counter()
        priced = 0
        for game in with_lines:
            priced += 1
            for ln in game.get("lines", []):
                providers[ln.get("provider")] += 1
                if ln.get("spreadOpen") is not None:
                    open_spread += 1
                if ln.get("overUnderOpen") is not None:
                    open_total += 1
                for k in ln:
                    kl = str(k).lower()
                    if "half" in kl or "period" in kl or "1h" in kl:
                        half_keys[k] += 1
        print(f"\n   priced games inspected: {priced}")
        print(f"   providers: {dict(providers)}")
        print(f"   entries with an OPENING spread: {open_spread}"
              f"   {'← CLV measurable' if open_spread else '← no opener, no CLV'}")
        print(f"   entries with an OPENING total:  {open_total}")
        print(f"   half/period line fields: {dict(half_keys) or 'NONE — first-half angle needs another source'}")

    # ------------------------------------- 2. real coverage, past the 3000 cap
    section("2. REAL COVERAGE — walking date ranges instead of trusting the cap")
    for season in (2023, 2025, 2026):
        total = priced_total = 0
        for a, b in month_ranges(season):
            st, bd = call("/lines", season=season,
                          startDateRange=f"{a.isoformat()}T00:00:00.000Z",
                          endDateRange=f"{b.isoformat()}T23:59:59.000Z")
            if st == 200 and isinstance(bd, list):
                total += len(bd)
                priced_total += sum(1 for x in bd if x.get("lines"))
                capped = " (CAPPED)" if len(bd) >= 3000 else ""
                print(f"   {season} {a:%b}: {len(bd):>5} games, "
                      f"{sum(1 for x in bd if x.get('lines')):>5} priced{capped}")
        print(f"   → {season} TOTAL: {total} games, {priced_total} with lines\n")

    # ------------------------------------------- 3. the nested bits, expanded
    section("3. NESTED STRUCTURES v1 printed as '<dict len=N>'")
    st, bd = call("/ratings/adjusted", season=2025)
    if st == 200 and isinstance(bd, list) and bd:
        dump("ratings row (Duke or first)", bd[0])

    st, bd = call("/stats/team/season", season=2025)
    if st == 200 and isinstance(bd, list) and bd:
        row = bd[0]
        print()
        dump("team season row", {k: v for k, v in row.items()
                                 if k in ("team", "games", "pace")})
        dump("teamStats", row.get("teamStats"))
        dump("opponentStats", row.get("opponentStats"))

    st, bd = call("/stats/player/season", season=2025)
    if st == 200 and isinstance(bd, list) and bd:
        row = bd[0]
        print()
        dump("player rebounds", row.get("rebounds"))
        dump("player fieldGoals", row.get("fieldGoals"))

    section("WHAT WE NOW KNOW")
    print("""   Openers present   → we can measure closing line value, the one
                         metric that separates edge from luck.
   Half lines present → your first-half angle is directly testable.
   Half lines absent  → we can still measure first-half RESULTS from
                         homePeriodPoints, but cannot grade a 1H bet.
   Coverage numbers  → decide which seasons we build on and which one
                         gets held out as the honest test.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
