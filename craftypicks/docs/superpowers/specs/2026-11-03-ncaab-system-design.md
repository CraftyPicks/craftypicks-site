# NCAAB System tabs

**Status:** approved design, not yet implemented
**Date:** 2026-11-03

## Goal

Encode the owner's college basketball handicapping rules as a checklist, run it
over every game each morning, and post the games that qualify on two new
sub-tabs under NCAAB: **System** (full game) and **1st Half**. Also show full
team names (school + mascot) everywhere on NCAAB, because nicknames alone are
ambiguous ("Flames" is Liberty and UIC; "Panthers" is Pitt, Georgia State,
Northern Iowa, FIU...).

## Global constraints

- Free data only. No new Odds API spend.
- Python 3.11 standard library only; nothing installed on the runner.
- Every module carries `_self_test()` and runs as `python3 scripts/<mod>.py`.
- ESPN is unreachable from the development sandbox; tests run on saved
  fixture responses, the live fetch runs on GitHub Actions.
- Ships as a zip with no `.github/workflows/` content.

## Data (ESPN, free)

| Need | Source |
|---|---|
| Tonight's games, full names, team ids, spread, ML | `site.api.espn.com/.../mens-college-basketball/scoreboard?dates=YYYYMMDD&groups=50&limit=400` |
| BPI rank for every D-I team | ESPN power index endpoint |
| Rebounds, steals, turnovers per game | ESPN team statistics |
| Players averaging 14+ | ESPN team roster / player season stats |
| Home/away ATS, last-5 home/road form, last-5 head to head | Past scoreboards this season (final score + closing spread), cached in `data/ncaab_games.json` and appended daily |

`displayName` ("Liberty Flames") is the full name used everywhere.

## Candidates

One candidate per game per tab:

- **System (full game):** the away team, on the full-game spread, with its
  moneyline price shown beside it.
- **1st Half:** the home team on the 1H spread, **unless** the away team ranks
  50 or more places higher in BPI, in which case the game is skipped.

## Checklist

Each check is ✓, ✗, or n/a (data missing; n/a never counts as a pass). A play
posts at **4 or more ✓**. The card lists every check with its mark.

| Check | Passes when (candidate vs opponent) | System | 1H |
|---|---|---|---|
| Rebounding | candidate averages ≥ 3.0 more rebounds per game | ✓ | ✓ |
| Venue ATS | candidate covers ≥ 55% in this venue role (road for System, home for 1H), minimum 4 graded games | ✓ | ✓ |
| BPI vs spread | candidate is getting 10+ points and the BPI ranks are within 15 places | ✓ | — |
| Head to head | candidate won ≥ 3 of the last 5 meetings (needs ≥ 3 meetings on file) | ✓ | ✓ |
| Scoring depth | candidate has ≥ 3 players at 14+ ppg and more such players than the opponent | ✓ | ✓ |
| Recent form | candidate won ≥ 3 of its last 5 games in this venue role | ✓ | ✓ |
| Defense | candidate's turnover margin per game (forced − committed) is higher | ✓ | ✓ |

**Postseason only** (conference tournaments and NCAA tournament; off until then):

- **Tournament unders:** a note on every tournament game card leaning under the
  total. Shown, not scored.
- **Tournament scorer:** an extra ✓ for a candidate in the top 25 nationally in
  points per game.

All thresholds live as named constants at the top of the module so they can be
tuned once the record is long enough to tune against.

## 1H line

`est = round_to_half(full_game_spread / 2)`, labelled **est.** on the card. The
reader confirms the real 1H number at their book.

## Grading

Each morning the previous day's posted plays are graded:

- System: against the closing full-game spread (and ML if the candidate was an
  underdog, shown separately).
- 1H: first-half score from the ESPN linescore against the estimated line.

Each tab shows W-L-P and units at -110 at the top, plus the hit rate of every
individual check, so a rule that isn't pulling weight is visible.

## Pages

- `ncaab/system.html` and `ncaab/first-half.html`, added to the NCAAB view
  row, English and Spanish.
- Card: full matchup ("Liberty Flames @ Pittsburgh Panthers"), the play
  ("Liberty Flames +11.5", ML price), checks passed out of applicable, the
  checklist, tip-off time.
- Empty state when nothing qualifies: "No games pass 4 checks today."
- The existing NCAAB board switches from nicknames to full names.

## Out of scope

- Real 1H lines (paid).
- BetIQ (paid); replaced by the Recent form check.
- A totals model; tournament unders is a note, not a play.
