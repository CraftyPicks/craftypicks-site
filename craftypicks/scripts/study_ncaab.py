#!/usr/bin/env python3
"""Test college basketball angles against real closing numbers.

Everything here runs on /lines alone, which carries matchup, final score and
the closing spread/total/moneyline. Team strength is an Elo we compute
ourselves, walking games in date order so a rating never contains information
from a game that hadn't been played yet. Season-aggregate stats and published
ratings are deliberately NOT used for this reason.

Guardrails, because with real prices the failure mode inverts from "can't
test" to "test until something looks good":

  * the newest season is held out and never informs a threshold
  * every rule tested is counted in a ledger printed at the end
  * break-even at -110 is 52.38%, and that line is drawn on every result
  * rules with thin samples are reported but flagged as unusable

    CBBD_API_KEY=xxx python research/study_ncaab.py
    CBBD_API_KEY=xxx python research/study_ncaab.py --seasons 2021,2022,2023,2024,2025 --holdout 2026
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

API = "https://api.collegebasketballdata.com"
KEY = os.environ.get("CBBD_API_KEY", "").strip()
HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache_ncaab"
BREAK_EVEN = 52.38          # cover % needed to break even at -110
VIG_PRICE = -110

LEDGER: list[dict] = []


# ------------------------------------------------------------------ fetching
def call(path: str, **params):
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {KEY}",
        "Accept": "application/json",
        "User-Agent": "craftypicks-research/1.0",
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                time.sleep(0.3)
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SystemExit(f"API rejected the key ({e.code}). Check CBBD_API_KEY.")
            time.sleep(2 ** attempt)
        except Exception:                                   # noqa: BLE001
            time.sleep(2 ** attempt)
    raise RuntimeError(f"gave up on {url}")


def month_windows(season: int):
    start = date(season - 1, 11, 1)
    while start < date(season, 4, 30):
        nxt = (start.replace(day=28) + timedelta(days=8)).replace(day=1)
        yield start, min(nxt - timedelta(days=1), date(season, 4, 30))
        start = nxt


def season_lines(season: int) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"lines_{season}.json"
    if path.exists():
        return json.loads(path.read_text())
    rows = []
    for a, b in month_windows(season):
        batch = call("/lines", season=season,
                     startDateRange=f"{a.isoformat()}T00:00:00.000Z",
                     endDateRange=f"{b.isoformat()}T23:59:59.000Z")
        if isinstance(batch, list):
            if len(batch) >= 3000:
                print(f"   !! {season} {a:%b} hit the 3000 cap — data may be incomplete")
            rows.extend(batch)
        print(f"   {season} {a:%b}: {len(rows)} cumulative")
    path.write_text(json.dumps(rows))
    return rows


# ------------------------------------------------------------------ shaping
def build_games(raw: list[dict]) -> list[dict]:
    """One row per priced game, with the closing number attached."""
    games = []
    for g in raw:
        lines = g.get("lines") or []
        if not lines:
            continue
        line = lines[0]
        spread, total = line.get("spread"), line.get("overUnder")
        hs, as_ = g.get("homeScore"), g.get("awayScore")
        if spread is None or hs is None or as_ is None:
            continue
        games.append({
            "id": g.get("gameId"),
            "season": g.get("season"),
            "date": (g.get("startDate") or "")[:10],
            "home": g.get("homeTeam"), "away": g.get("awayTeam"),
            "home_conf": g.get("homeConference"), "away_conf": g.get("awayConference"),
            "hs": float(hs), "as": float(as_),
            "margin": float(hs) - float(as_),
            "spread": float(spread),
            "total": float(total) if total is not None else None,
            "home_ml": line.get("homeMoneyline"), "away_ml": line.get("awayMoneyline"),
        })
    games.sort(key=lambda r: (r["date"], r["id"] or 0))
    return games


def check_spread_convention(games: list[dict]) -> int:
    """Work out which way the spread is signed instead of assuming.

    If `spread` is the HOME team's number, then margin + spread should centre
    on zero. If it's the away number, that sum is badly biased and we flip.
    Getting this backwards would invert every result in the file, so it is
    checked rather than trusted.
    """
    a = statistics.mean(g["margin"] + g["spread"] for g in games)
    b = statistics.mean(g["margin"] - g["spread"] for g in games)
    print(f"   mean(margin + spread) = {a:+.2f}   mean(margin − spread) = {b:+.2f}")
    if abs(a) <= abs(b):
        print("   → `spread` is the HOME team's line (home covers when margin + spread > 0)")
        return 1
    print("   → `spread` is the AWAY team's line; flipping sign")
    for g in games:
        g["spread"] = -g["spread"]
    return -1


# --------------------------------------------------------------------- elo
def attach_elo(games: list[dict], k: float = 20.0, hca: float = 65.0) -> None:
    """Walk games in date order, recording each team's rating BEFORE tip.

    Ratings carry 25% of their distance to 1500 across a season break, which
    roughly reflects how much roster turnover college teams get.
    """
    elo: dict[str, float] = defaultdict(lambda: 1500.0)
    season_seen = None
    for g in games:
        if g["season"] != season_seen:
            for team in list(elo):
                elo[team] = 1500 + (elo[team] - 1500) * 0.75
            season_seen = g["season"]
        h, a = g["home"], g["away"]
        g["elo_home"], g["elo_away"] = elo[h], elo[a]
        g["elo_diff"] = (elo[h] + hca) - elo[a]
        exp_home = 1 / (1 + 10 ** (-g["elo_diff"] / 400))
        actual = 1.0 if g["margin"] > 0 else 0.0
        # margin-of-victory multiplier keeps blowouts from being over-rewarded
        mov = math.log(abs(g["margin"]) + 1) * (2.2 / (abs(g["elo_diff"]) * 0.001 + 2.2))
        shift = k * mov * (actual - exp_home)
        elo[h] += shift
        elo[a] -= shift


# ------------------------------------------------------------------ scoring
def fit_margin_model(train: list[dict]) -> tuple[float, float]:
    """Least squares margin ≈ intercept + slope × elo_diff, on TRAIN only."""
    xs = [g["elo_diff"] for g in train]
    ys = [g["margin"] for g in train]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = cov / var if var else 0.0
    return my - slope * mx, slope


def grade_ats(games: list[dict], side: str) -> dict:
    """Cover record and ROI for betting `side` at -110 in every game given.

    side: home | away | dog | fav

    'dog' and 'fav' pick per game rather than by venue. This matters for the
    rank-gap angle: between two closely rated teams the favourite is often
    the home side, so betting 'away' would quietly mix backing dogs with
    backing favourites and average the two into mush.
    """
    w = l = p = 0
    for g in games:
        edge = g["margin"] + g["spread"]      # >0 means the home side covered
        if side == "away":
            edge = -edge
        elif side == "dog":
            edge = edge if g["spread"] > 0 else -edge
        elif side == "fav":
            edge = edge if g["spread"] < 0 else -edge
        if abs(edge) < 1e-9:
            p += 1
        elif edge > 0:
            w += 1
        else:
            l += 1
    decided = w + l
    cover = (w / decided * 100) if decided else 0.0
    profit = w * (100 / 110) - l
    roi = (profit / decided * 100) if decided else 0.0
    return {"n": len(games), "w": w, "l": l, "p": p, "cover": cover,
            "units": round(profit, 2), "roi": roi}


def report(name: str, description: str, train_games: list[dict],
           holdout_games: list[dict], side: str, min_n: int = 150) -> None:
    tr = grade_ats(train_games, side)
    ho = grade_ats(holdout_games, side)
    LEDGER.append({"name": name, "train_n": tr["n"], "train_cover": tr["cover"],
                   "holdout_n": ho["n"], "holdout_cover": ho["cover"]})
    print(f"\n  {name}")
    print(f"    {description}")
    for label, r in (("build seasons", tr), ("HELD-OUT season", ho)):
        if r["n"] == 0:
            print(f"    {label:<16} no qualifying games")
            continue
        verdict = ""
        if r["n"] < min_n:
            verdict = "  (sample too thin to mean anything)"
        elif r["cover"] > BREAK_EVEN:
            verdict = "  ← above break-even"
        print(f"    {label:<16} {r['n']:>5} bets  {r['w']}-{r['l']}-{r['p']}  "
              f"{r['cover']:>5.1f}%  {r['units']:+7.2f}u  ROI {r['roi']:+5.1f}%{verdict}")


# ------------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2020,2021,2022,2023,2024,2025")
    ap.add_argument("--holdout", default="2026")
    args = ap.parse_args()
    if not KEY:
        print("No CBBD_API_KEY set.", file=sys.stderr)
        return 1

    build_seasons = [int(s) for s in args.seasons.split(",")]
    holdout_season = int(args.holdout)

    print("== fetching (cached after the first run)")
    raw = []
    for season in build_seasons + [holdout_season]:
        raw.extend(season_lines(season))

    games = build_games(raw)
    print(f"\n== {len(games)} priced games across "
          f"{len(build_seasons)} build seasons + {holdout_season} held out")

    print("\n== sanity checks")
    check_spread_convention(games)
    attach_elo(games)

    fav_home = [g for g in games if g["spread"] < 0]
    print(f"   home favourites: {len(fav_home)} of {len(games)} "
          f"({len(fav_home)/len(games)*100:.1f}%) — expect roughly 65-75%")
    home_cover = grade_ats(games, "home")
    print(f"   every game, home side: {home_cover['cover']:.2f}% "
          f"(a fair market sits near 50%, and below break-even either way)")

    train = [g for g in games if g["season"] in build_seasons]
    hold = [g for g in games if g["season"] == holdout_season]
    intercept, slope = fit_margin_model(train)
    print(f"\n   margin model fit on build seasons only: "
          f"margin ≈ {intercept:+.2f} + {slope:.4f} × elo_diff")
    for g in games:
        g["model_margin"] = intercept + slope * g["elo_diff"]
        # model's view of the home line, versus the market's
        g["model_edge"] = g["model_margin"] + g["spread"]

    print("\n" + "=" * 74)
    print("YOUR ANGLES, TESTED AGAINST CLOSING NUMBERS")
    print("=" * 74)

    # ---- 1. the ranking-gap angle, in its testable form
    close = [g for g in games if abs(g["elo_diff"]) < 120]
    for threshold in (10, 12, 14):
        sel_tr = [g for g in close if g["season"] in build_seasons and abs(g["spread"]) >= threshold]
        sel_ho = [g for g in close if g["season"] == holdout_season and abs(g["spread"]) >= threshold]
        report(
            f"RANK GAP — similar teams, spread ≥ {threshold}, back the DOG",
            "Two closely rated teams but a big number. Your angle, generalised "
            "to whichever side is the underdog.",
            sel_tr, sel_ho, side="dog",
        )
        report(
            f"RANK GAP — same games, spread ≥ {threshold}, back the AWAY side",
            "Your angle exactly as stated, for comparison with the version above.",
            sel_tr, sel_ho, side="away",
        )

    # ---- 2. the same idea done properly: model disagrees with the market
    for edge_pts in (3, 5, 7):
        sel_tr = [g for g in train if g["model_edge"] >= edge_pts]
        sel_ho = [g for g in hold if g["model_edge"] >= edge_pts]
        report(
            f"MODEL vs MARKET — home side undervalued by ≥ {edge_pts} pts",
            "Elo-implied margin beats the posted line by this much.",
            sel_tr, sel_ho, side="home",
        )
        sel_tr = [g for g in train if g["model_edge"] <= -edge_pts]
        sel_ho = [g for g in hold if g["model_edge"] <= -edge_pts]
        report(
            f"MODEL vs MARKET — away side undervalued by ≥ {edge_pts} pts",
            "Same test, other direction.",
            sel_tr, sel_ho, side="away",
        )

    # ---- 3. plain positional bets, as controls
    report("HOME DOGS", "Every home underdog, no filter.",
           [g for g in train if g["spread"] > 0],
           [g for g in hold if g["spread"] > 0], side="home")
    report("AWAY FAVOURITES", "Your away-team lean, unfiltered.",
           [g for g in train if g["spread"] < 0],
           [g for g in hold if g["spread"] < 0], side="away")
    report("BIG FAVOURITES ≥ 15", "Fading double-digit chalk.",
           [g for g in train if abs(g["spread"]) >= 15],
           [g for g in hold if abs(g["spread"]) >= 15],
           side="away")

    # ------------------------------------------------------------- ledger
    print("\n" + "=" * 74)
    print(f"LEDGER — {len(LEDGER)} rules tested this run")
    print("=" * 74)
    print("  Testing this many rules means roughly one or two will clear "
          "break-even\n  on the build seasons by chance alone. The held-out "
          "column is the only\n  one that counts, and even it deserves "
          "suspicion if the rule was chosen\n  after seeing build results.\n")
    print(f"  {'rule':<52}{'build':>10}{'held out':>12}")
    print("  " + "-" * 72)
    for row in LEDGER:
        print(f"  {row['name'][:50]:<52}{row['train_cover']:>9.1f}%"
              f"{row['holdout_cover']:>11.1f}%")
    survivors = [r for r in LEDGER
                 if r["train_cover"] > BREAK_EVEN and r["holdout_cover"] > BREAK_EVEN
                 and r["holdout_n"] >= 150]
    print(f"\n  cleared break-even in BOTH build and held-out, with a usable "
          f"sample: {len(survivors)}")
    for r in survivors:
        print(f"    → {r['name']}  ({r['holdout_n']} held-out bets, "
              f"{r['holdout_cover']:.1f}%)")
    if not survivors:
        print("    → none. That is the most common and most honest outcome.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
