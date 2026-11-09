# NCAAF board

**Status:** design, awaiting approval
**Date:** 2026-11-09
**Launch target:** before conference championship weekend (Dec 5), live
through bowls and the College Football Playoff (January).

## Goal

A college football section that works like the NCAAB board: every FBS game
with full team names, the line, a number of our own, and a Game Detail
panel with the same Team Stats layout. Free data only; zero Odds API credits.

## Global constraints

- Free sources only: ESPN site/fitt APIs, no key. No Odds API spend.
- Python 3.11 standard library; `_self_test()` in every module.
- ESPN is unreachable from the dev sandbox: tests use real-shaped fixtures
  (sportsdataverse-py `tests/fixtures/espn/*_cfb.json`).
- Full team names everywhere (as NCAAB).
- Preview at 390px before shipping; zip delivery, no `.github/` content.

## Data (ESPN, free)

| Need | Source |
|---|---|
| Games, full names, rank, record, spread, total, ML, neutral site | `football/college-football/scoreboard?dates=YYYYMMDD&groups=80` (FBS) |
| Box scores: yards, pass/rush yards, turnovers, 3rd-down, quarter scores | `football/college-football/summary?event=ID` |
| Team strength | ESPN FPI (`fitt/v3/.../college-football/powerindex`) |

The scoreboard, odds and box parsers in `espn_cbb.py` are sport-agnostic
(checked against the CFB fixtures); they move to a shared `espn_site.py`
and both sports call them with their own URL path.

## Which games

Football is weekly, so the board shows **the next 7 days** of FBS games
(Thursday to Saturday, then each bowl as its date comes), soonest first.

## Our number

ESPN FPI is points better than an average FBS team on a neutral field.

- Expected margin = FPI(home) - FPI(away) + home edge (2.5 points; 0 when
  `neutralSite`, which covers every bowl and playoff game).
- Win probability = normal CDF of margin / 14 (13.5 to 15 is the usual
  college football margin spread; a tuning constant).
- The card shows our win % against the market's (from ESPN's moneyline),
  in the same layout as the NCAAB card. The detail line shows "FPI line"
  next to the spread.
- Graded every morning with the existing Brier scoring, so the record shows
  whether the FPI number beats the market.

## Game Detail: Team Stats

Same panel as NCAAB (away striped left, home in school colour right, AP rank,
record, BPI-style rank from FPI). Rows:

Focused on what the owner bets on (2026-11-09):

ATS, Points, Points Against, Turnovers (giveaways per game), Takeaways
(opponent turnovers per game), Yards per Play.

Yards per Play = total yards / (rush attempts + pass attempts), from the
box score. Added because it is a widely used college football efficiency
number: it measures how well a team moves the ball regardless of pace, so a
slow team and a fast one compare fairly. Its value here gets checked by the
record like everything else.

Season averages from our own stored box scores.

## Pages

- `ncaaf/index.html`, league row label **NCAAF**, after NCAAB in the nav.
- The sport row at 390px already scrolls; one more tab is acceptable but is
  checked in the preview.

## Runs

A free section in `run_daily.py` above the odds guard (as the NCAAB System
run), ESPN only, idempotent. Off outside August-January. About 60 box scores a
week plus 8 scoreboards and one FPI call a day.

## Out of scope

- A System tab of football rules (the owner has not set any yet).
- Props.
- Odds API prices (ESPN's single line only).
