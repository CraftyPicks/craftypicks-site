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
              <div class="v {cls_for(play.get('edge_pct',0))}">{pct(play.get('edge_pct',0))}</div></div>
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
            clv = p.get("clv_ev")
            clv_cell = (f'<td class="m {cls_for(clv)}">{pct(clv)}</td>'
                        if clv is not None else '<td class="m" style="color:var(--dim)">—</td>')
            rows.append(f"""<tr>
              <td class="m">{esc(_short_date(p))}</td>
              <td class="strong">{esc(p.get('pick',''))}</td>
              <td class="m">{esc(p.get('league',''))}</td>
              <td class="m">{esc(om.format_american(p.get('price',0)))}</td>
              <td class="m">{pct(p.get('edge_pct',0))}</td>
              {clv_cell}
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


SOURCE_LABEL = {"value": "Price scanner", "screen": "Strikeout screens"}


def source_rows(rows: list[dict]) -> str:
    """Head-to-head: which approach is actually beating the closing number."""
    if not rows:
        return ('<tr><td colspan="6" style="text-align:center;padding:34px 18px">'
                "Nothing posted yet.</td></tr>")
    out = []
    for r in rows:
        clv = r.get("clv_beat_pct", 0.0)
        clv_cell = (f'<td class="m {cls_for(clv - 50)}">{clv:.0f}%</td>'
                    if r.get("clv_n") else '<td class="m" style="color:var(--dim)">—</td>')
        out.append(f"""<tr>
          <td class="strong">{esc(SOURCE_LABEL.get(r['source'], r['source']))}</td>
          <td class="m">{r['posted']}</td>
          <td class="m">{esc(r['record'])}</td>
          <td class="m {cls_for(r['units'])}">{u(r['units'])}</td>
          <td class="m {cls_for(r['roi'])}">{pct(r['roi'])}</td>
          {clv_cell}</tr>""")
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
            ("Beat the close",
             f"{s.get('clv_beat_pct', 0):.0f}%" if s.get("clv_n") else "—",
             cls_for(s.get("clv_beat_pct", 0) - 50) if s.get("clv_n") else "",
             f"On {s.get('clv_n', 0)} plays with a late line"),
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


# ------------------------------------------------------- screen methodology
# Labels for the screen thresholds. The page renders straight from
# screen_config.py, so the rules shown to readers can never drift from the
# rules the scanner actually applies — a published methodology that quietly
# disagrees with the code is worse than none.
SCREEN_LABELS = {
    "min_pitcher_k_pct": ("Pitcher season K%", "at least", "pct"),
    "min_vs_pa": ("Career PA vs this roster", "at least", "int"),
    "min_vs_k_pct": ("K% vs this roster", "at least", "pct"),
    "max_vs_avg": ("Batting average vs this roster", "under", "three"),
    "max_vs_woba": ("wOBA vs this roster", "under", "three"),
    "min_opp_k_per_game": ("Opponent strikeouts per game", "at least", "two"),
    "max_opp_k_per_game": ("Opponent strikeouts per game", "below", "two"),
    "line_min": ("Strikeout line", "at least", "one"),
    "line_max": ("Strikeout line", "at most", "one"),
    "worst_juice": ("Price", "no worse than", "odds"),
    "min_odds": ("Price", "plus money only, at least", "odds"),
    "min_k_per_9": ("Season K/9", "at least", "one"),
    "max_bets_per_day": ("Plays per day from this screen", "at most", "int"),
    "preferred_k_pct_min": ("Preferred K% band, low end", "", "pct"),
    "preferred_k_pct_max": ("Preferred K% band, high end", "", "pct"),
    "high_k_exclude_at": ("Excluded if season K% reaches", "", "pct"),
    "max_line": ("Any line at or above this", "never bet", "one"),
    "banned_line": ("This exact line", "never bet", "one"),
}


def _fmt_threshold(value, kind: str) -> str:
    if kind == "pct":
        return f"{value * 100:.0f}%"
    if kind == "three":
        return f"{value:.3f}"
    if kind == "two":
        return f"{value:.2f}"
    if kind == "one":
        return f"{value:g}"
    if kind == "odds":
        return om.format_american(value)
    return str(value)


def screen_rule_rows(cfg: dict, skip=("fade_list",)) -> str:
    """A None threshold means the rule is switched off — say so plainly
    rather than printing 'None' at a reader."""
    rows = []
    for key, value in cfg.items():
        if key in skip or key not in SCREEN_LABELS:
            continue
        label, comparator, kind = SCREEN_LABELS[key]
        if value is None:
            rows.append(f"""<tr>
              <td class="strong" style="color:var(--dim)">{esc(label)}</td>
              <td style="color:var(--dim)">no limit</td>
              <td class="m" style="color:var(--dim)">off</td></tr>""")
            continue
        rows.append(f"""<tr>
          <td class="strong">{esc(label)}</td>
          <td>{esc(comparator)}</td>
          <td class="m">{esc(_fmt_threshold(value, kind))}</td></tr>""")
    return "".join(rows)


def breakeven_rows(prices=(-150, -130, -120, -110, 100, 110, 120, 140)) -> str:
    """What each price has to hit just to break even."""
    rows = []
    for price in prices:
        need = (100 / (price + 100)) if price > 0 else (abs(price) / (abs(price) + 100))
        rows.append(f"""<tr>
          <td class="m strong">{esc(om.format_american(price))}</td>
          <td class="m">{need * 100:.1f}%</td>
          <td>{_breakeven_note(need)}</td></tr>""")
    return "".join(rows)


def _breakeven_note(need: float) -> str:
    if need > 0.5:
        return "needs a real edge"
    if abs(need - 0.5) < 1e-9:
        return "a coin flip breaks even"
    return "a coin flip profits"


# --------------------------------------------------------------- full slate
def slate_rows(rows: list[dict]) -> str:
    if not rows:
        return ('<tr><td colspan="7" style="text-align:center;padding:34px 18px">'
                "No games rated today.</td></tr>")
    out = []
    for r in rows:
        ours = r.get("home_win_prob")
        mkt = r.get("market_home_prob")
        gap = r.get("disagreement")
        if gap is None:
            gap_cell = '<td class="m" style="color:var(--dim)">—</td>'
        elif r.get("suspect"):
            gap_cell = (f'<td class="m" style="color:var(--amber)" '
                        f'title="Bigger than the market can plausibly be wrong by — '
                        f'treated as our error">{gap:+.1f}&nbsp;⚠</td>')
        else:
            gap_cell = f'<td class="m {cls_for(gap)}">{gap:+.1f}</td>'
        starters = " / ".join(x for x in (r.get("away_starter"), r.get("home_starter")) if x)
        out.append(f"""<tr>
          <td class="m">{esc(game_time(r.get('commence_time')))}</td>
          <td class="strong">{esc(r.get('away',''))} @ {esc(r.get('home',''))}</td>
          <td style="font-size:13px;color:var(--muted)">{esc(starters) or '—'}</td>
          <td class="m">{ours*100:.1f}%</td>
          <td class="m">{f'{mkt*100:.1f}%' if mkt is not None else '—'}</td>
          {gap_cell}
          <td class="m" style="color:var(--dim)">{esc(r.get('final') or '')}</td></tr>""")
    return "".join(out)


def calibration_rows(rows: list[dict]) -> str:
    live = [r for r in rows if r.get("n")]
    if not live:
        return ('<tr><td colspan="5" style="text-align:center;padding:34px 18px">'
                "Nothing graded yet — this table fills in as rated games finish."
                "</td></tr>")
    out = []
    for r in live:
        gap = r["gap"]
        # Within the noise band for the sample size, a gap means nothing.
        import math as _m
        se = _m.sqrt(0.25 / r["n"]) * 100 * 1.96
        verdict = "within noise" if abs(gap) <= se else (
            "we were too low" if gap > 0 else "we were too high")
        out.append(f"""<tr>
          <td class="strong">{f"{r['lo']*100:.0f}%+" if r['hi'] > 1.0 else f"{r['lo']*100:.0f}–{r['hi']*100:.0f}%"}</td>
          <td class="m">{r['n']}</td>
          <td class="m">{r['predicted']:.1f}%</td>
          <td class="m">{r['actual']:.1f}%</td>
          <td style="font-size:13px;color:var(--muted)">{esc(verdict)} (±{se:.1f})</td></tr>""")
    return "".join(out)


def brier_line(summary: dict) -> str:
    ours, theirs = summary.get("brier"), summary.get("market_brier")
    if ours is None:
        return ("No rated game has finished yet. Once they start grading, this "
                "line reports how far off our probabilities were.")
    text = (f"Across {summary.get('graded', 0)} graded ratings our Brier score is "
            f"<b style=\"color:var(--txt)\">{ours:.4f}</b>. Always saying 50% scores 0.250, "
            "so lower than that is the minimum bar for being worth reading.")
    if theirs is not None:
        better = "better than" if ours < theirs else ("worse than" if ours > theirs else "level with")
        text += (f" The market scored <b style=\"color:var(--txt)\">{theirs:.4f}</b> on the same "
                 f"{summary.get('market_compared', 0)} games — its own vig-free number taken at "
                 f"the moment we rated the game, not the closing price — so we are {better} it. "
                 "Being worse is the expected outcome and we publish it either way.")
    return text
