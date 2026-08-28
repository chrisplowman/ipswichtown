import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ingest_women as iw


# ---- _find_list --------------------------------------------------------------
def test_find_list_walks_nested_dicts_and_lists():
    tree = {"a": {"b": [{"other": 1}]}, "c": [{"pts": 1, "played": 2}, {"pts": 3, "played": 4}]}
    assert iw._find_list(tree, lambda x: "pts" in x and "played" in x) == \
        [{"pts": 1, "played": 2}, {"pts": 3, "played": 4}]


def test_find_list_returns_none_when_nothing_matches():
    assert iw._find_list({"a": [{"x": 1}]}, lambda x: "pts" in x) is None


# ---- parse_table ---------------------------------------------------------------
def _league_json(table_rows, matches=None):
    return {
        "details": {"name": "Barclays Women's Super League 2"},
        "table": [{"data": {"table": {"all": table_rows}}}],
        "matches": {"allMatches": matches or []},
    }


def test_parse_table_maps_rows_and_flags_ipswich():
    rows = [
        {"id": 1, "idx": 1, "name": "Ipswich Town", "played": 2, "wins": 2, "draws": 0, "losses": 0,
         "scoresStr": "5-1", "goalConDiff": 4, "pts": 6,
         "form": [{"resultString": "w"}, {"resultString": "w"}]},
        {"id": 2, "idx": 2, "name": "Some Rival", "played": 2, "wins": 1, "draws": 0, "losses": 1,
         "scoresStr": "3-3", "goalConDiff": 0, "pts": 3, "form": []},
    ]
    table = iw.parse_table(_league_json(rows))
    assert [r["team"] for r in table] == ["Ipswich Town", "Some Rival"]
    ips = table[0]
    assert ips["is_ipswich"] is True
    assert (ips["played"], ips["won"], ips["gf"], ips["ga"], ips["points"]) == (2, 2, 5, 1, 6)
    assert ips["form"] == ["W", "W"]
    assert ips["badge"] == "https://images.fotmob.com/image_resources/logo/teamlogo/1.png"


def test_parse_table_falls_back_to_index_when_idx_missing():
    rows = [{"name": "A", "played": 0, "wins": 0, "draws": 0, "losses": 0, "pts": 0}]
    table = iw.parse_table(_league_json(rows))
    assert table[0]["rank"] == 1


def test_parse_table_empty_when_no_table_shape_found():
    assert iw.parse_table({"details": {}, "matches": {"allMatches": []}}) == []


# ---- parse_fixtures -------------------------------------------------------------
def test_parse_fixtures_splits_finished_and_upcoming_and_ignores_other_teams():
    matches = [
        {"round": 1, "home": {"id": 1, "name": "Ipswich Town", "score": 3},
         "away": {"id": 2, "name": "Some Rival", "score": 1},
         "status": {"finished": True, "utcTime": "2026-08-10T14:00:00Z"}},
        {"round": 2, "home": {"id": 3, "name": "Another Club"}, "away": {"id": 1, "name": "Ipswich Town"},
         "status": {"finished": False, "utcTime": "2026-08-24T14:00:00Z"}},
        {"round": 1, "home": {"id": 4, "name": "Other Team"}, "away": {"id": 5, "name": "Different Team"},
         "status": {"finished": True, "utcTime": "2026-08-10T14:00:00Z"}},
    ]
    results, upcoming = iw.parse_fixtures(_league_json([], matches))
    assert len(results) == 1 and len(upcoming) == 1
    r = results[0]
    assert (r["opponent"], r["home"], r["score"], r["result"]) == ("Some Rival", True, "3-1", "W")
    assert r["opponent_badge"] == "https://images.fotmob.com/image_resources/logo/teamlogo/2.png"
    u = upcoming[0]
    assert (u["opponent"], u["home"], u["opponent_id"]) == ("Another Club", False, 3)


def test_parse_fixtures_uses_score_str_fallback_when_score_fields_missing():
    matches = [{"round": 1, "home": {"id": 1, "name": "Ipswich Town"}, "away": {"id": 2, "name": "Rival"},
                "status": {"finished": True, "utcTime": "2026-08-10T14:00:00Z", "scoreStr": "2-0"}}]
    results, _ = iw.parse_fixtures(_league_json([], matches))
    assert results[0]["score"] == "2-0" and results[0]["result"] == "W"


def test_parse_fixtures_skips_cancelled_matches():
    matches = [{"round": 1, "home": {"id": 1, "name": "Ipswich Town"}, "away": {"id": 2, "name": "Rival"},
                "status": {"finished": False, "cancelled": True}}]
    results, upcoming = iw.parse_fixtures(_league_json([], matches))
    assert results == [] and upcoming == []


# ---- parse_squad ------------------------------------------------------------
def test_parse_squad_flattens_position_groups():
    team_json = {"squad": [
        {"title": "Goalkeepers", "members": [
            {"name": "Freya Scherpen", "shirtNumber": 1,
             "role": {"key": "goalkeeper", "fallback": "Goalkeeper"},
             "matchesPlayed": 2, "goals": 0, "assists": 0}]},
        {"title": "Forwards", "members": [
            {"name": "Jane Smith", "shirtNumber": 9, "role": {"key": "attacker", "fallback": "Attacker"},
             "matchesPlayed": 2, "goals": 3, "assists": 1}]},
    ]}
    squad = iw.parse_squad(team_json)
    assert [p["name"] for p in squad] == ["Scherpen", "Smith"]
    assert [p["pos"] for p in squad] == ["GKP", "FWD"]
    assert squad[1]["goals"] == 3 and squad[1]["assists"] == 1


def test_parse_squad_falls_back_to_generic_search_when_no_groups_key():
    team_json = {"players": [{"name": "Jane Smith", "shirtNumber": 9,
                              "role": {"key": "midfielder"}, "goals": None, "assists": None}]}
    squad = iw.parse_squad(team_json)
    assert squad == [{"name": "Smith", "full_name": "Jane Smith", "pos": "MID",
                      "apps": None, "goals": None, "assists": None}]


def test_parse_squad_defaults_unknown_role_to_mid():
    team_json = {"squad": [{"members": [{"name": "A B", "shirtNumber": 2, "role": {}}]}]}
    assert iw.parse_squad(team_json)[0]["pos"] == "MID"


def test_parse_squad_empty_when_no_squad_shape_found():
    assert iw.parse_squad({"details": {}}) == []


# ---- _team_badge -------------------------------------------------------------
def test_team_badge_none_without_id():
    assert iw._team_badge(None) is None


def test_team_badge_builds_fotmob_crest_url():
    assert iw._team_badge(1134184) == "https://images.fotmob.com/image_resources/logo/teamlogo/1134184.png"
