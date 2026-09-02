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
        "squad": [{"name": n, "full_name": n, "pos": p, "pos_id": 2, "age": 22, "price": 6.0, "points": 40,
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


def test_match_report_links_includes_guardian_espn_and_understat():
    from build import match_report_links
    links = match_report_links({"id": "740604", "date": "2026-08-22", "opponent": "Sunderland", "home": True,
                                "espn_report_url": "https://www.espn.com/soccer/report/_/gameId/401879299"})
    names = [l["name"] for l in links]
    assert names == ["The Guardian", "ESPN", "Understat"]
    assert [l["url"] for l in links if l["name"] == "Understat"] == ["https://understat.com/match/740604"]
    assert "sun" not in " ".join(l["name"].lower() for l in links)
    assert "mail" not in " ".join(l["name"].lower() for l in links)


def test_match_report_links_empty_without_espn_event():
    from build import match_report_links
    links = match_report_links({"date": "", "opponent": "Arsenal", "home": True})
    assert links == []


def test_assign_pitch_positions_bands_and_orders_by_side():
    from build import assign_pitch_positions
    starters = [
        {"jersey": "1", "pos_full": "Goalkeeper"},
        {"jersey": "2", "pos_full": "Right Back"},
        {"jersey": "3", "pos_full": "Left Back"},
        {"jersey": "5", "pos_full": "Center Right Defender"},
        {"jersey": "6", "pos_full": "Center Left Defender"},
        {"jersey": "9", "pos_full": "Forward"},
    ]
    out = assign_pitch_positions(starters, gk_y=96, fwd_y=54)
    by_jersey = {p["jersey"]: p for p in out}

    assert by_jersey["1"]["y"] == 96  # GK sits at its own goal line
    assert by_jersey["9"]["y"] == 54  # lone forward sits at the halfway line
    # within the back four, every left-sided player sits left of every right-sided one
    left_x = [by_jersey[j]["x"] for j in ("3", "6")]     # Left Back, Center Left Defender
    right_x = [by_jersey[j]["x"] for j in ("2", "5")]    # Right Back, Center Right Defender
    assert max(left_x) < min(right_x)


def test_assign_pitch_positions_narrow_row_stays_central():
    # A back four reaches out toward both touchlines, but a two-man central
    # midfield pairing should sit narrow and central rather than being
    # stretched out to that same touchline-to-touchline width.
    from build import assign_pitch_positions
    starters = [
        {"jersey": "1", "pos_full": "Goalkeeper"},
        {"jersey": "2", "pos_full": "Right Back"},
        {"jersey": "3", "pos_full": "Left Back"},
        {"jersey": "5", "pos_full": "Center Right Defender"},
        {"jersey": "6", "pos_full": "Center Left Defender"},
        {"jersey": "8", "pos_full": "Left Midfielder"},
        {"jersey": "10", "pos_full": "Right Midfielder"},
        {"jersey": "9", "pos_full": "Forward"},
    ]
    out = assign_pitch_positions(starters, gk_y=96, fwd_y=54)
    by_jersey = {p["jersey"]: p for p in out}

    def_span = max(by_jersey[j]["x"] for j in ("2", "3", "5", "6")) - min(by_jersey[j]["x"] for j in ("2", "3", "5", "6"))
    mid_span = abs(by_jersey["10"]["x"] - by_jersey["8"]["x"])
    assert def_span > mid_span
    # the narrow midfield pair still straddles the centre line evenly
    assert (by_jersey["8"]["x"] + by_jersey["10"]["x"]) / 2 == 50.0


def test_assign_pitch_positions_single_player_centres_row():
    from build import assign_pitch_positions
    out = assign_pitch_positions([{"jersey": "9", "pos_full": "Forward"}], gk_y=4, fwd_y=46)
    assert out[0]["x"] == 50.0
    assert out[0]["y"] == 46


def test_assign_pitch_positions_4231_gets_five_distinct_rows():
    # G, CD-L, LB, RB, CD-R, LM, AM-L, AM, RM, AM-R, F — a 4-2-3-1, not the
    # 4-5-1 it would flatten to if attacking midfielders weren't split from
    # the deeper two into their own, more advanced row.
    from build import assign_pitch_positions
    starters = [
        {"jersey": "1", "pos_full": "Goalkeeper"},
        {"jersey": "2", "pos_full": "Center Left Defender"},
        {"jersey": "3", "pos_full": "Left Back"},
        {"jersey": "4", "pos_full": "Right Back"},
        {"jersey": "5", "pos_full": "Center Right Defender"},
        {"jersey": "6", "pos_full": "Left Midfielder"},
        {"jersey": "7", "pos_full": "Attacking Midfielder Left"},
        {"jersey": "8", "pos_full": "Attacking Midfielder"},
        {"jersey": "9", "pos_full": "Right Midfielder"},
        {"jersey": "10", "pos_full": "Attacking Midfielder Right"},
        {"jersey": "11", "pos_full": "Forward"},
    ]
    out = assign_pitch_positions(starters, gk_y=96, fwd_y=54)
    by_jersey = {p["jersey"]: p for p in out}

    rows = sorted({by_jersey[j]["y"] for j in [str(n) for n in range(1, 12)]})
    assert len(rows) == 5, f"expected 5 distinct rows (GK/def/mid/AM/fwd), got {rows}"

    def_y = by_jersey["2"]["y"]
    mid_y = by_jersey["6"]["y"]
    am_y = by_jersey["7"]["y"]
    assert by_jersey["3"]["y"] == by_jersey["4"]["y"] == by_jersey["5"]["y"] == def_y
    assert by_jersey["9"]["y"] == mid_y
    assert by_jersey["8"]["y"] == by_jersey["10"]["y"] == am_y
    # attacking midfielders sit ahead of the regular midfielders — both
    # advancing from goal (96) toward the halfway line (54)
    assert 96 > def_y > mid_y > am_y > 54


def test_women_data_is_meaningful():
    from build import _women_data_is_meaningful
    # a real ingest_women.py run where every fetch came back empty (its own
    # output file always gets written regardless) shouldn't count as usable
    assert _women_data_is_meaningful({"table": [], "results": [], "upcoming": [],
                                      "squad": [], "news": [{"title": "x"}]}) is False
    assert _women_data_is_meaningful({}) is False
    assert _women_data_is_meaningful({"table": [{"team": "Ipswich"}]}) is True
    assert _women_data_is_meaningful({"squad": [{"name": "Player"}]}) is True
    assert _women_data_is_meaningful({"upcoming": [{"opponent": "X"}]}) is True


def test_is_live_now():
    from build import _is_live_now
    from datetime import datetime, timezone
    now = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
    assert _is_live_now(None, now) is False
    assert _is_live_now({}, now) is False
    assert _is_live_now({"kickoff": "2026-08-27T15:00:00Z"}, now) is True   # kicking off now
    assert _is_live_now({"kickoff": "2026-08-27T13:30:00Z"}, now) is True  # 90 min in
    assert _is_live_now({"kickoff": "2026-08-27T16:00:00Z"}, now) is False  # not kicked off yet
    assert _is_live_now({"kickoff": "2026-08-27T12:00:00Z"}, now) is False  # long finished
    assert _is_live_now({"kickoff": "not-a-date"}, now) is False


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


def test_ga_snippet_appears_only_when_measurement_id_set(tmp_path, monkeypatch):
    import build
    import json as _json
    data = build.sample_data(_live())
    monkeypatch.setattr(build, "SITE", tmp_path / "site")
    monkeypatch.setattr(build, "DATA", tmp_path / "itfc.json")
    monkeypatch.setattr(build, "GA_MEASUREMENT_ID", "G-TEST123")
    (tmp_path / "itfc.json").write_text(_json.dumps(data))
    build.main()
    idx = (tmp_path / "site" / "men" / "index.html").read_text()
    assert "googletagmanager.com/gtag/js?id=G-TEST123" in idx
    assert "gtag('config','G-TEST123')" in idx


def test_site_builds_end_to_end(tmp_path, monkeypatch):
    import build
    import json as _json
    data = build.sample_data(_live())
    monkeypatch.setattr(build, "SITE", tmp_path / "site")
    monkeypatch.setattr(build, "DATA", tmp_path / "itfc.json")
    (tmp_path / "itfc.json").write_text(_json.dumps(data))
    build.main()
    site = tmp_path / "site"
    assert (site / "index.html").exists(), "no root redirect page built"
    root_html = (site / "index.html").read_text()
    assert 'url=men/index.html' in root_html
    men = site / "men"
    for f in ["index.html", "table.html", "charts.html", "matches.html", "squad.html",
              "news.html", "sitemap.xml", "robots.txt"]:
        assert (site / f if f in ("sitemap.xml", "robots.txt") else men / f).exists(), f"missing {f}"
    assert (site / "style.css").exists(), "shared style.css missing from site root"
    assert list((men / "match").glob("*.html")), "no match pages built"
    assert list((men / "player").glob("*.html")), "no player pages built"
    idx = (men / "index.html").read_text()
    assert "{{" not in idx and "{%" not in idx, "unrendered Jinja in output"
    assert "Ipswich Town" in idx
    assert "googletagmanager" not in idx, "GA should be absent when GA_MEASUREMENT_ID isn't set"
    assert 'href="../style.css"' in idx, "men's top-level pages should reference the shared root style.css"
    match_html = next((men / "match").glob("*.html")).read_text()
    assert 'class="masthead' in match_html and 'href="../../style.css"' in match_html
    sitemap = (site / "sitemap.xml").read_text()
    match_slug = next((men / "match").glob("*.html")).stem
    player_slug = next((men / "player").glob("*.html")).stem
    assert f"men/match/{match_slug}.html" in sitemap
    assert f"men/player/{player_slug}.html" in sitemap
    assert "women/index.html" in sitemap
    assert "sitemap.xml" in (site / "robots.txt").read_text()
    assert (men / "preview.html").exists(), "no preview page built"
    assert "men/preview.html" in sitemap
    preview_html = (men / "preview.html").read_text()
    assert "{{" not in preview_html and "{%" not in preview_html
