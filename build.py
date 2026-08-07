"""
Render data/itfc.json into a static, multi-page site in ./site.

Each section (Overview, Table, Charts, Squad, News) is its own page with its own
URL (index.html, table.html, charts.html, squad.html, news.html). A full dummy-data
preview of every page is also built under ./site/preview so you can see how the site
looks with data present. A toggle in the header switches between live and preview.

Run:  python build.py
"""

import base64
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


def _pl_badge(code):
    return f"https://resources.premierleague.com/premierleague/badges/50/{code}.png"


# --------------------------------------------------------------------------- #
#  Dummy data for the preview — plausible mid-season values for every section  #
# --------------------------------------------------------------------------- #
def _ph_image(seed):
    """A self-contained SVG placeholder so preview images render with no network."""
    colours = ["#5645d4", "#1a2a52", "#dd5b00", "#1aae39", "#0075de"]
    c = colours[seed % len(colours)]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="132" height="88">'
           f'<rect width="132" height="88" fill="{c}"/>'
           f'<text x="66" y="48" font-family="Inter,sans-serif" font-size="13" '
           f'fill="#fff" text-anchor="middle">Preview</text></svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def sample_data():
    # 20 clubs in table order; Ipswich placed 14th. (name, short, FPL code)
    clubs = [
        ("Arsenal", "ARS", 3), ("Man City", "MCI", 43), ("Liverpool", "LIV", 14),
        ("Chelsea", "CHE", 8), ("Aston Villa", "AVL", 7), ("Newcastle", "NEW", 4),
        ("Tottenham", "TOT", 6), ("Man Utd", "MUN", 1), ("Brighton", "BHA", 36),
        ("Bournemouth", "BOU", 91), ("West Ham", "WHU", 21), ("Fulham", "FUL", 54),
        ("Crystal Palace", "CRY", 31), ("Ipswich Town", "IPS", 40), ("Brentford", "BRE", 94),
        ("Wolves", "WOL", 39), ("Everton", "EVE", 11), ("Nott'm Forest", "NFO", 17),
        ("Sunderland", "SUN", 56), ("Burnley", "BUR", 90),
    ]
    by_short = {s: (n, s, c) for n, s, c in clubs}

    # league table by rank
    table = []
    for i, (name, short, code) in enumerate(clubs, 1):
        pts = max(5, 30 - i - (i // 6))
        won, drawn = pts // 3, pts % 3
        lost = max(0, 12 - won - drawn)
        gf, ga = max(4, 26 - i), 8 + i
        table.append({"rank": i, "team": name, "short": short, "played": won + drawn + lost,
                      "won": won, "drawn": drawn, "lost": lost, "gf": gf, "ga": ga,
                      "gd": gf - ga, "points": pts, "is_ipswich": short == "IPS",
                      "badge": _pl_badge(code)})
    ips = next(r for r in table if r["is_ipswich"])
    summary = {k: ips[k] for k in ("played", "won", "drawn", "lost", "gf", "ga", "gd", "points")}

    # xG scatter + ranks
    team_scatter = [{"team": r["team"], "short": r["short"], "badge": r["badge"],
                     "xg_pg": round(2.4 - r["rank"] * 0.07, 2), "xga_pg": round(0.7 + r["rank"] * 0.05, 2),
                     "is_ipswich": r["is_ipswich"]} for r in table]
    team_ranks = [{"label": "Points", "value": ips["points"], "rank": 14, "total": 20, "low_good": False},
                  {"label": "xG per game", "value": 1.22, "rank": 15, "total": 20, "low_good": False},
                  {"label": "xGA per game", "value": 1.55, "rank": 16, "total": 20, "low_good": True},
                  {"label": "Non-penalty xG", "value": 13.4, "rank": 15, "total": 20, "low_good": False},
                  {"label": "Pressing (PPDA)", "value": 11.8, "rank": 8, "total": 20, "low_good": True},
                  {"label": "Goal difference", "value": ips["gd"], "rank": 14, "total": 20, "low_good": False}]

    # 38-game fixture list: every opponent home then away
    opponents = [c for c in clubs if c[1] != "IPS"]
    schedule = [(c, True) for c in opponents] + [(c, False) for c in opponents]
    base = datetime(2026, 8, 22, 14, 0, tzinfo=timezone.utc)
    fixtures, results, by_gameweek, cum = [], [], [], 0
    for gw, ((name, short, code), home) in enumerate(schedule, 1):
        fx = {"event": gw, "opponent": name, "opponent_short": short, "home": home,
              "badge": _pl_badge(code)}
        if gw <= 12:
            gfg, gag = (gw * 7) % 4, (gw * 5) % 4
            res = "W" if gfg > gag else "L" if gfg < gag else "D"
            fx.update({"finished": True, "score": f"{gfg}-{gag}", "result": res})
            results.append({"event": gw, "opponent": name, "opponent_short": short, "home": home,
                            "score": f"{gfg}-{gag}", "result": res, "badge": _pl_badge(code)})
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
    nxt = upcoming[0]
    on, os_, oc = by_short[nxt["opponent_short"]]
    next_fixture = dict(nxt)
    next_opponent = {"name": on, "short": os_, "badge": _pl_badge(oc), "home": nxt["home"],
                     "position": 9, "points": 18, "gd": 4, "xg_pg": 1.48, "xga_pg": 1.12,
                     "form": ["W", "D", "W", "L", "W"],
                     "prob": {"ipswich": 38, "draw": 27, "opponent": 35},
                     "h2h_record": {"w": 2, "d": 1, "l": 2},
                     "h2h": [{"date": "2025-12-21", "opponent": on, "home": False, "score": "1-2", "result": "L"},
                             {"date": "2025-08-17", "opponent": on, "home": True, "score": "2-2", "result": "D"},
                             {"date": "2024-04-30", "opponent": on, "home": True, "score": "3-1", "result": "W"}]}

    team_news = [
        {"player": "Wes Burns", "news": "Hamstring injury - 50% chance of playing", "tag": "Injured", "sev": "doubt"},
        {"player": "Sam Morsy", "news": "Suspended - 1 match ban", "tag": "Suspended", "sev": "out"},
        {"player": "Cameron Burgess", "news": "Knee injury - unknown return date", "tag": "Injured", "sev": "out"}]

    # squad
    names = [("Liam Delap", "FWD", 4), ("Omari Hutchinson", "MID", 3), ("Jack Clarke", "MID", 3),
             ("Conor Chaplin", "MID", 3), ("Nathan Broadhead", "FWD", 4), ("Sam Morsy", "MID", 3),
             ("Kalvin Phillips", "MID", 3), ("Leif Davis", "DEF", 2), ("Dara O'Shea", "DEF", 2),
             ("Jacob Greaves", "DEF", 2), ("Ben Johnson", "DEF", 2), ("Axel Tuanzebe", "DEF", 2),
             ("Arijanet Muric", "GKP", 1), ("Christian Walton", "GKP", 1)]
    squad = []
    for i, (nm, pos, pid) in enumerate(names):
        mins = max(180, 1000 - i * 60)
        g = max(0, 8 - i) if pos == "FWD" else max(0, 4 - i // 2)
        a = max(0, 6 - i // 2)
        squad.append({"name": nm.split()[-1], "full_name": nm, "pos": pos, "pos_id": pid,
                      "price": round(6.5 - i * 0.2, 1), "points": max(8, 120 - i * 8),
                      "form": round(max(1.0, 6.0 - i * 0.3), 1), "minutes": mins,
                      "starts": mins // 90, "goals": g, "assists": a,
                      "xg": round(g * 0.9, 2), "xa": round(a * 0.8, 2), "xgi": round(g * 0.9 + a * 0.8, 2),
                      "clean_sheets": 3 if pos in ("GKP", "DEF") else 0,
                      "selected": round(max(0.4, 15 - i), 1)})

    profs = [("Liam Delap", "FWD", {"goals": 88, "assists": 45, "npxg": 82, "xa": 40, "shots": 75,
                                    "key_passes": 38, "xgchain": 70, "xgbuildup": 30}),
             ("Omari Hutchinson", "MID", {"goals": 72, "assists": 80, "npxg": 68, "xa": 85, "shots": 66,
                                          "key_passes": 78, "xgchain": 74, "xgbuildup": 55}),
             ("Leif Davis", "DEF", {"goals": 30, "assists": 88, "npxg": 25, "xa": 90, "shots": 40,
                                    "key_passes": 82, "xgchain": 60, "xgbuildup": 70})]
    player_profiles = [{"name": n, "team": "Ipswich", "pos": p, "minutes": 950 - i * 40,
                        "per90": {k: round(v / 40, 2) for k, v in pct.items()}, "pct": pct}
                       for i, (n, p, pct) in enumerate(profs)]

    understat_matches = [{"match_id": str(g["gw"]), "opponent": r["opponent"], "home": r["home"],
                          "date": "2026-09-01", "gf": g["gf"], "ga": g["ga"],
                          "xg_for": g["team_xg"], "xg_against": g["team_xga"]}
                         for g, r in zip(by_gameweek[-5:], results[:5])]
    shot_maps = [{"match_id": "8", "opponent": "Newcastle", "home": True, "date": "2026-10-04",
                  "score": "3-1", "xg_for": 2.3, "xg_against": 0.9,
                  "shots": [{"x": 0.88, "y": 0.45, "xg": 0.62, "result": "Goal", "player": "Liam Delap", "minute": 23},
                            {"x": 0.80, "y": 0.55, "xg": 0.18, "result": "Goal", "player": "Omari Hutchinson", "minute": 41},
                            {"x": 0.74, "y": 0.35, "xg": 0.09, "result": "SavedShot", "player": "Jack Clarke", "minute": 58},
                            {"x": 0.83, "y": 0.62, "xg": 0.44, "result": "Goal", "player": "Nathan Broadhead", "minute": 77},
                            {"x": 0.68, "y": 0.5, "xg": 0.05, "result": "MissedShots", "player": "Conor Chaplin", "minute": 84}]}]
    understat_players = [{"name": s["full_name"], "games": 12, "minutes": s["minutes"], "goals": s["goals"],
                          "assists": s["assists"], "shots": s["goals"] * 4 + 3, "xg": s["xg"], "xa": s["xa"],
                          "npg": s["goals"], "npxg": round(s["xg"] * 0.85, 2),
                          "xgchain": round(s["xg"] + s["xa"] + 1, 2), "xgbuildup": round(s["xa"] + 0.5, 2)}
                         for s in squad if s["minutes"] > 300][:8]

    news = [
        {"title": "Ipswich complete signing of highly-rated winger on a four-year deal",
         "link": "https://example.com/1", "source": "BBC Sport", "date": "2026-11-08T09:00:00+00:00",
         "date_display": "8 Nov", "image": _ph_image(0),
         "summary": "Ipswich Town have completed the signing of a highly-rated winger. The 22-year-old "
                    "becomes the club's third addition of the window and is expected to feature at the "
                    "weekend. The manager praised his pace and directness, qualities the side has looked "
                    "to add in the final third throughout the campaign so far this season."},
        {"title": "Player ratings from a hard-fought draw at the weekend",
         "link": "https://example.com/2", "source": "TWTD", "date": "2026-11-07T18:00:00+00:00",
         "date_display": "7 Nov", "image": _ph_image(1),
         "summary": "A resolute defensive display earned a point on the road. The back line looked "
                    "composed and the midfield controlled long spells, though the finishing needs "
                    "sharpening ahead of a busy December schedule."},
        {"title": "Everything you need to know ahead of the next home fixture",
         "link": "https://example.com/3", "source": "ITFC.CO.UK", "date": "2026-11-06T12:00:00+00:00",
         "date_display": "6 Nov", "image": None,
         "summary": "Team news, ticket information and travel details ahead of Saturday's match at "
                    "Portman Road. Gates open two hours before kick-off."},
        {"title": "Loan watch: how the young Tractor Boys fared elsewhere",
         "link": "https://example.com/4", "source": "EADT", "date": "2026-11-05T15:00:00+00:00",
         "date_display": "5 Nov", "image": _ph_image(3),
         "summary": "A round-up of the academy graduates out on loan, with two goals and an assist "
                    "between them across the divisions this weekend."}]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": "2026/27",
        "team": {"id": 8, "name": "Ipswich", "short_name": "IPS", "badge": _pl_badge(40)},
        "current_event": 12, "next_event": 13,
        "next_fixture": next_fixture, "next_opponent": next_opponent, "team_news": team_news,
        "position": ips["rank"], "summary": summary, "table": table,
        "team_scatter": team_scatter, "team_ranks": team_ranks, "player_profiles": player_profiles,
        "by_gameweek": by_gameweek, "understat_matches": understat_matches, "shot_maps": shot_maps,
        "understat_players": understat_players, "upcoming": upcoming, "fixtures": fixtures,
        "results": results, "squad": squad, "news": news,
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
    render_site(template, real, preview=False)          # live -> site/*.html
    render_site(template, sample_data(), preview=True)  # dummy -> site/preview/*.html
    (SITE / ".nojekyll").write_text("")
    print(f"Built {len(PAGES)} pages (+ preview) into site/.")


if __name__ == "__main__":
    main()
