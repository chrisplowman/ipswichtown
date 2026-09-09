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


# ---- previous-season top 3 (right-hand axis reference lines) -----------------
def test_previous_season_label_steps_back_a_year_in_fotmob_format():
    assert iw._previous_season_label() == "2025/2026"


def test_parse_last_season_top3_takes_first_three_ranked_rows():
    rows = [
        {"id": 1, "idx": 1, "name": "Sunderland", "played": 22, "wins": 18, "draws": 4, "losses": 0,
         "scoresStr": "58-10", "goalConDiff": 48, "pts": 58, "form": []},
        {"id": 2, "idx": 2, "name": "Southampton", "played": 22, "wins": 17, "draws": 3, "losses": 2,
         "scoresStr": "50-15", "goalConDiff": 35, "pts": 54, "form": []},
        {"id": 3, "idx": 3, "name": "Newcastle United", "played": 22, "wins": 15, "draws": 4, "losses": 3,
         "scoresStr": "45-20", "goalConDiff": 25, "pts": 49, "form": []},
        {"id": 4, "idx": 4, "name": "Ipswich Town", "played": 22, "wins": 6, "draws": 5, "losses": 11,
         "scoresStr": "30-40", "goalConDiff": -10, "pts": 23, "form": []},
    ]
    top3 = iw.parse_last_season_top3(_league_json(rows))
    assert top3 == [
        {"rank": 1, "team": "Sunderland", "points": 58},
        {"rank": 2, "team": "Southampton", "points": 54},
        {"rank": 3, "team": "Newcastle United", "points": 49},
    ]


def test_parse_last_season_top3_none_when_fewer_than_three_teams():
    rows = [{"id": 1, "idx": 1, "name": "A", "played": 1, "wins": 1, "draws": 0, "losses": 0,
             "scoresStr": "1-0", "goalConDiff": 1, "pts": 3, "form": []}]
    assert iw.parse_last_season_top3(_league_json(rows)) is None


def test_parse_last_season_top3_none_without_a_response():
    assert iw.parse_last_season_top3(None) is None


# ---- parse_team_ranks ("How Ipswich compare" rank bars) ----------------------
# Confirmed against a real response: team_json["stats"]["teams"] is a list of
# per-stat entries, each with a "stat" (e.g. "goals_team_match" — note this is
# "stat", not "name" as stats.players entries use) and a "participant"
# carrying Ipswich's own rank/value for that stat.
def _team_json_with_stats(entries):
    return {"stats": {"teams": [
        {"stat": stat, "participant": {"rank": rank, "value": value}}
        for stat, rank, value in entries
    ]}}


def _wsl2_table(points=1, rank=5, gd=0, total=12):
    table = [{"rank": i, "team": f"Team {i}", "points": 0, "gd": 0, "is_ipswich": False}
             for i in range(1, total + 1) if i != rank]
    table.insert(rank - 1, {"rank": rank, "team": "Ipswich Town", "points": points,
                             "gd": gd, "is_ipswich": True})
    return table


def test_parse_team_ranks_bookends_with_points_and_goal_difference():
    team_json = _team_json_with_stats([("goals_team_match", 4, 1)])
    table = _wsl2_table(points=1, rank=5, gd=0)
    ranks = iw.parse_team_ranks(team_json, table)
    assert ranks[0] == {"label": "Points", "value": 1, "rank": 5, "total": 12, "low_good": False}
    assert ranks[-1]["label"] == "Goal difference"
    assert any(r["label"] == "Goals per match" and r["rank"] == 4 for r in ranks)


def test_parse_team_ranks_skips_stats_missing_from_response():
    team_json = _team_json_with_stats([("goals_team_match", 4, 1)])
    ranks = iw.parse_team_ranks(team_json, _wsl2_table())
    labels = [r["label"] for r in ranks]
    assert "Goals per match" in labels
    assert "Goals conceded per match" not in labels  # not present in team_json


def test_parse_team_ranks_empty_without_a_table():
    assert iw.parse_team_ranks(_team_json_with_stats([("goals_team_match", 4, 1)]), []) == []


def test_parse_team_ranks_empty_without_team_json():
    assert iw.parse_team_ranks(None, _wsl2_table()) == [
        {"label": "Points", "value": 1, "rank": 5, "total": 12, "low_good": False},
        {"label": "Goal difference", "value": 0, "rank": 5, "total": 12, "low_good": False},
    ]


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
                      "nationality": None, "nat_code": None, "age": None, "minutes": None, "goals": None,
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


# ---- _squad_stat_overrides / parse_squad stat patching -----------------------
# Confirmed against a real FotMob teams?id= response: every squad-list member
# carries goals/assists/ycards/rcards, but they're hardcoded 0 for the whole
# squad regardless of what actually happened — even the player who scored the
# only goal that matchday showed "goals": 0 there. The real numbers live in
# team_json["stats"]["players"], a team-scoped leaders-per-category list.
def test_squad_stat_overrides_reads_real_stats_players_shape():
    team_json = {"stats": {"players": [
        {"name": "goals", "header": "Top scorer",
         "participant": {"id": 1185220, "name": "Megan Hornby", "value": 1},
         "topThree": [{"id": 1185220, "name": "Megan Hornby", "value": 1}]},
        {"name": "goal_assist", "header": "Assists",
         "participant": {"id": 1406585, "name": "Mary McAteer", "value": 1},
         "topThree": [{"id": 1406585, "name": "Mary McAteer", "value": 1}]},
        {"name": "yellow_card", "header": "Yellow cards",
         "participant": {"id": 1703223, "name": "Leah Mitchell", "value": 1},
         "topThree": [{"id": 1703223, "name": "Leah Mitchell", "value": 1}]},
        {"name": "rating", "header": "FotMob rating",
         "participant": {"id": 1082549, "name": "Aimee Palmer", "value": 7.53}, "topThree": []},
    ]}}
    overrides = iw._squad_stat_overrides(team_json)
    assert overrides[1185220] == {"goals": 1}
    assert overrides[1406585] == {"assists": 1}
    assert overrides[1703223] == {"ycards": 1}
    assert 1082549 not in overrides  # "rating" isn't one of the fields we patch


def test_squad_stat_overrides_empty_when_no_stats_section():
    assert iw._squad_stat_overrides({}) == {}
    assert iw._squad_stat_overrides({"stats": {}}) == {}


def test_parse_squad_patches_goals_over_always_zero_squad_list_field():
    # goals: 0 here matches the real payload's placeholder — the override
    # from stats.players (value 1) should win.
    team_json = {
        "squad": {"squad": [{"title": "attackers", "members": [
            {"id": 1185220, "name": "Meg Hornby", "shirtNumber": 11,
             "role": {"key": "attacker_long"}, "positionIdsDesc": "ST",
             "goals": 0, "assists": 0, "ycards": 0, "rcards": 0}]}]},
        "stats": {"players": [
            {"name": "goals", "participant": {"id": 1185220, "name": "Meg Hornby", "value": 1},
             "topThree": [{"id": 1185220, "name": "Meg Hornby", "value": 1}]},
        ]},
    }
    p = iw.parse_squad(team_json)[0]
    assert p["goals"] == 1
    assert p["assists"] == 0  # no override found for assists — squad-list 0 stands


def test_parse_squad_leaves_goals_as_is_without_a_stats_section():
    team_json = {"squad": {"squad": [{"title": "attackers", "members": [
        {"id": 1, "name": "Jane Smith", "shirtNumber": 9,
         "role": {"key": "attacker_long"}, "goals": 3, "assists": 1}]}]}}
    p = iw.parse_squad(team_json)[0]
    assert p["goals"] == 3 and p["assists"] == 1


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


# ---- _minutes_played / _last_match_minutes ------------------------------------
def _lp(full_name, sub_on=None, sub_off=None):
    return {"full_name": full_name, "sub_on": sub_on, "sub_off": sub_off}


def test_minutes_played_starter_who_played_full_match():
    assert iw._minutes_played(_lp("A"), is_starter=True) == 90


def test_minutes_played_starter_subbed_off_early():
    assert iw._minutes_played(_lp("A", sub_off=70), is_starter=True) == 70


def test_minutes_played_sub_who_came_on():
    assert iw._minutes_played(_lp("A", sub_on=60), is_starter=False) == 30


def test_minutes_played_sub_brought_on_and_off_again():
    assert iw._minutes_played(_lp("A", sub_on=60, sub_off=80), is_starter=False) == 20


def test_minutes_played_unused_sub_never_came_on():
    # Both sub_on and sub_off are unset here — same as a starter who played
    # the full match — so is_starter is what has to tell them apart.
    assert iw._minutes_played(_lp("A"), is_starter=False) == 0


def test_last_match_minutes_drops_unused_subs():
    last_match = {"starters": [_lp("Starter", sub_off=70)],
                  "subs": [_lp("Used Sub", sub_on=70), _lp("Unused Sub")]}
    assert iw._last_match_minutes(last_match) == {"Starter": 70, "Used Sub": 20}


# ---- _women_match_cache_key ----------------------------------------------------
def test_women_match_cache_key_slugifies_opponent():
    key = iw._women_match_cache_key({"date": "2026-08-10", "opponent": "Nott'm Forest"})
    assert key == "2026-08-10_nott-m-forest"


def test_women_match_cache_key_none_without_date_or_opponent():
    assert iw._women_match_cache_key({"opponent": "Sunderland"}) is None
    assert iw._women_match_cache_key({"date": "2026-08-10"}) is None


# ---- career_minutes -------------------------------------------------------------
# FotMob's team endpoint only ever carries lineup detail for the match that was
# most recently played (see parse_last_match's docstring), so career_minutes
# persists each new one to WOMEN_LINEUP_CACHE_DIR and sums across everything
# recorded there so far — every test below points that dir at tmp_path so
# nothing is ever written into the real repo checkout.
def test_career_minutes_records_new_match_and_returns_totals(tmp_path, monkeypatch):
    monkeypatch.setattr(iw, "WOMEN_LINEUP_CACHE_DIR", tmp_path / "cache")
    last_match = {"date": "2026-08-10", "opponent": "Sunderland",
                  "starters": [_lp("Kenzie Weir", sub_off=80)],
                  "subs": [_lp("Kit Graham", sub_on=80)]}
    totals = iw.career_minutes(last_match)
    assert totals == {"Kenzie Weir": 80, "Kit Graham": 10}
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1


def test_career_minutes_sums_across_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(iw, "WOMEN_LINEUP_CACHE_DIR", tmp_path / "cache")
    iw.career_minutes({"date": "2026-08-10", "opponent": "Sunderland",
                       "starters": [_lp("Kenzie Weir")], "subs": []})
    totals = iw.career_minutes({"date": "2026-08-17", "opponent": "Watford",
                                "starters": [_lp("Kenzie Weir", sub_off=45)], "subs": []})
    assert totals == {"Kenzie Weir": 135}


def test_career_minutes_does_not_double_count_an_already_recorded_match(tmp_path, monkeypatch):
    # A match still being FotMob's "last match" on a later run must not
    # re-record it — otherwise re-running the same day would inflate totals.
    monkeypatch.setattr(iw, "WOMEN_LINEUP_CACHE_DIR", tmp_path / "cache")
    last_match = {"date": "2026-08-10", "opponent": "Sunderland",
                  "starters": [_lp("Kenzie Weir")], "subs": []}
    iw.career_minutes(last_match)
    totals = iw.career_minutes(last_match)
    assert totals == {"Kenzie Weir": 90}


def test_career_minutes_returns_existing_totals_without_a_last_match(tmp_path, monkeypatch):
    monkeypatch.setattr(iw, "WOMEN_LINEUP_CACHE_DIR", tmp_path / "cache")
    iw.career_minutes({"date": "2026-08-10", "opponent": "Sunderland",
                       "starters": [_lp("Kenzie Weir")], "subs": []})
    assert iw.career_minutes(None) == {"Kenzie Weir": 90}


def test_career_minutes_skips_caching_without_a_joined_date(tmp_path, monkeypatch):
    # parse_last_match can return a match with no "date" when it couldn't
    # join a score from `results` — nothing reliable to key a cache file on.
    monkeypatch.setattr(iw, "WOMEN_LINEUP_CACHE_DIR", tmp_path / "cache")
    last_match = {"opponent": "Sunderland", "starters": [_lp("Kenzie Weir")], "subs": []}
    assert iw.career_minutes(last_match) == {}
    assert not (tmp_path / "cache").exists()


def test_career_minutes_empty_without_any_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(iw, "WOMEN_LINEUP_CACHE_DIR", tmp_path / "does-not-exist")
    assert iw.career_minutes(None) == {}


# ---- parse_squad minutes wiring --------------------------------------------------
def test_parse_squad_carries_minutes_by_name():
    team_json = {"squad": {"squad": [{"title": "attackers", "members": [
        {"name": "Jane Smith", "shirtNumber": 9, "role": {"key": "attacker_long"}}]}]}}
    squad = iw.parse_squad(team_json, {"Jane Smith": 180})
    assert squad[0]["minutes"] == 180


def test_parse_squad_minutes_none_when_player_not_in_minutes_by_name():
    team_json = {"squad": {"squad": [{"title": "attackers", "members": [
        {"name": "Jane Smith", "shirtNumber": 9, "role": {"key": "attacker_long"}}]}]}}
    assert iw.parse_squad(team_json)[0]["minutes"] is None
