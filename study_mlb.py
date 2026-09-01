#!/usr/bin/env python3
"""Does starting-pitcher quality actually move run totals — and by how much?

This is a study, not a betting system. It answers one question honestly:
when both starters have been good this season, do fewer runs get scored, and
is the gap big enough to matter against a betting line?

What it deliberately does NOT do is tell you whether a bet would have won.
That needs the historical total, which no free source provides. A factor that
moves scoring by a quarter of a run is real and still completely useless if
the market already shaves half a run off the total for it. Treat everything
here as a filter for which ideas deserve to be tested against real lines once
the daily odds archive is deep enough.

    python research/study_mlb.py                 # 2025 season
    python research/study_mlb.py --seasons 2023,2024,2025

Data: MLB StatsAPI (statsapi.mlb.com). Public, no key, no rate limit
published — we stay polite anyway.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

API = "https://statsapi.mlb.com/api/v1"
HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
PAUSE = 0.12          # seconds between calls — be a good citizen
RETRIES = 4


# ------------------------------------------------------------------ fetching
def get(path: str, **params) -> dict:
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "craftypicks-research/1.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                time.sleep(PAUSE)
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            wait = 2 ** attempt
            print(f"   retry {attempt+1}/{RETRIES} after {e} (waiting {wait}s)", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"gave up on {url}")


def cached(name: str, producer):
    """Disk-cache a fetch so re-runs cost nothing."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    value = producer()
    path.write_text(json.dumps(value))
    return value


# -------------------------------------------------------------------- schedule
def season_games(season: int) -> list[dict]:
    """Every completed regular-season game, with venue and probable starters."""
    def fetch():
        out = []
        # Month at a time keeps each response a sane size.
        for month in range(3, 11):
            start = date(season, month, 1)
            end = date(season, month, 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31)
            print(f"   schedule {start} → {end}")
            data = get("/schedule", sportId=1, startDate=start.isoformat(),
                       endDate=end.isoformat(), gameType="R",
                       hydrate="probablePitcher,linescore,venue")
            for day in data.get("dates", []):
                for g in day.get("games", []):
                    if g.get("status", {}).get("abstractGameState") != "Final":
                        continue
                    home, away = g["teams"]["home"], g["teams"]["away"]
                    if "score" not in home or "score" not in away:
                        continue
                    out.append({
                        "pk": g["gamePk"],
                        "date": g["gameDate"][:10],
                        "hour": int(g["gameDate"][11:13]),
                        "venue_id": g.get("venue", {}).get("id"),
                        "venue": g.get("venue", {}).get("name", ""),
                        "home_id": home["team"]["id"], "home": home["team"]["name"],
                        "away_id": away["team"]["id"], "away": away["team"]["name"],
                        "home_score": home["score"], "away_score": away["score"],
                        "total": home["score"] + away["score"],
                        "home_sp": (home.get("probablePitcher") or {}).get("id"),
                        "away_sp": (away.get("probablePitcher") or {}).get("id"),
                        "home_sp_name": (home.get("probablePitcher") or {}).get("fullName", ""),
                        "away_sp_name": (away.get("probablePitcher") or {}).get("fullName", ""),
                    })
        return out
    return cached(f"schedule_{season}", fetch)


# ------------------------------------------------------------- pitcher records
def pitcher_log(pid: int, season: int) -> list[dict]:
    """A starter's game-by-game earned runs and innings for the season."""
    def fetch():
        data = get(f"/people/{pid}/stats", stats="gameLog", group="pitching", season=season)
        rows = []
        for split in (data.get("stats") or [{}])[0].get("splits", []):
            s = split.get("stat", {})
            ip = s.get("inningsPitched")
            if ip is None:
                continue
            # StatsAPI writes innings as 5.1 / 5.2 meaning 5⅓ / 5⅔.
            whole, _, thirds = str(ip).partition(".")
            innings = float(whole) + (float(thirds or 0) / 3.0)
            rows.append({
                "date": split.get("date", ""),
                "ip": round(innings, 4),
                "er": float(s.get("earnedRuns", 0) or 0),
            })
        return rows
    return cached(f"pitcher_{season}_{pid}", fetch)


def era_before(log: list[dict], day: str) -> tuple[float | None, float]:
    """Season ERA and innings accumulated strictly BEFORE `day`.

    Using only prior games is the whole ballgame. Season-final ERA would leak
    the future into the test and make any rule look far better than it is —
    the most common way a backtest lies to you.
    """
    ip = sum(r["ip"] for r in log if r["date"] < day)
    er = sum(r["er"] for r in log if r["date"] < day)
    if ip < 20:                      # too small to mean anything
        return None, ip
    return round(er * 9.0 / ip, 3), ip


# ------------------------------------------------------------------- statistics
def welch(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch's t and a rough two-sided p-value, no scipy needed."""
    if len(a) < 2 or len(b) < 2:
        return 0.0, 1.0
    ma, mb = statistics.mean(a), statistics.mean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    if se == 0:
        return 0.0, 1.0
    t = (ma - mb) / se
    # Normal approximation is fine at these sample sizes.
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
    return round(t, 2), round(p, 4)


def bucket_report(title: str, buckets: dict[str, list[float]], baseline: list[float]) -> None:
    base_mean = statistics.mean(baseline) if baseline else 0.0
    print(f"\n{title}")
    print(f"  {'bucket':<34}{'games':>7}{'avg runs':>11}{'vs all':>9}{'p':>9}")
    print("  " + "-" * 68)
    for name, values in buckets.items():
        if not values:
            continue
        mean = statistics.mean(values)
        _, p = welch(values, baseline)
        flag = "  *" if p < 0.01 and abs(mean - base_mean) > 0.25 else ""
        print(f"  {name:<34}{len(values):>7}{mean:>11.2f}{mean - base_mean:>+9.2f}{p:>9.4f}{flag}")
    print(f"  {'ALL GAMES':<34}{len(baseline):>7}{base_mean:>11.2f}{0.0:>+9.2f}")


# ------------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2025",
                    help="comma-separated, e.g. 2023,2024,2025")
    args = ap.parse_args()
    seasons = [int(s) for s in args.seasons.split(",")]

    rows: list[dict] = []
    for season in seasons:
        print(f"\n== {season} schedule")
        games = season_games(season)
        print(f"   {len(games)} completed regular-season games")

        starters = {g[k] for g in games for k in ("home_sp", "away_sp") if g.get(k)}
        print(f"   fetching game logs for {len(starters)} starters "
              f"(cached after the first run)")
        logs = {}
        for i, pid in enumerate(sorted(starters), 1):
            logs[pid] = pitcher_log(pid, season)
            if i % 50 == 0:
                print(f"     {i}/{len(starters)}")

        for g in games:
            h_era, h_ip = era_before(logs.get(g["home_sp"], []), g["date"]) if g.get("home_sp") else (None, 0)
            a_era, a_ip = era_before(logs.get(g["away_sp"], []), g["date"]) if g.get("away_sp") else (None, 0)
            rows.append({**g, "season": season, "home_era": h_era, "away_era": a_era,
                         "home_ip": round(h_ip, 1), "away_ip": round(a_ip, 1)})

    if not rows:
        print("\nNo games came back. Either the seasons are wrong, or the API "
              "shape changed. Nothing written.", file=sys.stderr)
        return 1

    out = HERE / f"mlb_games_{'_'.join(str(s) for s in seasons)}.csv"
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {len(rows)} rows → {out.relative_to(HERE.parent)}")

    # ------------------------------------------------------------- the study
    usable = [r for r in rows if r["home_era"] is not None and r["away_era"] is not None]
    totals = [float(r["total"]) for r in usable]
    print(f"\n{len(usable)} games have a season ERA on both starters "
          f"({len(rows) - len(usable)} dropped — early season or a spot starter)")

    # 1. combined starter quality
    def combo(r):
        return (r["home_era"] + r["away_era"]) / 2
    buckets = defaultdict(list)
    for r in usable:
        c = combo(r)
        if c <= 3.25:
            buckets["both strong (avg ERA ≤ 3.25)"].append(float(r["total"]))
        elif c <= 3.75:
            buckets["good (3.26 – 3.75)"].append(float(r["total"]))
        elif c <= 4.50:
            buckets["average (3.76 – 4.50)"].append(float(r["total"]))
        else:
            buckets["weak (> 4.50)"].append(float(r["total"]))
    bucket_report("STARTER QUALITY vs TOTAL RUNS", buckets, totals)

    # 2. how far does the extreme go — the actual usable signal
    strong = [float(r["total"]) for r in usable if r["home_era"] <= 3.50 and r["away_era"] <= 3.50]
    weak = [float(r["total"]) for r in usable if r["home_era"] > 4.50 and r["away_era"] > 4.50]
    if strong and weak:
        t, p = welch(strong, weak)
        print(f"\nBOTH ≤3.50 ERA ({len(strong)} games): {statistics.mean(strong):.2f} runs")
        print(f"BOTH >4.50 ERA ({len(weak)} games): {statistics.mean(weak):.2f} runs")
        print(f"gap: {statistics.mean(weak) - statistics.mean(strong):.2f} runs   t={t}  p={p}")

    # 3. park — the factor everyone already knows, as a sanity check
    parks = defaultdict(list)
    for r in usable:
        parks[r["venue"]].append(float(r["total"]))
    ranked = sorted(((v, k) for k, v in parks.items() if len(v) >= 40),
                    key=lambda kv: statistics.mean(kv[0]))
    print("\nPARK RUN ENVIRONMENT (sanity check — these should look familiar)")
    for values, name in ranked[:5]:
        print(f"  {name:<34}{len(values):>7}{statistics.mean(values):>11.2f}  lowest")
    for values, name in ranked[-5:]:
        print(f"  {name:<34}{len(values):>7}{statistics.mean(values):>11.2f}  highest")

    print("""
────────────────────────────────────────────────────────────────────────────
HOW TO READ THIS

A gap of under ~0.4 runs is not tradeable. Books move totals in half-run
steps, and the number already reflects both starters — that is the single
biggest input to any posted MLB total. If "both aces" only scores 0.3 fewer
runs than average, the market has already taken more than that off the line
and betting the under is paying for something you're not getting.

What would be interesting: a gap well over half a run, in a bucket with a
few hundred games, that holds up in every season separately. Anything that
only works in one season is noise wearing a suit.

None of this proves a bet wins. It says which factors are worth carrying
forward to test against real lines once the odds archive has depth.
────────────────────────────────────────────────────────────────────────────""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
