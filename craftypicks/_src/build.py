#!/usr/bin/env python3
"""Assemble the Craftypicks static site.

Reads the board documents in data/ — board.json, slate.json, pitchers.json
and the per-league prop boards — renders the cards, tables and calibration
strips, and writes the static pages. Shared CSS is linked, not inlined, so it
is fetched once per session instead of once per page.

    python _src/build.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import namedtuple
from datetime import date, datetime
from pathlib import Path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
DATA = ROOT / "data"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "scripts"))

import config   # noqa: E402
import leagues      # noqa: E402
import render as R  # noqa: E402
import i18n         # noqa: E402

CSS = (SRC / "base.css").read_text(encoding="utf-8")
# Content hash, so a changed stylesheet is fetched and an unchanged one
# is not. Short on purpose: this is a cache key, not a checksum.
CSS_VERSION = hashlib.sha1(CSS.encode("utf-8")).hexdigest()[:8]
JS = (SRC / "board.js").read_text(encoding="utf-8")

# out    — path relative to the output root; the subdirectory is in here
# body   — stem of the _src/<stem>.body.html file this page renders
# key    — nav identity, used to mark the current page active
# league — the league short name for a league page, else None
Page = namedtuple("Page", "out body key league")

_LEAGUE_PAGES = {
    f"{short}/index.html": Page(f"{short}/index.html", "league", short, short)
    for short in leagues.ORDER
}

# The form PAGE is gone -- four tabs of nav for a table nobody opened. The
# form DATA stays: form_store still feeds the streak, last-ten and season
# series inside every game card, which are read. See board.py.

PAGES: dict[str, Page] = {
    "index.html":    Page("index.html",    "tonight",  "tonight",  None),
    **_LEAGUE_PAGES,
    "batters.html":  Page("batters.html",  "batters",  "batters",  "mlb"),
    "hits.html":     Page("hits.html",     "hits",     "hits",     "mlb"),
    "f7.html":       Page("f7.html",       "f7",       "f7",       "mlb"),
    "nba/points.html":    Page("nba/points.html",    "nba_points",    "nba_points",    "nba"),
    "nba/assists.html":   Page("nba/assists.html",   "nba_assists",   "nba_assists",   "nba"),
    "nba/rebounds.html":  Page("nba/rebounds.html",  "nba_rebounds",  "nba_rebounds",  "nba"),
    "nfl/passing.html":   Page("nfl/passing.html",   "nfl_passing",   "nfl_passing",   "nfl"),
    "nfl/rushing.html":   Page("nfl/rushing.html",   "nfl_rushing",   "nfl_rushing",   "nfl"),
    "nfl/receiving.html": Page("nfl/receiving.html", "nfl_receiving", "nfl_receiving", "nfl"),
    "nfl/td.html":        Page("nfl/td.html",        "nfl_td",        "nfl_td",        "nfl"),
    "about.html":    Page("about.html",    "about",    "about",    None),
    "pitchers.html": Page("pitchers.html", "pitchers", "pitchers", "mlb"),
    "slate.html":    Page("slate.html",    "slate",    "slate",    None),
}


def page_url(page: Page) -> str:
    """The href to reach this page from the output root.

    Does not produce a directory-style URL. Cloudflare Pages will serve
    /mlb/ for /mlb/index.html, but the committed pages are also opened
    straight off disk during development, where only the filename works.
    """
    return page.out


def rel_root(page: Page) -> str:
    """The prefix a page needs on every link to reach back to the root.

    Empty at the top level, "../" one directory down. Every href in the head
    and nav is built with this, which is what lets /mlb/index.html and
    /index.html share one template.

    Does not handle more than one level of nesting; nothing on this site is
    deeper, and a silent wrong answer would be worse than an obvious one.
    """
    return "../" * page.out.count("/")


# The extra views each league has beyond its board and its form table.
# Keyed rather than branched, because the branch version already grew a
# condition that read "has_props AND short == mlb" and would have grown
# another for every sport added.
_EXTRA_VIEWS: dict[str, list[tuple[str, str]]] = {
    "mlb": [("pitchers.html", "nav_pitchers"),
            ("f7.html", "nav_f7"),
            ("batters.html", "nav_batters"),
            ("hits.html", "nav_hits")],
    "nba": [("nba/points.html", "nav_nbapts"),
            ("nba/assists.html", "nav_nbaast"),
            ("nba/rebounds.html", "nav_nbareb")],
    "nfl": [("nfl/passing.html", "nav_pass"),
            ("nfl/rushing.html", "nav_rush"),
            ("nfl/receiving.html", "nav_recv"),
            ("nfl/td.html", "nav_nfltd")],
}

# The views each league actually has. A league is not listed with a props tab
# until its props page is built — four tabs that 404 look worse than one tab
# that works.
VIEWS: dict[str, list[tuple[str, str]]] = {
    short: ([(f"{short}/index.html", "nav_board")]
            + _EXTRA_VIEWS.get(short, []))
    for short in leagues.ORDER
}


def sport_row(page: Page, lang: str) -> str:
    """The first navigation row: Tonight, then one tab per league.

    Marks at most one tab active. A page belonging to no sport — How it works,
    the track record — leaves the whole row inactive rather than guessing.

    Does not hide a league that is out of season. A reader who clicks NFL in
    June should find an NFL page saying nothing is on, not a missing tab that
    makes them wonder whether the site still covers it.
    """
    up = rel_root(page)
    items = [("index.html", i18n.t("nav_tonight", lang), "tonight")]
    for short in leagues.ORDER:
        items.append((f"{short}/index.html", leagues.LEAGUES[short].label,
                      short))
    out = []
    for href, label, key in items:
        active = " on" if (page.key == key or page.league == key) else ""
        out.append(f'<a href="{up}{href}" class="{active.strip()}">{label}</a>')
    return "".join(out)


def view_row(page: Page, lang: str) -> str:
    """The second row: the views within the sport the reader is looking at.

    Returns an empty string for a page that belongs to no sport, so the row
    collapses rather than rendering an empty bar.

    Does not repeat the sport's name. The row above already says which sport
    this is, and saying it twice costs a line of vertical space that a phone
    cannot spare.
    """
    if not page.league:
        return ""
    up = rel_root(page)
    out = []
    for href, key in VIEWS[page.league]:
        active = " on" if href == page.out else ""
        out.append(f'<a href="{up}{href}" class="{active.strip()}">'
                   f'{i18n.t(key, lang)}</a>')
    return "".join(out)


def tonight_rows(doc: dict) -> list[dict]:
    """Every league's games merged into one list, earliest first.

    Does not group by league. Tonight's whole point is that a reader sees what
    is starting soonest regardless of sport; grouping would bury a 7pm NBA
    game under twelve baseball games starting later.
    """
    rows = []
    for entry in (doc.get("leagues") or {}).values():
        rows.extend(entry.get("games") or [])
    rows.sort(key=lambda r: (r.get("commence_time") or "",
                             r.get("home") or ""))
    return rows


def _board_day(iso: str, lang: str) -> str:
    """The board's date as a reader's phrase, or an empty string.

    Does not fall back to today. An empty eyebrow is a visible sign that
    board.json is missing or malformed; a date invented here would make a
    stale board look current, which is the one thing a pricing page must
    never do.
    """
    try:
        return i18n.day_and_date(date.fromisoformat(iso), lang)
    except (ValueError, TypeError):
        return ""

# Page titles per language. The English half is what the site shipped with.
TITLES = {
    "index.html": {"en": f"Tonight — {config.SITE_NAME}",
                   "es": f"Esta noche — {config.SITE_NAME}"},
    **{f"{short}/index.html": {
        "en": f"{leagues.LEAGUES[short].label} board — {config.SITE_NAME}",
        "es": f"Tablero {leagues.LEAGUES[short].label} — {config.SITE_NAME}"}
       for short in leagues.ORDER},
    "about.html": {"en": f"How It Works — {config.SITE_NAME}",
                   "es": f"Cómo funciona — {config.SITE_NAME}"},
    "batters.html": {"en": f"Home runs — {config.SITE_NAME}",
                     "es": f"Jonrones — {config.SITE_NAME}"},
    "hits.html": {"en": f"Hits — {config.SITE_NAME}",
                  "es": f"Hits — {config.SITE_NAME}"},
    "f7.html": {"en": f"First 7 innings — {config.SITE_NAME}",
                "es": f"Primeras 7 entradas — {config.SITE_NAME}"},
    "nba/points.html": {"en": f"Points — {config.SITE_NAME}",
                        "es": f"Puntos — {config.SITE_NAME}"},
    "nba/assists.html": {"en": f"Assists — {config.SITE_NAME}",
                         "es": f"Asistencias — {config.SITE_NAME}"},
    "nba/rebounds.html": {"en": f"Rebounds — {config.SITE_NAME}",
                          "es": f"Rebotes — {config.SITE_NAME}"},
    "nfl/passing.html": {"en": f"Passing yards — {config.SITE_NAME}",
                         "es": f"Yardas de pase — {config.SITE_NAME}"},
    "nfl/rushing.html": {"en": f"Rushing yards — {config.SITE_NAME}",
                         "es": f"Yardas de acarreo — {config.SITE_NAME}"},
    "nfl/receiving.html": {"en": f"Receiving yards — {config.SITE_NAME}",
                           "es": f"Yardas de recepción — {config.SITE_NAME}"},
    "nfl/td.html": {"en": f"Anytime touchdown — {config.SITE_NAME}",
                    "es": f"Touchdown en cualquier momento — {config.SITE_NAME}"},
    "slate.html": {"en": f"MLB Board — {config.SITE_NAME}",
                   "es": f"Pizarra MLB — {config.SITE_NAME}"},
    "pitchers.html": {"en": f"Pitchers Prop — {config.SITE_NAME}",
                      "es": f"Props de lanzadores — {config.SITE_NAME}"},
}
META_DESC = {
    "en": "{site} prices the NBA, NFL, MLB and college basketball board every "
          "day — our number beside the market's, with the reasoning and a public "
          "accuracy score. Nothing for sale.",
    "es": "{site} valora la pizarra de NBA, NFL, MLB y básquetbol universitario "
          "todos los días — nuestro número junto al del mercado, con el razonamiento "
          "y una precisión pública. Nada está a la venta.",
}

HEAD = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="Free daily pricing boards, with the accuracy score in public.">
<meta property="og:type" content="website">
<meta name="theme-color" content="#08090B">
{hreflang}
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' fill='%2308090B'/><path d='M8 20 L14 12 L18 17 L24 9' stroke='%233BE081' stroke-width='2.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>">
<link rel="stylesheet" href="{up}style.css?v={cssv}">
</head>
<body>
<header class="nav">
  <div class="nav-in">
    <a href="{up}index.html" class="logo">Craftypicks<em>.</em></a>
    <nav class="nav-links">{links}</nav>
    <div class="nav-cta">
      <a href="{about_href}" class="link-quiet">{why_free}</a>
    </div>
  </div>
</header>
<div class="nav-views{views_empty}"><div class="nav-in">{views}</div></div>
{banner}
"""

def mock_banner(lang: str) -> str:
    return f'<div class="mock-banner">{i18n.t("sample_data", lang)}</div>' 

def footer_html(lang: str, year: int, up: str = "",
                stamp: str = "") -> str:
    """The footer, per language. Links point inside the same language tree.

    Carries the build stamp because the status strip that used to show it was
    removed as clutter, and a reader looking at a day-old board would then
    have nothing at all to tell them so.
    """
    L = lambda k: i18n.t(k, lang)
    updated = (f'<p class="foot-stamp">{i18n.t("foot_stamp", lang, v=stamp)}</p>'
               if stamp else "")
    # The league boards are what the site is now, so the footer lists them
    # rather than a card that no longer exists.
    board_links = "\n        ".join(
        f'<a href="{up}{short}/index.html">{leagues.LEAGUES[short].label}</a>'
        for short in leagues.ORDER)
    return f"""
<footer>
  <div class="wrap">
    <div class="foot-grid">
      <div>
        <a href="{up}index.html" class="logo" style="display:inline-block;margin-bottom:14px">Craftypicks<em>.</em></a>
        <p style="font-size:14px;max-width:34ch">{L("foot_tagline")}</p>
      </div>
      <div>
        <h4>{L("foot_boards")}</h4>
        {board_links}
      </div>
      <div>
        <h4>{L("foot_trans")}</h4>
        <a href="{up}slate.html">{L("nav_slate")}</a>
        <a href="{up}about.html#method">{L("foot_method")}</a>
        <a href="{up}about.html#accuracy">{L("foot_accuracy")}</a>
      </div>
      <div>
        <h4>{L("foot_about")}</h4>
        <a href="{up}about.html">{L("nav_about")}</a>
        <a href="{up}about.html#faq">{L("foot_faq")}</a>
        <a href="{up}about.html#responsible">{L("foot_resp")}</a>
      </div>
    </div>
    <div class="foot-legal">
      <p class="disclaimer">{L("disclaimer")}</p>
      <p>{i18n.t("foot_copy", lang, year=year)}</p>
      {updated}
    </div>
  </div>
</footer>
<script>{JS}</script>
"""



# ------------------------------------------------------------------ data load
def load(name: str, default):
    path = DATA / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        print(f"!! {name} is not valid JSON; using empty data")
        return default


def doc_date_label(doc: dict, lang: str = "en") -> str:
    """The headline date for a data file, in the page's language.

    The scripts store both an ISO `date` and an English `date_label`. The ISO
    field is the one that can be re-formatted, so it wins; the stored label is
    only a fallback for older files written before `date` existed.
    """
    stamp = doc.get("date")
    if stamp:
        try:
            return i18n.long_date(datetime.fromisoformat(stamp), lang)
        except ValueError:
            pass
    return doc.get("date_label", "")


def esc_min(t) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;")


# ---------------------------------------------------------------------- build
def build() -> None:
    slate_doc = load("slate.json", {"date_label": "", "games": [], "summary": {}})
    pitch_doc = load("pitchers.json", {"date_label": "", "pitchers": [], "summary": {}})
    board_doc = load("board.json", {})
    batter_doc = load("batters.json",
                      {"date_label": "", "batters": [], "summary": {}})
    # Every win probability the non-MLB boards have published, with whatever
    # has been graded. Summarised per league so a board page can show its own
    # score rather than borrowing MLB's.
    rating_doc = load("board_ratings.json", {"ratings": []})
    rating_summaries = {}
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import board_ratings as _br                          # noqa: PLC0415
        for _lg in sorted({r.get("league") for r in rating_doc.get("ratings")
                           or [] if r.get("league")}):
            rating_summaries[_lg] = _br.summary(rating_doc["ratings"], _lg)
    except Exception as _br_err:                             # noqa: BLE001
        print(f"!! board ratings unavailable ({_br_err})", file=sys.stderr)

    hit_doc = load("hits.json",
                   {"date_label": "", "batters": [], "summary": {}})
    f7_doc = load("f7.json", {"date_label": "", "rows": [], "summary": {}})

    # The four NFL boards: three yardage categories and one touchdown board,
    # each a sibling of hits.json above with its own rows and its own error
    # summary / calibration.
    NFL_DOCS = {
        "nfl_passing": load("nfl_passing.json",
                            {"date_label": "", "rows": [], "summary": {}}),
        "nfl_rushing": load("nfl_rushing.json",
                            {"date_label": "", "rows": [], "summary": {}}),
        "nfl_receiving": load("nfl_receiving.json",
                              {"date_label": "", "rows": [], "summary": {}}),
        "nfl_td": load("nfl_td.json",
                       {"date_label": "", "rows": [], "summary": {}}),
    }

    # The three NBA boards, the same shape as the NFL four.
    NBA_DOCS = {
        f"nba_{stat}": load(f"nba_{stat}.json",
                            {"date_label": "", "rows": [], "summary": {}})
        for stat in ("points", "assists", "rebounds")
    }

    def build_tokens(lang, slate_doc, pitch_doc):
        """Every {{TOKEN}} a page body can contain, for one language."""
        L = lambda k, **kw: i18n.t(k, lang, **kw)
        pl = lambda n: i18n.plural(n, lang)

        return {
            "{{SLATE_DATE}}": doc_date_label(slate_doc, lang) or L("not_rated"),
            "{{SLATE_ROWS}}": R.slate_rows(slate_doc.get("games", [])),
            "{{PITCH_DATE}}": doc_date_label(pitch_doc, lang) or L("not_rated"),
            "{{PITCH_META}}": R.board_head_meta(
                doc_date_label(pitch_doc, lang) or L("not_rated"),
                pitch_doc.get("pitchers", [])),
            "{{PITCH_EDGES}}": R.pitcher_head(
                pitch_doc.get("pitchers", []))["edges"],
            "{{PITCHER_CARDS}}": R.pitcher_cards(pitch_doc.get("pitchers", [])),
            "{{PITCH_BUCKETS}}": R.pitcher_bucket_rows(pitch_doc.get("summary", {})),
            "{{PITCH_ACCURACY}}": R.pitcher_accuracy(pitch_doc.get("summary", {})),
            "{{CALIBRATION_ROWS}}": R.calibration_rows(
                (slate_doc.get("summary") or {}).get("calibration", [])),
            "{{BRIER_LINE}}": R.brier_line(slate_doc.get("summary") or {}),
            # Overridden per page by the body that owns it (hits, the four
            # NFL boards). Empty is the right default: nothing else has a date.
            "{{DATE_LABEL}}": "",
            # Overridden on every page that has one (tonight, each league).
            "{{BOARD_EYEBROW}}": "",
            "{{MIN_EDGE}}": f"{config.MIN_EDGE_PCT:.1f}%",
            "{{MIN_BOOKS}}": str(config.MIN_BOOKS),
            "{{MAX_PLAYS}}": str(config.MAX_PLAYS_PER_DAY),
            "{{POST_TIME}}": config.POST_TIME_LABEL,
            "{{TONIGHT_BOARD}}": R.board_cards(tonight_rows(board_doc)),
            "{{BAT_DATE}}": doc_date_label(batter_doc, lang) or L("not_rated"),
            "{{BATTER_CARDS}}": R.batter_cards(batter_doc.get("batters", [])),
            "{{BAT_CALIBRATION}}": R.batter_calibration(
                batter_doc.get("summary", {})),
            "{{F7_DATE}}": doc_date_label(f7_doc, lang) or L("not_rated"),
            "{{F7_COUNT}}": L("f7_count", n=len(f7_doc.get("rows", [])),
                              s=pl(len(f7_doc.get("rows", [])))),
            "{{F7_CARDS}}": R.f7_cards(f7_doc.get("rows", [])),
            "{{F7_ACCURACY}}": R.f7_accuracy(f7_doc.get("summary", {})),
            "{{HIT_CARDS}}": R.hit_cards(hit_doc.get("batters", [])),
            "{{HIT_CALIBRATION}}": R.hit_calibration(
                hit_doc.get("summary", {})),
            # One per board, because the two can disagree: a club can have
            # posted for the early game and not for the late one, and the
            # home-run board and the hits board cover different clubs.
            "{{BAT_LINEUP_NOTE}}": R.lineup_note(
                batter_doc.get("batters", [])),
            "{{HIT_LINEUP_NOTE}}": R.lineup_note(hit_doc.get("batters", [])),
            "{{HIT_COUNT}}": L("hit_count", n=len(hit_doc.get("batters", [])),
                              s=pl(len(hit_doc.get("batters", [])))),
            "{{LEAGUE_BOARD}}": "",
            "{{LEAGUE_NAME}}": "",
            "{{LEAGUE_CALIBRATION}}": "",
            "{{NBA_CARDS}}": "", "{{NBA_ACCURACY}}": "", "{{NBA_NOTE}}": "",
            "{{NBA_COUNT}}": "", "{{NBA_DATE}}": "",
        }




    year = datetime.utcnow().year

    # Any language tree we are no longer publishing is removed here rather
    # than left on disk. The built pages are committed, so a directory that
    # simply stops being written stays live forever otherwise.
    for stale in (l for l in i18n.ALL_LANGS if l not in i18n.LANGS and l != "en"):
        old_tree = ROOT / stale
        if old_tree.is_dir():
            for f in sorted(old_tree.glob("*.html")):
                f.unlink()
            try:
                old_tree.rmdir()
                print(f"removed stale {stale}/ tree")
            except OSError:
                print(f"!! {stale}/ still has files in it; left in place")

    written: set = set()

    # One stylesheet, linked, instead of the same 68 KB inlined into 44 pages.
    # 53% of the site's HTML was one file copied over and over, and inline CSS
    # cannot be cached -- a reader moving Board -> Pitchers -> Hits downloaded
    # it again every time. Linked, it is fetched once and the rest of the
    # session is a cache hit.
    #
    # url() inside a LINKED stylesheet resolves against the stylesheet, not
    # the document, so the {{UP}} prefix the inline version needed is now
    # simply empty: style.css and fonts/ are siblings at the site root, at
    # every page depth. The version query busts the cache when it changes.
    css_out = ROOT / "style.css"
    css_out.write_text(CSS.replace("{{UP}}", ""), encoding="utf-8")
    written.add(css_out.resolve())
    print(f"built style.css  ({len(CSS) // 1024} KB, v{CSS_VERSION})")

    for lang in i18n.LANGS:
        R.set_lang(lang)
        # The board's cards carry each game's strikeout props. render holds
        # them the same way it holds the language: set once, before drawing.
        R.set_props(pitch_doc.get("pitchers", []))
        out_dir = ROOT if lang == "en" else ROOT / lang
        out_dir.mkdir(parents=True, exist_ok=True)

        tokens = build_tokens(lang, slate_doc, pitch_doc)

        for out_name, page in PAGES.items():
            key = page.key
            title = TITLES[out_name][lang]
            up = rel_root(page)
            links = sport_row(page, lang)
            views = view_row(page, lang)
            hreflang = ""
            body_file = SRC / (page.body + (".body.html" if lang == "en"
                                            else f".body.{lang}.html"))
            if not body_file.exists():
                body_file = SRC / f"{page.body}.body.html"
                print(f"!! {out_name} has no {lang} copy; using English")
            body = body_file.read_text()
            page_tokens = dict(tokens)
            if page.key == "tonight":
                page_tokens["{{BOARD_EYEBROW}}"] = i18n.t(
                    "board_eyebrow", lang,
                    n=sum((board_doc.get("counts") or {}).values()),
                    d=_board_day(board_doc.get("date", ""), lang))
            if page.league:
                entry = (board_doc.get("leagues") or {}).get(page.league, {})
                page_tokens["{{LEAGUE_NAME}}"] = entry.get(
                    "label", leagues.LEAGUES[page.league].label)
                page_tokens["{{LEAGUE_BOARD}}"] = R.board_cards(
                    entry.get("games") or [])
                page_tokens["{{BOARD_EYEBROW}}"] = i18n.t(
                    "board_eyebrow", lang,
                    n=(board_doc.get("counts") or {}).get(page.league, 0),
                    d=_board_day(board_doc.get("date", ""), lang))
                # How this league's own number has scored. MLB's lives on the
                # slate page, which is its home; every other league had no
                # such page and, until now, nothing scoring it at all.
                scored = (rating_summaries.get(page.league) or {}
                          if page.league != "mlb" else {})
                page_tokens["{{LEAGUE_CALIBRATION}}"] = \
                    R.calibration_section(scored)
            if page.body == "hits":
                # {{DATE_LABEL}} has no site-wide value any more; each body
                # that shows a date supplies its own here.
                page_tokens["{{DATE_LABEL}}"] = (
                    doc_date_label(hit_doc, lang) or i18n.t("not_rated", lang))
            elif page.body in NBA_DOCS:
                nba_doc = NBA_DOCS[page.body]
                nba_rows = nba_doc.get("rows", [])
                page_tokens["{{NBA_CARDS}}"] = R.nba_cards(nba_rows)
                page_tokens["{{NBA_ACCURACY}}"] = R.nba_accuracy(
                    nba_doc.get("summary", {}))
                # Every row still entirely last season's rate, because this
                # one has not played the games yet. blend sets weight 0.0 for
                # exactly that case, and the page says so rather than letting
                # an October number look like a February one.
                cold = bool(nba_rows) and all(
                    (r.get("weight") or 0) == 0 for r in nba_rows)
                page_tokens["{{NBA_NOTE}}"] = (
                    f'<p class="ecap">{i18n.t("nba_cold", lang)}</p>'
                    if cold else "")
                page_tokens["{{NBA_COUNT}}"] = i18n.t(
                    "nba_count", lang, n=len(nba_rows),
                    s=i18n.plural(len(nba_rows), lang))
                page_tokens["{{NBA_DATE}}"] = (
                    doc_date_label(nba_doc, lang) or i18n.t("not_rated", lang))
            elif page.body in NFL_DOCS:
                # Four sibling pages sharing one set of token names. Each
                # page's own document supplies the values, the same way the
                # hits page above supplies its own DATE_LABEL.
                nfl_doc = NFL_DOCS[page.body]
                nfl_rows = nfl_doc.get("rows", [])
                if page.body == "nfl_td":
                    page_tokens["{{NFL_CARDS}}"] = R.td_cards(nfl_rows)
                    page_tokens["{{NFL_ACCURACY}}"] = R.td_calibration(
                        nfl_doc.get("summary", {}))
                else:
                    page_tokens["{{NFL_CARDS}}"] = R.yard_cards(nfl_rows)
                    page_tokens["{{NFL_ACCURACY}}"] = R.yard_accuracy(
                        nfl_doc.get("summary", {}))
                # Cold start: every row still entirely last season's rate,
                # because this season has not played the games yet to blend
                # in. nfl_data.blend sets weight 0.0 for exactly that case.
                cold = bool(nfl_rows) and all(
                    (r.get("weight") or 0) == 0 for r in nfl_rows)
                page_tokens["{{NFL_NOTE}}"] = (
                    i18n.t("nfl_lastyear", lang) if cold else "")
                page_tokens["{{NFL_COUNT}}"] = i18n.t(
                    "nfl_count", lang, n=len(nfl_rows),
                    s=i18n.plural(len(nfl_rows), lang))
                page_tokens["{{DATE_LABEL}}"] = (
                    doc_date_label(nfl_doc, lang) or i18n.t("not_rated", lang))
            for token, value in page_tokens.items():
                body = body.replace(token, str(value))

            head = HEAD.format(
                title=title, cssv=CSS_VERSION, links=links, site=config.SITE_NAME,
                lang=lang, desc=META_DESC[lang].format(site=config.SITE_NAME),
                hreflang=hreflang, up=up, views=views,
                views_empty=("" if views else " is-empty"),
                about_href=f"{up}about.html",
                why_free=i18n.t("nav_why", lang),
                banner=mock_banner(lang) if board_doc.get("mock") else "",
            )
            stamp = (board_doc.get("generated_at", "") or "")[:16].replace("T", " ")
            html_out = head + body + footer_html(lang, year, up, stamp)
            target = out_dir / out_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html_out, encoding="utf-8")
            written.add(target.resolve())
            print(f"built {lang}/{out_name}  ({len(html_out)//1024} KB)")

    _remove_orphans(written)


def _remove_orphans(written: set) -> None:
    """Delete built pages this run no longer produces.

    The same reasoning as the stale-language sweep above, applied one level
    down: the built pages are committed, so a page that simply stops being
    written stays live forever. Removing the Form tab left four of them --
    /mlb/form.html and its siblings -- reachable by URL, frozen in the old
    theme and the old navigation, and updated by nothing ever again.

    Deliberately narrow. It only considers .html at the output root and one
    directory below it, which is every page this build can emit and nothing
    deeper. _src is skipped: its .body.html files are templates, not output.
    """
    here = ROOT.resolve()
    candidates = list(here.glob("*.html")) + list(here.glob("*/*.html"))
    for f in sorted(candidates):
        if f.parent.name == "_src" or f.resolve() in written:
            continue
        f.unlink()
        print(f"removed orphan {f.relative_to(here)} "
              f"— no longer built")


def _self_test() -> None:
    # Every registry entry is a Page, and the key matches its output path.
    for out, page in PAGES.items():
        assert isinstance(page, Page), f"{out} is not a Page: {page!r}"
        assert page.out == out, f"{out} is filed under {page.out}"

    # Retired pages stay retired. HR allowed was taken off because it was not
    # used; a nav entry pointing at a page nothing builds is a 404 in the
    # middle of the MLB tab row, and a page built with no nav entry is one
    # nobody can reach -- so both halves are pinned.
    for gone in ("homers.html",):
        assert gone not in PAGES, f"{gone} is retired but still built"
        assert all(gone != out for views in _EXTRA_VIEWS.values()
                   for out, _key in views), f"{gone} is retired but in the nav"

    # Every league in the nav has a page, and every league page is a league.
    for short in leagues.ORDER:
        out = f"{short}/index.html"
        assert out in PAGES, f"{short} has no board page"
        assert PAGES[out].league == short

    # Depth. A page one level down has to reach back up for every link.
    assert rel_root(PAGES["index.html"]) == ""
    assert rel_root(PAGES["mlb/index.html"]) == "../"

    # And the links themselves resolve from either depth.
    assert page_url(PAGES["index.html"]) == "index.html"
    assert page_url(PAGES["mlb/index.html"]) == "mlb/index.html"

    # Every page has a title in every published language, or the <title>
    # renders as a Python KeyError at build time.
    for out in PAGES:
        for lang in i18n.LANGS:
            assert out in TITLES and lang in TITLES[out], \
                f"{out} has no {lang} title"

    # The sport row is the same everywhere and always marks exactly one item
    # active — or none, on a page that belongs to no sport.
    for out, page in PAGES.items():
        row = sport_row(page, "en")
        assert row.count('class="on"') <= 1, f"{out}: two active sport tabs"
        assert 'href="' in row, f"{out}: sport row has no links"

    assert sport_row(PAGES["mlb/index.html"], "en").count('class="on"') == 1
    assert sport_row(PAGES["about.html"], "en").count('class="on"') == 0

    # A league page shows its own views; MLB has props and NCAAB does not.
    mlb = view_row(PAGES["mlb/index.html"], "en")
    assert "pitchers.html" in mlb, "MLB's props page is missing from its views"
    assert mlb.count('class="on"') == 1, "the board tab should be active"

    # Every page a league lists as one of its views must claim that league.
    # view_row() opens with `if not page.league: return ""`, so a page that
    # forgets it renders no second row at all -- the reader lands on it and
    # every sibling tab vanishes. This shipped once, on pitchers.html.
    for _league, _views in VIEWS.items():
        for _href, _key in _views:
            _page = PAGES.get(_href)
            assert _page is not None, f"{_href} is in VIEWS but not PAGES"
            assert _page.league == _league, (
                f"{_href} is listed under {_league} but declares "
                f"league={_page.league!r}; its sub-nav will be empty")

    ncaab = view_row(PAGES["ncaab/index.html"], "en")
    assert "pitchers.html" not in ncaab, \
        "NCAAB has no props page and must not link to one"

    # A page outside the sports has no second row at all, rather than an
    # empty bar taking up space.
    assert view_row(PAGES["about.html"], "en") == ""

    # Every href in either row points at a page that exists. A link to a page
    # the build does not emit is a 404 nobody notices until a reader does.
    import re as _re
    known = set(PAGES) | {"pitchers.html"}
    for page in PAGES.values():
        for href in _re.findall(r'href="([^"]+)"',
                                sport_row(page, "en") + view_row(page, "en")):
            target = href.replace(rel_root(page), "", 1)
            assert target in known, f"{page.out} links to missing {target}"

    doc = {
        "generated_at": "2026-08-31T13:00:00", "date": "2026-08-31",
        "leagues": {
            "mlb": {"label": "MLB", "games": [
                {"event_id": "b", "league": "mlb", "home": "H1", "away": "A1",
                 "commence_time": "2026-08-31T23:05:00Z", "markets": {},
                 "model": None}]},
            "nfl": {"label": "NFL", "games": [
                {"event_id": "a", "league": "nfl", "home": "H2", "away": "A2",
                 "commence_time": "2026-08-31T17:00:00Z", "markets": {},
                 "model": None}]},
        },
        "counts": {"mlb": 1, "nfl": 1},
    }

    merged = tonight_rows(doc)
    assert [r["event_id"] for r in merged] == ["a", "b"], \
        "Tonight is in start-time order across leagues, not grouped by league"
    assert all("league" in r for r in merged)

    # A missing or unreadable board.json yields an empty board, never a crash.
    assert tonight_rows({}) == []
    assert tonight_rows({"leagues": {}}) == []

    print("build self-test: all invariants hold")


if __name__ == "__main__":
    # The invariants run before every build, not only under --test. They are
    # pure registry checks -- no disk, no network, microseconds -- and the
    # one thing they are for is catching a page that is wired up wrong. Gated
    # behind a flag no workflow passes, they caught nothing: the page whose
    # missing league emptied the whole MLB sub-nav shipped past them and was
    # found by a reader instead.
    _self_test()
    if "--test" not in sys.argv:
        build()

