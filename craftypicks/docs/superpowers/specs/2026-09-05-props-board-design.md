# The MLB Props Board — Design

**Date:** 2026-09-05
**Status:** approved in conversation, pending implementation plan

## Goal

Collapse MLB's six nav items into two. One board, two views — Games and
Props — with the props filtered by chip: **Ks, Hits, HR**. Every number on
it is free, and every projection is graded, as everything on this site is.

## Global Constraints

- **No new paid data.** Nothing here may call The Odds API. The daily credit
  spend must not change by one credit.
- **Python 3.11 standard library only**, in the build and the scripts.
- **No third-party JavaScript.** No framework, no CDN, no runtime fetch.
- **Every projection is graded**, and **nothing is graded before its game has
  finished** — `projection.game_over` is the gate.
- Tests are `_self_test()` at the module bottom, run with
  `python3 scripts/<module>.py`. No pytest, no `tests/` directory.
- Parsers pure, fetches thin: this sandbox reaches no host but the repo, so
  anything testable only online is untestable.
- `limit=100` on `statSplits`, `gameType=R` on `/schedule`,
  `playerPool=All` on the hitting leaderboard. Each has silently corrupted
  data on this site before.
- `python3 scripts/palette.py` must pass. `--dim` is 3.0:1.
- f-strings cannot reuse the outer quote character or contain a backslash.

## Scope

**In:** the unified board, three prop chips, the per-player card with its
history columns, a free strikeout projection, and redirects from the four
pages this replaces.

**Out:** total bases — a new model and its own grading, where the other
three already exist. Four chips that work beat five where one is half-built.

**Out:** the book price. Player props are billed per event, and this board
exists to be free. Its absence is not a gap: the board's claim is "we make
it 73.6%", which stands without a line beside it.

**Out:** NFL, NBA and NCAAB. If this shape works for MLB it should spread,
but proving it once costs less than building it four times.

---

## 1. The page

`mlb/index.html` becomes the whole MLB board.

```
[ GAMES | PROPS ]                     <- view toggle
[ ALL | Ks | HITS | HR ]              <- chips, props view only
```

MLB's nav becomes **Board** and **Form**. `hits.html`, `batters.html`,
`homers.html` and `pitchers.html` become redirects into the right filtered
view, so nothing anyone has bookmarked breaks.

### Why JavaScript here, and how little of it

This site ships no JavaScript today. Filtering needs some. The version that
keeps the site's "it is just a file" property:

- **Every row is rendered into the HTML at build time.** The chips do not
  fetch, and no data is loaded at runtime.
- **JS only toggles visibility** — it adds and removes a class. Nothing
  computes a number in the browser.
- **The page is correct with JS switched off**: all rows visible, chips
  inert. A reader sees more than they asked for, never less, and never a
  blank screen.

No framework, no CDN, no build step. Roughly forty lines, inlined like the
CSS already is.

## 2. What each card carries

Per player, matching what the board is for — our number, and enough history
to argue with it:

| Field | Where it comes from |
|---|---|
| `OUR %` | `hits.chance`, `batters.chance`, or the K projection |
| `'26` | Season rate — already parsed |
| `H2H` | `mlb_api.vs_batter()` — **written months ago, never called** |
| `L5` / `L10` | New. A batter game log per player. |
| `STR` | Current streak, out of the same game log |
| `MATCH` | `matchup.verdict()` — already grades favourable/tough |
| Park | Already on every hits and HR row |

`vs_batter` returns `plateAppearances`, `strikeOuts`, `hits`, `homeRuns` in
one payload, so a single call serves H2H for all three props at once.

**Cost:** about 54 game-log calls and 54 H2H calls a night, all free,
roughly fifteen seconds at the existing pause. No paid request is added.

## 3. The free strikeout projection

`pitchers.build` opens with `if not prop_events: return []`, so the Ks board
exists only on nights props were bought. But everything it needs is already
free: the starters, their hands, the club strikeout splits, and each
opponent's strikeouts per game. Only the *loop* is over posted lines.

So the projection is extracted to run over `starters` instead of over
quotes. On a night props are bought, the posted line is shown beside it as
now. On a night they are not, the projection stands alone.

**This changes no existing number** — the same arithmetic, iterated
differently. The paid path keeps working exactly as it does.

## 4. Grading

Unchanged in mechanism, because it already works: the leaderboard is
refetched every morning, so a season total today against the total stored at
projection says whether the thing happened. Free, and impossible to skip.

Strikeouts grade against the starter's own line for that game.

**Nothing is graded before its game has finished.** `projection.game_over`
gates every store. This site published "promised 60%, delivered 0%" once,
because a thrice-daily job graded rows it had written that morning; the gate
is why that cannot recur, and every new store inherits it.

## 5. File structure

| File | Responsibility |
|---|---|
| `scripts/gamelog.py` (create) | Batter game logs → L5, L10, streak. Thin fetch, pure parsers. |
| `scripts/h2h.py` (create) | Batter-vs-pitcher history, wrapping the existing `vs_batter`. |
| `scripts/k_projection.py` (create) | The strikeout projection, freed from the posted line. |
| `scripts/props_board.py` (create) | Assembles one row per player per prop. Knows no models — it composes them. |
| `scripts/pitchers.py` (modify) | Its projection moves to `k_projection`; it keeps the paid line-comparison. |
| `scripts/run_boards.py` (modify) | Builds the props board. |
| `_src/build.py` (modify) | The unified page, the four redirects, nav down to two. |
| `_src/render.py` (modify) | The toggle, the chips, the player card. |
| `_src/board.js` (create) | The forty lines, inlined at build time. |

`props_board.py` composes and does not model. That boundary is what stops it
becoming the place where a fourth prop's special cases accumulate.

## 6. Error handling

Every board is optional and none may take down the daily run.

- Each import guarded, and **every name in a shared `try` cleared in its
  `except`** — the three-name import that left `homers_mod` undefined was
  exactly this bug.
- **An unreachable feed must never blank the board.** No data means the
  previous board stays and the run says why.
- A per-player call that fails leaves that player's history column empty
  rather than dropping the player. A missing L10 is a gap; a missing player
  is a wrong board.

## 7. Testing

- Pure parsers tested offline against committed fixtures. This is the only
  testing possible in an environment with no network.
- **A test may not stub the function it is testing.** `nfl_yards.schedule`
  called a function that did not exist and every test stubbed `schedule`
  itself, so all four NFL boards would have shipped permanently empty.
  Stub the HTTP layer.
- The build's registry invariants must still pass, including the assertion
  that every page in a league's `VIEWS` declares that league.
- A full build must pass `palette.py`.
- The page must be checked with JavaScript disabled: all rows visible.

## 8. Order of work

1. `gamelog.py` — L5, L10, streak. Independent, testable, no page.
2. `h2h.py` — wraps a function that already exists.
3. `k_projection.py` — extract from `pitchers.py`, proving the numbers
   are unchanged before anything depends on it.
4. `props_board.py` — compose the three props into rows.
5. The page: toggle, chips, card, the forty lines of JS.
6. Redirects, nav, `run_boards.py`, ship.

Steps 1–3 depend on nothing and each ship something testable on its own.
