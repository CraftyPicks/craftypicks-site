# The Props Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse MLB's six nav items into two — one board with a Games/Props toggle and chips for Ks, Hits and HR — while removing what nobody reads and fixing what nobody can close.

**Architecture:** Every row is rendered at build time; JavaScript only shows, hides and reorders what is already in the page. New readers (`gamelog.py`, `h2h.py`) supply history columns; `props_board.py` composes existing models rather than adding one.

**Tech Stack:** Python 3.11 standard library. No JS framework, no CDN, no runtime fetch.

## Global Constraints

- **No new paid data.** Nothing may call The Odds API. The daily credit spend must not change by one credit.
- **Python 3.11 standard library only**, in the build and the scripts.
- **No third-party JavaScript.** Everything inlined at build time, as the CSS already is.
- **The page must be correct with JavaScript off**: all rows visible, controls inert. More than asked for, never less, never blank.
- **Every projection is graded**, and **nothing is graded before its game has finished** — `projection.game_over` is the gate.
- Tests are `_self_test()` at the module bottom, run with `python3 scripts/<module>.py`. No pytest, no `tests/`.
- **A test may not stub the function it is testing.** `nfl_yards.schedule` called a function that did not exist and every test stubbed `schedule` itself; all four NFL boards would have shipped permanently empty. Stub the HTTP layer.
- Parsers pure, fetches thin. This sandbox reaches no host but the repo.
- `limit=100` on `statSplits`, `gameType=R` on `/schedule`, `playerPool=All` on the hitting leaderboard.
- `python3 _src/build.py` runs the registry invariants; `python3 scripts/palette.py` must pass. `--dim` is 3.0:1.
- Every user-facing string needs `en` and `es`.
- f-strings cannot reuse the outer quote character or contain a backslash.
- Archives contain source only — no built HTML, nothing under `.github/workflows`.

---

## Phasing, and why

This plan is four phases. **Each ships on its own**; none needs the next.
Phase A is an afternoon and improves the site today. Phase D should not be
started until Phase B has run for a week, because what NBA and NFL need will
be clearer once one league's board has been used in anger.

| Phase | What | Ships |
|---|---|---|
| **A** | Form tab out, disclosure closes on click | Immediately |
| **B** | The props board itself | The main build |
| **C** | Pick slip, record page, lineup-time run | After B is live |
| **D** | NFL, then NBA | After B has a week on it |

---

# Phase A — the two small things

## Task 1: Remove the Form tab

The page is four tabs of nav for a table nobody opens. The **data stays**:
`form_store` also feeds the streak, last-ten and head-to-head lines inside
every game card, which are read. Only the standalone page goes.

**Files:**
- Modify: `craftypicks/_src/build.py` (`_FORM_PAGES`, `VIEWS`, titles, the `{{FORM_TABLE}}` block)
- Modify: `craftypicks/_src/render.py` (delete `form_table`)
- Modify: `craftypicks/_src/i18n.py` (delete `nav_form` and the form page's copy keys)
- Delete: `craftypicks/_src/*form.body*.html`
- **Do not touch:** `craftypicks/scripts/form_store.py`, or `board.py`'s use of it

**Interfaces:**
- Consumes: nothing
- Produces: nothing. `VIEWS` shrinks by one entry per league.

- [ ] **Step 1: Confirm what depends on the form data before deleting anything**

```bash
cd craftypicks && grep -rn "form_store\|form_table\|FORM_TABLE" scripts/*.py _src/*.py
```

Expected: `board.py` imports `form_store` and calls `.table()` and `.series()`
— those stay. `build.py`'s `{{FORM_TABLE}}` token and `render.form_table` are
the only page-side users, and both go.

- [ ] **Step 2: Delete the pages**

In `_src/build.py` remove the `_FORM_PAGES` dict, its `**_FORM_PAGES,` entry
in `PAGES`, the `f"{short}/form.html"` entry in the titles map, and the
`(f"{short}/form.html", "nav_form")` pair from the `VIEWS` comprehension.
Remove the block that sets `page_tokens["{{FORM_TABLE}}"]`, and the
`import results_store, form_store` line that exists only to feed it.

In `_src/render.py` delete `form_table`. In `_src/i18n.py` delete `nav_form`
and any key used only by the form body files. Delete the form body files.

- [ ] **Step 3: Build and confirm the pages are gone and the cards are not**

```bash
cd craftypicks && python3 _src/build.py && python3 scripts/palette.py \
  && ls */form.html 2>/dev/null; echo "form pages: $? (2 = gone)" \
  && grep -c "last ten\|Last ten\|streak" mlb/index.html
```

Expected: the build passes its invariants, no `form.html` exists, and the
game cards still carry their streak and last-ten lines — a non-zero count.
If that count is zero, `form_store` was removed by mistake; put it back.

- [ ] **Step 4: Commit**

```bash
git add -A craftypicks/_src
git commit -m "feat: the form tab goes, the form data stays

Four tabs of nav for a table nobody opened. form_store still feeds the
streak, last-ten and head-to-head inside every game card, which are read;
only the standalone page is removed."
```

## Task 2: A disclosure you can close from where you are

Opening a game's detail scrolls the reader down a long panel, and the only
way to close it is to scroll all the way back to the toggle. Three ways out,
all of which land where the reader already is.

**Files:**
- Create: `craftypicks/_src/board.js`
- Modify: `craftypicks/_src/build.py` (inline it, as the CSS is)
- Modify: `craftypicks/_src/base.css` (the close control)
- Modify: `craftypicks/_src/i18n.py` (`close` label)

**Interfaces:**
- Consumes: nothing
- Produces: `_src/board.js`, inlined into every page. Phase B adds to it.

- [ ] **Step 1: Write the script**

Create `craftypicks/_src/board.js`:

```javascript
/* Everything here is progressive: the page is correct without it.
   <details> already opens and closes on its own summary; this only adds
   ways to close one that do not require scrolling back to where you
   started. */
(function () {
  "use strict";

  function openPanels() {
    return Array.prototype.slice.call(
      document.querySelectorAll("details[open]"));
  }

  /* A click outside an open panel closes it. Clicks inside must not, or
     selecting text in the panel would shut it. */
  document.addEventListener("click", function (e) {
    openPanels().forEach(function (d) {
      if (!d.contains(e.target)) { d.open = false; }
    });
  });

  /* Escape closes the innermost open panel, which is what every other
     disclosure on the web does. */
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") { return; }
    var open = openPanels();
    if (open.length) {
      var last = open[open.length - 1];
      last.open = false;
      var s = last.querySelector("summary");
      if (s) { s.focus(); }
    }
  });

  /* A close control at the FOOT of each panel, added on open. The panel is
     taller than the phone, so the control at the top is off-screen by the
     time the reader wants it -- which is the whole complaint. */
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (!d || d.tagName !== "DETAILS" || !d.open) { return; }
    if (d.querySelector(":scope > .d-close")) { return; }
    var b = document.createElement("button");
    b.type = "button";
    b.className = "d-close";
    b.textContent = d.getAttribute("data-close") || "Close";
    b.addEventListener("click", function (ev) {
      ev.stopPropagation();
      d.open = false;
      var s = d.querySelector("summary");
      if (s) { s.scrollIntoView({block: "nearest"}); s.focus(); }
    });
    d.appendChild(b);
  }, true);          /* capture: toggle does not bubble */
})();
```

`toggle` does not bubble, which is why the listener is registered in the
capture phase. A listener without `true` fires for nothing and the bug looks
like the button was never written.

- [ ] **Step 2: Style the control**

In `_src/base.css`, beside the other button rules:

```css
.d-close{display:block;width:100%;margin-top:14px;padding:10px;
  font-family:var(--mono);font-size:12px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--muted);background:var(--panel-2);
  border:1px solid var(--line);border-radius:8px;cursor:pointer}
.d-close:hover{color:var(--txt);border-color:var(--line-2)}
```

- [ ] **Step 3: Inline it, and label it in both languages**

In `_src/i18n.py`:

```python
    "close":        {"en": "Close", "es": "Cerrar"},
```

In `_src/build.py`, read `_src/board.js` beside where `CSS` is read, and
add `<script>{JS}</script>` immediately before `</body>` in the footer
template. Set `data-close` on each `<details>` in `render.py`'s
`_disclosure` to `i18n.t("close", lang)` so the button is translated.

- [ ] **Step 4: Verify all three routes out, and that the page survives without JS**

```bash
cd craftypicks && python3 _src/build.py && python3 - <<'CHECK'
import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        for js in (True, False):
            pg = await b.new_page(viewport={"width":390,"height":844},
                                  java_script_enabled=js)
            await pg.goto("file:///tmp/cps/craftypicks/mlb/index.html")
            d = await pg.query_selector("details")
            if not js:
                # Without scripting the panel must still open and close by
                # its own summary. That is the floor this must not break.
                await (await d.query_selector("summary")).click()
                assert await d.get_attribute("open") is not None
                print("no-JS: opens"); await pg.close(); continue
            await (await d.query_selector("summary")).click()
            assert await d.get_attribute("open") is not None
            await pg.mouse.click(5, 5)                  # outside
            assert await d.get_attribute("open") is None, "outside click failed"
            await (await d.query_selector("summary")).click()
            await pg.keyboard.press("Escape")
            assert await d.get_attribute("open") is None, "escape failed"
            await (await d.query_selector("summary")).click()
            await (await d.query_selector(".d-close")).click()
            assert await d.get_attribute("open") is None, "close button failed"
            print("JS: outside click, escape and the button all close it")
            await pg.close()
        await b.close()
asyncio.run(main())
CHECK
```

Expected: `JS: outside click, escape and the button all close it` and
`no-JS: opens`.

- [ ] **Step 5: Commit**

```bash
git add craftypicks/_src
git commit -m "feat: three ways to close a detail panel, all where you are

The panel is taller than a phone, so the only control was off-screen by
the time anyone wanted it. A click outside, Escape, or a button at the
foot of the panel. The toggle listener captures, because toggle does not
bubble and a listener without it fires for nothing."
```

---

# Phase B — the props board

## Task 3: `gamelog.py` — L5, L10 and the streak

**Files:** Create `craftypicks/scripts/gamelog.py`

**Interfaces:**
- Consumes: `mlb_api._get`
- Produces:
  - `parse_log(payload, stat: str) -> list[dict]` — `[{"date","value","game_id"}]`, newest first
  - `hit_rate(games: list[dict], n: int) -> float | None` — share of the last `n` with a non-zero value
  - `streak(games: list[dict]) -> int` — consecutive most-recent games with a non-zero value
  - `batter_log(batter_id: int, season: int, stat: str) -> list[dict]`

- [ ] **Step 1: Write the failing test**

Create `scripts/gamelog.py` containing only this:

```python
def _self_test() -> None:
    payload = {"stats": [{"splits": [
        {"date": "2026-09-01", "game": {"gamePk": 1}, "stat": {"hits": "2"}},
        {"date": "2026-09-02", "game": {"gamePk": 2}, "stat": {"hits": "0"}},
        {"date": "2026-09-03", "game": {"gamePk": 3}, "stat": {"hits": "1"}},
        {"date": "2026-09-04", "game": {"gamePk": 4}, "stat": {"hits": "1"}},
    ]}]}
    games = parse_log(payload, "hits")
    # Newest first, because every question asked of this list is about the
    # recent end and a caller that has to reverse it will one day forget.
    assert [g["date"] for g in games] == ["2026-09-04", "2026-09-03",
                                          "2026-09-02", "2026-09-01"], games
    assert games[0]["value"] == 2.0 or games[0]["value"] == 1.0

    # L5 over four games is four games, not a lie about five.
    assert hit_rate(games, 5) == 0.75, hit_rate(games, 5)
    assert hit_rate(games, 2) == 1.0
    assert hit_rate([], 5) is None, "no games is not a zero rate"

    # The streak counts from the most recent game and stops at the first 0.
    assert streak(games) == 2, streak(games)
    assert streak([{"date": "d", "value": 0.0, "game_id": 1}]) == 0
    assert streak([]) == 0

    # A blank stat is a game not played in, not a game with none.
    blank = parse_log({"stats": [{"splits": [
        {"date": "2026-09-01", "game": {"gamePk": 9}, "stat": {"hits": ""}}]}]},
        "hits")
    assert blank == [], blank

    print("gamelog self-test: the history holds")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd craftypicks && python3 scripts/gamelog.py
```

Expected: `NameError: name 'parse_log' is not defined`

- [ ] **Step 3: Write the implementation**

Insert above `_self_test`:

```python
"""A batter's recent games, for the columns that argue with the projection.

The board's own number is a season rate against a matchup. L5, L10 and the
current streak are what a reader uses to disagree with it, and they cost one
free request per player.

Sorted newest first, deliberately. Every question asked here -- last five,
last ten, current streak -- is about the recent end of the list, and a caller
who has to remember to reverse it will one day not.
"""
from __future__ import annotations

import mlb_api


def parse_log(payload, stat: str) -> list[dict]:
    """One entry per game, newest first, for a single counting stat.

    A blank value is a game the player did not appear in, and it is dropped
    rather than counted as a zero -- a pinch-hitter who never batted did not
    fail to get a hit, and counting it would drag every rate down.
    """
    out = []
    for block in (payload or {}).get("stats", []):
        for split in block.get("splits", []):
            raw = (split.get("stat") or {}).get(stat)
            if raw in (None, ""):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            out.append({
                "date": split.get("date") or "",
                "value": value,
                "game_id": (split.get("game") or {}).get("gamePk"),
            })
    out.sort(key=lambda g: g["date"], reverse=True)
    return out


def hit_rate(games: list[dict], n: int) -> float | None:
    """Share of the last n games with a non-zero value.

    Returns None rather than 0.0 for an empty list. A player with no games
    has no rate, and a zero would read as a player who never does it.

    Fewer than n games is reported over the games that exist. The page says
    how many, so a 100% over two is not mistaken for a 100% over ten.
    """
    window = games[:n]
    if not window:
        return None
    return sum(1 for g in window if g["value"] > 0) / len(window)


def streak(games: list[dict]) -> int:
    """Consecutive most-recent games with a non-zero value."""
    n = 0
    for g in games:
        if g["value"] <= 0:
            break
        n += 1
    return n


def batter_log(batter_id: int, season: int, stat: str) -> list[dict]:
    """One player's season game log. One free request."""
    return parse_log(mlb_api._get(
        f"/people/{batter_id}/stats", stats="gameLog",
        group="hitting", season=season), stat)
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/gamelog.py
```

Expected: `gamelog self-test: the history holds`

- [ ] **Step 5: Test the fetch without stubbing the fetch**

Add to `_self_test`, before the final print — stubbing only the HTTP layer,
never `batter_log` itself:

```python
    # The fetch, with only the transport stubbed. A test that stubs
    # batter_log proves batter_log was spelled correctly and nothing else;
    # that is exactly how four NFL boards nearly shipped permanently empty.
    real = mlb_api._get
    try:
        seen = {}
        def fake(path, **params):
            seen["path"], seen["params"] = path, params
            return payload
        mlb_api._get = fake
        got = batter_log(660271, 2026, "hits")
    finally:
        mlb_api._get = real
    assert seen["path"] == "/people/660271/stats", seen
    assert seen["params"]["stats"] == "gameLog", seen
    assert seen["params"]["group"] == "hitting", seen
    assert len(got) == 4, got
```

- [ ] **Step 6: Commit**

```bash
git add craftypicks/scripts/gamelog.py
git commit -m "feat: a batter's recent games

L5, L10 and the current streak -- the columns a reader uses to disagree
with the projection. A blank stat is a game he did not appear in, not a
game he failed in."
```

## Task 4: `h2h.py` — the history that was already fetched for

`mlb_api.vs_batter` already runs in production, but **only inside
`vs_roster`**, which sums it across a whole opposing roster for the strikeout
screens (`screen_source.py:167`). No caller has ever used an individual
pairing, which is exactly what an H2H column is. The reader is proven; the
use is new.

It returns plate appearances, strikeouts, hits and home runs in one payload,
so a single request serves the H2H column for all three props.

**This is cheaper than it looks on screen nights.** `mlb_api._cache` is keyed
on the request, and `vs_roster` has already fetched every batter on the
opposing roster for each rated starter. Where the board asks for a pairing
the screens already pulled, it costs nothing.

**Files:** Create `craftypicks/scripts/h2h.py`

**Interfaces:**
- Consumes: `mlb_api.vs_batter(pitcher_id, batter_id, season)`
- Produces: `record(pitcher_id, batter_id, season) -> dict | None` returning `{"pa","h","hr","k","hit_rate","hr_rate","k_rate"}`, and `MIN_PA`

- [ ] **Step 1: Write the failing test**

Create `scripts/h2h.py` with only:

```python
def _self_test() -> None:
    import mlb_api
    real = mlb_api.vs_batter
    try:
        mlb_api.vs_batter = lambda p, b, s: {
            "plateAppearances": 12, "hits": 5, "homeRuns": 2, "strikeOuts": 3}
        r = record(1, 2, 2026)
    finally:
        mlb_api.vs_batter = real
    assert r["pa"] == 12 and r["h"] == 5 and r["hr"] == 2 and r["k"] == 3
    assert abs(r["hit_rate"] - 5 / 12) < 1e-9, r

    # Under the floor the rates are withheld but the raw line is not. Three
    # for four is worth showing as three for four; it is not worth showing
    # as 75%, which is what a reader would compare against a season rate.
    try:
        mlb_api.vs_batter = lambda p, b, s: {
            "plateAppearances": 4, "hits": 3, "homeRuns": 0, "strikeOuts": 1}
        small = record(1, 2, 2026)
    finally:
        mlb_api.vs_batter = real
    assert small["pa"] == 4 and small["h"] == 3
    assert small["hit_rate"] is None, small

    # Never faced: None, not a zero line.
    try:
        mlb_api.vs_batter = lambda p, b, s: None
        assert record(1, 2, 2026) is None
    finally:
        mlb_api.vs_batter = real

    print("h2h self-test: the record holds")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd craftypicks && python3 scripts/h2h.py
```

Expected: `NameError: name 'record' is not defined`

- [ ] **Step 3: Write the implementation**

```python
"""What this batter has done against this pitcher.

vs_batter already runs in production, but only inside vs_roster, which sums
it across a whole roster for the strikeout screens. No caller has ever used a
single pairing -- which is what this column is. One payload carries plate
appearances, hits, home runs and strikeouts, so one request serves the
head-to-head column for all three props at once.

The sample is almost always tiny -- a dozen plate appearances is a good one.
That is why the rates are withheld below MIN_PA while the raw line is still
shown: three for four is worth reading as three for four, and is not worth
reading as 75%, which a reader would put beside a season rate built on six
hundred.
"""
from __future__ import annotations

import mlb_api

# Below this the rates are not reported. Chosen to be obviously small rather
# than tuned: no threshold makes a ten-plate-appearance sample meaningful,
# and the honest move is to show the count and let the reader weigh it.
MIN_PA = 10


def record(pitcher_id: int, batter_id: int, season: int) -> dict | None:
    """This pairing's line, or None if they have never met."""
    s = mlb_api.vs_batter(pitcher_id, batter_id, season)
    if not s:
        return None
    pa = int(s.get("plateAppearances") or 0)
    if pa <= 0:
        return None
    h = int(s.get("hits") or 0)
    hr = int(s.get("homeRuns") or 0)
    k = int(s.get("strikeOuts") or 0)
    enough = pa >= MIN_PA
    return {
        "pa": pa, "h": h, "hr": hr, "k": k,
        "hit_rate": (h / pa) if enough else None,
        "hr_rate": (hr / pa) if enough else None,
        "k_rate": (k / pa) if enough else None,
    }
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd craftypicks && python3 scripts/h2h.py
```

Expected: `h2h self-test: the record holds`

- [ ] **Step 5: Commit**

```bash
git add craftypicks/scripts/h2h.py
git commit -m "feat: the head-to-head column, from a reader that already existed

vs_batter already runs, but only inside vs_roster, which sums it over a
whole roster for the strikeout screens. The individual pairing -- which is
what an H2H column is -- has never been used.

One request serves hits, home runs and strikeouts at once, and on nights the
screens run the cache has already paid for most of them. Rates are withheld
below ten plate appearances; the raw line is not."
```

## Task 5: The strikeout projection, and what to do about it

**Read this before writing code.** The projection this task frees from the
posted line has been measured against it, on the site's own stored history:

```
140 graded starts with a posted line
  our MAE   1.849
  line MAE  1.671
  paired difference +0.177 K, t = 3.26, 95% CI [+0.071, +0.282]
  directional calls 52/117 = 44.4%
```

It is **significantly worse than the free number on any sportsbook**, and it
picks the right side of the line less often than a coin. The confidence
interval excluded zero only once the sample passed roughly a hundred; at 86
starts it did not. This is not noise.

Shipping it as a bare percentage would put a number in front of readers that
this site has measured to be worse than one they can see for free, with
nothing on the page to say so.

**The decision taken:** the Ks chip ships, and every strikeout card carries
its measured record beside the number. That is on-brand rather than a
compromise — this site's entire claim is that it grades what it publishes and
says so. A board that hides its worst model is the same board that published
"promised 60%, delivered 0%".

**Files:**
- Create: `craftypicks/scripts/k_projection.py`
- Modify: `craftypicks/scripts/pitchers.py` (its projection moves out; the paid line comparison stays)

**Interfaces:**
- Consumes: `mlb_api.probable_starters`, `team_k_per_game`, `team_k_splits`, `pitch_hands`, `pitcher_season`; `matchup.summarise`
- Produces:
  - `project(starter, opp_rate, league, season) -> float | None`
  - `build(date_str, season) -> list[dict]` — one row per probable starter, no posted line required
  - `RECORD: dict` — the measured comparison above, read from `data/pitcher_ratings.json` at build time, never hardcoded

- [ ] **Step 1: Extract, and prove the numbers did not move**

Move the projection arithmetic out of `pitchers.build` into
`k_projection.project`, and have `pitchers.build` call it. The paid path must
produce **byte-identical** rows afterwards.

Prove it before committing:

```bash
cd craftypicks && python3 - <<'CHECK'
import json, subprocess, sys
sys.path.insert(0, "scripts")
# The stored history is the fixture: every row carries the inputs its
# projection was made from, so the extracted function must reproduce them.
rows = json.load(open("data/pitcher_ratings.json"))["pitchers"]
import k_projection
bad = []
for r in rows[:60]:
    got = k_projection.project(
        {"pitcher_id": r["pitcher_id"], "opponent_id": r.get("opponent_id")},
        r.get("opp_k_per_game"), r.get("opp_teams_ranked"), 2026)
    if got is not None and abs(got - r["projection"]) > 0.001:
        bad.append((r["name"], r["projection"], got))
assert not bad, bad[:5]
print(f"projection unchanged on {len(rows[:60])} stored rows")
CHECK
```

If this fails, the extraction changed the model. Stop and reconcile; do not
adjust the tolerance.

- [ ] **Step 2: Add the free build path**

`build(date_str, season)` iterates `probable_starters` rather than posted
quotes. Everything it needs — the starters, their hands, the club strikeout
splits, each opponent's strikeouts per game — is already free, and
`pitchers.build` only ever looped over quotes.

- [ ] **Step 3: Read the record from the data, not from this document**

```python
def measured_record(path) -> dict:
    """How this projection has actually done against the posted line.

    Read from the stored history on every build rather than written down,
    because a number in a docstring is true on the day it is typed and
    quietly false afterwards. If the model improves, the page says so
    without anyone remembering to edit it.
    """
```

Return `{"n", "our_mae", "line_mae", "better": bool}` over rows that have
both an `actual` and a `line`; return `{"n": 0}` when there are none.

- [ ] **Step 4: Test both**

Self-test `project` on fixed inputs, and `measured_record` on a small
synthetic history where the answer is arithmetic. Assert `measured_record`
returns `{"n": 0}` for an empty store rather than dividing by zero.

- [ ] **Step 5: Commit**

```bash
git add craftypicks/scripts/k_projection.py craftypicks/scripts/pitchers.py
git commit -m "feat: the strikeout projection, free of the posted line

Everything it needed was already free; only the loop was over paid quotes.
Extraction verified against 60 stored rows -- the numbers are unchanged.

It also carries its own record, read from the history on every build. On
140 graded starts it is worse than the posted line by 0.177 K, t=3.26, and
calls the side right 44% of the time. That belongs on the page beside it,
not in a commit message."
```

## Task 6: `props_board.py` — compose, do not model

**Files:** Create `craftypicks/scripts/props_board.py`

**Interfaces:**
- Consumes: `hits.build`, `batters.build`, `k_projection.build`, `gamelog`, `h2h`, `matchup.verdict`, `projection.merge`
- Produces: `build(date_str, season) -> dict` shaped `{"date", "date_label", "props": {"hits": [...], "hr": [...], "ks": [...]}, "record": {...}}`, each row carrying `prop`, `player_id`, `name`, `team`, `vs`, `chance` or `projection`, `season_rate`, `l5`, `l10`, `streak`, `h2h`, `match`, `park`, `commence_time`, `game_id`

This module **composes and does not model**. That boundary is what stops it
becoming the place where a fourth prop's special cases accumulate.

- [ ] **Step 1: Write the failing test** — assert that `build` with every
model stubbed returns the three prop lists, that a player missing a game log
still appears with empty history columns rather than being dropped, and that
one failing per-player call does not remove the player.

- [ ] **Step 2: Run it, watch it fail, then implement.**

- [ ] **Step 3: Verify the request count**

```bash
cd craftypicks && python3 - <<'CHECK'
import sys; sys.path.insert(0, "scripts")
import mlb_api
calls = []
real = mlb_api.urllib.request.urlopen
mlb_api.urllib.request.urlopen = lambda req, timeout=None: calls.append(req.full_url)
# ... build with a stubbed transport, then:
print(f"{len(calls)} requests")
assert not any("api.the-odds-api" in u for u in calls), "paid request added"
CHECK
```

Expected: **zero** Odds API requests, and roughly 110 more free calls than
today at worst -- one game log and one H2H per rated player. On nights the
strikeout screens run it is fewer, because `vs_roster` has already pulled
those pairings into `mlb_api._cache`. Assert the zero; report the count.

- [ ] **Step 4: Commit**

## Task 7: The page

**Files:** `_src/build.py`, `_src/render.py`, `_src/i18n.py`, `_src/board.js`, `_src/mlb.body.html`

- [ ] **Step 1: The toggle and the chips**, rendered as real links with
`data-` attributes. Every row is in the DOM; the script sets a class.

- [ ] **Step 2: Sorting.** Chips narrow, sorting ranks — and on a hundred
rows the sort is what makes the board usable. Sort by chance, by season rate,
and by L10. Implemented by reordering existing nodes, never by re-fetching.

- [ ] **Step 3: The strikeout record**, rendered from `measured_record` on
every Ks card. If the model is behind the market, the card says so.

- [ ] **Step 4: The four redirects.** `hits.html`, `batters.html`,
`homers.html` and `pitchers.html` become one-line meta-refresh pages into the
right filtered view, so nothing anyone bookmarked breaks.

- [ ] **Step 5: Verify with JavaScript disabled.** All rows visible, chips
inert, nothing blank. This is the floor.

- [ ] **Step 6: `palette.py` passes, invariants pass, commit.**

---

# Phase C — after B is live

Not planned in detail here, deliberately: what each of these should look like
depends on how the board actually reads once it exists, and planning them now
would be inventing requirements.

**The pick slip.** Asked for months ago — "save their picks so they don't
forget while they are scrolling". On four pages it was optional; on one board
with a hundred rows it is not. `localStorage`, no account, no server.

**The record as a page.** Calibration currently sits at the foot of each
board where nobody scrolls. If grading everything is the differentiator, it
is a tab, not a footnote — and it is where the strikeout comparison belongs
in full.

**A run when lineups post.** The largest free accuracy gain available. The
boards build in the morning with no lineup card, so a rested player still
shows at 73%. MLB posts lineups two to three hours before first pitch; a run
then drops scratched players from every MLB board. Costs nothing.

# Phase D — the other leagues

**NFL** after Phase B has run a week: the four boards exist, so it is nav and
rendering rather than new models.

**NBA is deliberately last.** The season is seven weeks out. Building it now
means seven weeks of empty pages and no way to test any of it until there are
box scores. Build the structure so a league drops in as a config entry; write
the models when there is something to grade them against.
