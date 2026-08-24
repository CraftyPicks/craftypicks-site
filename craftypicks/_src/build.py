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

CSS = (SRC / "base.css").read_text()

PAGES = {
    "index.html": (f"{config.SITE_NAME} — Free daily sports betting plays with receipts", "home"),
    "plays.html": f"Today's Plays — {config.SITE_NAME}",
    "record.html": f"Track Record — {config.SITE_NAME}",
    "about.html": f"How It Works — {config.SITE_NAME}",
}
NAV_ITEMS = [
    ("plays.html", "Today's Plays", "plays"),
    ("record.html", "Track Record", "record"),
    ("about.html", "How It Works", "about"),
]

HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{site} posts free NBA, NFL, MLB and college basketball plays every day — the number, the price, the reasoning, and a fully public track record. Nothing for sale.">
<meta property="og:title" content="{title}">
<meta property="og:description" content="Free daily plays with receipts on every one.">
<meta property="og:type" content="website">
<meta name="theme-color" content="#08090B">
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
    <a href="index.html" class="logo">Crafty<span>picks</span></a>
    <nav class="nav-links">{links}</nav>
    <div class="nav-cta">
      <a href="about.html" class="link-quiet">Why it's free</a>
      <a href="plays.html" class="btn solid sm">Today's plays</a>
    </div>
  </div>
</header>
{banner}
"""

MOCK_BANNER = """<div class="mock-banner">
  <b>Sample data.</b> These plays were generated for testing — no real odds feed is connected yet.
  Add your ODDS_API_KEY and run the daily job to replace them.
</div>"""

FOOTER = """
<footer>
  <div class="wrap">
    <div class="foot-grid">
      <div>
        <a href="index.html" class="logo" style="display:inline-block;margin-bottom:14px">Crafty<span>picks</span></a>
        <p style="font-size:14px;max-width:34ch">Free plays, posted daily, graded in public. No packages, no premium tier, no DMs.</p>
      </div>
      <div>
        <h4>Plays</h4>
        <a href="plays.html">Today's board</a>
        <a href="plays.html#results">Yesterday's results</a>
        <a href="record.html">Full play log</a>
      </div>
      <div>
        <h4>Transparency</h4>
        <a href="record.html">Track record</a>
        <a href="about.html#method">Methodology</a>
        <a href="about.html#units">Units &amp; bankroll</a>
      </div>
      <div>
        <h4>About</h4>
        <a href="about.html">How it works</a>
        <a href="about.html#faq">FAQ</a>
        <a href="about.html#responsible">Play responsibly</a>
      </div>
    </div>
    <div class="note" style="margin-bottom:26px">
      <p class="disclaimer"><b style="color:var(--txt)">21+ only. For entertainment purposes.</b> Craftypicks is not a sportsbook and does not accept wagers, hold funds, or facilitate betting of any kind. Nothing here is financial advice or a guarantee of profit &mdash; every play posted can lose, and most winning stretches are followed by losing ones. Never wager money you cannot afford to lose. If gambling stops being fun, call <b style="color:var(--txt)">1-800-GAMBLER</b> or text 800GAM to 800177.</p>
    </div>
    <div class="foot-bot">
      <p>&copy; {year} Craftypicks. Plays are posted before the number moves and graded exactly as posted.</p>
      <span class="mono" style="letter-spacing:.14em;text-transform:uppercase">Board updated {updated}</span>
    </div>
  </div>
</footer>
<script>
document.querySelectorAll('.chip[data-filter]').forEach(function(chip){
  if(chip.disabled) return;
  chip.addEventListener('click',function(){
    document.querySelectorAll('.chip[data-filter]').forEach(function(c){c.classList.remove('on')});
    chip.classList.add('on');
    var f=chip.dataset.filter;
    document.querySelectorAll('#board .play').forEach(function(card){
      card.style.display=(f==='all'||card.dataset.league===f)?'':'none';
    });
  });
});
document.querySelectorAll('form[data-signup]').forEach(function(form){
  form.addEventListener('submit',function(e){
    e.preventDefault();
    var msg=form.parentElement.querySelector('.form-msg');
    form.reset();
    if(msg) msg.textContent='Email signup isn\\u2019t connected yet \\u2014 check back shortly.';
  });
});
</script>
</body>
</html>
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


def pretty_day(stamp: str) -> str:
    try:
        return f"{datetime.fromisoformat(stamp):%A, %B %-d}"
    except Exception:
        return stamp


def net_units(plays: list[dict]) -> float:
    return round(sum(p.get("profit", 0.0) for p in plays), 2)


# ---------------------------------------------------------------------- build
def build() -> None:
    plays_doc = load("plays.json", {"plays": [], "summary": {}, "date_label": "", "note": ""})
    stats = load("stats.json", {})
    history = load("history.json", {"plays": []})["plays"]

    card = plays_doc.get("plays", [])
    today = plays_doc.get("date", datetime.utcnow().date().isoformat())
    y_date, y_plays = latest_graded_day(history, today)
    recent = (stats.get("recent") or [])

    summary = plays_doc.get("summary", {})
    by_league = summary.get("by_league", {})
    league_line = " &middot; ".join(f"{n} {lg}" for lg, n in by_league.items()) or "—"

    if card:
        count_line = (
            f"{len(card)} play{'s' if len(card) != 1 else ''} on the card. "
            f"Posted at {plays_doc.get('post_time', config.POST_TIME_LABEL)}, with the price and "
            "book that was available at that moment. Every one gets graded here tomorrow morning."
        )
    else:
        count_line = (
            "No plays on the card today. The board was scanned and nothing cleared the "
            "edge threshold — that's a normal result, not an outage."
        )

    graded_n = stats.get("graded", 0)
    if graded_n:
        record_intro = (
            f"{graded_n} graded plays, {stats.get('pending', 0)} still in flight. Nothing "
            "removed, nothing re-priced after the fact. The losing stretches are on this "
            "page too — they're the point."
        )
        months_line = (
            f"{stats.get('losing_months', 0)} losing months out of "
            f"{stats.get('total_months', 0)}. Any record without red months has been edited."
        )
        log_heading = f"The last {min(20, len(recent))} graded plays"
    else:
        record_intro = (
            "This log starts empty, on purpose. Every play the scanner posts lands here the "
            "next morning — graded against the final score, winners and losers alike, and "
            "never edited afterward. Check back once the first cards have run."
        )
        months_line = (
            "The monthly chart fills in as soon as the first month of plays has been graded."
        )
        log_heading = "Play log"

    tokens = {
        "{{RECORD_INTRO}}": record_intro,
        "{{MONTHS_LINE}}": months_line,
        "{{LOG_HEADING}}": log_heading,
        "{{DATE_LABEL}}": plays_doc.get("date_label", ""),
        "{{COUNT_LINE}}": count_line,
        "{{PLAY_COUNT}}": str(len(card)),
        "{{UNITS_RISKED}}": f"{summary.get('units_risked', 0):.1f}u",
        "{{LEAGUE_LINE}}": league_line,
        "{{FILTER_CHIPS}}": R.filter_chips(card),
        "{{FILTER_BLOCK}}": (f'<div class="filters" style="margin-top:36px">'
                             f'{R.filter_chips(card)}</div>') if R.filter_chips(card) else "",
        "{{BOARD_EYEBROW}}": (
            f"{plays_doc.get('date_label','')} · Posted {plays_doc.get('post_time', config.POST_TIME_LABEL)}"
            if card else
            f"Board scanned · Next card posts at {plays_doc.get('post_time', config.POST_TIME_LABEL)}"),
        "{{HERO_CARD}}": R.play_card(card[0], 1, len(card)) if card
                         else R.empty_card(plays_doc.get("note", "")),
        "{{PLAY_CARDS}}": R.play_cards(card, plays_doc.get("note", "")),
        "{{YESTERDAY_LABEL}}": pretty_day(y_date) if y_date else "the last graded card",
        "{{YESTERDAY_ROWS}}": R.yesterday_rows(y_plays),
        "{{YESTERDAY_NET}}": R.u(net_units(y_plays)),
        "{{YESTERDAY_NET_CLASS}}": R.cls_for(net_units(y_plays)),
        "{{KPI_HOME}}": R.kpi_strip(stats, "home"),
        "{{KPI_RECORD}}": R.kpi_strip(stats, "record"),
        "{{RECENT_ROWS}}": R.result_rows(recent[:6], "compact"),
        "{{RECENT_NET}}": R.u(net_units(recent[:6])),
        "{{RECENT_NET_CLASS}}": R.cls_for(net_units(recent[:6])),
        "{{RECENT_COUNT}}": str(min(6, len(recent))),
        "{{LOG_ROWS}}": R.result_rows(recent[:20], "full"),
        "{{LOG_COUNT}}": str(min(20, len(recent))),
        "{{LEAGUE_ROWS}}": R.league_rows(stats.get("by_league", [])),
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
    footer = FOOTER.replace("{year}", str(datetime.utcnow().year)).replace("{updated}", updated)

    for fname, meta in PAGES.items():
        title = meta[0] if isinstance(meta, tuple) else meta
        key = meta[1] if isinstance(meta, tuple) else fname.replace(".html", "")
        links = "".join(
            f'<a href="{href}" class="{"on" if k == key else ""}">{label}</a>'
            for href, label, k in NAV_ITEMS
        )
        body = (SRC / fname.replace(".html", ".body.html")).read_text()
        for token, value in tokens.items():
            body = body.replace(token, value)
        head = HEAD.format(
            title=title, css=CSS, links=links, site=config.SITE_NAME,
            banner=MOCK_BANNER if plays_doc.get("mock") else "",
        )
        html_out = head + body + footer
        (ROOT / fname).write_text(html_out)
        print(f"built {fname}  ({len(html_out)//1024} KB)")


if __name__ == "__main__":
    build()
