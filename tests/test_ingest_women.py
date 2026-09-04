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
# FotMob nests the real list two levels down: team_json["squad"] is a dict
# ({"squad": [...], "isNationalTeam": ...}), and each entry in that inner
# list is a position group with a lowercase "title" ("keepers", "defenders",
# "midfielders", "attackers") plus a non-playing "coach" group.
def test_parse_squad_flattens_position_groups_and_drops_coach():
    team_json = {"squad": {"squad": [
        {"title": "coach", "members": [{"name": "David Wright", "role": {"key": "coach"}}]},
        {"title": "keepers", "members": [
            {"name": "Freya Scherpen", "shirtNumber": 1, "role": {"key": "keeper_long"},
             "positionIdsDesc": "GK", "age": 24, "goals": 0, "assists": 0}]},
        {"title": "attackers", "members": [
            {"name": "Jane Smith", "shirtNumber": 9, "role": {"key": "attacker_long"},
             "positionIdsDesc": "ST", "age": 27, "goals": 3, "assists": 1}]},
    ]}}
    squad = iw.parse_squad(team_json)
    assert [p["name"] for p in squad] == ["Scherpen", "Smith"]
    assert [p["pos"] for p in squad] == ["GKP", "FWD"]
    assert [p["age"] for p in squad] == [24, 27]
    assert squad[1]["goals"] == 3 and squad[1]["assists"] == 1


def test_parse_squad_falls_back_to_generic_search_when_shape_unrecognised():
    team_json = {"players": [{"name": "Jane Smith", "shirtNumber": 9,
                              "role": {"key": "midfielder_long"}, "goals": None, "assists": None}]}
    squad = iw.parse_squad(team_json)
    assert squad == [{"name": "Smith", "full_name": "Jane Smith", "pos": "MID", "pos_detail": None,
                      "nationality": None, "nat_code": None, "age": None, "apps": None, "goals": None,
                      "assists": None, "ycards": None, "rcards": None}]


def test_parse_squad_carries_nationality_pos_detail_and_cards():
    team_json = {"squad": {"squad": [{"title": "attackers", "members": [
        {"name": "Jane Smith", "shirtNumber": 9, "role": {"key": "attacker_long"},
         "positionIdsDesc": "ST,LW", "cname": "England", "ccode": "ENG",
         "goals": 3, "assists": 1, "ycards": 2, "rcards": 0}]}]}}
    p = iw.parse_squad(team_json)[0]
    assert p["pos_detail"] == "ST"
    assert (p["nationality"], p["nat_code"]) == ("England", "ENG")
    assert (p["ycards"], p["rcards"]) == (2, 0)


def test_parse_squad_defaults_unknown_role_to_mid():
    team_json = {"squad": {"squad": [{"title": "reserves", "members": [
        {"name": "A B", "shirtNumber": 2, "role": {}}]}]}}
    assert iw.parse_squad(team_json)[0]["pos"] == "MID"


def test_parse_squad_empty_when_no_squad_shape_found():
    assert iw.parse_squad({"details": {}}) == []


def test_parse_squad_uses_position_ids_desc_in_fallback_path():
    team_json = {"players": [{"name": "A Defender", "shirtNumber": 4, "positionIdsDesc": "CB,RB"}]}
    assert iw.parse_squad(team_json)[0]["pos"] == "DEF"


# ---- _team_badge -------------------------------------------------------------
def test_team_badge_none_without_id():
    assert iw._team_badge(None) is None


def test_team_badge_builds_fotmob_crest_url():
    assert iw._team_badge(1134184) == "https://images.fotmob.com/image_resources/logo/teamlogo/1134184.png"


# ---- parse_venue ---------------------------------------------------------------
def test_parse_venue_reads_widget_and_stat_pairs():
    team_json = {"overview": {"venue": {
        "widget": {"name": "JobServe Community Stadium", "city": "Colchester, Essex"},
        "statPairs": [["Surface", "Grass"], ["Capacity", 10083], ["Opened", 2008]]}}}
    venue = iw.parse_venue(team_json)
    assert venue == {"name": "JobServe Community Stadium", "city": "Colchester, Essex",
                     "capacity": 10083, "surface": "Grass", "opened": 2008}


def test_parse_venue_none_when_no_widget_name():
    assert iw.parse_venue({"overview": {}}) is None
    assert iw.parse_venue({}) is None


# ---- parse_coach ----------------------------------------------------------------
def test_parse_coach_joins_current_coach_with_wsl2_record():
    team_json = {"overview": {
        "lastLineupStats": {"coach": {"name": "David Wright", "countryName": "England"}},
        "coachHistory": [
            {"name": "Joe Sheehan", "leagueId": 9717, "win": 0, "draw": 0, "loss": 3, "pointsPerGame": 0},
            {"name": "David Wright", "leagueId": iw.FOTMOB_LEAGUE_ID,
             "win": 5, "draw": 3, "loss": 3, "pointsPerGame": 1.64},
        ]}}
    coach = iw.parse_coach(team_json)
    assert coach == {"name": "David Wright", "nationality": "England",
                     "win": 5, "draw": 3, "loss": 3, "points_per_game": 1.64}


def test_parse_coach_none_without_current_coach():
    assert iw.parse_coach({"overview": {}}) is None


def test_parse_coach_handles_missing_history_entry():
    team_json = {"overview": {"lastLineupStats": {"coach": {"name": "New Manager"}},
                              "coachHistory": []}}
    coach = iw.parse_coach(team_json)
    assert coach["name"] == "New Manager" and coach["win"] is None


# ---- parse_last_match ------------------------------------------------------------
def _lls_player(name, shirt, rating, x, y, events=None, sub_events=None, captain=False, potm=False):
    return {"name": name, "shirtNumber": shirt, "isCaptain": captain,
            "horizontalLayout": {"x": x, "y": y},
            "performance": {"rating": rating, "playerOfTheMatch": potm,
                            "events": events or [], "substitutionEvents": sub_events or []}}


def test_parse_last_match_maps_lineup_and_joins_score_from_results():
    team_json = {"overview": {"lastLineupStats": {
        "formation": "4-2-3-1", "rating": 6.9, "averageStarterAge": 24.3,
        "coach": {"name": "David Wright"},
        "lastMatch": {"homeTeamName": "Ipswich Town WFC", "awayTeamName": "Sunderland"},
        "starters": [
            _lls_player("Lysianne Proulx", "44", 7, 0.1, 0.5),
            _lls_player("Kenzie Weir", "23", 8.3, 0.292, 0.375,
                        events=[{"type": "goal", "time": 86}], captain=True),
        ],
        "subs": [
            _lls_player("Kit Graham", "16", 6, None, None,
                        sub_events=[{"type": "subIn", "time": 79}]),
        ],
    }}}
    results = [{"opponent": "Sunderland", "home": True, "score": "3-1", "result": "W",
               "date": "2026-08-10", "opponent_badge": "https://example.com/sun.png"}]
    m = iw.parse_last_match(team_json, results)
    assert m["opponent"] == "Sunderland" and m["home"] is True
    assert (m["formation"], m["team_rating"], m["average_age"]) == ("4-2-3-1", 6.9, 24.3)
    assert m["coach_name"] == "David Wright"
    assert (m["score"], m["result"], m["date"]) == ("3-1", "W", "2026-08-10")
    weir = m["starters"][1]
    assert weir["name"] == "Weir" and weir["is_captain"] is True
    assert weir["goals"] == [86]
    assert (weir["x"], weir["y"]) == (0.292, 0.375)
    graham = m["subs"][0]
    assert graham["sub_on"] == 79


def test_parse_last_match_none_without_starters():
    assert iw.parse_last_match({"overview": {"lastLineupStats": {"starters": []}}}, []) is None
    assert iw.parse_last_match({"overview": {}}, []) is None


def test_parse_last_match_skips_score_when_opponent_doesnt_match_latest_result():
    team_json = {"overview": {"lastLineupStats": {
        "formation": "4-4-2", "rating": 6.5, "averageStarterAge": 25.0, "coach": {},
        "lastMatch": {"homeTeamName": "Ipswich Town WFC", "awayTeamName": "Watford"},
        "starters": [_lls_player("A B", "1", 6, 0.1, 0.5)], "subs": []}}}
    results = [{"opponent": "Some Other Club", "home": True, "score": "1-0", "result": "W", "date": "2026-08-01"}]
    m = iw.parse_last_match(team_json, results)
    assert "score" not in m
