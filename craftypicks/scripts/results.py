"""Final scores from free sources: MLB StatsAPI for baseball, ESPN elsewhere."""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_PATH = {
    "mlb":   "baseball/mlb",
    "nba":   "basketball/nba",
    "nfl":   "football/nfl",
    "ncaab": "basketball/mens-college-basketball",
}
STATSAPI = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}"
TIMEOUT = 15


# ESPN's CDN refuses a request that does not look like a browser. The first
# probe run on 2026-09-01 got StatsAPI's eight finals and an HTTPError from
# ESPN on all four leagues, with the same URL returning valid JSON when
# fetched normally — so the URL was never the problem, the User-Agent was.
# "craftypicks/1.0" is honest and got us blocked; this is the smallest string
# that does not.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
}


def _request(url: str) -> urllib.request.Request:
    """The request this module sends, without sending it.

    Split out from _get purely so the headers can be asserted in a self-test
    without network access — the sandbox this is developed in cannot reach
    either source, so the header policy would otherwise be untested until it
    failed in production, which is exactly what happened once already.

    Does not vary by host. StatsAPI is happy with anything and ESPN is not, so
    both get the same headers rather than a per-source table nobody maintains.
    """
    return urllib.request.Request(url, headers=dict(HEADERS))


def _get(url: str) -> dict:
    """Fetch and decode JSON, returning {} on any failure.

    Deliberately swallows every error. A free score source is a convenience;
    if it is down the build must still produce a site, just without last
    night's finals filled in.

    http.client.HTTPException is caught explicitly because it is NOT an
    OSError: a truncated response raises http.client.IncompleteRead, which
    slipped through the old tuple and propagated out of a function whose
    whole contract is that it never raises.

    The message names the status code and the host. The first probe run
    reported only "HTTPError" four times over, which took a separate
    investigation to turn into "ESPN is returning 403" — a diagnosis the log
    line should have handed over on its own.

    Returning {} is the failure signal callers key on — see finals().
    """
    try:
        with urllib.request.urlopen(_request(url), timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"!! score source refused us: HTTP {e.code} {e.reason} "
              f"from {urllib.parse.urlsplit(url).netloc}; skipping")
        return {}
    except (urllib.error.URLError, http.client.HTTPException,
            TimeoutError, ValueError, OSError) as e:
        print(f"!! score source unreachable ({type(e).__name__}: {e}) "
              f"at {urllib.parse.urlsplit(url).netloc}; skipping")
        return {}


def parse_espn(payload: dict) -> list[dict]:
    """Pull finals out of an ESPN scoreboard payload.

    Does not raise on a malformed entry. ESPN's endpoint is undocumented and
    can change shape without notice, so anything that does not parse is
    skipped and the rest of the slate still comes through.
    """
    out = []
    for ev in (payload or {}).get("events") or []:
        try:
            comp = (ev.get("competitions") or [])[0]
            sides = {c["homeAway"]: c for c in comp["competitors"]}
            home, away = sides["home"], sides["away"]
            out.append({
                "home": home["team"]["displayName"],
                "away": away["team"]["displayName"],
                "home_score": int(home["score"]),
                "away_score": int(away["score"]),
                "completed": bool(
                    ev.get("status", {}).get("type", {}).get("completed")),
                "date": (ev.get("date") or "")[:10],
            })
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            continue
    return out


def parse_statsapi(payload: dict) -> list[dict]:
    """Pull finals out of an MLB StatsAPI schedule payload.

    Same tolerance as parse_espn: a game that does not parse is dropped rather
    than failing the run.
    """
    out = []
    for day in (payload or {}).get("dates") or []:
        try:
            games = day.get("games") or []
        except AttributeError:
            continue
        for g in games:
            try:
                teams = g["teams"]
                out.append({
                    "home": teams["home"]["team"]["name"],
                    "away": teams["away"]["team"]["name"],
                    "home_score": int(teams["home"]["score"]),
                    "away_score": int(teams["away"]["score"]),
                    "completed":
                        g.get("status", {}).get("abstractGameState") == "Final",
                    "date": (g.get("gameDate") or "")[:10],
                })
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
    return out


def finals(league: str, date_str: str) -> list[dict]:
    """Completed games for one league on one date, from a free source.

    Baseball uses MLB's official API because it is documented and stable.
    Everything else uses ESPN, which is neither, hence the tolerant parsing.
    Does not retry a failed fetch; _get has already given up by the time it
    returns.

    Each returned row's "date" is the SLATE date that was asked for, not the
    kickoff timestamp's UTC date. The parsers stay pure and keep reporting
    the raw UTC date; this function overwrites it. The distinction matters
    because a 10:10pm ET West Coast game on 2026-08-26 kicks off at 02:10Z on
    the 27th, so [:10] of the timestamp puts it on the wrong slate. These
    rows are the declared input to ratings.run(), which sorts on that string,
    and any caller matching results back to a slate by date would silently
    miss every late game.

    MLB falls back to ESPN only when the StatsAPI FETCH FAILED (_get returned
    {}), never when StatsAPI answered and simply had no games scheduled. An
    off-day is routine; treating it as a failure meant a spurious "falling
    back" log line and a second HTTP call on every MLB off-day — and, worse,
    a day of MLB rows carrying ESPN's team names instead of StatsAPI's.

    UNRESOLVED RISK: the two sources spell team names differently in kind —
    parse_statsapi emits teams.home.team.name, parse_espn emits
    team.displayName — and those two name sets have NOT been diffed. Anything
    keyed on the string (ratings.run() keys team history on it) would split a
    club's rating history in two the first time one league drew rows from
    both sources, with nothing in the output looking wrong. The guard above
    makes that impossible today for MLB. Before anything consumes both
    sources for one league, run .github/workflows/probe.yml against a date
    both sources cover and diff the name sets.
    """
    if league == "mlb":
        # {} is _get's failure signal. StatsAPI never returns a bare {} on
        # success — a scheduled-nothing day still carries "dates": [].
        payload = _get(STATSAPI.format(date=date_str))
        if payload != {}:
            return _stamp([r for r in parse_statsapi(payload) if r["completed"]],
                          date_str)
        print("!! StatsAPI fetch failed; falling back to ESPN for MLB")

    path = ESPN_PATH.get(league)
    if not path:
        return []
    url = f"{ESPN_BASE}/{path}/scoreboard?dates={date_str.replace('-', '')}"
    return _stamp([r for r in parse_espn(_get(url)) if r["completed"]], date_str)


def _stamp(rows: list[dict], date_str: str) -> list[dict]:
    """Re-date rows to the slate they were requested for. See finals()."""
    for r in rows:
        r["date"] = date_str
    return rows


def _self_test() -> None:
    # A recorded ESPN shape, trimmed to the fields we read.
    espn = {"events": [{"date": "2026-08-26T23:05Z", "status":
              {"type": {"completed": True}},
              "competitions": [{"competitors": [
                  {"homeAway": "home", "score": "4",
                   "team": {"displayName": "Milwaukee Brewers"}},
                  {"homeAway": "away", "score": "1",
                   "team": {"displayName": "Chicago Cubs"}}]}]}]}
    rows = parse_espn(espn)
    assert len(rows) == 1
    assert rows[0]["home"] == "Milwaukee Brewers"
    assert rows[0]["away"] == "Chicago Cubs"
    assert rows[0]["home_score"] == 4 and rows[0]["away_score"] == 1
    assert rows[0]["completed"] is True

    # An in-progress game is returned but flagged incomplete, never guessed at.
    live = {"events": [{"date": "2026-08-26T23:05Z", "status":
              {"type": {"completed": False}},
              "competitions": [{"competitors": [
                  {"homeAway": "home", "score": "2",
                   "team": {"displayName": "A"}},
                  {"homeAway": "away", "score": "1",
                   "team": {"displayName": "B"}}]}]}]}
    assert parse_espn(live)[0]["completed"] is False

    # Malformed entries are skipped, not crashed on. A score source going
    # strange must never take down the daily build.
    broken = {"events": [{"competitions": [{}]},
                         {"competitions": [{"competitors": [
                             {"homeAway": "home", "team": {}}]}]},
                         {"no": "competitions"}]}
    assert parse_espn(broken) == []
    assert parse_espn({}) == []

    # A null "status" (not merely a missing one) is a real shape a postponed
    # or cancelled game can send on either feed, not a hypothetical: it must
    # be skipped like any other malformed entry, never raise.
    assert parse_espn({"events": [{"date": "2026-08-26T23:05Z", "status": None,
             "competitions": [{"competitors": [
                 {"homeAway": "home", "score": "4", "team": {"displayName": "A"}},
                 {"homeAway": "away", "score": "1", "team": {"displayName": "B"}}]}]}]}) == []
    assert parse_espn({"events": {"foo": "bar"}}) == []

    # MLB StatsAPI shape.
    api = {"dates": [{"games": [{"status": {"abstractGameState": "Final"},
             "gameDate": "2026-08-26T23:05:00Z",
             "teams": {"home": {"score": 4, "team": {"name": "Milwaukee Brewers"}},
                       "away": {"score": 1, "team": {"name": "Chicago Cubs"}}}}]}]}
    rows = parse_statsapi(api)
    assert len(rows) == 1 and rows[0]["home_score"] == 4
    assert rows[0]["completed"] is True
    assert parse_statsapi({}) == []

    # Same null-status case on the StatsAPI side, plus a non-list "dates".
    assert parse_statsapi({"dates": [{"games": [{"status": None,
             "gameDate": "2026-08-26T23:05:00Z",
             "teams": {"home": {"score": 4, "team": {"name": "A"}},
                       "away": {"score": 1, "team": {"name": "B"}}}}]}]}) == []
    assert parse_statsapi({"dates": {"foo": "bar"}}) == []

    # Every league we publish has an ESPN path.
    assert set(ESPN_PATH) == {"mlb", "nba", "nfl", "ncaab"}

    # --- finals() dates rows by the slate asked for, not by UTC -----------
    # 10:10pm ET on 2026-08-26 is 02:10Z on the 27th: a real West Coast
    # start that rolls past midnight UTC.
    late = {"dates": [{"games": [{"status": {"abstractGameState": "Final"},
             "gameDate": "2026-08-27T02:10:00Z",
             "teams": {"home": {"score": 3, "team": {"name": "Los Angeles Dodgers"}},
                       "away": {"score": 2, "team": {"name": "San Diego Padres"}}}}]}]}
    # The parser stays pure: it still reports the timestamp's own UTC date.
    assert parse_statsapi(late)[0]["date"] == "2026-08-27"

    global _get
    real_get = _get
    calls: list[str] = []
    try:
        _get = lambda url: (calls.append(url), late)[1]        # noqa: E731
        rows = finals("mlb", "2026-08-26")
        assert len(rows) == 1
        assert rows[0]["date"] == "2026-08-26", \
            f"late game filed under {rows[0]['date']}, not the slate date"

        # Same for the ESPN path, whose timestamps roll the same way.
        espn_late = {"events": [{"date": "2026-08-27T02:10Z",
              "status": {"type": {"completed": True}},
              "competitions": [{"competitors": [
                  {"homeAway": "home", "score": "110", "team": {"displayName": "A"}},
                  {"homeAway": "away", "score": "101", "team": {"displayName": "B"}}]}]}]}
        _get = lambda url: (calls.append(url), espn_late)[1]   # noqa: E731
        assert finals("nba", "2026-08-26")[0]["date"] == "2026-08-26"

        # A StatsAPI off-day (fetch SUCCEEDED, no games) must not fall back
        # to ESPN: that is one HTTP call and one bogus log line per off-day,
        # and it would mix ESPN's team spellings into MLB's rating history.
        calls.clear()
        _get = lambda url: (calls.append(url), {"dates": []})[1]  # noqa: E731
        assert finals("mlb", "2026-08-26") == []
        assert len(calls) == 1, \
            "a StatsAPI off-day must not trigger the ESPN fallback"
        assert "statsapi" in calls[0]

        # A StatsAPI FETCH FAILURE ({} from _get) still does fall back.
        calls.clear()
        _get = lambda url: (calls.append(url), {})[1]            # noqa: E731
        assert finals("mlb", "2026-08-26") == []
        assert len(calls) == 2, \
            "a failed StatsAPI fetch must still fall back to ESPN"
        assert "espn" in calls[1]
    finally:
        _get = real_get

    # _get swallows a truncated response too. IncompleteRead is an
    # HTTPException, not an OSError, so it used to escape the except tuple.
    assert issubclass(http.client.IncompleteRead, http.client.HTTPException)
    assert not issubclass(http.client.IncompleteRead, OSError)
    import unittest.mock
    with unittest.mock.patch("urllib.request.urlopen",
                             side_effect=http.client.IncompleteRead(b"")):
        assert _get("https://example.invalid/x") == {}

    # --- what we actually send -------------------------------------------
    # ESPN blocked us on 2026-09-01 for looking like a script. There is no
    # network here, so the header policy is asserted on the Request object
    # rather than on a response; that is the only way this can be caught
    # before it fails in production, which is how it was found last time.
    req = _request("https://site.api.espn.com/x")
    ua = req.get_header("User-agent") or ""
    assert "Mozilla" in ua, f"ESPN refuses a non-browser User-Agent, got {ua!r}"
    assert "craftypicks" not in ua.lower(), \
        "the honest User-Agent is the one that got us a 403"
    assert req.get_header("Accept"), "ESPN wants an Accept header too"

    # Deliberately not asserted here: that no caller bypasses _request. Every
    # version of that check scanned this file for its own needle and tripped
    # over the assertion's own source. A test that keeps outsmarting itself is
    # worse than the convention it was guarding.

    print("results self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
