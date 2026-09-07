# Design Canvas Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the site look like the Claude Design canvas — its palette, type, page furniture, slate cards and expanded game details — applied to both the game boards and the player prop boards.

**Architecture:** The design is React with inline styles. The site is static HTML built by Python with one inlined stylesheet and zero runtime dependencies, and that does not change. What is ported is the *design*: tokens, type scale, and component shapes rewritten as classes in `_src/base.css`, with `_src/render.py` emitting the new structure. The existing `.gcard` already has the same bones as the design's slate card — team row, big probability, bar with a market tick, footer — so most of this is restyling plus one new disclosure panel.

**Tech Stack:** Python 3.11 stdlib, hand-written CSS, self-hosted woff2. No React, no build step, no CDN.

## Global Constraints

- Fonts are **self-hosted** from `craftypicks/fonts/`, not fetched from Google. A board that is the whole product should not have a third party in its critical render path, and the six subset files total 96 KB.
- `scripts/palette.py` is the gate. Every colour below was re-checked against its floors: `txt >= 12`, `sub >= 9`, `muted >= 5.5`, `green/red/amber >= 5`, `dim` in [3.0, 5.0]. A swap that breaks a floor fails the build.
- The design's 3D "five plates" section needs Three.js and is **out of scope** — it is a marketing object, not a board, and it would put a runtime dependency into a site that has none.
- The design's hero copy makes claims the data does not support ("2,417 scored games"). Copy is not ported; only form is.
- Both languages must render. Spanish needs latin-ext, so that subset ships.

---

### Task 1: tokens and type

**Files:**
- Create: `craftypicks/fonts/*.woff2` (6 files)
- Modify: `craftypicks/_src/base.css:1-40` (`:root`)
- Modify: `craftypicks/scripts/palette.py`

The design's palette, mapped onto the roles the stylesheet already has:

| token | Graphite | canvas | role |
|---|---|---|---|
| `--bg` | `#14171C` | `#08090B` | page |
| `--bg-2` | `#14171C` | `#0A0B0E` | banded sections |
| `--panel` | `#1C2027` | `#0E1014` | card |
| `--panel-2` | `#191D23` | `#0B0C10` | inset panel (pitcher block) |
| `--line` | `#2A3038` | `#1C2029` | card border |
| `--line-2` | `#3A424C` | `#3B434F` | hover border, top edge |
| `--txt` | `#E6EAF0` | `#F5F6F8` | names, numbers |
| `--sub` | `#BFC7D2` | `#C4CAD6` | detail rows |
| `--muted` | `#8E99A6` | `#8A909C` | mono labels |
| `--green` | `#3FD37A` | `#5BE39C` | our number |
| `--green-deep` | `#2A9C59` | `#226E49` | button shadow, bar gradient tail |

`--dim` has no counterpart in the design and keeps its Graphite value: the
canvas simply has no text that quiet, and inventing one below the floor to
match a design that does not use it would be backwards.

- [ ] **Step 1: Write the failing test**

```python
def test_the_canvas_palette_clears_every_floor():
    for token, floor in FLOORS.items():
        assert contrast(VALUES[token], VALUES["--bg"]) >= floor, token
```

- [ ] **Step 2: Run it and watch it fail** — `python3 scripts/palette.py`
- [ ] **Step 3: Write the tokens and the six `@font-face` rules**
- [ ] **Step 4: Run it and watch it pass**
- [ ] **Step 5: Commit**

---

### Task 2: page furniture

**Files:** `craftypicks/_src/base.css`, `craftypicks/_src/render.py`

Three shapes carry the whole look and are reused everywhere:

- **the eyebrow** — Space Mono, 11px, `.16em` tracking, uppercase, `--green`
- **the headline** — Space Grotesk 700, `clamp(30px,3.6vw,42px)`, `-.035em`
- **the solid button** — green ground, dark ink, `6px 6px 0 var(--green-deep)`
  hard shadow, translating 2px into it on hover

Plus the stat row's layered `text-shadow` extrusion, which is the one purely
decorative flourish worth keeping because it is what makes the record read as
a headline rather than a footnote.

- [ ] Steps 1-5 as above.

---

### Task 3: the slate card

**Files:** `craftypicks/_src/base.css:214-300`, `craftypicks/_src/render.py:640-690`

The existing card already has every part the design's card has. What
changes is proportion and weight:

- the matchup becomes one 18px line, `AWAY @ HOME`, the `@` in `--muted`
- the probability grows to 25px and is always `--green` on the leading side
- the bar grows from 7px to 12px and gains the gradient
  `linear-gradient(90deg, rgba(green,.28), green)`, keeping the existing
  market tick
- the footer becomes `market {pct}` on the left and the edge, coloured, on
  the right
- the card lifts on hover: `translateZ(46px) rotateX(4deg)` inside a
  `perspective:1600px` grid

`prefers-reduced-motion` disables the lift and the bar animation. The
design ships neither guard; a board people read every morning needs both.

- [ ] Steps 1-5 as above.

---

### Task 4: the game detail panel

**Files:** `craftypicks/_src/render.py`, `craftypicks/_src/i18n.py`, `craftypicks/_src/base.css`

The design's expanded card carries five blocks, each under a green mono
label. All five already exist in `slate.json`:

| block | source |
|---|---|
| Records | `home_record`, `away_record` |
| Form & streaks | `home_form`, `away_form` |
| Head to head | `home_vs_opp` / `away_vs_opp` |
| Starting pitchers | `*_starter`, `*_starter_era`, `*_starter_wl`, `*_sp_innings` |
| Notes | the existing lean / disagreement line |

Reuses the `<details>` element and `board.js` already built for the prop
cards, so the outside-click and Escape behaviour comes for free.

- [ ] Steps 1-5 as above.

---

### Task 5: the same card for player props

**Files:** `craftypicks/_src/render.py` (`pitcher_cards`, `_matchup_panel`, the HR/hits/NFL card builders)

The user asked for this look "for games and player props". The prop card
gets the same frame, the same eyebrow-and-label vocabulary inside its
disclosure, and the same hover lift. The projection bar strip (`.pb-strip`)
keeps its own shape — it is a different chart, not a probability — but
adopts the palette.

- [ ] Steps 1-5 as above.

## Self-Review

- Coverage: the user asked for "the web and slate design and game details, for games and player props" — Tasks 1-2 are the web, 3 the slate, 4 the details, 5 the props.
- Out of scope and said so: the 3D model section, the hero's unsupported copy.
- Consistency: every colour is a token, so `palette.py` sees all of them; no hex literal enters `render.py`.
