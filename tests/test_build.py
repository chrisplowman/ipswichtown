import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import _ord, fmt_kickoff, fmt_updated


def test_ord_suffixes():
    assert _ord(1) == "st"
    assert _ord(2) == "nd"
    assert _ord(3) == "rd"
    assert _ord(4) == "th"
    assert _ord(11) == "th"
    assert _ord(12) == "th"
    assert _ord(13) == "th"
    assert _ord(21) == "st"
    assert _ord(22) == "nd"
    assert _ord(23) == "rd"


def test_fmt_kickoff_none():
    assert fmt_kickoff(None) == "TBC"
    assert fmt_kickoff("") == "TBC"


def test_fmt_kickoff_malformed():
    assert fmt_kickoff("not-a-date") == "TBC"


def test_fmt_kickoff_valid():
    out = fmt_kickoff("2026-08-22T14:00:00Z")
    assert "22" in out
    assert "Aug" in out


def test_fmt_updated_valid():
    out = fmt_updated("2026-08-05T12:34:56+00:00")
    assert "2026" in out
    assert "UTC" in out


def test_fmt_updated_malformed_returns_input():
    assert fmt_updated("not-a-date") == "not-a-date"


def _live():
    return {
        "team": {"name": "Ipswich", "short_name": "IPS", "badge": None},
        "fixtures": [{"event": i, "opponent": o, "opponent_short": s, "home": (i % 2 == 0),
                      "finished": False, "kickoff": "2026-08-22T14:00:00Z", "difficulty": 3, "badge": None}
                     for i, (o, s) in enumerate([("Arsenal", "ARS"), ("Everton", "EVE"),
                                                 ("Chelsea", "CHE"), ("Fulham", "FUL")], 1)],
        "squad": [{"name": n, "full_name": n, "pos": p, "pos_id": 2, "price": 6.0, "points": 40,
                   "form": 4.2, "minutes": 900, "starts": 10, "goals": 2, "assists": 1, "xg": 1.5,
                   "xa": 1.0, "xgi": 2.5, "clean_sheets": 2, "selected": 8.5}
                  for n, p in [("Delap", "FWD"), ("Hutchinson", "MID")]],
        "news": []}


def test_season_summary_preseason():
    from build import season_summary
    s = season_summary({"season": "2026/27", "team": {"name": "Ipswich Town"}, "summary": {"played": 0},
                        "next_fixture": {"opponent": "Sunderland", "home": True, "kickoff": "2026-08-22T14:00:00Z"},
                        "next_opponent": {"name": "Sunderland", "prob": {"ipswich": 48}}})
    assert "under way" in s and "Sunderland" in s


def test_season_summary_relegation_tone():
    from build import season_summary
    d = {"season": "2026/27", "team": {"name": "Ipswich Town"}, "position": 18,
         "summary": {"played": 12, "won": 2, "drawn": 3, "lost": 7, "points": 9},
         "table": [{"rank": 17, "points": 15, "played": 12}],
         "understat_history": [{"pts": 0, "xpts": 1.2}] * 12,
         "next_fixture": {"opponent": "Arsenal", "home": False},
         "next_opponent": {"name": "Arsenal", "prob": {"ipswich": 15}}}
    s = season_summary(d)
    assert "18th" in s and "relegation" in s.lower()


def test_projected_table_projection_and_rank():
    from build import projected_table
    pt = projected_table({"table": [
        {"rank": 1, "team": "A", "played": 10, "points": 25, "gd": 15},
        {"rank": 2, "team": "B", "played": 10, "points": 10, "gd": -5}]})
    assert pt[0]["proj"] == 95 and pt[0]["ppg"] == 2.5
    assert pt[0]["proj_rank"] == 1 and pt[1]["proj_rank"] == 2


def test_projected_table_preseason_none():
    from build import projected_table
    pt = projected_table({"table": [{"rank": 1, "team": "A", "played": 0, "points": 0, "gd": 0}]})
    assert pt[0]["proj"] is None


def test_rival_tracker_window_and_releg():
    from build import rival_tracker
    table = [{"rank": r, "team": f"T{r}", "is_ipswich": (r == 10), "points": 40 - r, "form": []}
             for r in range(1, 21)]
    rivals = rival_tracker({"table": table, "releg_odds": {"T13": 42.0}})
    assert [r["rank"] for r in rivals] == [7, 8, 9, 10, 11, 12, 13]
    assert [r for r in rivals if r["team"] == "T13"][0]["releg"] == 42.0


def test_rival_tracker_no_ipswich_returns_empty():
    from build import rival_tracker
    assert rival_tracker({"table": [{"rank": 1, "team": "A", "is_ipswich": False}]}) == []


def test_guardian_report_url_home_match():
    from build import guardian_report_url
    url = guardian_report_url({"date": "2026-08-22", "opponent": "Sunderland", "home": True})
    assert url == "https://www.theguardian.com/football/2026/aug/22/ipswich-sunderland-premier-league-match-report"


def test_guardian_report_url_away_match_uses_slug_map():
    from build import guardian_report_url
    url = guardian_report_url({"date": "2026-09-01", "opponent": "West Ham United", "home": False})
    assert url == "https://www.theguardian.com/football/2026/sep/1/west-ham-ipswich-premier-league-match-report"


def test_guardian_report_url_invalid_date_returns_none():
    from build import guardian_report_url
    assert guardian_report_url({"date": "", "opponent": "Arsenal", "home": True}) is None


def test_match_report_links_includes_guardian_and_espn():
    from build import match_report_links
    links = match_report_links({"date": "2026-08-22", "opponent": "Sunderland", "home": True,
                                "espn_report_url": "https://www.espn.com/soccer/report/_/gameId/401879299"})
    names = [l["name"] for l in links]
    assert names == ["The Guardian", "ESPN"]
    assert "sun" not in " ".join(l["name"].lower() for l in links)
    assert "mail" not in " ".join(l["name"].lower() for l in links)


def test_match_report_links_empty_without_espn_event():
    from build import match_report_links
    links = match_report_links({"date": "", "opponent": "Arsenal", "home": True})
    assert links == []


def test_pslug_and_pnorm():
    from build import _pslug, _pnorm
    assert _pslug("Liam Delap") == "liam-delap"
    assert _pnorm("Omari Hutchinson") == "omarihutchinson"
    assert _pslug("") == "player"


def test_build_player_pages_slug_and_join():
    from build import build_player_pages
    data = {"squad": [{"name": "Delap", "full_name": "Liam Delap", "pos": "FWD"}],
            "understat_players": [{"name": "Liam Delap", "xg": 3.2, "xa": 1.1, "shots": 20,
                                   "npxg": 2.9, "xgchain": 4.0, "xgbuildup": 1.0}],
            "player_profiles": [], "match_pages": []}
    pages = build_player_pages(data)
    assert pages[0]["slug"] == "liam-delap"
    assert pages[0]["us"]["xg"] == 3.2
    assert data["squad"][0]["slug"] == "liam-delap"


def test_site_builds_end_to_end(tmp_path, monkeypatch):
    import build
    import json as _json
    data = build.sample_data(_live())
    monkeypatch.setattr(build, "SITE", tmp_path / "site")
    monkeypatch.setattr(build, "DATA", tmp_path / "itfc.json")
    (tmp_path / "itfc.json").write_text(_json.dumps(data))
    build.main()
    site = tmp_path / "site"
    for f in ["index.html", "table.html", "charts.html", "matches.html", "squad.html",
              "news.html", "style.css"]:
        assert (site / f).exists(), f"missing {f}"
    assert list((site / "match").glob("*.html")), "no match pages built"
    assert list((site / "player").glob("*.html")), "no player pages built"
    idx = (site / "index.html").read_text()
    assert "{{" not in idx and "{%" not in idx, "unrendered Jinja in output"
    assert "Ipswich Town" in idx
    match_html = next((site / "match").glob("*.html")).read_text()
    assert 'class="masthead' in match_html and 'href="../style.css"' in match_html
