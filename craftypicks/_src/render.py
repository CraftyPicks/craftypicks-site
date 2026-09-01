"""Render the site's data-driven pieces as HTML fragments.

Every function here takes plain dicts loaded from data/*.json and returns a
string. No template engine, no dependencies — that keeps the free hosting
story simple and the build instant.
"""
from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import config          # noqa: E402
import leagues          # noqa: E402
import odds_math as om  # noqa: E402
import i18n             # noqa: E402

BOOK_NOTE = "Odds shown are the price at post time"

# The language of the page currently being rendered. build.py sets it once
# per pass and every string below reads it. A module-level value rather than
# a parameter on twenty signatures: the build is single-threaded and renders
# one language to completion before starting the next, so there is nothing
# for two languages to race over.
LANG = "en"


def set_lang(lang: str) -> None:
    global LANG
    LANG = lang if lang in i18n.LANGS else "en"


def _(key: str, **kw) -> str:
    """Shorthand for a translated string in the current language."""
    return i18n.t(key, LANG, **kw)


def _pl(n: int) -> str:
    return i18n.plural(n, LANG)


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
    reasons = "".join(f"<li>{i18n.reason_text(r, LANG)}</li>"
                      for r in play.get("reasons", []))
    tip = game_time(play.get("commence_time"))
    return f"""
      <div class="play" data-league="{esc(play.get('league_short',''))}">
        <div class="play-top">
          <div style="display:flex;align-items:center;gap:9px">
            <span class="dot"></span>
            <span class="stamp on">{_("posted", v=esc(posted_time(play.get("posted_at"))))}</span>
          </div>
          <span class="stamp">{_("play_n_of", i=index, n=total)}</span>
        </div>
        <div class="play-body">
          <div class="pick">{esc(play.get('pick',''))}</div>
          <div class="meta">{esc(play.get('league',''))} &middot; {esc(play.get('market_label',''))}
            &middot; {esc(om.format_american(play['price']))} &middot; {esc(play.get('book',''))}</div>
          <div class="matchup-line">{esc(play.get('matchup',''))}{f' &middot; {tip}' if tip else ''}</div>
          <ul class="reasons">{reasons}</ul>
          <div class="stats">
            <div class="stat"><div class="k">{_("stake")}</div><div class="v">{play.get('stake',1.0):.1f}u</div></div>
            <div class="stat"><div class="k">{_("edge_vs_fair")}</div>
              <div class="v {cls_for(play.get('edge_pct',0))}">{pct(play.get('edge_pct',0))}</div></div>
            <div class="stat"><div class="k">{_("fair_price")}</div>
              <div class="v">{esc(om.format_american(play.get('fair_price',0)))}</div></div>
          </div>
        </div>
      </div>"""


def empty_card(note: str = "") -> str:
    body = note or _("no_plays_body")
    return f"""
      <div class="play" style="grid-column:1/-1">
        <div class="play-top">
          <span class="stamp">{_("no_plays_h")}</span>
          <span class="stamp">{_("no_plays_sub")}</span>
        </div>
        <div class="play-body">
          <div class="pick" style="color:var(--muted)">{_("no_plays_t")}</div>
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
    chips = [f'<button class="chip on" data-filter="all">{_("all_plays")}</button>']
    for short, (label, n) in sorted(counts.items(), key=lambda kv: -kv[1][1]):
        chips.append(
            f'<button class="chip" data-filter="{esc(short)}">{esc(label)} &middot; {n}</button>')
    return "".join(chips)


# -------------------------------------------------------------------- tables
# The tag class is stable; the label is looked up at render time so it
# follows the page's language rather than being frozen at import.
RESULT_CLASS = {"win": "win", "loss": "loss", "push": "push"}
RESULT_KEY = {"win": "res_win", "loss": "res_loss", "push": "res_push"}


def _result_tag(result: str, fallback: str = "&mdash;") -> tuple[str, str]:
    cls = RESULT_CLASS.get(result, "")
    key = RESULT_KEY.get(result)
    return cls, (_(key) if key else fallback)


def result_rows(plays: list[dict], columns: str = "full") -> str:
    if not plays:
        colspan = 7 if columns == "full" else 5
        return (f'<tr><td colspan="{colspan}" style="text-align:center;padding:34px 18px">'
                f'{_("no_graded")}</td></tr>')
    rows = []
    for p in plays:
        tag, label = _result_tag(p.get("result", ""))
        profit = p.get("profit", 0.0)
        if columns == "full":
            clv = p.get("clv_ev")
            clv_cell = (f'<td class="m {cls_for(clv)}">{pct(clv)}</td>'
                        if clv is not None else '<td class="m" style="color:var(--muted)">—</td>')
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
                f'{_("nothing_yesterday")}</td></tr>')
    rows = []
    for p in plays:
        tag, label = _result_tag(p.get("result", ""), _("res_pending"))
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
                f'{_("no_graded_short")}</td></tr>')
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


SOURCE_KEY = {"value": "src_value", "screen": "src_screen"}


def source_rows(rows: list[dict]) -> str:
    """Head-to-head: which approach is actually beating the closing number."""
    if not rows:
        return ('<tr><td colspan="6" style="text-align:center;padding:34px 18px">'
                f'{_("nothing_posted")}</td></tr>')
    out = []
    for r in rows:
        clv = r.get("clv_beat_pct", 0.0)
        clv_cell = (f'<td class="m {cls_for(clv - 50)}">{clv:.0f}%</td>'
                    if r.get("clv_n") else '<td class="m" style="color:var(--muted)">—</td>')
        out.append(f"""<tr>
          <td class="strong">{esc(_(SOURCE_KEY[r['source']]) if r['source'] in SOURCE_KEY else r['source'])}</td>
          <td class="m">{r['posted']}</td>
          <td class="m">{esc(r['record'])}</td>
          <td class="m {cls_for(r['units'])}">{u(r['units'])}</td>
          <td class="m {cls_for(r['roi'])}">{pct(r['roi'])}</td>
          {clv_cell}</tr>""")
    return "".join(out)


def _short_date(play: dict) -> str:
    stamp = play.get("posted_date") or (play.get("commence_time") or "")[:10]
    try:
        return i18n.short_date(datetime.fromisoformat(stamp), LANG)
    except Exception:
        return stamp


# ---------------------------------------------------------------------- KPIs
def kpi_strip(s: dict, variant: str = "home") -> str:
    units, roi = s.get("units", 0.0), s.get("roi", 0.0)
    if variant == "home":
        cards = [
            (_("kpi_units"), u(units), cls_for(units), _("kpi_units_sub")),
            (_("kpi_roi"), pct(roi), cls_for(roi),
             _("kpi_roi_home", n=s.get("graded", 0))),
            (_("kpi_record"), esc(s.get("record", "0–0–0")), "",
             _("kpi_record_sub", v=f"{s.get('win_pct',0):.1f}")),
            (_("kpi_losing"), f"{s.get('losing_months',0)}<span style=\"color:var(--muted)\">/"
             f"{max(s.get('total_months',0),1)}</span>", "", _("kpi_losing_sub")),
        ]
    else:
        # Beat-the-close leads. It converges in tens of plays where win/loss
        # needs thousands, so on any record this site will realistically have
        # it is the only figure carrying real information — putting ROI first
        # would be leading with the number that means least.
        ci = s.get("roi_interval") or {}
        clv_n = s.get("clv_n", 0)
        sigma = s.get("clv_sigma")
        cards = [
            (_("kpi_clv"),
             f"{s.get('clv_beat_pct', 0):.0f}%" if clv_n else "—",
             cls_for(s.get("clv_beat_pct", 0) - 50) if clv_n else "",
             _("kpi_clv_sigma", v=f"{sigma:.1f}", n=clv_n)
             if clv_n and sigma is not None else _("kpi_clv_sub", n=clv_n)),
            (_("kpi_units"), u(units), cls_for(units), _("kpi_units_sub")),
            (_("kpi_roi"), pct(roi), cls_for(roi),
             _("kpi_roi_range", lo=pct(ci["lo"]), hi=pct(ci["hi"]))
             if ci.get("lo") is not None
             else _("kpi_roi_rec", v=f"{s.get('risked',0):.0f}")),
            (_("kpi_record"), esc(s.get("record", "0–0–0")), "",
             _("kpi_record_sub", v=f"{s.get('win_pct',0):.1f}")),
        ]
    return "".join(
        f'<div class="kpi"><div class="k">{k}</div>'
        f'<div class="v {c}">{v}</div><div class="s">{esc(sub)}</div></div>'
        for k, v, c, sub in cards
    )


def evidence_block(s: dict) -> str:
    """Why this page leads with the closing line instead of the profit.

    The argument is arithmetic and the arithmetic moves with the data, so it
    is rendered from the numbers rather than written into the page copy. A
    static sentence claiming the record proves something would become a lie
    the first time the sample changed.
    """
    ci = s.get("roi_interval") or {}
    clv_n, sigma = s.get("clv_n", 0), s.get("clv_sigma")
    needed, n = ci.get("needed"), ci.get("n", 0)

    # Left: what the profit column can and cannot support yet.
    if not n:
        profit_line = _("ev_profit_none")
    elif ci.get("lo") is None:
        profit_line = _("ev_profit_thin", n=n)
    elif needed is None:
        profit_line = _("ev_profit_losing", n=n)
    elif needed > 0:
        profit_line = _("ev_profit_needs", n=n, more=f"{needed:,}")
    else:
        profit_line = _("ev_profit_proven", n=n)

    # Right: what the closing line already supports.
    if not clv_n:
        clv_line = _("ev_clv_none")
    elif sigma is None or sigma < 2:
        clv_line = _("ev_clv_early", n=clv_n)
    else:
        clv_line = _("ev_clv_strong", n=clv_n, v=f"{sigma:.1f}")

    approx = (f'<div class="ev-note">{_("ev_approx")}</div>'
              if ci.get("approximate") and n else "")
    return f"""
      <div class="ev">
        <div class="ev-col">
          <div class="ev-k">{_("ev_by_profit")}</div>
          <div class="ev-n">{esc(f"{n:,}") if n else "&mdash;"}</div>
          <p>{profit_line}</p>
        </div>
        <div class="ev-col lead">
          <div class="ev-k">{_("ev_by_close")}</div>
          <div class="ev-n g">{esc(f"{clv_n:,}") if clv_n else "&mdash;"}</div>
          <p>{clv_line}</p>
        </div>
      </div>{approx}"""


# --------------------------------------------------------------------- chart
def month_chart(months: list[dict]) -> str:
    if not months:
        return ('<p style="padding:40px 0;text-align:center;color:var(--muted)">'
                f'{_("chart_empty")}</p>')
    def mlabel(m: dict) -> str:
        key = m.get("key") or ""
        try:
            return i18n.MONTHS_SHORT[LANG][int(key.split("-")[1]) - 1]
        except (IndexError, ValueError):
            return str(m.get("label", ""))

    peak = max((abs(m["units"]) for m in months), default=1.0) or 1.0
    up_px, down_px = 150.0, 66.0
    cols, described = [], []
    for m in months:
        val = m["units"]
        described.append(f"{mlabel(m)} {u(val)}")
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
            f'<div class="col" title="{esc(_("chart_tip", month=mlabel(m), year=m["year"], units=u(val), n=m["plays"]))}">'
            f'{body}<span class="mlab">{esc(mlabel(m))}</span></div>')
    label = _("chart_alt", v=", ".join(described))
    return (f'<div class="chart" role="img" aria-label="{esc(label)}">'
            f'<div class="bars">{"".join(cols)}</div></div>')


# -------------------------------------------------------------------- signup
def signup_form(button: str | None = None) -> str:
    button = button or _("signup_btn")
    if config.BEEHIIV_EMBED_URL:
        return (f'<iframe src="{esc(config.BEEHIIV_EMBED_URL)}" class="signup-embed" '
                f'title="{_("signup_title")}" scrolling="no" frameborder="0"></iframe>')
    return f"""<form class="form-row" data-signup>
      <input type="email" required placeholder="you@email.com" aria-label="{_("signup_aria")}">
      <button class="btn solid" type="submit">{esc(button)}</button>
    </form>
    <p class="form-msg" role="status"></p>"""


# ------------------------------------------------------- screen methodology
# Labels for the screen thresholds. The page renders straight from
# screen_config.py, so the rules shown to readers can never drift from the
# rules the scanner actually applies — a published methodology that quietly
# disagrees with the code is worse than none.
# (label key, comparator key, number format). Both label and comparator are
# i18n keys rather than English text, so the published methodology translates
# with the rest of the page while still coming from screen_config.py.
SCREEN_LABELS = {
    "min_pitcher_k_pct": ("sl_min_pitcher_k_pct", "cmp_at_least", "pct"),
    "min_vs_pa": ("sl_min_vs_pa", "cmp_at_least", "int"),
    "min_vs_k_pct": ("sl_min_vs_k_pct", "cmp_at_least", "pct"),
    "max_vs_avg": ("sl_max_vs_avg", "cmp_under", "three"),
    "max_vs_woba": ("sl_max_vs_woba", "cmp_under", "three"),
    "min_opp_k_per_game": ("sl_min_opp_k_per_game", "cmp_at_least", "two"),
    "line_min": ("sl_line_min", "", "one"),
    "line_max": ("sl_line_max", "", "one"),
    "worst_juice": ("sl_worst_juice", "cmp_no_worse", "odds"),
    "min_k_per_9": ("sl_min_k_per_9", "cmp_at_least", "one"),
    "max_bets_per_day": ("sl_max_bets_per_day", "cmp_at_most", "int"),
    "max_line": ("sl_max_line", "cmp_never", "one"),
    "banned_line": ("sl_banned_line", "cmp_never", "one"),
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
        label_key, cmp_key, kind = SCREEN_LABELS[key]
        label = _(label_key)
        comparator = _(cmp_key) if cmp_key else ""
        if value is None:
            rows.append(f"""<tr>
              <td class="strong" style="color:var(--muted)">{esc(label)}</td>
              <td style="color:var(--muted)">{_("rule_nolimit")}</td>
              <td class="m" style="color:var(--muted)">{_("rule_off")}</td></tr>""")
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
        return _("be_edge")
    if abs(need - 0.5) < 1e-9:
        return _("be_even")
    return _("be_profit")


# --------------------------------------------------------------- full slate
def _nickname(team: str | None) -> str:
    """'San Diego Padres' -> 'Padres'. Enough to name a side in a tight space."""
    parts = str(team or "").split()
    if not parts:
        return ""
    # Both Chicago and Boston end in "Sox", so the last word alone is ambiguous.
    if len(parts) > 1 and parts[-1].lower() == "sox":
        return " ".join(parts[-2:])
    return parts[-1]


def _record_line(rec: dict | None, at_home: bool) -> str:
    """'78–52 · 44–21 at home'. The venue split is the half that's relevant."""
    if not rec or (rec.get("w", 0) + rec.get("l", 0)) == 0:
        return ""
    overall = f"{rec['w']}&ndash;{rec['l']}"
    if at_home:
        w, l, label = rec.get("hw", 0), rec.get("hl", 0), _("at_home")
    else:
        w, l, label = rec.get("aw", 0), rec.get("al", 0), _("on_the_road")
    # An older stats file carries the overall record without the venue split.
    # Printing "0-0 on the road" beside a real record looks like the number is
    # broken; showing the overall record alone just looks shorter.
    if w + l == 0:
        return f'<div class="grec">{overall}</div>'
    return f'<div class="grec">{overall} &middot; {w}&ndash;{l} {label}</div>'


# Below this many career starts against a club, the split is noise wearing a
# number, and the card says so rather than letting it read as a trend.
THIN_VS_STARTS = 3


def _vs_line(vs: dict | None, opponent: str | None) -> str:
    if not vs:
        return ""
    who = _nickname(opponent) or _("them")
    starts = vs.get("starts") or 0
    # No starts but innings on the board means relief work — saying "0 GS"
    # reads like missing data rather than what it is.
    stint = f'{starts} {_("gs")} &middot; ' if starts else ""
    body = _("vs_body", team=esc(who), stint=stint,
             ip=f"{vs.get('innings', 0):.1f}", ipu=_("ip"),
             era=f"{vs.get('era', 0):.2f}", erau=_("era"))
    span = vs.get("span")
    tip = _("vs_tip", span=(_("span_season", v=span) if span else _("span_career")))
    if starts < THIN_VS_STARTS:
        return (f'<div class="gvs thin" title="{esc(_("vs_tip_thin", tip=tip))}">'
                f'{body} &middot; {_("vs_thin")}</div>')
    return f'<div class="gvs" title="{esc(tip)}">{body}</div>'


def _side(team, starter, era, prob, leading, rec=None, at_home=False,
          vs=None, opponent=None) -> str:
    sp = esc(starter or "TBA")
    if era is not None:
        sp += f' &middot; {era:.2f} {_("era")}'
    # One decimal, not zero: at 49.8 vs 50.2 a rounded pair both read "50%"
    # while the footer reports a lean, which looks like a contradiction.
    return f"""
        <div class="gside{' lead' if leading else ''}">
          <div class="tm">{_tdot(team)}{esc(team or '')}</div>
          <div class="pc">{prob*100:.1f}%</div>
        </div>
        {_record_line(rec, at_home)}
        <div class="gsp">{sp}</div>
        {_vs_line(vs, opponent)}"""


def _abbr(team: str | None) -> str:
    """MIL, CHC, NYY. Falls back to the nickname when a club isn't listed."""
    return TEAM_ABBR.get(_nickname(team).lower()) or _nickname(team).upper()[:3]


def _short_name(name: str | None) -> str:
    """'Freddy Peralta' -> 'F. Peralta'. A card has room for a surname."""
    parts = str(name or "").split()
    if len(parts) < 2:
        return parts[0] if parts else "TBA"
    return f"{parts[0][0]}. {' '.join(parts[1:])}"


def slate_rows(rows: list[dict]) -> str:
    """One card per game: both clubs, both numbers, the market's tick.

    Showing only our side of the number and abbreviating the clubs made the
    card shorter but cost the two things a reader actually compares — who is
    playing, and how far apart the two opinions are. Both sides are named in
    full and both percentages are printed; the bar carries the market's own
    number as a tick so the gap is visible without arithmetic.
    """
    if not rows:
        return f'<div class="empty-board">{_("empty_board")}</div>'
    out = []
    for r in rows:
        ph = r.get("home_win_prob") or 0.0
        pa = 1.0 - ph
        mkt_home = r.get("market_home_prob")
        gap = r.get("disagreement")
        suspect = bool(r.get("suspect"))
        home, away = r.get("home"), r.get("away")

        # The bar reads left-to-right as the away club's chance, so the
        # market's tick has to be expressed on that same side.
        tick = ("" if mkt_home is None else
                f'<div class="tick" style="left:{max(0.0, min(100.0, (1 - mkt_home) * 100)):.1f}%" '
                f'title="{_("market_tick")}"></div>')

        if mkt_home is None:
            foot_left = f'<span>{_("market_na")}</span>'
        else:
            # Name the club the market makes the favourite, rather than a bare
            # percentage the reader has to attach to a side themselves.
            fav, fav_pct = ((home, mkt_home) if mkt_home >= 0.5
                            else (away, 1 - mkt_home))
            foot_left = (f'<span>' + _("market_fav", pct=f"<b>{fav_pct * 100:.1f}%</b>",
                                        team=esc(_nickname(fav))) + '</span>')

        if gap is None:
            foot_right = ""
        elif suspect:
            foot_right = (f'<span class="flagged">'
                          f'{_("off_market", v=f"{abs(gap):.1f}")}</span>')
        elif abs(gap) < 1.0:
            # Under a point the two numbers are the same number wearing
            # different rounding. Calling that a lean would be noise.
            foot_right = f'<span>{_("in_line")}</span>'
        else:
            side = home if gap > 0 else away
            foot_right = ('<span class="lean">'
                          + _("lean_on", v=f"+{abs(gap):.1f}", team=esc(_nickname(side)))
                          + '</span>')

        when = esc(game_time(r.get("commence_time")) or "")
        # The left of the header already carries the start time. Repeating it
        # on the right for an ungraded game reads as a rendering fault, so the
        # right side says what state the game is in instead.
        final = (f'<span class="fin">{_("final", v=esc(r["final"]))}</span>'
                 if r.get("final") else
                 f'<span style="color:var(--muted)">{_("scheduled")}</span>')

        accent = team_color(home) or "var(--line-2)"
        out.append(f"""
        <div class="gcard{' flag' if suspect else ''}" style="--accent:{accent}">
          <div class="gcard-top">
            <span>{when}</span>
            {final}
          </div>
          <div class="gcard-body">
            {_side(away, r.get('away_starter'), r.get('away_starter_era'), pa,
                   pa > ph, r.get('away_record'), False,
                   r.get('away_vs_opp'), home)}
            <div class="gbar">
              <div class="seg on" style="left:0;width:{max(0.0, min(100.0, pa * 100)):.1f}%"></div>
              <div class="seg" style="left:{max(0.0, min(100.0, pa * 100)):.1f}%;right:0"></div>
              {tick}
            </div>
            {_side(home, r.get('home_starter'), r.get('home_starter_era'), ph,
                   ph >= pa, r.get('home_record'), True,
                   r.get('home_vs_opp'), away)}
            <div class="gfoot">
              {foot_left}
              {foot_right}
            </div>
          </div>
        </div>""")
    return "".join(out)


# The calibration plot is drawn on a fixed window so every row shares a scale
# and the dots line up down the page.
CALIB_LO, CALIB_HI = 25.0, 85.0


def _cpos(value: float) -> float:
    return max(0.0, min(100.0, (value - CALIB_LO) / (CALIB_HI - CALIB_LO) * 100))


def calibration_rows(rows: list[dict]) -> str:
    live = [r for r in rows if r.get("n")]
    if not live:
        return f'<div class="empty-board">{_("cal_empty")}</div>' 
    import math as _m
    out = []
    for r in live:
        gap, n = r["gap"], r["n"]
        said, actual = r["predicted"], r["actual"]
        # Within the noise band for this sample size, a gap means nothing.
        se = _m.sqrt(0.25 / n) * 100 * 1.96
        outside = abs(gap) > se
        verdict = (_("within_noise") if not outside else
                   (_("too_low") if gap > 0 else _("too_high")))
        band_l, band_r = _cpos(said - se), _cpos(said + se)
        label = (f"{r['lo']*100:.0f}%+" if r["hi"] > 1.0
                 else f"{r['lo']*100:.0f}–{r['hi']*100:.0f}%")
        out.append(f"""
        <div class="crow">
          <div class="cl">{label}</div>
          <div class="cn">{_("cal_games", n=n)}</div>
          <div class="ctrack" title="{_("cal_tip", a=f"{said:.1f}", b=f"{actual:.1f}")}">
            <div class="cband" style="left:{band_l:.1f}%;width:{max(0.0, band_r-band_l):.1f}%"></div>
            <div class="csaid" style="left:{_cpos(said):.1f}%"></div>
            <div class="cact{' out' if outside else ''}" style="left:{_cpos(actual):.1f}%"></div>
          </div>
          <div class="cverdict{' out' if outside else ''}">{esc(verdict)}<br>
            <span style="color:var(--muted)">{_("said_won", a=f"{said:.1f}", b=f"{actual:.1f}")}</span></div>
        </div>""")
    return "".join(out)


def brier_line(summary: dict) -> str:
    ours, theirs = summary.get("brier"), summary.get("market_brier")
    if ours is None:
        return _("brier_empty")
    text = _("brier_main", n=summary.get("graded", 0), v=f"{ours:.4f}")
    if theirs is not None:
        rel = ("rel_better" if ours < theirs
               else ("rel_worse" if ours > theirs else "rel_level"))
        text += _("brier_market", v=f"{theirs:.4f}",
                  n=summary.get("market_compared", 0), rel=_(rel))
    return text


# ----------------------------------------------------------- pitchers prop
# The bar strip stays anchored at zero. Zooming the axis would make small
# differences look big, which is the opposite of what this page argues.
PITCH_MAX_K = 14


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _strip(recent: list[dict], line: float) -> str:
    if not recent:
        return f'<div class="pb-nostrip">{_("no_starts")}</div>' 
    bars, ticks = [], []
    for i, start in enumerate(recent):
        k = start.get("strikeouts") or 0
        h = max(6.0, min(100.0, k / PITCH_MAX_K * 100))
        ago = len(recent) - i
        when = esc(start.get("date") or "")
        opp = esc(start.get("opponent") or "")
        bars.append(f'<div class="pb-bar{" hit" if k > line else ""}" '
                    f'style="height:{h:.1f}%" '
                    f'title="{_("pb_tip", when=when, opp=opp, k=k, ip=start.get("innings", 0))}"></div>')
        ticks.append(f"<span>{k}</span>")
    pos = max(0.0, min(100.0, line / PITCH_MAX_K * 100))
    return f"""
      <div class="pb-strip">
        <div class="pb-line" style="bottom:{pos:.1f}%"><span class="pb-linelab">{line:g}</span></div>
        {''.join(bars)}
      </div>
      <div class="pb-ticks">{''.join(ticks)}</div>"""


def pitcher_cards(rows: list[dict]) -> str:
    if not rows:
        return f'<div class="empty-board">{_("pitch_empty")}</div>' 
    out = []
    for r in rows:
        line = r.get("line") or 0
        proj = r.get("projection") or 0
        gap = r.get("gap")

        if r.get("suspect"):
            lean = (f'<span class="flagged" title="{_("pb_flagtip")}">'
                    f'{_("off_the_line", v=f"{abs(gap):.1f}")}</span>')
        elif gap is None or abs(gap) < 0.4:
            lean = f'<span>{_("in_line")}</span>'
        else:
            key = "over_the_line" if gap > 0 else "under_the_line"
            lean = f'<span class="lean">{_(key, v=f"{abs(gap):.1f}")}</span>' 

        actual = r.get("actual")
        if actual is None:
            status = f'<span>{_("rated")}</span>'
        else:
            went = _("over") if actual > line else _("under")
            status = f'<span class="fin">{_("final_k", n=actual, side=went)}</span>' 

        vs = r.get("vs_opp")
        vs_html = _vs_line(vs, r.get("opponent")) if vs else (
            f'<div class="gvs thin">'
            f'{_("never_faced", team=esc(_nickname(r.get("opponent"))))}</div>')

        rank = r.get("opp_k_rank")
        rank_txt = (" &middot; " + _("pb_rank", r=rank, ord=_ordinal(rank),
                                     n=r.get("opp_teams_ranked", 30))
                    if rank else "")
        opp_rate = r.get("opp_k_per_game")
        prices = []
        if r.get("over_odds") is not None:
            prices.append(f"o{om.format_american(r['over_odds'])}")
        if r.get("under_odds") is not None:
            prices.append(f"u{om.format_american(r['under_odds'])}")

        out.append(f"""
        <div class="pb-card{' flag' if r.get('suspect') else ''}"
             style="--accent:{team_color(r.get('opponent')) or 'var(--line-2)'}">
          <div class="pb-top">
            <span>{esc(r.get('team',''))} vs {esc(_nickname(r.get('opponent')))}
              &middot; {esc(game_time(r.get('commence_time')))}</span>
            {status}
          </div>
          <div class="pb-body">
            <div class="pb-name">{esc(r.get('name',''))}</div>
            <div class="pb-head">
              <div class="pb-num"><div class="k">{_("our_projection")}</div>
                <div class="v">{proj:.1f}<span class="unit">{_("k_unit")}</span></div></div>
              <div class="pb-num alt"><div class="k">{_("posted_line")}</div>
                <div class="v">{line:g}<span class="unit">{_("k_unit")}</span></div></div>
            </div>
            <div class="pb-striphead">
              <span>{_("last_n_starts", n=r.get('recent_n', 0))}</span>
              <span class="pb-rec"><b>{r.get('recent_over',0)}&ndash;{max(0,(r.get('recent_n',0)-r.get('recent_over',0)))}</b>
                {_("over_line", v=f"{line:g}")} &middot; {_("l5")} <b>{r.get('last5_over',0)}&ndash;{max(0,(r.get('last5_n',0)-r.get('last5_over',0)))}</b></span>
            </div>
            {_strip(r.get('recent') or [], line)}
            <div class="pb-rows">
              <div class="pb-row"><span>{_("season")}</span><b>{_season_line(r)}</b></div>
              <div class="pb-row"><span>{_("opp_ks", team=esc(_nickname(r.get('opponent'))))}</span>
                <b>{_("per_game", v=f"{opp_rate:.1f}") if opp_rate else '&mdash;'}{rank_txt}</b></div>
            </div>
            {vs_html}
            <div class="pb-foot">
              <span>{esc(' / '.join(prices)) or '&mdash;'}</span>
              {lean}
            </div>
          </div>
        </div>""")
    return "".join(out)


def _season_line(r: dict) -> str:
    bits = []
    if r.get("k_pct") is not None:
        bits.append(_("k_rate", v=f"{r['k_pct']*100:.1f}"))
    if r.get("k_per_9") is not None:
        bits.append(f"{r['k_per_9']:.1f} K/9")
    if r.get("era") is not None:
        bits.append(f"{r['era']:.2f} {_('era')}")
    return " &middot; ".join(bits) or "&mdash;"


def pitcher_accuracy(summary: dict) -> str:
    """How far off the projections have been, against the line's own miss."""
    mae, line_mae = summary.get("mae"), summary.get("line_mae")
    if mae is None:
        return _("pa_empty")
    n = summary.get("graded", 0)
    text = _("pa_main", n=n, noun=_("pa_noun_one" if n == 1 else "pa_noun_many"),
             mae=f"{mae:.2f}", lmae=f"{line_mae:.2f}")
    if line_mae is not None:
        text += _("pa_closer") if mae < line_mae else _("pa_line_closer")
    called = summary.get("called_right")
    if called is not None:
        text += _("pa_called", n=summary.get("calls", 0), v=f"{called:.1f}")
    return text


def pitcher_bucket_rows(summary: dict) -> str:
    buckets = [b for b in summary.get("buckets", []) if b.get("n")]
    if not buckets:
        return f'<div class="empty-board">{_("pb_empty")}</div>' 
    import math as _m
    out = []
    for b in buckets:
        n, pct_right = b["n"], b["pct"]
        se = _m.sqrt(0.25 / n) * 100 * 1.96
        noise = abs(pct_right - 50.0) <= se
        if noise:
            verdict = _("within_noise")
        else:
            verdict = _("better_coin") if pct_right > 50 else _("worse_coin")
        width = max(0.0, min(100.0, pct_right))
        out.append(f"""
        <div class="crow">
          <div class="cl">{esc(_(b["id"]) if b.get("id") else b.get("label", ""))}</div>
          <div class="cn">{_("n_starts", n=n, s=_pl(n))}</div>
          <div class="ctrack" title="{_("bucket_tip", a=b['right'], b=n)}">
            <div class="cband" style="left:{max(0.0,50-se):.1f}%;width:{min(100.0,2*se):.1f}%"></div>
            <div class="csaid" style="left:50%"></div>
            <div class="cact{'' if noise else ' out'}"
                 style="left:{width:.1f}%"></div>
          </div>
          <div class="cverdict{'' if noise else ' out'}">{esc(verdict)}<br>
            <span style="color:var(--muted)">{_("pct_right", v=f"{pct_right:.0f}")}</span></div>
        </div>""")
    return "".join(out)


# ------------------------------------------------------------ team colour
# One primary per club, used only for a 2px card edge and a small dot beside
# the name. Keyed on the last word of the feed's team name, which is what
# _nickname() already returns, so a name the feed spells differently simply
# falls through to the neutral default instead of breaking.
TEAM_COLOR = {
    "diamondbacks": "#A71930", "braves": "#CE1141", "orioles": "#DF4601",
    "red sox": "#BD3039", "cubs": "#0E3386", "white sox": "#C4CED4",
    "reds": "#C6011F", "guardians": "#00385D", "rockies": "#33006F",
    "tigers": "#0C2340", "astros": "#EB6E1F", "royals": "#004687",
    "angels": "#BA0021", "dodgers": "#005A9C", "marlins": "#00A3E0",
    "brewers": "#12284B", "twins": "#002B5C", "mets": "#FF5910",
    "yankees": "#1C2841", "athletics": "#003831", "phillies": "#E81828",
    "pirates": "#FDB827", "padres": "#2F241D", "giants": "#FD5A1E",
    "mariners": "#005C5C", "cardinals": "#C41E3A", "rays": "#8FBCE6",
    "rangers": "#003278", "jays": "#134A8E", "nationals": "#AB0003",
}


# Some clubs wear a colour that all but disappears against the card. Rather
# than hand-picking substitutes and getting it subtly wrong, every colour is
# moved away from the card until it clears a contrast floor; clubs already
# legible are returned untouched. Which way "away" points depends on the card,
# so the panel colour is read from the palette rather than written out again
# here — two copies of one colour is how the bar tick ended up white on a
# white card. On the slate palette three clubs move: the White Sox' silver,
# the Pirates' gold and the Rays' light blue.
def _panel_rgb() -> tuple[int, int, int]:
    css = (Path(__file__).resolve().parent / "base.css").read_text(encoding="utf-8")
    m = re.search(r":root\s*\{.*?--panel\s*:\s*(#[0-9A-Fa-f]{6})", css, re.S)
    value = m.group(1) if m else "#FFFFFF"
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


PANEL_RGB = _panel_rgb()
MIN_CONTRAST = 2.6


def _luminance(rgb) -> float:
    def channel(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    la, lb = _luminance(a), _luminance(b)
    lo, hi = sorted((la, lb))
    return (hi + 0.05) / (lo + 0.05)


def _legible(hex_color: str) -> str:
    """Move a club's colour away from the card until it is legible on it.

    Which way is "away" depends on the card. On a dark panel the colour is
    lifted toward white; on a white one it is pushed toward black. The earlier
    version only ever lifted, because it was written when the panel was
    #101317 — run against a white card it made the palest clubs paler still.

    Does not preserve hue exactly. Mixing toward black or white desaturates, so
    a club needing heavy mixing stops looking quite like itself; legibility
    wins. Against a white card three clubs move at all: the White Sox, the
    Pirates and the Rays.
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


# Three-letter codes, keyed the same way as TEAM_COLOR so both maps agree.
TEAM_ABBR = {
    "diamondbacks": "ARI", "braves": "ATL", "orioles": "BAL", "red sox": "BOS",
    "cubs": "CHC", "white sox": "CWS", "reds": "CIN", "guardians": "CLE",
    "rockies": "COL", "tigers": "DET", "astros": "HOU", "royals": "KC",
    "angels": "LAA", "dodgers": "LAD", "marlins": "MIA", "brewers": "MIL",
    "twins": "MIN", "mets": "NYM", "yankees": "NYY", "athletics": "ATH",
    "phillies": "PHI", "pirates": "PIT", "padres": "SD", "giants": "SF",
    "mariners": "SEA", "cardinals": "STL", "rays": "TB", "rangers": "TEX",
    "jays": "TOR", "nationals": "WSH",
}


def team_color(team: str | None) -> str | None:
    raw = TEAM_COLOR.get(_nickname(team).lower()) if team else None
    return _legible(raw) if raw else None


def _tdot(team: str | None) -> str:
    c = team_color(team)
    return f'<span class="tdot" style="--tc:{c}"></span>' if c else ""


def market_rows(row: dict) -> str:
    """The card's market block: one row per market this game actually has.

    Each row is the league's own name for the market, the best price with the
    book offering it, and the edge against the vig-free fair number. A total
    shows the market's line and says "market only" where the edge would be.

    Does not show a Craftypicks number for a total. Elo produces a win
    probability, not a run distribution; inventing a total here would be the
    one number on the page with nothing behind it.
    """
    short = row.get("league", "")
    out = []
    for market in ("h2h", "spreads", "totals"):
        m = (row.get("markets") or {}).get(market)
        if not m:
            continue
        label = _(leagues.market_label_key(short, market))

        point = m.get("point")
        if market == "totals":
            side = f'{om.format_point(point)} &middot; o'
            price = m["best_home"]["price"]
            book = m["best_home"]["book"]
        elif market == "spreads":
            side = f'{_nickname(row.get("home"))} {om.format_point(point)} '
            price = m["best_home"]["price"]
            book = m["best_home"]["book"]
        else:
            side = f'{_nickname(row.get("home"))} '
            price = m["best_home"]["price"]
            book = m["best_home"]["book"]

        if market == "totals":
            edge_cell = f'<span class="mk-note">{_("market_only")}</span>'
        else:
            edge = m.get("edge_home", 0.0)
            edge_cell = f'<span class="mk-edge {cls_for(edge)}">{pct(edge)}</span>'

        out.append(
            f'<div class="mk-row">'
            f'<span class="mk-label">{esc(label)}</span>'
            f'<span class="mk-line">{side}<b>{esc(om.format_american(price))}</b>'
            f' <span class="mk-book">{esc(book)}</span></span>'
            f'{edge_cell}</div>')
    return "".join(out)


def board_card(row: dict) -> str:
    """One game, priced, with the deep material behind a disclosure.

    The disclosure is a <details> rather than a card flip: a flipped card's
    back is exactly the footprint of its front, and the detail does not fit —
    a ten-row prototype needed its own scrollbar before books or props were
    added. <details> also stays findable by Ctrl+F and by search engines, and
    works with no JavaScript at all.

    Does not decide whether the game is worth betting. Every game on the
    board is rendered the same way; the edge column is what varies.
    """
    model = row.get("model") or {}
    tip = game_time(row.get("commence_time"))
    accent = team_color(row.get("home"))
    style = f' style="--accent:{accent}"' if accent else ""
    lg = leagues.LEAGUES.get(row.get("league") or "")
    league_tag = f"{esc(lg.label)} &middot; " if lg else ""

    def side(team: str, prob: float | None, leading: bool) -> str:
        pc = (f'<span class="pc">{prob * 100:.1f}<span class="pcs">%</span>'
              f'</span>') if prob is not None else ""
        return (f'<div class="gside{" lead" if leading else ""}">'
                f'<span class="tm">{_tdot(team)}{esc(team)}</span>{pc}</div>')

    hp = model.get("home_win_prob")
    ap = model.get("away_win_prob")
    lead_home = hp is not None and ap is not None and hp >= ap

    return f"""
      <article class="gcard"{style} id="g-{esc(row.get('event_id',''))}">
        <div class="gcard-top">
          <span>{league_tag}{esc(tip)}</span><span>{_("scheduled")}</span>
        </div>
        <div class="gcard-body">
          {side(row.get('away',''), ap, not lead_home and ap is not None)}
          {side(row.get('home',''), hp, lead_home)}
          <div class="mk">{market_rows(row)}</div>
          <details class="gmore">
            <summary>{_("card_more")}</summary>
            <div class="gmore-in">{_book_table(row)}</div>
          </details>
        </div>
      </article>"""


def _book_table(row: dict) -> str:
    """Every market's fair price, width and book count, for the disclosure.

    Does not list each individual book's price yet. That needs the raw quotes
    carried through into board.json, which the board plan deliberately left
    out until there is a page that shows them.
    """
    short = row.get("league", "")
    rows = []
    for market in ("h2h", "spreads", "totals"):
        m = (row.get("markets") or {}).get(market)
        if not m:
            continue
        rows.append(
            f"<tr><td>{esc(_(leagues.market_label_key(short, market)))}</td>"
            f"<td class=\"m\">"
            f"{esc(om.format_american(m['fair_price_home']))}</td>"
            f"<td class=\"m\">{m['width']}</td>"
            f"<td class=\"m\">{_('n_books', n=m['books'])}</td></tr>")
    return ('<table class="gtbl"><tbody>' + "".join(rows) + "</tbody></table>")


def board_cards(rows: list[dict], empty_key: str = "board_empty") -> str:
    """Every game on a board, or a line saying there are none.

    Does not group by league. A caller wanting per-league headings renders
    each league's rows in its own call, which keeps this function ignorant of
    page layout.
    """
    if not rows:
        return f'<p class="empty-board">{_(empty_key)}</p>'
    return '<div class="board">' + "".join(board_card(r) for r in rows) + "</div>"


def _self_test() -> None:
    row = {
        "event_id": "evt1", "league": "mlb",
        "commence_time": "2026-08-31T23:05:00Z",
        "home": "Milwaukee Brewers", "away": "Chicago Cubs",
        "model": {"home_win_prob": 0.556, "away_win_prob": 0.444},
        "markets": {
            "h2h": {"point": None, "side_a": "home", "fair_home": 0.548, "fair_away": 0.452,
                    "fair_price_home": -121, "fair_price_away": 121,
                    "best_home": {"book": "Caesars", "price": -125},
                    "best_away": {"book": "FanDuel", "price": 114},
                    "edge_home": 0.9, "edge_away": -2.1,
                    "books": 6, "width": 14},
            "spreads": {"point": -1.5, "side_a": "home", "fair_home": 0.41, "fair_away": 0.59,
                        "fair_price_home": 144, "fair_price_away": -144,
                        "best_home": {"book": "FanDuel", "price": 134},
                        "best_away": {"book": "BetMGM", "price": -155},
                        "edge_home": 2.2, "edge_away": -1.0,
                        "books": 5, "width": 20},
            "totals": {"point": 8.5, "side_a": "over", "fair_home": 0.503, "fair_away": 0.497,
                       "fair_price_home": -101, "fair_price_away": 101,
                       "best_home": {"book": "BetMGM", "price": -105},
                       "best_away": {"book": "Caesars", "price": -110},
                       "edge_home": 0.4, "edge_away": -0.8,
                       "books": 6, "width": 10, "model": None},
        },
    }

    html_out = board_card(row)

    # Both clubs are named at full strength. The card must not mark our side
    # by making the other one harder to read.
    assert row["home"] in html_out and row["away"] in html_out
    assert "--dim" not in html_out, \
        "--dim may not appear in a card; it is 3:1 and this is all content"

    # The league's own word for a spread, resolved through i18n.
    assert i18n.t("mkt_run_line", LANG) in html_out, "MLB says run line"
    assert i18n.t("mkt_spread", LANG) not in html_out, \
        "a baseball card must not say 'spread'"

    # A total carries the market's number and never one of ours.
    assert "8.5" in html_out
    assert i18n.t("market_only", LANG) in html_out, \
        "the total row must say it is market-only"

    # The disclosure is a details element, not a flip.
    assert "<details" in html_out and "<summary" in html_out
    assert "onclick" not in html_out, "the card needs no JavaScript"

    # The best price and the book offering it both appear.
    assert "Caesars" in html_out and "−125" in html_out, \
        "prices use a real minus sign"

    # A game with only a moneyline still renders, rather than raising on the
    # markets it does not have. Half the NCAAB board looks like this.
    thin = {**row, "markets": {"h2h": row["markets"]["h2h"]}}
    thin_html = board_card(thin)
    assert "8.5" not in thin_html

    # A game with no model has no win probability rather than a made-up one.
    unrated = {**row, "model": None}
    assert "55.6" not in board_cards([unrated])

    # An empty board says so instead of rendering nothing at all.
    assert i18n.t("board_empty", LANG) in board_cards([])

    print("render self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()

