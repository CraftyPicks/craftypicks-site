# Light Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the site from its dark palette to the slate light theme, with automated checks that keep it legible.

**Architecture:** The palette lives in one place — the `:root` block of `_src/base.css` — and a new stdlib-only module, `scripts/palette.py`, reads it from there and asserts the contrast properties the spec requires. Nothing keeps a second copy of a colour. Three things beyond the tokens have to move with them: colour literals hardcoded in rules, inline gradients in the page bodies, and the team-colour legibility pass, which currently lifts club colours *toward white* because it was written for a dark panel.

**Tech Stack:** Python 3.12 standard library only; hand-written CSS; no build tooling, no preprocessor, no test runner.

## Global Constraints

- **Standard library only.** No pip installs. The site's whole hosting story depends on this.
- **No test runner exists.** Each module defines `_self_test()` and runs it under `if __name__ == "__main__":`. Tests are run with `python3 scripts/<module>.py`, which prints a confirmation line and exits non-zero on failure. Do not introduce pytest.
- **Never print a bare English sentence from `render.py` or `build.py`.** Every reader-facing string lives in `_src/i18n.py`. This plan adds no reader-facing copy, but the rule binds anything added later.
- **All text meets or exceeds 5:1 contrast**, with exactly one exception: `--dim`, which is UI-only and never carries body text.
- **Both clubs on a game card are equally legible.** Neither side's name or win probability may be dimmed to signal a pick.
- Working directory for all commands is the repository's `craftypicks/` directory.

---

### Task 1: The slate palette, and a test that reads it from the CSS

The palette is currently dark. Swapping the `:root` tokens is most of the visible change, and a contrast test written first is what stops the swap from being an act of faith.

The test deliberately reads `_src/base.css` rather than keeping its own copy of the colours. A palette test with hardcoded values passes happily while the site ships something else — that is the failure this design exists to prevent.

**Files:**
- Create: `scripts/palette.py`
- Modify: `_src/base.css` (the `:root` block only)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `tokens(css_text: str | None = None) -> dict[str, str]` — every `--name` in `:root` mapped to its hex value, names without the leading dashes
  - `contrast(hex_a: str, hex_b: str) -> float` — WCAG contrast ratio
  - `luminance(hex_color: str) -> float` — WCAG relative luminance
  - `CSS: pathlib.Path` — the stylesheet the module reads
  - `_rgb(hex_color: str) -> tuple[int, int, int]` — private, but Tasks 2 and 4 use it

- [ ] **Step 1: Write the failing test**

Create `scripts/palette.py`:

```python
#!/usr/bin/env python3
"""Contrast checks for the site's palette, read from base.css itself.

The tokens live in exactly one place — the :root block of _src/base.css — and
this module reads them from there rather than keeping a second copy. A palette
test carrying its own hardcoded colours goes on passing while the site ships
something else entirely; that is the failure this design exists to prevent.

It deliberately does not check which element uses which token. Contrast is a
property of a colour pair; whether the right pair reaches the reader is a
separate question, enforced by the --dim allowlist check further down this file.
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
CSS = HERE.parent / "_src" / "base.css"

# Floors are measured against --bg, the darker of the two grounds and so the
# harder test. The spec's own table quotes the ratios against white cards,
# which are all higher; a token that clears the ground clears the card.
FLOORS = {
    "txt":   12.0,   # club names, primary numbers, best price
    "sub":    9.0,   # records, starter, ERA, supporting stats
    "muted":  5.5,   # market labels, card headers, units
    "green":  5.0,
    "red":    5.0,
}

# --dim is the one token allowed below the 5:1 body-text floor, because it is
# only ever valid for a caption beneath a figure that already carries the
# meaning. It still has to clear 3:1 to be usable as UI.
DIM_MIN = 3.0
DIM_MAX = 5.0

REQUIRED = set(FLOORS) | {"dim", "bg", "bg-2", "panel", "panel-2",
                          "line", "line-2"}


def tokens(css_text: str | None = None) -> dict[str, str]:
    """Every custom property defined in the stylesheet's :root block.

    Does not resolve `var()` references or follow @media overrides — it reads
    the one literal block that defines the palette, which is the only place
    this project puts colour values.
    """
    text = css_text if css_text is not None else CSS.read_text()
    m = re.search(r":root\s*\{(.*?)\}", text, re.S)
    if not m:
        raise ValueError("no :root block in base.css")
    return {name: value.strip()
            for name, value in re.findall(r"--([\w-]+)\s*:\s*(#[0-9A-Fa-f]{6})",
                                          m.group(1))}


def _channel(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminance(hex_color: str) -> float:
    """WCAG relative luminance of a hex colour, 0.0 (black) to 1.0 (white).

    Does not account for the alpha channel; every colour this project pins in
    :root is fully opaque, and a translucent wash is checked as the pair it
    ends up producing, not as a token.
    """
    r, g, b = (_channel(v) for v in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(hex_a: str, hex_b: str) -> float:
    """WCAG contrast ratio between two hex colours, 1.0 to 21.0.

    Does not know which of the two is foreground; the ratio is symmetric, and
    the caller is responsible for pairing text with the ground behind it.
    """
    la, lb = luminance(hex_a), luminance(hex_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _self_test() -> None:
    t = tokens()

    missing = sorted(REQUIRED - set(t))
    assert not missing, f"palette is missing tokens: {missing}"

    # The theme is light. This is the assertion that fails on the dark palette
    # and passes on the slate one — every ratio below is satisfied by both, so
    # without it this test would approve either theme.
    assert luminance(t["bg"]) > 0.5, \
        f"--bg {t['bg']} is dark; this is meant to be the light theme"
    assert t["panel"].upper() == "#FFFFFF", \
        f"cards must be white, got --panel {t['panel']}"

    ground = t["bg"]
    for name, floor in FLOORS.items():
        ratio = contrast(t[name], ground)
        assert ratio >= floor, \
            f"--{name} {t[name]} is {ratio:.2f}:1 on --bg {ground}, needs {floor}"

    dim_ratio = contrast(t["dim"], ground)
    assert DIM_MIN <= dim_ratio < DIM_MAX, (
        f"--dim {t['dim']} is {dim_ratio:.2f}:1 on --bg; it must sit between "
        f"{DIM_MIN} and {DIM_MAX} — above that it should be --muted, below it "
        f"is unusable even as UI")

    # Cards sit on the ground and must be distinguishable from it without a
    # border doing all the work.
    assert contrast(t["panel"], t["bg"]) > 1.05, \
        "cards are indistinguishable from the ground behind them"

    print("palette self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/palette.py`

Expected: `AssertionError: --bg #08090B is dark; this is meant to be the light theme`

- [ ] **Step 3: Swap the palette**

In `_src/base.css`, replace the entire `:root{ ... }` block with:

```css
:root{
  /* Slate. Every value below was checked with scripts/palette.py rather than
     eyeballed; the ratios in the spec's table are reproduced exactly by that
     module, so a change here that breaks legibility fails the build. */
  --bg:#EEF1F4;
  --bg-2:#EEF1F4;
  --nav:#FFFFFF;
  --panel:#FFFFFF;
  --panel-2:#F7F9FB;
  --line:#D8DEE4;
  --line-2:#BFC7D0;

  /* The type hierarchy, in the order a reader meets it. --dim is the only
     token below 5:1 and is valid only for a caption under a figure that
     already carries the meaning — never for a name, a price or a percentage.
     See the --dim allowlist at the bottom of this file. */
  --txt:#14181D;      /* club names, primary numbers, best price        15.7:1 */
  --sub:#333A42;      /* records, starter, ERA, supporting stats        10.2:1 */
  --muted:#525B65;    /* market labels, card headers, units              6.1:1 */
  --dim:#828C97;      /* footnote captions only                          3.0:1 */

  --green:#106E42;
  --green-deep:#3D8D68;   /* the light end of the probability-bar gradient */
  --green-dim:#1F7F4B;
  --red:#BE2F2F;
  --amber:#96650B;

  /* Two roles: mono labels the data, the sans carries everything else. */
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:"Inter","Helvetica Neue",Helvetica,Arial,sans-serif;
  --maxw:1220px;
}
```

Three of these were not given by the spec and were chosen by measurement:

- `--amber` moved from `#F5C451` (1.63:1 on white — invisible) to `#96650B` (5.04:1), keeping it above the body-text floor since it labels flagged rows.
- `--green-deep` keeps its existing value `#3D8D68`. It is the *light* end of the bar gradient now rather than the dark end, and at 3.56:1 against the track it stays visible as a bar while remaining clearly distinct from `--green`.
- `--bg-2` is set equal to `--bg`. The dark theme used a second, slightly different ground to feed a hero glow that Task 3 removes.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/palette.py`
Expected: `palette self-test: all invariants hold`

- [ ] **Step 5: Confirm the site still builds**

Run: `python3 _src/build.py`
Expected: seven `built en/*.html` lines, no traceback. The pages will look wrong at this stage — rules still carry hardcoded dark literals, which Task 2 fixes. That is expected and is not a reason to stop.

- [ ] **Step 6: Commit**

```bash
git add scripts/palette.py _src/base.css
git commit -m "feat: slate light palette, enforced by a contrast test that reads base.css"
```

---

### Task 2: The colour literals hardcoded in rules

Twenty-one colour literals sit in `base.css` outside `:root`. Some are washes and glows built for a dark ground; the rest are tinted accents built from the *old* green, red and amber, which now point at colours the palette no longer contains. They do not move when the tokens move, so after Task 1 the page is a light theme wearing dark-theme jewellery.

The check added here is stricter than "no white washes": every `rgba()` triple in the file must match a colour the palette actually defines. That catches a stale accent tint, which is the failure mode that would otherwise survive review — a green glow whose rgb is the *old* green looks fine in isolation and wrong beside the new one.

**Files:**
- Modify: `scripts/palette.py` (add `rgba_triples`, `ALLOWED_EXTRA`, extend `_self_test`)
- Modify: `_src/base.css` (rules only; the `:root` block is already correct)

**Interfaces:**
- Consumes: `tokens()`, `contrast()` from Task 1
- Produces: `rgba_triples(css_text: str | None = None) -> list[tuple[int, tuple[int, int, int]]]` — every `rgba()` in the stylesheet as `(line_number, (r, g, b))`

- [ ] **Step 1: Write the failing test**

Add to `scripts/palette.py`, immediately above `_self_test`:

```python
# Pure black and pure white are allowed in an rgba() even though neither is a
# palette token: a shadow is black at low alpha and a highlight is white at low
# alpha, and naming those would not make them clearer.
ALLOWED_EXTRA = {(0, 0, 0), (255, 255, 255)}


def rgba_triples(css_text: str | None = None) -> list[tuple[int, tuple[int, int, int]]]:
    """Every rgba() colour in the stylesheet, as (line number, rgb).

    Does not look at the alpha channel. A tint's opacity is a design choice;
    what this exists to catch is a tint built on a colour the palette no longer
    contains, which is invisible in isolation and obvious beside its neighbour.
    """
    text = css_text if css_text is not None else CSS.read_text()
    found = []
    for n, line in enumerate(text.splitlines(), start=1):
        for m in re.finditer(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", line):
            found.append((n, tuple(int(g) for g in m.groups())))
    return found
```

Then add to `_self_test()`, just before the `print(...)` line:

```python
    # Every tint must be built from a colour the palette still defines.
    palette_rgb = {_rgb(v) for v in t.values()}
    stray = [(n, rgb) for n, rgb in rgba_triples()
             if rgb not in palette_rgb and rgb not in ALLOWED_EXTRA]
    assert not stray, (
        "these rgba() colours are not in the palette — they are most likely "
        "tints left over from the dark theme:\n"
        + "\n".join(f"  base.css:{n}  rgba{rgb}" for n, rgb in stray))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/palette.py`

Expected: an `AssertionError` listing stray tints, including `rgba(6, 10, 13)` at line 55, `rgba(91, 227, 156)` at lines 75, 99 and 125, `rgba(59, 224, 129)` at lines 181, 254, 255, 256, 269, 270 and 346, `rgba(245, 196, 81)` at lines 133, 183, 194 and 281, and `rgba(255, 92, 92)` at line 182.

- [ ] **Step 3: Rewrite the literals**

Make these edits in `_src/base.css`. Each replaces a dark-theme literal with one built from a current token.

The nav — stop hardcoding a value that duplicates `--nav`, which is what let the two drift apart in the first place:

```css
/* was: background:rgba(6,10,13,.86); */
background:rgba(255,255,255,.86);
```

The ghost button's hover wash, which lightened a dark surface and must now darken a light one — `20,24,29` is `--txt`:

```css
/* was: background:rgba(255,255,255,.03) */
background:rgba(20,24,29,.03)
```

The hero. Delete the radial glow line entirely and flatten the gradient; a green bloom on a near-white ground reads as a smudge:

```css
/* was two lines:
     radial-gradient(900px 420px at 76% 22%,rgba(91,227,156,.08),transparent 62%),
     linear-gradient(180deg,#0A0C0F 0%,var(--bg) 100%);          */
background:var(--bg-2);
```

The pulsing live dot, and the button glow on line 75 — both used `91,227,156`, a green that was never a token. Use `--green`'s `16,110,66`:

```css
box-shadow:0 0 0 3px rgba(16,110,66,.16);animation:pulse 2.4s infinite
```

The mock-data banner, from old amber to new — `150,101,11`:

```css
.mock-banner{background:rgba(150,101,11,.12);border-bottom:1px solid rgba(150,101,11,.35);
```

The three result tags. Old green `59,224,129` → `16,110,66`; old red `255,92,92` → `190,47,47`; old amber → `150,101,11`. Raise each alpha, because a tint calibrated against a dark panel disappears on white:

```css
.tag.win{border-color:rgba(16,110,66,.4);background:rgba(16,110,66,.10)}
.tag.loss{border-color:rgba(190,47,47,.35);background:rgba(190,47,47,.08)}
.tag.push{border-color:rgba(150,101,11,.35);background:rgba(150,101,11,.08)}
```

The two flag borders, at lines 194 and 281:

```css
.gcard.flag{border-color:rgba(150,101,11,.42)}
.pb-card.flag{border-color:rgba(150,101,11,.42)}
```

The calibration band and its marker, lines 254-256:

```css
.cband{background:rgba(16,110,66,.09);
  border-left:1px solid rgba(16,110,66,.18);border-right:1px solid rgba(16,110,66,.18)}
.csaid{box-shadow:0 0 6px rgba(16,110,66,.55)}
```

The key band, lines 269-270:

```css
.key-band{background:rgba(16,110,66,.09);
  border-left:1px solid rgba(16,110,66,.25);border-right:1px solid rgba(16,110,66,.25)}
```

Line 346's radial, same treatment as the hero:

```css
/* was: radial-gradient(700px 300px at 50% 0%,rgba(59,224,129,.10),transparent 65%),var(--bg-2); */
background:var(--bg-2);
```

The panel wash at line 488. A white wash on a white card does nothing; invert it so it still reads as depth:

```css
.gcard,.pb-card,.tile,.kpis,.calib{background-image:linear-gradient(180deg, rgba(20,24,29,.022), transparent 42%);}
```

The probability bar's tick, line 216. It marked the market's number with a white line and a white glow, both of which vanish on a white card. The tick is the one mark on the card a reader has to find, so it becomes the darkest token available and drops the glow:

```css
.gbar .tick{position:absolute;top:-5px;bottom:-5px;width:2px;background:var(--txt);opacity:.95}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/palette.py`
Expected: `palette self-test: all invariants hold`

- [ ] **Step 5: Confirm the stylesheet still parses as CSS**

There is no CSS parser in the standard library, so check the one thing a bad edit here actually breaks — brace balance:

Run: `python3 -c "s=open('_src/base.css').read(); print('braces balanced:', s.count('{')==s.count('}'), s.count('{'))"`
Expected: `braces balanced: True` followed by a count.

- [ ] **Step 6: Commit**

```bash
git add scripts/palette.py _src/base.css
git commit -m "fix: rebuild every tint and wash from the light palette"
```

---

### Task 3: The inline gradients in the page bodies

Six page bodies open with `<section style="background:linear-gradient(180deg,#0A0C0F,var(--bg))">`. That near-black top stop is inline, so no token change reaches it, and it survives every edit made so far.

Each of the six has a `.es.html` twin. Spanish is switched off (`i18n.LANGS = ("en",)`) so those files do not build today, but they are complete and re-enabling them is a one-line change. Leaving a dark gradient in them plants a bug that appears months from now, in a language whose pages nobody is looking at.

**Files:**
- Modify: `_src/about.body.html`, `_src/pitchers.body.html`, `_src/plays.body.html`, `_src/record.body.html`, `_src/screens.body.html`, `_src/slate.body.html` and each file's `.body.es.html` twin
- Modify: `scripts/palette.py` (add `dark_literals_in_bodies`, extend `_self_test`)

**Interfaces:**
- Consumes: `tokens()` from Task 1
- Produces: `dark_literals_in_bodies() -> list[tuple[str, int, str]]` — `(filename, line number, the literal)` for every hardcoded hex in a body file that is darker than the ground

- [ ] **Step 1: Write the failing test**

Add to `scripts/palette.py`, above `_self_test`:

```python
SRC = HERE.parent / "_src"


def dark_literals_in_bodies() -> list[tuple[str, int, str]]:
    """Hex colours hardcoded in the page bodies that are darker than the ground.

    Inline styles are invisible to a token change, so a dark value here
    survives a theme conversion untouched. Both the English bodies and their
    Spanish twins are read: Spanish is switched off rather than deleted, and a
    colour bug planted in a file nobody builds is a colour bug that surfaces
    months later.

    Does not flag light literals. A hardcoded near-white is wrong for other
    reasons — it should be a token — but it will not make text unreadable, and
    this check exists to catch the one that does.
    """
    ground = luminance(tokens()["bg"])
    found = []
    for path in sorted(SRC.glob("*.body*.html")):
        for n, line in enumerate(path.read_text().splitlines(), start=1):
            for lit in re.findall(r"#[0-9A-Fa-f]{6}", line):
                if luminance(lit) < ground:
                    found.append((path.name, n, lit))
    return found
```

Then add to `_self_test()`, just before the `print(...)` line:

```python
    dark = dark_literals_in_bodies()
    assert not dark, (
        "these page bodies hardcode a colour darker than the ground, so the "
        "palette change never reaches them:\n"
        + "\n".join(f"  {name}:{n}  {lit}" for name, n, lit in dark))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/palette.py`

Expected: an `AssertionError` listing `#0A0C0F` at line 1 of twelve files — `about.body.html`, `about.body.es.html`, `pitchers.body.html`, `pitchers.body.es.html`, `plays.body.html`, `plays.body.es.html`, `record.body.html`, `record.body.es.html`, `screens.body.html`, `screens.body.es.html`, `slate.body.html`, `slate.body.es.html`.

- [ ] **Step 3: Replace every inline hero gradient**

Run:

```bash
sed -i 's|background:linear-gradient(180deg,#0A0C0F,var(--bg))|background:var(--bg-2)|g' \
  _src/about.body.html _src/about.body.es.html \
  _src/pitchers.body.html _src/pitchers.body.es.html \
  _src/plays.body.html _src/plays.body.es.html \
  _src/record.body.html _src/record.body.es.html \
  _src/screens.body.html _src/screens.body.es.html \
  _src/slate.body.html _src/slate.body.es.html
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/palette.py`
Expected: `palette self-test: all invariants hold`

If it still lists `slate.body.html`, the remaining match is the legend swatch on line 16 — `linear-gradient(90deg,var(--green-deep),var(--green))`. That one is already built from tokens and contains no hex literal, so it will not be reported; a report means the sed missed a file, not that the swatch is wrong.

- [ ] **Step 5: Confirm the built pages carry no dark literal**

Run:

```bash
python3 _src/build.py && grep -c "0A0C0F" *.html || echo "no dark literals in the built pages"
```

Expected: seven `built en/*.html` lines, then `no dark literals in the built pages`.

- [ ] **Step 6: Commit**

```bash
git add scripts/palette.py _src/*.body*.html
git commit -m "fix: flatten the inline hero gradients onto the light ground"
```

---

### Task 4: Team colours, recomputed against white

`render.py` lifts each club's colour *toward white* until it clears 2.6:1 against `PANEL_RGB`, which is `#101317` — the old dark panel. On a white card that algorithm runs backwards: it makes a pale colour paler, and the clubs that most need help are the ones it hurts.

The fix is to make the adjustment aware of which way the ground lies, and to read the panel colour from the palette instead of hardcoding it a second time.

Measured against white, three of the thirty clubs need adjustment: the White Sox' silver (`#C4CED4`, 1.60:1), the Pirates' gold (`#FDB827`, 1.74:1) and the Rays' light blue (`#8FBCE6`, 2.00:1). Every other club's primary colour already clears 2.6:1 on white, and none fails after adjustment. Expect a small diff and three changed swatches, not thirty.

**Files:**
- Modify: `_src/render.py` — `PANEL_RGB`, `_legible`
- Modify: `scripts/palette.py` — add `team_color_report`, extend `_self_test`

**Interfaces:**
- Consumes: `tokens()`, `contrast()`, `_rgb()` from Task 1; `SRC` from Task 3; `render.TEAM_COLOR`, `render.team_color`, `render.MIN_CONTRAST`
- Produces: `team_color_report() -> list[tuple[str, str, str, float]]` — `(nickname, original hex, adjusted hex, final ratio against the card)` for every club

- [ ] **Step 1: Write the failing test**

Add to `scripts/palette.py`, above `_self_test`:

```python
def team_color_report() -> list[tuple[str, str, str, float]]:
    """Every club's colour before and after the legibility pass, with its ratio.

    Imports render rather than re-implementing the adjustment, so this measures
    what the site actually paints. Does not check that the colour resembles the
    club's real one — a team whose brand colour is unusable at this contrast is
    a design problem, not something a test can settle.
    """
    sys.path.insert(0, str(SRC))
    import render  # noqa: E402  — _src is not a package; this matches build.py

    card = tokens()["panel"]
    out = []
    for nickname, original in sorted(render.TEAM_COLOR.items()):
        adjusted = render.team_color(nickname)
        out.append((nickname, original, adjusted, contrast(adjusted, card)))
    return out
```

Then add to `_self_test()`, just before the `print(...)` line:

```python
    sys.path.insert(0, str(SRC))
    import render  # noqa: E402

    # The legibility pass must aim away from the card it sits on. Hardcoding
    # the old dark panel is what made it lighten colours on a white card.
    assert render.PANEL_RGB == _rgb(t["panel"]), (
        f"render.PANEL_RGB is {render.PANEL_RGB}, but cards are {t['panel']} "
        f"= {_rgb(t['panel'])}; the team-colour pass is aiming at the wrong "
        f"ground")

    illegible = [(nick, orig, adj, ratio)
                 for nick, orig, adj, ratio in team_color_report()
                 if ratio < render.MIN_CONTRAST - 1e-9]
    assert not illegible, (
        "these club colours do not reach MIN_CONTRAST against a white card:\n"
        + "\n".join(f"  {nick}: {orig} -> {adj} ({ratio:.2f}:1)"
                    for nick, orig, adj, ratio in illegible))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/palette.py`

Expected: `AssertionError: render.PANEL_RGB is (16, 19, 23), but cards are #FFFFFF = (255, 255, 255); the team-colour pass is aiming at the wrong ground`

- [ ] **Step 3: Make the legibility pass direction-aware**

In `_src/render.py`, replace the `PANEL_RGB` assignment and the whole `_legible` function with:

```python
# The ground a club's colour is judged against. Read from the palette rather
# than written out again here: two copies of one colour is how the bar tick
# ended up white on a white card.
def _panel_rgb() -> tuple[int, int, int]:
    css = (Path(__file__).resolve().parent / "base.css").read_text()
    m = re.search(r":root\s*\{.*?--panel\s*:\s*(#[0-9A-Fa-f]{6})", css, re.S)
    value = m.group(1) if m else "#FFFFFF"
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


PANEL_RGB = _panel_rgb()
MIN_CONTRAST = 2.6


def _legible(hex_color: str) -> str:
    """Move a club's colour away from the card until it is legible on it.

    Which way is "away" depends on the card. On a dark panel the colour is
    lifted toward white; on a white one it is pushed toward black. The earlier
    version only ever lifted, because it was written when the panel was
    #101317 — run against a white card it made the palest clubs paler still.

    Does not preserve hue exactly. Mixing toward black or white desaturates, so
    a club needing heavy mixing stops looking quite like itself; legibility
    wins. Against a white card only three clubs move at all.
    """
    rgb = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    target = (0, 0, 0) if _luminance(PANEL_RGB) > 0.5 else (255, 255, 255)
    for step in range(21):                       # up to 100% toward target
        mix = step / 20.0
        moved = tuple(round(c + (target[i] - c) * mix)
                      for i, c in enumerate(rgb))
        if _contrast(moved, PANEL_RGB) >= MIN_CONTRAST:
            return "#%02X%02X%02X" % moved
    return "#%02X%02X%02X" % target
```

Two details about this file, both verified rather than assumed:

- `render.py` imports `from pathlib import Path`, not `pathlib`, so `_panel_rgb` above uses `Path`. It does **not** import `re` — add `import re` beside `import html` at the top.
- There is no `_hex_rgb` helper; the existing `_legible` converts inline with `(1, 3, 5)` slicing, and the version above keeps that convention rather than introducing a second spelling. `_luminance(rgb)` and `_contrast(a, b)` already exist and take rgb tuples — do not change them.

The fallback on the last line changes too: the old version gave up and returned `#FFFFFF`, which on a white card is the worst possible answer. It now returns the target it was mixing toward, so a hopeless colour fails legibly rather than invisibly.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/palette.py`
Expected: `palette self-test: all invariants hold`

- [ ] **Step 5: Confirm only the two expected clubs moved**

Run:

```bash
python3 -c "
import sys; sys.path.insert(0,'scripts')
import palette
moved = [(n,o,a,r) for n,o,a,r in palette.team_color_report() if o.upper()!=a.upper()]
print(f'{len(palette.team_color_report())} clubs, {len(moved)} adjusted')
for n,o,a,r in moved: print(f'  {n}: {o} -> {a} ({r:.2f}:1)')
"
```

Expected: `30 clubs, 3 adjusted`, listing `white sox: #C4CED4 -> #939A9F`, `pirates: #FDB827 -> #CA931F` and `rays: #8FBCE6 -> #7AA0C4`, at 2.85, 2.73 and 2.74:1. If more than a handful moved, `PANEL_RGB` is probably still pointing at the dark panel.

- [ ] **Step 6: Confirm the site builds and commit**

Run: `python3 _src/build.py`
Expected: seven `built en/*.html` lines, no traceback.

```bash
git add _src/render.py scripts/palette.py
git commit -m "fix: judge club colours against the card they sit on, not a dark panel"
```

---

### Task 5: The type hierarchy, and a check that keeps it

The first light draft failed on legibility in a specific way the spec records: the losing club's name and win probability were rendered in a dimmer token than the winning one. A win probability is not chrome — it is half of what the card exists to say — and dimming one club makes one of the two teams harder to read on every single card.

Today `.gside .tm` is `--sub` and only `.gside.lead .tm` gets `--txt`; `.gside .pc` is `--sub` and only the leading one is green. The green percentage already signals which side the model favours. The name does not need to help.

**Files:**
- Modify: `_src/base.css` — `.gside .tm`, `.gside.lead .tm`, `.gside .pc`; add the `--dim` allowlist comment
- Modify: `scripts/palette.py` — add `dim_selectors`, `DIM_ALLOWED`, extend `_self_test`

**Interfaces:**
- Consumes: `tokens()` from Task 1
- Produces: `dim_selectors(css_text: str | None = None) -> set[str]` — every selector whose declarations use `var(--dim)`

- [ ] **Step 1: Write the failing test**

Add to `scripts/palette.py`, above `_self_test`:

```python
# --dim is 3.0:1 on the ground. It is valid only beneath a figure that already
# carries the meaning — a units caption under a number, a timestamp under a
# headline. Anything a reader has to read to understand the card belongs to
# --muted or above. Adding a selector here is a deliberate act; if you are
# doing it to make something quieter, you want --muted.
#
# Seeded with the one selector in the current stylesheet that is unambiguously
# the legitimate case: the unit suffix after a pitcher's projected strikeout
# number, where the number beside it already carries the meaning. Twenty
# selectors use var(--dim) today; the rest are triaged in Step 3.
DIM_ALLOWED = {
    ".pb-num .unit",
}


def dim_selectors(css_text: str | None = None) -> set[str]:
    """Every selector in the stylesheet whose rule body uses var(--dim).

    Does not follow specificity or cascade — it reports what asks for the
    token, which is the question the allowlist answers. A selector that sets
    --dim and is then overridden still counts, because the next edit to that
    rule will make it real.
    """
    text = css_text if css_text is not None else CSS.read_text()
    out = set()
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        selector, body = m.group(1), m.group(2)
        if "var(--dim)" in body:
            for part in selector.split(","):
                part = part.strip()
                if part and not part.startswith("@"):
                    out.add(part)
    return out
```

Then add to `_self_test()`, just before the `print(...)` line:

```python
    unexpected = sorted(dim_selectors() - DIM_ALLOWED)
    assert not unexpected, (
        "--dim is 3.0:1 and may only caption a figure that already carries "
        "the meaning. These selectors use it for something else:\n"
        + "\n".join(f"  {s}" for s in unexpected)
        + "\n\nUse --muted, or add the selector to DIM_ALLOWED with a reason.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/palette.py`

Expected: an `AssertionError` listing the selectors in `base.css` that use `var(--dim)` and are not the one allowed. Twenty selectors across nineteen rules use the token today, so expect a long list. The exact list depends on the stylesheet; read it, and for each entry decide whether it is genuinely a caption under a figure (add it to `DIM_ALLOWED` with a comment saying which figure) or is carrying meaning (change the rule to `var(--muted)` in Step 3).

- [ ] **Step 3: Fix the hierarchy**

First, both clubs equally legible. In `_src/base.css`, replace lines 203-206:

```css
/* Both clubs are named at full strength. An earlier draft dimmed the side we
   did not favour, which made one of the two teams harder to read on every
   card; the green percentage already says which side we are on. */
.gside .tm{font-size:15.5px;font-weight:700;letter-spacing:-.01em;color:var(--txt);line-height:1.25}
.gside .pc{font-family:var(--mono);font-size:18px;font-weight:700;color:var(--txt)}
.gside.lead .pc{color:var(--green)}
```

Note that `.gside.lead .tm` is deleted rather than changed — with both names at `--txt` it has nothing left to say.

Then resolve each selector the test listed. For any that is a caption beneath a figure, add it to `DIM_ALLOWED` with a comment naming the figure it captions. For every other one, change `var(--dim)` to `var(--muted)` in that rule.

Finally, add this comment immediately above the closing `}` of the `:root` block so a reader meets the rule where the token is defined:

```css
  /* --dim allowlist: see DIM_ALLOWED in scripts/palette.py. Adding a selector
     there is the only way to use this token, and the test will tell you so. */
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/palette.py`
Expected: `palette self-test: all invariants hold`

- [ ] **Step 5: Prove the check bites**

A test that cannot fail is worse than no test. Verify this one by breaking the rule it protects:

```bash
sed -i 's|^\.gside \.tm{\(.*\)color:var(--txt)|.gside .tm{\1color:var(--dim)|' _src/base.css
python3 scripts/palette.py; echo "exit=$?"
git checkout _src/base.css
python3 scripts/palette.py; echo "exit=$?"
```

Expected: the first run fails with `.gside .tm` in the unexpected list and `exit=1`; the second prints `palette self-test: all invariants hold` and `exit=0`.

- [ ] **Step 6: Build, then commit**

Run: `python3 _src/build.py`
Expected: seven `built en/*.html` lines, no traceback.

```bash
git add _src/base.css scripts/palette.py
git commit -m "fix: both clubs at full strength, and an allowlist that keeps --dim to captions"
```

---

## What this plan deliberately does not do

- **No navigation change.** The two-row sport-owns-everything nav, the league page tree, and the horizontal-scroll behaviour below 760px all belong to the board plan, where the nav is rebuilt anyway.
- **No horizontal-overflow check.** The spec requires a build check asserting zero horizontal overflow at 390px. Measuring layout needs a headless browser, which cannot be a dependency of a stdlib-only build; it belongs in a separate CI workflow, added alongside the nav rebuild that creates the risk. Note that workflow files cannot travel in the update archive — `applyupdate.yml` refuses them, because `GITHUB_TOKEN` may not write them — so that step will be a manual paste.
- **No card restructure.** The market block, the `<details>` disclosure, and the "market only" total are the board plan's work. This plan changes what colour the existing card is, not what it contains.
- **No page retirement.** `plays.html`, `record.html` and `screens.html` are still built. They are retired when `/accuracy` and `/how-it-works` exist to receive their machinery.
- **Spanish stays off.** The `.es.html` bodies are edited so they do not carry a dark gradient into a future re-enable, but `i18n.LANGS` is untouched.

## Plans that follow

| Plan | Depends on | Ships |
|---|---|---|
| Board, nav and league pages | this | The four-league board, two-row nav, `/mlb/` and friends |
| Hourly refresh and live scores | board | Prices current to the hour, scores live |
| Props | board | List view, detail panel, NFL/NBA pulls |
| Accuracy | refresh | Closing-line movement, calibration, intervals |
| Historical backtest | accuracy | Launch-day sample, labelled as backtest |
