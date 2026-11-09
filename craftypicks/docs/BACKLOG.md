# Backlog

Saved ideas, newest first. Read this at the start of any session on the site.

## Our own NCAAB offence/defence ratings (saved 2026-11-10, start mid-December)

- **What:** tempo-free, opponent-adjusted offence and defence ratings (points
  per 100 possessions, KenPom/Torvik style) built from the box scores already
  stored in `data/ncaab_games.json`. Possessions = FGA - OREB + TO + 0.475*FTA
  (needs FGA, OREB and FTA added to `espn_cbb.parse_box`: bump BOX_VERSION).
  Solve adjusted ratings iteratively against opponents' ratings.
- **Why:** an independent number to set against ESPN BPI; then blend the two
  (average), which usually beats either alone. Projected score and line on
  the card would use the blend.
- **When:** ~mid-December, once most teams have 8-10 games. Grade it against
  BPI on the same games before switching the card over.

## Per-team home-court edge (saved 2026-11-09)

- **Why:** the average college home edge is ~4 points but varies a lot by
  arena; crowd density matters more than travel
  (Yi, Sport Journal: https://thesportjournal.org/article/the-home-court-advantage-evidence-from-mens-college-basketball/).
- **What:** from our own stored finals (`data/ncaab_games.json`), estimate each
  team's home margin over expectation (home result vs BPI-expected margin),
  shrunk toward the league average by sample size. Show it in Team Stats and
  consider it as a System / 1st Half check.
- **When:** needs ~8+ home games per team -- revisit in January.

## TheRundown as a second free odds source (saved 2026-11-04)

- **Why:** the Odds API free tier is 500 credits/month and the site spends
  ~20/day (~600/month), so credits run out near month end.
- **What:** TheRundown's free key gives 20,000 data points/day for pregame
  moneyline, spread and total from DraftKings, FanDuel and BetMGM.
  Use it for NCAAB and NBA game lines; keep Odds API credits for markets only
  it carries (player props).
- **Check first:** does the free tier include NCAAB, and first-half lines?
  If it has 1H spreads, they replace the estimated line on NCAAB > 1st Half.
- **Rules:** one key, within their terms. No second Odds API account.
- Docs: https://therundown.io/blog/free-sports-odds-api

## Still open

- Workflow edits, paste by hand (zips cannot carry `.github/workflows/`):
  - `daily.yml` after the `git add` line (~97):
    `git -C .. add -u -- ':(exclude)craftypicks/**'`
  - `boards.yml` ~58: same line, and add `style.css` to its `git add`
  - `boards.yml` cron minute `30` -> `27` (GitHub drops `:30` runs)
- Dead files to delete in the GitHub UI: `scripts/homers.py`,
  `_src/homers.body.html`, `scripts/play_log.py`, `scripts/stats.py`,
  `scripts/grade_props.py`, and `_src/{plays,record,ev,screens,form}.body.html`.
- F7 review leftovers: Jensen's inequality on `min(E[IP], 7)`; NB2 vs NB1 once
  graded; no home-field term; no Brier on the ladder; `splits[0]` for traded
  pitchers.
- NCAAB System: optional filter to only post when the spread is under 6.5.
