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
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
DATA = ROOT / "data"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "scripts"))

import config   # noqa: E402
import render as R  # noqa: E402
import i18n         # noqa: E402

CSS = (SRC / "base.css").read_text()

PAGES = {
    "index.html": (f"{config.SITE_NAME} — Free daily sports betting plays with receipts", "home"),
    "plays.html": f"Today's Plays — {config.SITE_NAME}",
    "record.html": f"Track Record — {config.SITE_NAME}",
    "about.html": f"How It Works — {config.SITE_NAME}",
    "screens.html": f"The Strikeout Screens — {config.SITE_NAME}",
    "slate.html": f"MLB Board — {config.SITE_NAME}",
    "pitchers.html": f"Pitchers Prop — {config.SITE_NAME}",
}
# Labels come from i18n so the nav translates with everything else.
NAV_ITEMS = [
    ("plays.html", "nav_plays", "plays"),
    ("slate.html", "nav_board", "slate"),
    ("pitchers.html", "nav_pitchers", "pitchers"),
    ("record.html", "nav_record", "record"),
    ("about.html", "nav_about", "about"),
    ("screens.html", "nav_screens", "screens"),
]

# Page titles per language. The English half is what the site shipped with.
TITLES = {
    "index.html": {"en": f"{config.SITE_NAME} — Free daily sports betting plays with receipts",
                   "es": f"{config.SITE_NAME} — Jugadas deportivas gratis, con recibos"},
    "plays.html": {"en": f"Today's Plays — {config.SITE_NAME}",
                   "es": f"Jugadas de hoy — {config.SITE_NAME}"},
    "record.html": {"en": f"Track Record — {config.SITE_NAME}",
                    "es": f"Historial — {config.SITE_NAME}"},
    "about.html": {"en": f"How It Works — {config.SITE_NAME}",
                   "es": f"Cómo funciona — {config.SITE_NAME}"},
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
<meta name="viewport" content="width=device-width,initial-scale=1">
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
    <a href="index.html" class="logo">Craftypicks<em>.</em></a>
    <nav class="nav-links">{links}</nav>
    <div class="nav-cta">
      <a href="{about_href}" class="link-quiet">{why_free}</a>
      <a href="{plays_href}" class="btn solid sm">{cta}</a>
    </div>
  </div>
</header>
{statbar}
{banner}
"""

def mock_banner(lang: str) -> str:
    return f'<div class="mock-banner">{i18n.t("sample_data", lang)}</div>' 

def footer_html(lang: str, year: int) -> str:
    """The footer, per language. Links point inside the same language tree."""
    L = lambda k: i18n.t(k, lang)
    return f"""
<footer>
  <div class="wrap">
    <div class="foot-grid">
      <div>
        <a href="index.html" class="logo" style="display:inline-block;margin-bottom:14px">Craftypicks<em>.</em></a>
        <p style="font-size:14px;max-width:34ch">{L("foot_tagline")}</p>
      </div>
      <div>
        <h4>{L("foot_plays")}</h4>
        <a href="plays.html">{L("foot_today")}</a>
        <a href="plays.html#results">{L("foot_yest")}</a>
        <a href="record.html">{L("foot_log")}</a>
      </div>
      <div>
        <h4>{L("foot_trans")}</h4>
        <a href="record.html">{L("nav_record")}</a>
        <a href="about.html#method">{L("foot_method")}</a>
        <a href="screens.html">{L("nav_screens")}</a>
      </div>
      <div>
        <h4>{L("foot_about")}</h4>
        <a href="about.html">{L("nav_about")}</a>
        <a href="about.html#faq">{L("foot_faq")}</a>
        <a href="about.html#responsible">{L("foot_resp")}</a>
      </div>
    </div>
    <div class="foot-legal">
      <p class="disclaimer">{L("disclaimer")}</p>
      <p>{i18n.t("foot_copy", lang, year=year)}</p>
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


def _statbar(slate_doc: dict, plays_doc: dict, lang: str = "en") -> str:
    """The live-facts row under the nav.

    Every figure is derived from the data already on disk — nothing here is
    decorative, and nothing is asserted that the files don't support. On a
    board that hasn't been rated the row still renders, saying so plainly,
    because a status strip that vanishes when there's nothing to report is
    worse than one that admits it.
    """
    games = slate_doc.get("games") or []
    rated = len(games)
    flagged = sum(1 for g in games if g.get("suspect"))
    gaps = sorted(abs(g["disagreement"]) for g in games
                  if g.get("disagreement") is not None)
    if gaps:
        mid = len(gaps) // 2
        median = gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2
        median_txt = f'<b>{median:.1f} {i18n.t("pts", lang)}</b>'
    else:
        median_txt = "<b>&mdash;</b>"

    stamp = (plays_doc.get("generated_at", "") or "")[:16].replace("T", " ")
    L = lambda k, **kw: i18n.t(k, lang, **kw)
    live = L("sb_live") if rated else L("sb_noboard")
    pl = i18n.plural

    cells = [
        f'<div class="sb-cell"><span class="sb-live"><span class="dot"></span>{live}</span></div>',
        f'<div class="sb-cell">{L("sb_rated", n=f"<b>{rated}</b>", s=pl(rated, lang))}</div>',
        f'<div class="sb-cell">{L("sb_flagged", n=f"<b>{flagged}</b>", s=pl(flagged, lang))}</div>',
        f'<div class="sb-cell">{L("sb_median", v=median_txt)}</div>',
        f'<div class="sb-cell">{L("sb_updated", v=f"<b>{esc_min(stamp) or chr(8212)}</b>")}</div>',
    ]
    return '<div class="statbar">' + "".join(cells) + "</div>"


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
        out_dir = ROOT if lang == "en" else ROOT / lang
        out_dir.mkdir(parents=True, exist_ok=True)

        tokens = build_tokens(lang, plays_doc, stats, history,
                              slate_doc, pitch_doc)

        for fname in PAGES:
            key = PAGES[fname]
            title = TITLES[fname][lang]
            links = "".join(
                f'<a href="{href}" class="{"on" if k == key else ""}">'
                f'{i18n.t(label, lang)}</a>'
                for href, label, k in NAV_ITEMS
            )
            hreflang = ""
            body_file = SRC / (fname.replace(".html", "") + (".body.html" if lang == "en"
                                                            else f".body.{lang}.html"))
            if not body_file.exists():          # untranslated page falls back
                body_file = SRC / fname.replace(".html", ".body.html")
                print(f"!! {fname} has no {lang} copy; using English")
            body = body_file.read_text()
            for token, value in tokens.items():
                body = body.replace(token, value)

            head = HEAD.format(
                title=title, css=CSS, links=links, site=config.SITE_NAME,
                lang=lang, desc=META_DESC[lang].format(site=config.SITE_NAME),
                hreflang=hreflang,
                about_href="about.html", plays_href="plays.html",
                why_free=i18n.t("nav_why", lang), cta=i18n.t("cta_plays", lang),
                statbar=_statbar(slate_doc, plays_doc, lang),
                banner=mock_banner(lang) if plays_doc.get("mock") else "",
            )
            html_out = head + body + footer_html(lang, year)
            (out_dir / fname).write_text(html_out)
            print(f"built {lang}/{fname}  ({len(html_out)//1024} KB)")


if __name__ == "__main__":
    build()
