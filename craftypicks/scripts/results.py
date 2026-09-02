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

# The Odds API's own sport keys, duplicated here rather than imported from
# leagues.py so this module stays a leaf: it is imported by the daily job, by
# the results store and by a probe workflow, and none of them should have to
# drag the site's league configuration along to ask for a score.
SPORT_KEY = {
    "mlb":   "baseball_mlb",
    "nba":   "basketball_nba",
    "nfl":   "americanfootball_nfl",
    "ncaab": "basketball_ncaab",
}
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


def parse_odds_scores(events: list[dict], date_str: str) -> list[dict]:
    """Pull finals out of an Odds API /scores response.

    ESPN's scoreboard was the free source for every league but baseball, and
    it answers a GitHub runner with 403 Forbidden — a browser User-Agent did
    not change that, and the same URL serves fine from elsewhere, so it is the
    caller's address being refused rather than the request. Rather than fight
    a CDN indefinitely, the three non-baseball leagues buy their scores: two
    credits per league per day, about 180 a month against a 20,000 allowance.
    The free-source detour existed to save credits, and credits turned out not
    to be the scarce thing.

    Rows are filtered to the requested date and stamped with it, matching what
    finals() guarantees. Deliberately does not use the event's own
    commence_time as the row's date: a late West Coast game kicks off after
    midnight UTC and would land on the wrong slate.

    Does not grade anything. grade.py reads the same endpoint for its own
    purposes and keys on event id; this returns the flat shape the results
    store and the Elo engine consume.
    """
    out = []
    for ev in events or []:
        try:
            if not ev.get("completed"):
                continue
            if (ev.get("commence_time") or "")[:10] != date_str:
                continue
            home, away = ev.get("home_team"), ev.get("away_team")
            by_name = {}
            for s in ev.get("scores") or []:
                by_name[s["name"]] = int(float(s["score"]))
            if home not in by_name or away not in by_name:
                continue
            out.append({
                "home": home,
                "away": away,
                "home_score": by_name[home],
                "away_score": by_name[away],
                "completed": True,
                "date": date_str,
            })
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


def finals(league: str, date_str: str, client=None) -> list[dict]:
    """Completed games for one league on one date.

    Baseball uses MLB's official API: free, documented, and stable. The other
    three used ESPN's scoreboard until 2026-09-01, when it began answering a
    GitHub runner with 403 Forbidden — a browser User-Agent did not change it
    and the same URL serves fine from elsewhere, so it is our address being
    refused and no header will fix it. They now buy their scores instead, at
    two credits a league a day, which needs a client.

    Pass `client` (an OddsClient) to enable the paid path. Without one the
    non-baseball leagues return nothing rather than reaching for ESPN: a
    source that refuses us is not a fallback, it is a second failure and a
    wasted fifteen-second timeout. This is the ONE place that knows where a
    league's scores come from — an earlier version put the paid path in the
    caller, and the probe workflow went on testing ESPN and reporting a
    failure that no longer meant anything.

    Does not retry a failed fetch; _get has already given up by the time it
    returns, and the paid client has its own budget guard.

    Each returned row's "date" is the SLATE date that was asked for, not the
    kickoff timestamp's UTC date. The parsers stay pure and keep reporting
    the raw UTC date; this function overwrites it. The distinction matters
    because a 10:10pm ET West Coast game on 2026-08-26 kicks off at 02:10Z on
    the 27th, so [:10] of the timestamp puts it on the wrong slate. These
    rows are the declared input to ratings.run(), which sorts on that string,
    and any caller matching results back to a slate by date would silently
    miss every late game.

    REMAINING NAME RISK, now narrowed to one league: the three paid leagues
    draw both their odds and their scores from the Odds API, so their club
    names agree by construction. Baseball does not — the board names come
    from the Odds API and these rows come from MLB StatsAPI, and those two
    sets have not been diffed. Nothing consumes both today, because MLB is
    rated by slate.py rather than from this store. Before anything does, run
    .github/workflows/probe.yml and compare them.
    """
    if league == "mlb":
        # {} is _get's failure signal. StatsAPI never returns a bare {} on
        # success — a scheduled-nothing day still carries "dates": [].
        payload = _get(STATSAPI.format(date=date_str))
        if payload == {}:
            print("!! StatsAPI fetch failed; no baseball finals today")
            return []
        return _stamp([r for r in parse_statsapi(payload) if r["completed"]],
                      date_str)

    if client is None:
        print(f"!! no client given, so no paid scores for {league}; skipping")
        return []

    sport_key = SPORT_KEY.get(league)
    if not sport_key:
        return []
    return parse_odds_scores(client.scores(sport_key), date_str)


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

        # The paid path rolls the same way. A 10:10pm PT tip-off is 02:10Z the
        # next day, and parse_odds_scores filters on commence_time, so the
        # late game has to be asked for under ITS OWN UTC date and then filed
        # under the slate date the caller wanted. This is the seam where an
        # off-by-one-day bug would hide.
        class LateClient:
            def scores(self, sport_key, days_from=2):
                return [{"id": "L", "commence_time": "2026-08-26T23:10:00Z",
                         "completed": True, "home_team": "A", "away_team": "B",
                         "scores": [{"name": "A", "score": "110"},
                                    {"name": "B", "score": "101"}]}]

        late_rows = finals("nba", "2026-08-26", client=LateClient())
        assert len(late_rows) == 1
        assert late_rows[0]["date"] == "2026-08-26"

        # A StatsAPI off-day (fetch SUCCEEDED, no games) is not a failure and
        # must not reach for anything else. There is no fallback left, so the
        # thing to pin is that it makes exactly one call and returns nothing.
        calls.clear()
        _get = lambda url: (calls.append(url), {"dates": []})[1]  # noqa: E731
        assert finals("mlb", "2026-08-26") == []
        assert len(calls) == 1, "an MLB off-day must make exactly one call"
        assert "statsapi" in calls[0]

        # A StatsAPI FETCH FAILURE ({} from _get) used to fall back to ESPN.
        # It no longer does, because ESPN refuses this machine: the fallback
        # was a guaranteed second failure and a fifteen-second timeout on top
        # of the first. Baseball simply has no finals that morning.
        calls.clear()
        _get = lambda url: (calls.append(url), {})[1]            # noqa: E731
        assert finals("mlb", "2026-08-26") == []
        assert len(calls) == 1, \
            "a failed StatsAPI fetch must not chase a source that blocks us"
        assert "statsapi" in calls[0]
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

    # --- the paid path, for the leagues ESPN refuses ----------------------
    paid = [
        {"id": "a", "commence_time": "2026-09-01T17:00:00Z", "completed": True,
         "home_team": "Chicago Bears", "away_team": "Green Bay Packers",
         "scores": [{"name": "Chicago Bears", "score": "24"},
                    {"name": "Green Bay Packers", "score": "17"}]},
        # Still in progress: not a result, and Elo would read a 0-0 as a tie.
        {"id": "b", "commence_time": "2026-09-01T20:00:00Z", "completed": False,
         "home_team": "Buffalo Bills", "away_team": "Houston Texans",
         "scores": [{"name": "Buffalo Bills", "score": "3"},
                    {"name": "Houston Texans", "score": "0"}]},
        # A different day. /scores returns a window, not a single date, so
        # this filter is what keeps a row off the wrong slate.
        {"id": "c", "commence_time": "2026-08-31T17:00:00Z", "completed": True,
         "home_team": "Detroit Lions", "away_team": "Minnesota Vikings",
         "scores": [{"name": "Detroit Lions", "score": "10"},
                    {"name": "Minnesota Vikings", "score": "20"}]},
    ]
    rows = parse_odds_scores(paid, "2026-09-01")
    assert len(rows) == 1, rows
    r = rows[0]
    assert r["home"] == "Chicago Bears" and r["home_score"] == 24
    assert r["away_score"] == 17 and r["completed"] is True
    assert r["date"] == "2026-09-01", "the row carries the slate date asked for"

    # A score list that does not name both clubs is not a result.
    half = [{"id": "d", "commence_time": "2026-09-01T17:00:00Z",
             "completed": True, "home_team": "A", "away_team": "B",
             "scores": [{"name": "A", "score": "7"}]}]
    assert parse_odds_scores(half, "2026-09-01") == []

    # Malformed entries are skipped, not raised on — this runs unattended.
    assert parse_odds_scores([{"completed": True}], "2026-09-01") == []
    assert parse_odds_scores(None, "2026-09-01") == []
    assert parse_odds_scores([{"id": "e", "commence_time": "2026-09-01T1",
                               "completed": True, "home_team": "A",
                               "away_team": "B",
                               "scores": "not a list"}], "2026-09-01") == []

    # The same shape both parsers produce, so the store cannot tell them apart.
    assert set(rows[0]) == {"home", "away", "home_score", "away_score",
                            "completed", "date"}

    # --- finals() is the one place that knows where scores come from ------
    class FakeClient:
        def __init__(self): self.asked = []
        def scores(self, sport_key, days_from=2):
            self.asked.append(sport_key)
            return [{"id": "z", "commence_time": "2026-09-01T17:00:00Z",
                     "completed": True, "home_team": "Chicago Bears",
                     "away_team": "Green Bay Packers",
                     "scores": [{"name": "Chicago Bears", "score": "24"},
                                {"name": "Green Bay Packers", "score": "17"}]}]

    fc = FakeClient()
    rows = finals("nfl", "2026-09-01", client=fc)
    assert fc.asked == ["americanfootball_nfl"], fc.asked
    assert len(rows) == 1 and rows[0]["home_score"] == 24

    # Without a client the paid leagues return nothing rather than reaching
    # for ESPN, which refuses us and costs a fifteen-second timeout to learn.
    assert finals("nfl", "2026-09-01") == []

    # Baseball never touches the client — its source is free.
    fc2 = FakeClient()
    finals("mlb", "2026-09-01", client=fc2)
    assert fc2.asked == [], "MLB must not spend credits; StatsAPI is free"

    # An unknown league is not an error and does not spend anything.
    fc3 = FakeClient()
    assert finals("cricket", "2026-09-01", client=fc3) == []
    assert fc3.asked == []

    assert set(SPORT_KEY) == {"mlb", "nba", "nfl", "ncaab"}

    print("results self-test: all invariants hold")


if __name__ == "__main__":
    _self_test()
