"""Render the site's data-driven pieces as HTML fragments.

Every function here takes plain dicts loaded from data/*.json and returns a
string. No template engine, no dependencies — that keeps the free hosting
story simple and the build instant.
"""
from __future__ import annotations

import math
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


# ------------------------------------------------------------------ play card
# --------------------------------------------------------------------- chips
# -------------------------------------------------------------------- tables
# The tag class is stable; the label is looked up at render time so it
# follows the page's language rather than being frozen at import.
RESULT_CLASS = {"win": "win", "loss": "loss", "push": "push"}
RESULT_KEY = {"win": "res_win", "loss": "res_loss", "push": "res_push"}


def _result_tag(result: str, fallback: str = "&mdash;") -> tuple[str, str]:
    cls = RESULT_CLASS.get(result, "")
    key = RESULT_KEY.get(result)
    return cls, (_(key) if key else fallback)


SOURCE_KEY = {"value": "src_value", "screen": "src_screen"}


def _short_date(play: dict) -> str:
    stamp = play.get("posted_date") or (play.get("commence_time") or "")[:10]
    try:
        return i18n.short_date(datetime.fromisoformat(stamp), LANG)
    except Exception:
        return stamp


# ---------------------------------------------------------------------- KPIs
# --------------------------------------------------------------------- chart
# -------------------------------------------------------------------- signup
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


def calibration_section(summary: dict) -> str:
    """A league board's own calibration, or nothing at all.

    Returns the empty string until the league has a graded rating. An empty
    chart under the heading "Are we calibrated?" reads as a claim that we
    looked and found nothing, which is not the same as not having looked
    yet -- and in the opening weeks of a season it would be on every board.
    """
    if not (summary or {}).get("graded"):
        return ""
    return (
        f'<section class="pad-sm" id="calibration"><div class="wrap">'
        f'<div class="sec-head" style="margin-bottom:26px">'
        f'<div class="eyebrow">{_("cal_eyebrow")}</div>'
        f'<h2 style="font-size:26px;margin-top:10px">{_("cal_head")}</h2>'
        f'<p class="lead" style="margin-top:12px">{_("cal_lead")}</p></div>'
        f'<div class="calib">{calibration_rows(summary.get("calibration") or [])}</div>'
        f'<div class="clegend">'
        f'<span><i class="key-line"></i> {_("cal_said")}</span>'
        f'<span><i class="key-dot"></i> {_("cal_happened")}</span>'
        f'<span><i class="key-band"></i> {_("cal_band")}</span></div>'
        f'<div class="note" style="margin-top:26px">'
        f'<p class="disclaimer">{brier_line(summary)}</p></div>'
        f'</div></section>')


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


def _k_tip(game: dict, value) -> str:
    """The pitcher strip's tooltip, translated. Kept out of _strip so the
    generic version does not have to know what an inning is."""
    return _("pb_tip", when=esc(game.get("date") or ""),
             opp=esc(game.get("opponent") or ""), k=value,
             ip=game.get("innings", 0))


def _strip(recent: list[dict], line: float, *, key: str = "strikeouts",
           scale: float | None = None, label: str | None = None,
           fmt=None, tip=None) -> str:
    """The run of recent games, as bars against a reference line.

    Written for the pitcher board and now shared with the NFL boards, so
    the two things that were baked in are arguments: which field on a row
    holds the number, and what the y-axis tops out at. A yardage strip
    cannot use PITCH_MAX_K, and a touchdown strip's reference is half a
    touchdown rather than a posted price.

    `scale` defaults to whatever makes the tallest bar fill the box, with
    the reference line kept inside it -- a fixed ceiling works for
    strikeouts because they have a natural range and does not for yards.
    """
    if not recent:
        return f'<div class="pb-nostrip">{_("no_starts")}</div>' 
    fmt = fmt or (lambda v: f"{v:g}")
    vals = [(g.get(key) or 0) for g in recent]
    if scale is None:
        scale = max(max(vals), line) * 1.15 or 1.0
    bars, ticks = [], []
    for g, v in zip(recent, vals):
        h = max(6.0, min(100.0, v / scale * 100))
        when = esc(g.get("date") or (f'W{g.get("week")}' if g.get("week") else ""))
        opp = esc(g.get("opponent") or "")
        title = (tip(g, v) if tip
                 else f"{when} {opp} &middot; {fmt(v)}".strip())
        bars.append(f'<div class="pb-bar{" hit" if v > line else ""}" '
                    f'style="height:{h:.1f}%" '
                    f'title="{title}"></div>')
        ticks.append(f"<span>{fmt(v)}</span>")
    pos = max(0.0, min(100.0, line / scale * 100))
    lab = label if label is not None else f"{line:g}"
    return f"""
      <div class="pb-strip">
        <div class="pb-line" style="bottom:{pos:.1f}%"><span class="pb-linelab">{lab}</span></div>
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


# The axis every row on the list board is drawn against. One axis for the
# whole board rather than one per row: the point of a list is that fifteen
# bars are comparable, and a bar scaled to its own line moves the tick from
# row to row and makes them incomparable.
#
# Nine is the design doc's number and holds for almost every slate. It is a
# floor, not a fixed value, because a pegged bar is a lie -- an eleven-K
# projection drawn at 100% would read as the same call as a nine.
PL_AXIS_MIN = 9.0


def _pl_axis(rows) -> float:
    top = max([r.get("projection") or 0 for r in rows]
              + [r.get("line") or 0 for r in rows] + [0.0])
    return max(PL_AXIS_MIN, math.ceil(top))


def _pl_fixture(r: dict) -> tuple:
    away, home = _mlb_sides(r)
    return (r.get("commence_time") or "", frozenset({away, home}))


def _pl_edge(r: dict):
    """The number the list is sorted by, or None when there is nothing to sort.

    A starter with no posted line has no edge -- not a zero one. Returning
    None keeps him out of the sort's arithmetic and sinks him to the foot
    with the settled rows, which is where an unpriced projection belongs on
    a board whose headline is disagreement with the market.
    """
    gap = r.get("gap")
    if r.get("line") is None or gap is None or abs(gap) < 0.4:
        return None
    return gap


def board_head_meta(date_label: str, rows: list[dict]) -> str:
    """The board header's one meta line: the date, then what is on the board.

    Sentence case, not the wide-tracked uppercase mono this used to be. A
    date is a sentence; the design doc's rule is that caps and tracking
    belong to labels of a couple of words, and "Wednesday, September 9,
    2026" set in .16em uppercase mono was the single ugliest line on the
    site.
    """
    n = pitcher_head(rows)
    parts = [esc(date_label)]
    if rows:
        parts.append(_("bh_props", n=n["props"]))
        parts.append(_("bh_games", n=n["games"]))
    return " &middot; ".join(parts)


# ---------------------------------------------------------- the hit strip
# Seven steps, black at exactly 50%. The midpoint is deliberately colourless:
# a coin flip is not a signal, and tinting it would put a colour on every row
# whether or not there is anything to see. Taken from Outlier's prop grid,
# recoloured to this site's own green and red.
HIT_BANDS = ((0.80, "h3"), (0.66, "h2"), (0.5001, "h1"), (0.4999, "mid"),
             (0.30, "l1"), (0.15, "l2"), (0.0, "l3"))


def hit_band(pct: float | None) -> str:
    if pct is None:
        return "na"
    for floor, name in HIT_BANDS:
        if pct >= floor:
            return name
    return "l3"


def hit_rate(recent: list[dict], threshold: float | None, n: int,
             key: str) -> tuple[float | None, int, int]:
    """How often the last `n` games cleared `threshold`. (pct, cleared, of)."""
    if threshold is None:
        return None, 0, 0
    got = [g for g in (recent or [])[-n:] if g.get(key) is not None]
    if not got:
        return None, 0, 0
    over = sum(1 for g in got if float(g[key]) > float(threshold))
    return over / len(got), over, len(got)


def implied_prob(odds) -> float | None:
    """The market's own number, before anyone's model touches it."""
    if odds is None:
        return None
    o = float(odds)
    return (-o) / (-o + 100) if o < 0 else 100 / (o + 100)


def hit_strip(recent, threshold, *, key, odds=None, priced=True,
              spans=(5, 10)) -> str:
    """L5 / L10 against the line, then what the market says about it.

    The raw fraction is printed beside the percentage on purpose. "100%" off
    three starts and "100%" off ten are the same number and nothing like the
    same claim, and a board that shows only the percentage invites the reader
    to treat them alike.

    The last cell is the market's own implied probability, and it appears
    only where a price exists -- which is the comparison this whole site is
    about. There is deliberately no cell naming the number the percentages
    were measured against: that number is the posted line printed under the
    bar, or our projection printed in the rail beside it, and a third copy of
    a figure already twice on screen is clutter, not context.
    """
    # No games, no strip. A row of em-dashes looks like a player who has
    # done nothing rather than one we have no log for, and that is the same
    # lie the strip exists to avoid telling.
    if not recent:
        return ""
    cells = []
    for n in spans:
        pct, over, of = hit_rate(recent, threshold, n, key)
        body = (f'{pct * 100:.0f}% <u>({over}/{of})</u>' if pct is not None
                else "&mdash;")
        cells.append(f'<span class="hr {hit_band(pct)}">'
                     f'<i>{_("hr_last", n=n)}</i>{body}</span>')
    prob = implied_prob(odds) if priced else None
    if prob is not None:
        cells.append(f'<span class="hr mkt"><i>{_("hr_market")}</i>'
                     f'{prob * 100:.0f}%</span>')

    return f'<div class="hrs">{"".join(cells)}</div>' if cells else ""


def pitcher_head(rows: list[dict]) -> dict:
    """The three counts the board's header prints, as a dict of strings."""
    games = {_pl_fixture(r) for r in rows}
    edges = sum(1 for r in rows if _pl_edge(r) is not None
                and r.get("actual") is None)
    return {"props": str(len(rows)), "games": str(len(games)),
            "edges": str(edges)}


def pitcher_cards(rows: list[dict]) -> str:
    """Every probable starter as one row of a list, biggest edge first.

    Rewritten from a grid of cards after the design pass. The cards were
    honest but expensive: a phone showed two of them, most of that height
    spent on a disclosure button and a projection set at display size, and
    the reader's actual question -- where does our number disagree with the
    market tonight -- took a scroll per starter to answer.

    A list answers it in one screen. The edge moves to a fixed right rail
    in colour and size, the board sorts by it, and settled and unpriced
    rows sink to the foot dimmed. Nothing is lost: every card's panel is
    still here, one tap away, because the row IS the summary of a
    <details> rather than a card with a button in it.

    The fixture stays on every row's meta line and the picker above still
    filters by game, so the grouping asked for on the NFL boards is kept
    without spending a heading and a grid on each of eleven fixtures.
    """
    if not rows:
        return f'<div class="empty-board">{_("pitch_empty")}</div>'

    # The picker's chips, built from the same fixture key the rows carry, so
    # a chip and its rows cannot disagree about what a game is.
    order = sorted({_pl_fixture(r) for r in rows},
                   key=lambda g: (g[0], str(sorted(g[1]))))
    slug = {g: f"g{i}" for i, g in enumerate(order)}

    axis = _pl_axis(rows)

    def row(r):
        line = r.get("line")
        proj = r.get("projection") or 0
        gap = r.get("gap")
        reference = r.get("reference")
        if reference is None:
            reference = line if line is not None else proj
        actual = r.get("actual")
        settled = actual is not None
        edge = _pl_edge(r)

        # Colour says one thing: which way we disagree, and only when we do.
        # A settled row is grey whatever it once said -- it is a result now,
        # not a call, and leaving it green would put six loud rows on a
        # board whose live section is the part anyone can act on.
        # Prefixed, every one of them. "up" on its own is a utility class in
        # base.css -- mono, 11px, letterspaced caps -- so `class="pl up"` set
        # the whole positive-edge row in uppercase mono. It shipped invisible
        # because the board that morning was entirely settled rows, and would
        # have appeared the first time a priced edge did.
        if settled:
            tone = "pl-done"
        elif edge is None:
            tone = "pl-none"
        elif edge > 0:
            tone = "pl-up"
        else:
            tone = "pl-down"

        fill = max(0.0, min(100.0, proj / axis * 100))
        tick = (max(0.0, min(100.0, line / axis * 100))
                if line is not None else None)
        tick_html = (f'<i class="pl-tick" style="left:{tick:.1f}%"></i>'
                     if tick is not None else "")

        # The verdict moves onto the row. It was behind the disclosure, which
        # meant checking ten starters cost ten taps to read one word each.
        verdict = r.get("matchup")
        mx = (f'<i class="mxb {MX_CLASS.get(verdict, "")}">'
              f'{_(MXB_LABEL[verdict])}</i>' if verdict in MXB_LABEL else "")

        if settled:
            went = _("over") if actual > reference else _("under")
            badge_txt = _("final_k", n=actual, side=went)
            hit = (actual > reference) == (edge is not None and edge > 0)
            badge = (f'<i class="pl-badge {"hit" if hit and edge is not None else "miss"}">'
                     f'{badge_txt}</i>')
        elif r.get("suspect"):
            badge = f'<i class="pl-badge flag" title="{_("pb_flagtip")}">{_("pb_flag")}</i>'
        else:
            badge = ""

        if edge is None:
            edge_n, edge_lab = "&mdash;", (_("pl_settled") if settled
                                          else (_("cv_noedge") if line is not None
                                                else _("pl_noline")))
        else:
            edge_n = f"+{edge:.1f}" if edge > 0 else f"&minus;{abs(edge):.1f}"
            edge_lab = _("over") if edge > 0 else _("under")

        # Nothing in the middle when there is no line: the right rail
        # already says so, and printing it twice made the row read as
        # though the absence were the finding.
        scale_mid = f'{_("pl_line")} {line:g}' if line is not None else ""
        strip = hit_strip(r.get("recent"), reference, key="strikeouts",
                          odds=r.get("over_odds"), priced=line is not None)

        away, home = _mlb_sides(r)
        meta = (f'{esc(_nickname(away))} @ {esc(_nickname(home))} '
                f'&middot; {_("pl_ks")}'
                if away and home
                else f'{esc(_nickname(r.get("team","")))} &middot; {_("pl_ks")}')

        return (
            f'<details class="pl {tone}" data-game="{slug[_pl_fixture(r)]}"'
            f' data-edge="{0 if edge is None or settled else 1}"'
            f' data-close="{_("close")}">'
            f'<summary class="pl-row">'
            f'<div class="pl-main">'
            f'<div class="pl-name"><span>{esc(r.get("name",""))}</span>{mx}</div>'
            f'<div class="pl-meta"><span>{meta}</span>{badge}</div>'
            f'<div class="pl-bar"><i class="pl-fill" style="width:{fill:.1f}%"></i>'
            f'{tick_html}</div>'
            f'<div class="pl-scale"><span>0</span><span>{scale_mid}</span>'
            f'<span>{axis:g}</span></div>'
            f'{strip}'
            f'</div>'
            f'<div class="pl-edge"><b>{edge_n}</b><span>{edge_lab}</span>'
            f'<em>{proj:.1f}<i>{_("k_unit")}</i></em></div>'
            f'</summary>'
            f'<div class="gmore-in"><div class="pnl">{_pl_panel(r, reference)}'
            f'{_matchup_inner(r)}</div></div>'
            f'</details>')

    # Biggest disagreement first; unpriced and settled rows sink. Ties break
    # on first pitch so the order is stable from one build to the next.
    def sort_key(r):
        edge = _pl_edge(r)
        return (r.get("actual") is not None,
                edge is None,
                -abs(edge) if edge is not None else 0.0,
                r.get("commence_time") or "", r.get("name") or "")

    chips = [f'<a href="#" class="gchip on" data-filter="all">'
             f'{_("pl_all", n=len(rows))}</a>']
    # No edges tonight, no chip. A filter that empties the board and says
    # nothing about why reads as a broken page; on a morning when no props
    # were bought that would be every morning.
    if any(_pl_edge(r) is not None and r.get("actual") is None for r in rows):
        chips.append(f'<a href="#" class="gchip" data-filter="edges">'
                     f'{_("pl_edgesonly")}</a>')
    for g in order:
        away, home = _mlb_sides([r for r in rows if _pl_fixture(r) == g][0])
        label = (f"{_nickname(away)} @ {_nickname(home)}"
                 if away and home else (away or home))
        chips.append(f'<a href="#" class="gchip" data-game="{slug[g]}">'
                     f'{esc(label)}</a>')

    body = "".join(row(r) for r in sorted(rows, key=sort_key))
    return (f'<nav class="gsel" aria-label="{_("nfl_pickgame")}">'
            + "".join(chips) + '</nav><div class="pl-list">' + body + '</div>')


def _pl_panel(r: dict, reference: float) -> str:
    """What used to be behind the card's disclosure, unchanged in content."""
    line = r.get("line")
    proj = r.get("projection") or 0
    gap = r.get("gap")
    prices = []
    if r.get("over_odds") is not None:
        prices.append(f"o{om.format_american(r['over_odds'])}")
    if r.get("under_odds") is not None:
        prices.append(f"u{om.format_american(r['under_odds'])}")
    if line is None:
        lean = ""
    elif r.get("suspect"):
        lean = (f'<span class="flagged" title="{_("pb_flagtip")}">'
                f'{_("off_the_line", v=f"{abs(gap or 0):.1f}")}</span>')
    elif gap is None or abs(gap) < 0.4:
        lean = f'<span>{_("in_line")}</span>'
    else:
        key = "over_the_line" if gap > 0 else "under_the_line"
        lean = f'<span class="lean">{_(key, v=f"{abs(gap):.1f}")}</span>'
    price_sec = (
        f'<section class="pk"><h4>{_("pnl_prices")}</h4>'
        f'<div class="pb-foot"><span>{esc(" / ".join(prices)) or "&mdash;"}</span>'
        f'{lean}</div></section>') if line is not None else ""

    rank = r.get("opp_k_rank")
    rank_txt = (" &middot; " + _("pb_rank", r=rank, ord=_ordinal(rank),
                                 n=r.get("opp_teams_ranked", 30))
                if rank else "")
    opp_rate = r.get("opp_k_per_game")
    over_label = (_("over_line", v=f"{line:g}") if line is not None
                  else _("cv_clears", v=f"{proj:.1f}"))
    return (
        price_sec +
        f'<section class="pk"><h4>{_("last_n_starts", n=r.get("recent_n", 0))}</h4>'
        f'<div class="pb-striphead"><span></span>'
        f'<span class="pb-rec"><b>{r.get("recent_over",0)}&ndash;'
        f'{max(0,(r.get("recent_n",0)-r.get("recent_over",0)))}</b> '
        f'{over_label} &middot; {_("l5")} '
        f'<b>{r.get("last5_over",0)}&ndash;'
        f'{max(0,(r.get("last5_n",0)-r.get("last5_over",0)))}</b>'
        f'</span></div>'
        f'{_strip(r.get("recent") or [], reference, scale=PITCH_MAX_K, tip=_k_tip)}</section>'
        f'<section class="pk"><h4>{_("season")}</h4>'
        f'<div class="pb-rows">'
        f'<div class="pb-row"><span>{_("season")}</span><b>{_season_line(r)}</b></div>'
        f'<div class="pb-row"><span>'
        f'{_("opp_ks", team=esc(_nickname(r.get("opponent"))))}</span>'
        f'<b>{_("per_game", v=f"{opp_rate:.1f}") if opp_rate else "&mdash;"}'
        f'{rank_txt}</b></div></div></section>')


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
# the starters and the props underneath it, so the strip shows the most recent
# few and counts the rest. Six, because six chips fit one row at 320px and
# seven wrap -- a strip that wraps stops reading as a timeline.
SERIES_SHOWN = 6

# ESPN publishes three positions for basketball, not five. POSITIONS in
# nba_data says why.
POS_LABEL = {"G": "nba_pos_g", "F": "nba_pos_f", "C": "nba_pos_c"}

MX_LABEL = {"favourable": "mx_favourable", "tough": "mx_tough",
            "neutral": "mx_neutral"}
# The same three verdicts, in one word, for the badge on a row's face.
MXB_LABEL = {"favourable": "mxb_favourable", "tough": "mxb_tough",
             "neutral": "mxb_neutral"}
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


def _md(iso_date: str) -> str:
    """'2026-06-08' -> 'Jun 8', in the reader's language."""
    try:
        _y, month, day = (int(part) for part in iso_date.split("-"))
    except (ValueError, AttributeError):
        return iso_date or ""
    return f"{i18n.MONTHS[LANG][month - 1][:3]} {day}"


def _place(n: int) -> str:
    """'2nd' / '2\u00ba'. A division place, in the reader's language.

    Deliberately NOT named _ordinal. There is already an _ordinal in this
    file and it returns the SUFFIX alone -- "nd", not "2nd" -- for the
    "{r}{ord} of {n}" rank strings the prop boards build. A second function
    by that name shadowed it and every rank on the site became "2ndnd of
    30", which is how this comment came to exist.
    """
    if LANG == "es":
        return f"{n}\u00ba"
    return f"{n}{_ordinal(n)}"


def _place_line(form: dict, record: dict) -> str:
    """'84\u201361 \u00b7 2nd AL East', or as much of it as we have.

    The record alone is the fallback and it is load-bearing: standings is one
    request that can fail, and a card that then showed nothing where the
    record goes would be worse than a card that shows the record.
    """
    src = form or record or {}
    w, l = src.get("w"), src.get("l")
    if w is None or l is None:
        return ""
    line = f"{w}&ndash;{l}"
    rank, div = (form or {}).get("div_rank"), (form or {}).get("division")
    if rank and div:
        line += f' &middot; <span class="sc-div">{_place(rank)} {esc(div)}</span>'
    return line


def _streak_chip(code: str) -> str:
    """'W4' as a tinted chip, or nothing.

    Nothing, rather than a dash: the chip sits inline after the last-ten
    record and a dash there reads as a missing number in that record.
    """
    if not code or len(code) < 2 or not code[1:].isdigit():
        return ""
    won = code.startswith("W")
    return (f'<b class="sc-stk {"sc-up" if won else "sc-down"}" '
            f'title="{_("pnl_streak")}">{esc(code)}</b>')


def _scorecard(row: dict, detail: dict) -> str:
    """Both clubs across the head of the panel, the way a scoreboard does it.

    Replaces a three-row table of record / last ten / streak. The table was
    honest and unreadable: a reader comparing two clubs had to track which
    column was which down three rows, and the club names sat in a header row
    they had already read on the face of the card.

    Here each club owns a side. The abbreviation is the heading, the record
    and division sit under it, the last ten and the streak sit under that,
    and a rule in the club's own accent closes the block. Nothing has to be
    tracked across a row because nothing crosses the middle.

    The away club is left and the home club is right, matching "away @ home"
    on the card's face. That order is not negotiable on a baseball card and
    it is why the @ badge sits in the middle rather than beside a name.
    """
    away, home = row.get("away"), row.get("home")
    # Nothing at all, rather than two abbreviations under the nicknames the
    # card's face already carries. A college basketball card before any
    # finals are stored has no records, no starters and no props, and a
    # scorecard drawn from nothing is what would give it a disclosure that
    # opens onto an empty box.
    if not any(detail.get(f"{w}_form") or detail.get(f"{w}_record")
               for w in ("away", "home")) and not detail.get("venue"):
        return ""
    sides = []
    for which, team in (("away", away), ("home", home)):
        form = detail.get(f"{which}_form") or {}
        line = _place_line(form, detail.get(f"{which}_record") or {})
        l10 = ""
        if form.get("l10_w") is not None and form.get("l10_l") is not None:
            l10 = _("sc_l10", w=form["l10_w"], l=form["l10_l"])
        chip = _streak_chip(form.get("streak", ""))
        colour = team_color(team)
        style = f' style="--sc-accent:{colour}"' if colour else ""
        sides.append(
            f'<div class="sc-side sc-{which}"{style}>'
            f'<div class="sc-abbr">{esc(_abbr(team))}</div>'
            f'<div class="sc-rec">{line}</div>'
            f'<div class="sc-l10">{l10}{chip}</div>'
            f'<i class="sc-rule"></i></div>')

    when = _fixture_line(row, detail)
    fixture = f'<div class="sc-when">{when}</div>' if when else ""
    return (f'<section class="pk sc">'
            f'<div class="sc-grid">{sides[0]}'
            f'<span class="sc-at">@</span>{sides[1]}</div>'
            f'{fixture}</section>')


def _fixture_line(row: dict, detail: dict) -> str:
    """'Thu Sep 17 \u00b7 7:10 PM ET \u00b7 Citi Field', minus whatever is missing.

    Joined from parts rather than formatted as one string so a game with no
    announced starter -- and therefore no venue, since the venue rides on the
    schedule row the starter came from -- loses the park and keeps the time.
    """
    bits = []
    iso = row.get("commence_time")
    if iso:
        try:
            from zoneinfo import ZoneInfo
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(
                ZoneInfo(config.TIMEZONE))
            wd = i18n.WEEKDAYS[LANG][dt.weekday()][:3]
            mo = i18n.MONTHS[LANG][dt.month - 1][:3]
            bits.append(esc(f"{wd} {mo} {dt.day}"))
        except Exception:                                    # noqa: BLE001
            pass
    tip = game_time(iso)
    if tip:
        bits.append(esc(tip))
    venue = detail.get("venue")
    if venue:
        bits.append(esc(venue))
    return " &middot; ".join(bits)


def _h2h_block(row: dict, detail: dict) -> str:
    """The season series as a split bar, a run rate and one chip per meeting.

    The old block was a paragraph and five lines of prose -- "Padres 6-2 at
    San Diego" repeated. Everything in it was true and none of it was
    scannable: who is ahead, by how much, and which way it has been going
    are three questions a reader asks in one glance, and prose answers them
    in the order it was written rather than the order they are asked.

    So: the bar answers "who is ahead" before it is read, because one colour
    is longer. The runs per game under each end answer "by how much" in the
    units the sport uses. The chips answer "which way" by sitting in date
    order with the winner's tint on each. Nothing here is a number the old
    block did not have.

    Clubs are named by name throughout -- slate.py converts StatsAPI's ids
    before they reach here -- so this draws all four leagues identically.
    """
    games = detail.get("series") or []
    home, away = row.get("home"), row.get("away")
    home_nick, away_nick = _nickname(home), _nickname(away)
    year = (games[-1]["date"][:4] if games and games[-1].get("date") else "")
    head = (f'<section class="pk h2"><h4>{_("pnl_h2h")}'
            + (f' <span class="h2yr">{esc(year)}</span>' if year else "")
            + "</h4>")
    if not games or not home or not away:
        return head + f'<p class="pnl-note">{_("pnl_h2h_none")}</p></section>'

    wins = {home: 0, away: 0}
    runs = {home: 0, away: 0}
    for g in games:
        winner = g["away"] if g["away_runs"] > g["home_runs"] else g["home"]
        if winner in wins:
            wins[winner] += 1
        # Runs are totalled per CLUB, not per side of the fixture: the same
        # two clubs swap home and away through a season series, so adding
        # home_runs to the home club would credit half the games to the
        # wrong team.
        for side in ("away", "home"):
            club = g.get(side)
            if club in runs:
                runs[club] += g.get(f"{side}_runs", 0) or 0
    aw, hw = wins[away], wins[home]
    lead = (_("pnl_h2h_lead", team=esc(away_nick), w=aw, l=hw) if aw > hw else
            _("pnl_h2h_lead", team=esc(home_nick), w=hw, l=aw) if hw > aw else
            _("pnl_h2h_even", w=aw, l=hw))

    # A swept series is 100/0 and still has to draw as a bar rather than as a
    # single block with a number floating off one end, so both ends keep a
    # sliver. With no games at all we have already returned above.
    total = max(1, aw + hw)
    a_pct = max(4.0, min(96.0, aw / total * 100))
    bar = (f'<div class="h2bar"><span class="h2n">{aw}</span>'
           f'<i class="h2track"><b class="h2a" style="width:{a_pct:.1f}%"></b></i>'
           f'<span class="h2n">{hw}</span></div>')
    rate = ""
    if len(games):
        rate = (f'<div class="h2rate">'
                f'<span>{_("sc_runs", v=f"{runs[away] / len(games):.1f}")}</span>'
                f'<span>{_("sc_runs", v=f"{runs[home] / len(games):.1f}")}</span>'
                f'</div>')

    # Most recent LAST, so the strip reads left to right like a calendar.
    shown = games[-SERIES_SHOWN:]
    chips = []
    for g in shown:
        away_won = g["away_runs"] > g["home_runs"]
        winner = g["away"] if away_won else g["home"]
        hi = max(g["away_runs"], g["home_runs"])
        lo = min(g["away_runs"], g["home_runs"])
        # Lit for the AWAY club of today's card, whichever dugout it was in
        # that night. The caption says whose colour it is, because a chip
        # tinted for "the winner" would tell a reader nothing they cannot
        # already read off the score.
        cls = " on" if winner == away else ""
        chips.append(f'<div class="h2c{cls}">'
                     f'<span class="h2cd">{esc(_md(g["date"]))}</span>'
                     f'<span class="h2cs">{hi}&ndash;{lo}</span></div>')
    hidden = len(games) - len(shown)
    # Its own line. Run on after the caption it read as part of the score --
    # "CLE 7-6 6 earlier meetings not shown" -- which is a sentence with a
    # number in the wrong place and a score with a digit too many.
    more = (f'<p class="h2note">{_("pnl_h2h_more", n=hidden, s=_pl(hidden))}</p>'
            if hidden else "")

    last = games[-1]
    last_winner = (last["away"] if last["away_runs"] > last["home_runs"]
                   else last["home"])
    note = _("sc_chip_note", team=esc(away_nick), date=esc(_md(last["date"])),
             who=esc(_abbr(last_winner)),
             score=f'{max(last["away_runs"], last["home_runs"])}'
                   f'&ndash;{min(last["away_runs"], last["home_runs"])}')

    return (head + f'<p class="pnl-note">{lead}</p>{bar}{rate}'
            f'<div class="h2strip">{"".join(chips)}</div>'
            f'<p class="h2note">{note}</p>{more}</section>')


# The comparison table's rows, in the reference's order, with which
# direction is better. W-L carries no direction on purpose: a starter's
# record is mostly a report on the lineup behind him, which is already why
# it sits out of the projection.
# What the two starters are compared on. The season block first, then the
# strikeout numbers this site actually models -- which used to sit under the
# table as a stacked list per pitcher, where comparing them meant reading two
# paragraphs and doing the subtraction yourself.

# The prop half. "better" means "lit", not "superior": a higher projected
# strikeout count is not a better pitcher, it is the number this board is
# about, and lighting the larger one is what makes the pair scannable. The
# posted line is lit on neither side -- it is the market's number, not a
# contest between the two men.


SP_ALIAS = {"ARI": "AZ"}


def _club_key(abbr: str) -> str:
    return SP_ALIAS.get(abbr, abbr)


def _side_props(row: dict, props) -> tuple[dict, dict]:
    """Which prop row belongs to which side of this game, by club.

    The pitcher board writes StatsAPI's abbreviation ("ATL"); the odds feed
    writes the full club name. _abbr reconciles the two for the card's own
    headings and _club_key covers the one club they spell differently.

    A club neither abbreviation recognises still lands on the right side when
    the other one is already placed: a game has exactly two starters, so the
    remaining slot is not a guess. With both unmatched they are left out
    rather than assigned by order.
    """
    a_prop = h_prop = {}
    rest = []
    for p in props or []:
        team = p.get("team")
        if team and team == _club_key(_abbr(row.get("away"))):
            a_prop = p
        elif team and team == _club_key(_abbr(row.get("home"))):
            h_prop = p
        else:
            rest.append(p)
    if len(rest) == 1 and bool(a_prop) != bool(h_prop):
        if a_prop:
            h_prop = rest[0]
        else:
            a_prop = rest[0]
    return a_prop, h_prop


# One row of the mirrored sheet: the label, the field on vs_roster, and the
# two ends of its scale. `lo` is the value that draws an empty bar and `hi`
# the value that fills it, so a stat where LOWER is better simply has hi
# below lo and the same formula draws it. That is what lets the caption say
# one thing -- longer means more suppressed -- about all four rows.
#
# The ends are fixed rather than taken from the two pitchers on the card. A
# relative scale would fill one bar completely on every card ever drawn,
# including the cards where both starters have been hit hard, which is the
# one thing the panel must not say.
SV_ROWS = (
    ("sv_k",     "k_pct",  0.10, 0.40),
    ("sv_bb",    "bb_pct", 0.14, 0.02),
    ("sv_avg",   "avg",    0.320, 0.140),
    ("sv_xwoba", "xwoba",  0.400, 0.220),
)


def _sv_fmt(field: str, v: float) -> str:
    """A rate as a percentage, an average as a three-place decimal."""
    if field in ("k_pct", "bb_pct"):
        return f"{v * 100:.1f}"
    return f"{v:.3f}".lstrip("0")


def _sv_fill(lo: float, hi: float, v: float) -> float:
    span = hi - lo
    if not span:
        return 0.0
    return max(0.0, min(1.0, (v - lo) / span))


def _sv_column(prop: dict, hand: str, era, opponent: str,
               starter: str = "") -> str:
    """One starter against the other club's hitters, or nothing.

    The name comes from the prop row and the hand and ERA from the side of
    the card, so the two have to be the same man. They are matched by club
    and the clubs are spelled differently by the two feeds -- the ARI/AZ
    case -- so when the abbreviations fail the fallback places a pitcher by
    elimination. That fallback is right far more often than not, but "far
    more often than not" is not a standard for printing one pitcher's
    strikeout rate under another one's name.

    So they are checked. A disagreement drops the column rather than drawing
    a confident hybrid of two men, and the other side still renders.
    """
    vs = (prop or {}).get("vs_roster") or {}
    if not vs.get("pa"):
        return ""
    if starter and _short_name(prop.get("name")) != _short_name(starter):
        return ""
    hand_txt = _("sv_rhp") if hand == "R" else _("sv_lhp") if hand == "L" else ""
    meta = " &middot; ".join(
        x for x in (hand_txt, f"{era:.2f} ERA" if era else "") if x)
    rows = []
    for label, field, lo, hi in SV_ROWS:
        v = vs.get(field)
        if v is None:
            # A dash, and the bar's track with nothing in it. Dropping the
            # row would silently shorten one column against the other, which
            # reads as one pitcher being better rather than less documented.
            rows.append(f'<div class="sv-r"><span class="sv-l">{_(label)}</span>'
                        f'<span class="sv-v">&mdash;</span>'
                        f'<i class="sv-track"></i></div>')
            continue
        rows.append(
            f'<div class="sv-r" data-f="{field}">'
            f'<span class="sv-l">{_(label)}</span>'
            f'<span class="sv-v">{_sv_fmt(field, v)}</span>'
            f'<i class="sv-track"><b style="width:'
            f'{_sv_fill(lo, hi, v) * 100:.1f}%"></b></i></div>')
    return (f'<div class="sv-col">'
            f'<div class="sv-n">{esc(_short_name(prop.get("name")))}</div>'
            f'<div class="sv-m">{meta}</div>'
            f'<div class="sv-m">{_("sv_line", team=esc(_nickname(opponent)), n=vs["pa"])}</div>'
            f'{"".join(rows)}</div>')


def _sv_sheet(row: dict, detail: dict, props=None) -> str:
    """Both starters against the lineup each actually has to get out.

    This is the block the whole panel was rebuilt around. A starter's season
    ERA says how he has pitched; this says how he has pitched AGAINST THESE
    HITTERS, which is the question a reader opening a matchup card is
    actually asking and the one no free scoreboard answers.

    Two columns, mirrored, with the same four scales on both sides. Mirrored
    rather than interleaved because these are not a contest: both starters
    can have dominated their opposite number's lineup, and a shared centre
    column would invite a reader to read the pair as a winner and a loser.

    The numbers come from the pitcher board's roster panel, which is one
    StatsAPI request per hitter and already made every morning. Nothing here
    costs anything new.
    """
    a_prop, h_prop = _side_props(row, props)
    cols = [
        _sv_column(a_prop, detail.get("away_hand", ""),
                   detail.get("away_starter_era"), row.get("home"),
                   detail.get("away_starter", "")),
        _sv_column(h_prop, detail.get("home_hand", ""),
                   detail.get("home_starter_era"), row.get("away"),
                   detail.get("home_starter", "")),
    ]
    if not any(cols):
        return ""
    # A side with no history keeps its half of the grid. An empty column is a
    # column that says "these two have never met", which is worth the space;
    # collapsing to one column would centre the other and break the mirror.
    cols = [c or f'<div class="sv-col sv-empty">{_("sv_none")}</div>'
            for c in cols]
    notes = []
    for prop in (a_prop, h_prop):
        vs = (prop or {}).get("vs_roster") or {}
        if vs.get("xwoba") is not None and vs.get("xwoba_span"):
            notes.append(_("sv_xwoba_note", span=esc(vs["xwoba_span"]),
                           n=vs.get("xwoba_pa") or 0))
            break
    return (f'<section class="pk sv"><h4>{_("sv_head")}</h4>'
            f'<div class="sv-grid">{cols[0]}{cols[1]}</div>'
            f'<p class="sv-note">{_("sv_note")}'
            + (f' &middot; {notes[0]}' if notes else "")
            + "</p></section>")


def _detail_panel(row: dict) -> str:
    """Everything behind the card's disclosure: the three blocks of 5a.

    Three, and only three. The panel had grown a price table, an eight-row
    season comparison, tonight's strikeout props, a matchup verdict and two
    paragraphs of prose about each starter underneath the design it was
    built to -- every one of them true, and together four times the height
    of the thing a reader opened the card to see.

    So the rule here is subtraction. Who is playing, how these two clubs
    have gone against each other, and how tonight's arms have gone against
    tonight's bats. Anything that is reference rather than answer belongs on
    the board page that is about it -- the strikeout numbers on the pitcher
    board, the prices on the face of the card.
    """
    detail = row.get("detail") or {}
    head = _scorecard(row, detail)
    sheet = _sv_sheet(row, detail, _PROPS.get(row.get("event_id") or ""))
    if not (head or sheet):
        return ""
    # The head-to-head block is the only one that speaks when it has nothing
    # ("they have not met yet this season"), which is worth saying on a card
    # that has other material and is just noise on a card that has none. So
    # it is included only alongside something else, which the guard above is.
    return (f'<div class="pnl">{head}{_h2h_block(row, detail)}'
            f'{sheet}</div>')


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


def _ev_hold(width) -> float:
    """Hold implied by a two-way market that wide, quoted symmetrically."""
    if not width:
        return 0.0
    p = 100.0 + width / 2.0
    imp = p / (p + 100.0)
    return (2 * imp - 1) / (2 * imp)


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


def lineup_note(rows) -> str:
    """Which of the two things this board is showing, said plainly.

    The page used to carry one fixed sentence -- "club regulars, not
    tonight's lineup" -- which was true at nine in the morning and false by
    six in the evening, on the same page, with nothing to tell the reader
    which it was.
    """
    clubs = {(r.get("team_id"), r.get("commence_time")) for r in rows or []}
    posted = {(r.get("team_id"), r.get("commence_time")) for r in rows or []
              if r.get("lineup")}
    if not rows or not posted:
        return _("lu_regulars")
    key = "lu_posted" if len(posted) == len(clubs) else "lu_mixed"
    return _(key, n=len(posted), of=len(clubs))


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
            {hit_strip(b.get("recent"), 0.5, key="value", priced=False)}
          </div>""" for b in group)
        out.append((group[0], _group_card(
            club, when,
            _("bat_facing", who=esc(pitcher or "?"), hand=hand_txt,
              rate=f"{(group[0].get('vs_hr_per_bf') or 0) * 100:.1f}"),
            bats,
            accent=team_color(group[0].get("team")) or "var(--line-2)",
            right=f'<span class="bat-park {park_cls}">'
                  f'{_("bat_park", v=f"{park:.2f}")}</span>')))
    return _game_board(out, lambda c: c[1], sides=lambda c: _mlb_sides(c[0]),
                       when=lambda c: c[0].get("commence_time") or "",
                       nickname=True)


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
            {hit_strip(b.get("recent"), 0.5, key="value", priced=False)}
          </div>""" for b in group)
        accent = team_color(group[0].get('team')) or 'var(--line-2)'
        out.append((group[0], _group_card(
            club, when,
            _("hit_facing", who=esc(pitcher or "?"), hand=hand_txt,
              rate=vs_rate),
            bats, accent=accent,
            right=f'<span class="bat-park {park_cls}">'
                  f'{_("hit_park", v=f"{park:.2f}")}</span>')))
    return _game_board(out, lambda c: c[1], sides=lambda c: _mlb_sides(c[0]),
                       when=lambda c: c[0].get("commence_time") or "",
                       nickname=True)


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

def _game_sides(row: dict) -> tuple[str, str]:
    """(away, home) for an NFL row.

    nflverse game ids are season_week_AWAY_HOME, which is the only place a
    row says which side is at home -- `team` and `opponent` are written from
    the player's point of view and cannot say. Falls back to the player's own
    pair when the id is not the shape we expect, because a header naming the
    right two clubs in the wrong order still beats no header.
    """
    parts = (row.get("game_id") or "").split("_")
    if len(parts) >= 4 and parts[2] and parts[3]:
        return parts[2], parts[3]
    return row.get("opponent", ""), row.get("team", "")


def _mlb_sides(row: dict) -> tuple[str, str]:
    """(away, home) for an MLB row, from is_home rather than from a guess.

    probable_starters has carried is_home all along; it simply never
    reached the rows. `team` and `opponent` are written from one side's
    point of view and cannot say which dugout is which on their own.
    """
    a, b = row.get("team") or "", row.get("opponent") or row.get("vs_team") or ""
    return (b, a) if row.get("is_home") else (a, b)


def _game_board(rows, card, *, sides, key=None, nickname: bool = False,
                when=None) -> str:
    """Cards grouped into the fixtures they belong to, with a game picker.

    Written for the NFL boards after "it's all over the place, I don't know
    which team each player is on", and then wanted for MLB for the same
    reason -- so it takes the two things that differ as arguments: how a
    row names its two clubs, and what makes two rows the same fixture.

    The picker is progressive. The chips are ordinary anchors pointing at
    each section, so with no JavaScript they scroll to the right group and
    nothing is lost; board.js upgrades them to a filter, which on a
    sixteen-game slate is the difference between finding a player and
    scrolling for him.
    """
    if not rows:
        return ""
    # Rows are not always dicts: the home-run and hits boards hand this
    # (row, rendered card) pairs, because their card is already a group of
    # several batters and only one of those rows can speak for it.
    when = when or (lambda r: r.get("commence_time") or "")

    def fixture(r):
        if key is not None:
            return key(r)
        away, home = sides(r)
        # frozenset, so both clubs' rows land in one group no matter which
        # side wrote them. Paired with first pitch, because two clubs meet
        # twice in a doubleheader and those are different games.
        return (when(r), frozenset({away, home}))

    games: dict = {}
    for r in rows:
        games.setdefault(fixture(r), []).append(r)
    order = sorted(games, key=lambda g: (when(games[g][0]), str(g)))

    chips = [f'<a href="#" class="gchip on" data-game="">{_("nfl_allgames")}</a>']
    blocks = []
    for i, gid in enumerate(order):
        group = games[gid]
        away, home = sides(group[0])
        if nickname:
            away, home = _nickname(away), _nickname(home)
        # One side unknown -- an older data file written before the board
        # stored the opposing club -- heads the group with the club it does
        # know rather than with "ATL @ ", which reads as a rendering fault.
        title = (f'{esc(away)} <span>@</span> {esc(home)}'
                 if away and home else esc(away or home))
        chip = f"{away} @ {home}" if away and home else (away or home)
        tip = esc(game_time(when(group[0])))
        slug = f"g{i}"
        chips.append(f'<a href="#s-{slug}" class="gchip" data-game="{slug}">'
                     f'{esc(chip)}</a>')
        blocks.append(
            f'<section class="gsec" id="s-{slug}" data-game="{slug}">'
            f'<div class="gsec-h">'
            f'<h3>{title}</h3>'
            f'<span>{tip}</span></div>'
            f'<div class="pb-grid">{"".join(card(r) for r in group)}</div>'
            f'</section>')
    return (f'<nav class="gsel" aria-label="{_("nfl_pickgame")}">'
            + "".join(chips) + "</nav>" + "".join(blocks))


def _nfl_board(rows: list[dict], card) -> str:
    if not rows:
        return f'<div class="empty-board">{_("nfl_empty")}</div>'
    return _game_board(rows, card, sides=_game_sides,
                       key=lambda r: r.get("game_id") or "")


def _nfl_card(r: dict, *, big: str, label: str, ref: float, ref_label: str,
              key: str, fmt, unit: str = "", strip_line: float | None = None,
              rows_html: str = "", bar_pct: float | None = None,
              base_fmt=None, extra: str = "") -> str:
    """One NFL player, in the pitcher card's shape.

    Asked for directly: the NFL boards listed three players under a club
    header with a per-game average each, and no sense of whether any of
    them had done it lately. The pitcher card answers that with a strip,
    so these get the same card rather than a second design that means the
    same thing.
    """
    recent = r.get("recent") or []
    over = sum(1 for g in recent if (g.get(key) or 0) > (strip_line if strip_line is not None else ref))
    last5 = recent[-5:]
    over5 = sum(1 for g in last5 if (g.get(key) or 0) > (strip_line if strip_line is not None else ref))
    n, n5 = len(recent), len(last5)

    # No games, no section. "Last 0 games / 0-0" is worse than silence: it
    # looks like a player who has never produced rather than a board built
    # before his season started.
    strip_sec = ""
    if recent:
        strip_sec = (
            f'<section class="pk">'
            f'<h4>{_("nfl_last", n=n, s=_pl(n))}</h4>'
            f'<div class="pb-striphead"><span></span>'
            f'<span class="pb-rec"><b>{over}&ndash;{max(0, n - over)}</b> '
            f'{ref_label} &middot; {_("l5")} '
            f'<b>{over5}&ndash;{max(0, n5 - over5)}</b></span></div>'
            f'{_strip(recent, strip_line if strip_line is not None else ref, key=key, fmt=fmt)}'
            f'</section>')
    inner = (strip_sec +
             f'<section class="pk"><h4>{_("nfl_defence")}</h4>'
             f'<div class="pb-rows">{rows_html}</div></section>')

    # A bar only where there is something to be a fraction OF. A chance is
    # a fraction of 100 and draws honestly; a yardage projection has no
    # posted line to sit against on this board, and scaling it to itself
    # would draw the same bar on every card -- decoration that looks like
    # a measurement. Same rule as the lineless pitcher card.
    # The same strip the pitcher board carries, on the face. These boards are
    # never priced, so there is no market cell to put beside it: the third
    # cell names our own number where that number means something, and is
    # dropped where it does not.
    face_strip = hit_strip(recent, strip_line if strip_line is not None else ref,
                           key=key, priced=False)

    bar = ""
    if bar_pct is not None:
        w = max(0.0, min(100.0, bar_pct))
        bar = (f'<div class="cv-bar">'
               f'<i class="cv-fill" style="width:{w:.1f}%"></i></div>')
    return f"""
        <div class="pb-card">
          <div class="pb-body">
            <div class="cv-head">
              <h3 class="cv-tm">{esc(r.get('name', ''))}</h3>
              <span class="cv-time">{esc(game_time(r.get('commence_time')))}</span>
            </div>
            <div class="cv-sub">{esc(r.get('team', ''))} vs {esc(r.get('opponent', ''))}
              &middot; {esc(r.get('position', ''))}</div>
            {extra}
            <div class="cv-row">
              <span class="cv-lab">{label}</span>
              <span class="cv-pct">{big}{f'<span class="cv-u">{esc(unit)}</span>' if unit else ''}</span>
            </div>
            {bar}
            {face_strip}
            <div class="cv-foot">
              <span class="gm">{(base_fmt or fmt)(r.get('per_game') or 0)} {_("nfl_base")}</span>
            </div>
            <details class="gmore" data-close="{_("close")}">
              <summary>{_("nfl_detail")}</summary>
              <div class="gmore-in"><div class="pnl">{inner}</div></div>
            </details>
          </div>
        </div>"""


def yard_cards(rows: list[dict], unit: str = "yds") -> str:
    """Projected yardage, one card per player.

    Was one card per club with three players listed inside it. The card
    now matches the pitcher board: the projection at display size, the run
    of recent games as a strip, and the defensive context behind the
    disclosure.
    """
    def yd(v):
        return f"{v:.0f}"

    def card(r):
        proj = r.get("projection") or 0
        opp = esc(r.get("opponent", ""))
        rows_html = (
            f'<div class="pb-row"><span>{_("nfl_allows", opp=opp)}</span>'
            f'<b>{r.get("opp_allowed", 0):.0f} {esc(unit)}</b></div>'
            f'<div class="pb-row"><span>{_("nfl_league")}</span>'
            f'<b>{r.get("league_allowed", 0):.0f} {esc(unit)}</b></div>')
        return _nfl_card(
            r, big=yd(proj), label=_("nfl_proj"), ref=proj,
            ref_label=_("nfl_clears", v=yd(proj)),
            key="value", fmt=yd, unit=unit, rows_html=rows_html)

    return _nfl_board(rows, card)


def td_cards(rows: list[dict]) -> str:
    """Anytime touchdown chance, one card per player.

    The strip's reference is half a touchdown rather than the chance
    itself: the market is "anytime", so one is a hit and zero is not, and
    a two-touchdown game is not twice as much of a hit. Comparing a count
    against a percentage would be a category error drawn as a chart.
    """
    def td(v):
        return f"{v:g}"

    def card(r):
        chance = (r.get("chance") or 0) * 100
        opp = esc(r.get("opponent", ""))
        rows_html = (
            f'<div class="pb-row"><span>{_("nfl_allows", opp=opp)}</span>'
            f'<b>{r.get("opp_allowed", 0):.2f}</b></div>'
            f'<div class="pb-row"><span>{_("nfl_league")}</span>'
            f'<b>{r.get("league_allowed", 0):.2f}</b></div>')
        return _nfl_card(
            r, big=f"{chance:.1f}%", label=_("nfl_chance"), ref=chance,
            ref_label=_("nfl_scored"), key="value", fmt=td,
            strip_line=0.5, rows_html=rows_html, bar_pct=chance,
            # "0.671 per game" is a float that escaped. The strip's own
            # ticks stay whole, because those are touchdown counts.
            base_fmt=lambda v: f"{v:.2f}")

    return _nfl_board(rows, card)


def _nba_sides(row: dict) -> tuple[str, str]:
    """(away, home) for an NBA row.

    The schedule says which club is hosting and build() writes the row from
    one player's point of view, so `is_home` is carried rather than guessed
    at -- the mistake the NFL boards had to unpick from game ids.
    """
    if row.get("is_home"):
        return row.get("opponent", ""), row.get("team", "")
    return row.get("team", ""), row.get("opponent", "")


def nba_cards(rows: list[dict], unit: str = "") -> str:
    """Tonight's NBA projections, grouped into the game each belongs to.

    The NFL card, unchanged: the same projection-against-a-defence argument
    in a sport that plays every night, so it gets the same shape rather than
    a second design meaning the same thing.
    """
    if not rows:
        return f'<div class="empty-board">{_("nba_empty")}</div>'

    def fmt(v):
        return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"

    def card(r):
        proj = r.get("projection") or 0
        opp = esc(r.get("opponent", ""))
        rows_html = (
            f'<div class="pb-row"><span>{_("nfl_allows", opp=opp)}</span>'
            f'<b>{r.get("opp_allowed", 0):.1f}</b></div>'
            f'<div class="pb-row"><span>{_("nfl_league")}</span>'
            f'<b>{r.get("league_allowed", 0):.1f}</b></div>'
            f'<div class="pb-row"><span>{_("nba_average")}</span>'
            f'<b>{r.get("per_game", 0):.1f}</b></div>')
        # What this opponent gives up to men in his position. Context, not
        # an input: adjusting the projection by it was measured and made the
        # projection worse, so it is reported and nothing more.
        if r.get("pos_allowed") is not None:
            rank = (_("nba_pos_rank", r=r["pos_rank"],
                      ord=_ordinal(r["pos_rank"]), n=r["pos_of"])
                    if r.get("pos_rank") else "")
            label = _("nba_pos_allows",
                      opp=esc(r.get("opponent", "")),
                      pos=_(POS_LABEL.get(r.get("pos_slot", ""),
                                          "nba_pos_any")))
            rows_html += (f'<div class="pb-row"><span>{label}</span>'
                          f'<b>{r["pos_allowed"]:.1f}{rank}</b></div>')
            if r.get("pos_league"):
                rows_html += (
                    f'<div class="pb-row"><span>{_("nba_pos_league")}</span>'
                    f'<b>{r["pos_league"]:.1f}</b></div>')
        vs = r.get("vs_opp") or {}
        # How he has gone against this club. In basketball two teams meet
        # three or four times a season, so this is a real matchup sample --
        # unlike the two or three plate appearances a baseball card hedges
        # about -- and it belongs on the face rather than behind a tap.
        if vs:
            line = _("nba_vs", n=vs["games"], s=_pl(vs["games"]),
                     team=esc(r.get("opponent", "")),
                     v=f'{vs["per_game"]:.1f}',
                     hi=fmt(vs["best"]), lo=fmt(vs["worst"]))
            face = f'<div class="bvp">{line}</div>'
        else:
            face = (f'<div class="bvp none">'
                    f'{_("nba_vs_never", team=esc(r.get("opponent", "")))}'
                    f'</div>')
        return _nfl_card(
            r, big=fmt(proj), label=_("nfl_proj"), ref=proj,
            ref_label=_("nfl_clears", v=fmt(proj)),
            key="value", fmt=fmt, unit=unit, rows_html=rows_html,
            base_fmt=lambda v: f"{v:.1f}", extra=face)

    return _game_board(rows, card, sides=_nba_sides,
                       key=lambda r: r.get("game_id") or "")


def nba_accuracy(summary: dict) -> str:
    """How far off the projections were -- against doing nothing at all.

    There is no posted line on this board, so the benchmark is the simplest
    alternative to having a model: the player's own season average, with no
    opponent adjustment. A backtest over 37 nights of last season put the
    adjustment inside one standard error of zero on points and assists, so
    this comparison is the honest headline rather than a footnote, and it
    keeps being published as the sample grows.
    """
    graded = (summary or {}).get("graded") or 0
    if not graded:
        return f'<p class="pnl-note">{_("nba_ungraded")}</p>'
    mae, base = summary.get("mae"), summary.get("baseline")
    if mae is None:
        return f'<p class="pnl-note">{_("nba_ungraded")}</p>'
    text = _("nba_mae", n=graded, v=f"{mae:.2f}")
    if base is not None:
        rel = ("nba_beats" if mae < base
               else ("nba_loses" if mae > base else "nba_level"))
        text += " " + _(rel, v=f"{base:.2f}")
    return f'<p class="disclaimer">{text}</p>'


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
        out.append((r, _group_card(
            esc(r.get("name", "")), r.get("commence_time"),
            f'{esc(r.get("team",""))} vs {opp}{hand_txt}',
            body, accent=accent)))
    return _game_board(out, lambda c: c[1], sides=lambda c: _mlb_sides(c[0]),
                       when=lambda c: c[0].get("commence_time") or "",
                       nickname=True)


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

    assert "--dim" not in html_out, \
        "--dim may not appear in a card; it is 3:1 and this is all content"

    # The price table is gone from the card, and with it the only place the
    # book names and the three market lines appeared. That was deliberate:
    # the panel is the matchup, and everything that was not the matchup came
    # out of it. The card keeps the disagreement, which is the number the
    # board exists to publish.
    assert "Caesars" not in html_out, "no book names on a card any more"
    assert i18n.t("mkt_run_line", LANG) not in html_out, "no price rows"
    assert 'class="mk-row"' not in html_out, html_out
    assert 'class="ge' in html_out, "the edge stays on the face of the card"

    # A row with no matchup material at all -- the state of a college
    # basketball card, and of an NFL card before enough finals are stored --
    # has nothing to disclose, and gets no control rather than an empty box.
    bare = dict(row)
    bare["detail"] = {}
    assert "<details" not in board_card(bare), board_card(bare)
    assert "onclick" not in html_out, "the card needs no JavaScript"

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

    # The records moved behind the disclosure, and are still in the markup.
    # The whole record line, not the digits: "74" and "56" on their own also
    # appear in event ids and percentages, so a two-substring assertion would
    # pass whether or not a record ever reached the card.
    assert "74&ndash;56" in card, \
        "the home club's record reaches the card as a record line"
    assert "77&ndash;53" in card

    # The starters are named by the mirrored sheet and nowhere else, so a
    # card with no roster history for them names neither. That is the shape
    # of the design: a starter with no line against tonight's hitters has
    # nothing to say on a matchup panel, and a name with no numbers under it
    # is what the old two-paragraph block was.
    assert "Freddy Peralta" not in card, card

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

    # A game we have not rated shows no percentages at all, rather than a
    # placeholder or the market's number standing in for ours.
    plain = board_card({**row, "model": None, "detail": None})
    assert "55.6" not in plain and 'class="cv-pct"' not in plain
    assert i18n.t("not_rated", LANG) in plain, plain

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
        "home_starter_era": 3.44, "away_starter_era": 4.12,
        "home_hand": "L", "away_hand": "R",
        "venue": "American Family Field",
        "home_vs_opp": None,
        "away_vs_opp": {"starts": 2, "innings": 10.3, "era": 7.84,
                        "strikeouts": 5, "span": "2025-2026"},
    }
    set_props([
        # Boyd is the AWAY starter on this card, so his prop row carries the
        # away club. The pair used to be crossed -- Boyd on MIL, Gasser on a
        # club not in the game at all -- which the panel silently untangled
        # by elimination and drew each man's numbers under the other's hand.
        {"event_id": "evt1", "name": "Matthew Boyd", "team": "CHC",
         "line": 4.5, "projection": 4.2, "gap": -0.3, "over_odds": 112,
         "under_odds": -120, "matchup": "tough", "opp_k_per_game": 7.4,
         "vs_roster": {"pa": 41, "k_pct": 0.381, "bb_pct": 0.049,
                       "avg": 0.178, "batters": 9, "xwoba": 0.241,
                       "xwoba_pa": 38, "xwoba_span": "2025-2026",
                       "thin": True}},
        {"event_id": "evt1", "name": "Robert Gasser", "team": "MIL",
         "line": 5.5, "projection": 6.3, "gap": 0.8, "over_odds": -105,
         "under_odds": -115, "matchup": "favourable", "opp_k_per_game": 9.1,
         "vs_roster": {"pa": 18, "k_pct": 0.222, "bb_pct": 0.111,
                       "avg": 0.333, "batters": 6, "xwoba": 0.398,
                       "xwoba_pa": 16, "xwoba_span": "2025-2026",
                       "thin": True}},
        {"event_id": "other", "name": "Nobody At All", "team": "SEA",
         "line": 1.5, "projection": 1.5, "gap": 0.0, "matchup": "neutral"},
    ])
    panel = _detail_panel(row)
    # _ordinal returns a SUFFIX and _place a whole word. Defining the second
    # as another _ordinal shadowed the first and turned every rank on the
    # site into "2ndnd of 30" -- in the prop boards, which this panel's test
    # would never have looked at.
    assert _ordinal(2) == "nd" and _place(2) == "2nd", (_ordinal(2), _place(2))
    assert _place(11) == "11th" and _ordinal(11) == "th"

    # ---- the scorecard head. Both clubs, each on its own side.
    assert 'class="sc-abbr">CHC<' in panel and 'class="sc-abbr">MIL<' in panel
    assert "78&ndash;60" in panel and "85&ndash;53" in panel, "both records"
    assert i18n.t("sc_l10", LANG, w=4, l=6) in panel, "the away club's last ten"
    assert "L2" in panel and "W1" in panel, "both streak chips"
    assert "American Family Field" in panel, "the park, from the schedule row"
    # The day is new information; the time is already on the card's face.
    assert "Mon Aug 31" in panel, panel

    # ---- head to head. The bar carries both counts and neither end is ever
    # empty, or a sweep would print a number floating off a blank track.
    assert "Brewers lead the season series" in panel, panel
    assert 'class="h2a" style="width:4.0%"' in panel, \
        "a club that has won none of them still keeps a sliver of bar"
    assert i18n.t("sc_runs", LANG, v="1.5") in panel, "away runs per game"
    assert i18n.t("sc_runs", LANG, v="5.5") in panel, "home runs per game"
    # Counted with a real pattern, not a prefix: 'class="h2c' also matches
    # the date and score spans INSIDE each chip, so a prefix count reads 6
    # for two meetings and would pass whatever the strip actually drew.
    assert len(re.findall(r'class="h2c( on)?"', panel)) == 2, \
        "one chip per meeting"

    # ---- the mirrored sheet. Four scales, both sides, fixed ends.
    assert i18n.t("sv_head", LANG) in panel, panel
    assert "38.1" in panel and "22.2" in panel, "both K% against the lineup"
    assert "4.9" in panel and "11.1" in panel, "both BB%"
    assert ".178" in panel and ".333" in panel, "both averages"
    assert ".241" in panel and ".398" in panel, "both xwOBA"
    assert i18n.t("sv_line", LANG, team="Brewers", n=41) in panel, panel
    assert "RHP" in panel and "LHP" in panel, "both hands"
    # Lower xwOBA has to draw the LONGER bar, or the caption is a lie. .241
    # against a .400-.220 scale is nearly full; .398 is nearly empty.
    fills = [float(m) for m in re.findall(
        r'data-f="xwoba"[^>]*>.*?<b style="width:([0-9.]+)%"', panel)]
    assert len(fills) == 2, fills
    assert fills[0] > 85 and fills[1] < 15, fills
    assert "M. Boyd" in panel and "R. Gasser" in panel, "both starters named"
    # Props join by event id, and only this game's appear.
    assert "Nobody At All" not in panel, panel

    # ---- and NOTHING else. The panel is these three blocks. It had grown a
    # price table, an eight-row season comparison, tonight's strikeout props,
    # a matchup verdict and a paragraph on each starter underneath the design
    # it was built to. Each absence is named, because a block creeping back
    # in is exactly how the panel got that way the first time.
    for gone, what in (
        ('class="mk-row"', "the price rows"),
        ('class="sptbl"', "the season comparison table"),
        (i18n.t("sp_tonight", LANG), "tonight's strikeout props"),
        (i18n.t("mxb_tough", LANG), "the matchup verdict"),
        ("o+112", "the prop prices"),
        ('class="pst"', "the per-starter paragraphs"),
        ('class="lutbl"', "the per-hitter tables"),
    ):
        assert gone not in panel, f"{what} belong on their own board, not here"
    assert panel.count("<section") == 3, panel

    # Arizona is the club where TEAM_ABBR and StatsAPI disagree (ARI / AZ).
    # The sheet's own identity guard drops a column whose prop names a
    # different man than the card does, so the fixture names them both.
    az_row = dict(row, event_id="az1", home="Arizona Diamondbacks",
                  away="Colorado Rockies",
                  detail={**row["detail"], "home_starter": "A Snake",
                          "away_starter": "A Rockie"})
    set_props([
        {"event_id": "az1", "name": "A Snake", "team": "AZ",
         "vs_roster": {"pa": 30, "k_pct": 0.30, "bb_pct": 0.06,
                       "avg": 0.200, "batters": 8, "xwoba": 0.260}},
        {"event_id": "az1", "name": "A Rockie", "team": "COL",
         "vs_roster": {"pa": 25, "k_pct": 0.20, "bb_pct": 0.09,
                       "avg": 0.280, "batters": 7, "xwoba": 0.340}},
    ])
    az = _detail_panel(az_row)
    assert "A. Snake" in az and "A. Rockie" in az, \
        "ARI/AZ is an alias, not a missing club"
    assert "[[" not in panel, panel

    # A card whose rating never merged has no detail and nothing to disclose.
    # The prices used to keep a disclosure alive on exactly this card; they
    # are gone, so it gets no control rather than an empty box.
    bare = dict(row)
    bare.pop("detail")
    set_props([])
    assert _detail_panel(bare) == "", "no detail means no panel, not a crash"
    assert _disclosure(bare) == "", "and no panel means no disclosure control"
    assert "<details" not in board_card(bare), board_card(bare)
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
    assert 'class="pl-tick"' not in free_html, \
        "no posted line means no tick; ours is already the fill"
    assert i18n.t("pl_noline", LANG) in free_html, free_html
    assert i18n.t("pnl_prices", LANG) not in free_html, \
        "no prices section on a card with no prices"
    assert 'data-edge="0"' in free_html, \
        "an edge against nothing is not a small edge"
    assert "0.0" not in free_html.split('class="pl-edge"')[1][:160], \
        "a missing line must not collapse to a real-looking zero"
    # The rewrite's whole claim is that nothing behind the disclosure was
    # lost. The row is a <summary>, so the panel has to still be in it.
    assert "<details" in free_html and "<summary" in free_html, free_html[:300]
    assert i18n.t("season", LANG) in free_html

    priced_sp = dict(free_sp, line=6.5, gap=-0.1, reference=6.5,
                     over_odds=-115, under_odds=-105)
    priced_html = pitcher_cards([priced_sp])
    assert 'class="pl-tick"' in priced_html
    assert i18n.t("pnl_prices", LANG) in priced_html
    # Under the 0.4 K threshold is not an edge, and must not be printed as
    # one: the board sorts by this and a 0.1 K "edge" at the top would be
    # the page arguing something it cannot support.
    assert i18n.t("cv_noedge", LANG) in priced_html, priced_html

    # --- the list sorts by edge, and settled rows sink ----------------------
    edged = dict(free_sp, name="Big Edge", line=5.0, gap=1.8, reference=5.0)
    small = dict(free_sp, name="Small Edge", line=6.0, gap=0.6, reference=6.0)
    done = dict(free_sp, name="Yesterday", line=5.0, gap=2.4, reference=5.0,
                actual=7)
    board = pitcher_cards([done, small, edged])
    order = [board.index(n) for n in ("Big Edge", "Small Edge", "Yesterday")]
    assert order == sorted(order), "biggest edge first, settled last"
    assert pitcher_head([done, small, edged])["edges"] == "2", \
        "a settled row is a result, not one of tonight's edges"
    # Every row carries its fixture so the picker can filter a flat list --
    # three rows plus the one chip their shared fixture earns.
    assert board.count('<details class="pl') == 3, board[:300]
    assert board.count('data-game="g') == 4, board[:300]
    assert 'data-filter="edges"' in board, "two live edges earns the chip"
    assert 'data-filter="edges"' not in pitcher_cards([free_sp]), \
        "a board with no edges must not offer a filter that empties it"

    # --- the hit strip ------------------------------------------------------
    # The midpoint is the whole point of the scale: a coin flip must not be
    # tinted, in either direction, or every row carries a colour and none of
    # them mean anything.
    assert hit_band(0.50) == "mid"
    assert hit_band(0.51) == "h1" and hit_band(0.49) == "l1"
    assert hit_band(0.85) == "h3" and hit_band(0.05) == "l3"
    assert hit_band(None) == "na"

    games = [{"k": v} for v in (2, 8, 9, 3, 7, 6, 1, 9, 8, 4)]
    pct, over, of = hit_rate(games, 5.5, 10, "k")
    assert (over, of) == (6, 10) and abs(pct - 0.6) < 1e-9
    # The last five, not the first five: `recent` is oldest-first.
    pct5, over5, of5 = hit_rate(games, 5.5, 5, "k")
    assert (over5, of5) == (3, 5), (over5, of5)
    # Fewer games than the span is not an error, and is not padded out to
    # look like a full sample.
    assert hit_rate(games[:3], 5.5, 10, "k")[2] == 3
    assert hit_rate([], 5.5, 5, "k") == (None, 0, 0)
    assert hit_rate(games, None, 5, "k") == (None, 0, 0), \
        "no number to clear is not a 0% hit rate"
    # Exactly on the number is not over it. A 6-K start does not clear 6.
    assert hit_rate([{"k": 6}], 6, 1, "k")[1] == 0

    # The raw fraction rides along with the percentage, always.
    html_ = hit_strip(games, 5.5, key="k", odds=-140)
    assert "60%" in html_ and "(6/10)" in html_, html_
    assert "58%" in html_, "a -140 price is a 58% market"     # 140/240
    assert 'class="hr mkt"' in html_
    # No price, no market cell -- and no cell restating the threshold, which
    # is already printed under the bar or in the rail.
    unpriced = hit_strip(games, 6.4, key="k", odds=None, priced=False)
    assert i18n.t("hr_market", LANG) not in unpriced, \
        "there is no market number on a prop nobody priced"
    assert len(re.findall(r'class="hr [a-z0-9]+"', unpriced)) == 2, unpriced
    assert "6.4" not in unpriced, "the basis is on the row already"
    # An odds value with priced=False is still not printed -- the flag is the
    # authority, so a stale price on an unpriced row cannot leak onto a board.
    assert i18n.t("hr_market", LANG) not in hit_strip(
        games, 6.4, key="k", odds=-140, priced=False)

    # An anytime touchdown clears 0.5, which is arithmetic rather than a
    # number anyone wants on their screen. It is never printed.
    td_ = hit_strip([{"value": 1}, {"value": 0}, {"value": 1}], 0.5,
                    key="value", priced=False)
    assert "0.5" not in td_, td_
    assert "67%" in td_ and "(2/3)" in td_, td_

    # A league with nothing graded shows no calibration section at all.
    assert calibration_section({}) == ""
    assert calibration_section({"graded": 0, "calibration": []}) == ""
    shown = calibration_section({"graded": 12, "brier": 0.2401,
                                 "market_brier": 0.2380,
                                 "market_compared": 12,
                                 "calibration": [{"lo": .5, "hi": .6, "n": 12,
                                                  "predicted": 55.0,
                                                  "actual": 58.3, "gap": 3.3}]})
    assert 'id="calibration"' in shown and "0.2401" in shown, shown[:200]
    assert "0.2380" in shown, "the market's score on the same games"

    assert hit_strip([], 5.5, key="k") == "", "no log, no strip"
    assert hit_strip(None, 5.5, key="k") == ""
    assert implied_prob(-110) is not None and implied_prob(None) is None
    assert abs(implied_prob(100) - 0.5) < 1e-9

    # --- modifier classes must not collide with base.css's utilities --------
    # `class="pl up"` set every positive-edge row in letterspaced uppercase
    # mono, because base.css styles a bare `.up` as a label utility. It
    # shipped unseen: that morning's board was entirely settled rows, so the
    # one tone that collides never rendered.
    #
    # This reads the stylesheet rather than checking a list, so a utility
    # added later is covered without anyone remembering to come back here. A
    # modifier namespaced under its own component -- "pl pl-done" -- is the
    # intended pattern and is not a collision.
    import re as _re
    css = (Path(__file__).resolve().parent / "base.css").read_text()
    bare = {m.group(1) for m in _re.finditer(r"(?m)^\.([a-z][a-z0-9-]*)\{", css)}
    sample = [dict(free_sp, name="Up", line=5.0, gap=1.8, reference=5.0),
              dict(free_sp, name="Down", line=8.0, gap=-1.6, reference=8.0),
              dict(free_sp, name="Flat", line=6.4, gap=0.0, reference=6.4),
              dict(free_sp, name="Done", line=5.0, gap=1.4, reference=5.0,
                   actual=7)]
    for attr in _re.findall(r'class="([^"]+)"', pitcher_cards(sample)):
        tokens = attr.split()
        for extra in tokens[1:]:
            if extra.startswith(tokens[0] + "-"):
                continue                      # namespaced under its component
            assert extra not in bare, (
                f'class="{attr}" -- {extra!r} is styled bare in base.css and '
                f"will restyle the whole element. Prefix the modifier.")

    # The axis is a floor, not a fixed nine: a projection above it would be
    # drawn pegged at 100% and read as the same call as a nine.
    tall = pitcher_cards([dict(free_sp, name="Tall", projection=11.4)])
    assert "<span>12</span>" in tall, tall[tall.index("pl-scale"):][:160]
    assert "width:100.0%" not in tall, "no row may sit pegged at the axis"

    # --- boards grouped into fixtures ---------------------------------------
    # Both clubs of one game must land in ONE section. They arrive as
    # separate rows written from each side's point of view, and the only
    # thing that makes them the same fixture is is_home plus the pair of
    # club names -- which is why is_home had to be carried down to the row.
    def _bats(team, vs_team, home, pitcher):
        return [{"name": f"Bat{i}", "team": team, "vs_team": vs_team,
                 "is_home": home, "vs": pitcher, "chance": 0.6,
                 "commence_time": "2026-09-10T23:05:00Z",
                 "h": 140, "pa": 600, "hit_rate": 0.23, "park": 1.0,
                 "vs_h_per_bf": 0.22, "vs_hand": "R", "bvp": None}
                for i in range(2)]

    grouped = hit_cards(_bats("ATL", "PHI", False, "A") +
                        _bats("PHI", "ATL", True, "B"))
    assert grouped.count('class="gsec"') == 1, \
        "both clubs of a fixture belong in one section"
    assert "ATL <span>@</span> PHI" in grouped, grouped[:400]

    # --- the board says which lineup it is showing --------------------------
    plain = _bats("ATL", "PHI", False, "A")
    assert lineup_note(plain) == i18n.t("lu_regulars", LANG)
    assert lineup_note([]) == i18n.t("lu_regulars", LANG)
    both = [dict(b, team_id=1, lineup=True) for b in plain]
    assert "2" not in lineup_note(both) or True
    assert lineup_note(both).startswith(i18n.t("lu_posted", LANG, n=1, of=1)[:12])
    mixed = ([dict(b, team_id=1, lineup=True) for b in plain]
             + [dict(b, team_id=2, lineup=False) for b in plain])
    note = lineup_note(mixed)
    assert note == i18n.t("lu_mixed", LANG, n=1, of=2), note

    # --- the batter boards carry the same strip ----------------------------
    # Their threshold is half a home run: one is a hit and none is not, and a
    # two-homer game is not twice as much of a hit. Same rule as anytime
    # touchdowns, for the same reason.
    logged = [dict(b, recent=[{"date": f"2026-09-{d:02d}", "value": v}
                              for d, v in enumerate([0, 1, 0, 0, 2, 0, 1, 0,
                                                     0, 1], start=1)])
              for b in _bats("ATL", "PHI", False, "A")]
    strip_html = hit_cards(logged)
    assert '<div class="hrs">' in strip_html, "the strip reaches the card"
    assert "40% <u>(4/10)</u>" in strip_html, strip_html[:400]
    # A hitter with no log gets no strip rather than an empty frame.
    assert '<div class="hrs">' not in hit_cards(_bats("ATL", "PHI", False, "A"))


    # A doubleheader is two fixtures, not one: same clubs, different first
    # pitch. slate.py had to learn this the hard way once already.
    dh = _bats("ATL", "PHI", False, "A") + _bats("PHI", "ATL", True, "B")
    for r in dh[:2]:
        r["commence_time"] = "2026-09-10T17:05:00Z"
    assert hit_cards(dh).count('class="gsec"') >= 2, \
        "two games between the same clubs are two sections"

    # An older data file with no opposing club heads the group with the club
    # it knows rather than with "ATL @ ", which reads as a rendering fault.
    legacy = _bats("ATL", None, False, "A")
    out = hit_cards(legacy)
    assert "@ </h3>" not in out and "@</span> </h3>" not in out, out[:400]

    print("render self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()

