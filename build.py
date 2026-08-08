"""
Render data/itfc.json into a static, multi-page site in ./site.

Each section (Overview, Table, Charts, Squad, News) is its own page with its own
URL (index.html, table.html, charts.html, squad.html, news.html). A full dummy-data
preview of every page is also built under ./site/preview so you can see how the site
looks with data present. A toggle in the header switches between live and preview.

Run:  python build.py
"""

import json
import shutil
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
    }


# --------------------------------------------------------------------------- #
def _make_env():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                      autoescape=select_autoescape(["html"]))
    env.filters["kickoff"] = fmt_kickoff
    env.filters["updated"] = fmt_updated
    env.filters["ordinal"] = lambda n: (
        f"{int(n)}{'th' if 11 <= int(n) % 100 <= 13 else {1:'st',2:'nd',3:'rd'}.get(int(n) % 10, 'th')}"
        if str(n).lstrip('-').isdigit() else n)
    return env


def render_site(template, data, preview):
    outdir = SITE / "preview" if preview else SITE
    (outdir / "data").mkdir(parents=True, exist_ok=True)
    data_json = json.dumps(data).replace("<", "\\u003c")
    for page_id, filename, _label in PAGES:
        toggle_href = f"../{filename}" if preview else f"preview/{filename}"
        html = template.render(data_json=data_json, page=page_id, current=page_id,
                               pages=PAGES, preview=preview, toggle_href=toggle_href, **data)
        (outdir / filename).write_text(html)
    (outdir / "data" / "itfc.json").write_text(json.dumps(data))


def main():
    real = json.loads(DATA.read_text())
    template = _make_env().get_template("index.html.j2")

    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    render_site(template, real, preview=False)                # live -> site/*.html
    render_site(template, sample_data(real), preview=True)    # dummy -> site/preview/*.html
    (SITE / ".nojekyll").write_text("")
    print(f"Built {len(PAGES)} pages (+ preview) into site/.")


if __name__ == "__main__":
    main()
