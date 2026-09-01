# Our Number On The Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put Craftypicks' own win probability on every card beside the market's, and start accumulating the free score data the other three leagues will need to have one.

**Architecture:** MLB is already rated — `slate.py` produces a starter-adjusted win probability for every game today, and the board simply does not read it. Task 1 merges that in by event id. Task 2 rebuilds the board card around the two numbers, reusing the rich card `render.slate_rows` already draws. Tasks 3 to 5 build the general path: a probe that verifies the two free score sources agree on team names, a results cache that grows by one day per daily run, and Elo ratings for any league with enough history.

**Tech Stack:** Python 3.12 standard library only; hand-written CSS and HTML; no JavaScript; no build tooling, no test runner.

## Global Constraints

- **Standard library only.** No pip installs. The site's whole hosting story depends on this.
- **No test runner exists.** Each module defines `_self_test()` and runs it under `if __name__ == "__main__":`. Tests are run with `python3 scripts/<module>.py`, which prints a confirmation line and exits non-zero on failure. Do not introduce pytest.
- **Never print a bare English sentence from `render.py` or `build.py`.** Every reader-facing string lives in `_src/i18n.py` and is reached through `i18n.t(key, lang)` — in `render.py` through the `_()` shorthand.
- **All text meets or exceeds 5:1 contrast**, with one exception: `--dim`, which is UI-only, never carries body text, and may only be used by a selector listed in `DIM_ALLOWED` in `scripts/palette.py`. `python3 scripts/palette.py` enforces this, and it also scans `render.py` for inline styles.
- **Both clubs on a game card are equally legible.** Neither side's name nor win probability may be dimmed to signal a pick.
- **Never show a number we do not have.** A game with no rating shows no percentage, not a placeholder and not the market's number wearing our label. A total never shows a Craftypicks number at all, because Elo produces a win probability and not a run distribution.
- **The daily job runs unattended and commits its own output.** Nothing added here may raise out of `run_daily.py`, and no failure may silently empty a file that had content yesterday.
- **Every public function gets a docstring stating what it does and one thing it deliberately does not do.** Match the existing style in `scripts/odds_math.py`.
- Working directory for all commands is the repository's `craftypicks/` directory.

---

### Task 1: Merge MLB's rating into the board

`slate.py` already computes a starter-adjusted win probability for every MLB game, writes it to `data/slate.json`, and the board ignores it. Today's file has all fifteen games with `home_win_prob`, `market_home_prob` and `disagreement` — and every `event_id` matches the board's exactly.

This is the smallest change in the plan and the most visible: the cards get their percentages back.

**Files:**
- Modify: `scripts/board.py` — add `merge_model`
- Modify: `scripts/run_daily.py` — call it before writing `board.json`

**Interfaces:**
- Consumes: the board row shape from `board.price_game` — `event_id`, `league`, `commence_time`, `home`, `away`, `markets`, `model`; and `slate.build`'s row shape, which carries `event_id`, `home_win_prob`, `away_win_prob`, `market_home_prob`, `disagreement`, `suspect`, `home_record`, `away_record`, `home_starter`, `away_starter`, `home_starter_era`, `away_starter_era`, `home_hand`, `away_hand`, `home_vs_opp`, `away_vs_opp`
- Produces: `merge_model(rows: list[dict], rated: list[dict], source: str) -> int` — fills `model` and `detail` on matching rows, returns how many it matched

- [ ] **Step 1: Write the failing test**

Add to `_self_test()` in `scripts/board.py`, before its `print(...)`:

```python
    # --- merging a rating onto a priced board -------------------------------
    board_rows = [
        {"event_id": "e1", "league": "mlb", "home": "H", "away": "A",
         "commence_time": "2026-09-01T23:00:00Z", "markets": {}, "model": None},
        {"event_id": "e2", "league": "mlb", "home": "H2", "away": "A2",
         "commence_time": "2026-09-01T23:00:00Z", "markets": {}, "model": None},
    ]
    rated = [
        {"event_id": "e1", "home_win_prob": 0.4425, "away_win_prob": 0.5575,
         "market_home_prob": 0.4376, "disagreement": 0.5, "suspect": False,
         "home_record": {"w": 70, "l": 60}, "away_record": {"w": 65, "l": 65},
         "home_starter": "Hunter Greene", "home_starter_era": 3.11,
         "home_hand": "R", "away_starter": "Yu Darvish",
         "away_starter_era": 4.02, "away_hand": "R",
         "home_vs_opp": None, "away_vs_opp": None},
        # A rated game that is not on the board at all — a postponement, or a
        # game the pricing dropped for want of books. It must be ignored, not
        # appended: the board is the list of games we can price.
        {"event_id": "gone", "home_win_prob": 0.5, "away_win_prob": 0.5},
    ]

    matched = merge_model(board_rows, rated, "slate")
    assert matched == 1, matched
    assert len(board_rows) == 2, "merging must not add or drop rows"

    m = board_rows[0]["model"]
    assert m["home_win_prob"] == 0.4425 and m["away_win_prob"] == 0.5575
    assert m["market_home_prob"] == 0.4376
    assert m["disagreement"] == 0.5
    assert m["suspect"] is False
    assert m["source"] == "slate", "the card has to say where the number came from"

    d = board_rows[0]["detail"]
    assert d["home_starter"] == "Hunter Greene"
    assert d["home_record"] == {"w": 70, "l": 60}
    assert "home_win_prob" not in d, \
        "the general numbers live in model; detail is the sport-specific extra"

    # An unmatched game keeps its empty model rather than inheriting a
    # neighbour's. Showing one game's number on another is worse than none.
    assert board_rows[1]["model"] is None
    assert board_rows[1].get("detail") is None

    # A rating with no probability is not a rating.
    half = [{"event_id": "e2", "market_home_prob": 0.5}]
    assert merge_model(board_rows, half, "slate") == 0
    assert board_rows[1]["model"] is None

    # The probabilities must be a coherent pair; a rating that does not sum
    # to 1 is a bug upstream and must not reach a card.
    bad = [{"event_id": "e2", "home_win_prob": 0.6, "away_win_prob": 0.6}]
    assert merge_model(board_rows, half + bad, "slate") == 0
    assert board_rows[1]["model"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/board.py`
Expected: `NameError: name 'merge_model' is not defined`

- [ ] **Step 3: Write the implementation**

Add to `scripts/board.py`, above `_self_test`:

```python
# The sport-specific extras a card may show beneath a club's name. Kept apart
# from `model` on purpose: every league has a win probability, only baseball
# has a starting pitcher, and mixing them would make the general path carry
# baseball's vocabulary into leagues that have no use for it.
DETAIL_KEYS = (
    "home_record", "away_record",
    "home_starter", "away_starter",
    "home_starter_era", "away_starter_era",
    "home_hand", "away_hand",
    "home_vs_opp", "away_vs_opp",
)


def merge_model(rows: list[dict], rated: list[dict], source: str) -> int:
    """Attach a rating to each board row that has one, by event id.

    Returns the number of rows matched. A rated game missing from the board is
    ignored rather than appended — the board is the list of games we could
    price, and a game with no price has nothing to compare a number against.

    Deliberately does not invent a rating for an unmatched row. A card with no
    percentage is honest; a card showing the market's number in our colour, or
    a neighbour's number, is not.
    """
    by_id = {}
    for r in rated:
        eid = r.get("event_id")
        if eid:
            by_id[eid] = r

    matched = 0
    for row in rows:
        rating = by_id.get(row.get("event_id"))
        if not rating:
            continue

        hp, ap = rating.get("home_win_prob"), rating.get("away_win_prob")
        if hp is None or ap is None:
            continue
        # A pair that does not sum to 1 means something upstream went wrong.
        # Better to show no number than a number we cannot explain.
        if abs(hp + ap - 1.0) > 1e-6:
            continue

        row["model"] = {
            "home_win_prob": hp,
            "away_win_prob": ap,
            "market_home_prob": rating.get("market_home_prob"),
            "disagreement": rating.get("disagreement"),
            "suspect": bool(rating.get("suspect")),
            "source": source,
        }
        detail = {k: rating[k] for k in DETAIL_KEYS if rating.get(k) is not None}
        if detail:
            row["detail"] = detail
        matched += 1
    return matched
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/board.py`
Expected: `board self-test: all invariants hold`

- [ ] **Step 5: Call it from the daily job**

In `scripts/run_daily.py`, find where `slate_rows` is produced for MLB inside the per-sport loop (the `if slate_mod and sport == "baseball_mlb":` block). Immediately after `slate_rows` is assigned, add:

```python
                # The board already has this game priced; slate has it rated.
                # Same event ids, so the two join cleanly.
                if board_mod and lg and boards.get(lg.short):
                    n = board_mod.merge_model(boards[lg.short], slate_rows,
                                              "slate")
                    print(f"   board: {n} {lg.short} game(s) carry our number")
```

`lg` is the `League` the board step already resolved for this sport. If the board step runs after the slate step in the current file, move the merge below both — it needs `boards[lg.short]` to exist.

- [ ] **Step 6: Run the daily job and confirm the numbers land**

Run:

```bash
CRAFTYPICKS_MOCK=1 python3 scripts/run_daily.py 2>&1 | grep -i "our number"
python3 -c "
import json; d=json.load(open('data/board.json'))
for short, lg in d['leagues'].items():
    rated=[g for g in lg['games'] if g.get('model')]
    print(f'{short}: {len(rated)} of {len(lg[\"games\"])} carry a model')
    if rated:
        m=rated[0]['model']
        print('  ', rated[0]['away'], '@', rated[0]['home'])
        print('   ours', round(m['home_win_prob']*100,1), '% home | market',
              None if m['market_home_prob'] is None else round(m['market_home_prob']*100,1), '%')
"
```

Expected: a `game(s) carry our number` line, then a count above zero for MLB with our percentage and the market's printed side by side. Mock mode spends no credits.

- [ ] **Step 7: Commit**

```bash
git add scripts/board.py scripts/run_daily.py data/board.json
git commit -m "feat: the board carries our number, not only the market's"
```

---

### Task 2: The card the spec asked for

`render.board_card` shows club names and a market block. `render.slate_rows` — the old MLB-only board — already draws the card the spec describes: both clubs at full strength with their records and venue split, the starter and ERA, and a probability bar with the market's number marked as a tick. The board card is the poorer of the two, and the richer one is about to lose its page.

This task moves that content onto the board card, driven by the `model` and `detail` that Task 1 puts in `board.json`.

**The bar is the point.** Two percentages side by side make a reader do arithmetic. A bar with a tick shows the disagreement as a distance, which is the thing the site exists to make visible.

**Files:**
- Modify: `_src/render.py` — `board_card`, and a new `_prob_bar`
- Modify: `_src/base.css` — reuse `.gbar`, add nothing new if the existing rules fit
- Modify: `_src/i18n.py` — labels for the bar's footer

**Interfaces:**
- Consumes: `model` and `detail` from Task 1; the existing `_side(team, starter, era, prob, leading, rec=None, at_home=False, vs=None, opponent=None) -> str`, `_record_line(rec, at_home) -> str`, `_vs_line(vs, opponent) -> str`, `_nickname(team) -> str`
- Produces: `_prob_bar(model: dict | None) -> str`

- [ ] **Step 1: Write the failing test**

Add to `_self_test()` in `_src/render.py`, before its `print(...)`. The fixture there already has a `row` with a `model`; extend it:

```python
    # --- the probability bar ------------------------------------------------
    rated = {**row, "model": {
        "home_win_prob": 0.556, "away_win_prob": 0.444,
        "market_home_prob": 0.503, "disagreement": 5.3,
        "suspect": False, "source": "slate"},
        "detail": {"home_record": {"w": 74, "l": 56},
                   "away_record": {"w": 77, "l": 53},
                   "home_starter": "Freddy Peralta", "home_starter_era": 3.47,
                   "away_starter": "Shota Imanaga", "away_starter_era": 3.24}}

    bar = _prob_bar(rated["model"])
    assert 'class="gbar"' in bar
    assert 'class="tick"' in bar, "the market's own number has to be marked"
    # The bar reads left to right as the away club's chance, so the market's
    # tick sits at 1 - market_home_prob.
    assert "49.7%" in bar, "the tick is placed on the away side of the bar"

    # No market number means no tick, rather than a tick at zero.
    assert 'class="tick"' not in _prob_bar(
        {**rated["model"], "market_home_prob": None})

    # No model at all means no bar, rather than an empty one.
    assert _prob_bar(None) == ""

    card = board_card(rated)
    assert "55.6" in card and "44.4" in card, "both percentages are printed"
    assert "74" in card and "56" in card, "records reach the card"
    assert "Freddy Peralta" in card and "3.47" in card
    assert "var(--dim)" not in card, "everything on a card is content"

    # A game we have not rated shows the market block and no percentages,
    # rather than a placeholder or the market's number in our place.
    plain = board_card({**row, "model": None, "detail": None})
    assert "55.6" not in plain and "class=\"gbar\"" not in plain
    assert "MONEYLINE" in plain.upper() or i18n.t("mkt_moneyline", LANG) in plain
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 _src/render.py`
Expected: `NameError: name '_prob_bar' is not defined`

- [ ] **Step 3: Add the i18n strings**

Two of the three strings this card needs are already in `_src/i18n.py`, because `slate_rows` — the card this one is inheriting from — uses them:

- `market_tick` at line 103, "Where the market has it"
- `off_market` at line 84, "{v} pts off market"

**Reuse both. Do not add a second copy under a new name** — a duplicate key in the `T` dict silently shadows the first, and two keys saying the same thing drift apart the first time one of them is edited.

Only one string is genuinely new. Add it to the `T` table:

```python
    "agree_market": {"en": "in line with the market",
                     "es": "en línea con el mercado"},
```

- [ ] **Step 4: Write the bar and rebuild the card**

Add to `_src/render.py`, above `board_card`:

```python
def _prob_bar(model: dict | None) -> str:
    """The two numbers as one bar, with the market's own number as a tick.

    The bar fills left to right with the away club's chance, so the tick sits
    at 1 - market_home_prob. Printing the two percentages alone makes a reader
    do the subtraction; the distance between fill and tick is the disagreement
    without arithmetic.

    Does not scale the tick's prominence by how large the gap is. A two-point
    disagreement and a ten-point one are drawn identically, because the bar is
    a measurement and not an argument.
    """
    if not model:
        return ""
    away = model.get("away_win_prob")
    if away is None:
        return ""
    fill = max(0.0, min(100.0, away * 100))

    market_home = model.get("market_home_prob")
    tick = ""
    if market_home is not None:
        at = max(0.0, min(100.0, (1.0 - market_home) * 100))
        tick = (f'<div class="tick" style="left:{at:.1f}%" '
                f'title="{_("market_tick")}"></div>')

    gap = model.get("disagreement")
    if gap is None:
        foot = ""
    elif abs(gap) < 1.0:
        # Under a point the two numbers are the same number wearing different
        # rounding, and calling that a disagreement would cry wolf.
        foot = f'<div class="gfoot"><span>{_("agree_market")}</span></div>'
    else:
        cls = " flagged" if model.get("suspect") else ""
        foot = (f'<div class="gfoot"><span class="lean{cls}">'
                f'{_("off_market", v=f"{abs(gap):.1f}")}</span></div>')

    return (f'<div class="gbar"><div class="seg on" '
            f'style="width:{fill:.1f}%"></div>{tick}</div>{foot}')
```

Then rewrite `board_card`'s body so the two sides carry their detail and the bar sits between them. Replace its inner `side(...)` helper and the block that assembles `gcard-body` with:

```python
    detail = row.get("detail") or {}

    def side(which: str, team: str, prob: float | None,
             leading: bool) -> str:
        return _side(
            team,
            detail.get(f"{which}_starter"),
            detail.get(f"{which}_starter_era"),
            prob,
            leading,
            rec=detail.get(f"{which}_record"),
            at_home=(which == "home"),
            vs=detail.get(f"{which}_vs_opp"),
            opponent=row.get("home" if which == "away" else "away"),
        )
```

and build the body as away side, bar, home side, market block, disclosure. This is the inside of `board_card`'s returned f-string, not standalone Python — note that it mixes quote styles inside the braces, which Python 3.12 allows:

```html
        <div class="gcard-body">
          {side("away", row.get('away',''), ap, not lead_home and ap is not None)}
          {_prob_bar(model)}
          {side("home", row.get('home',''), hp, lead_home)}
          <div class="mk">{market_rows(row)}</div>
          <details class="gmore">
            <summary>{_("card_more")}</summary>
            <div class="gmore-in">{_book_table(row)}</div>
          </details>
        </div>
```

Read `_side`'s existing definition before wiring this up and match its parameter order exactly; it is the function `slate_rows` already uses, so it is known to render correctly.

- [ ] **Step 5: Run the tests and rebuild**

Run:

```bash
python3 _src/render.py && python3 scripts/palette.py && python3 _src/build.py
```

Expected: `render self-test: all invariants hold`, `palette self-test: all invariants hold`, then the built pages. The palette check matters here — it is what catches a card reaching for `--dim`.

- [ ] **Step 6: Look at it**

The whole task is a visual change, so look rather than trusting the count:

```bash
python3 - <<'PY'
from playwright.sync_api import sync_playwright
import pathlib
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1180, "height": 900})
    pg.goto(f"file://{pathlib.Path('mlb/index.html').resolve()}")
    pg.wait_for_timeout(1600)          # the bar animates in at ~850ms
    over = pg.evaluate("Math.max(0, document.documentElement.scrollWidth"
                       " - document.documentElement.clientWidth)")
    print("horizontal overflow:", over, "px")
    pg.screenshot(path="/tmp/card.png", clip={"x": 20, "y": 260,
                                              "width": 400, "height": 420})
    b.close()
PY
```

Expected: `0 px`. Open `/tmp/card.png` and confirm: both clubs named in full and equally dark, both percentages printed, the bar filled to the away club's share with a dark tick at the market's number, records and starters beneath each club, the market block below.

- [ ] **Step 7: Commit**

```bash
git add _src/render.py _src/i18n.py _src/base.css *.html */index.html
git commit -m "feat: the board card shows both numbers and the gap between them"
```

---

### Task 3: Probe the free score sources

Tasks 4 and 5 depend on two free endpoints — MLB's StatsAPI and ESPN's scoreboard — that this sandbox cannot reach and that nobody has verified from a machine that can. Two things need answering before code is built on them: are they reachable, and **do they spell team names the same way?**

The second question is the dangerous one. `ratings.run()` keys Elo on the team name string. If StatsAPI says "St. Louis Cardinals" and ESPN says "St Louis Cardinals", one fallback day mid-season creates a second club, splits that team's rating history in half, and nothing in the output looks wrong.

**`GITHUB_TOKEN` cannot create files under `.github/workflows/`, and no permission setting grants it.** This file is added by hand through GitHub's web editor. It is Task 3 rather than Task 6 because Tasks 4 and 5 need its answer.

**Files:**
- Create: `.github/workflows/probe.yml` — **by hand, through the GitHub web UI**

**Interfaces:**
- Consumes: `results.finals(league, date_str) -> list[dict]`, `results.parse_espn`, `results.parse_statsapi` from `scripts/results.py`
- Produces: nothing the site imports; its output is read by a human

- [ ] **Step 1: Add the workflow through the web UI**

In GitHub: **Add file → Create new file**, path `.github/workflows/probe.yml`, contents:

```yaml
name: Probe score sources

# Why this exists
# ---------------
# scripts/results.py reads finals from two free sources — MLB's own StatsAPI
# for baseball and ESPN's scoreboard for everything else. Neither is reachable
# from the development sandbox, so the parsers are tested against recorded
# fixtures and the live endpoints are checked here, from a runner that can
# actually reach them.
#
# The reachability answer is the easy half. The half that matters is whether
# the two sources spell team names identically: ratings.py keys Elo on the name
# string, so one fallback day mid-season would create a second club and split
# that team's rating history with nothing in the output looking wrong.
#
# This file cannot be delivered through the update archive — GITHUB_TOKEN may
# not write anything under .github/workflows — so it is pasted in by hand.

on:
  workflow_dispatch:
    inputs:
      date:
        description: "Date to probe, YYYY-MM-DD (blank = yesterday)"
        required: false
        default: ""

jobs:
  probe:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Reachability and team-name agreement
        working-directory: craftypicks
        env:
          PROBE_DATE: ${{ inputs.date }}
        run: |
          python3 - <<'PY'
          import datetime, gzip, json, os, sys
          sys.path.insert(0, "scripts")
          import results

          day = (os.environ.get("PROBE_DATE") or "").strip()
          if not day:
              day = (datetime.date.today()
                     - datetime.timedelta(days=1)).isoformat()
          print(f"probing {day}\n")

          # Only leagues plausibly playing on this date are treated as
          # must-have. A legitimate zero out of season is not a failure, and a
          # probe that cries wolf every June gets ignored by July.
          MONTHS = {"mlb": range(3, 11), "nfl": list(range(9, 13)) + [1, 2],
                    "nba": list(range(10, 13)) + list(range(1, 7)),
                    "ncaab": list(range(11, 13)) + list(range(1, 5))}
          month = int(day[5:7])

          failures = []
          rows_by_league = {}
          for league in ("mlb", "nfl", "nba", "ncaab"):
              try:
                  rows = results.finals(league, day)
              except Exception as e:                        # noqa: BLE001
                  print(f"{league:6} RAISED  {type(e).__name__}: {e}")
                  failures.append(f"{league} raised {type(e).__name__}")
                  continue
              rows_by_league[league] = rows
              in_season = month in MONTHS[league]
              note = "" if rows else ("  <-- expected games" if in_season
                                      else "  (out of season)")
              print(f"{league:6} {len(rows):3} final(s){note}")
              if in_season and not rows:
                  failures.append(f"{league} returned nothing in season")

          # The name question. Ask both sources for the same MLB day and
          # compare the sets; anything in one and not the other is a club whose
          # rating history would split the first time we fell back.
          print("\n--- MLB team names: StatsAPI vs ESPN")
          try:
              stats_rows = results.parse_statsapi(
                  results._get(results.STATSAPI.format(date=day)))
              url = f"{results.ESPN_BASE}/{results.ESPN_PATH['mlb']}/scoreboard"
              espn_rows = results.parse_espn(
                  results._get(f"{url}?dates={day.replace('-', '')}"))
              a = {r[k] for r in stats_rows for k in ("home", "away")}
              b = {r[k] for r in espn_rows for k in ("home", "away")}
              print(f"  StatsAPI: {len(a)} club(s)   ESPN: {len(b)} club(s)")
              only_a, only_b = sorted(a - b), sorted(b - a)
              if not a or not b:
                  print("  one source returned no games; cannot compare today")
              elif only_a or only_b:
                  print("  MISMATCH — these do not appear in both:")
                  for n in only_a:
                      print(f"    StatsAPI only: {n!r}")
                  for n in only_b:
                      print(f"    ESPN only:     {n!r}")
                  failures.append("team names differ between sources")
              else:
                  print("  every club spelled identically in both")
          except Exception as e:                            # noqa: BLE001
              print(f"  comparison failed: {type(e).__name__}: {e}")
              failures.append("name comparison raised")

          if failures:
              print("\nFAILED:")
              for f in failures:
                  print(f"  {f}")
              sys.exit(1)
          print("\nboth sources reachable and in agreement")
          PY
```

Commit it through the web UI.

- [ ] **Step 2: Run it and read the answer**

Actions → **Probe score sources** → **Run workflow**, leave the date blank.

Expected: a green run showing a final count per league and `every club spelled identically in both`.

**If it reports a mismatch, stop and read the list before continuing.** Task 4 has a step that depends on the answer, and the right fix — an alias map, or preferring one source per league — depends on which names differ and how. A mismatch is not a reason to abandon the plan; it is the reason the probe exists.

- [ ] **Step 3: Record what it said**

Append the probe's team-name verdict to `craftypicks/docs/superpowers/specs/2026-08-28-pricing-board-design.md`, under the "Unverified" heading, replacing whatever that section says about the score sources being unverified. State the date probed and the outcome, so the next person does not have to re-run it to find out.

```bash
git add docs/superpowers/specs/2026-08-28-pricing-board-design.md
git commit -m "docs: record what the score-source probe found"
```

---

### Task 4: A results cache that grows by itself

Elo needs a season of results. Fetching a whole season on every daily run would mean roughly 170 requests to ESPN for basketball alone — free, but slow and rude, and it would put the daily job's reliability at the mercy of an endpoint nobody promised us.

Instead the daily job fetches **one day**: yesterday. Results are appended to a per-league file, deduplicated by event, and the file grows one day at a time. It costs one request per in-season league per day, and after a few weeks there is a season's worth of history sitting in the repository.

**Files:**
- Create: `scripts/results_store.py`
- Modify: `scripts/run_daily.py` — append yesterday's finals once per run

**Interfaces:**
- Consumes: `results.finals(league, date_str) -> list[dict]` returning rows with `home`, `away`, `home_score`, `away_score`, `completed`, `date`
- Produces:
  - `path_for(league: str) -> pathlib.Path`
  - `load(league: str) -> list[dict]`
  - `merge(existing: list[dict], fresh: list[dict]) -> list[dict]`
  - `append_day(league: str, date_str: str, fetch=results.finals) -> int` — returns how many new results were stored

- [ ] **Step 1: Write the failing test**

Create `scripts/results_store.py`:

```python
#!/usr/bin/env python3
"""A growing store of finished games, one file per league."""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DATA = HERE.parent / "data" / "results"


def _self_test() -> None:
    a = {"date": "2026-09-01", "home": "H", "away": "A",
         "home_score": 5, "away_score": 3, "completed": True}
    b = {"date": "2026-09-01", "home": "C", "away": "D",
         "home_score": 1, "away_score": 2, "completed": True}

    # Merging is idempotent: the same day fetched twice stores one copy.
    assert len(merge([], [a, b])) == 2
    assert len(merge([a, b], [a, b])) == 2
    assert len(merge([a], [a, b])) == 2

    # A corrected score replaces the earlier row rather than sitting beside it.
    fixed = {**a, "home_score": 6}
    out = merge([a, b], [fixed])
    assert len(out) == 2
    assert [r for r in out if r["home"] == "H"][0]["home_score"] == 6

    # Unfinished games are not results and must never enter the store; Elo
    # would treat a 0-0 game in progress as a genuine tie.
    live = {"date": "2026-09-01", "home": "E", "away": "F",
            "home_score": 0, "away_score": 0, "completed": False}
    assert merge([], [live]) == []

    # A row missing a score is dropped rather than stored as zero.
    assert merge([], [{"date": "2026-09-01", "home": "G", "away": "H",
                       "completed": True}]) == []

    # The store stays sorted by date, so a reader can trust the order and
    # ratings.run gets its input in the order it expects.
    later = {**a, "date": "2026-09-02", "home": "X", "away": "Y"}
    assert [r["date"] for r in merge([later], [a])] == \
        ["2026-09-01", "2026-09-02"]

    # append_day never lets a fetch failure empty a file that had content.
    def boom(league, day):
        raise RuntimeError("ESPN is down")

    before = load("mlb")
    assert append_day("mlb", "2026-09-01", fetch=boom) == 0
    assert load("mlb") == before, "a failed fetch must not touch the store"

    print("results_store self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/results_store.py`
Expected: `NameError: name 'merge' is not defined`

- [ ] **Step 3: Write the implementation**

Insert above `_self_test`, and add `import results` beneath the `sys.path` line:

```python
import results  # noqa: E402


def path_for(league: str) -> pathlib.Path:
    """Where one league's finished games are kept.

    One file per league rather than one big file: they are written on
    different days as seasons start and end, and a single file would rewrite
    every league's history every morning for no reason.

    Does not create the directory. Callers that write are the ones that make
    it, so a read of a league we have never stored stays side-effect free.
    """
    return DATA / f"{league}.json"


def load(league: str) -> list[dict]:
    """Every finished game stored for a league, oldest first.

    Does not distinguish a league we have never stored from one whose file is
    corrupt — both return an empty list. The daily job must keep running
    either way, and a rating built from nothing is visibly absent rather than
    quietly wrong.
    """
    path = path_for(league)
    if not path.exists():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"!! {path.name} is not valid JSON; treating as empty",
              file=sys.stderr)
        return []
    return doc.get("games") or []


def _key(row: dict) -> tuple:
    return (row.get("date"), row.get("home"), row.get("away"))


def merge(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Existing results plus new ones, deduplicated and sorted by date.

    A row already present is replaced by the fresh copy, so a score corrected
    hours after the final lands on top of the wrong one instead of beside it.
    Games that are not finished, or that carry no score, are dropped: Elo would
    read an in-progress 0-0 as a genuine tie.

    Does not verify that a team name matches any other source's spelling. That
    is what the probe workflow is for, and doing it here would mean carrying an
    alias map into a module whose job is storage.
    """
    out = {_key(r): r for r in existing}
    for row in fresh:
        if not row.get("completed"):
            continue
        if row.get("home_score") is None or row.get("away_score") is None:
            continue
        if not row.get("home") or not row.get("away") or not row.get("date"):
            continue
        out[_key(row)] = row
    return sorted(out.values(), key=lambda r: (r["date"], r["home"]))


def append_day(league: str, date_str: str, fetch=results.finals) -> int:
    """Fetch one day's finals for a league and add them to the store.

    Returns how many rows the store gained. A failed fetch returns 0 and
    leaves the file exactly as it was — an unattended job that empties its own
    history because a third-party endpoint had a bad minute is worse than one
    that skips a day.

    Does not backfill. One day per run is the whole design: a season
    accumulates for one request a day rather than 170 in one morning.
    """
    existing = load(league)
    try:
        fresh = fetch(league, date_str)
    except Exception as e:                                   # noqa: BLE001
        print(f"!! results for {league} {date_str} unavailable "
              f"({type(e).__name__}: {e}); store left alone", file=sys.stderr)
        return 0

    merged = merge(existing, fresh)
    gained = len(merged) - len(existing)
    if gained or merged != existing:
        DATA.mkdir(parents=True, exist_ok=True)
        path_for(league).write_text(
            json.dumps({"league": league, "games": merged}, indent=1),
            encoding="utf-8")
    return gained
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/results_store.py`
Expected: `results_store self-test: all invariants hold`

- [ ] **Step 5: Call it once per run**

In `scripts/run_daily.py`, beside the other optional imports at the top:

```python
# Yesterday's finals, from the free sources. Optional like everything else:
# the card must go out whether or not ESPN answered.
try:
    import results_store  # noqa: E402
except Exception as _rs_err:                                 # noqa: BLE001
    results_store = None
    print(f"!! results store unavailable ({_rs_err})", file=sys.stderr)
```

and after the per-sport loop finishes, before the board document is written:

```python
    if results_store and leagues:
        yesterday = (now.date() - timedelta(days=1)).isoformat()
        for short in leagues.ORDER:
            # append_day swallows a failed fetch itself, but not a bug in its
            # own merge. Nothing below this line catches an exception, and the
            # card has to go out.
            try:
                gained = results_store.append_day(short, yesterday)
                if gained:
                    print(f"-- results: +{gained} {short} final(s) "
                          f"for {yesterday}")
            except Exception as e:                           # noqa: BLE001
                print(f"!! storing {short} results failed "
                      f"({type(e).__name__}: {e})", file=sys.stderr)
```

`timedelta` is already imported at the top of `run_daily.py`; confirm it before relying on it.

- [ ] **Step 6: Confirm it does not break the daily job**

The sandbox cannot reach ESPN or StatsAPI, so every fetch here will fail — which is exactly the path worth testing:

```bash
CRAFTYPICKS_MOCK=1 python3 scripts/run_daily.py 2>&1 | tail -20; echo "exit=$?"
```

Expected: `!! results for ... unavailable` lines for each league, `exit=0`, and the run completing normally with `board.json` and the card still written. A failure of the score sources must not take the site down.

- [ ] **Step 7: Commit**

```bash
git add scripts/results_store.py scripts/run_daily.py
git commit -m "feat: accumulate finished games one day at a time, for free"
```

---

### Task 5: Rate a league once there is enough history

With results accumulating, any league with enough of them can be rated by `ratings.py` and merged onto the board the same way MLB's slate rating is.

**Be clear about what this shows today.** Of the four leagues, only MLB is in season on 1 September 2026 — the last month of archives holds baseball every day, NFL pre-season until 29 August, and nothing else. NFL's regular season starts in days; NBA and college basketball start in late October. So this task's visible effect right now is nil, and that is expected: it is the machinery that makes those leagues arrive already rated rather than needing work on the morning their season opens.

**Files:**
- Modify: `scripts/board.py` — add `elo_model`
- Modify: `scripts/run_daily.py` — merge it for leagues that qualify

**Interfaces:**
- Consumes: `ratings.LEAGUE_CONFIG: dict[str, EloConfig]`, `ratings.run(results, config) -> dict[str, float]`, `ratings.win_probability(rating_home, rating_away, config) -> float`; `results_store.load(league) -> list[dict]`; `merge_model(rows, rated, source)` from Task 1
- Produces: `elo_model(rows: list[dict], history: list[dict], short: str, min_games: int = 100) -> list[dict]` — rating rows in `merge_model`'s input shape

- [ ] **Step 1: Write the failing test**

Add to `_self_test()` in `scripts/board.py`, before its `print(...)`:

```python
    # --- rating a league from its stored results ---------------------------
    history = []
    for i in range(60):
        # Alpha beats Bravo consistently; Charlie and Delta split.
        history.append({"date": f"2026-04-{i % 28 + 1:02d}", "home": "Alpha",
                        "away": "Bravo", "home_score": 5, "away_score": 3})
        history.append({"date": f"2026-04-{i % 28 + 1:02d}", "home": "Charlie",
                        "away": "Delta",
                        "home_score": 4 + i % 2, "away_score": 5 - i % 2})

    upcoming = [{"event_id": "n1", "league": "nba", "home": "Alpha",
                 "away": "Bravo", "markets": {}, "model": None}]

    rated = elo_model(upcoming, history, "nba", min_games=100)
    assert len(rated) == 1, rated
    r = rated[0]
    assert r["event_id"] == "n1"
    assert 0.0 < r["home_win_prob"] < 1.0
    assert abs(r["home_win_prob"] + r["away_win_prob"] - 1.0) < 1e-9
    assert r["home_win_prob"] > 0.5, "Alpha has beaten Bravo sixty times"

    # Too little history means no rating at all. A number built on nine games
    # is noise wearing a percentage sign.
    assert elo_model(upcoming, history[:9], "nba", min_games=100) == []

    # A game whose clubs are not in the history is skipped rather than rated
    # from the starting value, which would be a coin flip dressed as a model.
    stranger = [{"event_id": "n2", "league": "nba", "home": "Echo",
                 "away": "Foxtrot", "markets": {}, "model": None}]
    assert elo_model(stranger, history, "nba", min_games=100) == []

    # An unknown league has no Elo settings and must not borrow another's.
    assert elo_model(upcoming, history, "cricket", min_games=1) == []

    # And the output slots straight into merge_model.
    assert merge_model(upcoming, rated, "elo") == 1
    assert upcoming[0]["model"]["source"] == "elo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/board.py`
Expected: `NameError: name 'elo_model' is not defined`

- [ ] **Step 3: Write the implementation**

Add to `scripts/board.py`, above `_self_test`, and `import ratings` beside the other imports:

```python
def elo_model(rows: list[dict], history: list[dict], short: str,
              min_games: int = 100) -> list[dict]:
    """Rate a league's upcoming games from its stored results.

    Returns rating rows shaped for merge_model. A league with fewer than
    min_games of history is not rated at all: Elo needs a season to say
    anything, and a number built on a handful of games is noise wearing a
    percentage sign. A game whose clubs are absent from the history is skipped
    for the same reason — rating it from the starting value would publish a
    coin flip as a model.

    Deliberately carries no market comparison. merge_model fills
    market_home_prob from whatever rated the game, and Elo alone does not know
    what the market thinks; the board's own pricing supplies that separately.
    """
    config = ratings.LEAGUE_CONFIG.get(short)
    if not config or len(history) < min_games:
        return []

    table = ratings.run(history, config)
    out = []
    for row in rows:
        home, away = row.get("home"), row.get("away")
        if home not in table or away not in table:
            continue
        hp = ratings.win_probability(table[home], table[away], config)
        out.append({
            "event_id": row.get("event_id"),
            "home_win_prob": hp,
            "away_win_prob": 1.0 - hp,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/board.py`
Expected: `board self-test: all invariants hold`

- [ ] **Step 5: Merge it in the daily job, without displacing MLB**

In `scripts/run_daily.py`, after the results-store loop from Task 4 and before `board.json` is written:

```python
    # MLB already carries a richer number from the slate — Elo plus the
    # starting pitcher — so it is rated above and deliberately skipped here.
    # Everything else gets plain Elo once its store is deep enough.
    if board_mod and results_store and leagues:
        for short, rows in boards.items():
            if short == "mlb" or not rows:
                continue
            # Guarded like every other module call in this file. A league
            # going unrated is a worse board; an exception here is no card
            # at all, because nothing below this catches it.
            try:
                history = results_store.load(short)
                rated = board_mod.elo_model(rows, history, short)
                if rated:
                    n = board_mod.merge_model(rows, rated, "elo")
                    print(f"-- ratings: {n} {short} game(s) rated from "
                          f"{len(history)} stored result(s)")
            except Exception as e:                           # noqa: BLE001
                print(f"!! rating {short} failed "
                      f"({type(e).__name__}: {e})", file=sys.stderr)
```

- [ ] **Step 6: Confirm nothing regressed and MLB kept its own number**

Run:

```bash
CRAFTYPICKS_MOCK=1 python3 scripts/run_daily.py 2>&1 | grep -Ei "board|ratings|results"
python3 -c "
import json; d=json.load(open('data/board.json'))
for short, lg in d['leagues'].items():
    src = {}
    for g in lg['games']:
        s = (g.get('model') or {}).get('source', 'none')
        src[s] = src.get(s, 0) + 1
    print(f'{short}: {src}')
"
```

Expected: MLB's games show `{'slate': N}` — the starter-adjusted number, not overwritten by plain Elo. Any other in-season league shows either `{'elo': N}` or `{'none': N}` depending on whether its store has reached a hundred games yet. Neither outcome is an error today.

- [ ] **Step 7: Commit**

**Do not stage `data/board.json`.** Step 6 runs the daily job in mock mode, which overwrites it with synthetic games — six fake MLB fixtures and three fake NFL ones, none rated. Committing that publishes invented games. Restore the real file first:

```bash
git checkout -- data/board.json
git add scripts/board.py scripts/run_daily.py
git commit -m "feat: rate any league whose stored results run deep enough"
```

The same applies to any other `data/*.json` the mock run rewrote. Check `git status` before committing and restore anything you did not mean to change.

---

## What this plan deliberately does not do

- **No backfill.** The results store grows one day per run. Fetching a whole season in one morning would mean about 170 requests to an endpoint nobody promised us, and the cold start is worth less than the reliability. NBA and college basketball do not start until late October; the store will be deep by then.
- **No total, ever, from Elo.** Elo produces a win probability, not a run distribution. The totals row stays "market only" until a scoring model exists and has been validated on its own.
- **No change to how MLB is rated.** `rate_mlb.py` and `slate.py` keep producing the starter-adjusted number; this plan reads it rather than replacing it. Consolidating the two Elo implementations is worth doing, but not while one of them is the only rating on the site.
- **No accuracy page.** How good these numbers turn out to be — calibration, Brier against the market, closing-line movement — is the accuracy plan. Publishing a number and publishing its track record are separate jobs, and doing the second badly is worse than waiting.
- **No hourly refresh.** The board is still built once a day. Prices go stale between runs, and the card's timestamp is what tells a reader so.

## Plans that follow

| Plan | Depends on | Ships |
|---|---|---|
| Hourly refresh and live scores | this | Prices current to the hour, live scores, the book picker |
| Props | the board | Props list and detail, NFL/NBA pulls |
| Accuracy | this | Calibration, Brier vs the market, closing-line movement, `/accuracy` |
| Historical backtest | accuracy | Launch-day sample, labelled as a backtest |
