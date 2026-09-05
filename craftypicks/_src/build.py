#!/usr/bin/env python3
"""Assemble the Craftypicks static site.

Reads data/plays.json, data/history.json and data/stats.json, renders the
play cards, tables, KPI strips and chart, and writes four self-contained HTML
files. Shared CSS is inlined so every page works on its own, on any host,
with no build step at serve time.

    python _src/build.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict, namedtuple
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

# out    — path relative to the output root; the subdirectory is in here
# body   — stem of the _src/<stem>.body.html file this page renders
# key    — nav identity, used to mark the current page active
# league — the league short name for a league page, else None
Page = namedtuple("Page", "out body key league")

_LEAGUE_PAGES = {
    f"{short}/index.html": Page(f"{short}/index.html", "league", short, short)
    for short in leagues.ORDER
}

# Every league gets a form table, because every league now stores its own
# finished games. It is the second view for the three that have no props.
_FORM_PAGES = {
    f"{short}/form.html": Page(f"{short}/form.html", "form", short, short)
    for short in leagues.ORDER
}

PAGES: dict[str, Page] = {
    "index.html":    Page("index.html",    "tonight",  "tonight",  None),
    **_LEAGUE_PAGES,
    **_FORM_PAGES,
    "homers.html":   Page("homers.html",   "homers",   "homers",   "mlb"),
    "batters.html":  Page("batters.html",  "batters",  "batters",  "mlb"),
    "hits.html":     Page("hits.html",     "hits",     "hits",     "mlb"),
    "nfl/passing.html":   Page("nfl/passing.html",   "nfl_passing",   "nfl_passing",   "nfl"),
    "nfl/rushing.html":   Page("nfl/rushing.html",   "nfl_rushing",   "nfl_rushing",   "nfl"),
    "nfl/receiving.html": Page("nfl/receiving.html", "nfl_receiving", "nfl_receiving", "nfl"),
    "nfl/td.html":        Page("nfl/td.html",        "nfl_td",        "nfl_td",        "nfl"),
    "record.html":   Page("record.html",   "record",   "record",   None),
    "about.html":    Page("about.html",    "about",    "about",    None),
    "ev.html":       Page("ev.html",       "ev",       "ev",       None),
    "plays.html":    Page("plays.html",    "plays",    "plays",    None),
    "screens.html":  Page("screens.html",  "screens",  "screens",  None),
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
            ("batters.html", "nav_batters"),
            ("hits.html", "nav_hits"),
            ("homers.html", "nav_homers")],
    "nfl": [("nfl/passing.html", "nav_pass"),
            ("nfl/rushing.html", "nav_rush"),
            ("nfl/receiving.html", "nav_recv"),
            ("nfl/td.html", "nav_nfltd")],
}

# The views each league actually has. A league is not listed with a props tab
# until its props page is built — four tabs that 404 look worse than one tab
# that works.
VIEWS: dict[str, list[tuple[str, str]]] = {
    short: ([(f"{short}/index.html", "nav_board"),
             (f"{short}/form.html", "nav_form")]
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
    "plays.html": {"en": f"System Plays — {config.SITE_NAME}",
                   "es": f"Jugadas del sistema — {config.SITE_NAME}"},
    "record.html": {"en": f"Track Record — {config.SITE_NAME}",
                    "es": f"Historial — {config.SITE_NAME}"},
    "about.html": {"en": f"How It Works — {config.SITE_NAME}",
                   "es": f"Cómo funciona — {config.SITE_NAME}"},
    "homers.html": {"en": f"Home runs allowed — {config.SITE_NAME}",
                    "es": f"Jonrones permitidos — {config.SITE_NAME}"},
    "batters.html": {"en": f"Home runs — {config.SITE_NAME}",
                     "es": f"Jonrones — {config.SITE_NAME}"},
    "hits.html": {"en": f"Hits — {config.SITE_NAME}",
                  "es": f"Hits — {config.SITE_NAME}"},
    "nfl/passing.html": {"en": f"Passing yards — {config.SITE_NAME}",
                         "es": f"Yardas de pase — {config.SITE_NAME}"},
    "nfl/rushing.html": {"en": f"Rushing yards — {config.SITE_NAME}",
                         "es": f"Yardas de acarreo — {config.SITE_NAME}"},
    "nfl/receiving.html": {"en": f"Receiving yards — {config.SITE_NAME}",
                           "es": f"Yardas de recepción — {config.SITE_NAME}"},
    "nfl/td.html": {"en": f"Anytime touchdown — {config.SITE_NAME}",
                    "es": f"Touchdown en cualquier momento — {config.SITE_NAME}"},
    **{f"{short}/form.html": {
        "en": f"{leagues.LEAGUES[short].label} form — {config.SITE_NAME}",
        "es": f"Forma {leagues.LEAGUES[short].label} — {config.SITE_NAME}"}
       for short in leagues.ORDER},
    "ev.html":    {"en": f"+EV — {config.SITE_NAME}",
                   "es": f"+EV — {config.SITE_NAME}"},
    "screens.html": {"en": f"The Strikeout Screens — {config.SITE_NAME}",
                     "es": f"Los filtros de ponches — {config.SITE_NAME}"},
    "slate.html": {"en": f"MLB Board — {config.SITE_NAME}",
                   "es": f"Pizarra MLB — {config.SITE_NAME}"},
    "pitchers.html": {"en": f"Pitchers Prop — {config.SITE_NAME}",
                      "es": f"Props de lanzadores — {config.SITE_NAME}"},
}
META_DESC = {
    "en": "{site} posts free NBA, NFL, MLB and college basketball plays every day — "
          "the number, the price, the reasoning, and a fully public track record. "
          "Nothing for sale.",
    "es": "{site} publica jugadas gratis de NBA, NFL, MLB y básquetbol universitario "
          "todos los días — el número, el precio, el razonamiento y un historial "
          "totalmente público. Nada está a la venta.",
}

HEAD = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="Free daily plays with receipts on every one.">
<meta property="og:type" content="website">
<meta name="theme-color" content="#08090B">
{hreflang}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' fill='%2308090B'/><path d='M8 20 L14 12 L18 17 L24 9' stroke='%233BE081' stroke-width='2.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>">
<style>
{css}
</style>
</head>
<body>
<header class="nav">
  <div class="nav-in">
    <a href="{up}index.html" class="logo">Craftypicks<em>.</em></a>
    <nav class="nav-links">{links}</nav>
    <div class="nav-cta">
      <a href="{ev_href}" class="link-quiet">+EV</a>
      <a href="{about_href}" class="link-quiet">{why_free}</a>
      <a href="{plays_href}" class="btn solid sm">{cta}</a>
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
    return f"""
<footer>
  <div class="wrap">
    <div class="foot-grid">
      <div>
        <a href="{up}index.html" class="logo" style="display:inline-block;margin-bottom:14px">Craftypicks<em>.</em></a>
        <p style="font-size:14px;max-width:34ch">{L("foot_tagline")}</p>
      </div>
      <div>
        <h4>{L("foot_plays")}</h4>
        <a href="{up}plays.html">{L("foot_today")}</a>
        <a href="{up}plays.html#results">{L("foot_yest")}</a>
        <a href="{up}record.html">{L("foot_log")}</a>
      </div>
      <div>
        <h4>{L("foot_trans")}</h4>
        <a href="{up}record.html">{L("nav_record")}</a>
        <a href="{up}about.html#method">{L("foot_method")}</a>
        <a href="{up}screens.html">{L("nav_screens")}</a>
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


def latest_graded_day(history: list[dict], before: str) -> tuple[str, list[dict]]:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for p in history:
        if p.get("result") and p.get("posted_date"):
            by_day[p["posted_date"]].append(p)
    days = sorted((d for d in by_day if d < before), reverse=True)
    if not days:
        return "", []
    return days[0], by_day[days[0]]


def pretty_day(stamp: str, lang: str = "en") -> str:
    """'Wednesday, August 26' / 'miércoles, 26 de agosto'.

    Built from i18n's own month and weekday tables rather than strftime,
    because the GitHub runner has no Spanish locale installed and would
    silently print English dates on the Spanish pages.
    """
    try:
        return i18n.day_and_date(datetime.fromisoformat(stamp), lang)
    except Exception:
        return stamp


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


def _caps_status(scfg, lang: str = "en") -> str:
    """Describe the universal caps as they actually are right now."""
    caps = scfg.HARD_CAPS
    L = lambda k, **kw: i18n.t(k, lang, **kw)
    if not [k for k, v in caps.items() if v is not None]:
        return L("caps_off")
    parts = []
    if caps.get("max_line") is not None:
        parts.append(L("cap_max_line", v=f"{caps['max_line']:g}"))
    if caps.get("banned_line") is not None:
        parts.append(L("cap_banned_line", v=f"{caps['banned_line']:g}"))
    if caps.get("worst_juice") is not None:
        parts.append(L("cap_worst_juice", v=f"{int(caps['worst_juice']):+d}"))
    return L("caps_active", v="; ".join(parts))


def _price_note(scfg, lang: str = "en") -> str:
    # The plus-money requirement was removed from every screen rather than
    # switched off. A screen's job is to say the matchup is good; whether the
    # price is good is a separate question, answered against the vig-free
    # number rather than against zero. Under the old rule a strong matchup
    # could be thrown out for being correctly priced, which is backwards.
    return i18n.t("price_note", lang)



def esc_min(t) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;")


def net_units(plays: list[dict]) -> float:
    return round(sum(p.get("profit", 0.0) for p in plays), 2)


# ---------------------------------------------------------------------- build
def build() -> None:
    plays_doc = load("plays.json", {"plays": [], "summary": {}, "date_label": "", "note": ""})
    stats = load("stats.json", {})
    history = load("history.json", {"plays": []})["plays"]
    slate_doc = load("slate.json", {"date_label": "", "games": [], "summary": {}})
    pitch_doc = load("pitchers.json", {"date_label": "", "pitchers": [], "summary": {}})
    board_doc = load("board.json", {})
    homer_doc = load("homers.json", {"date_label": "", "starters": []})
    batter_doc = load("batters.json",
                      {"date_label": "", "batters": [], "summary": {}})
    hit_doc = load("hits.json",
                   {"date_label": "", "batters": [], "summary": {}})

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

    def build_tokens(lang, plays_doc, stats, history, slate_doc,
                     pitch_doc, closing_doc=None):
        """Every {{TOKEN}} a page body can contain, for one language."""
        L = lambda k, **kw: i18n.t(k, lang, **kw)
        pl = lambda n: i18n.plural(n, lang)

        card = plays_doc.get("plays", [])
        today = plays_doc.get("date", datetime.utcnow().date().isoformat())
        y_date, y_plays = latest_graded_day(history, today)
        recent = (stats.get("recent") or [])

        summary = plays_doc.get("summary", {})
        by_league = summary.get("by_league", {})
        league_line = " &middot; ".join(f"{n} {lg}" for lg, n in by_league.items()) or "—"

        post_time = plays_doc.get("post_time", config.POST_TIME_LABEL)
        if card:
            count_line = L("count_line_card", n=len(card), s=pl(len(card)),
                           time=post_time)
        else:
            count_line = L("count_line_none")

        try:
            import screen_config as scfg
            screen_tokens = {
                "{{SCREEN_A_ROWS}}": R.screen_rule_rows(scfg.SCREEN_A),
                "{{SCREEN_B_ROWS}}": R.screen_rule_rows(scfg.SCREEN_B),
                "{{HARD_CAP_ROWS}}": R.screen_rule_rows(scfg.HARD_CAPS),
                "{{SCREEN_DAILY_CAP}}": str(getattr(scfg, "MAX_SCREEN_PLAYS_PER_DAY", 5)),
                "{{CAPS_STATUS}}": _caps_status(scfg, lang),
                "{{SCREEN_B_PRICE_NOTE}}": _price_note(scfg, lang),
            }
        except Exception as e:                                   # noqa: BLE001
            print(f"!! screen config unavailable ({e}); methodology page will be thin")
            blank = ('<tr><td colspan="3" style="text-align:center;padding:30px">'
                     f'{L("screen_missing")}</td></tr>')
            screen_tokens = {k: blank for k in
                             ("{{SCREEN_A_ROWS}}", "{{SCREEN_B_ROWS}}",
                              "{{HARD_CAP_ROWS}}")}
            screen_tokens["{{SCREEN_DAILY_CAP}}"] = "5"
            screen_tokens["{{CAPS_STATUS}}"] = ""
            screen_tokens["{{SCREEN_B_PRICE_NOTE}}"] = ""

        graded_n = stats.get("graded", 0)
        if graded_n:
            record_intro = L("record_intro", n=graded_n, p=stats.get("pending", 0))
            months_line = L("months_line", n=stats.get("losing_months", 0),
                            total=stats.get("total_months", 0))
            log_heading = L("log_heading", n=min(20, len(recent)))
        else:
            record_intro = L("record_intro_empty")
            months_line = L("months_line_empty")
            log_heading = L("log_heading_empty")

        return {
            **screen_tokens,
            "{{BREAKEVEN_ROWS}}": R.breakeven_rows(),
            "{{SLATE_DATE}}": doc_date_label(slate_doc, lang) or L("not_rated"),
            "{{SLATE_ROWS}}": R.slate_rows(slate_doc.get("games", [])),
            "{{PITCH_DATE}}": doc_date_label(pitch_doc, lang) or L("not_rated"),
            "{{PITCHER_CARDS}}": R.pitcher_cards(pitch_doc.get("pitchers", [])),
            "{{PITCH_BUCKETS}}": R.pitcher_bucket_rows(pitch_doc.get("summary", {})),
            "{{PITCH_ACCURACY}}": R.pitcher_accuracy(pitch_doc.get("summary", {})),
            "{{CALIBRATION_ROWS}}": R.calibration_rows(
                (slate_doc.get("summary") or {}).get("calibration", [])),
            "{{BRIER_LINE}}": R.brier_line(slate_doc.get("summary") or {}),
            "{{RECORD_INTRO}}": record_intro,
            "{{DRAWDOWN_LINE}}": (
                L("drawdown", v=R.u(stats.get("drawdown", 0.0))) if graded_n
                else L("drawdown_empty", v=R.pct(stats.get("clv_avg", 0.0)))
            ),
            "{{MONTHS_LINE}}": months_line,
            "{{LOG_HEADING}}": log_heading,
            "{{DATE_LABEL}}": doc_date_label(plays_doc, lang),
            "{{COUNT_LINE}}": count_line,
            "{{PLAY_COUNT}}": str(len(card)),
            "{{UNITS_RISKED}}": f"{summary.get('units_risked', 0):.1f}u",
            "{{LEAGUE_LINE}}": league_line,
            "{{FILTER_CHIPS}}": R.filter_chips(card),
            "{{FILTER_BLOCK}}": (f'<div class="filters" style="margin-top:36px">'
                                 f'{R.filter_chips(card)}</div>') if R.filter_chips(card) else "",
            "{{BOARD_EYEBROW}}": (
                L("eyebrow_posted", date=doc_date_label(plays_doc, lang), time=post_time)
                if card else L("eyebrow_scan", time=post_time)),
            "{{HERO_CARD}}": R.play_card(card[0], 1, len(card)) if card
                             else R.empty_card(plays_doc.get("note", "")),
            "{{PLAY_CARDS}}": R.play_cards(card, plays_doc.get("note", "")),
            "{{YESTERDAY_LABEL}}": (pretty_day(y_date, lang) if y_date
                                    else L("last_graded_card")),
            "{{YESTERDAY_ROWS}}": R.yesterday_rows(y_plays),
            "{{YESTERDAY_NET}}": R.u(net_units(y_plays)),
            "{{YESTERDAY_NET_CLASS}}": R.cls_for(net_units(y_plays)),
            "{{KPI_HOME}}": R.kpi_strip(stats, "home"),
            "{{KPI_RECORD}}": R.kpi_strip(stats, "record"),
            "{{EVIDENCE}}": R.evidence_block(stats),
            "{{RECENT_ROWS}}": R.result_rows(recent[:6], "compact"),
            "{{RECENT_NET}}": R.u(net_units(recent[:6])),
            "{{RECENT_NET_CLASS}}": R.cls_for(net_units(recent[:6])),
            "{{RECENT_COUNT}}": str(min(6, len(recent))),
            "{{LOG_ROWS}}": R.result_rows(recent[:20], "full"),
            "{{LOG_COUNT}}": str(min(20, len(recent))),
            "{{LEAGUE_ROWS}}": R.league_rows(stats.get("by_league", [])),
            "{{SOURCE_ROWS}}": R.source_rows(stats.get("by_source", [])),
            "{{MONTH_CHART}}": R.month_chart(stats.get("months", [])),
            "{{GRADED_COUNT}}": str(stats.get("graded", 0)),
            "{{PENDING_COUNT}}": str(stats.get("pending", 0)),
            "{{LOSING_MONTHS}}": str(stats.get("losing_months", 0)),
            "{{TOTAL_MONTHS}}": str(stats.get("total_months", 0)),
            "{{MIN_EDGE}}": f"{config.MIN_EDGE_PCT:.1f}%",
            "{{MIN_BOOKS}}": str(config.MIN_BOOKS),
            "{{MAX_PLAYS}}": str(config.MAX_PLAYS_PER_DAY),
            "{{POST_TIME}}": config.POST_TIME_LABEL,
            "{{SIGNUP}}": R.signup_form(),
            "{{YEAR}}": str(datetime.utcnow().year),
            "{{TONIGHT_BOARD}}": R.board_cards(tonight_rows(board_doc)),
            # ---- the +EV page, generated so it cannot drift from config
            "{{BAT_DATE}}": doc_date_label(batter_doc, lang) or L("not_rated"),
            "{{BATTER_CARDS}}": R.batter_cards(batter_doc.get("batters", [])),
            "{{BAT_CALIBRATION}}": R.batter_calibration(
                batter_doc.get("summary", {})),
            "{{HIT_CARDS}}": R.hit_cards(hit_doc.get("batters", [])),
            "{{HIT_CALIBRATION}}": R.hit_calibration(
                hit_doc.get("summary", {})),
            "{{HIT_COUNT}}": L("hit_count", n=len(hit_doc.get("batters", [])),
                              s=pl(len(hit_doc.get("batters", [])))),
            "{{HR_DATE}}": doc_date_label(homer_doc, lang) or L("not_rated"),
            "{{HOMER_CARDS}}": R.homer_cards(homer_doc.get("starters", [])),
            "{{FORM_TABLE}}": "",
            "{{EV_PRICES}}": R.ev_price_table(),
            "{{EV_EXAMPLE}}": R.ev_example(board_doc),
            "{{EV_GATES}}": R.ev_gates(),
            "{{EV_CARD}}": R.ev_card_rules(),
            "{{EV_FUNNEL}}": R.ev_funnel(board_doc),
            "{{EV_HOLD}}": f"{R.ev_numbers(board_doc)['hold']:.2f}",
            "{{EV_SIDES}}": str(R.ev_numbers(board_doc)["sides"]),
            "{{EV_NEGATIVE}}": str(R.ev_numbers(board_doc)["negative"]),
            "{{EV_PLAYS}}": L("ev_n_plays", n=len(plays_doc.get("plays") or []),
                              s=pl(len(plays_doc.get("plays") or []))),
            "{{EV_DAY}}": _board_day(board_doc.get("date", ""), lang) or "&mdash;",
            "{{LEAGUE_BOARD}}": "",
            "{{LEAGUE_NAME}}": "",
        }




    updated = plays_doc.get("generated_at", "")[:16].replace("T", " ") or "—"
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

    for lang in i18n.LANGS:
        R.set_lang(lang)
        # The board's cards carry each game's strikeout props. render holds
        # them the same way it holds the language: set once, before drawing.
        R.set_props(pitch_doc.get("pitchers", []))
        out_dir = ROOT if lang == "en" else ROOT / lang
        out_dir.mkdir(parents=True, exist_ok=True)

        tokens = build_tokens(lang, plays_doc, stats, history,
                              slate_doc, pitch_doc)

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
            if page.body == "form":
                import results_store, form_store          # noqa: E402
                page_tokens["{{LEAGUE_NAME}}"] = leagues.LEAGUES[page.league].label
                page_tokens["{{FORM_TABLE}}"] = R.form_table(
                    form_store.table(results_store.load(page.league)))
            elif page.league:
                entry = (board_doc.get("leagues") or {}).get(page.league, {})
                page_tokens["{{LEAGUE_NAME}}"] = entry.get(
                    "label", leagues.LEAGUES[page.league].label)
                page_tokens["{{LEAGUE_BOARD}}"] = R.board_cards(
                    entry.get("games") or [])
                page_tokens["{{BOARD_EYEBROW}}"] = i18n.t(
                    "board_eyebrow", lang,
                    n=(board_doc.get("counts") or {}).get(page.league, 0),
                    d=_board_day(board_doc.get("date", ""), lang))
            if page.body == "hits":
                # {{DATE_LABEL}} is otherwise the plays board's date; the
                # hits page is the only body that consumes it, so it is
                # safe to point it at the hits document here instead.
                page_tokens["{{DATE_LABEL}}"] = (
                    doc_date_label(hit_doc, lang) or i18n.t("not_rated", lang))
            elif page.body in NFL_DOCS:
                # Four sibling pages sharing one set of token names. Each
                # page's own document supplies the values, the same way the
                # hits page above supplies its own DATE_LABEL rather than
                # the plays board's.
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
                title=title, css=CSS, links=links, site=config.SITE_NAME,
                lang=lang, desc=META_DESC[lang].format(site=config.SITE_NAME),
                hreflang=hreflang, up=up, views=views,
                views_empty=("" if views else " is-empty"),
                about_href=f"{up}about.html", plays_href=f"{up}plays.html",
                ev_href=f"{up}ev.html",
                why_free=i18n.t("nav_why", lang), cta=i18n.t("cta_plays", lang),
                banner=mock_banner(lang) if plays_doc.get("mock") else "",
            )
            stamp = (plays_doc.get("generated_at", "") or "")[:16].replace("T", " ")
            html_out = head + body + footer_html(lang, year, up, stamp)
            target = out_dir / out_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html_out, encoding="utf-8")
            print(f"built {lang}/{out_name}  ({len(html_out)//1024} KB)")


def _self_test() -> None:
    # Every registry entry is a Page, and the key matches its output path.
    for out, page in PAGES.items():
        assert isinstance(page, Page), f"{out} is not a Page: {page!r}"
        assert page.out == out, f"{out} is filed under {page.out}"

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

