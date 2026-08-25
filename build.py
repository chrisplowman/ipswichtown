"""
Render data/itfc.json into a static, multi-page site in ./site.

Each section (Overview, Table, Charts, Squad, News) is its own page with its own
URL (index.html, table.html, charts.html, squad.html, news.html).

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
DATA_WOMEN = Path("data/itfc_women.json")
SITE = Path("site")
TEMPLATES = Path("templates")
ASSETS = Path("assets")

# (page id, output filename, nav label) — order defines the nav order.
PAGES = [
    ("overview", "index.html", "Overview"),
    ("table",    "table.html", "Table"),
    ("charts",   "charts.html", "Charts"),
    ("matches",  "matches.html", "Matches"),
    ("squad",    "squad.html",  "Squad"),
    ("news",     "news.html",   "News"),
]

# Women's team pages: a trimmed subset — no Charts (no free xG/shot source for
# WSL2 exists yet; see templates/women.html.j2's footer note).
WOMEN_PAGES = [
    ("overview", "index.html", "Overview"),
    ("table",    "table.html", "Table"),
    ("matches",  "matches.html", "Matches"),
    ("squad",    "squad.html",  "Squad"),
    ("news",     "news.html",   "News"),
]

# per-page Open Graph title/description
OG = {
    "overview": ("Ipswich Town: Premier League stats", "Live xG, form, the projected table and a survival forecast for Ipswich Town's Premier League season."),
    "table":    ("Ipswich Town: Premier League table", "The live table, projected final standings and home/away splits."),
    "charts":   ("Ipswich Town: season charts", "xG, expected points, pressing, discipline and more, chart by chart."),
    "matches":  ("Ipswich Town: match results", "Every result this season with xG, and a full report for each match."),
    "squad":    ("Ipswich Town: squad stats", "Per-90 stats and percentile profiles for the Ipswich squad."),
    "news":     ("Ipswich Town: latest news", "The latest Ipswich Town headlines from across the web."),
}


def _ord(n):
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL = True
except Exception:  # pragma: no cover
    _PIL = False

SITE_URL = "https://chrisplowman.github.io/ipswichtown"


def _font(size, bold=False):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""),
              "/usr/share/fonts/truetype/liberation/LiberationSans%s.ttf" % ("-Bold" if bold else "")]:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _og_image(path, title, subtitle):
    """Draw a 1200x630 branded share card (best-effort; skipped if Pillow is absent)."""
    if not _PIL:
        return False
    try:
        img = Image.new("RGB", (1200, 630), (10, 21, 48))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, 1200, 12], fill=(221, 91, 0))
        d.text((70, 88), "IPSWICH TOWN", font=_font(34, True), fill=(174, 183, 204))
        words, lines, cur, f = title.split(), [], "", _font(74, True)
        for w in words:
            test = (cur + " " + w).strip()
            if d.textlength(test, font=f) > 1060 and cur:
                lines.append(cur); cur = w
            else:
                cur = test
        lines.append(cur)
        y = 175
        for ln in lines[:4]:
            d.text((70, y), ln, font=f, fill=(255, 255, 255)); y += 90
        d.text((70, 548), subtitle, font=_font(29), fill=(174, 183, 204))
        img.save(path)
        return True
    except Exception:
        return False


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


# Clubs whose Guardian URL slug diverges from a naive slugify() of the name
# Understat/FPL give us (see guardian_report_url below) — e.g. "West Ham
# United" slugifies to "west-ham-united" but the Guardian's own slug is just
# "west-ham". Unlisted opponents (Sunderland, Liverpool, Arsenal, Chelsea,
# Everton, Fulham, Brentford, Burnley, Bournemouth, ...) already match a
# plain slugify() of their common name.
_GUARDIAN_SLUGS = {
    "man utd": "manchester-united", "man united": "manchester-united", "manchester united": "manchester-united",
    "man city": "manchester-city", "manchester city": "manchester-city",
    "spurs": "tottenham-hotspur", "tottenham": "tottenham-hotspur", "tottenham hotspur": "tottenham-hotspur",
    "newcastle": "newcastle-united", "newcastle united": "newcastle-united",
    "west ham": "west-ham", "west ham united": "west-ham",
    "wolves": "wolverhampton-wanderers", "wolverhampton wanderers": "wolverhampton-wanderers",
    "nott'm forest": "nottingham-forest", "nottingham forest": "nottingham-forest",
    "leeds": "leeds-united", "leeds united": "leeds-united",
    "brighton": "brighton-and-hove-albion", "brighton and hove albion": "brighton-and-hove-albion",
    "leicester": "leicester-city", "leicester city": "leicester-city",
    "sheffield utd": "sheffield-united", "sheffield united": "sheffield-united",
    "west brom": "west-brom", "west bromwich albion": "west-brom",
    "qpr": "queens-park-rangers", "queens park rangers": "queens-park-rangers",
}


def _slugify(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def guardian_report_url(mp):
    """Best-effort link to the Guardian's own match report, built from its
    predictable URL scheme (.../football/<year>/<mon>/<day>/<home>-<away>-
    premier-league-match-report) since the Guardian has no public API to
    look this up properly. Team slugs come from _GUARDIAN_SLUGS for the
    clubs where that differs from a plain slugify(), and slugify() for
    everything else. Unverified against the live site, so this can 404 for
    a match the Guardian didn't cover (or a name this map doesn't catch) —
    it's a predictable guess, not a confirmed link."""
    try:
        d = datetime.strptime((mp.get("date") or "")[:10], "%Y-%m-%d")
    except ValueError:
        return None
    opp = (mp.get("opponent") or "").strip()
    opp_slug = _GUARDIAN_SLUGS.get(opp.lower()) or _slugify(opp)
    if not opp_slug:
        return None
    home_slug, away_slug = ("ipswich", opp_slug) if mp.get("home") else (opp_slug, "ipswich")
    return (f"https://www.theguardian.com/football/{d.year}/{d.strftime('%b').lower()}/{d.day}/"
            f"{home_slug}-{away_slug}-premier-league-match-report")


def match_report_links(mp):
    """External match-report links for one match, from outlets whose report
    URL is genuinely derivable rather than an opaque numeric/hash ID — which
    rules out most UK football sites (Sky Sports, the BBC's newer article
    IDs, the Mirror, the Independent, football.london, WhoScored, FotMob,
    Transfermarkt, ...) and is also why this list stays short by
    construction, not by hand-picking: tabloids like the Sun and the Daily
    Mail aren't included on principle either way.
    - The Guardian: date + team-slug URL scheme (guardian_report_url above);
      unverified against the live site, so it's a best-effort guess that can
      404 for a match the Guardian didn't cover.
    - ESPN: the exact report URL ESPN itself serves for the matching event
      (espn_report_url, stamped in ingest.py from the same event id used for
      cards/subs/lineups) — not a guess, just not always present.
    - Understat: mp["id"] already *is* Understat's own match id (it's what
      fetch_understat() used to pull this match's xG/shots in the first
      place), so its match page is an exact link, not a guess."""
    links = []
    guardian = guardian_report_url(mp)
    if guardian:
        links.append({"name": "The Guardian", "url": guardian})
    if mp.get("espn_report_url"):
        links.append({"name": "ESPN", "url": mp["espn_report_url"]})
    if mp.get("id"):
        links.append({"name": "Understat", "url": f"https://understat.com/match/{mp['id']}"})
    return links


def _pitch_band(pos_full):
    """GK / defence / (regular) midfield / attacking midfield / attack, from
    ESPN's own position name text (e.g. "Center Left Defender", "Attacking
    Midfielder Left", "Forward") — a formation string like "4-2-3-1" only
    gives row *sizes*, not which specific players are in which row, and
    ESPN's numeric formationPlace slot (1-11) isn't a reliably documented
    guide to that either without a hand-verified table per formation shape.
    Band text is self-describing and works for any formation: an explicit
    "Attacking Midfielder" (left/right/centre) gets its own more advanced
    band ahead of plain midfielders (e.g. 4-2-3-1's back two vs front
    three), so a formation isn't flattened into one midfield row it isn't."""
    name = (pos_full or "").lower()
    if "goalkeeper" in name:
        return "gk"
    if "back" in name or "defender" in name:
        return "def"
    if "forward" in name or "striker" in name or "winger" in name:
        return "fwd"
    if "attacking" in name:
        return "am"
    return "mid"


def _pitch_side(pos_full):
    name = (pos_full or "").lower()
    if "left" in name:
        return -1
    if "right" in name:
        return 1
    return 0


def assign_pitch_positions(starters, gk_y, fwd_y):
    """Places each starter on a schematic pitch as x/y percentages (x: 0
    left touchline to 100 right; y: gk_y at this side's own goal to fwd_y
    at the halfway line), banded by _pitch_band/_pitch_side above. Two
    calls with mirrored gk_y/fwd_y ranges — one per side — lay both teams
    out on a single shared pitch, facing off across the halfway line.
    gk_y/fwd_y are fixed endpoints; whichever of def/mid/am are actually
    present (e.g. a back three with no "Attacking Midfielder"-labelled
    player has no "am" row) are spaced evenly between them, so a plain
    4-3-3 still gets the same even four-row spacing it always did, and a
    4-2-3-1 gets a true fifth row for its attacking-midfield three instead
    of it being folded into one flat five-wide midfield line."""
    bands = {"gk": [], "def": [], "mid": [], "am": [], "fwd": []}
    for p in starters:
        bands[_pitch_band(p.get("pos_full"))].append(p)
    interior = [b for b in ("def", "mid", "am") if bands[b]]
    step = (fwd_y - gk_y) / (len(interior) + 1)
    band_y = {"gk": gk_y, "fwd": fwd_y}
    for i, b in enumerate(interior, start=1):
        band_y[b] = gk_y + step * i
    out = []
    for band in ("gk", "def", "mid", "am", "fwd"):
        players = bands[band]
        if not players:
            continue
        ordered = sorted(players, key=lambda p: (_pitch_side(p.get("pos_full")), p.get("jersey") or ""))
        n = len(ordered)
        y = round(band_y[band], 1)
        # A row's width scales with its own player count rather than always
        # spanning the full 14-86 touchline-to-touchline range: a back four
        # (n=4, the reference width) reaches the same near-touchline spread
        # it always did, but a two-man central midfield sits narrow and
        # central rather than stretched out to the same width as the
        # fullbacks either side of it — narrower rows are that way because
        # they're genuinely more central players (a double pivot), not just
        # because there happen to be fewer of them.
        half_span = 36 * min(1.0, (n - 1) / 3) if n > 1 else 0
        for j, p in enumerate(ordered):
            x = 50.0 if n == 1 else 50 - half_span + j * (2 * half_span) / (n - 1)
            out.append({**p, "x": round(x, 1), "y": y})
    return out


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
            parts.append(f"At that rate they'd finish on about {projected} points, a pace that would put them in the European conversation.")
        elif projected >= survival + 8:
            parts.append(f"That pace projects to around {projected} points, comfortably clear of the ~{survival} the drop looks likely to demand.")
        elif projected >= survival + 3:
            parts.append(f"That pace projects to around {projected} points, a cushion above the ~{survival} likely needed to stay up.")
        elif projected >= survival - 2:
            parts.append(f"That pace projects to around {projected} points, right on the ~{survival} likely needed for safety, so survival is finely balanced.")
        else:
            parts.append(f"That pace projects to around {projected} points, short of the ~{survival} likely needed to survive: a relegation fight as things stand.")
    else:
        parts.append(f"At their current rate that projects to around {projected} points over the season.")

    # underlying quality (xPts)
    if uh:
        xpts = round(sum(h.get("xpts", 0) for h in uh))
        diff = pts - xpts
        if diff >= 4:
            parts.append(f"They've outrun the underlying numbers: {pts} points from an expected {xpts}, so some regression may be due.")
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
#  Synthetic data for tests — plausible mid-season values for every section    #
# --------------------------------------------------------------------------- #
def sample_data(live=None):
    """Dummy stats for exercising every section end to end, but real teams/badges/
    squad/news from live data where given so it reflects the actual club."""
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
                      "points": pts, "is_ipswich": c["short"] == ips_short, "badge": c["badge"],
                      "form": (["W", "W", "D", "L", "W"] if i <= 6 else
                               ["L", "D", "L", "W", "D"] if i >= 15 else ["W", "L", "D", "W", "L"])})
    ipr = next((r for r in table if r["is_ipswich"]), table[-1])
    summary = {k: ipr[k] for k in ("played", "won", "drawn", "lost", "gf", "ga", "gd", "points")}

    def _rank_on(key, low_good=False):
        arr = sorted(table, key=lambda r: r[key], reverse=not low_good)
        return next((i for i, r in enumerate(arr, 1) if r["is_ipswich"]), None)
    summary_ranks = {"total": len(table), "points": _rank_on("points"), "won": _rank_on("won"),
                     "lost": _rank_on("lost", low_good=True), "gf": _rank_on("gf"),
                     "ga": _rank_on("ga", low_good=True), "gd": _rank_on("gd")}

    team_scatter = [{"team": r["team"], "short": r["short"], "badge": r["badge"],
                     "xg_pg": round(2.4 - r["rank"] * 0.07, 2), "xga_pg": round(0.7 + r["rank"] * 0.05, 2),
                     "is_ipswich": r["is_ipswich"]} for r in table]
    team_ranks = [{"label": "Points", "value": ipr["points"], "rank": 14, "total": 20, "low_good": False},
                  {"label": "xG per game", "value": 1.22, "rank": 15, "total": 20, "low_good": False},
                  {"label": "xGA per game", "value": 1.55, "rank": 16, "total": 20, "low_good": True},
                  {"label": "Non-penalty xG", "value": 13.4, "rank": 15, "total": 20, "low_good": False},
                  {"label": "Pressing (PPDA)", "value": 11.8, "rank": 8, "total": 20, "low_good": True},
                  {"label": "Goal difference", "value": ipr["gd"], "rank": 14, "total": 20, "low_good": False}]

    league_table = []
    for i, (r, ts) in enumerate(zip(table, team_scatter), 1):
        xg, xga = round(ts["xg_pg"] * r["played"], 1), round(ts["xga_pg"] * r["played"], 1)
        xpts = round(r["points"] * (0.9 + (i % 5) * 0.05), 1)
        league_table.append({
            "team": r["team"], "short": r["short"], "badge": r["badge"],
            "is_ipswich": r["is_ipswich"], "rank": i, "played": r["played"], "points": r["points"],
            "gf": r["gf"], "ga": r["ga"], "gd": r["gd"],
            "xg": xg, "xga": xga, "npxg": round(xg * 0.88, 1),
            "xg_pg": ts["xg_pg"], "xga_pg": ts["xga_pg"],
            "ppda": round(8 + (i % 7), 1), "elo": 1620 - i * 8,
            "xpts": xpts, "xpts_diff": round(r["points"] - xpts, 1)})

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
    upcoming = [f for f in fixtures if not f["finished"]]
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
    # a few non-Ipswich league players so the "any PL player" search has content
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
            "gf": g["gf"], "ga": g["ga"], "result": "W" if g["pts"] == 3 else "D" if g["pts"] == 1 else "L",
            "ht_for": min(g["gf"], 1), "ht_against": min(g["ga"], 1),
            "ht_state": "ahead" if min(g["gf"], 1) > min(g["ga"], 1) else "behind" if min(g["gf"], 1) < min(g["ga"], 1) else "level",
            "shots_for": 10 + (i*3) % 8, "shots_against": 8 + (i*2) % 7,
            "sot_for": 3 + (i*2) % 5, "sot_against": 2 + i % 4,
            "corners_for": 4 + i % 5, "corners_against": 3 + i % 4,
            "fouls_for": 9 + i % 5, "fouls_against": 10 + i % 6,
            "yellows_for": 1 + i % 3, "yellows_against": 2 + i % 2,
            "reds_for": 1 if i % 7 == 0 else 0, "reds_against": 0})

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
        # Role name per slot, defence-to-attack, matching each dummy formation's
        # shape (4-2-3-1 / 4-3-3) so the formation-pitch diagram (which bands
        # players by this text, not by slot index) actually spreads them out.
        ROLES_4231 = [("Goalkeeper", "G"), ("Right Back", "RB"), ("Center Right Defender", "CD-R"),
                      ("Center Left Defender", "CD-L"), ("Left Back", "LB"),
                      ("Defensive Midfielder", "DM"), ("Defensive Midfielder", "DM"),
                      ("Attacking Midfielder Right", "AM-R"), ("Attacking Midfielder", "AM"),
                      ("Attacking Midfielder Left", "AM-L"), ("Forward", "F")]
        ROLES_433 = [("Goalkeeper", "G"), ("Right Back", "RB"), ("Center Right Defender", "CD-R"),
                     ("Center Left Defender", "CD-L"), ("Left Back", "LB"),
                     ("Center Midfielder", "CM"), ("Center Midfielder", "CM"), ("Center Midfielder", "CM"),
                     ("Right Winger", "RW"), ("Forward", "F"), ("Left Winger", "LW")]

        # Plain surnames, not "Opponent N" — a name ending in a digit would
        # make the pitch diagram's surname label (last word of the name)
        # show the jersey number a second time instead of an actual name.
        OPPONENT_SURNAMES = ["Smith", "Jones", "Brown", "Wilson", "Taylor", "Davies",
                              "Evans", "Thomas", "Roberts", "Walker", "Wright"]

        def _starter(j, name, role):
            pos_full, pos = role
            return {"name": name, "jersey": str(j + 1), "pos": pos, "pos_full": pos_full,
                    "sub_on": None, "sub_off": "72'" if j == 0 else None,
                    "cards": [{"kind": "yellow", "minute": "58'"}] if j == 4 else [],
                    "goals": ["20'"] if (j == 0 and gf > 0) else []}
        def _bench(name, jersey, pos, pos_full, sub_on=None):
            return {"name": name, "jersey": jersey, "pos": pos, "pos_full": pos_full,
                    "sub_on": sub_on, "sub_off": None, "cards": [], "goals": []}
        lineups = {
            "for": {"formation": "4-2-3-1",
                    "starters": [_starter(j, sq_names[j % len(sq_names)], ROLES_4231[j]) for j in range(11)],
                    "subs": [_bench(sq_names[0], "20", "M", "Midfielder", sub_on="72'"),
                             _bench("Reserve GK", "13", "G", "Goalkeeper"),
                             _bench("Reserve Defender", "15", "D", "Center Left Defender"),
                             _bench("Reserve Forward", "18", "F", "Forward")]},
            "against": {"formation": "4-3-3",
                        "starters": [_starter(j, "Opponent " + OPPONENT_SURNAMES[j], ROLES_433[j]) for j in range(11)],
                        "subs": [_bench("Opponent Sub", "20", "F", "Forward", sub_on="80'"),
                                 _bench("Opponent Reserve GK", "13", "G", "Goalkeeper"),
                                 _bench("Opponent Reserve Winger", "17", "W", "Left Winger")]}}
        match_pages.append({
            "id": "demo" + str(i + 1), "opponent": r["opponent"], "opponent_short": r["opponent_short"],
            "opponent_badge": r["badge"], "team_badge": ips_badge, "home": r["home"], "date": "2026-10-04",
            "score": r["score"], "gf": gf, "ga": ga, "result": r["result"],
            "xg_for": round(1.4 + gf * 0.3, 2), "xg_against": round(0.8 + ga * 0.3, 2),
            "ht_score": f"{min(gf,1)}-{min(ga,1)}",
            "ht_state": "ahead" if min(gf,1) > min(ga,1) else "behind" if min(gf,1) < min(ga,1) else "level",
            "xpts": round(1.2 + gf * 0.4, 2),
            "deep": 9 + i, "deep_allowed": 6 + i, "ppda": round(9.5 + i, 2), "ppda_allowed": round(11.0 - i, 2),
            "fbd": {"shots_for": 14, "shots_against": 9, "sot_for": 6, "sot_against": 3,
                    "corners_for": 7, "corners_against": 4, "fouls_for": 10, "fouls_against": 12,
                    "yellows_for": 1, "yellows_against": 2, "reds_for": 0, "reds_against": 0},
            "shots_for": sfor, "shots_against": sag, "players_for": pfor, "players_against": pag,
            "goals": goals, "lineups": lineups, "attendance": 28312 + i * 214, "referee": "Sample Referee",
            "team_stats": {"possession_for": 46.5, "possession_against": 53.5,
                           "pass_pct_for": 79.4, "pass_pct_against": 84.1,
                           "tackles_for": 15, "tackles_against": 11,
                           "interceptions_for": 7, "interceptions_against": 9},
            "espn_data_fetched_at": "2026-10-04T18:03:00+00:00",
            "h2h": next_opponent["h2h"] if next_opponent else []})
    mpid = {(mp["opponent_short"], mp["home"]): mp["id"] for mp in match_pages}
    for r in results:
        r["match_id"] = mpid.get((r["opponent_short"], r["home"]))

    # home / away sub-tables (split each club's dummy record) + Elo trend + strength
    def half_table(is_home):
        rows = []
        for r in table:
            p = (r["played"] + (1 if is_home else 0)) // 2
            w = r["won"] // 2 + (1 if is_home and r["won"] % 2 else 0)
            d, l = r["drawn"] // 2, max(0, p - (r["won"] // 2) - (r["drawn"] // 2))
            gf, ga = r["gf"] // 2, r["ga"] // 2
            rows.append({"team": r["team"], "short": r["short"], "badge": r["badge"],
                         "is_ipswich": r["is_ipswich"], "played": p, "won": w, "drawn": d, "lost": l,
                         "gf": gf, "ga": ga, "gd": gf - ga, "points": w * 3 + d})
        rows.sort(key=lambda x: (-x["points"], -x["gd"]))
        for i, x in enumerate(rows, 1):
            x["rank"] = i
        return rows
    home_table, away_table = half_table(True), half_table(False)
    elo_history = [{"date": f"2026-{m:02d}-01", "elo": 1500 + (i - 3) * 8 + (i % 2) * 6}
                   for i, m in enumerate(range(8, 8 + len(by_gameweek) + 1))]
    team_strength = [{"label": lab, "value": v, "pct": pc} for lab, v, pc in [
        ("Attack home", 1180, 35), ("Attack away", 1120, 30), ("Defence home", 1150, 40),
        ("Defence away", 1090, 25), ("Overall home", 1165, 38), ("Overall away", 1105, 28)]]
    survival = {"survive_pct": 71.4, "releg_pct": 28.6, "avg_points": 41, "pts_lo": 33, "pts_hi": 49,
                "avg_position": 15.2, "pos_lo": 11, "pos_hi": 19, "sims": 10000}
    releg_odds = {r["team"]: round(max(0.2, (r["rank"] - 12) * 9 + (r["rank"] - 12)**2), 1)
                  if r["rank"] >= 12 else 0.2 for r in table}

    # top scorers / assists — a handful of real-name dummy rows (rest of the league,
    # plus one Ipswich player mid-table) so this section has something to show.
    ips_leader = squad[0] if squad else {"full_name": "Ipswich Striker", "starts": 10,
                                         "minutes": 900, "goals": 6, "assists": 2, "xg": 5.4, "xa": 1.8}
    ips_leader_row = {"player": ips_leader["full_name"], "team": "Ipswich Town", "team_short": ips_short,
                      "badge": ips_badge, "games": ips_leader["starts"], "minutes": ips_leader["minutes"],
                      "goals": ips_leader["goals"], "assists": ips_leader["assists"],
                      "xg": ips_leader["xg"], "xa": ips_leader["xa"], "is_ipswich": True}
    top_scorers = [
        {"player": "Erling Haaland", "team": "Manchester City", "team_short": "MCI", "badge": None,
         "games": 14, "minutes": 1250, "goals": 17, "assists": 3, "xg": 15.2, "xa": 2.8, "is_ipswich": False},
        {"player": "Mohamed Salah", "team": "Liverpool", "team_short": "LIV", "badge": None,
         "games": 14, "minutes": 1260, "goals": 13, "assists": 9, "xg": 11.4, "xa": 7.9, "is_ipswich": False},
        {"player": "Cole Palmer", "team": "Chelsea", "team_short": "CHE", "badge": None,
         "games": 13, "minutes": 1150, "goals": 10, "assists": 6, "xg": 9.1, "xa": 5.3, "is_ipswich": False},
        {**ips_leader_row},
    ]
    top_assists = [
        {"player": "Bruno Fernandes", "team": "Manchester United", "team_short": "MUN", "badge": None,
         "games": 14, "minutes": 1240, "goals": 6, "assists": 11, "xg": 5.0, "xa": 9.6, "is_ipswich": False},
        {"player": "Mohamed Salah", "team": "Liverpool", "team_short": "LIV", "badge": None,
         "games": 14, "minutes": 1260, "goals": 13, "assists": 9, "xg": 11.4, "xa": 7.9, "is_ipswich": False},
        {"player": "Cole Palmer", "team": "Chelsea", "team_short": "CHE", "badge": None,
         "games": 13, "minutes": 1150, "goals": 10, "assists": 6, "xg": 9.1, "xa": 5.3, "is_ipswich": False},
        {**ips_leader_row},
    ]
    for i, r in enumerate(top_scorers, 1): r["rank"] = i
    for i, r in enumerate(top_assists, 1): r["rank"] = i

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": live.get("season", "2026/27"),
        "team": {"id": 8, "name": team.get("name", "Ipswich"), "short_name": ips_short, "badge": ips_badge},
        "current_event": 12, "next_event": 13,
        "next_fixture": next_fixture, "next_opponent": next_opponent,
        "team_news": [
            {"player": "Wes Burns", "news": "Hamstring injury - 50% chance of playing", "tag": "Injured", "sev": "doubt"},
            {"player": "Sam Morsy", "news": "Suspended - 1 match ban", "tag": "Suspended", "sev": "out"}],
        "position": ipr["rank"], "summary": summary, "summary_ranks": summary_ranks, "table": table,
        "team_scatter": team_scatter, "team_ranks": team_ranks, "league_table": league_table,
        "top_scorers": top_scorers, "top_assists": top_assists,
        "player_profiles": player_profiles,
        "by_gameweek": by_gameweek, "understat_matches": understat_matches, "shot_maps": shot_maps,
        "understat_players": understat_players, "upcoming": upcoming, "fixtures": fixtures,
        "understat_history": understat_history, "match_stats": match_stats,
        "elo_history": elo_history, "home_table": home_table, "away_table": away_table,
        "team_strength": team_strength, "survival": survival, "releg_odds": releg_odds,
        "results": results, "squad": squad, "news": live.get("news") or [],
        "match_pages": match_pages,
        "health": {"preseason": False, "sources": {}, "missing": []},
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
                            "date": m["date"], "match_id": m["slug"], "minutes": pl["minutes"],
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


def projected_table(data):
    """Every club's projected final points, from current points-per-game over 38 games."""
    tbl = data.get("table") or []
    rows = []
    for r in tbl:
        played, pts = r.get("played", 0), r.get("points", 0)
        ppg = pts / played if played else 0
        proj = round(pts + ppg * (38 - played)) if played else None
        rows.append({**r, "proj": proj, "ppg": round(ppg, 2)})
    if any(x["proj"] is not None for x in rows):
        rows.sort(key=lambda x: (-(x["proj"] or 0), -(x.get("gd") or 0), x.get("team", "")))
        for i, x in enumerate(rows, 1):
            x["proj_rank"] = i
    return rows


def _make_env():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                      autoescape=select_autoescape(["html"]))
    env.filters["kickoff"] = fmt_kickoff
    env.filters["updated"] = fmt_updated
    env.filters["ordinal"] = lambda n: (
        f"{int(n)}{'th' if 11 <= int(n) % 100 <= 13 else {1:'st',2:'nd',3:'rd'}.get(int(n) % 10, 'th')}"
        if str(n).lstrip('-').isdigit() else n)
    return env


def form_guide(data, n=6):
    """Last n results with rolling points/PPG, a momentum trend, and an 'expected
    form' read: performance-based expected points (xPts), xG for/against, and
    how tough the run of opponents was."""
    results = data.get("results") or []          # most recent first
    recent = results[:n]
    if not recent:
        return None
    pts_of = lambda r: 3 if r["result"] == "W" else 1 if r["result"] == "D" else 0
    pts = sum(pts_of(r) for r in recent)
    ppg = round(pts / len(recent), 2)
    k = len(recent)

    # momentum: newer half's PPG vs older half's
    half = max(1, k // 2)
    newer, older = recent[:half], recent[half:half * 2] or recent[half:]
    np_ = sum(pts_of(r) for r in newer) / len(newer)
    op = sum(pts_of(r) for r in older) / len(older) if older else np_
    trend = "up" if np_ > op + 0.25 else "down" if np_ < op - 0.25 else "flat"

    # performance-based expected points + xG (Understat, last k finished matches)
    uh = (data.get("understat_history") or [])[-k:]
    xpts = round(sum(h.get("xpts", 0) for h in uh), 1) if uh else None
    xgf = round(sum(h.get("xg", 0) for h in uh), 1) if uh else None
    xga = round(sum(h.get("xga", 0) for h in uh), 1) if uh else None

    # over/under-performance verdict (vs deserved expectation)
    ref = xpts
    verdict = None
    if ref is not None:
        d = pts - ref
        verdict = "over" if d >= 1.5 else "under" if d <= -1.5 else "par"

    # run difficulty: average current league position of the opponents faced
    rank_by = {_pnorm(t["team"]): t["rank"] for t in (data.get("table") or []) if t.get("rank")}
    opp_ranks = [rank_by.get(_pnorm(r.get("opponent", ""))) for r in recent]
    opp_ranks = [x for x in opp_ranks if x]
    opp_avg_rank = round(sum(opp_ranks) / len(opp_ranks)) if opp_ranks else None
    run_label = None
    if opp_avg_rank:
        run_label = "a tough run" if opp_avg_rank <= 8 else "a kind run" if opp_avg_rank >= 13 else "an average run"

    # per-match expectation breakdown, joined from the same match-report data
    # (match_pages) that already carries Understat xG/xPts per match
    mp_by_id = {mp.get("slug"): mp for mp in (data.get("match_pages") or [])}
    matches = []
    for r in reversed(recent):          # oldest first (reads left→right)
        mp = mp_by_id.get(r.get("match_id")) or {}
        matches.append({
            "result": r["result"], "opponent": r.get("opponent", ""),
            "opponent_short": r.get("opponent_short", ""), "home": r.get("home"),
            "score": r.get("score", ""), "match_id": r.get("match_id"),
            "event": r.get("event"), "pts": pts_of(r), "date": mp.get("date"),
            "xg_for": mp.get("xg_for"), "xg_against": mp.get("xg_against"),
            "xpts": mp.get("xpts"),
        })
    return {"matches": matches, "pts": pts, "ppg": ppg, "trend": trend, "count": k,
            "xpts": xpts, "xgf": xgf, "xga": xga, "verdict": verdict,
            "opp_avg_rank": opp_avg_rank, "run_label": run_label}


def rival_tracker(data):
    """Clubs immediately around Ipswich, with form and relegation odds."""
    table = data.get("table") or []
    odds = data.get("releg_odds") or {}
    ips = next((r for r in table if r.get("is_ipswich")), None)
    if not ips:
        return []
    lo, hi = ips["rank"] - 3, ips["rank"] + 3
    out = []
    for r in table:
        if lo <= r["rank"] <= hi:
            key = _pnorm(r["team"])
            releg = next((v for k, v in odds.items() if _pnorm(k) == key
                          or _pnorm(k).endswith(key) or key.endswith(_pnorm(k))), None)
            out.append({**r, "releg": releg})
    return out


def form_guide_women(data, n=6):
    """Simplified form_guide(): results only, no xG/xPts/odds — those sources
    don't exist for free for women's football (see templates/women.html.j2)."""
    results = data.get("results") or []
    recent = results[:n]
    if not recent:
        return None
    pts_of = lambda r: 3 if r["result"] == "W" else 1 if r["result"] == "D" else 0
    pts = sum(pts_of(r) for r in recent)
    ppg = round(pts / len(recent), 2)
    k = len(recent)
    half = max(1, k // 2)
    newer, older = recent[:half], recent[half:half * 2] or recent[half:]
    np_ = sum(pts_of(r) for r in newer) / len(newer)
    op = sum(pts_of(r) for r in older) / len(older) if older else np_
    trend = "up" if np_ > op + 0.25 else "down" if np_ < op - 0.25 else "flat"
    matches = [{"result": r["result"], "opponent": r.get("opponent", ""),
                "opponent_short": r.get("opponent_short", ""), "home": r.get("home"),
                "score": r.get("score", ""), "event": r.get("event"), "pts": pts_of(r)}
               for r in reversed(recent)]
    return {"matches": matches, "pts": pts, "ppg": ppg, "trend": trend, "count": k}


def render_women_site(template, data, outdir):
    """Renders into outdir (e.g. site/women/), sharing style.css/fonts/share.js
    from outdir's parent rather than duplicating them — main() copies those
    into SITE before calling this."""
    outdir.mkdir(parents=True, exist_ok=True)
    if ASSETS.exists() and not (outdir.parent / "style.css").exists():
        shutil.copytree(ASSETS, outdir.parent, dirs_exist_ok=True)
    league_name = data.get("league_name", "Women's Super League 2")
    fguide = form_guide_women(data)

    for page_id, filename, _label in WOMEN_PAGES:
        html = template.render(page=page_id, current=page_id, pages=WOMEN_PAGES,
                               css_href="../style.css", form_guide=fguide,
                               og_title=f"Ipswich Town Women · {filename.replace('.html', '').title()}",
                               og_description=f"Ipswich Town Women {league_name} stats.",
                               canonical=f"{SITE_URL}/women/{filename}", **data)
        (outdir / filename).write_text(html)
    (outdir / "data.json").write_text(json.dumps(data))


def sample_data_women():
    """Realistic fake data for the women's-team site — no live ingest source
    exists yet (see ingest_women.py), so this is what's rendered for now."""
    opponents = ["Charlton Athletic", "Southampton", "Birmingham City", "Sunderland",
                 "Sheffield United", "Blackburn Rovers", "Newcastle United", "Watford",
                 "Reading", "London City Lionesses", "Bristol City"]
    results, badges = [], {}
    random_results = ["W", "W", "D", "L", "W", "D", "L", "W"]
    for i, (opp, res) in enumerate(zip(opponents[:8], random_results)):
        home = i % 2 == 0
        gf, ga = {"W": (2, 1), "D": (1, 1), "L": (0, 2)}[res]
        results.append({"event": i + 1, "opponent": opp, "opponent_short": opp[:3].upper(),
                        "home": home, "score": f"{gf}-{ga}", "result": res,
                        "date": f"2026-{9 + i // 4:02d}-{(i % 4) * 7 + 6:02d}"})
    results.reverse()  # most recent first, matching itfc.json's convention
    won = sum(r["result"] == "W" for r in results)
    drawn = sum(r["result"] == "D" for r in results)
    lost = sum(r["result"] == "L" for r in results)
    gf = sum(int(r["score"].split("-")[0]) for r in results)
    ga = sum(int(r["score"].split("-")[1]) for r in results)
    squad_names = [("Bethany Rutter", "GKP"), ("Freya Cook", "DEF"), ("Amelia Sharp", "DEF"),
                   ("Chloe Wardle", "DEF"), ("Isla Barnes", "MID"), ("Millie Radford", "MID"),
                   ("Grace Oduya", "MID"), ("Poppy Fenn", "FWD"), ("Ruby Halston", "FWD"),
                   ("Neve Colbeck", "DEF"), ("Tilly Vance", "MID")]
    squad = [{"name": n.split()[-1], "full_name": n, "pos": p,
              "apps": 8 - i % 3, "goals": max(0, 5 - i) if p == "FWD" else max(0, 2 - i % 3),
              "assists": max(0, 3 - i % 4)} for i, (n, p) in enumerate(squad_names)]
    table = []
    for i, opp in enumerate(opponents):
        is_ips = opp == "Ipswich Town"
        table.append({"rank": i + 1, "team": opp, "badge": None, "played": 8,
                      "won": max(0, 6 - i), "drawn": 1, "lost": min(7, i),
                      "gf": max(2, 20 - i * 2), "ga": 5 + i, "gd": max(2, 20 - i * 2) - (5 + i),
                      "points": max(0, 6 - i) * 3 + 1, "form": ["W", "D", "L", "W", "W"],
                      "is_ipswich": is_ips})
    table.insert(8, {"rank": 9, "team": "Ipswich Town", "badge": None, "played": 8,
                     "won": won, "drawn": drawn, "lost": lost, "gf": gf, "ga": ga, "gd": gf - ga,
                     "points": won * 3 + drawn, "form": [r["result"] for r in results[:5]],
                     "is_ipswich": True})
    for i, row in enumerate(table):
        row["rank"] = i + 1
    return {
        "season": "2026/27", "league_name": "Barclays Women's Super League 2",
        "team": {"short_name": "Ipswich", "badge": None}, "position": 9,
        "summary": {"played": 8, "won": won, "drawn": drawn, "lost": lost,
                    "gf": gf, "ga": ga, "gd": gf - ga, "points": won * 3 + drawn},
        "summary_text": f"Ipswich Town Women sit 9th in the Barclays Women's Super League 2 "
                        f"after 8 matches, with {won} wins, {drawn} draws and {lost} defeats.",
        "next_fixture": {"opponent": "Southampton", "opponent_short": "SOU", "home": True,
                         "kickoff": "2026-09-27T14:00:00Z", "event": 9, "badge": None},
        "results": results,
        "upcoming": [{"event": 9, "opponent": "Southampton", "home": True,
                     "kickoff": "2026-09-27T14:00:00Z"},
                    {"event": 10, "opponent": "Birmingham City", "home": False,
                     "kickoff": "2026-10-04T14:00:00Z"}],
        "table": table,
        "squad": squad,
        "news": [{"source": "TWTD", "date_display": "2 days ago",
                  "title": "Ipswich Women fall short in narrow defeat at Charlton",
                  "link": "https://www.twtd.co.uk/", "summary": None, "image": None},
                 {"source": "ITFC", "date_display": "5 days ago",
                  "title": "Matchday programme: Ipswich Town Women vs Southampton",
                  "link": "https://www.itfc.co.uk/itfc-women/", "summary": None, "image": None}],
        "health": {"missing": []},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_site(template, match_template, player_template, data):
    outdir = SITE
    (outdir / "data").mkdir(parents=True, exist_ok=True)
    if ASSETS.exists():
        shutil.copytree(ASSETS, outdir, dirs_exist_ok=True)   # style.css, fonts/, share.js per site root

    # readable match-page URLs (date + opponent + venue) instead of Understat's
    # opaque numeric id — mp["id"] itself is left untouched since match_report_links()
    # still needs it to build the real understat.com link.
    used_slugs, slug_by_id = {}, {}
    for mp in data.get("match_pages") or []:
        base = f"{mp.get('date', '')}-{_slugify(mp.get('opponent', ''))}-{'h' if mp.get('home') else 'a'}"
        used_slugs[base] = used_slugs.get(base, 0) + 1
        mp["slug"] = base if used_slugs[base] == 1 else f"{base}-{used_slugs[base]}"
        slug_by_id[mp.get("id")] = mp["slug"]
    for r in data.get("results") or []:
        if r.get("match_id") in slug_by_id:
            r["match_id"] = slug_by_id[r["match_id"]]

    for mp in data.get("match_pages") or []:
        mp["reports"] = match_report_links(mp)
        lineups = mp.get("lineups") or {}
        for_starters = (lineups.get("for") or {}).get("starters")
        if for_starters:
            lineups["for"]["starters"] = assign_pitch_positions(for_starters, gk_y=96, fwd_y=54)
        against_starters = (lineups.get("against") or {}).get("starters")
        if against_starters:
            lineups["against"]["starters"] = assign_pitch_positions(against_starters, gk_y=4, fwd_y=46)
    player_pages = build_player_pages(data)     # stamps slug on each squad entry
    data_json = json.dumps(data).replace("<", "\\u003c")
    summary_text = season_summary(data)
    predicted = projected_table(data)
    rivals = rival_tracker(data)
    fguide = form_guide(data)
    season = data.get("season", "2026/27")
    team = data.get("team", {})
    position = data.get("position")
    generated_at = data.get("generated_at", "")

    _og_image(str(outdir / "og.png"), "Ipswich Town Stats",
              f"Premier League {season} · xG, form & survival odds")
    og_default = "og.png"

    for page_id, filename, _label in PAGES:
        og_title, og_desc = OG.get(page_id, OG["overview"])
        html = template.render(data_json=data_json, page=page_id, current=page_id,
                               pages=PAGES, nav_prefix="", css_href="style.css",
                               summary_text=summary_text, predicted=predicted, rivals=rivals,
                               form_guide=fguide,
                               og_title=og_title, og_description=og_desc, og_image=og_default,
                               canonical=f"{SITE_URL}/{filename}", **data)
        (outdir / filename).write_text(html)
    (outdir / "data" / "itfc.json").write_text(json.dumps(data))

    # a full detail page per finished match (+ its own share card)
    matches = data.get("match_pages", [])
    if matches:
        (outdir / "match").mkdir(exist_ok=True)
        for mp in matches:
            score = f"Ipswich {mp['gf']}\u2013{mp['ga']} {mp['opponent']}"
            og_img = f"match/{mp['slug']}.png"
            xg = (f" \u00b7 xG {mp['xg_for']:.1f}\u2013{mp['xg_against']:.1f}"
                  if mp.get("xg_for") is not None else "")
            _og_image(str(outdir / "match" / f"{mp['slug']}.png"), score,
                      f"Premier League {season}{xg}")
            match_json = json.dumps({"opponent": mp.get("opponent", ""),
                                     "shots_for": mp.get("shots_for", []),
                                     "shots_against": mp.get("shots_against", [])}).replace("<", "\\u003c")
            html = match_template.render(m=mp, season=season,
                                         generated_at=generated_at, match_json=match_json,
                                         pages=PAGES, nav_prefix="../", current="matches",
                                         css_href="../style.css", team=team, position=position,
                                         og_title=score + " · Match report",
                                         og_description=f"Full report: xG, shots, player ratings and the story of Ipswich {mp['gf']}-{mp['ga']} {mp['opponent']}.",
                                         og_image="../" + og_img, canonical=f"{SITE_URL}/match/{mp['slug']}.html")
            (outdir / "match" / f"{mp['slug']}.html").write_text(html)

    # a page per squad player
    if player_pages:
        (outdir / "player").mkdir(exist_ok=True)
        for pp in player_pages:
            player_json = json.dumps({"shots": pp["shots"],
                                      "log": list(reversed(pp["log"]))}).replace("<", "\\u003c")
            html = player_template.render(p=pp, season=season, player_json=player_json,
                                          pages=PAGES, nav_prefix="../", current="squad",
                                          css_href="../style.css", team=team, position=position,
                                          generated_at=generated_at,
                                          og_title=f"{pp['name']} · Ipswich Town",
                                          og_description=f"{pp['name']}'s Ipswich Town season: stats, percentile profile, match log and shot map.",
                                          og_image="../og.png", canonical=f"{SITE_URL}/player/{pp['slug']}.html")
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
    render_site(template, match_template, player_template, real)
    (SITE / ".nojekyll").write_text("")
    n = len(real.get("match_pages", []))
    print(f"Built {len(PAGES)} pages + {n} match pages + {len(real.get('squad', []))} player pages.")

    # Women's team: free-sources-only trimmed site. No ingest_women.py output yet,
    # so this renders sample data until that lands — see WOMEN_PAGES's comment.
    women_template = env.get_template("women.html.j2")
    women_data = json.loads(DATA_WOMEN.read_text()) if DATA_WOMEN.exists() else sample_data_women()
    render_women_site(women_template, women_data, SITE / "women")
    print(f"Built {len(WOMEN_PAGES)} women's pages"
          f"{' (sample data — no live source yet)' if not DATA_WOMEN.exists() else ''}.")


if __name__ == "__main__":
    main()
