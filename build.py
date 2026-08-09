"""
Render data/itfc.json into a static, multi-page site in ./site.

Each section (Overview, Table, Charts, Squad, News) is its own page with its own
URL (index.html, table.html, charts.html, squad.html, news.html). A full dummy-data
preview of every page is also built under ./site/preview so you can see how the site
looks with data present. A toggle in the header switches between live and preview.

Run:  python build.py
"""

import json
import re
import shutil
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    LONDON = ZoneInfo("Europe/London")
except Exception:  # pragma: no cover
    LONDON = None

from jinja2 import Environment, FileSystemLoader, select_autoescape

DATA = Path("data/itfc.json")
SITE = Path("site")
TEMPLATES = Path("templates")

# (page id, output filename, nav label) — order defines the nav order.
PAGES = [
    ("overview", "index.html", "Overview"),
    ("table",    "table.html", "Table"),
    ("charts",   "charts.html", "Charts"),
    ("squad",    "squad.html",  "Squad"),
    ("news",     "news.html",   "News"),
]


def _ord(n):
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def fmt_kickoff(iso):
    if not iso:
        return "TBC"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "TBC"
    if LONDON:
        dt = dt.astimezone(LONDON)
    return dt.strftime("%a ") + f"{dt.day}{_ord(dt.day)} " + dt.strftime("%b, %H:%M")


def fmt_updated(iso):
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return dt.strftime("%d %b %Y, %H:%M UTC")


def season_summary(data):
    """A short, plain-language read on how the season is going, composed from the
    live numbers (projection, xPts, form, next fixture) so it updates every build."""
    def _an(n):  # "an 8/11/18/80s%" vs "a 45%"
        n = int(n)
        return "an" if n in (8, 11, 18) or 80 <= n <= 89 else "a"
    s = data.get("summary") or {}
    played = s.get("played", 0)
    team = (data.get("team") or {}).get("name", "Ipswich Town")
    nf, no = data.get("next_fixture"), data.get("next_opponent")

    if not played:  # pre-season
        bits = [f"The {data.get('season', '2026/27')} Premier League season is about to get under way."]
        if nf:
            venue = "at home to" if nf.get("home") else "away to"
            bits.append(f"{team} open {venue} {nf.get('opponent', 'their first opponents')} "
                        f"({fmt_kickoff(nf.get('kickoff', ''))}).")
        if no and no.get("prob"):
            bits.append(f"The model makes it {_an(no['prob']['ipswich'])} {no['prob']['ipswich']}% chance of a winning start.")
        return " ".join(bits)

    pts, pos = s.get("points", 0), data.get("position")
    won, drawn, lost = s.get("won", 0), s.get("drawn", 0), s.get("lost", 0)
    ppg = pts / played
    projected = round(ppg * 38)
    posx = f"{pos}{_ord(pos)}" if pos else "mid-table"

    parts = []
    # standing + recent form
    uh = data.get("understat_history") or []
    last5 = uh[-5:]
    if last5:
        pts5 = sum(3 if h.get("pts") == 3 else 1 if h.get("pts") == 1 else 0 for h in last5)
        parts.append(f"{team} sit {posx} after {played} games on {pts} points "
                     f"({won}W {drawn}D {lost}L), with {pts5} from the last five.")
    else:
        parts.append(f"{team} sit {posx} after {played} games on {pts} points ({won}W {drawn}D {lost}L).")

    # projection vs survival / euro line
    table = data.get("table") or []
    safe = next((r for r in table if r.get("rank") == 17), None)
    survival = round(safe["points"] / safe["played"] * 38) if safe and safe.get("played") else None
    if survival:
        if projected >= 66:
            parts.append(f"At that rate they'd finish on about {projected} points — a pace that would put them in the European conversation.")
        elif projected >= survival + 8:
            parts.append(f"That pace projects to around {projected} points, comfortably clear of the ~{survival} the drop looks likely to demand.")
        elif projected >= survival + 3:
            parts.append(f"That pace projects to around {projected} points, a cushion above the ~{survival} likely needed to stay up.")
        elif projected >= survival - 2:
            parts.append(f"That pace projects to around {projected} points — right on the ~{survival} likely needed for safety, so survival is finely balanced.")
        else:
            parts.append(f"That pace projects to around {projected} points, short of the ~{survival} likely needed to survive — a relegation fight as things stand.")
    else:
        parts.append(f"At their current rate that projects to around {projected} points over the season.")

    # underlying quality (xPts)
    if uh:
        xpts = round(sum(h.get("xpts", 0) for h in uh))
        diff = pts - xpts
        if diff >= 4:
            parts.append(f"They've outrun the underlying numbers — {pts} points from an expected {xpts} — so some regression may be due.")
        elif diff <= -4:
            parts.append(f"The performances merit more: an expected {xpts} points against {pts} banked suggests they've been unlucky.")
        else:
            parts.append(f"Points and expected points line up closely ({pts} vs {xpts}), so the table looks about deserved.")

    # next up
    if nf and no:
        prob = (no.get("prob") or {}).get("ipswich")
        tail = f", where the model gives them {_an(prob)} {prob}% win chance" if prob else ""
        parts.append(f"Next up: {nf.get('opponent')} ({'home' if nf.get('home') else 'away'}){tail}.")

    return " ".join(parts)


# --------------------------------------------------------------------------- #
#  Dummy data for the preview — plausible mid-season values for every section  #
# --------------------------------------------------------------------------- #
def sample_data(live=None):
    """Dummy stats for the preview, but real teams/badges/squad/news from live data
    so the preview reflects the actual club (and its badges actually load)."""
    live = live or {}
    team = live.get("team") or {"name": "Ipswich", "short_name": "IPS", "badge": None}
    ips_short, ips_badge = team.get("short_name", "IPS"), team.get("badge")

    # real opponents + working badges, taken from the live fixture list
    seen = {}
    for f in live.get("fixtures", []):
        s = f.get("opponent_short")
        if s and s not in seen:
            seen[s] = {"name": f.get("opponent"), "short": s, "badge": f.get("badge")}
    opponents = list(seen.values())
    if not opponents:  # fallback if live has no fixtures yet
        opponents = [{"name": n, "short": s, "badge": None} for n, s in [
            ("Arsenal", "ARS"), ("Man City", "MCI"), ("Liverpool", "LIV"), ("Chelsea", "CHE"),
            ("Aston Villa", "AVL"), ("Newcastle", "NEW"), ("Tottenham", "TOT"), ("Man Utd", "MUN"),
            ("Brighton", "BHA"), ("Bournemouth", "BOU"), ("West Ham", "WHU"), ("Fulham", "FUL"),
            ("Crystal Palace", "CRY"), ("Brentford", "BRE"), ("Wolves", "WOL"), ("Everton", "EVE"),
            ("Nott'm Forest", "NFO"), ("Sunderland", "SUN"), ("Burnley", "BUR")]]
    ips = {"name": "Ipswich Town", "short": ips_short, "badge": ips_badge}

    # league table: opponents with Ipswich slotted in at 14th
    ordered = opponents[:13] + [ips] + opponents[13:]
    ordered = ordered[:20]
    table = []
    for i, c in enumerate(ordered, 1):
        pts = max(6, 32 - i - i // 5)
        won, drawn = pts // 3, pts % 3
        lost = max(0, 12 - won - drawn)
        gf, ga = max(4, 27 - i), 8 + i
        table.append({"rank": i, "team": c["name"], "short": c["short"], "played": won + drawn + lost,
                      "won": won, "drawn": drawn, "lost": lost, "gf": gf, "ga": ga, "gd": gf - ga,
                      "points": pts, "is_ipswich": c["short"] == ips_short, "badge": c["badge"]})
    ipr = next((r for r in table if r["is_ipswich"]), table[-1])
    summary = {k: ipr[k] for k in ("played", "won", "drawn", "lost", "gf", "ga", "gd", "points")}

    team_scatter = [{"team": r["team"], "short": r["short"], "badge": r["badge"],
                     "xg_pg": round(2.4 - r["rank"] * 0.07, 2), "xga_pg": round(0.7 + r["rank"] * 0.05, 2),
                     "is_ipswich": r["is_ipswich"]} for r in table]
    team_ranks = [{"label": "Points", "value": ipr["points"], "rank": 14, "total": 20, "low_good": False},
                  {"label": "xG per game", "value": 1.22, "rank": 15, "total": 20, "low_good": False},
                  {"label": "xGA per game", "value": 1.55, "rank": 16, "total": 20, "low_good": True},
                  {"label": "Non-penalty xG", "value": 13.4, "rank": 15, "total": 20, "low_good": False},
                  {"label": "Pressing (PPDA)", "value": 11.8, "rank": 8, "total": 20, "low_good": True},
                  {"label": "Goal difference", "value": ipr["gd"], "rank": 14, "total": 20, "low_good": False}]

    # 38-game fixture list (each opponent home then away); ~first third finished
    schedule = [(c, True) for c in opponents] + [(c, False) for c in opponents]
    finished_count = min(12, len(schedule) // 2)
    base = datetime(2026, 8, 22, 14, 0, tzinfo=timezone.utc)
    fixtures, results, by_gameweek, cum = [], [], [], 0
    for gw, (c, home) in enumerate(schedule, 1):
        fx = {"event": gw, "opponent": c["name"], "opponent_short": c["short"], "home": home,
              "badge": c["badge"]}
        if gw <= finished_count:
            gfg, gag = (gw * 7) % 4, (gw * 5) % 4
            res = "W" if gfg > gag else "L" if gfg < gag else "D"
            fx.update({"finished": True, "score": f"{gfg}-{gag}", "result": res})
            results.append({"event": gw, "opponent": c["name"], "opponent_short": c["short"],
                            "home": home, "score": f"{gfg}-{gag}", "result": res, "badge": c["badge"]})
            pts = 3 if res == "W" else 1 if res == "D" else 0
            cum += pts
            by_gameweek.append({"gw": gw, "gf": gfg, "ga": gag, "pts": pts, "cum_points": cum,
                                "team_xg": round(1.0 + (gw % 3) * 0.4, 2),
                                "team_xga": round(0.8 + (gw % 4) * 0.3, 2)})
        else:
            fx.update({"finished": False,
                       "kickoff": (base + timedelta(days=7 * (gw - 1))).isoformat().replace("+00:00", "Z"),
                       "difficulty": (gw % 5) + 1})
        fixtures.append(fx)
    upcoming = [f for f in fixtures if not f["finished"]][:8]
    results = list(reversed(results))

    nxt = upcoming[0] if upcoming else None
    next_fixture = dict(nxt) if nxt else None
    next_opponent = None
    if nxt:
        next_opponent = {"name": nxt["opponent"], "short": nxt["opponent_short"], "badge": nxt["badge"],
                         "home": nxt["home"], "position": 9, "points": 18, "gd": 4, "xg_pg": 1.48,
                         "xga_pg": 1.12, "form": ["W", "D", "W", "L", "W"],
                         "prob": {"ipswich": 38, "draw": 27, "opponent": 35},
                         "h2h_record": {"w": 2, "d": 1, "l": 2},
                         "h2h": [{"date": "2025-12-21", "opponent": nxt["opponent"], "home": False, "score": "1-2", "result": "L"},
                                 {"date": "2025-08-17", "opponent": nxt["opponent"], "home": True, "score": "2-2", "result": "D"},
                                 {"date": "2024-04-30", "opponent": nxt["opponent"], "home": True, "score": "3-1", "result": "W"}]}

    # squad — real current players from live, with dummy stats layered on
    live_squad = live.get("squad") or []
    squad = []
    for i, p in enumerate(live_squad[:16]):
        pos = p.get("pos", "MID")
        mins = max(180, 1000 - i * 55)
        g = max(0, 8 - i) if pos == "FWD" else max(0, 4 - i // 2)
        a = max(0, 6 - i // 2)
        squad.append({**p, "minutes": mins, "starts": mins // 90, "goals": g, "assists": a,
                      "xg": round(g * 0.9, 2), "xa": round(a * 0.8, 2), "xgi": round(g * 0.9 + a * 0.8, 2),
                      "points": max(8, 120 - i * 8), "form": round(max(1.0, 6.0 - i * 0.3), 1),
                      "clean_sheets": 3 if pos in ("GKP", "DEF") else 0,
                      "selected": round(max(0.4, 15 - i), 1), "price": p.get("price", 5.0)})

    outfield = [s for s in squad if s["pos"] != "GKP"]
    pcts = [{"goals": 88, "assists": 45, "npxg": 82, "xa": 40, "shots": 75, "key_passes": 38, "xgchain": 70, "xgbuildup": 30},
            {"goals": 72, "assists": 80, "npxg": 68, "xa": 85, "shots": 66, "key_passes": 78, "xgchain": 74, "xgbuildup": 55},
            {"goals": 30, "assists": 62, "npxg": 25, "xa": 70, "shots": 40, "key_passes": 66, "xgchain": 60, "xgbuildup": 72}]
    player_profiles = [{"name": s["full_name"], "team": "Ipswich", "pos": s["pos"], "minutes": s["minutes"],
                        "per90": {k: round(v / 40, 2) for k, v in pcts[i].items()}, "pct": pcts[i],
                        "is_ipswich": True}
                       for i, s in enumerate(outfield[:3])]
    # a few non-Ipswich league players so the "any PL player" search has content in preview
    league_demo = [
        ("Mo Salah", "Liverpool", "F", {"goals": 95, "assists": 78, "npxg": 90, "xa": 72, "shots": 92, "key_passes": 80, "xgchain": 88, "xgbuildup": 60}),
        ("Bruno Fernandes", "Manchester United", "M", {"goals": 70, "assists": 88, "npxg": 66, "xa": 90, "shots": 74, "key_passes": 93, "xgchain": 85, "xgbuildup": 70}),
        ("Virgil van Dijk", "Liverpool", "D", {"goals": 40, "assists": 30, "npxg": 35, "xa": 28, "shots": 45, "key_passes": 40, "xgchain": 55, "xgbuildup": 82}),
        ("Cole Palmer", "Chelsea", "M", {"goals": 90, "assists": 82, "npxg": 85, "xa": 84, "shots": 88, "key_passes": 86, "xgchain": 87, "xgbuildup": 64}),
        ("Erling Haaland", "Manchester City", "F", {"goals": 99, "assists": 40, "npxg": 98, "xa": 45, "shots": 96, "key_passes": 42, "xgchain": 80, "xgbuildup": 35})]
    for nm, tm, pos, pct in league_demo:
        player_profiles.append({"name": nm, "team": tm, "pos": pos, "minutes": 1400,
                                "per90": {k: round(v / 40, 2) for k, v in pct.items()}, "pct": pct,
                                "is_ipswich": False})

    understat_players = [{"name": s["full_name"], "games": 12, "minutes": s["minutes"], "goals": s["goals"],
                          "assists": s["assists"], "shots": s["goals"] * 4 + 3, "xg": s["xg"], "xa": s["xa"],
                          "npg": s["goals"], "npxg": round(s["xg"] * 0.85, 2),
                          "xgchain": round(s["xg"] + s["xa"] + 1, 2), "xgbuildup": round(s["xa"] + 0.5, 2)}
                         for s in squad if s["minutes"] > 300][:8]

    shooters = [s["full_name"] for s in outfield[:4]] or ["Player One", "Player Two"]
    shot_maps = [{"match_id": "8", "opponent": results[0]["opponent"] if results else "Newcastle",
                  "home": True, "date": "2026-10-04", "score": "3-1", "xg_for": 2.3, "xg_against": 0.9,
                  "shots": [{"x": 0.88, "y": 0.45, "xg": 0.62, "result": "Goal", "player": shooters[0], "minute": 23, "situation": "OpenPlay"},
                            {"x": 0.80, "y": 0.55, "xg": 0.18, "result": "Goal", "player": shooters[1 % len(shooters)], "minute": 41, "situation": "FromCorner"},
                            {"x": 0.74, "y": 0.35, "xg": 0.09, "result": "SavedShot", "player": shooters[2 % len(shooters)], "minute": 58, "situation": "OpenPlay"},
                            {"x": 0.83, "y": 0.62, "xg": 0.44, "result": "Goal", "player": shooters[3 % len(shooters)], "minute": 77, "situation": "Penalty"}]}]
    understat_matches = [{"match_id": str(g["gw"]), "opponent": r["opponent"], "home": r["home"],
                          "date": "2026-09-01", "gf": g["gf"], "ga": g["ga"],
                          "xg_for": g["team_xg"], "xg_against": g["team_xga"]}
                         for g, r in zip(by_gameweek[-5:], results[:5])]
    # per-match history (xPts, PPDA, deep completions) + shot counts for the new charts
    understat_history, match_stats = [], []
    for i, g in enumerate(by_gameweek):
        won = g["pts"] == 3
        understat_history.append({"date": "2026-09-01", "h_a": "h" if i % 2 else "a",
            "xg": g["team_xg"], "xga": g["team_xga"], "npxg": round(g["team_xg"]*0.9, 2),
            "npxga": round(g["team_xga"]*0.9, 2), "deep": 8 + (i % 5), "deep_allowed": 6 + (i % 4),
            "scored": g["gf"], "conceded": g["ga"], "xpts": round(1.0 + (i % 3)*0.6, 2),
            "pts": g["pts"], "ppda": round(9.0 + (i % 5), 2), "ppda_allowed": round(11.0 - (i % 4), 2)})
        match_stats.append({"date": "2026-09-01", "opponent": g.get("opponent", "Opp"), "home": bool(i % 2),
            "shots_for": 10 + (i*3) % 8, "shots_against": 8 + (i*2) % 7,
            "sot_for": 3 + (i*2) % 5, "sot_against": 2 + i % 4,
            "corners_for": 4 + i % 5, "corners_against": 3 + i % 4})

    # full detail match pages (dummy) for the most recent results, and link them in
    def _shot(x, y, xg, res, pl, mn, sit):
        return {"x": x, "y": y, "xg": xg, "result": res, "player": pl, "minute": mn,
                "situation": sit, "assist": ""}
    sq_names = [s["full_name"] for s in squad] or ["Player One", "Player Two", "Player Three"]
    match_pages = []
    for i, r in enumerate(results[:4]):
        gf, ga = (int(x) for x in r["score"].split("-"))
        sfor = [_shot(0.90, 0.45, 0.55, "Goal" if gf > 0 else "SavedShot", sq_names[0], 20, "OpenPlay"),
                _shot(0.82, 0.40, 0.12, "SavedShot", sq_names[1 % len(sq_names)], 38, "OpenPlay"),
                _shot(0.88, 0.55, 0.30, "Goal" if gf > 1 else "MissedShots", sq_names[2 % len(sq_names)], 66, "FromCorner")]
        sag = [_shot(0.86, 0.50, 0.40, "Goal" if ga > 0 else "SavedShot", "Opponent striker", 55, "OpenPlay"),
               _shot(0.78, 0.60, 0.08, "MissedShots", "Opponent winger", 72, "OpenPlay")]
        goals = ([{"minute": s["minute"], "player": s["player"], "assist": "", "side": "for"} for s in sfor if s["result"] == "Goal"]
                 + [{"minute": s["minute"], "player": s["player"], "assist": "", "side": "against"} for s in sag if s["result"] == "Goal"])
        goals.sort(key=lambda g: g["minute"])
        pfor = [{"name": sq_names[j % len(sq_names)], "pos": "F" if j == 0 else "M", "minutes": 90,
                 "goals": 1 if (j == 0 and gf > 0) else 0, "assists": 0, "shots": (3 - j) if j < 3 else 1,
                 "xg": round(max(0.1, 0.6 - j * 0.1), 2), "xa": round(max(0.02, 0.2 - j * 0.03), 2),
                 "key_passes": (3 - j) if j < 3 else 0, "yellow": 1 if j == 4 else 0, "red": 0} for j in range(6)]
        pag = [{"name": "Opponent " + p, "pos": q, "minutes": 90, "goals": 0, "assists": 0, "shots": 1,
                "xg": 0.2, "xa": 0.1, "key_passes": 1, "yellow": 0, "red": 0}
               for p, q in [("striker", "F"), ("winger", "M"), ("midfielder", "M"), ("defender", "D")]]
        match_pages.append({
            "id": "demo" + str(i + 1), "opponent": r["opponent"], "opponent_short": r["opponent_short"],
            "opponent_badge": r["badge"], "team_badge": ips_badge, "home": r["home"], "date": "2026-10-04",
            "score": r["score"], "gf": gf, "ga": ga, "result": r["result"],
            "xg_for": round(1.4 + gf * 0.3, 2), "xg_against": round(0.8 + ga * 0.3, 2),
            "ht_score": f"{min(gf,1)}-{min(ga,1)}", "referee": "M. Oliver",
            "odds": {"win": 42, "draw": 27, "opp": 31}, "xpts": round(1.2 + gf * 0.4, 2),
            "deep": 9 + i, "deep_allowed": 6 + i, "ppda": round(9.5 + i, 2), "ppda_allowed": round(11.0 - i, 2),
            "fbd": {"shots_for": 14, "shots_against": 9, "sot_for": 6, "sot_against": 3,
                    "corners_for": 7, "corners_against": 4, "fouls_for": 10, "fouls_against": 12,
                    "yellows_for": 1, "yellows_against": 2, "reds_for": 0, "reds_against": 0},
            "shots_for": sfor, "shots_against": sag, "players_for": pfor, "players_against": pag,
            "goals": goals, "h2h": next_opponent["h2h"] if next_opponent else []})
    mpid = {(mp["opponent_short"], mp["home"]): mp["id"] for mp in match_pages}
    for r in results:
        r["match_id"] = mpid.get((r["opponent_short"], r["home"]))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": live.get("season", "2026/27"),
        "team": {"id": 8, "name": team.get("name", "Ipswich"), "short_name": ips_short, "badge": ips_badge},
        "current_event": 12, "next_event": 13,
        "next_fixture": next_fixture, "next_opponent": next_opponent,
        "team_news": [
            {"player": "Wes Burns", "news": "Hamstring injury - 50% chance of playing", "tag": "Injured", "sev": "doubt"},
            {"player": "Sam Morsy", "news": "Suspended - 1 match ban", "tag": "Suspended", "sev": "out"}],
        "position": ipr["rank"], "summary": summary, "table": table,
        "team_scatter": team_scatter, "team_ranks": team_ranks, "player_profiles": player_profiles,
        "by_gameweek": by_gameweek, "understat_matches": understat_matches, "shot_maps": shot_maps,
        "understat_players": understat_players, "upcoming": upcoming, "fixtures": fixtures,
        "understat_history": understat_history, "match_stats": match_stats,
        "results": results, "squad": squad, "news": live.get("news") or [],
        "match_pages": match_pages,
    }


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
def _pnorm(name):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _pslug(name):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "player"


def build_player_pages(data):
    """One page's data per squad player: FPL + Understat totals, percentile profile,
    match-by-match log and personal shot map. Stamps a slug on each squad entry so
    the squad table can link out."""
    squad = data.get("squad") or []
    us_by = {_pnorm(p["name"]): p for p in (data.get("understat_players") or [])}
    prof_by = {_pnorm(p["name"]): p for p in (data.get("player_profiles") or [])}
    matches = data.get("match_pages") or []

    def find(d, full):
        k = _pnorm(full)
        if k in d:
            return d[k]
        ln = _pnorm(full.split()[-1]) if full and full.split() else ""
        for kk, v in d.items():
            if ln and len(ln) > 2 and (kk.endswith(ln) or ln in kk):
                return v
        return None

    pages, used = [], {}
    for sp in squad:
        full = sp.get("full_name") or sp.get("name") or "Player"
        slug = _pslug(full)
        used[slug] = used.get(slug, 0) + 1
        if used[slug] > 1:
            slug = f"{slug}-{used[slug]}"
        sp["slug"] = slug
        key = _pnorm(full)
        ln = _pnorm(full.split()[-1]) if full.split() else ""

        def same(nm, _key=key, _ln=ln):
            k = _pnorm(nm)
            return k == _key or (_ln and len(_ln) > 2 and (k.endswith(_ln) or _ln in k))

        log, shots = [], []
        for m in matches:
            pl = next((x for x in m.get("players_for", []) if same(x["name"])), None)
            if pl:
                log.append({"opponent": m["opponent"], "opponent_badge": m.get("opponent_badge"),
                            "home": m["home"], "result": m["result"], "score": m["score"],
                            "date": m["date"], "match_id": m["id"], "minutes": pl["minutes"],
                            "goals": pl["goals"], "assists": pl["assists"], "shots": pl["shots"],
                            "xg": pl["xg"], "xa": pl["xa"], "key_passes": pl.get("key_passes", 0)})
            for s in m.get("shots_for", []):
                if same(s["player"]):
                    shots.append({"x": s["x"], "y": s["y"], "xg": s["xg"], "result": s["result"],
                                  "minute": s["minute"], "situation": s.get("situation", ""),
                                  "opponent": m["opponent"]})
        pages.append({"slug": slug, "name": full, "web_name": sp.get("name"), "pos": sp.get("pos"),
                      "fpl": sp, "us": find(us_by, full), "profile": find(prof_by, full),
                      "log": log, "shots": shots})
    return pages


def _make_env():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                      autoescape=select_autoescape(["html"]))
    env.filters["kickoff"] = fmt_kickoff
    env.filters["updated"] = fmt_updated
    env.filters["ordinal"] = lambda n: (
        f"{int(n)}{'th' if 11 <= int(n) % 100 <= 13 else {1:'st',2:'nd',3:'rd'}.get(int(n) % 10, 'th')}"
        if str(n).lstrip('-').isdigit() else n)
    return env


def render_site(template, match_template, player_template, data, preview):
    outdir = SITE / "preview" if preview else SITE
    (outdir / "data").mkdir(parents=True, exist_ok=True)
    player_pages = build_player_pages(data)     # stamps slug on each squad entry
    data_json = json.dumps(data).replace("<", "\\u003c")
    summary_text = season_summary(data)
    for page_id, filename, _label in PAGES:
        toggle_href = f"../{filename}" if preview else f"preview/{filename}"
        html = template.render(data_json=data_json, page=page_id, current=page_id,
                               pages=PAGES, preview=preview, toggle_href=toggle_href,
                               summary_text=summary_text, **data)
        (outdir / filename).write_text(html)
    (outdir / "data" / "itfc.json").write_text(json.dumps(data))

    # a full detail page per finished match
    matches = data.get("match_pages", [])
    if matches:
        (outdir / "match").mkdir(exist_ok=True)
        for mp in matches:
            match_json = json.dumps({"opponent": mp.get("opponent", ""),
                                     "shots_for": mp.get("shots_for", []),
                                     "shots_against": mp.get("shots_against", [])}).replace("<", "\\u003c")
            html = match_template.render(m=mp, season=data.get("season", ""),
                                         generated_at=data.get("generated_at", ""),
                                         preview=preview, match_json=match_json)
            (outdir / "match" / f"{mp['id']}.html").write_text(html)

    # a page per squad player
    if player_pages:
        (outdir / "player").mkdir(exist_ok=True)
        for pp in player_pages:
            player_json = json.dumps({"shots": pp["shots"],
                                      "log": list(reversed(pp["log"]))}).replace("<", "\\u003c")
            html = player_template.render(p=pp, season=data.get("season", ""),
                                          preview=preview, player_json=player_json)
            (outdir / "player" / f"{pp['slug']}.html").write_text(html)


def main():
    real = json.loads(DATA.read_text())
    env = _make_env()
    template = env.get_template("index.html.j2")
    match_template = env.get_template("match.html.j2")
    player_template = env.get_template("player.html.j2")

    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    render_site(template, match_template, player_template, real, preview=False)
    render_site(template, match_template, player_template, sample_data(real), preview=True)
    (SITE / ".nojekyll").write_text("")
    n = len(real.get("match_pages", []))
    print(f"Built {len(PAGES)} pages + {n} match pages + {len(real.get('squad', []))} player pages (+ preview).")


if __name__ == "__main__":
    main()
