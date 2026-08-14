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
def test_fetch_match_stats_extracts_result_and_odds():
    from ingest import fetch_match_stats
    rows = [{"HomeTeam": "Ipswich", "AwayTeam": "Arsenal", "FTHG": "2", "FTAG": "1",
             "HTHG": "1", "HTAG": "0", "HS": "12", "AS": "9", "HST": "5", "AST": "3",
             "HC": "6", "AC": "4", "HF": "10", "AF": "11", "HY": "1", "AY": "2",
             "HR": "0", "AR": "0", "Referee": "M Oliver", "Date": "01/09/26",
             "B365H": "2.0", "B365D": "3.4", "B365A": "3.6"},
            {"HomeTeam": "Spurs", "AwayTeam": "Chelsea", "FTHG": "1", "FTAG": "1"}]
    ms = fetch_match_stats(rows)
    assert len(ms) == 1
    m = ms[0]
    assert m["opponent"] == "Arsenal" and m["home"] is True
    assert (m["result"], m["gf"], m["ga"]) == ("W", 2, 1)
    assert (m["shots_for"], m["shots_against"]) == (12, 9)
    assert m["ht_state"] == "ahead" and m["referee"] == "M Oliver"
    assert 99 <= sum(m["odds"].values()) <= 101


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
