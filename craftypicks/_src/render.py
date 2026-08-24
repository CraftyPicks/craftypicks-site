"""Render the site's data-driven pieces as HTML fragments.

Every function here takes plain dicts loaded from data/*.json and returns a
string. No template engine, no dependencies — that keeps the free hosting
story simple and the build instant.
"""
from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import config          # noqa: E402
import odds_math as om  # noqa: E402

BOOK_NOTE = "Odds shown are the price at post time"


def esc(text) -> str:
    return html.escape(str(text), quote=False)


def u(value: float, decimals: int = 2) -> str:
    """Signed unit figure, using a real minus sign."""
    value = round(float(value), decimals)
    sign = "+" if value > 0 else ("−" if value < 0 else "")
    return f"{sign}{abs(value):.{decimals}f}u"


def pct(value: float, decimals: int = 1) -> str:
    value = round(float(value), decimals)
    sign = "+" if value > 0 else ("−" if value < 0 else "")
    return f"{sign}{abs(value):.{decimals}f}%"


def cls_for(value: float) -> str:
    return "g" if value > 0 else ("r" if value < 0 else "")


def game_time(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(
            ZoneInfo(config.TIMEZONE))
        return f"{dt:%-I:%M %p} ET"
    except Exception:
        return ""


def posted_time(iso: str | None) -> str:
    if not iso:
        return config.POST_TIME_LABEL
    try:
        dt = datetime.fromisoformat(iso)
        return f"{dt:%-I:%M %p} ET"
    except Exception:
        return config.POST_TIME_LABEL


# ------------------------------------------------------------------ play card
def play_card(play: dict, index: int, total: int) -> str:
    reasons = "".join(f"<li>{r}</li>" for r in play.get("reasons", []))
    tip = game_time(play.get("commence_time"))
    return f"""
      <div class="play" data-league="{esc(play.get('league_short',''))}">
        <div class="play-top">
          <div style="display:flex;align-items:center;gap:9px">
            <span class="dot"></span>
            <span class="stamp on">Posted {esc(posted_time(play.get('posted_at')))}</span>
          </div>
          <span class="stamp">Play {index} of {total}</span>
        </div>
        <div class="play-body">
          <div class="pick">{esc(play.get('pick',''))}</div>
          <div class="meta">{esc(play.get('league',''))} &middot; {esc(play.get('market_label',''))}
            &middot; {esc(om.format_american(play['price']))} &middot; {esc(play.get('book',''))}</div>
          <div class="matchup-line">{esc(play.get('matchup',''))}{f' &middot; {tip}' if tip else ''}</div>
          <ul class="reasons">{reasons}</ul>
          <div class="stats">
            <div class="stat"><div class="k">Stake</div><div class="v">{play.get('stake',1.0):.1f}u</div></div>
            <div class="stat"><div class="k">Edge vs fair</div>
              <div class="v g">{pct(play.get('edge_pct',0))}</div></div>
            <div class="stat"><div class="k">Fair price</div>
              <div class="v">{esc(om.format_american(play.get('fair_price',0)))}</div></div>
          </div>
        </div>
      </div>"""


def empty_card(note: str = "") -> str:
    body = note or (
        "Nothing on the board cleared the edge threshold this morning. "
        "A card with no plays is a normal outcome — forcing one is how a good "
        "process turns into a bad month."
    )
    return f"""
      <div class="play" style="grid-column:1/-1">
        <div class="play-top">
          <span class="stamp">No qualifying plays</span>
          <span class="stamp">Checked every game on the board</span>
        </div>
        <div class="play-body">
          <div class="pick" style="color:var(--muted)">No plays today</div>
          <p style="margin-top:10px;max-width:60ch">{esc(body)}</p>
        </div>
      </div>"""


def play_cards(plays: list[dict], note: str = "") -> str:
    if not plays:
        return empty_card(note)
    return "".join(play_card(p, i, len(plays)) for i, p in enumerate(plays, 1))


# --------------------------------------------------------------------- chips
def filter_chips(plays: list[dict]) -> str:
    if len(plays) < 2:
        return ""
    counts: dict[str, tuple[str, int]] = {}
    for p in plays:
        short = p.get("league_short", "")
        label, n = counts.get(short, (p.get("league", short), 0))
        counts[short] = (label, n + 1)
    chips = [f'<button class="chip on" data-filter="all">All plays</button>']
    for short, (label, n) in sorted(counts.items(), key=lambda kv: -kv[1][1]):
        chips.append(
            f'<button class="chip" data-filter="{esc(short)}">{esc(label)} &middot; {n}</button>')
    return "".join(chips)


# -------------------------------------------------------------------- tables
RESULT_TAG = {"win": ("win", "Win"), "loss": ("loss", "Loss"), "push": ("push", "Push")}


def result_rows(plays: list[dict], columns: str = "full") -> str:
    if not plays:
        colspan = 7 if columns == "full" else 5
        return (f'<tr><td colspan="{colspan}" style="text-align:center;padding:34px 18px">'
                "No graded plays yet — the first results land the morning after "
                "the first card.</td></tr>")
    rows = []
    for p in plays:
        tag, label = RESULT_TAG.get(p.get("result", ""), ("", "—"))
        profit = p.get("profit", 0.0)
        if columns == "full":
            rows.append(f"""<tr>
              <td class="m">{esc(_short_date(p))}</td>
              <td class="strong">{esc(p.get('pick',''))}</td>
              <td class="m">{esc(p.get('league',''))}</td>
              <td class="m">{esc(om.format_american(p.get('price',0)))}</td>
              <td class="m">{pct(p.get('edge_pct',0))}</td>
              <td><span class="tag {tag}">{label}</span></td>
              <td class="m {cls_for(profit)}">{u(profit)}</td></tr>""")
        else:
            rows.append(f"""<tr>
              <td class="strong">{esc(p.get('pick',''))}</td>
              <td class="m">{esc(p.get('league',''))}</td>
              <td class="m">{esc(om.format_american(p.get('price',0)))}</td>
              <td><span class="tag {tag}">{label}</span></td>
              <td class="m {cls_for(profit)}">{u(profit)}</td></tr>""")
    return "".join(rows)


def yesterday_rows(plays: list[dict]) -> str:
    if not plays:
        return ('<tr><td colspan="7" style="text-align:center;padding:34px 18px">'
                "Nothing graded from yesterday yet.</td></tr>")
    rows = []
    for p in plays:
        tag, label = RESULT_TAG.get(p.get("result", ""), ("", "Pending"))
        profit = p.get("profit", 0.0)
        rows.append(f"""<tr>
          <td class="strong">{esc(p.get('pick',''))}</td>
          <td class="m">{esc(p.get('league',''))}</td>
          <td class="m">{esc(p.get('market_label',''))}</td>
          <td class="m">{esc(om.format_american(p.get('price',0)))}</td>
          <td class="m">{p.get('stake',1.0):.1f}u</td>
          <td><span class="tag {tag}">{label}</span></td>
          <td class="m {cls_for(profit)}">{u(profit)}</td></tr>""")
    return "".join(rows)


def league_rows(rows: list[dict]) -> str:
    if not rows:
        return ('<tr><td colspan="6" style="text-align:center;padding:34px 18px">'
                "No graded plays yet.</td></tr>")
    out = []
    for r in rows:
        out.append(f"""<tr>
          <td class="strong">{esc(r['league'])}</td>
          <td class="m">{r['plays']}</td>
          <td class="m">{esc(r['record'])}</td>
          <td class="m">{r['win_pct']:.1f}%</td>
          <td class="m {cls_for(r['units'])}">{u(r['units'])}</td>
          <td class="m {cls_for(r['roi'])}">{pct(r['roi'])}</td></tr>""")
    return "".join(out)


def _short_date(play: dict) -> str:
    stamp = play.get("posted_date") or (play.get("commence_time") or "")[:10]
    try:
        return f"{datetime.fromisoformat(stamp):%b %-d}"
    except Exception:
        return stamp


# ---------------------------------------------------------------------- KPIs
def kpi_strip(s: dict, variant: str = "home") -> str:
    units, roi = s.get("units", 0.0), s.get("roi", 0.0)
    if variant == "home":
        cards = [
            ("Units won", u(units), cls_for(units), "Flat 1u stake on every play"),
            ("ROI", pct(roi), cls_for(roi), f"Across {s.get('graded',0)} graded plays"),
            ("Record", esc(s.get("record", "0–0–0")), "",
             f"{s.get('win_pct',0):.1f}% on decided plays"),
            ("Losing months", f"{s.get('losing_months',0)}<span style=\"color:var(--dim)\">/"
             f"{max(s.get('total_months',0),1)}</span>", "", "We post those too"),
        ]
    else:
        cards = [
            ("Units won", u(units), cls_for(units), "Flat 1u stake on every play"),
            ("ROI", pct(roi), cls_for(roi), f"Return on {s.get('risked',0):.0f}u risked"),
            ("Record", esc(s.get("record", "0–0–0")), "",
             f"{s.get('win_pct',0):.1f}% on decided plays"),
            ("Worst drawdown", u(s.get("drawdown", 0.0)), cls_for(s.get("drawdown", 0.0)),
             "Peak-to-trough across the log"),
        ]
    return "".join(
        f'<div class="kpi"><div class="k">{k}</div>'
        f'<div class="v {c}">{v}</div><div class="s">{esc(sub)}</div></div>'
        for k, v, c, sub in cards
    )


# --------------------------------------------------------------------- chart
def month_chart(months: list[dict]) -> str:
    if not months:
        return ('<p style="padding:40px 0;text-align:center;color:var(--dim)">'
                "The monthly chart fills in once the first month of plays is graded.</p>")
    peak = max((abs(m["units"]) for m in months), default=1.0) or 1.0
    up_px, down_px = 150.0, 66.0
    cols, described = [], []
    for m in months:
        val = m["units"]
        described.append(f"{m['label']} {u(val)}")
        if val >= 0:
            h = max(3, round(val / peak * up_px))
            body = (f'<div class="pos"><span class="val g">{u(val,1)}</span>'
                    f'<i style="height:{h}px"></i></div><div class="neg"></div>')
        else:
            h = max(3, round(abs(val) / peak * down_px))
            body = (f'<div class="pos"></div><div class="neg">'
                    f'<i class="down" style="height:{h}px"></i>'
                    f'<span class="val r">{u(val,1)}</span></div>')
        cols.append(
            f'<div class="col" title="{esc(m["label"])} {esc(m["year"])} · {u(val)} · '
            f'{m["plays"]} plays">{body}<span class="mlab">{esc(m["label"])}</span></div>')
    label = "Monthly units: " + ", ".join(described)
    return (f'<div class="chart" role="img" aria-label="{esc(label)}">'
            f'<div class="bars">{"".join(cols)}</div></div>')


# -------------------------------------------------------------------- signup
def signup_form(button: str = "Send me the plays") -> str:
    if config.BEEHIIV_EMBED_URL:
        return (f'<iframe src="{esc(config.BEEHIIV_EMBED_URL)}" class="signup-embed" '
                'title="Newsletter signup" scrolling="no" frameborder="0"></iframe>')
    return f"""<form class="form-row" data-signup>
      <input type="email" required placeholder="you@email.com" aria-label="Email address">
      <button class="btn solid" type="submit">{esc(button)}</button>
    </form>
    <p class="form-msg" role="status"></p>"""
