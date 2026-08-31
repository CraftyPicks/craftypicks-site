# Craftypicks: from picks service to pricing board

**Status:** approved design, not yet implemented
**Date:** 2026-08-28

## Goal

Turn Craftypicks from a site that publishes daily plays into a tool that helps
people bet well on their own. For every game in MLB, NBA, NFL and NCAAB it
shows what the game should be priced at, what the market is actually paying,
where the best number is, and the research behind the estimate.

The existing MLB board is the model. The change is to generalise it to four
leagues, add prices, refresh it hourly, and retire the daily card.

## Decisions

| Question | Decision |
|---|---|
| Core job | Tell people the fair price, and show the research behind it |
| The plays | Retired. The model is judged on every game it rates, not on a card |
| League depth | Same floor everywhere; MLB deeper because its data is free |
| Freshness | Hourly rebuild + deploy; live scores fetched in the browser |
| Name / domain | Unchanged — Craftypicks, craftypicks.org |
| Homepage | Tonight's board at the root, collapsible explainer above it |
| Books | Reader picks their books; stored in the browser |
| Theme | Light: grey ground, white cards |
| Card detail | Compact-ish front, `<details>` expand. Not a flip |
| Navigation | Sport on the top row, view on a second row beneath it |
| Search | Build-time JSON index, filtered in the browser |
| Totals | Market number now; our own total model is later work |
| History | One-off historical pull to backtest and tune, labelled as backtest and never merged with live results |
| Props layout | Dense list with an expanding detail panel, not cards |
| Props valuation | Two numbers: the player's average and the devigged edge. "No model" where we have none |
| Props leagues | MLB, NFL, NBA. NCAAB board-only |

## Architecture

Static site, built by GitHub Actions, served by Cloudflare Pages. No server, no
database, no accounts. Two scheduled jobs and one small client script.

```
hourly (active hours)      daily (early morning)        in the browser
─────────────────────      ─────────────────────        ──────────────
odds per in-season league  Elo ratings                  ESPN scoreboard
  ↓ 3 credits each         team records + form            ↓
fair price + best book     MLB probable starters        live scores and
  ↓                        MLB strikeout props          finals patched
data/board.json            grade yesterday              into cards
  ↓                        closing-line comparison
build.py → HTML
  ↓
commit → Cloudflare deploy
```

**Why hourly and not faster.** Cloudflare Pages' free tier allows 500 builds a
month — about 16 a day — and every deploy counts. Hourly across an active
window fits with headroom; anything faster does not. The API budget is not the
constraint. If sub-hourly odds are ever wanted, Pages Pro ($20/month) raises the
cap to 5,000 builds and nothing else needs to change.

**Why scores are client-side.** Scores change far more often than deploys can.
Fetching them in the browser makes them genuinely live, costs no credits and no
builds, and fails safely: if the request fails the page still shows everything
the build produced.

## Navigation and pages

Two rows. The top row picks the sport; the second picks the view within it.
Everything about a sport lives under that sport — props stop being a sibling of
the board and become a child of it, so a reader looking at tonight's Brewers
game is one click from Peralta's strikeout line rather than two tabs away.

```
Tonight     all sports, start-time order
MLB      →  Board · Pitcher props · Team ratings · Yesterday
NBA      →  Board · Player props · Team ratings · Yesterday
NFL      →  Board · Player props · Team ratings · Yesterday
NCAAB    →  Board · Team ratings · Yesterday
Accuracy    how good the numbers have been
Search      teams, players, matchups
```

| Path | Contents |
|---|---|
| `/` | Tonight — every game today, all leagues, start-time order, league filter chips. Collapsible "how to read this" strip above the board, dismissal remembered in the browser. |
| `/mlb/` etc. | League board — the default view for that sport |
| `/mlb/props/` | That sport's props. MLB has pitcher strikeouts at launch; other leagues get this tab when their props are added |
| `/mlb/ratings/` | Elo, form, and how the rating has moved |
| `/mlb/yesterday/` | Last night's finals with how the numbers did |
| `/accuracy` | Brier vs market, calibration, closing-line movement, sample-size honesty |
| `/how-it-works` | Methodology; merges today's About and Screens pages |

Retired: `plays.html`, `record.html`, `screens.html`. Their machinery survives
inside `/accuracy` and `/how-it-works`.

**Both nav rows must scroll horizontally below 760px.** The current site shipped
a nav that overflowed the document on a phone, and the prototype reproduced it
at 367px of overflow before it was fixed. A build check asserts zero horizontal
overflow at 390px on every page.

### Search

The build already knows every team, player and game, so it emits a small JSON
index at build time and the browser filters it. No search service, no backend,
no index to keep in sync — it works the same way the book picker does. Search
matches team names and nicknames, player names, and matchups ("cubs brewers").
With JavaScript off the field is hidden rather than broken.

## The game card

The front keeps roughly the density the current card has — full club names,
records with venue split, form, starter and ERA — and adds a market block. What
moves behind the disclosure is the deep material: every book's price, matchup
history, and that game's props.

```
CHC @ MIL                            7:05 PM ET   ● 6th · 3–1
Chicago Cubs                                          44.4%
  77-53 · 34-30 on the road · ●●○●●○●●●○
  Shota Imanaga L · 3.24 ERA · 150 IP
[========|=====================]     ← bar, tick = market
Milwaukee Brewers                                     55.6%
  74-56 · 41-25 at home · ●●●○●●○●●●
  Freddy Peralta R · 3.47 ERA · 140 IP
──────────────────────────────────────────────────────────
ML         MIL −128  Caesars                          +0.9%
RUN LINE   MIL −1.5 +134  FanDuel                     +2.2%
TOTAL      8.5 · o−105 / u−115  BetMGM           market only
              Books, matchup history and props  ▾
──────────────────────────────────────────────────────────
  Starter vs this opponent · strikeout props tonight ·
  every book for every market · fair prices · Elo
```

**Disclosure is `<details>`, not a flip.** A flipped card's back face is exactly
the footprint of its front, so the detail cannot fit — a prototype with ten rows
already needed its own scrollbar, before books or props were added. `<details>`
is Baseline Widely available, needs no JavaScript, is keyboard and
screen-reader accessible by default, keeps the hidden text findable by Ctrl+F
and by search engines, and can be deep-linked. `interpolate-size:
allow-keywords` animates it to natural height, guarded by
`prefers-reduced-motion`.

**Market labels come from league config.** "Run line" is MLB's word; the other
three leagues say "spread". Never hardcoded in the renderer.

### Totals

Devigging the market's over/under is free — the `totals` market is already
pulled — so the card can show the posted total, the best price across books,
and the vig-free implied percentage from day one.

It cannot show *our* number for a total. Elo produces a win probability, not a
run distribution. A Craftypicks total needs a scoring model — Poisson on team
run rates, adjusted for park and starter — and that is separate work with its
own validation. Until it exists the total row reads **"market only"** rather
than displaying an invented number. This is deliberate and should not be
quietly filled in later without the model behind it.

## The props page

One per sport with props: **MLB, NFL and NBA**. NCAAB is board-only — 110 games
a night across three markets is 9,900 credits a month on its own.

### Layout: list, not cards

Props are scanned, not read. A card grid works for 15 games; it fails at 60
prop rows. The page is a dense list with the same `<details>` disclosure the
game card uses.

Row: player and team · line and best price with the book · the player's recent
average · our edge · a last-10 hit/miss strip.

The strip in a row is **uniform-height blocks** — colour carries over/under and
the value is not encoded in height. The taller value-scaled bar chart belongs
in the expanded panel where there is room and the numbers can be printed under
each bar.

### Two number columns, and why both

| Column | What it is |
|---|---|
| Recent average | What the player has done. A fact about the past. |
| Our edge | What the offered price is worth after devigging. |

Props apps show only the first and call it "edge". A player averaging 1.7
against a 1.5 line looks like a lock in that column and can still be a bad bet,
because &minus;150 already charges for it. Showing the average alone is the most
misleading thing this category does.

**Where no model exists the edge column reads "no model".** MLB pitcher
strikeouts is the only prop market with a projection at launch. Outs, earned
runs, and every NFL and NBA market show the average, the hit rates and the best
price — genuinely useful for line shopping — with the edge column saying so
plainly. Same rule as the totals row: never borrow a different number and
present it as a valuation.

### The detail panel

Four splits and the matchup. Deliberately not thirteen.

```
Hit rate vs 7.5              Matchup — looking at the over
  Last 5      3 of 5   60%     White Sox strikeouts  [3rd]     9.4 K/g
  Last 10     6 of 10  60%     7.0 ──────[ lg avg 8.4 ]──▮── 9.9
  Season     18 of 29  62%     strongly favours the over
  vs CWS      3 of 4   75%
  ── season rate 62% ──        Expected innings              5.5 IP
                               neutral matchup
```

Rules, each of which exists because of a specific way this feature misleads:

1. **The four splits are fixed and always rendered in full**, in the same
   order, and cannot be sorted by hit rate. A panel that can be re-ordered to
   lead with whatever looks best is a trend-mining tool regardless of its copy.
2. **Sample size is printed on every row** — "3 of 5", not "60%".
3. **The bar is measured against the player's own rate**, drawn as a tick, not
   against 50%. A 60% recent split against a 62% season rate is *below*
   baseline; every trends app renders that green.
4. **Splits under five games are greyed and tagged.** At &minus;110 a perfect
   4-of-4 arrives by chance once in thirteen tries.

Simulation behind rule 4: a player with *no edge*, hitting at exactly the 52.4%
a &minus;110 line implies, produces at least one perfect split **50.3% of the
time** when a log is sliced 18 ways (200,000 trials). Perfect splits are the
expected output of slicing, not evidence.

### The matchup component

A rate, not a rank. "3rd of 30" gives an ordering; "9.4 per game against a
league average of 8.4" gives the size.

Each row shows the value, a scale from league worst to league best with the
neutral band shaded, the league average, and a one-line verdict.

**Colour is relative to the side being viewed.** 9.4 K/g is green on an over
and red on an under — the same number, opposite meaning. The component takes
the side as an argument.

**Neutral band is half a standard deviation.** Measured from real
distributions:

| Stat | League avg | SD | Neutral band |
|---|---|---|---|
| MLB strikeouts allowed / game | 8.4 | 0.70 | 8.01 – 8.71 |
| NBA assists allowed / game | 24.8 | 1.62 | 24.02 – 25.64 |

A team a tenth above average must read grey. Colouring it green makes the cue
meaningless. Per-league constants, one function.

**The number is never coloured without the league average beside it**, because
"9.4" alone tells a reader nothing.

### Page furniture

- Accuracy strip at the top: projections graded, our average miss against the
  line's, right-side rate with its sigma, and how many starters have a posted
  line.
- Filters: all / we differ by 0.5+ / over leans / under leans / flagged.
- Four row states must render: a clean lean, one inside the noise, a flagged
  one, and a player with **no posted line** — still projected, still graded, so
  the accuracy figure is not quietly drawn only from starts where a line existed.

## Book selection

A one-time picker, remembered in `localStorage`. No account, no server, nothing
leaves the device.

- Unset (first visit, private window, cleared storage) → all books, and the
  card says "of all books" rather than implying a personal set.
- Every read and write wrapped in `try/catch`; storage can throw in some
  contexts and the board must render regardless.
- The build emits every book's price into the HTML. The picker only changes
  which of them is labelled "best", so it works without JavaScript too — it
  just shows the market-wide best.

## Accuracy: what replaces the track record

Dropping the daily card removes the win/loss record, and that is an
improvement: the model rates every game, so it can be scored on every game
rather than on the five a day it happened to bet.

**Brier and calibration** — unchanged, but now over the full board rather than
the plays only.

**Closing-line movement** replaces beat-the-close:

```
for each rated game where |our_prob − market_prob_at_rating| ≥ 2 points:
    disagreement = our_prob − market_open
    movement     = market_close − market_open
    moved_toward_us = sign(movement) == sign(disagreement)

report: % moved toward us, average movement in points,
        and sigma from chance using sqrt(0.25/n)
```

Null is 50%. This is the same significance test already implemented in
`stats.py`, pointed at a much larger sample.

**Closing lines are free going forward.** The hourly refresh already pulls odds
continuously, so the last pull before a game starts *is* the closing snapshot.
No extra call, no extra credits, and `closing.py`'s dedicated snapshot job can
retire. Closing lines for games *already played* come from the historical pull
instead — see below — and are labelled as backtest, not live.

Sample-size honesty carries over unchanged: the confidence interval on any
rate, the "needs N more" counter, and the under-30 approximation warning.

## Modules

| Module | Responsibility |
|---|---|
| `scripts/fair.py` **new** | Devig, fair price, best-book selection. Sport-agnostic. Extracted from `find_plays.py` so the board and any future screen share one implementation. |
| `scripts/ratings.py` **new** | Elo for any league from dated results. Generalises `rate_mlb.py`. |
| `scripts/results.py` **new** | Free score sources — MLB StatsAPI for baseball, ESPN for the rest. Feeds Elo and grading. Replaces paid `/scores`. |
| `scripts/board.py` **new** | Assembles `data/board.json` from odds + ratings + research. |
| `craftypicks/live.js` **new** | The only client-side code: ESPN fetch, score patching, book picker, search filtering. |
| `scripts/search_index.py` **new** | Emits `data/search.json` — teams, nicknames, players and matchups — at build time. |
| `_src/render.py` | Gains the price row and the book-aware "best" label. |
| `_src/build.py` | Gains league pages and Tonight. |
| `scripts/rate_mlb.py` | Keeps MLB-specific work (starters, vs-opponent); Elo moves out. |
| `scripts/find_plays.py` | Retired as a publisher; its devig logic moves to `fair.py`. |
| `scripts/closing.py` | Retired — the hourly refresh supersedes it. |

### The `screen_*` modules

Five files carry a `screen_` prefix but they are not one thing, and the naming
has been hiding that:

| File | What it actually is | Fate |
|---|---|---|
| `screen_mlb.py` | **The MLB StatsAPI client.** Probable starters, game logs, season stats, team strikeout rates, pitcher-vs-team. Nothing to do with screening. `pitchers.py`, `rate_mlb.py`, `slate.py` and `screen_source.py` all depend on it. | **Keep, rename `mlb_api.py`.** Renaming it is the point: four modules depend on it for data and its current name implies it can be deleted with the screens. |
| `screen_rules.py` | Threshold evaluation for the strikeout screens | Retire |
| `screen_source.py` | Turns screen matches into posted plays | Retire |
| `screen_models.py` | Dataclasses for the above | Retire |
| `screen_config.py` | Screen thresholds *and* MLB season constants, mixed together | Split: the season/props constants move to `config.py`, the thresholds retire with the screens |

`build.py` and `render.py` currently import `screen_config` only to render the
methodology page from the live thresholds. With the screens gone, so does that
import.

## Credit budget

| Item | Per month | % of 20,000 |
|---|---|---|
| Tiered refresh (30 min prime, hourly shoulder, 4 leagues) | 7,560 | 38% |
| MLB pitcher props (15 events × 2 markets) | 900 | 5% |
| NFL props (16 events × 6 markets, ~5 days/wk) | 2,064 | 10% |
| NBA props (10 events × 5 markets) | 1,500 | 8% |
| Grading and scores (free sources) | 0 | 0% |
| **Total** | **12,024** | **60%** |

Props cost 1 credit per market per event, so unlike bulk odds they scale with
slate size. That is why NCAAB props are excluded and NCAAB keeps a board only.

Bulk odds cost 3 credits per league per pull regardless of slate size, so a
140-game NCAAB night costs the same as a 4-game one. Only props scale per
event, which is why they stay MLB-only.

The workflow tracks its own deploy count against Cloudflare's monthly cap and
skips a refresh rather than silently exhausting it.

## Light theme

Slate palette. All text meets or exceeds 5:1 contrast.

```
ground  #EEF1F4      text   #14181D   15.7:1
cards   #FFFFFF      muted  #525B65    6.1:1
panel2  #F7F9FB      dim    #828C97    3.0:1  (UI only, never body text)
line    #D8DEE4      green  #106E42    5.6:1
line2   #BFC7D0      red    #BE2F2F    5.1:1
```

The conversion is more than swapping tokens. Also required:

- Four hardcoded dark values in `base.css`: two `rgba(255,255,255,…)` washes,
  the white bar tick with its glow, and the nav's `rgba(6,10,13,.86)`.
- Six inline hero gradients in the page bodies, all
  `linear-gradient(180deg,#0A0C0F,var(--bg))` → `var(--bg-2)`.
- Team colours were lifted for contrast **against a dark panel**. The whole
  `TEAM_COLOR` legibility pass must be recomputed against white, and some
  clubs that needed lightening now need darkening.

### Type hierarchy — a rule, not a preference

The first light draft failed on legibility in a specific, measurable way:
`--dim` (#828C97, **3.4:1** on white) was carrying the market labels *and* the
losing side's win probability. A win probability is not chrome; it is half of
what the card exists to say. These assignments are now fixed:

| Role | Token | On white |
|---|---|---|
| Club names (both sides), primary numbers, best price | `--txt` #14181D, weight 700 | 17.8:1 |
| Records, starter, ERA, supporting stats | `--sub` #333A42 | 11.5:1 |
| Market labels, card headers, units | `--muted` #525B65 | 6.9:1 |
| Footnote captions under a large number only | `--dim` #828C97 | 3.4:1 |

Two rules follow, and a build check enforces the second:

1. **Both clubs are equally legible.** The earlier card marked our pick by
   dimming the *other* club's name, which made one of the two teams harder to
   read on every card. The green percentage already signals which side we
   favour; the name does not need to help.
2. **`--dim` never carries anything a reader needs.** It is only valid for a
   caption beneath a figure that already conveys the meaning.

## Historical backtesting

The $30 tier includes historical odds. Snapshots run back to 6 June 2020 at
5-minute granularity, and cost **10 credits per region per market** — ten times
live. Each call is one point in time, so opening and closing prices are two
calls.

### Why this matters more than it looks

Without history the Accuracy page has nothing to say at launch. Closing-line
value needs roughly 50–65 games before it separates skill from chance, and
profit needs thousands. With one season of historical closes the model can be
scored against ~2,400 MLB games on day one, at a sample size where the sigma
means something.

It also lets Elo be tuned — K-factor, home advantage, starter weighting —
against outcomes it never saw, rather than shipping guessed constants and
learning slowly. And it answers the shelf-life question: 5-minute snapshots
make it possible to measure how long a mispriced number actually survives,
which no competitor publishes.

### Cost, and the cheap way to buy it

| Pull | Credits |
|---|---|
| MLB season, moneyline only, open + close | 3,700 |
| MLB season, all three markets, open + close | 11,100 |
| Four leagues, one season, all markets | 44,400 |

The 20K tier leaves ~11,500 spare a month, which covers the first two. The
full four-league pull does not fit — but the 100K tier is $59, and **the
backtest is a one-off, not a recurring cost**. Run a single month on 100K,
harvest everything, drop back to 20K for the live site. $29 once.

### The rule that keeps this honest

A backtest is not a track record, and blurring the two is the exact behaviour
this site exists to be the opposite of. Betaminic is the model here: they label
every segment RP (research period) or SS (since shared) and publish the ratio
between them, because backtests decay on contact with reality.

Non-negotiable:

1. **Backtested results are labelled as backtest**, rendered in a visually
   distinct band, and **never summed with live results** in any figure.
2. **The decay ratio is published** — live performance as a percentage of
   backtested performance — as its own number, from the first live week.
3. **Tuning and reporting use different data.** Elo constants are fitted on one
   split and accuracy is reported from the other. Tuning on the same games we
   then report from is overfitting dressed as evidence.
4. **The pull is archived to the repository** as raw JSON, so any figure can be
   recomputed later without spending credits again and without trusting a
   number nobody can re-derive.

### Sequence

This comes *after* the live board works. It depends on `fair.py` and
`ratings.py` — the same devig and rating code the live path uses — because a
backtest run through different code than production proves nothing about
production.

### Unverified

How far back player props go. The docs note additional market data after
3 May 2023, which suggests pitcher strikeout lines have a shorter history than
moneylines. To be probed with a handful of credits before any props backtest is
designed.

## Failure handling

| Failure | Behaviour |
|---|---|
| ESPN unreachable or shape changed | Live scores silently absent; page shows build-time state. Never blocks a render. |
| Free score source fails at grading | Falls back to the Odds API `/scores` for that league only |
| Odds pull fails for one league | That league keeps the previous build's prices, card shows the timestamp it was last confirmed |
| Cloudflare build budget near cap | Refresh skipped, logged, daily build still runs |
| `localStorage` throws | Book picker falls back to all books |
| A league out of season | Skipped entirely; no empty tab, no wasted credits |

## Testing

Self-tests in the `stats.py` style — `python scripts/<module>.py` runs them,
no test runner:

- `fair.py` — devig methods against hand-computed values on a known −300/+240
  market; probabilities sum to 1; best-book selection respects a book filter.
- `ratings.py` — Elo conserves total rating across a game; a result dated after
  the rating date can never influence it (no look-ahead).
- `results.py` — parses a recorded ESPN and StatsAPI payload fixture; a missing
  or malformed field yields no score rather than a crash.
- `board.py` — a league with no games, a game with one book, and a game with a
  missing market all render.
- Build — every page emits with no unreplaced `{{TOKEN}}` and no `[[key]]`.
- Contrast — the palette check that produced the table above, kept as a test,
  extended to assert no element in the card or props templates uses `--dim`
  for anything but a caption.
- Layout — zero horizontal overflow at 390px on every generated page.
- `search_index.py` — a team, a nickname, a player and a matchup query each
  return the expected entry; the index stays under a size budget.

## Out of scope for this build

A +EV screen or alerts. Accounts, bet tracking, or a bet slip. Research for
NBA/NFL/NCAAB beyond Elo, records and form. Spanish. Sub-hourly odds.

**Deferred, not abandoned** — these have a designed place waiting for them and
should not be quietly dropped:

- **A totals model.** Until it exists the total row says "market only".
- **Props beyond MLB strikeouts.** The props tab exists per sport; only MLB is
  populated at launch.
- **Per-game pages.** A static site generates these for free and they are good
  for search traffic. The card's disclosure is the interim answer.

## Known thin spots, to be stated on the site rather than hidden

- NFL Elo is thin: 17 games a season means ratings move slowly and mean little
  early.
- NCAAB needs most of a season before ratings are meaningful, across 350+ teams.
- ESPN's endpoint is undocumented and can change without notice.
- Fair prices are only as good as the book set behind them; a market priced by
  few books produces a soft consensus, and the card should say so.
