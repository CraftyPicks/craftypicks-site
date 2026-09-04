#!/usr/bin/env python3
"""What do the CURRENT nflverse assets contain?

Diagnostic only. Reads public files, writes nothing, commits nothing.

Run one told us player_stats.csv.gz stops at 2024 -- it is the deprecated
asset. This one reads the three files the NFL boards would actually be
built on:

    stats_player_week_<year>.csv.gz   the live weekly player lines
    games.csv                         the schedule, to know who plays whom
    depth_charts_<year>.csv.gz        to know who starts

It also checks whether the current season's stats file exists yet, which
decides how much of the first weeks has to lean on last season.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import urllib.error
import urllib.request

RELEASES = "https://api.github.com/repos/nflverse/nflverse-data/releases"
UA = {"User-Agent": "craftypicks-probe/1.0"}
SEASON = 2026
PRIOR = 2025


def get(url: str, want_json: bool = True):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"  !! {url} -> {type(e).__name__}: {e}")
        return None
    return json.loads(raw.decode("utf-8")) if want_json else raw


def all_assets() -> dict:
    """Every asset name across every release, mapped to its download URL."""
    out, page = {}, 1
    while True:
        batch = get(f"{RELEASES}?per_page=100&page={page}")
        if batch is None:
            return {}
        if not batch:
            break
        for rel in batch:
            for a in rel.get("assets", []):
                out[a["name"]] = a["browser_download_url"]
        if len(batch) < 100:
            break
        page += 1
    return out


def read_csv_gz(url: str):
    raw = get(url, want_json=False)
    if raw is None:
        return None, None
    text = gzip.decompress(raw).decode("utf-8", "replace")
    reader = csv.DictReader(io.StringIO(text))
    return reader, list(reader)


def describe(label: str, assets: dict, name: str, show_row: bool = True,
             season_key: str = "season", extra=None) -> None:
    print(f"\n{'=' * 62}\n== {label}: {name}")
    url = assets.get(name)
    if not url:
        near = sorted(n for n in assets if n.startswith(name.split("_20")[0]))
        print(f"   NOT FOUND. Nearest names:")
        for n in near[-12:]:
            print(f"      {n}")
        return
    reader, rows = read_csv_gz(url)
    if rows is None:
        return
    print(f"   {len(rows):,} rows, {len(reader.fieldnames or [])} columns")
    print("   columns:")
    for c in reader.fieldnames or []:
        print(f"      {c}")
    if rows and show_row:
        # Prefer a recent, busy row over row zero -- row zero is often a
        # 1999 line with half its columns blank, which teaches nothing
        # about what a current row looks like.
        pick = rows[-1]
        print("   last row, verbatim:")
        for k, v in pick.items():
            print(f"      {k:34} {v!r}")
    if rows and season_key in (reader.fieldnames or []):
        seasons = {}
        for r in rows:
            s = r.get(season_key) or "?"
            seasons[s] = seasons.get(s, 0) + 1
        keys = sorted(seasons, key=lambda x: str(x))
        print(f"   seasons present: {keys[0]} .. {keys[-1]}")
    if extra:
        extra(reader, rows)


def main() -> int:
    assets = all_assets()
    if not assets:
        print("nflverse unreachable. Try ESPN instead; see the spec.")
        return 1
    print(f"== {len(assets):,} assets across all releases")

    for yr in (SEASON, PRIOR):
        name = f"stats_player_week_{yr}.csv.gz"
        print(f"   {name}: {'PRESENT' if name in assets else 'absent'}")

    describe(f"weekly player lines, {PRIOR}", assets,
             f"stats_player_week_{PRIOR}.csv.gz")

    if f"stats_player_week_{SEASON}.csv.gz" in assets:
        describe(f"weekly player lines, {SEASON}", assets,
                 f"stats_player_week_{SEASON}.csv.gz")

    def sched_extra(reader, rows):
        cur = [r for r in rows if (r.get("season") or "") == str(SEASON)]
        print(f"   {SEASON} games: {len(cur)}")
        for r in cur[:6]:
            print(f"      wk{r.get('week','?'):>2} {r.get('gameday','?')} "
                  f"{r.get('away_team','?')} @ {r.get('home_team','?')}")

    print(f"\n{'=' * 62}\n== schedule: games.csv")
    url = assets.get("games.csv")
    if url:
        raw = get(url, want_json=False)
        if raw is not None:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8", "replace")))
            rows = list(reader)
            print(f"   {len(rows):,} rows, {len(reader.fieldnames or [])} columns")
            print("   columns:")
            for c in reader.fieldnames or []:
                print(f"      {c}")
            sched_extra(reader, rows)
    else:
        print("   NOT FOUND")

    describe(f"depth charts, {SEASON}", assets,
             f"depth_charts_{SEASON}.csv.gz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
