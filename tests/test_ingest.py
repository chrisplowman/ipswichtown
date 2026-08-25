import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import to_float, _norm, canon, simplify_pos, win_probs, _fbd_iso


def test_to_float_valid():
    assert to_float("1.236") == 1.24
    assert to_float(3) == 3.0


def test_to_float_invalid():
    assert to_float(None) == 0.0
    assert to_float("not-a-number") == 0.0


def test_norm_strips_club_suffixes_and_punctuation():
    assert _norm("Ipswich Town FC") == "ipswichtown"
    assert _norm("Nott'm Forest") == "nottmforest"
    assert _norm("Brighton & Hove Albion") == "brightonhovealbion"


def test_canon_known_aliases_collapse_to_same_key():
    assert canon("Man City") == canon("Manchester City") == "mancity"
    assert canon("Spurs") == canon("Tottenham Hotspur") == "tottenham"


def test_canon_unknown_name_falls_back_to_normalised():
    assert canon("Some New Club FC") == _norm("Some New Club FC")


def test_simplify_pos():
    assert simplify_pos("GK") == "GKP"
    assert simplify_pos("D") == "DEF"
    assert simplify_pos("F") == "FWD"
    assert simplify_pos("S") == "FWD"
    assert simplify_pos("M") == "MID"
    assert simplify_pos("") == "MID"


def test_win_probs_sums_to_100():
    p = win_probs(1500, 1500, home=True)
    assert p["ipswich"] + p["draw"] + p["opponent"] == 100


def test_win_probs_home_advantage():
    equal_home = win_probs(1500, 1500, home=True)
    equal_away = win_probs(1500, 1500, home=False)
    assert equal_home["ipswich"] > equal_away["ipswich"]


def test_win_probs_stronger_team_favoured():
    p = win_probs(1700, 1300, home=True)
    assert p["ipswich"] > p["opponent"]


def test_fbd_iso_two_digit_year():
    assert _fbd_iso("22/08/26") == "2026-08-22"


def test_fbd_iso_four_digit_year():
    assert _fbd_iso("22/08/2026") == "2026-08-22"


def test_fbd_iso_blank_passthrough():
    assert _fbd_iso("") == ""


# ---- Monte Carlo -----------------------------------------------------------
def test_monte_carlo_survival_and_releg_sum():
    import random
    from ingest import monte_carlo, canon
    random.seed(0)
    teams = {i: {"id": i, "name": n, "points": p} for i, (n, p) in
             enumerate([("A", 30), ("B", 25), ("C", 20), ("D", 15), ("Ipswich", 10), ("F", 5)], 1)}
    fx = [{"team_h": h, "team_a": a, "finished": False} for h in teams for a in teams if h != a]
    elos = {canon(t["name"]): 1500 for t in teams.values()}
    surv, odds = monte_carlo(teams, fx, elos, 5, n=2000)
    assert abs(surv["survive_pct"] + surv["releg_pct"] - 100) < 0.1
    assert set(odds) == {t["name"] for t in teams.values()}
    assert 0 <= surv["survive_pct"] <= 100
    assert surv["pts_lo"] <= surv["avg_points"] <= surv["pts_hi"]
    assert surv["pos_lo"] <= surv["avg_position"] <= surv["pos_hi"]
    assert surv["sims"] == 2000


def test_monte_carlo_no_remaining_fixtures_returns_none():
    from ingest import monte_carlo
    teams = {1: {"id": 1, "name": "Ipswich", "points": 10}}
    surv, odds = monte_carlo(teams, [], {}, 1, n=100)
    assert surv is None and odds == {}


# ---- League tables + form --------------------------------------------------
def test_fetch_league_tables_home_away_form():
    from ingest import fetch_league_tables, canon
    rows = [
        {"HomeTeam": "Ipswich", "AwayTeam": "Arsenal", "FTHG": "2", "FTAG": "1", "Date": "01/09/26"},
        {"HomeTeam": "Chelsea", "AwayTeam": "Ipswich", "FTHG": "0", "FTAG": "0", "Date": "08/09/26"},
        {"HomeTeam": "Ipswich", "AwayTeam": "Chelsea", "FTHG": "1", "FTAG": "3", "Date": "15/09/26"},
    ]
    home, away, form = fetch_league_tables(rows)
    ih = [r for r in home if canon(r["team"]) == canon("Ipswich")][0]
    assert (ih["played"], ih["won"], ih["lost"], ih["points"]) == (2, 1, 1, 3)
    ia = [r for r in away if canon(r["team"]) == canon("Ipswich")][0]
    assert (ia["played"], ia["drawn"], ia["points"]) == (1, 1, 1)
    assert form[canon("Ipswich")][-3:] == ["W", "D", "L"]


# ---- Match stats -----------------------------------------------------------
def test_fetch_match_stats_extracts_result():
    from ingest import fetch_match_stats
    rows = [{"HomeTeam": "Ipswich", "AwayTeam": "Arsenal", "FTHG": "2", "FTAG": "1",
             "HTHG": "1", "HTAG": "0", "HS": "12", "AS": "9", "HST": "5", "AST": "3",
             "HC": "6", "AC": "4", "HF": "10", "AF": "11", "HY": "1", "AY": "2",
             "HR": "0", "AR": "0", "Date": "01/09/26"},
            {"HomeTeam": "Spurs", "AwayTeam": "Chelsea", "FTHG": "1", "FTAG": "1"}]
    ms = fetch_match_stats(rows)
    assert len(ms) == 1
    m = ms[0]
    assert m["opponent"] == "Arsenal" and m["home"] is True
    assert (m["result"], m["gf"], m["ga"]) == ("W", 2, 1)
    assert (m["shots_for"], m["shots_against"]) == (12, 9)
    assert m["ht_state"] == "ahead"
    assert "referee" not in m and "odds" not in m


# ---- ESPN play-by-play pagination -------------------------------------------
def test_fetch_espn_match_events_follows_pagination(monkeypatch):
    import ingest

    def team_ref(team_id):
        return {"$ref": f"https://sports.core.api.espn.com/v2/sports/soccer/leagues/eng.1/teams/{team_id}"}

    page1 = {
        "pageCount": 2,
        "items": [
            {"type": {"type": "pass"}, "team": team_ref(ingest.IPSWICH_ESPN_TEAM_ID),
             "clock": {"value": 300.0, "displayValue": "5:00"}, "text": "Early pass",
             "substitution": False, "yellowCard": False, "redCard": False},
        ],
    }
    # A card past minute ~20, only reachable via page 2 — this is exactly the
    # real-world case that silently vanished before pagination was added.
    page2 = {
        "pageCount": 2,
        "items": [
            {"type": {"type": "foul"}, "team": team_ref(ingest.IPSWICH_ESPN_TEAM_ID),
             "clock": {"value": 2700.0, "displayValue": "45:00"}, "text": "Booking for a foul",
             "substitution": False, "yellowCard": True, "redCard": False},
            {"type": {"type": "substitution-half"}, "team": team_ref(ingest.IPSWICH_ESPN_TEAM_ID),
             "clock": {"value": 3600.0, "displayValue": "60:00"}, "text": "Sub on for sub off",
             "substitution": True, "yellowCard": False, "redCard": False},
        ],
    }

    calls = []

    def fake_get_json(url, *a, **k):
        calls.append(url)
        return page2 if "&page=2" in url else page1

    monkeypatch.setattr(ingest, "get_json", fake_get_json)
    cards, subs, stats = ingest.fetch_espn_match_events("999999", True)

    assert len(calls) == 2 and "&page=2" in calls[1]
    assert len(cards) == 1 and cards[0]["kind"] == "yellow"
    assert len(subs) == 1 and subs[0]["text"] == "Sub on for sub off"


# ---- ESPN lineups -----------------------------------------------------------
def test_fetch_espn_lineups_splits_starters_and_full_bench(monkeypatch):
    import ingest

    def player(name, jersey, pos, starter, subbed_in=False):
        return {"starter": starter, "jersey": jersey, "subbedIn": subbed_in,
                "athlete": {"displayName": name}, "position": {"abbreviation": pos}}

    summary = {"rosters": [
        {"team": {"id": ingest.IPSWICH_ESPN_TEAM_ID}, "formation": "4-2-3-1", "roster": [
            player("Scherpen", "37", "G", True),
            player("Clarke", "47", "F", False, subbed_in=True),
            player("Walton", "28", "G", False, subbed_in=False),  # unused sub
        ]},
        {"team": {"id": "366"}, "formation": "4-3-3", "roster": [
            player("Roefs", "22", "G", True),
        ]},
    ]}

    monkeypatch.setattr(ingest, "get_json", lambda url, *a, **k: summary)
    lineups = ingest.fetch_espn_lineups("401879299")

    assert lineups["for"]["formation"] == "4-2-3-1"
    assert [p["name"] for p in lineups["for"]["starters"]] == ["Scherpen"]
    # the full bench, not just the substitutes actually brought on
    assert [p["name"] for p in lineups["for"]["subs"]] == ["Clarke", "Walton"]
    assert lineups["against"]["formation"] == "4-3-3"
    assert [p["name"] for p in lineups["against"]["starters"]] == ["Roefs"]


def test_fetch_espn_lineups_returns_none_when_unpublished(monkeypatch):
    import ingest
    monkeypatch.setattr(ingest, "get_json", lambda url, *a, **k: {"rosters": []})
    assert ingest.fetch_espn_lineups("401879299") is None


def test_fetch_espn_lineups_extracts_sub_card_and_goal_minutes(monkeypatch):
    import ingest

    def play(minute, **flags):
        d = {"clock": {"displayValue": minute}, "substitution": False,
             "yellowCard": False, "redCard": False}
        d.update(flags)
        return d

    summary = {"rosters": [
        {"team": {"id": ingest.IPSWICH_ESPN_TEAM_ID}, "formation": "4-2-3-1", "roster": [
            # Starter: scores at 24', booked at 58', subbed off at 71'.
            {"starter": True, "jersey": "10", "subbedOut": True, "subbedIn": False,
             "athlete": {"displayName": "Enciso"}, "position": {"abbreviation": "AM"},
             "plays": [play("24'", didScore=True), play("58'", yellowCard=True),
                       play("71'", substitution=True)]},
            # Bench player: comes on at 71', scores at 90'.
            {"starter": False, "jersey": "47", "subbedOut": False, "subbedIn": True,
             "athlete": {"displayName": "Clarke"}, "position": {"abbreviation": "F"},
             "plays": [play("71'", substitution=True), play("90'", didScore=True)]},
        ]},
        {"team": {"id": "366"}, "formation": "4-3-3", "roster": [
            {"starter": True, "jersey": "5", "subbedOut": False, "subbedIn": False,
             "athlete": {"displayName": "Ballard"}, "position": {"abbreviation": "CD"},
             "plays": [play("36'", redCard=True)]},
        ]},
    ]}

    monkeypatch.setattr(ingest, "get_json", lambda url, *a, **k: summary)
    lineups = ingest.fetch_espn_lineups("401879299")

    enciso = lineups["for"]["starters"][0]
    assert enciso["goals"] == ["24'"]
    assert enciso["cards"] == [{"kind": "yellow", "minute": "58'"}]
    assert enciso["sub_off"] == "71'" and enciso["sub_on"] is None

    clarke = lineups["for"]["subs"][0]
    assert clarke["sub_on"] == "71'" and clarke["sub_off"] is None
    assert clarke["goals"] == ["90'"]

    ballard = lineups["against"]["starters"][0]
    assert ballard["cards"] == [{"kind": "red", "minute": "36'"}]


def test_fetch_espn_lineups_extracts_attendance_referee_and_team_stats(monkeypatch):
    import ingest

    summary = {
        "rosters": [
            {"team": {"id": ingest.IPSWICH_ESPN_TEAM_ID}, "formation": "4-2-3-1", "roster": [
                {"starter": True, "jersey": "1", "subbedOut": False, "subbedIn": False,
                 "athlete": {"displayName": "Scherpen"}, "position": {"abbreviation": "G", "name": "Goalkeeper"}},
            ]},
            {"team": {"id": "366"}, "formation": "4-3-3", "roster": [
                {"starter": True, "jersey": "22", "subbedOut": False, "subbedIn": False,
                 "athlete": {"displayName": "Roefs"}, "position": {"abbreviation": "G", "name": "Goalkeeper"}},
            ]},
        ],
        "gameInfo": {"attendance": 29669, "officials": [
            {"fullName": "Farai Hallam", "position": {"name": "Referee"}, "order": 1}]},
        "boxscore": {"teams": [
            {"team": {"id": ingest.IPSWICH_ESPN_TEAM_ID}, "statistics": [
                {"name": "possessionPct", "displayValue": "37.5"},
                {"name": "accuratePasses", "displayValue": "258"},
                {"name": "totalPasses", "displayValue": "325"},
                {"name": "effectiveTackles", "displayValue": "15"},
                {"name": "interceptions", "displayValue": "7"}]},
            {"team": {"id": "366"}, "statistics": [
                {"name": "possessionPct", "displayValue": "62.5"},
                {"name": "accuratePasses", "displayValue": "484"},
                {"name": "totalPasses", "displayValue": "549"},
                {"name": "effectiveTackles", "displayValue": "8"},
                {"name": "interceptions", "displayValue": "9"}]}]},
    }

    monkeypatch.setattr(ingest, "get_json", lambda url, *a, **k: summary)
    lineups = ingest.fetch_espn_lineups("401879299")

    assert lineups["attendance"] == 29669
    assert lineups["referee"] == "Farai Hallam"
    assert lineups["team_stats"]["possession_for"] == 37.5
    assert lineups["team_stats"]["possession_against"] == 62.5
    assert lineups["team_stats"]["pass_pct_for"] == round(258 / 325 * 100, 1)
    assert lineups["team_stats"]["tackles_for"] == 15
    assert lineups["team_stats"]["interceptions_against"] == 9


# ---- FDR fallback probabilities --------------------------------------------
def test_fdr_win_probs_sum_to_100():
    from ingest import fdr_win_probs
    for d in (1, 2, 3, 4, 5):
        p = fdr_win_probs(d)
        assert p["ipswich"] + p["draw"] + p["opponent"] == 100


def test_strip_html_removes_tags():
    from ingest import _strip_html
    out = _strip_html("<p>Hello <b>world</b></p>")
    assert "Hello" in out and "world" in out and "<" not in out
