#!/usr/bin/env python3
"""What does the nflverse feed actually contain?

Diagnostic only. Reads public files, writes nothing, commits nothing.
Run it from the Actions tab and read the log.

It exists because the NFL boards must be built against field names that
were read rather than guessed, and the environment the plan was written in
could not reach any host but GitHub.
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


def get(url: str, want_json: bool = True):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"  !! {url} -> {type(e).__name__}: {e}")
        return None
    if want_json:
        return json.loads(raw.decode("utf-8"))
    return raw


def main() -> int:
    print("== releases")
    rels = []
    page = 1
    while True:
        url = RELEASES + f"?per_page=100&page={page}"
        page_data = get(url)
        if page_data is None:
            print("   nflverse unreachable. Try ESPN instead; see the spec.")
            return 1
        if not page_data:
            break
        rels.extend(page_data)
        if len(page_data) < 100:
            break
        page += 1
    for rel in rels:
        names = [a["name"] for a in rel.get("assets", [])]
        print(f"  {rel['tag_name']:24} {len(names):3} assets")
        for n in names:
            print(f"      {n}")

    # The asset we expect to carry weekly player lines.
    target = None
    for rel in rels:
        for a in rel.get("assets", []):
            if a["name"] in ("player_stats.csv.gz", "stats_player_week.csv.gz",
                             "player_stats_2026.csv.gz"):
                target = a
                break
        if target:
            break
    if not target:
        print("\n!! no player-stats asset matched the expected names.")
        print("   Read the asset list above and pick one by hand.")
        return 1

    print(f"\n== reading {target['name']}")
    raw = get(target["browser_download_url"], want_json=False)
    if raw is None:
        return 1
    text = gzip.decompress(raw).decode("utf-8", "replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    print(f"   {len(rows):,} rows")
    print(f"   columns ({len(reader.fieldnames or [])}):")
    for c in reader.fieldnames or []:
        print(f"      {c}")

    if rows:
        print("\n== one full row, verbatim")
        for k, v in rows[0].items():
            print(f"   {k:32} {v!r}")

    print("\n== rows per season")
    seasons: dict = {}
    for r in rows:
        s = r.get("season") or "?"
        seasons[s] = seasons.get(s, 0) + 1
    for s in sorted(seasons, key=str)[-6:]:
        print(f"   {s}: {seasons[s]:,}")

    print("\n== can we get team defence from this file?")
    print("   opponent column present:",
          any(c in (reader.fieldnames or [])
              for c in ("opponent_team", "opponent", "def_team")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
