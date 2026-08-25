#!/usr/bin/env python3
"""Find out exactly what the free CollegeBasketballData tier actually gives us.

No analysis here on purpose. Before writing a few hundred lines of testing
code against a guessed schema, we establish four things:

  1. Does the free key reach /lines at all, or is it a paid tier?
  2. How many seasons back do lines go, and how complete are they?
  3. Do they include OPENING numbers (needed for closing line value) and
     first-half lines (needed for the first-half angle)?
  4. What are the real field names on ratings, games, and stats?

Everything it learns gets printed. Nothing is assumed.

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

API = "https://api.collegebasketballdata.com"
KEY = os.environ.get("CBBD_API_KEY", "").strip()


def call(path: str, **params) -> tuple[int, object]:
    """Returns (http_status, parsed_body_or_error_text)."""
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
            time.sleep(0.4)
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except Exception as e:                                  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def show_fields(label: str, sample: object, limit: int = 40) -> None:
    if isinstance(sample, list):
        print(f"   {label}: list of {len(sample)}")
        sample = sample[0] if sample else None
    if isinstance(sample, dict):
        print(f"   {label} fields:")
        for k, v in list(sample.items())[:limit]:
            shown = v
            if isinstance(v, (list, dict)):
                shown = f"<{type(v).__name__} len={len(v)}>"
            print(f"     {k:<28} = {shown}")
    elif sample is not None:
        print(f"   {label}: {str(sample)[:200]}")


def section(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def main() -> int:
    if not KEY:
        print("No CBBD_API_KEY set. Add it as a repo secret and pass it through "
              "the workflow env.", file=sys.stderr)
        return 1
    print(f"key present: {KEY[:4]}…{KEY[-4:]} ({len(KEY)} chars)")

    # ---------------------------------------------------------------- lines
    section("1. BETTING LINES — the make-or-break question")
    status, body = call("/lines", season=2025)
    print(f"   GET /lines?season=2025 → HTTP {status}")
    if status == 200 and isinstance(body, list):
        print(f"   got {len(body)} game(s) with lines")
        if body:
            show_fields("game", body[0])
            inner = body[0].get("lines")
            if isinstance(inner, list) and inner:
                show_fields("one line entry", inner[0])
                providers = set()
                open_spread = open_total = half = 0
                for g in body[:1500]:
                    for ln in (g.get("lines") or []):
                        providers.add(ln.get("provider"))
                        if ln.get("spreadOpen") is not None:
                            open_spread += 1
                        if ln.get("overUnderOpen") is not None:
                            open_total += 1
                        if any("alf" in str(k) for k in ln):
                            half += 1
                print(f"\n   providers seen: {sorted(p for p in providers if p)}")
                print(f"   entries carrying an OPENING spread: {open_spread}")
                print(f"   entries carrying an OPENING total:  {open_total}")
                print(f"   entries mentioning a half/period line: {half}"
                      f"   {'← first-half angle is testable' if half else '← NO first-half lines'}")
    else:
        print(f"   BLOCKED OR EMPTY: {body}")
        print("   If this is 401/403, lines are not in the free tier and the "
              "whole plan needs rethinking. Report this exactly.")

    # how far back do lines go?
    print("\n   season coverage:")
    for season in (2019, 2021, 2023, 2024, 2025, 2026):
        st, bd = call("/lines", season=season)
        n = len(bd) if st == 200 and isinstance(bd, list) else 0
        print(f"     {season}: HTTP {st}, {n} games")

    # ------------------------------------------------------------- ratings
    section("2. ADJUSTED EFFICIENCY RATINGS")
    status, body = call("/ratings/adjusted", season=2025)
    print(f"   GET /ratings/adjusted?season=2025 → HTTP {status}")
    if status == 200:
        show_fields("rating", body)
        if isinstance(body, list):
            print(f"   teams rated: {len(body)}")
    else:
        print(f"   {body}")

    # --------------------------------------------------------------- games
    section("3. GAMES — results, and whether period scores exist for 1H")
    status, body = call("/games", season=2025, seasonType="regular")
    print(f"   GET /games?season=2025 → HTTP {status}")
    if status == 200 and isinstance(body, list):
        print(f"   games: {len(body)}")
        if body:
            show_fields("game", body[0])
            periods = [g for g in body[:200]
                       if any("period" in str(k).lower() or "half" in str(k).lower() for k in g)]
            print(f"\n   games exposing period/half scores: {len(periods)} of first 200")

    # --------------------------------------------------------------- stats
    section("4. TEAM & PLAYER SEASON STATS — rebounding, turnovers, balance")
    status, body = call("/stats/team/season", season=2025)
    print(f"   GET /stats/team/season?season=2025 → HTTP {status}")
    if status == 200:
        show_fields("team stat row", body, limit=60)

    status, body = call("/stats/player/season", season=2025)
    print(f"\n   GET /stats/player/season?season=2025 → HTTP {status}")
    if status == 200:
        show_fields("player stat row", body, limit=45)
        if isinstance(body, list):
            print(f"   player rows: {len(body)}")

    section("WHAT THIS DECIDES")
    print("""   lines present + openers present  → full ROI backtest with closing
                                        line value. Best case.
   lines present, no openers        → ROI backtest only, no CLV.
   half lines present               → the first-half angle is testable.
   lines 401/403                    → free tier excludes them; we fall back
                                        to effect-size work and rethink.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
