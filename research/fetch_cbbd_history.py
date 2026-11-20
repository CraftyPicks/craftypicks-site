#!/usr/bin/env python3
"""Download past college basketball seasons from CollegeBasketballData.com,
for the System's multi-season backtest. One-time; free tier.

Saves CBBD's raw answers, unparsed, so nothing is lost to a guess about
field names: for each season, gzipped JSON lists from

    /lines        closing spread, total and final score per game
    /games        game details, including the neutral-site flag
    /games/teams  team box scores: rebounds, steals, three-pointers...

into research/history_ncaab/{season}_{lines|games|teams}.json.gz.

Every endpoint answers at most 3000 rows, so each season is walked in date
windows; a window that comes back full is split in half and fetched again
rather than silently truncated. A season already on disk is skipped, so a
re-run only fetches what is missing. Calls stop at CALL_BUDGET, well under
the free tier's 1,000 a month (a full run is about 150).

    CBBD_API_KEY=xxx python research/fetch_cbbd_history.py
    CBBD_API_KEY=xxx python research/fetch_cbbd_history.py --seasons 2024,2025

Stdlib only.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

API = "https://api.collegebasketballdata.com"
OUT = Path(__file__).resolve().parent / "history_ncaab"
CAP = 3000              # rows an endpoint returns at most
CALL_BUDGET = 400       # stop well short of the free tier's 1,000 a month
SEASONS = (2021, 2022, 2023, 2024, 2025, 2026)   # 2026 = the 2025-26 season
KINDS = {"lines": "/lines", "games": "/games", "teams": "/games/teams"}


class Budget(Exception):
    pass


class Client:
    def __init__(self, key: str, budget: int = CALL_BUDGET, opener=None, pause: float = 0.4):
        self.key, self.budget, self.calls = key, budget, 0
        self.opener = opener or urllib.request.urlopen
        self.pause = pause

    def get(self, path: str, **params):
        if self.calls >= self.budget:
            raise Budget(f"stopped at {self.calls} calls (budget {self.budget})")
        url = f"{API}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.key}", "Accept": "application/json",
            "User-Agent": "craftypicks-history/1.0"})
        for attempt in range(4):
            self.calls += 1
            try:
                with self.opener(req, timeout=90) as resp:
                    time.sleep(self.pause)
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise SystemExit(f"CBBD rejected the key ({e.code}). Check the CBBD_API_KEY secret.")
                if e.code == 429:
                    raise Budget("CBBD says the monthly call limit is used up (429)")
                time.sleep(2 ** attempt * self.pause)
            except (urllib.error.URLError, TimeoutError, ValueError):
                time.sleep(2 ** attempt * self.pause)
            if self.calls >= self.budget:
                raise Budget(f"stopped at {self.calls} calls (budget {self.budget})")
        raise RuntimeError(f"gave up on {path} {params}")


def season_span(season: int) -> tuple[date, date]:
    """A season runs from early November to the title game in April."""
    return date(season - 1, 11, 1), date(season, 4, 30)


def months(a: date, b: date):
    while a <= b:
        nxt = (a.replace(day=28) + timedelta(days=8)).replace(day=1)
        yield a, min(nxt - timedelta(days=1), b)
        a = nxt


def fetch_window(client: Client, path: str, season: int, a: date, b: date) -> list:
    """Rows for one date window; halves it while the answer comes back full."""
    rows = client.get(path, season=season,
                      startDateRange=f"{a.isoformat()}T00:00:00.000Z",
                      endDateRange=f"{b.isoformat()}T23:59:59.000Z")
    rows = rows if isinstance(rows, list) else []
    if len(rows) >= CAP and a < b:
        mid = a + (b - a) // 2
        return (fetch_window(client, path, season, a, mid)
                + fetch_window(client, path, season, mid + timedelta(days=1), b))
    return rows


def fetch_season(client: Client, season: int, out: Path = OUT) -> dict:
    """Fetch and save whatever of one season is not on disk yet."""
    out.mkdir(parents=True, exist_ok=True)
    got = {}
    for kind, path in KINDS.items():
        dest = out / f"{season}_{kind}.json.gz"
        if dest.exists():
            got[kind] = "on disk"
            continue
        a, b = season_span(season)
        rows = []
        for x, y in months(a, b):
            rows.extend(fetch_window(client, path, season, x, y))
        # Only a complete season is written, so an interrupted run never
        # leaves a half file that a re-run would mistake for done.
        with gzip.open(dest, "wt", encoding="utf-8") as f:
            json.dump(rows, f)
        got[kind] = len(rows)
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default=",".join(map(str, SEASONS)))
    args = ap.parse_args()
    key = os.environ.get("CBBD_API_KEY", "").strip()
    if not key:
        print("CBBD_API_KEY is not set.", file=sys.stderr)
        return 1
    client = Client(key)
    for season in [int(s) for s in args.seasons.split(",") if s.strip()]:
        try:
            got = fetch_season(client, season)
        except Budget as e:
            print(f"!! {season}: {e}. Re-run later; finished seasons are kept.")
            break
        print(f"-- {season}: " + ", ".join(f"{k} {v}" for k, v in got.items())
              + f"  ({client.calls} calls so far)")
    print(f"done: {client.calls} API call(s)")
    return 0


# --------------------------------------------------------------------- tests
def _self_test() -> None:
    import io
    import tempfile

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    log = []

    def fake(n_for):
        def opener(req, timeout=0):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
            a = q["startDateRange"][0][:10]
            b = q["endDateRange"][0][:10]
            log.append((urllib.parse.urlparse(req.full_url).path, a, b))
            assert req.headers["Authorization"] == "Bearer k"
            return Resp(json.dumps([{"a": a}] * n_for(a, b)).encode())
        return opener

    # A full window is split until each half fits.
    days = lambda a, b: (date.fromisoformat(b) - date.fromisoformat(a)).days + 1
    c = Client("k", opener=fake(lambda a, b: min(CAP, 200 * days(a, b))), pause=0)
    rows = fetch_window(c, "/lines", 2025, date(2024, 11, 1), date(2024, 11, 30))
    assert len(rows) == 200 * 30 and all(len(r) == 1 for r in rows), len(rows)
    # A season: three kinds, six month windows each, written gzipped; a
    # second run fetches nothing.
    log.clear()
    with tempfile.TemporaryDirectory() as tmp:
        c = Client("k", opener=fake(lambda a, b: 5), pause=0)
        got = fetch_season(c, 2025, Path(tmp))
        assert got == {"lines": 30, "games": 30, "teams": 30}, got
        assert c.calls == 18 and {p for p, _, _ in log} == {"/lines", "/games", "/games/teams"}
        with gzip.open(Path(tmp) / "2025_teams.json.gz", "rt") as f:
            assert len(json.load(f)) == 30
        c2 = Client("k", opener=fake(lambda a, b: 5), pause=0)
        assert fetch_season(c2, 2025, Path(tmp)) == {k: "on disk" for k in KINDS}
        assert c2.calls == 0
        # The budget stops a run before the free tier's limit, writing no half file.
        c3 = Client("k", budget=4, opener=fake(lambda a, b: 5), pause=0)
        try:
            fetch_season(c3, 2024, Path(tmp))
            raise AssertionError("budget not enforced")
        except Budget:
            pass
        assert not (Path(tmp) / "2024_lines.json.gz").exists()
    assert season_span(2026) == (date(2025, 11, 1), date(2026, 4, 30))
    assert len(list(months(*season_span(2026)))) == 6
    print("fetch_cbbd_history self-test: all invariants hold")


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        _self_test()
    else:
        sys.exit(main())
