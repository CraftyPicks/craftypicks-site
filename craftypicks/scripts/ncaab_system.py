#!/usr/bin/env python3
"""The owner's college basketball system, as a checklist.

Every game on tonight's slate gets one candidate per tab:

  System    the AWAY team on the full-game spread (moneyline shown too)
  1st Half  the HOME team on an estimated 1H spread -- skipped when the away
            team ranks 50+ places better in BPI ("unless the away team is
            way better")

The candidate is run through the checks below. Each is a pass, a fail, or
n/a (not enough data yet); n/a never counts as a pass. A play posts when a
candidate passes MIN_PASS of them.

Thresholds are the owner's rules turned into numbers. They are starting
points, kept here as named constants so the record can tune them.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MIN_PASS = 4
REB_EDGE = 3.0          # rebounds per game more than the opponent
ATS_RATE = 0.55         # covers in this venue role
ATS_MIN = 4             # graded games in that role before the rate counts
BPI_SPREAD = 10.0       # "spreads are 10+ ..."
BPI_CLOSE = 15          # "... between teams ranked 50th and 60th"
H2H_MIN = 3             # meetings on file before the last-5 counts
H2H_WINS = 3
SCORER_PPG = 14.0
SCORERS_MIN = 3
FORM_N = 5
FORM_WINS = 3
BOX_MIN = 2             # box scores before team averages count
AWAY_WAY_BETTER = 50    # BPI places that make the away team "way better"
TOURNEY_TOP = 25        # postseason: top-25 scoring offence
WIN_UNITS = 100 / 110   # a win at -110

CHECKS = {
    "system": ("reb", "ats", "bpi", "h2h", "depth", "form", "def"),
    "1h":     ("reb", "ats", "h2h", "depth", "form", "def"),
}


# ----------------------------------------------------------------- the store
# data/ncaab_games.json: {"season": 2027, "last_day": "YYYY-MM-DD",
#                         "games": {event_id: parsed event + "box"}}
_KEEP_IF_MISSING = ("spread_home", "ml_home", "ml_away", "total")


def merge_games(store: dict, games: list[dict]) -> int:
    """Add or refresh games. A refresh never blanks a line we already had:
    ESPN drops the odds block from some finals, and the line is what ATS is
    graded on. Returns how many games were new."""
    book = store.setdefault("games", {})
    added = 0
    for g in games:
        eid = g.get("event_id")
        if not eid:
            continue
        old = book.get(eid)
        if old is None:
            book[eid] = dict(g)
            added += 1
            continue
        new = dict(old)
        for k, v in g.items():
            if v is None and k in _KEEP_IF_MISSING:
                continue
            new[k] = v
        book[eid] = new
    return added


def attach_box(store: dict, event_id: str, box: dict) -> None:
    """Hang a parsed box score on its game. The summary's own line fills a
    line the scoreboard never carried."""
    g = store.get("games", {}).get(event_id)
    if g is None or not box:
        return
    g["box"] = {k: v for k, v in box.items() if not k.startswith("_")}
    g["box_v"] = BOX_VERSION
    halves = box.get("_1h") or {}
    if g.get("home_1h") is None and g["home"]["id"] in halves:
        g["home_1h"] = halves[g["home"]["id"]]
        g["away_1h"] = halves.get(g["away"]["id"])
    for k, v in (box.get("_odds") or {}).items():
        if g.get(k) is None and v is not None:
            g[k] = v


def _finals(store: dict) -> list[dict]:
    out = [g for g in store.get("games", {}).values()
           if g.get("completed") and g.get("home_score") is not None]
    return sorted(out, key=lambda g: (g.get("date") or "",
                                      g.get("commence_time") or ""))


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def profiles(store: dict) -> dict:
    """Everything the checks need about every team, from this season."""
    acc: dict[str, dict] = {}

    def team(tid):
        return acc.setdefault(tid, {
            "box": 0, "_reb": [], "_stl": [], "_tov": [], "_forced": [],
            "_players": {}, "_pts": [], "_opp": [], "_ast": [], "_blk": [],
            "_fgm": 0, "_fga": 0, "w": 0, "l": 0, "_ats": [0, 0, 0],
            "_h1f": [], "_h1a": [],
            "ats": {"home": [0, 0], "away": [0, 0]},
            "form": {"home": [], "away": []}})

    for g in _finals(store):
        for role, other in (("home", "away"), ("away", "home")):
            tid, oid = g[role]["id"], g[other]["id"]
            t = team(tid)
            mine, theirs = g[f"{role}_score"], g[f"{other}_score"]
            t["_pts"].append(mine)
            t["_opp"].append(theirs)
            t["w" if mine > theirs else "l"] += 1
            if g.get(f"{role}_1h") is not None and g.get(f"{other}_1h") is not None:
                t["_h1f"].append(g[f"{role}_1h"])
                t["_h1a"].append(g[f"{other}_1h"])
            # Overall ATS for display: every game with a line, neutral too.
            # (The venue splits below, used by the checks, skip neutral.)
            if g.get("spread_home") is not None:
                line_all = g["spread_home"] if role == "home" else -g["spread_home"]
                edge_all = mine - theirs + line_all
                t["_ats"][0 if edge_all > 0 else 1 if edge_all < 0 else 2] += 1
            if not g.get("neutral"):
                t["form"][role].insert(0, "W" if mine > theirs else "L")
                sp = g.get("spread_home")
                if sp is not None:
                    line = sp if role == "home" else -sp
                    edge = mine - theirs + line
                    if edge > 0:
                        t["ats"][role][0] += 1
                    elif edge < 0:
                        t["ats"][role][1] += 1
            box = g.get("box") or {}
            if tid in box and oid in box:
                b, ob = box[tid], box[oid]
                t["box"] += 1
                t["_reb"].append(b.get("reb"))
                t["_stl"].append(b.get("stl"))
                t["_tov"].append(b.get("tov"))
                t["_forced"].append(ob.get("tov"))
                t["_ast"].append(b.get("ast"))
                t["_blk"].append(b.get("blk"))
                if b.get("fgm") is not None and b.get("fga"):
                    t["_fgm"] += b["fgm"]
                    t["_fga"] += b["fga"]
                for pid, pts in (b.get("players") or {}).items():
                    tot = t["_players"].setdefault(pid, [0, 0])
                    tot[0] += pts
                    tot[1] += 1
    out = {}
    for tid, t in acc.items():
        scorers = sum(1 for tot, n in t["_players"].values()
                      if n >= BOX_MIN and tot / n >= SCORER_PPG)
        out[tid] = {
            "box": t["box"], "reb": _mean(t["_reb"]), "stl": _mean(t["_stl"]),
            "tov": _mean(t["_tov"]), "forced": _mean(t["_forced"]),
            "scorers14": scorers, "ppg": _mean(t["_pts"]),
            "opp": _mean(t["_opp"]), "ast": _mean(t["_ast"]),
            "blk": _mean(t["_blk"]),
            "fg": round(100 * t["_fgm"] / t["_fga"], 1) if t["_fga"] else None,
            "w": t["w"], "l": t["l"], "ats_all": t["_ats"],
            "h1": [_mean(t["_h1f"]), _mean(t["_h1a"])] if t["_h1f"] else None,
            "ats": t["ats"], "form": t["form"]}
    return out


def meetings(store: dict, h2h: dict, a: str, b: str) -> list[dict]:
    """Every meeting of a and b on file, newest first, with the winner."""
    seen, out = set(), []
    rows = []
    for tid in (a, b):
        for season_rows in ((h2h.get(tid) or {}).get("seasons") or {}).values():
            rows.extend(season_rows)
    for g in _finals(store):
        rows.append({"date": g["date"], "home_id": g["home"]["id"],
                     "away_id": g["away"]["id"], "home_score": g["home_score"],
                     "away_score": g["away_score"]})
    for r in rows:
        if {r["home_id"], r["away_id"]} != {a, b}:
            continue
        key = (r["date"], r["home_id"], r["away_id"])
        if key in seen or r["home_score"] == r["away_score"]:
            continue
        seen.add(key)
        win = r["home_id"] if r["home_score"] > r["away_score"] else r["away_id"]
        out.append({**r, "winner": win})
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def est_1h(spread_home: float) -> float:
    """Half the full-game spread, to the nearest half point (half away from
    zero, so -7 is -3.5 and -11.5 is -6)."""
    half = abs(spread_home) / 2
    r = math.floor(half * 2 + 0.5) / 2
    return math.copysign(r, spread_home) if r else 0.0


# ---------------------------------------------------------------- the checks
def _ck(key, mark, *v):
    return {"key": key, "mark": mark, "v": list(v)}


def _run(game: dict, side: str, tab: str, prof: dict, bpi: dict,
         meets: list[dict]) -> list[dict]:
    other = "home" if side == "away" else "away"
    me, them = game[side]["id"], game[other]["id"]
    p, q = prof.get(me) or {}, prof.get(them) or {}
    boxed = p.get("box", 0) >= BOX_MIN and q.get("box", 0) >= BOX_MIN
    out = []
    for key in CHECKS[tab]:
        if key == "reb":
            if not boxed:
                out.append(_ck(key, "na"))
            else:
                out.append(_ck(key, "y" if p["reb"] - q["reb"] >= REB_EDGE else "n",
                               p["reb"], q["reb"]))
        elif key == "ats":
            w, l = (p.get("ats") or {}).get(side, [0, 0])
            if w + l < ATS_MIN:
                out.append(_ck(key, "na", w, l, side))
            else:
                out.append(_ck(key, "y" if w / (w + l) >= ATS_RATE else "n",
                               w, l, side))
        elif key == "bpi":
            sp = game.get("spread_home")
            getting = sp if side == "home" else -sp
            ra, rb = bpi.get(me), bpi.get(them)
            if getting < BPI_SPREAD or ra is None or rb is None:
                out.append(_ck(key, "na", ra, rb, getting))
            else:
                out.append(_ck(key, "y" if abs(ra - rb) <= BPI_CLOSE else "n",
                               ra, rb, getting))
        elif key == "h2h":
            last = meets[:FORM_N]
            if len(last) < H2H_MIN:
                out.append(_ck(key, "na", 0, len(last)))
            else:
                won = sum(1 for m in last if m["winner"] == me)
                out.append(_ck(key, "y" if won >= H2H_WINS else "n", won, len(last)))
        elif key == "depth":
            if not boxed:
                out.append(_ck(key, "na"))
            else:
                a, b = p["scorers14"], q["scorers14"]
                out.append(_ck(key, "y" if a >= SCORERS_MIN and a > b else "n", a, b))
        elif key == "form":
            last = ((p.get("form") or {}).get(side) or [])[:FORM_N]
            if len(last) < FORM_WINS:
                out.append(_ck(key, "na", 0, len(last), side))
            else:
                won = last.count("W")
                out.append(_ck(key, "y" if won >= FORM_WINS else "n",
                               won, len(last), side))
        elif key == "def":
            if not boxed:
                out.append(_ck(key, "na"))
            else:
                a = round(p["forced"] - p["tov"], 1)
                b = round(q["forced"] - q["tov"], 1)
                out.append(_ck(key, "y" if a > b else "n", a, b))
    if game.get("postseason"):
        ranked = sorted((t for t in prof if prof[t].get("ppg") is not None),
                        key=lambda t: -prof[t]["ppg"])
        top = set(ranked[:TOURNEY_TOP])
        out.append(_ck("scorer", "y" if me in top else "n", p.get("ppg")))
    return out


def _row(game, tab, side, line, checks, ml=None):
    passed = sum(1 for c in checks if c["mark"] == "y")
    return {"tab": tab, "event_id": game["event_id"], "date": game["date"],
            "commence_time": game.get("commence_time", ""),
            "home": game["home"], "away": game["away"], "side": side,
            "line": line, "est": tab == "1h", "ml": ml,
            "checks": checks, "passed": passed,
            "applicable": sum(1 for c in checks if c["mark"] != "na"),
            "postseason": bool(game.get("postseason")),
            "under_note": bool(game.get("postseason")),
            "total": game.get("total")}


def build(slate: list[dict], store: dict, h2h: dict, bpi: dict) -> list[dict]:
    """Tonight's qualifying plays, both tabs. A game with no line is skipped:
    a play with no number to bet against is not a play."""
    prof = profiles(store)
    rows = []
    for g in slate:
        if g.get("completed") or g.get("spread_home") is None:
            continue
        meets = meetings(store, h2h, g["home"]["id"], g["away"]["id"])
        # System: the road team, full game.
        ck = _run(g, "away", "system", prof, bpi, meets)
        r = _row(g, "system", "away", -g["spread_home"], ck, ml=g.get("ml_away"))
        if r["passed"] >= MIN_PASS:
            rows.append(r)
        # 1st Half: the home team, unless the road team is way better.
        ra, rh = bpi.get(g["away"]["id"]), bpi.get(g["home"]["id"])
        if ra is not None and rh is not None and ra <= rh - AWAY_WAY_BETTER:
            continue
        ck = _run(g, "home", "1h", prof, bpi, meets)
        r = _row(g, "1h", "home", est_1h(g["spread_home"]), ck)
        if r["passed"] >= MIN_PASS:
            rows.append(r)
    rows.sort(key=lambda r: (-r["passed"], r["commence_time"]))
    return rows


# ---------------------------------------------------------- record keeping
def merge(history: list[dict], rows: list[dict]) -> int:
    """Append tonight's plays. A published play is never rewritten."""
    have = {(r["tab"], r["event_id"]) for r in history}
    n = 0
    for r in rows:
        if (r["tab"], r["event_id"]) not in have:
            history.append(dict(r))
            have.add((r["tab"], r["event_id"]))
            n += 1
    return n


def _result(edge: float) -> str:
    return "W" if edge > 0 else "L" if edge < 0 else "P"


def grade(history: list[dict], store: dict) -> int:
    """Settle every play whose game is final.

    System is graded against the CLOSING full-game spread when the store has
    one (the posted number otherwise). 1st Half is graded against the
    estimate we posted -- it is our number, and there is no free real one.
    """
    games = store.get("games", {})
    n = 0
    for r in history:
        if r.get("result"):
            continue
        g = games.get(r["event_id"])
        if not g or not g.get("completed") or g.get("home_score") is None:
            continue
        side = r["side"]
        other = "home" if side == "away" else "away"
        if r["tab"] == "system":
            sp = g.get("spread_home")
            line = (sp if side == "home" else -sp) if sp is not None else r["line"]
            margin = g[f"{side}_score"] - g[f"{other}_score"]
            r["result"] = _result(margin + line)
            r["closing"] = line
            if r.get("ml") is not None:
                r["ml_result"] = "W" if margin > 0 else "L"
        else:
            if g.get(f"{side}_1h") is None or g.get(f"{other}_1h") is None:
                continue
            margin = g[f"{side}_1h"] - g[f"{other}_1h"]
            r["result"] = _result(margin + r["line"])
        r["final"] = [g["away_score"], g["home_score"]]
        n += 1
    return n


def summary(history: list[dict], tab: str) -> dict:
    """W-L-P, units at -110, and how each check has done when it passed."""
    rows = [r for r in history if r.get("tab") == tab]
    done = [r for r in rows if r.get("result")]
    w = sum(1 for r in done if r["result"] == "W")
    l = sum(1 for r in done if r["result"] == "L")
    p = sum(1 for r in done if r["result"] == "P")
    checks: dict[str, list[int]] = {}
    for r in done:
        if r["result"] == "P":
            continue
        for c in r.get("checks", []):
            if c["mark"] == "y":
                tot = checks.setdefault(c["key"], [0, 0])
                tot[0 if r["result"] == "W" else 1] += 1
    return {"w": w, "l": l, "p": p, "pending": len(rows) - len(done),
            "units": round(w * WIN_UNITS - l, 2) if done else 0.0,
            "checks": checks}



# Word-level spellings the Odds API and ESPN disagree on. Applied to both
# feeds alike, so a rule only has to map both spellings to one form -- and
# must never map two different schools to one (the self-test checks every
# ESPN name for collisions).
_WORDS = {"univ": "university", "miss": "mississippi"}
_PHRASES = (("appalachian state", "app state"),)


def name_key(name: str) -> str:
    """A name both feeds agree on. The board's names come from the Odds API
    and these from ESPN; they mostly match, and where they differ it is
    punctuation or abbreviation: "St." / "St" / "State", "A&M" / "A and M",
    "SIU-Edwardsville" / "SIU Edwardsville", "Univ." / "University".
    A leading "St" is Saint (St. John's); anywhere else it is State."""
    import re  # noqa: PLC0415
    n = str(name or "").lower().replace("&", " and ").replace("-", " ")
    n = re.sub(r"[^a-z0-9 ]+", "", n)
    words = n.split()
    words = [("state" if w == "st" and i > 0 else _WORDS.get(w, w))
             for i, w in enumerate(words)]
    n = " ".join(words)
    for a, b in _PHRASES:
        n = n.replace(a, b)
    return n


def team_sheet(store: dict, bpi: dict | None = None) -> dict:
    """Season averages for the board's Team Stats panel, keyed by name_key.

    Points and points against come from every final; the box-score rows
    (FG%, rebounds, assists, blocks, steals) from the finals that have a box
    score, and are None until one does. Name, colour and rank are taken from
    the team's most recent game; the record is counted from our own finals,
    so it can never disagree with the averages beside it.
    """
    prof = profiles(store)
    latest: dict[str, dict] = {}
    for g in sorted(store.get("games", {}).values(),
                    key=lambda g: (g.get("date") or "", g.get("commence_time") or "")):
        for role in ("home", "away"):
            latest[g[role]["id"]] = g[role]
    out = {}
    for tid, p in prof.items():
        club = latest.get(tid) or {}
        if not club.get("name"):
            continue
        boxed = p.get("box", 0) > 0
        out[name_key(club["name"])] = {
            "id": tid, "name": club["name"], "color": club.get("color", ""),
            "rank": club.get("rank"), "record": f"{p['w']}-{p['l']}",
            "bpi": (bpi or {}).get(tid),
            "games": p["w"] + p["l"],
            "stats": {"ats": p["ats_all"], "h1": p["h1"],
                      "pts": p["ppg"], "opp": p["opp"],
                      "fg": p["fg"] if boxed else None,
                      "reb": p["reb"] if boxed else None,
                      "ast": p["ast"] if boxed else None,
                      "blk": p["blk"] if boxed else None,
                      "stl": p["stl"] if boxed else None}}
    return out


# ---------------------------------------------------------------- daily run
SEASON_MONTHS = (11, 12, 1, 2, 3, 4)
SCOREBOARD_DAYS = 14     # days walked per run when catching up
SUMMARY_CAP = 400        # box scores fetched per run
SCHEDULE_CAP = 300       # past-season schedules fetched per run
H2H_SEASONS = 4          # past seasons searched for head-to-head
BOX_TRIES = 3
# Bumped whenever parse_box starts capturing a new stat: every stored box
# below this version is fetched once more. 2 added FG, assists and blocks.
BOX_VERSION = 2


def season_for(day) -> int:
    """ESPN names a season by the year it ends: 2026-27 is 2027."""
    return day.year + 1 if day.month >= 7 else day.year


def _load(path: Path, default):
    import json  # noqa: PLC0415
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _save(path: Path, payload, compact: bool = False) -> None:
    import json  # noqa: PLC0415
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            if compact else json.dumps(payload, indent=2, ensure_ascii=False))
    path.write_text(text + "\n")


def daily(day, data, fetch=None) -> dict | None:
    """The whole NCAAB System run: fetch, store, grade, pick, publish.

    Free (ESPN only) and idempotent -- the store only grows, a published play
    is never rewritten, a graded one never regraded -- so run_daily calls it
    on every invocation, above the paid-odds guard.

    Returns a small dict for the log, or None out of season (nothing fetched,
    nothing written).
    """
    import datetime as dt  # noqa: PLC0415
    if day.month not in SEASON_MONTHS:
        return None
    if fetch is None:
        import espn_cbb as fetch  # noqa: PLC0415
    data = Path(data)
    season = season_for(day)
    one = dt.timedelta(days=1)

    store = _load(data / "ncaab_games.json", {})
    if store.get("season") != season:
        store = {"season": season, "last_day": None, "games": {}}

    # 1. Scoreboards: from the last day we closed out, up to today.
    if store.get("last_day"):
        start = dt.date.fromisoformat(store["last_day"])
    else:
        start = day - one * (SCOREBOARD_DAYS - 1)
    stop = min(day, start + one * (SCOREBOARD_DAYS - 1))
    slate: list[dict] | None = None
    closed = start - one                 # last day fetched without a failure
    d = start
    while d <= stop:
        got = fetch.scoreboard(d.strftime("%Y%m%d"))
        if got is None:
            break                        # never skip past a failed day
        games = [g for g in got if g.get("season") in (None, season)]
        merge_games(store, games)
        if d == day:
            slate = games
        closed = d
        d += one
    if slate is None and closed < day:   # caught short: tonight anyway
        slate = fetch.scoreboard(day.strftime("%Y%m%d"))
        if slate is not None:
            merge_games(store, slate)
    if closed >= start:
        store["last_day"] = min(closed, day - one).isoformat()

    # 2. Box scores for finals that do not have one yet.
    boxes = 0
    for g in _finals(store):
        if boxes >= SUMMARY_CAP:
            break
        current = g.get("box") and g.get("box_v", 1) >= BOX_VERSION
        if current or g.get("box_tries", 0) >= BOX_TRIES:
            continue
        box = fetch.summary(g["event_id"])
        boxes += 1
        if box:
            attach_box(store, g["event_id"], box)
        else:
            g["box_tries"] = g.get("box_tries", 0) + 1

    # 3. BPI. Yesterday's table beats none.
    bpi_doc = _load(data / "ncaab_bpi.json", {})
    stale = bpi_doc if bpi_doc.get("season") == season else {}
    if hasattr(fetch, "bpi_full"):
        ranks, raw_values = fetch.bpi_full(season)
    else:
        ranks, raw_values = fetch.bpi(season), {}
    ranks = ranks or stale.get("ranks") or {}
    # BPI by team name, for the board: its rows come from the Odds API, which
    # has names, not ESPN ids. Yesterday's values beat none.
    values = ({name_key(v["name"]): v["bpi"] for v in raw_values.values()
               if v.get("name")} or stale.get("values") or {})

    # 4. Head to head: past seasons, through the home team's schedule.
    #    Past seasons never change, so each is fetched once, ever.
    h2h = _load(data / "ncaab_h2h.json", {})
    calls = 0
    for g in slate or []:
        tid = g["home"]["id"]
        entry = h2h.setdefault(tid, {"seasons": {}})
        have = entry["seasons"]
        # An empty answer is either a failed call or a team with no season
        # that year; the two look identical. Retry on a later day, three
        # times at most, and never twice in one day.
        tried = entry.setdefault("tried", {})
        for past in range(season - H2H_SEASONS, season):
            key = str(past)
            last = tried.get(key) or [0, ""]
            if (key in have or calls >= SCHEDULE_CAP
                    or last[0] >= BOX_TRIES or last[1] == day.isoformat()):
                continue
            rows = fetch.schedule(tid, past)
            calls += 1
            if rows:
                have[key] = rows
                tried.pop(key, None)
            else:
                tried[key] = [last[0] + 1, day.isoformat()]

    # 5. Grade, pick, publish.
    doc = _load(data / "ncaab_system.json", {})
    history = doc.get("history") or []
    graded = grade(history, store)
    picks = build(slate or [], store, h2h, ranks)
    added = merge(history, picks)
    if slate is None:
        # Tonight's scoreboard did not answer. Keep what this morning
        # already published rather than blanking the page.
        rows = doc.get("rows", []) if doc.get("date") == day.isoformat() else []
    else:
        tonight = {g["event_id"] for g in slate}
        rows = [r for r in history if r["event_id"] in tonight]
    rows.sort(key=lambda r: (-r["passed"], r.get("commence_time") or ""))

    _save(data / "ncaab_games.json", store, compact=True)
    _save(data / "ncaab_h2h.json", h2h, compact=True)
    neutral = sorted(f'{name_key(g["away"]["name"])}@{name_key(g["home"]["name"])}'
                     for g in slate or [] if g.get("neutral"))
    # Offence/defence (for a projected score) and the league's points per
    # team per game, which the projection is built around.
    offdef = ({name_key(v["name"]): [v["off"], v["def"]] for v in raw_values.values()
               if v.get("name") and v.get("off") is not None
               and v.get("def") is not None} or stale.get("offdef") or {})
    pts = [s for g in _finals(store) for s in (g["home_score"], g["away_score"])]
    avg_pts = round(sum(pts) / len(pts), 1) if pts else stale.get("avg_pts")
    _save(data / "ncaab_bpi.json", {"season": season, "ranks": ranks,
                                    "values": values, "neutral": neutral,
                                    "offdef": offdef, "avg_pts": avg_pts},
          compact=True)
    _save(data / "ncaab_teams.json", {"season": season,
                                      "teams": team_sheet(store, ranks)},
          compact=True)
    _save(data / "ncaab_system.json", {
        "date": day.isoformat(),
        "date_label": f"{day:%A, %B %-d, %Y}",
        "rows": rows,
        "summary": {tab: summary(history, tab) for tab in CHECKS},
        "history": history,
    })
    return {"games": len(store["games"]), "boxes": boxes, "slate": len(slate or []),
            "plays": len(rows), "new": added, "graded": graded}


# ------------------------------------------------------------------ fixtures
def _club(tid):
    return {"id": tid, "name": f"Team {tid}", "abbr": f"T{tid}"}


def _game(eid, home, away, hs=None, as_=None, spread=None, date="2026-11-10",
          h1=None, a1=None, neutral=False, postseason=False, ml=(None, None)):
    done = hs is not None
    return {"event_id": eid, "date": date, "commence_time": date + "T23:00Z",
            "season": 2027, "season_type": 2, "neutral": neutral,
            "postseason": postseason, "completed": done,
            "home": _club(home), "away": _club(away),
            "home_score": hs, "away_score": as_, "home_1h": h1, "away_1h": a1,
            "spread_home": spread, "ml_home": ml[0], "ml_away": ml[1],
            "total": 140.5}


def _box(home, away, h_reb, a_reb, h_stl=6, a_stl=6, h_tov=10, a_tov=10,
         h_players=None, a_players=None):
    return {home: {"reb": h_reb, "stl": h_stl, "tov": h_tov,
                   "players": h_players or {"h1": 10}},
            away: {"reb": a_reb, "stl": a_stl, "tov": a_tov,
                   "players": a_players or {"a1": 10}}}


def _season():
    """Team A (the road side tonight) against team H, with a season behind
    each that passes every check for A unless a test breaks one."""
    store = {"season": 2027, "games": {}}
    deep = {"p1": 16, "p2": 15, "p3": 14, "p4": 5}
    thin = {"q1": 30, "q2": 8}
    games = []
    # A on the road: five road wins, all covers.
    for i in range(5):
        games.append((_game(f"a{i}", f"x{i}", "A", 60, 70, spread=-2.0,
                            date=f"2026-11-0{i+1}"),
                      _box(f"x{i}", "A", 30, 40, h_tov=14, a_tov=8,
                           a_players=deep)))
    # H at home: 1-4, no covers.
    for i in range(5):
        games.append((_game(f"h{i}", "H", f"y{i}", 60, 70, spread=-5.0,
                            date=f"2026-11-0{i+1}"),
                      _box("H", f"y{i}", 33, 33, h_tov=12, a_tov=12,
                           h_players=thin)))
    for g, b in games:
        merge_games(store, [g])
        attach_box(store, g["event_id"], b)
    # Head to head: A won 3 of the last 4 meetings (past seasons).
    h2h = {"A": {"seasons": {"2026": [
        {"date": "2026-01-10", "home_id": "H", "away_id": "A", "home_score": 60, "away_score": 66},
        {"date": "2025-01-10", "home_id": "A", "away_id": "H", "home_score": 70, "away_score": 60},
        {"date": "2024-01-10", "home_id": "H", "away_id": "A", "home_score": 50, "away_score": 61},
        {"date": "2023-01-10", "home_id": "A", "away_id": "H", "home_score": 50, "away_score": 61},
    ]}}}
    tonight = _game("t1", "H", "A", spread=-11.5, date="2026-11-12",
                    ml=(-700, 480))
    bpi = {"A": 55, "H": 48}
    return store, h2h, bpi, tonight


def _marks(row):
    return {c["key"]: c["mark"] for c in row["checks"]}



def _test_daily() -> None:
    import datetime as dt
    import json
    import tempfile

    class Fake:
        calls = {"scoreboard": 0, "summary": 0, "schedule": 0, "bpi": 0}

        def __init__(self):
            self.days = {}

        def scoreboard(self, day):
            self.calls["scoreboard"] += 1
            return [dict(g) for g in self.days.get(day, [])]

        def summary(self, eid):
            self.calls["summary"] += 1
            g = self.box_for.get(eid)
            return dict(g) if g else {}

        def schedule(self, tid, season):
            self.calls["schedule"] += 1
            return self.sched.get((tid, season), [])

        def bpi(self, season):
            self.calls["bpi"] += 1
            return {"A": 55, "H": 48}

        def bpi_full(self, season):
            return self.bpi(season), {
                "A": {"bpi": 2.5, "name": "Team A", "off": 1.5, "def": 1.0},
                "H": {"bpi": 4.0, "name": "Team H", "off": None, "def": None}}

    store, h2h, bpi, tonight = _season()
    f = Fake()
    # Yesterday's finals are the fixture season; tonight is A at H.
    finals = list(store["games"].values())
    f.days = {"20261111": [{k: v for k, v in g.items() if k not in ("box", "box_v")}
                           for g in finals],
              "20261112": [tonight]}
    f.box_for = {g["event_id"]: dict(g["box"]) for g in finals}
    f.sched = {("H", 2026): h2h["A"]["seasons"]["2026"]}

    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        day = dt.date(2026, 11, 12)
        # Out of season: nothing fetched, nothing written.
        assert daily(dt.date(2026, 8, 1), data, fetch=f) is None
        assert not any(data.iterdir())
        # Catch-up starts no earlier than SCOREBOARD_DAYS back.
        out = daily(day, data, fetch=f)
        assert out["plays"] >= 1, out
        assert f.calls["scoreboard"] == SCOREBOARD_DAYS, f.calls
        assert f.calls["summary"] == len(finals)
        doc = json.loads((data / "ncaab_system.json").read_text())
        assert doc["date"] == "2026-11-12"
        assert [r["tab"] for r in doc["rows"]] == ["system"]
        assert doc["summary"]["system"]["pending"] == 1
        games = json.loads((data / "ncaab_games.json").read_text())
        assert games["season"] == 2027 and games["last_day"] == "2026-11-11"
        cache = json.loads((data / "ncaab_h2h.json").read_text())
        assert "2026" in cache["H"]["seasons"]
        # BPI values by name for the board, and tonight's neutral sites.
        bdoc = json.loads((data / "ncaab_bpi.json").read_text())
        assert bdoc["values"] == {"team a": 2.5, "team h": 4.0}
        assert bdoc["neutral"] == [], "t1 is a true home game"
        assert bdoc["offdef"] == {"team a": [1.5, 1.0]}, "only teams with both"
        # League average points per team per game, from this season's finals.
        assert bdoc["avg_pts"] == 65.0, bdoc["avg_pts"]
        sheet = json.loads((data / "ncaab_teams.json").read_text())
        assert sheet["teams"][name_key("Team A")]["stats"]["reb"] == 40.0

        # A box stored before assists/blocks/FG were captured is fetched once
        # more, then left alone.
        games = json.loads((data / "ncaab_games.json").read_text())
        del games["games"]["a0"]["box_v"]
        (data / "ncaab_games.json").write_text(json.dumps(games))
        f.box_for["a0"] = {k: dict(v, ast=12, blk=2, fgm=20, fga=50)
                           for k, v in f.box_for["a0"].items()}
        before = f.calls["summary"]
        daily(day, data, fetch=f)
        assert f.calls["summary"] - before == 1, ("only the old-format box", f.calls["summary"] - before)
        games = json.loads((data / "ncaab_games.json").read_text())
        assert games["games"]["a0"]["box"]["A"]["ast"] == 12

        # Second run the same day: two scoreboards (yesterday, today), no
        # boxes refetched, no duplicate play.
        before = dict(f.calls)
        out = daily(day, data, fetch=f)
        assert f.calls["scoreboard"] - before["scoreboard"] == 2
        assert f.calls["summary"] == before["summary"]
        assert f.calls["schedule"] == before["schedule"], "past seasons are cached"
        doc = json.loads((data / "ncaab_system.json").read_text())
        assert len(doc["history"]) == 1

        # Next day: tonight's game is final, so the play grades.
        f.days["20261112"] = [dict(tonight, completed=True, home_score=70,
                                   away_score=60, home_1h=30, away_1h=30)]
        f.days["20261113"] = []
        daily(dt.date(2026, 11, 13), data, fetch=f)
        doc = json.loads((data / "ncaab_system.json").read_text())
        assert doc["history"][0]["result"] == "W", doc["history"][0]
        assert doc["rows"] == [] and doc["summary"]["system"]["w"] == 1

    # A failed scoreboard (None) is not an empty day: the walk stops there,
    # last_day stays put, and the next run fetches it again.
    store, h2h, bpi, tonight = _season()
    f = Fake()
    finals = list(store["games"].values())
    f.box_for = {g["event_id"]: dict(g["box"]) for g in finals}
    f.sched = {("H", 2026): h2h["A"]["seasons"]["2026"]}
    f.days = {"20261108": [{k: v for k, v in g.items() if k not in ("box", "box_v")}
                           for g in finals],
              "20261111": [], "20261112": [tonight]}
    real = f.scoreboard
    down = {"20261110"}
    f.scoreboard = lambda d: None if d in down else real(d)
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        daily(dt.date(2026, 11, 12), data, fetch=f)
        games = json.loads((data / "ncaab_games.json").read_text())
        assert games["last_day"] == "2026-11-09", games["last_day"]
        doc = json.loads((data / "ncaab_system.json").read_text())
        assert doc["rows"] and doc["rows"][0]["event_id"] == "t1", \
            "tonight's slate is still fetched when an older day failed"
        down.clear()
        before = f.calls["scoreboard"]
        daily(dt.date(2026, 11, 12), data, fetch=f)
        assert f.calls["scoreboard"] - before == 4, "11-09 to 11-12 again"
        games = json.loads((data / "ncaab_games.json").read_text())
        assert games["last_day"] == "2026-11-11"
        # Today itself failing keeps the plays already published today.
        down.add("20261112")
        daily(dt.date(2026, 11, 12), data, fetch=f)
        doc = json.loads((data / "ncaab_system.json").read_text())
        assert doc["rows"] and doc["rows"][0]["event_id"] == "t1"


def _test_team_sheet() -> None:
    store = {"season": 2027, "games": {}}
    g1 = _game("s1", "UVA", "ARK", 66, 106, date="2026-11-05")
    g1["home"].update(name="Virginia Cavaliers", color="f84c1e", rank=9, record="1-0")
    g1["away"].update(name="Arkansas Razorbacks", color="9d2235", rank=12, record="1-0")
    g2 = _game("s2", "UVA", "X", 80, 60, date="2026-11-07")
    g2["home"].update(name="Virginia Cavaliers", color="f84c1e", rank=8, record="2-0")
    for g in (g1, g2):
        merge_games(store, [g])
    box = lambda reb, ast, blk, stl, fgm, fga: {"reb": reb, "ast": ast, "blk": blk,
                                                 "stl": stl, "tov": 10, "fgm": fgm,
                                                 "fga": fga, "players": {}}
    attach_box(store, "s1", {"UVA": box(38, 20, 3, 14, 25, 50),
                             "ARK": box(43, 19, 7, 16, 40, 72)})
    attach_box(store, "s2", {"UVA": box(41, 23, 4, 16, 30, 58),
                             "X": box(30, 10, 1, 5, 20, 60)})
    sheet = team_sheet(store, {"UVA": 14})
    uva = sheet[name_key("Virginia Cavaliers")]
    assert uva["bpi"] == 14
    assert sheet[name_key("Arkansas Razorbacks")]["bpi"] is None, "no rank, no guess"
    assert uva["name"] == "Virginia Cavaliers" and uva["games"] == 2
    assert uva["rank"] == 8, "latest rank wins"
    assert uva["record"] == "1-1", "record is counted from the finals we hold"
    assert uva["color"] == "f84c1e"
    st = uva["stats"]
    assert st["pts"] == 73.0 and st["opp"] == 83.0
    assert st["reb"] == 39.5 and st["ast"] == 21.5 and st["blk"] == 3.5
    assert st["stl"] == 15.0
    assert st["fg"] == round(100 * 55 / 108, 1), "FG% from totals, not a mean of games"
    # First half: average points scored and allowed before halftime.
    store["games"]["s1"].update(home_1h=30, away_1h=50)
    store["games"]["s2"].update(home_1h=41, away_1h=25)
    h1 = team_sheet(store)[name_key("Virginia Cavaliers")]["stats"]["h1"]
    assert h1 == [35.5, 37.5], h1
    assert team_sheet(store)[name_key("Arkansas Razorbacks")]["stats"]["h1"] == [50.0, 30.0]
    # ATS over every game with a line, neutral sites included; W-L-P.
    store["games"]["s1"]["spread_home"] = -3.0    # UVA lost by 40 laying 3
    store["games"]["s2"]["spread_home"] = -20.0   # UVA won by 20 laying 20: push
    sheet2 = team_sheet(store)
    assert sheet2[name_key("Virginia Cavaliers")]["stats"]["ats"] == [0, 1, 1]
    assert sheet2[name_key("Arkansas Razorbacks")]["stats"]["ats"] == [1, 0, 0]
    ark = sheet[name_key("Arkansas Razorbacks")]
    assert ark["stats"]["pts"] == 106.0 and ark["stats"]["opp"] == 66.0
    # A team with a final but no box score still gets points, not box stats.
    merge_games(store, [_game("s3", "Y", "Z", 70, 65, date="2026-11-07")])
    y = team_sheet(store)[name_key("Team Y")]
    assert y["stats"]["pts"] == 70.0 and y["stats"]["reb"] is None
    # Odds API and ESPN spell some names differently.
    assert name_key("St. John's Red Storm") == name_key("St John's Red Storm")
    assert name_key("Texas A&M Aggies") == name_key("Texas A and M Aggies")
    assert name_key("  Virginia  Cavaliers ") == name_key("virginia cavaliers")
    # The six that went unrated on 2026-11-09: Odds API spelling vs ESPN's.
    for odds, espn in (("SIU-Edwardsville Cougars", "SIU Edwardsville Cougars"),
                       ("Boston Univ. Terriers", "Boston University Terriers"),
                       ("Illinois St Redbirds", "Illinois State Redbirds"),
                       ("Oregon St Beavers", "Oregon State Beavers"),
                       ("Appalachian St Mountaineers", "App State Mountaineers"),
                       ("Miss Valley St Delta Devils", "Mississippi Valley State Delta Devils")):
        assert name_key(odds) == name_key(espn), (odds, name_key(odds), name_key(espn))
    # "St." at the front is Saint, not State.
    assert name_key("St. John's Red Storm") == "st johns red storm"
    # Distinct schools must stay distinct.
    assert name_key("Mississippi State Bulldogs") != name_key("Mississippi Valley State Delta Devils")
    assert name_key("Boston College Eagles") != name_key("Boston University Terriers")
    assert name_key("Illinois Fighting Illini") != name_key("Illinois State Redbirds")


def _self_test() -> None:
    _test_team_sheet()
    _test_daily()
    store, h2h, bpi, tonight = _season()

    # ---- profiles
    prof = profiles(store)
    assert prof["A"]["reb"] == 40.0 and prof["H"]["reb"] == 33.0
    assert prof["A"]["scorers14"] == 3 and prof["H"]["scorers14"] == 1
    assert prof["A"]["ats"]["away"] == [5, 0]
    assert prof["H"]["ats"]["home"] == [0, 5]
    assert prof["A"]["form"]["away"][:5] == ["W"] * 5
    assert prof["A"]["forced"] == 14.0 and prof["A"]["tov"] == 8.0

    # ---- meetings: newest first, both teams' caches and this season
    m = meetings(store, h2h, "A", "H")
    assert [x["date"] for x in m] == ["2026-01-10", "2025-01-10",
                                      "2024-01-10", "2023-01-10"]
    assert m[0]["winner"] == "A" and m[1]["winner"] == "A"

    # ---- est 1H line
    assert est_1h(-11.5) == -6.0 and est_1h(-7.0) == -3.5
    assert est_1h(3.0) == 1.5 and est_1h(-1.0) == -0.5 and est_1h(0.0) == 0.0

    # ---- System: every check passes for A
    rows = build([tonight], store, h2h, bpi)
    sysrow = next(r for r in rows if r["tab"] == "system")
    assert sysrow["side"] == "away" and sysrow["line"] == 11.5
    assert sysrow["ml"] == 480
    assert _marks(sysrow) == {"reb": "y", "ats": "y", "bpi": "y", "h2h": "y",
                              "depth": "y", "form": "y", "def": "y"}, _marks(sysrow)
    assert sysrow["passed"] == 7 and sysrow["applicable"] == 7
    assert sysrow["home"]["name"] == "Team H"

    # 1st Half: the candidate is H, who fails nearly everything -> no play.
    assert not any(r["tab"] == "1h" for r in rows)

    # ---- thresholds: exactly 4 posts, 3 does not.
    def with_passes(n_fail):
        s, hh, b, t = _season()
        # Break checks one at a time: bpi, then h2h, then form.
        if n_fail >= 1:
            b = {"A": 80, "H": 20}            # 60 places apart
        if n_fail >= 2:
            hh = {}
        if n_fail >= 3:
            t = dict(t, spread_home=-11.5)
            for i in range(3):                # three road losses, newest
                g = _game(f"z{i}", f"w{i}", "A", 80, 60, spread=-2.0,
                          date=f"2026-11-1{i}")
                merge_games(s, [g])
        if n_fail >= 4:
            s2 = {"season": 2027, "games": {}}
            for eid, g in s["games"].items():
                g = dict(g)
                if g.get("box") and "A" in g["box"]:
                    g["box"] = dict(g["box"], A=dict(g["box"]["A"], reb=20))
                s2["games"][eid] = g
            s = s2
        return [r for r in build([t], s, hh, b) if r["tab"] == "system"]
    assert with_passes(0) and with_passes(0)[0]["passed"] == 7
    r3 = with_passes(3)
    assert r3 and r3[0]["passed"] == 4, r3 and _marks(r3[0])
    assert _marks(r3[0])["bpi"] == "n" and _marks(r3[0])["h2h"] == "na"
    assert _marks(r3[0])["form"] == "n"
    assert with_passes(4) == [], "3 passes must not post"

    # BPI rule only speaks on 10+: a 6-point spread is n/a, not a fail.
    small = dict(tonight, spread_home=-6.0)
    r = next(r for r in build([small], store, h2h, bpi) if r["tab"] == "system")
    assert _marks(r)["bpi"] == "na" and r["applicable"] == 6

    # n/a on an empty season: nothing posts.
    assert build([tonight], {"season": 2027, "games": {}}, {}, {}) == []

    # No line, no play.
    assert build([dict(tonight, spread_home=None)], store, h2h, bpi) == []

    # ---- 1st Half: flip the roles so the HOME side is the strong one.
    flip = _game("t2", "A", "H", spread=-4.0, date="2026-11-12")
    s2, hh2, _b, _t = _season()
    # A also needs home history for the 1H venue checks.
    for i in range(5):
        g = _game(f"ah{i}", "A", f"v{i}", 80, 60, spread=-3.0,
                  date=f"2026-10-2{i}")
        merge_games(s2, [g])
        attach_box(s2, g["event_id"], _box("A", f"v{i}", 40, 30, h_tov=8,
                                           a_tov=14, h_players={"p1": 16, "p2": 15, "p3": 14}))
    rows = build([flip], s2, hh2, {"A": 40, "H": 45})
    h1 = next(r for r in rows if r["tab"] == "1h")
    assert h1["side"] == "home" and h1["line"] == -2.0 and h1["est"] is True
    assert "bpi" not in _marks(h1)
    # Way better away team -> no 1H play at all.
    rows = build([flip], s2, hh2, {"A": 90, "H": 30})
    assert not any(r["tab"] == "1h" for r in rows)

    # ---- postseason: tournament scorer check + unders note
    post = dict(tonight, postseason=True)
    r = next(r for r in build([post], store, h2h, bpi) if r["tab"] == "system")
    assert "scorer" in _marks(r) and r["under_note"] is True
    assert "scorer" not in _marks(sysrow) and sysrow["under_note"] is False

    # ---- merge never overwrites, grade against the closing number
    hist: list[dict] = []
    assert merge(hist, [sysrow]) == 1 and merge(hist, [sysrow]) == 0
    final = dict(tonight, completed=True, home_score=70, away_score=60,
                 home_1h=30, away_1h=31, spread_home=-11.5)
    store["games"]["t1"] = final
    assert grade(hist, store) == 1 and grade(hist, store) == 0
    assert hist[0]["result"] == "W", "lost by 10 getting 11.5 is a cover"
    assert hist[0]["ml_result"] == "L"
    # Push.
    hist2 = []
    merge(hist2, [sysrow])
    store["games"]["t1"] = dict(final, home_score=71.5 - 0.0, away_score=60)
    store["games"]["t1"]["home_score"] = 72
    store["games"]["t1"]["away_score"] = 60
    store["games"]["t1"]["spread_home"] = -12.0
    grade(hist2, store)
    assert hist2[0]["result"] == "P", hist2[0]
    # 1H graded on the posted estimate.
    h1row = dict(h1, event_id="t1")
    hist3 = []
    merge(hist3, [h1row])
    store["games"]["t1"] = dict(final, home=_club("A"), away=_club("H"),
                                home_1h=40, away_1h=37)
    grade(hist3, store)
    assert hist3[0]["result"] == "W", "won the half by 3 laying 2"

    # ---- summary
    hist = [dict(sysrow, result="W"), dict(sysrow, event_id="b", result="L"),
            dict(sysrow, event_id="c", result="W"), dict(sysrow, event_id="d", result="P"),
            dict(sysrow, event_id="e")]
    s = summary(hist, "system")
    assert (s["w"], s["l"], s["p"], s["pending"]) == (2, 1, 1, 1)
    assert math.isclose(s["units"], 2 * WIN_UNITS - 1, abs_tol=0.005)
    assert s["checks"]["reb"] == [2, 1]
    assert summary(hist, "1h")["w"] == 0

    print("ncaab_system self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
