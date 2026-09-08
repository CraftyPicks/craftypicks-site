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
          vs=None, opponent=None, wl=None) -> str:
    # No starter, no starter line. The old "TBA" was a hardcoded English
    # string — the only reader-facing word on a card not routed through _()
    # — and it is now reached by every Elo league, printing a pitcher slot on
    # a basketball card. slate_rows, the other caller, does not depend on the
    # line being present: .gsp is a margin-top only, so a baseball card whose
    # starter is not yet announced simply closes up. An ERA without a starter
    # cannot be labelled and goes with it.
    sp = f'<div class="gsp">{esc(starter)}' if starter else ""
    if sp:
        # Win-loss sits between the name and the ERA, the order every
        # scoreboard uses. It is display-only: a starter's record is mostly a
        # report on the lineup behind him, which is why the ERA follows it
        # immediately rather than the other way round.
        if wl and wl[0] is not None and wl[1] is not None:
            sp += f' &middot; <span class="gwl">{wl[0]}&ndash;{wl[1]}</span>'
        if era is not None:
            sp += f' &middot; {era:.2f} {_("era")}'
        sp += "</div>"
    # One decimal, not zero: at 49.8 vs 50.2 a rounded pair both read "50%"
    # while the footer reports a lean, which looks like a contradiction.
    # No probability means no model for this game yet — the club's name still
    # gets its slot, but the percentage is left off rather than faked as 0%.
    pc = f'<div class="pc">{prob*100:.1f}%</div>' if prob is not None else ""
    # The model's own EV used to print here. It is still computed and still
    # stored in board.json as ev_home / ev_away, because the record needs to
    # keep accumulating -- but it is not shown, and the reason is in the
    # numbers rather than in taste.
    #
    # On 165 graded games, backing the side the model preferred returned
    # +8.08% where it claimed +13.25% (n=72, se 13.21) on the games it
    # disagreed with the market by four points or more, and -3.03% where it
    # claimed +2.02% (n=93, se 10.45) on the rest. Both are indistinguishable
    # from zero. The win model is level with the market on Brier -- 0.2382
    # against 0.2402, CI [-0.0106, +0.0065] -- and "level with" does not
    # support an EV figure, which is a claim of being better.
    #
    # It also contradicted the page it sat on: the same run that printed
    # +17.9% on a card logged "0 qualifying edges, rejected -- EV below
    # 2.5%: 60". The market edge on the price rows stays, because it
    # compares a book against consensus and needs no model to be right.
    return f"""
        <div class="gside{' lead' if leading else ''}">
          <div class="tm">{_tdot(team)}{esc(team or '')}</div>
          {pc}
        </div>
        {_record_line(rec, at_home)}
        {sp}
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


def _roster_block(row: dict, who: str, team: str) -> str:
    """PA, K%, AVG, xwOBA against tonight's lineup.

    First in the panel, above the vs-opponent block, because it is the
    wider sample: a whole roster's career against this arm, rather than the
    two or three starts he has made against the club.

    The prose that used to sit under this grid is gone -- twice asked for
    and twice justified, which is one more time than a caveat gets. What it
    was protecting is real: xwOBA here often rests on twenty-odd plate
    appearances and a three-decimal number reads as precision when it is
    noise. So the protection stays, as DATA rather than as a paragraph --
    the xwOBA denominator prints as a mono caption, and a thin sample still
    dims the whole grid. A reader who wants to know the sample size can
    read the PA cell, which is the first thing on the row.
    """
    rs = row.get("vs_roster")
    if not rs or not rs.get("pa"):
        return ""

    def three(v):
        return f"{v:.3f}".lstrip("0") if v is not None else "&mdash;"

    k_txt = f'{rs["k_pct"] * 100:.1f}%' if rs.get("k_pct") is not None else "&mdash;"
    # The one thing the grid cannot say for itself: xwOBA's denominator is
    # not the PA cell beside it. StatsAPI gives the career line, Savant the
    # Statcast rows, and the two rarely cover the same plate appearances.
    cap = ""
    if rs.get("xwoba") is not None:
        cap = (f'<div class="mxcap">{_("rs_xwoba")} &middot; '
               f'{esc(rs.get("xwoba_span") or "")} &middot; '
               f'{format(rs.get("xwoba_pa") or 0, ",")} {_("rs_pa")}</div>')

    thin = ' dim' if rs.get("thin") else ''
    return (f'<div class="mxh">{_("rs_head", who=who, team=team)}</div>'
            f'<div class="mxg four{thin}">'
            f'<div><span>{_("rs_pa")}</span><b>{format(rs["pa"], ",")}</b></div>'
            f'<div><span>{_("rs_kpct")}</span><b>{k_txt}</b></div>'
            f'<div><span>{_("rs_avg")}</span><b>{three(rs.get("avg"))}</b></div>'
            f'<div><span>{_("rs_xwoba")}</span><b>{three(rs.get("xwoba"))}</b></div>'
            f'</div>{cap}')


def _matchup_inner(row: dict) -> str:
    """The prop card's collapsible detail.

    Three things, in this order: how this starter has done against this
    opponent, how that opponent strikes out against the hand he throws with,
    and the verdict. Only the applicable hand is shown -- printing both
    columns made the reader do the selection the card already knows how to do.
    """
    who = esc((row.get("name") or "").split()[-1] or "?")
    team = esc(_nickname(row.get("opponent")))
    parts = []

    # The roster line leads: it rests on hundreds of plate appearances where
    # the vs-opponent line below often rests on two starts.
    block = _roster_block(row, who, team)
    if block:
        parts.append(block)

    vs = row.get("vs_opp")
    if vs and vs.get("innings"):
        k9 = vs["strikeouts"] * 9 / vs["innings"]
        parts.append(
            f'<div class="mxh">'
            f'{_("mx_hist", who=who, team=team, span=esc(vs.get("span", "")))}'
            f'</div>'
            f'<div class="mxg">'
            f'<div><span>{_("mx_starts")}</span><b>{vs["starts"]}</b></div>'
            f'<div><span>{_("mx_innings")}</span><b>{vs["innings"]:g}</b></div>'
            f'<div><span>{_("mx_k")}</span><b>{vs["strikeouts"]}</b></div>'
            f'<div><span>{_("mx_k9")}</span><b>{k9:.1f}</b></div>'
            f'<div><span>{_("mx_era")}</span><b>{vs["era"]:.2f}</b></div>'
            f'</div>')
        # No sentence restating K/9 against them versus K/9 all season --
        # both numbers are already in the grid above, one of them twice.
        # A thin sample dims the grid instead of being narrated.
    else:
        parts.append(f'<div class="mxh">{_("mx_never", who=who, team=team)}</div>')

    split = row.get("opp_split")
    hand = row.get("hand") or ""
    if split and hand:
        row_label = _("mx_vs_l") if hand == "L" else _("mx_vs_r")
        rank = split.get("rank")
        of = split.get("of")
        # Every value is formatted before it enters the f-string. Python 3.11
        # cannot reuse the outer quote character inside an f-string
        # expression, so a nested f'{split["pa"]:,}' is a syntax error on the
        # runner even though it parses on 3.12.
        rank_cell = (_("pb_rank", r=rank, ord=_ordinal(rank), n=of)
                     if rank and of else "")
        pa_txt = format(split["pa"], ",")
        pct_txt = f'{split["k_pct"]:.1f}'
        mean_txt = f'{split.get("league_mean") or 0.0:.1f}'
        # The paragraph that used to explain which hand applies, and how the
        # club's overall rank compares with its rank against that hand, is
        # gone. The row is already labelled "vs right-handers", the rank is
        # already in the row, and the verdict chip below already prints the
        # gap against the league. It was three ways of saying one number.
        parts.append(
            f'<div class="mxh">{_("mx_how", team=team)}</div>'
            f'<table class="mxt">'
            f'<tr class="on"><th>{row_label}</th>'
            f'<td class="n">{pct_txt}%</td>'
            f'<td class="r">{rank_cell}</td>'
            f'<td class="p">{_("mx_pa", n=pa_txt)}</td></tr>'
            f'<tr class="avg"><th>{_("mx_league")}</th>'
            f'<td class="n">{mean_txt}%</td>'
            f'<td class="r"></td><td class="p"></td></tr>'
            f'</table>')

    verdict = row.get("matchup") or "neutral"
    delta = ""
    if split and split.get("league_mean") is not None:
        gap = split["k_pct"] - split["league_mean"]
        delta = f'<span class="vd">{_("mx_delta", v=f"{gap:+.1f}")}</span>'
    return (f'<div class="mxb">{"".join(parts)}</div>'
            f'<div class="verdict {MX_CLASS[verdict]}">'
            f'{_(MX_LABEL[verdict])}{delta}</div>')


def pitcher_cards(rows: list[dict]) -> str:
    if not rows:
        return f'<div class="empty-board">{_("pitch_empty")}</div>' 
    out = []
    for r in rows:
        # A starter with no posted line is the normal case now: the board is
        # built from StatsAPI every morning and prices are attached only on
        # the mornings props were bought. `line` therefore has to stay None
        # here rather than collapsing to 0, which would print a real-looking
        # "0.0" and score every projection as an over.
        line = r.get("line")
        proj = r.get("projection") or 0
        gap = r.get("gap")
        reference = r.get("reference")
        if reference is None:
            reference = line if line is not None else proj

        if line is None:
            lean = ""
        elif r.get("suspect"):
            lean = (f'<span class="flagged" title="{_("pb_flagtip")}">'
                    f'{_("off_the_line", v=f"{abs(gap):.1f}")}</span>')
        elif gap is None or abs(gap) < 0.4:
            lean = f'<span>{_("in_line")}</span>'
        else:
            key = "over_the_line" if gap > 0 else "under_the_line"
            lean = f'<span class="lean">{_(key, v=f"{abs(gap):.1f}")}</span>' 

        actual = r.get("actual")
        if actual is None:
            status_txt = _("rated")
        else:
            went = _("over") if actual > reference else _("under")
            status_txt = _("final_k", n=actual, side=went)


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

        # The canvas card, applied to a prop. Same five lines as a game:
        # who, one number, a bar with the market's own number ticked onto it,
        # what the market says and the size of the disagreement.
        #
        # The bar is scaled to twice the posted line, so the line always sits
        # at the halfway mark and the fill reads directly as "how far past
        # it we are". Scaling to the projection instead would move the tick
        # from card to card and make fifteen cards incomparable, which is the
        # whole thing the canvas layout is for.
        span = max(reference * 2.0, proj * 1.15, 1.0)
        fill = max(0.0, min(100.0, proj / span * 100))
        # No posted line, no tick. There is nothing on the market to mark,
        # and a tick sitting on our own number would draw the projection
        # twice and read as agreement with a price nobody offered.
        tick = (max(0.0, min(100.0, line / span * 100))
                if line is not None else None)
        if line is None:
            edge = ""
        elif gap is None or abs(gap) < 0.4:
            edge = f'<span class="ge none">{_("cv_noedge")}</span>'
        elif gap > 0:
            edge = (f'<span class="ge up">'
                    f'{_("cv_edge", v=f"+{abs(gap):.1f}")}</span>')
        else:
            edge = (f'<span class="ge down">'
                    f'{_("cv_fade", v=f"&minus;{abs(gap):.1f}")}</span>')

        tick_html = (f'<i class="cv-tick" style="left:{tick:.1f}%"></i>'
                     if tick is not None else "")
        foot_left = (f'{_("posted_line")} {line:g}' if line is not None
                     else _("cv_noline"))

        # The strip, the season rows and the prices come off the face and go
        # behind the disclosure, where the game card put its price rows.
        price_sec = (
            f'<section class="pk"><h4>{_("pnl_prices")}</h4>'
            f'<div class="pb-foot"><span>{esc(" / ".join(prices)) or "&mdash;"}</span>'
            f'{lean}</div></section>') if line is not None else ""
        # The record label names whatever the strip is drawn against -- the
        # posted line when there is one, our own number when there is not.
        over_label = (_("over_line", v=f"{line:g}") if line is not None
                      else _("cv_clears", v=f"{proj:.1f}"))
        inner = (
            price_sec +
            f'<section class="pk"><h4>{_("last_n_starts", n=r.get("recent_n", 0))}</h4>'
            f'<div class="pb-striphead"><span></span>'
            f'<span class="pb-rec"><b>{r.get("recent_over",0)}&ndash;'
            f'{max(0,(r.get("recent_n",0)-r.get("recent_over",0)))}</b> '
            f'{over_label} &middot; {_("l5")} '
            f'<b>{r.get("last5_over",0)}&ndash;'
            f'{max(0,(r.get("last5_n",0)-r.get("last5_over",0)))}</b>'
            f'</span></div>'
            f'{_strip(r.get("recent") or [], reference)}</section>'
            f'<section class="pk"><h4>{_("season")}</h4>'
            f'<div class="pb-rows">'
            f'<div class="pb-row"><span>{_("season")}</span><b>{_season_line(r)}</b></div>'
            f'<div class="pb-row"><span>'
            f'{_("opp_ks", team=esc(_nickname(r.get("opponent"))))}</span>'
            f'<b>{_("per_game", v=f"{opp_rate:.1f}") if opp_rate else "&mdash;"}'
            f'{rank_txt}</b></div></div></section>')

        out.append(f"""
        <div class="pb-card{' flag' if r.get('suspect') else ''}"
             style="--accent:{team_color(r.get('opponent')) or 'var(--line-2)'}">
          <div class="pb-body">
            <div class="cv-head">
              <h3 class="cv-tm">{esc(r.get('name',''))}</h3>
              <span class="cv-time">{esc(game_time(r.get('commence_time')))}</span>
            </div>
            <div class="cv-sub">{esc(r.get('team',''))} vs {esc(_nickname(r.get('opponent')))}
              &middot; {status_txt}</div>
            <div class="cv-row">
              <span class="cv-lab">{_("our_projection")}</span>
              <span class="cv-pct">{proj:.1f}<span class="cv-u">{_("k_unit")}</span></span>
            </div>
            <div class="cv-bar"><i class="cv-fill" style="width:{fill:.1f}%"></i>
              {tick_html}</div>
            <div class="cv-foot">
              <span class="gm">{foot_left}</span>{edge}
            </div>
            <details class="gmore" data-close="{_("close")}">
              <summary>{_("cv_prop_detail")}</summary>
              <div class="gmore-in"><div class="pnl">{inner}
                {_matchup_inner(r)}</div></div>
            </details>
          </div>
        </div>""")
    return "".join(out)


def _wl_tag(r: dict) -> str:
    """A starter's win-loss beside his name, the way a scoreboard prints it.

    Display-only. Cleveland's Bibee is 5-14 with a 3.88 ERA, which is the
    whole reason this number never reaches the projection.
    """
    w, l = r.get("w"), r.get("l")
    if w is None or l is None:
        return ""
    return f' <span class="pb-wl">{w}&ndash;{l}</span>'


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


def _prob_bar(model: dict | None) -> str:
    """The two numbers as one bar, with the market's own number as a tick.

    The bar fills left to right with the away club's chance, so the tick sits
    at 1 - market_home_prob. Printing the two percentages alone makes a reader
    do the subtraction; the distance between fill and tick is the disagreement
    without arithmetic.

    Does not scale the tick's prominence by how large the gap is. A two-point
    disagreement and a ten-point one are drawn identically, because the bar is
    a measurement and not an argument.

    Returns only the bar, not its caption — see _prob_foot() below. The two
    used to come back as one string that board_card rendered between the away
    and home clubs, which put the caption directly above the home club's name
    and made it read as that club's label rather than a caption on the bar.
    Two functions (instead of one returning a tuple) keep each call site
    reading as plain HTML-in, HTML-out, matching every other renderer here.
    board_card now places _prob_bar between the clubs and _prob_foot after
    both of them, which is the slot .gfoot's CSS (border-top, nothing below)
    was built for — the same slot slate_rows already uses.
    """
    if not model:
        return ""
    away = model.get("away_win_prob")
    if away is None:
        return ""
    fill = max(0.0, min(100.0, away * 100))

    market_home = model.get("market_home_prob")
    tick = ""
    if market_home is not None:
        at = max(0.0, min(100.0, (1.0 - market_home) * 100))
        tick = (f'<div class="tick" style="left:{at:.1f}%" '
                f'title="{_("market_tick")}"></div>')

    return (f'<div class="gbar"><div class="seg on" '
            f'style="width:{fill:.1f}%"></div>{tick}</div>')


def _prob_foot(model: dict | None) -> str:
    """The bar's caption: how far the model and market disagree.

    Companion to _prob_bar() — see that docstring for why the bar and its
    caption are returned separately. Renders after both clubs.
    """
    if not model:
        return ""
    if model.get("away_win_prob") is None:
        return ""
    gap = model.get("disagreement")
    if gap is None:
        return ""
    if abs(gap) < 1.0:
        # Under a point the two numbers are the same number wearing different
        # rounding, and calling that a disagreement would cry wolf.
        return f'<div class="gfoot"><span>{_("agree_market")}</span></div>'
    cls = " flagged" if model.get("suspect") else ""
    return (f'<div class="gfoot"><span class="lean{cls}">'
            f'{_("off_market", v=f"{abs(gap):.1f}")}</span></div>')


def _cv_edge(model: dict) -> str:
    """The card's one verdict, bottom right.

    Three states, because the canvas card has three: an edge worth naming,
    an edge pointing the other way, and nothing. Printing "+0.4 EDGE" on a
    game we agree with the market about is the kind of number that teaches a
    reader to stop believing the ones that matter.
    """
    gap = model.get("disagreement")
    if gap is None:
        return f'<span class="ge none">{_("cv_noedge")}</span>'
    if abs(gap) < 1.0:
        return f'<span class="ge none">{_("cv_noedge")}</span>'
    v = f"{abs(gap):.0f}" if abs(gap) >= 10 else f"{abs(gap):.1f}"
    if gap > 0:
        return f'<span class="ge up">{_("cv_edge", v="+" + v)}</span>'
    return f'<span class="ge down">{_("cv_fade", v="&minus;" + v)}</span>'


def board_card(row: dict) -> str:
    """One game, priced, with everything else behind a disclosure.

    Rebuilt to the design canvas's card, which is a deliberately thin thing:
    the matchup, ONE probability -- the side we favour -- a bar with the
    market's own number ticked onto it, what the market says, and the size of
    the disagreement. Five lines.

    Clubs are named by nickname -- "Phillies @ Nationals", not "Philadelphia
    Phillies @ Washington Nationals". At 20px the full names wrap to two
    lines on every card and the matchup stops being one object.

    What used to sit on the face of this card and now sits inside it: both
    clubs' records, both starters, the head-to-head strip, and the three
    market price rows. None of that is gone; it is one tap away. The point of
    the canvas card is that a reader scanning fifteen games should be
    comparing fifteen of the same number, not reading fifteen paragraphs.

    The disclosure is a <details> rather than a card flip: a flipped card's
    back is exactly the footprint of its front, and the detail does not fit.
    <details> also stays findable by Ctrl+F and works with no JavaScript.
    """
    model = row.get("model") or {}
    tip = game_time(row.get("commence_time"))
    accent = team_color(row.get("home"))
    style = f' style="--accent:{accent}"' if accent else ""

    hp = model.get("home_win_prob")
    ap = model.get("away_win_prob")
    away, home = row.get("away", ""), row.get("home", "")

    if hp is None or ap is None:
        body = f'<div class="cv-none">{_("not_rated")}</div>'
    else:
        # One side, and it is ours -- the club our number likes. A card that
        # printed both made the reader do the comparison the card had already
        # done.
        lead_home = hp >= ap
        who = home if lead_home else away
        ours = hp if lead_home else ap
        mkt = model.get("market_home_prob")
        if mkt is not None and not lead_home:
            mkt = 1.0 - mkt
        market_txt = (_("cv_market", v=f"{mkt * 100:.0f}%")
                      if mkt is not None else "")
        fill = max(0.0, min(100.0, ours * 100))
        tick = (f'<i class="cv-tick" style="left:{max(0.0, min(100.0, mkt * 100)):.1f}%"></i>'
                if mkt is not None else "")
        body = f"""
          <div class="cv-row">
            <span class="cv-lab">{_("cv_winprob", who=esc(_abbr(who)))}</span>
            <span class="cv-pct">{ours * 100:.0f}%</span>
          </div>
          <div class="cv-bar"><i class="cv-fill" style="width:{fill:.1f}%"></i>{tick}</div>
          <div class="cv-foot">
            <span class="gm">{market_txt}</span>{_cv_edge(model)}
          </div>"""

    return f"""
      <article class="gcard"{style} id="g-{esc(row.get('event_id',''))}">
        <div class="gcard-body">
          <div class="cv-head">
            <h3 class="cv-tm">{esc(_nickname(away))} <span>@</span> {esc(_nickname(home))}</h3>
            <span class="cv-time">{esc(tip)}</span>
          </div>
          {body}
          {_disclosure(row)}
        </div>
      </article>"""


# Division rivals meet thirteen times a season. Listing every meeting buries
# the starters and the props underneath it, so the panel shows the most recent
# few and counts the rest.
SERIES_SHOWN = 5

MX_LABEL = {"favourable": "mx_favourable", "tough": "mx_tough",
            "neutral": "mx_neutral"}
MX_CLASS = {"favourable": "good", "tough": "bad", "neutral": ""}

# Tonight's strikeout props, indexed by event id. Module-level for the same
# reason LANG is: build.py sets it once before rendering, and threading a
# props argument down through board_cards -> board_card -> panel would put
# baseball's vocabulary into a signature every league has to use.
_PROPS: dict[str, list[dict]] = {}


def set_props(rows) -> None:
    """Hand render the day's prop rows. Call before drawing any board."""
    global _PROPS
    index: dict[str, list[dict]] = {}
    for r in rows or []:
        eid = r.get("event_id")
        if eid:
            index.setdefault(eid, []).append(r)
    _PROPS = index


def _city(full_name: str) -> str:
    """'San Diego Padres' -> 'San Diego'. A venue should read as a place."""
    nick = _nickname(full_name)
    if nick and full_name.endswith(nick):
        return full_name[:-len(nick)].strip()
    return full_name


def _md(iso_date: str) -> str:
    """'2026-06-08' -> 'Jun 8', in the reader's language."""
    try:
        _y, month, day = (int(part) for part in iso_date.split("-"))
    except (ValueError, AttributeError):
        return iso_date or ""
    return f"{i18n.MONTHS[LANG][month - 1][:3]} {day}"


def _streak_cell(code: str) -> str:
    """'W3' with its meaning spelled out underneath."""
    if not code or len(code) < 2 or not code[1:].isdigit():
        return "&mdash;"
    n = int(code[1:])
    won = code.startswith("W")
    if n == 1:
        words = _("pnl_won_last") if won else _("pnl_lost_last")
    else:
        words = _("pnl_won_n", n=n) if won else _("pnl_lost_n", n=n)
    return (f'<b class="{"good" if won else "bad"}">{esc(code)}</b>'
            f'<i>{words}</i>')


def _form_block(row: dict, detail: dict) -> str:
    """Records, last ten and streak, both clubs side by side.

    Falls back to the bare records when there is no form yet. That fallback
    is load-bearing: the canvas card took the records off its face, so if
    this block returned nothing without form data the records would not
    appear anywhere on the site at all -- which is exactly what happened,
    and what the fixture at the bottom of this file now catches.
    """
    home, away = detail.get("home_form"), detail.get("away_form")
    if not home or not away:
        hr, ar = detail.get("home_record"), detail.get("away_record")
        if not hr or not ar:
            return ""
        rows = [(_("pnl_record"), f'{ar["w"]}&ndash;{ar["l"]}',
                                  f'{hr["w"]}&ndash;{hr["l"]}')]
    else:
        rows = [
            (_("pnl_record"), f'{away["w"]}&ndash;{away["l"]}',
                              f'{home["w"]}&ndash;{home["l"]}'),
            (_("pnl_last10"), f'{away["l10_w"]}&ndash;{away["l10_l"]}',
                              f'{home["l10_w"]}&ndash;{home["l10_l"]}'),
            (_("pnl_streak"), _streak_cell(away.get("streak", "")),
                              _streak_cell(home.get("streak", ""))),
        ]
    body = "".join(f"<tr><th>{lab}</th><td>{a}</td><td>{h}</td></tr>"
                   for lab, a, h in rows)
    return (f'<section class="pk"><h4>{_("pnl_form")}</h4>'
            f'<table class="pkt fm">'
            f'<tr class="hd"><th></th>'
            f'<td>{esc(_nickname(row.get("away")))}</td>'
            f'<td>{esc(_nickname(row.get("home")))}</td></tr>'
            f'{body}</table></section>')


def _h2h_block(row: dict, detail: dict) -> str:
    """The season series. Club names throughout -- slate.py converts
    StatsAPI's ids before they reach here, so this draws all four leagues
    identically."""
    games = detail.get("series") or []
    home, away = row.get("home"), row.get("away")
    home_nick, away_nick = _nickname(home), _nickname(away)
    head = f'<section class="pk"><h4>{_("pnl_h2h")}</h4>'
    if not games or not home or not away:
        return head + f'<p class="pnl-note">{_("pnl_h2h_none")}</p></section>'

    wins = {home: 0, away: 0}
    for g in games:
        winner = g["away"] if g["away_runs"] > g["home_runs"] else g["home"]
        if winner in wins:
            wins[winner] += 1
    aw, hw = wins[away], wins[home]
    if aw > hw:
        lead = _("pnl_h2h_lead", team=esc(away_nick), w=aw, l=hw)
    elif hw > aw:
        lead = _("pnl_h2h_lead", team=esc(home_nick), w=hw, l=aw)
    else:
        lead = _("pnl_h2h_even", w=aw, l=hw)

    nick = {home: home_nick, away: away_nick}
    place = {home: _city(home), away: _city(away)}
    shown = games[-SERIES_SHOWN:]
    lines = []
    hidden = len(games) - len(shown)
    if hidden:
        lines.append(f'<div class="h2more">'
                     f'{_("pnl_h2h_more", n=hidden, s=_pl(hidden))}</div>')
    for g in shown:
        winner = g["away"] if g["away_runs"] > g["home_runs"] else g["home"]
        hi = max(g["away_runs"], g["home_runs"])
        lo = min(g["away_runs"], g["home_runs"])
        lines.append(
            f'<div class="h2g"><span class="h2d">{esc(_md(g["date"]))}</span>'
            f'<span class="h2s"><b>{esc(nick.get(winner, "?"))}</b> '
            f'{hi}&ndash;{lo}</span>'
            f'<span class="h2w">'
            f'{_("pnl_h2h_at", place=esc(place.get(g["home"], "?")))}'
            f'</span></div>')
    return head + f'<p class="pnl-note">{lead}</p>' + "".join(lines) + "</section>"


# The comparison table's rows, in the reference's order, with which
# direction is better. W-L carries no direction on purpose: a starter's
# record is mostly a report on the lineup behind him, which is already why
# it sits out of the projection.
SP_ROWS = (
    ("sp_wl",   "wl",      None),
    ("sp_era",  "era",     "low"),
    ("sp_whip", "whip",    "low"),
    ("sp_ip",   "innings", "high"),
    ("sp_h",    "h",       "low"),
    ("sp_k",    "k",       "high"),
    ("sp_bb",   "bb",      "low"),
    ("sp_hr",   "hr",      "low"),
)


def _sp_cell(sp: dict, key: str) -> str:
    """One number, formatted the way its own stat is normally written."""
    if key == "wl":
        w, l = sp.get("w"), sp.get("l")
        return f"{w}&ndash;{l}" if w is not None and l is not None else "&mdash;"
    v = sp.get(key)
    if v is None:
        return "&mdash;"
    if key in ("era", "whip"):
        return f"{v:.2f}"
    if key == "innings":
        return f"{v:.1f}"
    return f"{int(v)}"


def _sp_table(row: dict, detail: dict) -> str:
    """Two starters, the label down the middle.

    The centre column is what makes it readable. Two stat blocks side by
    side make a reader hunt for which number pairs with which; a shared
    label removes the hunt, which is why every scoreboard that shows this
    comparison draws it the same way.
    """
    away, home = detail.get("away_sp") or {}, detail.get("home_sp") or {}
    if not any(v is not None for v in away.values()) and \
       not any(v is not None for v in home.values()):
        return ""
    body = []
    for label, key, better in SP_ROWS:
        a, h = _sp_cell(away, key), _sp_cell(home, key)
        acls = hcls = ""
        av, hv = away.get(key), home.get(key)
        if better and av is not None and hv is not None and av != hv:
            wins_away = (av < hv) if better == "low" else (av > hv)
            acls, hcls = ("on", "") if wins_away else ("", "on")
        body.append(f'<tr><td class="spv {acls}">{a}</td>'
                    f'<th>{_(label)}</th>'
                    f'<td class="spv {hcls}">{h}</td></tr>')
    return (f'<table class="sptbl">'
            f'<tr class="hd"><td>{esc(_abbr(row.get("away")))}</td>'
            f'<th></th><td>{esc(_abbr(row.get("home")))}</td></tr>'
            f'{"".join(body)}</table>')


def _starters_block(row: dict, detail: dict) -> str:
    out = []
    for which, other in (("away", "home"), ("home", "away")):
        name = detail.get(f"{which}_starter")
        if not name:
            continue
        era = detail.get(f"{which}_starter_era")
        opp = _nickname(row.get(other))
        vs = detail.get(f"{which}_vs_opp")
        if vs and vs.get("innings"):
            k9 = vs["strikeouts"] * 9 / vs["innings"]
            line = _("pnl_vs_line", n=vs["starts"], s=_pl(vs["starts"]),
                     team=esc(opp), ip=f'{vs["innings"]:g}',
                     k=vs["strikeouts"], k9=f"{k9:.1f}",
                     era=f'{vs["era"]:.2f}')
        else:
            line = _("pnl_vs_never", team=esc(opp), span="2025&ndash;2026")
        head = esc(name) + (f" &middot; {era:.2f} ERA" if era else "")
        out.append(f'<div class="pst"><div class="pst-n">{head}</div>'
                   f'<div class="pst-v">{line}</div></div>')
    table = _sp_table(row, detail)
    if not out and not table:
        return ""
    return (f'<section class="pk"><h4>{_("sp_head")}</h4>'
            + table + "".join(out) + "</section>")


def _lineup_table(bats, team: str, who: str) -> str:
    """One club's hitters against the other club's starter, career.

    A hitter with no history keeps his row, every figure a dash. That is
    what the reference does and it is the right call twice over: "has never
    faced him" is information, and dropping those rows would silently
    shorten one club's table against the other's, which reads as one lineup
    being better documented rather than as one pitcher being newer to it.
    """
    if not bats:
        return ""
    rows = []
    for b in bats:
        pa = b.get("pa")
        if not pa:
            cells = ('<td class="lz">&mdash;</td>' * 5)
        else:
            avg = b.get("avg")
            cells = (
                f'<td>{b.get("h", 0)}&ndash;{b.get("ab", 0)}</td>'
                f'<td>{b.get("hr") if b.get("hr") is not None else "&mdash;"}</td>'
                f'<td>{b.get("rbi") if b.get("rbi") is not None else "&mdash;"}</td>'
                f'<td>{b.get("k") if b.get("k") is not None else "&mdash;"}</td>'
                f'<td class="lav">{f"{avg:.3f}".lstrip("0") if avg is not None else "&mdash;"}</td>')
        rows.append(f'<tr><th>{esc(_short_name(b.get("name")))}'
                    f'<span class="ppos">{esc(b.get("position", ""))}</span>'
                    f'</th>{cells}</tr>')
    return (f'<section class="pk">'
            f'<h4>{_("lu_head", team=esc(_nickname(team)), who=esc(_short_name(who)))}</h4>'
            f'<div class="sscroll"><table class="lutbl">'
            f'<tr class="hd"><th>{_("lu_hitters")}</th>'
            f'<td>{_("lu_hab")}</td><td>{_("lu_hr")}</td>'
            f'<td>{_("lu_rbi")}</td><td>{_("lu_k")}</td>'
            f'<td>{_("lu_avg")}</td></tr>'
            f'{"".join(rows)}</table></div>'
            f'<p class="pnl-note">{_("lu_note")}</p></section>')


def _lineups_block(row: dict, detail: dict) -> str:
    """Both clubs' tables, away first, matching the card's own order."""
    out = []
    for which, other in (("away", "home"), ("home", "away")):
        out.append(_lineup_table(detail.get(f"{which}_bats"),
                                 row.get(which),
                                 detail.get(f"{other}_starter") or "?"))
    return "".join(out)


def _props_block(row: dict) -> str:
    """The strikeout props for this game, joined to it by event id.

    The props already exist on their own page. Repeating them here is the
    point: a reader looking at the game should not have to go and find them.
    """
    props = _PROPS.get(row.get("event_id") or "") or []
    if not props:
        return ""
    out = []
    for p in props:
        gap = p.get("gap") or 0.0
        # Reuses the pitcher board's own three words rather than inventing a
        # fourth vocabulary for the same judgement.
        if abs(gap) < 0.4:
            lean, lean_cls = _("in_line"), ""
        elif gap > 0:
            lean, lean_cls = _("over_the_line", v=f"{abs(gap):.1f}"), "good"
        else:
            lean, lean_cls = _("under_the_line", v=f"{abs(gap):.1f}"), "bad"
        prices = []
        if p.get("over_odds") is not None:
            prices.append("o" + om.format_american(p["over_odds"]))
        if p.get("under_odds") is not None:
            prices.append("u" + om.format_american(p["under_odds"]))
        # esc() escapes '&', so the em-dash entity is substituted after
        # escaping rather than passed through it.
        price_txt = esc(" / ".join(prices)) if prices else "&mdash;"
        verdict = p.get("matchup") or "neutral"
        line = _("pnl_prop_line",
                 ours=f'{p.get("projection") or 0:.1f}',
                 line=f'{p.get("line") or 0:g}',
                 prices=price_txt)
        out.append(
            f'<div class="ppr"><div class="ppr-top">'
            f'<span class="ppr-n">{esc(p.get("name", ""))}</span>'
            f'<span class="ppr-v {MX_CLASS[verdict]}">'
            f'{_(MX_LABEL[verdict])}</span></div>'
            f'<div class="ppr-line">{line} &middot; '
            f'<span class="{lean_cls}">{lean}</span></div></div>')
    return (f'<section class="pk"><h4>{_("pnl_props")}</h4>'
            + "".join(out) + "</section>")


def _detail_panel(row: dict) -> str:
    """Everything behind the card's disclosure.

    Replaced a table of the home side's fair price, the market width in cents
    and a book count, none of which were labelled. A reader could not tell
    what the middle number was, and the summary promised matchup history and
    props that were never there.
    """
    detail = row.get("detail") or {}
    form = _form_block(row, detail)
    starters = _starters_block(row, detail)
    props = _props_block(row)
    # The head-to-head block is the only one that speaks when it has nothing
    # ("they have not met yet this season"), which is worth saying on a card
    # that has other material and is just noise on a card that has none. So it
    # is included only alongside something else.
    # The price rows came off the face of the card when it took the canvas's
    # shape, so they land here -- first, because a reader who opened the card
    # after seeing an edge is looking for the price that edge is against.
    prices = market_rows(row)
    price_block = (f'<section class="pk"><h4>{_("pnl_prices")}</h4>'
                   f'<div class="mk">{prices}</div></section>') if prices else ""
    if not (form or starters or props or price_block):
        return ""
    return (f'<div class="pnl">{price_block}{form}{_h2h_block(row, detail)}'
            f'{starters}{_lineups_block(row, detail)}{props}</div>')


def _disclosure(row: dict) -> str:
    """The card's expandable half, or nothing.

    College basketball has no starters, no props and -- until enough finals
    are stored -- no form. A <details> that opens onto an empty box reads as
    a broken page, so a card with nothing behind it gets no control at all.
    """
    panel = _detail_panel(row)
    if not panel:
        return ""
    close = _("close")
    return (f'<details class="gmore" data-close="{close}">'
            f'<summary>{_("cv_detail")}</summary>'
            f'<div class="gmore-in">{panel}</div></details>')


def board_cards(rows: list[dict], empty_key: str = "board_empty") -> str:
    """Every game on a board, or a line saying there are none.

    Does not group by league. A caller wanting per-league headings renders
    each league's rows in its own call, which keeps this function ignorant of
    page layout.
    """
    if not rows:
        return f'<p class="empty-board">{_(empty_key)}</p>'
    return '<div class="board">' + "".join(board_card(r) for r in rows) + "</div>"


# ------------------------------------------------------------------ +EV ---
# The page is generated rather than written because every threshold on it is
# a live value from config.py and every figure a live value from the board.
# A page that restated them in prose would be wrong the first time either
# moved, and this is the one page whose whole claim is that it is not.

EV_PRICES = (-200, -110, 100, 150, 900)


def ev_price_table() -> str:
    """What five prices imply, and what $100 returns on each."""
    rows = "".join(
        f'<tr><th>{om.format_american(p)}</th>'
        f'<td class="en">{om.american_to_decimal(p):.2f}</td>'
        f'<td class="en">{om.american_to_prob(p) * 100:.1f}%</td>'
        f'<td class="en">${100 * om.american_to_decimal(p):,.0f}</td></tr>'
        for p in EV_PRICES)
    return (f'<div class="sscroll"><table class="stbl num">'
            f'<tr><th></th>'
            f'<td class="en hd">{_("ev_decimal")}</td>'
            f'<td class="en hd">{_("ev_implies")}</td>'
            f'<td class="en hd">{_("ev_returns")}</td></tr>'
            f'{rows}</table></div>')


def _ev_hold(width) -> float:
    """Hold implied by a two-way market that wide, quoted symmetrically."""
    if not width:
        return 0.0
    p = 100.0 + width / 2.0
    imp = p / (p + 100.0)
    return (2 * imp - 1) / (2 * imp)


def ev_numbers(board: dict) -> dict:
    """The board's own arithmetic, for the prose to quote."""
    import statistics
    holds, edges = [], []
    for entry in (board.get("leagues") or {}).values():
        for game in entry.get("games") or []:
            for m in (game.get("markets") or {}).values():
                if m.get("width"):
                    holds.append(_ev_hold(m["width"]))
                for k in ("edge_home", "edge_away"):
                    if m.get(k) is not None:
                        edges.append(m[k])
    return {
        "hold": statistics.median(holds) * 100 if holds else 0.0,
        "sides": len(edges),
        "negative": sum(1 for e in edges if e < 0),
        "best": max(edges) if edges else 0.0,
    }


def _ev_best_side(board: dict):
    """The best-priced side anywhere on the board, or None."""
    best = None
    for entry in (board.get("leagues") or {}).values():
        for game in entry.get("games") or []:
            for market, m in (game.get("markets") or {}).items():
                for tag in ("home", "away"):
                    edge = m.get(f"edge_{tag}")
                    if edge is None:
                        continue
                    if best is None or edge > best["edge"]:
                        best = {"edge": edge, "game": game, "market": market,
                                "tag": tag, "best": m.get(f"best_{tag}") or {},
                                "fair": m.get(f"fair_{tag}"),
                                "books": m.get("books"),
                                "point": m.get("point")}
    return best


def ev_example(board: dict) -> str:
    """One real price, with the multiplication shown rather than asserted."""
    b = _ev_best_side(board)
    if not b or b["best"].get("price") is None:
        return f'<p class="pnl-note">{_("ev_no_board")}</p>'
    price = b["best"]["price"]
    dec = om.american_to_decimal(price)
    implied = om.american_to_prob(price) * 100
    fair = (b["fair"] or 0.0)
    game = b["game"]
    club = _nickname(game.get("away") if b["tag"] == "away" else game.get("home"))
    point = b["point"]
    if point is not None:
        point = -point if b["tag"] == "away" else point
    label = f"{esc(club)}" + (f" {point:+g}" if point is not None else "")
    market = _(leagues.market_label_key(game.get("league", ""), b["market"]))
    return f"""<div class="sum">
      <div><span>{label} &middot; {esc(market.lower())}, {_("ev_best_price")}</span>
        <span>{esc(om.format_american(price))}</span></div>
      <div><span>{_("ev_which_implies")}</span><span>{implied:.2f}%</span></div>
      <div><span>{_("ev_books_say", n=b["books"] or 0)}</span>
        <span>{fair * 100:.2f}%</span></div>
      <div class="tot"><span>{_("ev_chance_paid", pct=f"{fair * 100:.2f}",
                              dec=f"{dec:.4f}")}</span>
        <span>{fair:.4f} &times; {dec:.4f} = {fair * dec:.4f}</span></div>
    </div>
    <p>{_("ev_example_read", back=f"{100 * fair * dec:.2f}",
          ev=f"{b['edge']:+.2f}")}</p>"""


def ev_gates() -> str:
    """Every gate a price has to survive, read out of config."""
    gates = [
        ("ev_g_today", "SAME_DAY_ONLY", str(config.SAME_DAY_ONLY)),
        ("ev_g_stale", "STALE_MINUTES", _("ev_minutes", n=config.STALE_MINUTES)),
        ("ev_g_books", "MIN_BOOKS", str(config.MIN_BOOKS)),
        ("ev_g_point", "&mdash;", _("ev_consensus_point")),
        ("ev_g_devig", "DEVIG_METHOD", config.DEVIG_METHOD),
        ("ev_g_band", "MIN_PRICE / MAX_PRICE",
         f"{config.MIN_PRICE:+d} to {config.MAX_PRICE:+d}"),
        ("ev_g_loo", "&mdash;", _("ev_n_others", n=config.MIN_BOOKS - 1)),
        ("ev_g_ev", "MIN_EDGE_PCT", f"{config.MIN_EDGE_PCT:.1f}%"),
        ("ev_g_pp", "MIN_EDGE_PP", f"{config.MIN_EDGE_PP:.1f} pp"),
        ("ev_g_ceiling", "MAX_EDGE_PCT", f"{config.MAX_EDGE_PCT:.1f}%"),
    ]
    rows = "".join(
        f'<tr><th><span class="gn">{i:02d}</span>{_(key + "_n")}</th>'
        f'<td class="sval"><span class="skey">{const}</span>'
        f'<span class="snum">{val}</span></td>'
        f'<td class="swhy">{_(key + "_w")}</td></tr>'
        for i, (key, const, val) in enumerate(gates, 1))
    return f'<div class="sscroll"><table class="stbl">{rows}</table></div>'


def ev_card_rules() -> str:
    """And what fits on the card once a price has cleared."""
    rules = [
        ("ev_c_side", "&mdash;"),
        ("ev_c_league", str(config.MAX_PLAYS_PER_LEAGUE)),
        ("ev_c_day", str(config.MAX_PLAYS_PER_DAY)),
        ("ev_c_stake", _("ev_one_unit")),
    ]
    rows = "".join(
        f'<tr><th>{_(key + "_n")}</th><td class="snum">{val}</td>'
        f'<td class="swhy">{_(key + "_w")}</td></tr>' for key, val in rules)
    return f'<div class="sscroll"><table class="stbl">{rows}</table></div>'


def ev_funnel(board: dict) -> str:
    """The same real price, walked through every gate until it stops."""
    b = _ev_best_side(board)
    if not b or b["best"].get("price") is None:
        return ""
    price = b["best"]["price"]
    fair = b["fair"] or 0.0
    edge = b["edge"]
    pp = (fair - om.american_to_prob(price)) * 100
    game = b["game"]
    market = _(leagues.market_label_key(game.get("league", ""), b["market"]))
    ok = (b["books"] or 0) >= config.MIN_BOOKS
    rows = [
        (_("ev_f_books"), f'{b["books"]} &ge; {config.MIN_BOOKS}', ok),
        (_("ev_f_best"),
         f'{esc(om.format_american(price))} {_("ev_at")} '
         f'{esc(b["best"].get("book", ""))}', True),
        (_("ev_f_band"), f"{config.MIN_PRICE:+d} to {config.MAX_PRICE:+d}", True),
        (_("ev_f_fair", book=esc(b["best"].get("book", ""))),
         esc(om.format_american(om.prob_to_american(fair))), True),
        (_("ev_f_ev"),
         f'{edge:+.2f}% &lt; {config.MIN_EDGE_PCT:.1f}%'
         if edge < config.MIN_EDGE_PCT
         else f'{edge:+.2f}% &ge; {config.MIN_EDGE_PCT:.1f}%',
         edge >= config.MIN_EDGE_PCT),
        (_("ev_f_pp"),
         f'{pp:+.2f} pp &lt; {config.MIN_EDGE_PP:.1f} pp'
         if pp < config.MIN_EDGE_PP
         else f'{pp:+.2f} pp &ge; {config.MIN_EDGE_PP:.1f} pp',
         pp >= config.MIN_EDGE_PP),
    ]
    posted = all(good for _lab, _v, good in rows)
    body = "".join(
        f'<div class="swork-r{"" if good else " fail"}">'
        f'<span>{lab}</span><span>{val}</span></div>'
        for lab, val, good in rows)
    body += (f'<div class="swork-r{"" if posted else " fail"}">'
             f'<span>{_("ev_f_posted")}</span>'
             f'<span>{_("ev_yes") if posted else _("ev_no")}</span></div>')
    return (f'<div class="swork"><div class="swork-h">'
            f'{esc(game.get("away",""))} {_("ev_at")} '
            f'{esc(game.get("home",""))} &middot; {esc(market.lower())}</div>'
            f'{body}</div>')


# --------------------------------------------------------- batter homers ---
# A projection, and drawn as one: the chance is the headline, the three
# numbers behind it sit underneath, and the calibration strip above the cards
# says what the model has actually delivered so far.

def _bvp_line(r: dict) -> str:
    """This batter's career line against tonight's starter, in one row.

    The board's own unit is already one batter against one named pitcher,
    so a whole table would be five columns of one row. A sentence carries
    the same five numbers and does not have to be scanned.

    The sample is almost always small -- five to twenty-five plate
    appearances -- so it is set at label weight beside the projection rather
    than beside it in size, and nothing on the card is derived from it.
    """
    who = _short_name(r.get("vs"))
    bvp = r.get("bvp")
    if not bvp or not bvp.get("pa"):
        return (f'<div class="bvp none">'
                f'{_("bvp_never", who=esc(who))}</div>')
    avg = bvp.get("avg")
    return (f'<div class="bvp">'
            + _("bvp_line", who=esc(who),
                h=bvp.get("h", 0), ab=bvp.get("ab", 0),
                hr=bvp.get("hr") if bvp.get("hr") is not None else 0,
                k=bvp.get("k") if bvp.get("k") is not None else 0,
                avg=(f"{avg:.3f}".lstrip("0") if avg is not None else "&mdash;"))
            + "</div>")


def _group_card(title: str, when, sub: str, rows_html: str,
                accent: str | None = None, right: str = "",
                detail: str = "") -> str:
    """The canvas card, for a board whose unit is a LIST rather than a number.

    The home run, hits and NFL boards each show several players under one
    pitcher or one defence, so they cannot borrow board_card's shape
    literally -- there is no single figure to set at 30px. What they take
    instead is the vocabulary: the same head, the same mono sub-line, the
    same footer rule, the same disclosure button. Five boards through one
    function, so the next change to the card is one change.
    """
    style = f' style="--accent:{accent}"' if accent else ""
    right_html = f'<span class="cv-time">{right}</span>' if right else ""
    return f"""
        <article class="pb-card bat-card"{style}>
          <div class="pb-body">
            <div class="cv-head">
              <h3 class="cv-tm">{title}</h3>
              <span class="cv-time">{esc(game_time(when)) if when else ""}</span>
            </div>
            <div class="cv-sub">{sub}{(" &middot; " + right_html) if right else ""}</div>
            <div class="bats">{rows_html}</div>
            {detail}
          </div>
        </article>"""


def batter_cards(rows: list[dict]) -> str:
    """Tonight's most dangerous bats, grouped by the game they appear in."""
    if not rows:
        return f'<div class="empty-board">{_("bat_empty")}</div>'
    games: dict = {}
    for r in rows:
        games.setdefault((r.get("commence_time"), r.get("vs")), []).append(r)

    out = []
    for (when, pitcher), group in games.items():
        club = esc(_nickname(group[0].get("team")))
        hand = group[0].get("vs_hand") or ""
        hand_txt = (f' ({_("mx_right") if hand == "R" else _("mx_left")})'
                    if hand in ("L", "R") else "")
        park = group[0].get("park") or 1.0
        park_cls = "good" if park > 1.03 else "bad" if park < 0.97 else ""
        bats = "".join(f"""
          <div class="bat">
            <div class="bat-n">{esc(b.get('name',''))}</div>
            <div class="bat-c"><b>{b['chance'] * 100:.1f}%</b></div>
            <div class="bat-w">{_("bat_season",
                hr=b.get('hr', 0), pa=f"{b.get('pa', 0):,}",
                rate=f"{b.get('hr_rate', 0) * 100:.1f}")}</div>
            {_bvp_line(b)}
          </div>""" for b in group)
        out.append(_group_card(
            club, when,
            _("bat_facing", who=esc(pitcher or "?"), hand=hand_txt,
              rate=f"{(group[0].get('vs_hr_per_bf') or 0) * 100:.1f}"),
            bats,
            accent=team_color(group[0].get("team")) or "var(--line-2)",
            right=f'<span class="bat-park {park_cls}">'
                  f'{_("bat_park", v=f"{park:.2f}")}</span>'))
    return '<div class="pb-grid">' + "".join(out) + "</div>"


def batter_calibration(summary: dict) -> str:
    """What the model promised against what happened. Not a win rate."""
    n = (summary or {}).get("graded") or 0
    if not n:
        return f'<p class="pnl-note">{_("bat_ungraded")}</p>'
    exp, act = summary["expected"], summary["actual"]
    rows = "".join(
        f'<tr><th>{esc(b["label"])}</th>'
        f'<td class="en">{b["n"]}</td>'
        f'<td class="en">{b["expected"]:.1f}%</td>'
        f'<td class="en {"egain" if b["actual"] >= b["expected"] else "eloss"}">'
        f'{b["actual"]:.1f}%</td></tr>'
        for b in summary.get("buckets") or [])
    # Formatted before the f-string, not inside it. An f-string expression
    # cannot be split across two adjacent literals, and this is the third
    # time that trap has been hit in this file.
    exp_txt, act_txt = f"{exp:.1f}", f"{act:.1f}"
    head = f'<p class="pnl-note">{_("bat_cal", n=n, exp=exp_txt, act=act_txt)}</p>' 
    if not rows:
        return head
    return (head + f'<div class="sscroll"><table class="stbl num">'
            f'<tr><th></th><td class="en hd">{_("bat_n")}</td>'
            f'<td class="en hd">{_("bat_promised")}</td>'
            f'<td class="en hd">{_("bat_delivered")}</td></tr>'
            f'{rows}</table></div>')


# ----------------------------------------------------------------- hits ---
# A sibling of the batter home-run board, same layout, different column:
# the hits column of payloads the home-run board already fetches.

def hit_cards(rows: list[dict]) -> str:
    """Tonight's best chances of a hit, grouped by the game they appear in."""
    if not rows:
        return f'<div class="empty-board">{_("hit_empty")}</div>'
    games: dict = {}
    for r in rows:
        games.setdefault((r.get("commence_time"), r.get("vs")), []).append(r)

    out = []
    for (when, pitcher), group in games.items():
        club = esc(_nickname(group[0].get("team")))
        hand = group[0].get("vs_hand") or ""
        hand_txt = (f' ({_("mx_right") if hand == "R" else _("mx_left")})'
                    if hand in ("L", "R") else "")
        park = group[0].get("park") or 1.0
        park_cls = "good" if park > 1.03 else "bad" if park < 0.97 else ""
        vs_rate = f"{(group[0].get('vs_h_per_bf') or 0) * 100:.1f}"
        bats = "".join(f"""
          <div class="bat">
            <div class="bat-n">{esc(b.get('name',''))}</div>
            <div class="bat-c"><b>{b['chance'] * 100:.1f}%</b></div>
            <div class="bat-w">{_("hit_season",
                h=b.get('h', 0), pa=f"{b.get('pa', 0):,}",
                rate=f"{b.get('hit_rate', 0) * 100:.1f}")}</div>
            {_bvp_line(b)}
          </div>""" for b in group)
        accent = team_color(group[0].get('team')) or 'var(--line-2)'
        out.append(_group_card(
            club, when,
            _("hit_facing", who=esc(pitcher or "?"), hand=hand_txt,
              rate=vs_rate),
            bats, accent=accent,
            right=f'<span class="bat-park {park_cls}">'
                  f'{_("hit_park", v=f"{park:.2f}")}</span>'))
    return '<div class="pb-grid">' + "".join(out) + "</div>"


def hit_calibration(summary: dict) -> str:
    """What the model promised against what happened. Not a win rate."""
    n = (summary or {}).get("graded") or 0
    if not n:
        return f'<p class="pnl-note">{_("hit_ungraded")}</p>'
    return batter_calibration(summary)


# ------------------------------------------------------------------ NFL ---
# Three yardage boards (passing, rushing, receiving) and one touchdown
# board, siblings of the hits board above: same card grid, same calibration
# note, a different number underneath. yard_cards and td_cards both group by
# game exactly as hit_cards does; yard_accuracy is the continuous-error
# sibling of hit_calibration's bucketed one, because a yardage projection is
# a number, not a chance.
#
# The badge that names a player's position is given its own class, "ppos",
# rather than the bare "pos" the brief's own snippet uses -- base.css already
# defines a bare .pos rule for the monthly chart's positive bars
# (height:180px, flex column), and a player's position badge would have
# inherited that layout by accident.

def yard_cards(rows: list[dict], unit: str = "yds") -> str:
    """Projected yardage, one card per club.

    Grouped on (commence_time, team), not the fixture. Grouping on the
    game put both sides of a fixture in one card headed with one club's
    name and captioned with that club's opp_allowed -- the visiting
    side's players then sat under the home side's opponent and defensive
    rate, a wrong number that reads as a plausible one. hit_cards already
    groups on the club rather than the fixture; this follows it.
    """
    if not rows:
        return f'<div class="empty-board">{_("nfl_empty")}</div>'
    games: dict = {}
    for r in rows:
        games.setdefault((r.get("commence_time"), r.get("team")), []).append(r)

    out = []
    for (when, _team), group in games.items():
        opp = esc(group[0].get("opponent", ""))
        allowed = f"{group[0].get('opp_allowed', 0):.0f}"
        league = f"{group[0].get('league_allowed', 0):.0f}"
        men = "".join(f"""
          <div class="bat">
            <div class="bat-n">{esc(p.get('name',''))}
              <span class="ppos">{esc(p.get('position',''))}</span></div>
            <div class="bat-c"><b>{p.get('projection', 0):.0f}</b>
              <span class="unit">{esc(unit)}</span></div>
            <div class="bat-w">{p.get('baseline', 0):.0f} {esc(unit)}
              unadjusted</div>
          </div>""" for p in group)
        out.append(_group_card(
            esc(group[0].get("team", "")), when,
            _("nfl_vs", opp=opp, allowed=allowed, league=league),
            men))
    return '<div class="pb-grid">' + "".join(out) + "</div>"


def td_cards(rows: list[dict]) -> str:
    """Anytime touchdown chances, one card per club.

    Grouped on (commence_time, team) for the same reason as yard_cards:
    grouping on the fixture instead puts the away side's players under
    the home side's name and opp_allowed.
    """
    if not rows:
        return f'<div class="empty-board">{_("nfl_empty")}</div>'
    games: dict = {}
    for r in rows:
        games.setdefault((r.get("commence_time"), r.get("team")), []).append(r)
    out = []
    for (when, _team), group in games.items():
        opp = esc(group[0].get("opponent", ""))
        allowed = f"{group[0].get('opp_allowed', 0):.2f}"
        league = f"{group[0].get('league_allowed', 0):.2f}"
        men = "".join(f"""
          <div class="bat">
            <div class="bat-n">{esc(p.get('name',''))}
              <span class="ppos">{esc(p.get('position',''))}</span></div>
            <div class="bat-c"><b>{p.get('chance', 0) * 100:.1f}%</b></div>
          </div>""" for p in group)
        out.append(_group_card(
            esc(group[0].get("team", "")), when,
            _("nfl_vs", opp=opp, allowed=allowed, league=league),
            men))
    return '<div class="pb-grid">' + "".join(out) + "</div>"


def td_calibration(summary: dict) -> str:
    """What the model promised against what happened. Not a win rate.

    batter_calibration's bucketed markup fits a chance-based verdict
    exactly as well here as it does for a home run -- the touchdown page
    just needs its own empty state. Without this it fell through to
    batter_calibration directly, and batter_calibration's own empty-state
    copy talks about the batter's season total, which is how a public NFL
    page ended up reading like a baseball one. hit_calibration is the
    same fix for the same reason; follow it.
    """
    n = (summary or {}).get("graded") or 0
    if not n:
        return f'<p class="pnl-note">{_("nfl_ungraded")}</p>'
    return batter_calibration(summary)


def yard_accuracy(summary: dict) -> str:
    """Mean error against the unadjusted baseline, like for like.

    Every sibling renderer goes through i18n; this one used to hardcode
    its sentences in English only, which is invisible in an English-only
    build but is exactly the kind of gap that leaves half a site
    untranslatable the day a second language ships.
    """
    n = (summary or {}).get("graded") or 0
    if not n:
        return f'<p class="pnl-note">{_("nfl_ungraded")}</p>'
    mae = summary.get("mae")
    base = summary.get("baseline_mae")
    comp = summary.get("mae_on_baseline_rows")
    bits = [_("nfl_acc_headline", mae=mae, n=n, s=i18n.plural(n, LANG))]
    if base is not None and comp is not None:
        verdict = _("nfl_acc_earning" if comp < base
                   else "nfl_acc_not_earning")
        bits.append(_("nfl_acc_compare", bn=summary.get("baseline_n"),
                      comp=comp, base=base, verdict=verdict))
    return '<p class="pnl-note">' + " ".join(bits) + "</p>"


# ------------------------------------------------------------- home runs ---
# The strikeout page's argument applied to a different number, and with the
# same posture: matchup facts, no projection, no pick. There are no prices
# here because a batter home-run market is billed per event and the strikeout
# projection has not yet earned a second one.

HR_CLASS = {"favourable": "good", "tough": "bad", "neutral": ""}
HR_LABEL = {"favourable": "hr_v_high", "tough": "hr_v_low",
            "neutral": "hr_v_ordinary"}


def _hr_row(label: str, value, unit: str, rank, of, mean,
            verdict: str) -> str:
    """One measured line: the number, where it ranks, and the league beside it."""
    if value is None:
        return (f'<div class="hrl"><span class="hrl-k">{label}</span>'
                f'<span class="hrl-v">&mdash;</span></div>')
    rank_txt = (_("pb_rank", r=rank, ord=_ordinal(rank), n=of)
                if rank and of else "")
    mean_txt = _("hr_league", v=f"{mean:.2f}") if mean else ""
    return (f'<div class="hrl {HR_CLASS[verdict]}">'
            f'<span class="hrl-k">{label}</span>'
            f'<span class="hrl-v"><b>{value:.2f}</b> {unit}</span>'
            f'<span class="hrl-r">{rank_txt}</span>'
            f'<span class="hrl-m">{mean_txt}</span></div>')


def homer_cards(rows: list[dict]) -> str:
    """One card per starter: how often he gives one up, how often they hit one."""
    if not rows:
        return f'<div class="empty-board">{_("hr_empty")}</div>'
    out = []
    for r in rows:
        opp = esc(_nickname(r.get("opponent")))
        hand = r.get("hand") or ""
        hand_txt = (f' &middot; {_("mx_right") if hand == "R" else _("mx_left")}'
                    if hand in ("L", "R") else "")
        thin = r.get("thin")
        accent = team_color(r.get("opponent")) or "var(--line-2)"
        body = f"""
            {_hr_row(_("hr_allows"), r.get("hr_per_9"), _("hr_per9_unit"),
                     r.get("hr_per_9_rank"), r.get("pitchers_ranked"),
                     r.get("league_hr_per_9"), r.get("pitcher_verdict"))}
            {_hr_row(_("hr_lineup", team=opp), r.get("opp_hr_per_game"),
                     _("hr_pergame_unit"), r.get("opp_hr_rank"),
                     r.get("teams_ranked"), r.get("league_hr_per_game"),
                     r.get("lineup_verdict"))}
            <div class="pb-rows">
              <div class="pb-row"><span>{_("season")}</span>
                <b>{_("hr_season", hr=r.get("hr_allowed") or 0,
                      ip=f'{r.get("innings") or 0:.1f}')}</b></div>
            </div>
            {f'<p class="hr-thin">{_("hr_too_few")}</p>' if thin else ""}"""
        out.append(_group_card(
            esc(r.get("name", "")), r.get("commence_time"),
            f'{esc(r.get("team",""))} vs {opp}{hand_txt}',
            body, accent=accent))
    return '<div class="pb-grid">' + "".join(out) + "</div>"


# ------------------------------------------------------------------ form ---
# Every league's table, computed from the finals this project stores for
# itself. MLB could take it from StatsAPI instead, but one code path that
# works for four leagues beats two that each work for some of them.

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

    # Both clubs are named, by nickname -- the canvas card sets the matchup
    # at 20px and the full names wrap to two lines on every card. The card
    # must still not mark our side by making the other one harder to read,
    # so both are present and neither is dimmed.
    assert _nickname(row["home"]) in html_out, html_out
    assert _nickname(row["away"]) in html_out, html_out

    # One probability, not two: the side our number likes. Printing both
    # made the reader do the comparison the card had already done.
    assert html_out.count('class="cv-pct"') == 1, html_out

    # The prices moved behind the disclosure when the card took the canvas's
    # shape, but they are still in the markup -- <details> keeps its content
    # findable by Ctrl+F and by a crawler.
    assert 'class="gmore"' in html_out
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

    # This row has no form, starters or props -- the state of a college
    # basketball card, and of an NFL card before enough finals are stored.
    # It still gets a disclosure, because the price rows moved behind one
    # when the card took the canvas's shape and prices are content.
    assert "<details" in html_out, \
        "a card with prices has something to disclose"

    # A card with genuinely nothing behind it still renders none. An empty
    # disclosure reads as a broken page.
    bare = dict(row)
    bare["markets"] = {}
    bare["detail"] = {}
    assert "<details" not in board_card(bare), board_card(bare)
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

    # --- the probability bar ------------------------------------------------
    rated = {**row, "model": {
        "home_win_prob": 0.556, "away_win_prob": 0.444,
        "market_home_prob": 0.503, "disagreement": 5.3,
        "suspect": False, "source": "slate"},
        "detail": {"home_record": {"w": 74, "l": 56},
                   "away_record": {"w": 77, "l": 53},
                   "home_starter": "Freddy Peralta", "home_starter_era": 3.47,
                   "away_starter": "Shota Imanaga", "away_starter_era": 3.24}}

    bar = _prob_bar(rated["model"])
    assert 'class="gbar"' in bar
    assert 'class="tick"' in bar, "the market's own number has to be marked"
    # The bar reads left to right as the away club's chance, so the market's
    # tick sits at 1 - market_home_prob.
    assert "49.7%" in bar, "the tick is placed on the away side of the bar"

    # No market number means no tick, rather than a tick at zero.
    assert 'class="tick"' not in _prob_bar(
        {**rated["model"], "market_home_prob": None})

    # No model at all means no bar, rather than an empty one.
    assert _prob_bar(None) == ""

    card = board_card(rated)
    # ONE percentage on the face, rounded to whole points, and it is the side
    # our number likes. The canvas card prints the claim, not the arithmetic
    # -- 44.4 is 100 minus 55.6 and the reader can do that subtraction.
    shown = re.findall(r'class="cv-pct">([^<]*)', card)
    assert shown == ["56%"], shown
    # 55.6 still appears -- as the bar's width in a style attribute, which is
    # geometry, not a claim. The assertion is on the printed number only:
    # a decimal there implies a precision the model does not have.
    assert "44.4" not in card, card

    # The records and the starters moved behind the disclosure, and are still
    # in the markup. The whole record line, not the digits: "74" and "56" on
    # their own also appear in event ids, prices and percentages, so a
    # two-substring assertion would pass whether or not a record ever
    # reached the card.
    assert "74&ndash;56" in card, \
        "the home club's record reaches the card as a record line"
    assert "77&ndash;53" in card
    assert "Freddy Peralta" in card and "3.47" in card

    # A card with no starter shows no starter line at all, rather than a
    # hardcoded English "TBA" — which every basketball and football card
    # would otherwise carry under a club that has no pitcher.
    hoops = board_card({**row, "league": "nba", "detail": {},
                        "model": {"home_win_prob": 0.55, "away_win_prob": 0.45}})
    assert "TBA" not in hoops, "no pitcher slot on a card with no pitcher"
    assert "var(--dim)" not in card, "everything on a card is content"

    # The edge is the last thing on the face, after the market's number --
    # the canvas reads left to right as "here is what they say, here is how
    # far we are from it". Pin the order so an edit that swaps them fails.
    assert card.index('class="gm"') < card.index('class="ge'), \
        "the market's number comes before the size of the disagreement"

    # Under a point, the card says so instead of printing a decimal that
    # would teach a reader to stop believing the ones that matter.
    agree = board_card({**rated, "model": {**rated["model"], "disagreement": 0.4}})
    assert i18n.t("cv_noedge", LANG) in agree, agree
    assert "0.4" not in agree.split('class="ge')[1][:40], agree

    # An edge the other way is amber and says "fade", not a negative edge.
    fade = board_card({**rated, "model": {**rated["model"], "disagreement": -6.0}})
    assert 'class="ge down"' in fade and i18n.t("cv_fade", LANG, v="") .split()[-1] in fade

    # A game we have not rated shows the market block and no percentages,
    # rather than a placeholder or the market's number in our place.
    plain = board_card({**row, "model": None, "detail": None})
    assert "55.6" not in plain and 'class="cv-pct"' not in plain
    assert "MONEYLINE" in plain.upper() or i18n.t("mkt_moneyline", LANG) in plain

    # ---- the detail panel is the card's whole second half.
    row["detail"] = {
        "home_form": {"w": 85, "l": 53, "streak": "L2", "l10_w": 6, "l10_l": 4},
        "away_form": {"w": 78, "l": 60, "streak": "W1", "l10_w": 4, "l10_l": 6},
        "series": [
            {"date": "2026-06-23", "away": "Chicago Cubs", "away_runs": 1,
             "home": "Milwaukee Brewers", "home_runs": 4},
            {"date": "2026-06-29", "away": "Milwaukee Brewers", "away_runs": 7,
             "home": "Chicago Cubs", "home_runs": 2},
        ],
        "home_starter": "Robert Gasser", "away_starter": "Matthew Boyd",
        "home_vs_opp": None,
        "away_vs_opp": {"starts": 2, "innings": 10.3, "era": 7.84,
                        "strikeouts": 5, "span": "2025-2026"},
    }
    set_props([
        {"event_id": "evt1", "name": "Matthew Boyd", "line": 4.5,
         "projection": 4.2, "gap": -0.3, "over_odds": 112, "under_odds": -120,
         "matchup": "tough"},
        {"event_id": "other", "name": "Nobody At All", "line": 1.5,
         "projection": 1.5, "gap": 0.0, "matchup": "neutral"},
    ])
    panel = _detail_panel(row)
    assert "Last 10" in panel, panel
    assert "L2" in panel and "W1" in panel
    assert "Brewers lead the season series" in panel, panel
    assert "Matthew Boyd" in panel
    # A starter with no history says so rather than rendering a blank line.
    assert "has not faced" in panel
    # Props join by event id, and only this game's appear.
    assert "Nobody At All" not in panel, panel
    assert "tough matchup" in panel
    assert "[[" not in panel, panel

    # A card whose rating never merged has no detail, and must still render.
    # It keeps a disclosure, because the price rows live behind one now.
    bare = dict(row)
    bare.pop("detail")
    set_props([])
    assert "<details" in board_card(bare), "prices are still worth disclosing"

    # Strip the prices too and there is genuinely nothing to expand -- the
    # college basketball card, and the NFL card on the first morning after
    # the scores fix lands. No control at all, rather than an empty box.
    nothing = {**bare, "markets": {}}
    assert _detail_panel(nothing) == "", "no detail means no panel, not a crash"
    assert _disclosure(nothing) == "", "and no panel means no disclosure control"
    assert "<details" not in board_card(nothing), board_card(nothing)
    # And with a detail block it is a details element, not a flip.
    with_detail = board_card(row)
    assert "<details" in with_detail and "<summary" in with_detail
    assert "onclick" not in with_detail, "still no JavaScript"

    # ---- the prop card's matchup panel
    prop = {
        "name": "Gavin Williams", "team": "CLE", "opponent": "TOR",
        "hand": "R", "matchup": "tough", "k_per_9": 11.77,
        "opp_split": {"k_pct": 18.9, "pa": 3665, "rank": 29, "rank_all": 28,
                      "of": 30, "league_mean": 21.85},
        "vs_opp": {"starts": 3, "innings": 15.3, "era": 6.46,
                   "strikeouts": 15, "span": "2025-2026"},
    }
    mx = _matchup_inner(prop)
    assert "18.9%" in mx, mx
    assert "vs right-handers" in mx and "vs left-handers" not in mx, \
        "only the hand that applies is shown"
    assert "29th of 30" in mx, "the split rank stays, in the row"
    assert "3,665 PA" in mx, "the sample size prints with a thousands mark"
    assert "tough matchup" in mx
    assert "[[" not in mx, mx

    # The panel is a grid, a table and a verdict -- no paragraphs. Asked for
    # twice, so it is pinned rather than left to taste. Every sentence that
    # used to sit here restated a number already on screen.
    assert "<p" not in mx, f"the prop panel carries no prose:\n{mx}"
    for gone in ("mx_read", "mx_thin", "mx_applies", "mx_and_hand",
                 "mx_same", "mx_never_v"):
        assert i18n.t(gone, LANG, k9="", season="", n=1, s="", who="",
                      team="", hand="", overall="", split="",
                      hand_word="") not in mx, gone

    # No split and no history still renders, and claims nothing.
    thin = {"name": "Nobody", "opponent": "TOR", "hand": "",
            "matchup": "neutral", "k_per_9": 8.0, "opp_split": None,
            "vs_opp": None}
    out = _matchup_inner(thin)
    assert "has never faced" in out, out
    assert "%" not in out, "no split means no percentage invented"

    # --- the pitcher card with no posted line -------------------------------
    # The board is built from StatsAPI every morning now, so most cards have
    # no price on them. The card must not invent one.
    free_sp = {"name": "A Pitcher", "team": "DET",
               "opponent": "Cleveland Guardians", "projection": 6.4,
               "line": None, "gap": None, "suspect": False, "reference": 6.4,
               "recent": [{"date": "2026-09-02", "strikeouts": 8,
                           "innings": 6.0}],
               "recent_over": 1, "recent_n": 1, "last5_over": 1, "last5_n": 1,
               "k_per_9": 11.2, "matchup": "neutral", "actual": None}
    free_html = pitcher_cards([free_sp])
    assert 'class="cv-tick"' not in free_html, \
        "no posted line means no tick; ours is already the fill"
    assert 'class="ge ' not in free_html, \
        "an edge against nothing is not a small edge"
    assert i18n.t("cv_noline", LANG) in free_html, free_html
    assert i18n.t("pnl_prices", LANG) not in free_html, \
        "no prices section on a card with no prices"
    assert "0.0" not in free_html.split('class="cv-foot"')[1][:120], \
        "a missing line must not collapse to a real-looking zero"

    priced_sp = dict(free_sp, line=6.5, gap=-0.1, reference=6.5,
                     over_odds=-115, under_odds=-105)
    priced_html = pitcher_cards([priced_sp])
    assert 'class="cv-tick"' in priced_html and 'class="ge ' in priced_html
    assert i18n.t("pnl_prices", LANG) in priced_html

    print("render self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()

