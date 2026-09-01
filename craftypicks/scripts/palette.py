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
SRC = HERE.parent / "_src"

# Floors are measured against --bg, the darker of the two grounds and so the
# harder test. The spec's own table quotes the ratios against white cards,
# which are all higher; a token that clears the ground clears the card.
FLOORS = {
    "txt":   12.0,   # club names, primary numbers, best price
    "sub":    9.0,   # records, starter, ERA, supporting stats
    "muted":  5.5,   # market labels, card headers, units
    "green":  5.0,
    "red":    5.0,
    # --amber carries text (.gfoot .flagged, .pb-foot .flagged, .cverdict.out,
    # .mock-banner), so it needs a floor like any other type colour. 5.0 is set
    # so the token still clears it composited on its own .12 banner tint.
    "amber":  5.0,
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


def bare_hex_outside_root(css_text: str | None = None) -> list[tuple[int, str]]:
    """Every #rrggbb literal in a rule body, as (line number, literal).

    The :root block is where colours are allowed to be literal; everywhere else
    a rule should name a token. rgba_triples() already guards the tints, but it
    cannot see a bare hex — which is exactly where the dark theme's #04150C
    button text and #74E9AC hover survived the palette swap.

    Does not resolve which property the literal sets. A hex in a rule body is
    reported whether it paints text, a border or a gradient stop; each one is
    either a palette colour or a leftover.
    """
    text = css_text if css_text is not None else CSS.read_text(encoding="utf-8")
    root = re.search(r":root\s*\{(.*?)\}", text, re.S)
    root_span = root.span() if root else (-1, -1)
    offset = 0
    found = []
    for n, line in enumerate(text.splitlines(keepends=True), start=1):
        for m in re.finditer(r"#[0-9A-Fa-f]{6}", line):
            if not (root_span[0] <= offset + m.start() < root_span[1]):
                found.append((n, m.group(0)))
        offset += len(line)
    return found


# A literal in a body is a mark on the ground — text, a rule, a legend swatch.
# Below this ratio against that ground it is not reliably visible.
LITERAL_MIN = 3.0


def illegible_literals_in_bodies() -> list[tuple[str, int, str, float]]:
    """Hex colours hardcoded in the page bodies that vanish into the ground.

    Inline styles are invisible to a token change, so a literal here survives a
    theme conversion untouched. Both the English bodies and their Spanish twins
    are read: Spanish is switched off rather than deleted, and a colour bug
    planted in a file nobody builds is a colour bug that surfaces months later.

    Direction is not the test; distance is. An earlier version flagged only
    literals darker than the ground, reasoning that was written when the ground
    was near-black and the danger was a value that sank into it. On a light
    theme the dangerous leftover is a pale one — which is why that version could
    not see the #F5F6F8 legend swatch sitting at 1.05:1 on slate. Anything
    within LITERAL_MIN of the ground is flagged, lighter or darker.

    Does not judge which ground: --bg is the page, and a literal legible on it
    is legible on the white cards that sit on it.
    """
    ground = tokens()["bg"]
    found = []
    for path in sorted(SRC.glob("*.body*.html")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(),
                                 start=1):
            for lit in re.findall(r"#[0-9A-Fa-f]{6}", line):
                ratio = contrast(lit, ground)
                if ratio < LITERAL_MIN:
                    found.append((path.name, n, lit, ratio))
    return found


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


# --dim is 3.0:1 on the ground. It is valid only beneath a figure that already
# carries the meaning — a units caption under a number, a timestamp under a
# headline. Anything a reader has to read to understand the card belongs to
# --muted or above. Adding a selector here is a deliberate act; if you are
# doing it to make something quieter, you want --muted.
#
# Triaged from the twenty selectors that used var(--dim) before this check
# existed. Everything else moved to --muted: table headers, KPI/stat labels,
# the play meta line, the footer legal text and section eyebrows all carry
# meaning a reader needs, not a caption under something already said.
DIM_ALLOWED = {
    # Unit nouns trailing a figure that already carries the meaning: the "K"
    # after a pitcher's projected strikeout number, and the generic .unit used
    # for "risked" after a units total on the plays page.
    ".pb-num .unit",
    ".unit",
    # Decorative team-colour dot before a club name; --dim is only the
    # fallback background when a club has no colour of its own, never text.
    ".tdot",
}


def dim_inline_uses_in_sources() -> list[tuple[str, int]]:
    """Every source line that reaches for var(--dim) through an inline style.

    The allowlist only sees the stylesheet, so an inline style is a way around
    it — the same way the inline hero gradients survived the palette swap
    untouched. There is no legitimate use: a caption that genuinely warrants
    --dim warrants a class, which the allowlist can then judge.

    The page bodies are only half the site. render.py builds most of the text a
    reader actually meets — the game cards, the screen-rule table, the record
    tables — as HTML strings with inline styles baked in, and build.py does the
    same for the shell around them. A stylesheet check can never see those, so
    they are scanned here too; ten of them were carrying --dim on real content
    while the body-only version of this check reported nothing.

    Only flags a line where var(--dim) sits inside an HTML style="..."
    attribute — that is the only shape this check exists to catch. The same
    characters show up legitimately in a docstring, a comment, or a test
    assertion (this file's own module docstring above, and render.py's self
    -test, both name "var(--dim)" without ever setting it); a bare substring
    scan cannot tell those apart from the real thing and used to flag them
    too. Still a line-based scan — no HTML or Python parser — so a style
    attribute split across lines, or one using single quotes, would slip
    through; nothing here does either, and every inline style in these files
    is written as style="..." on one line.
    """
    found = []
    style_dim = re.compile(r'style="[^"]*var\(--dim\)')
    paths = sorted(SRC.glob("*.body*.html")) + [SRC / "render.py",
                                                SRC / "build.py"]
    for path in paths:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(),
                                 start=1):
            if style_dim.search(line):
                found.append((path.name, n))
    return found


def dim_selectors(css_text: str | None = None) -> set[str]:
    """Every selector in the stylesheet whose rule body uses var(--dim).

    Does not follow specificity or cascade — it reports what asks for the
    token, which is the question the allowlist answers. A selector that sets
    --dim and is then overridden still counts, because the next edit to that
    rule will make it real.
    """
    text = css_text if css_text is not None else CSS.read_text()
    # Comments are stripped first: without this, a comment sitting above a rule
    # is swallowed into the selector text and reported as if it were one.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = set()
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        selector, body = m.group(1), m.group(2)
        if "var(--dim)" in body:
            for part in selector.split(","):
                part = part.strip()
                if part and not part.startswith("@"):
                    out.add(part)
    return out


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

    # Every tint must be built from a colour the palette still defines.
    palette_rgb = {_rgb(v) for v in t.values()}
    stray = [(n, rgb) for n, rgb in rgba_triples()
             if rgb not in palette_rgb and rgb not in ALLOWED_EXTRA]
    assert not stray, (
        "these rgba() colours are not in the palette — they are most likely "
        "tints left over from the dark theme:\n"
        + "\n".join(f"  base.css:{n}  rgba{rgb}" for n, rgb in stray))

    # Positive assertion: rgba_triples() returning nothing would make the stray
    # check above pass vacuously, which is what a mis-parse of base.css looks
    # like. The stylesheet has tints; if it suddenly has none, the parse broke.
    assert rgba_triples(), \
        "rgba_triples() found no tints in base.css — the stylesheet parse broke"

    # Every bare hex outside :root must be a colour the palette defines.
    palette_hex = {v.upper() for v in t.values()}
    strays = [(n, lit) for n, lit in bare_hex_outside_root()
              if lit.upper() not in palette_hex]
    assert not strays, (
        "these hex literals sit in a rule body but are not palette colours — "
        "they are most likely dark-theme values the token swap never reached:\n"
        + "\n".join(f"  base.css:{n}  {lit}" for n, lit in strays)
        + "\n\nUse a token, or add the value to :root with a name.")

    illegible_lits = illegible_literals_in_bodies()
    assert not illegible_lits, (
        f"these page bodies hardcode a colour under {LITERAL_MIN}:1 against "
        f"the ground, so it is not reliably visible there:\n"
        + "\n".join(f"  {name}:{n}  {lit} ({ratio:.2f}:1)"
                     for name, n, lit, ratio in illegible_lits))

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

    inline = dim_inline_uses_in_sources()
    assert not inline, (
        "these sources reach for --dim through an inline style, which the "
        "allowlist cannot see:\n"
        + "\n".join(f"  {name}:{n}" for name, n in inline)
        + "\n\nGive it a class and add that to DIM_ALLOWED, or use --muted.")

    # Positive assertion: if the comment stripper or the rule regex mis-parses,
    # dim_selectors() comes back empty and the subset check below passes with
    # nothing examined. This also catches a stale allowlist entry naming a
    # selector that no longer exists in the stylesheet.
    selectors = dim_selectors()
    orphans = sorted(DIM_ALLOWED - selectors)
    assert not orphans, (
        "DIM_ALLOWED names selectors that no longer use var(--dim) in "
        "base.css — either the rule was removed, or the stylesheet parse "
        "broke:\n" + "\n".join(f"  {s}" for s in orphans))

    unexpected = sorted(selectors - DIM_ALLOWED)
    assert not unexpected, (
        "--dim is 3.0:1 and may only caption a figure that already carries "
        "the meaning. These selectors use it for something else:\n"
        + "\n".join(f"  {s}" for s in unexpected)
        + "\n\nUse --muted, or add the selector to DIM_ALLOWED with a reason.")

    print("palette self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
