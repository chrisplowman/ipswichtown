"""
Pull Ipswich Town data from several free/open football sources and write a clean
data/itfc.json that build.py renders into the static page.

Sources (all free; only football-data-style keys avoided — none needed here):
  FPL              https://fantasy.premierleague.com/api/...   squad, fixtures, difficulty
  Understat        https://understat.com/team|match/...         shot-level xG, match xG, player npxG
  ESPN (hidden)    https://site.api.espn.com/.../eng.1/standings  league table  (keyless)
  TheSportsDB      https://www.thesportsdb.com/api/v1/json/3/...   club badges   (public test key)

Each non-FPL source is wrapped so a failure just drops that section — the page
still builds from whatever succeeded.

Run:  python ingest.py
"""

import codecs
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

FPL = "https://fantasy.premierleague.com/api"
UNDERSTAT_SEASON = "2026"          # Understat labels 2026/27 as "2026"
ESPN_SEASON = "2026"
UNDERSTAT_TEAM_SLUG = "Ipswich_Town"
TSDB_PL_LEAGUE_ID = "4328"         # English Premier League on TheSportsDB
AF_BASE = "https://v3.football.api-sports.io"   # API-Football (api-sports.io direct)
AF_LEAGUE = 39                     # Premier League on API-Football
AF_SEASON = 2026                   # 2026/27
SHOT_MAP_MATCHES = 5               # how many recent matches to keep shot maps for
TEAM_NAME_MATCH = "ipswich"
OUT = Path("data/itfc.json")
TIMEOUT = 30
UA = {"User-Agent": "Mozilla/5.0 (compatible; itfc-stats/2.0; +github pages reference page)"}


def get_json(url, base=None):
    r = requests.get((f"{base}/{url}" if base else url), headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_text(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def to_float(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- #
#  FPL — squad, fixtures, results, per-gameweek points/goals                   #
# --------------------------------------------------------------------------- #
def fetch_fpl():
    boot = get_json("bootstrap-static/", FPL)
    fixtures = get_json("fixtures/", FPL)

    teams = {t["id"]: t for t in boot["teams"]}
    positions = {p["id"]: p["singular_name_short"] for p in boot["element_types"]}
    player_team = {p["id"]: p["team"] for p in boot["elements"]}

    ipswich = next((t for t in boot["teams"] if TEAM_NAME_MATCH in t["name"].lower()), None)
    if not ipswich:
        sys.exit("Ipswich Town not found in current FPL data — are they in the Premier League?")
    tid = ipswich["id"]

    current = next((e["id"] for e in boot["events"] if e["is_current"]), None)
    nxt = next((e["id"] for e in boot["events"] if e["is_next"]), None)

    upcoming, results, finished_meta = [], [], []
    won = drawn = lost = gf = ga = 0

    club = [f for f in fixtures if tid in (f["team_h"], f["team_a"])]
    club.sort(key=lambda f: (f["event"] or 999, f["kickoff_time"] or ""))
    for f in club:
        home = f["team_h"] == tid
        opp = teams[f["team_a"] if home else f["team_h"]]
        difficulty = f["team_h_difficulty"] if home else f["team_a_difficulty"]
        if f["finished"] and f["team_h_score"] is not None:
            our = f["team_h_score"] if home else f["team_a_score"]
            their = f["team_a_score"] if home else f["team_h_score"]
            gf += our; ga += their
            res = "W" if our > their else "L" if our < their else "D"
            won += res == "W"; drawn += res == "D"; lost += res == "L"
            results.append({"event": f["event"], "opponent": opp["name"],
                            "opponent_short": opp["short_name"], "home": home,
                            "score": f"{our}-{their}", "result": res})
            finished_meta.append({"gw": f["event"], "gf": our, "ga": their,
                                  "pts": 3 if res == "W" else 1 if res == "D" else 0,
                                  "opp_id": opp["id"]})
        else:
            upcoming.append({"event": f["event"], "opponent": opp["name"],
                             "opponent_short": opp["short_name"], "home": home,
                             "kickoff": f["kickoff_time"], "difficulty": difficulty})

    played = won + drawn + lost
    summary = {"played": played, "won": won, "drawn": drawn, "lost": lost,
               "gf": gf, "ga": ga, "gd": gf - ga, "points": won * 3 + drawn}

    # per-gameweek series (points/goals from fixtures; xG from live feed)
    finished_meta.sort(key=lambda m: m["gw"])
    by_gameweek, cum = [], 0
    for m in finished_meta:
        cum += m["pts"]
        rec = {"gw": m["gw"], "gf": m["gf"], "ga": m["ga"], "pts": m["pts"],
               "cum_points": cum, "team_xg": None, "team_xga": None}
        try:
            live = get_json(f"event/{m['gw']}/live/", FPL)
            xf = xa = 0.0
            for el in live.get("elements", []):
                exg = to_float(el.get("stats", {}).get("expected_goals", 0))
                t = player_team.get(el["id"])
                if t == tid: xf += exg
                elif t == m["opp_id"]: xa += exg
            rec["team_xg"] = round(xf, 2); rec["team_xga"] = round(xa, 2)
        except requests.RequestException:
            pass
        by_gameweek.append(rec)

    squad = []
    for p in boot["elements"]:
        if p["team"] != tid:
            continue
        squad.append({"name": p["web_name"],
                      "full_name": f"{p['first_name']} {p['second_name']}".strip(),
                      "pos": positions.get(p["element_type"], "?"), "pos_id": p["element_type"],
                      "price": round(p["now_cost"] / 10, 1), "points": p["total_points"],
                      "form": to_float(p["form"]), "minutes": p["minutes"], "starts": p.get("starts", 0),
                      "goals": p["goals_scored"], "assists": p["assists"],
                      "xg": to_float(p["expected_goals"]), "xa": to_float(p["expected_assists"]),
                      "xgi": to_float(p["expected_goal_involvements"]),
                      "clean_sheets": p["clean_sheets"], "selected": to_float(p["selected_by_percent"])})
    squad.sort(key=lambda x: (-x["points"], -x["minutes"]))

    return {"teams": teams, "ipswich": ipswich, "tid": tid,
            "current": current, "next": nxt, "summary": summary,
            "by_gameweek": by_gameweek, "upcoming": upcoming, "results": results, "squad": squad}


# --------------------------------------------------------------------------- #
#  ESPN — league table (keyless)                                              #
# --------------------------------------------------------------------------- #
def _stat(stats, name, default=0):
    for s in stats:
        if s.get("name") == name:
            v = s.get("value")
            return v if v is not None else default
    return default


def fetch_table():
    url = (f"https://site.api.espn.com/apis/v2/sports/soccer/eng.1/standings?season={ESPN_SEASON}")
    j = get_json(url)
    entries = []
    def collect(node):
        st = node.get("standings")
        if isinstance(st, dict) and st.get("entries"):
            entries.extend(st["entries"])
    for child in j.get("children", []):
        collect(child)
    collect(j)

    rows = []
    for e in entries:
        team = e.get("team", {})
        s = e.get("stats", [])
        gf = int(_stat(s, "pointsFor")); against = int(_stat(s, "pointsAgainst"))
        logo = (team.get("logos") or [{}])[0].get("href")
        rows.append({"team": team.get("displayName", "?"),
                     "short": team.get("abbreviation") or team.get("shortDisplayName", ""),
                     "espn_logo": logo,
                     "played": int(_stat(s, "gamesPlayed")), "won": int(_stat(s, "wins")),
                     "drawn": int(_stat(s, "ties")), "lost": int(_stat(s, "losses")),
                     "gf": gf, "ga": against, "gd": gf - against,
                     "points": int(_stat(s, "points"))})
    if not rows:
        return None, None
    rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["team"]))
    position = None
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["is_ipswich"] = TEAM_NAME_MATCH in r["team"].lower()
        if r["is_ipswich"]:
            position = i
    return rows, position


# --------------------------------------------------------------------------- #
#  TheSportsDB — club badges (public test key "3")                            #
# --------------------------------------------------------------------------- #
def _norm(name):
    n = name.lower()
    for junk in [" fc", " afc", "afc ", "'", ".", "&", "-"]:
        n = n.replace(junk, "")
    return re.sub(r"\s+", "", n)

ALIASES = {  # bridge FPL/ESPN naming to TheSportsDB where a plain match fails
    "spurs": "tottenham", "wolves": "wolverhampton", "nottmforest": "nottingham",
    "manutd": "manchesterunited", "mancity": "manchestercity",
    "newcastleunited": "newcastle", "brightonhovealbion": "brighton",
    "westhamunited": "westham", "leedsunited": "leeds",
}

def fetch_badges(fpl_teams):
    url = f"https://www.thesportsdb.com/api/v1/json/3/lookup_all_teams.php?id={TSDB_PL_LEAGUE_ID}"
    j = get_json(url)
    by_norm = {}
    for t in (j.get("teams") or []):
        badge = t.get("strBadge") or t.get("strTeamBadge")
        if badge:
            by_norm[_norm(t.get("strTeam", ""))] = badge

    def lookup(name):
        k = _norm(name)
        if k in by_norm: return by_norm[k]
        if k in ALIASES and ALIASES[k] in by_norm: return by_norm[ALIASES[k]]
        for nk, url_ in by_norm.items():          # contains fallback
            if len(k) > 3 and (k in nk or nk in k):
                return url_
        return None

    return {t["short_name"]: lookup(t["name"]) for t in fpl_teams.values()}


# --------------------------------------------------------------------------- #
#  Understat — match xG, shot maps, player npxG                               #
# --------------------------------------------------------------------------- #
def _us_json(html, var):
    m = re.search(var + r"\s*=\s*JSON\.parse\('(.*?)'\)", html, re.S)
    if not m:
        return None
    raw = m.group(1)
    try:
        decoded = codecs.escape_decode(raw.encode())[0].decode("utf-8")
    except Exception:
        decoded = raw.encode("utf8").decode("unicode_escape")
    return json.loads(decoded)


def fetch_understat():
    team_html = get_text(f"https://understat.com/team/{UNDERSTAT_TEAM_SLUG}/{UNDERSTAT_SEASON}")
    dates = _us_json(team_html, "datesData") or []
    players_raw = _us_json(team_html, "playersData") or []

    matches, finished_ids = [], []
    for d in dates:
        h_is_ips = TEAM_NAME_MATCH in d["h"]["title"].lower()
        opp = d["a"]["title"] if h_is_ips else d["h"]["title"]
        us = "h" if h_is_ips else "a"; them = "a" if h_is_ips else "h"
        rec = {"match_id": d["id"], "opponent": opp, "home": h_is_ips,
               "date": d.get("datetime", "")[:10]}
        if d.get("isResult"):
            rec.update({"gf": int(d["goals"][us]), "ga": int(d["goals"][them]),
                        "xg_for": to_float(d["xG"][us]), "xg_against": to_float(d["xG"][them])})
            finished_ids.append((d["id"], opp, h_is_ips, rec["date"],
                                 f"{rec['gf']}-{rec['ga']}", us))
        matches.append(rec)
    finished_matches = [m for m in matches if "gf" in m]

    # shot maps for the most recent finished matches
    shot_maps = []
    for mid, opp, home, date, score, side in list(reversed(finished_ids))[:SHOT_MAP_MATCHES]:
        try:
            mh = get_text(f"https://understat.com/match/{mid}")
            shots = _us_json(mh, "shotsData") or {}
            ours = shots.get(side, [])
            shot_maps.append({"match_id": mid, "opponent": opp, "home": home,
                              "date": date, "score": score,
                              "shots": [{"x": to_float(s["X"]), "y": to_float(s["Y"]),
                                         "xg": to_float(s["xG"]), "result": s["result"],
                                         "player": s["player"], "minute": int(s["minute"])}
                                        for s in ours]})
        except requests.RequestException:
            continue

    players = []
    for p in players_raw:
        if int(p.get("time", 0)) <= 0:
            continue
        players.append({"name": p["player_name"], "games": int(p["games"]),
                        "minutes": int(p["time"]), "goals": int(p["goals"]),
                        "assists": int(p["assists"]), "shots": int(p["shots"]),
                        "xg": to_float(p["xG"]), "xa": to_float(p["xA"]),
                        "npg": int(p.get("npg", p["goals"])), "npxg": to_float(p.get("npxG", p["xG"])),
                        "xgchain": to_float(p.get("xGChain", 0)), "xgbuildup": to_float(p.get("xGBuildup", 0))})
    players.sort(key=lambda x: -x["npxg"])

    return {"matches": finished_matches, "shot_maps": shot_maps, "players": players}


# --------------------------------------------------------------------------- #
#  Understat LEAGUE page — every team + every player, in one request           #
# --------------------------------------------------------------------------- #
def simplify_pos(p):
    p = (p or "").upper()
    if p.startswith("G"): return "GKP"
    if p.startswith("D"): return "DEF"
    if p.startswith("F") or p.startswith("S"): return "FWD"
    return "MID"


def fetch_understat_league():
    html = get_text(f"https://understat.com/league/EPL/{UNDERSTAT_SEASON}")
    teams_raw = _us_json(html, "teamsData") or {}
    players_raw = _us_json(html, "playersData") or []

    league_teams = {}
    for t in teams_raw.values():
        hist = t.get("history", [])
        g = len(hist) or 1
        att = sum(to_float((h.get("ppda") or {}).get("att", 0)) for h in hist)
        dfn = sum(to_float((h.get("ppda") or {}).get("def", 0)) for h in hist)
        agg = {"title": t["title"], "games": len(hist),
               "xg": round(sum(to_float(h["xG"]) for h in hist), 2),
               "xga": round(sum(to_float(h["xGA"]) for h in hist), 2),
               "npxg": round(sum(to_float(h.get("npxG", 0)) for h in hist), 2),
               "scored": sum(int(h["scored"]) for h in hist),
               "conceded": sum(int(h["missed"]) for h in hist),
               "ppda": round(att / dfn, 2) if dfn else None,
               "xg_pg": round(sum(to_float(h["xG"]) for h in hist) / g, 2),
               "xga_pg": round(sum(to_float(h["xGA"]) for h in hist) / g, 2),
               "form": [h.get("result", "").upper()[:1] for h in hist[-5:]
                        if h.get("result", "").upper()[:1] in ("W", "D", "L")]}
        league_teams[t["title"]] = agg
    return league_teams, players_raw


# --------------------------------------------------------------------------- #
#  API-Football — team news, head-to-head, win probability (needs a free key)  #
#  Set the API_FOOTBALL_KEY env var (a GitHub Actions secret). Without it this  #
#  source is simply skipped and the page builds from everything else.           #
# --------------------------------------------------------------------------- #
AF_BASE = "https://v3.football.api-sports.io"
AF_LEAGUE = 39            # Premier League on API-Football
AF_SEASON = "2026"        # 2026/27


def af_get(path, params):
    key = os.environ.get("API_FOOTBALL_KEY")
    if not key:
        raise RuntimeError("API_FOOTBALL_KEY not set")
    r = requests.get(f"{AF_BASE}/{path}", params=params,
                     headers={"x-apisports-key": key, **UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("response", [])


def _af_pct(s):
    try:
        return int(str(s).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def fetch_api_football():
    out = {"team_news": [], "h2h": [], "h2h_summary": None, "win_prob": None}

    teams = af_get("teams", {"league": AF_LEAGUE, "season": AF_SEASON})
    ips = next((t for t in teams if TEAM_NAME_MATCH in t["team"]["name"].lower()), None)
    if not ips:
        raise RuntimeError("Ipswich not found in API-Football PL teams")
    ips_id = ips["team"]["id"]

    nxt = af_get("fixtures", {"team": ips_id, "next": 1})
    if not nxt:
        return out
    fx = nxt[0]
    fid = fx["fixture"]["id"]
    ips_home = fx["teams"]["home"]["id"] == ips_id
    opp_id = (fx["teams"]["away"] if ips_home else fx["teams"]["home"])["id"]

    # team news: prefer injuries for the exact next fixture, else recent season ones
    inj = []
    try:
        inj = [i for i in af_get("injuries", {"fixture": fid}) if i["team"]["id"] == ips_id]
        if not inj:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()
            latest = {}
            for i in af_get("injuries", {"team": ips_id, "season": AF_SEASON}):
                nm = i["player"]["name"]
                d = (i.get("fixture") or {}).get("date", "")
                if nm not in latest or d > (latest[nm].get("fixture") or {}).get("date", ""):
                    latest[nm] = i
            inj = [i for i in latest.values()
                   if (i.get("fixture") or {}).get("date", "") >= cutoff]
    except requests.RequestException:
        pass
    seen = set()
    for i in inj:
        nm = i["player"]["name"]
        if nm in seen:
            continue
        seen.add(nm)
        out["team_news"].append({"player": nm,
                                 "type": i["player"].get("type") or "Out",
                                 "reason": i["player"].get("reason") or ""})
    out["team_news"] = out["team_news"][:12]

    # head-to-head, last 5 meetings
    try:
        w = d = l = 0
        for m in af_get("fixtures/headtohead", {"h2h": f"{ips_id}-{opp_id}", "last": 5}):
            gh, ga = m["goals"]["home"], m["goals"]["away"]
            if gh is None:
                continue
            h_is_ips = m["teams"]["home"]["id"] == ips_id
            us, them = (gh, ga) if h_is_ips else (ga, gh)
            res = "W" if us > them else "L" if us < them else "D"
            w += res == "W"; d += res == "D"; l += res == "L"
            out["h2h"].append({"date": (m["fixture"]["date"] or "")[:10],
                               "home": h_is_ips, "score": f"{us}-{them}", "result": res})
        if out["h2h"]:
            out["h2h_summary"] = f"W{w} D{d} L{l}"
    except requests.RequestException:
        pass

    # win probability from API-Football's prediction model
    try:
        pred = af_get("predictions", {"fixture": fid})
        if pred:
            pc = pred[0].get("predictions", {}).get("percent", {})
            h, dr, a = _af_pct(pc.get("home")), _af_pct(pc.get("draw")), _af_pct(pc.get("away"))
            if None not in (h, dr, a):
                out["win_prob"] = {"ipswich": h if ips_home else a, "draw": dr,
                                   "opponent": a if ips_home else h}
    except requests.RequestException:
        pass

    return out


# --------------------------------------------------------------------------- #
#  API-Football — team news (injuries/suspensions), head-to-head, win prob     #
#  Needs a free key in the API_FOOTBALL_KEY env var (a GitHub Actions secret).  #
# --------------------------------------------------------------------------- #
def af_get(path, params, key):
    r = requests.get(f"{AF_BASE}/{path}", params=params,
                     headers={"x-apisports-key": key}, timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    return j.get("response", [])


def _pct(v):
    try:
        return int(str(v).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def fetch_api_football(key):
    out = {"team_news": [], "h2h": [], "h2h_record": None, "prob": None}

    # resolve Ipswich's API-Football team id
    resp = af_get("teams", {"search": "ipswich", "league": AF_LEAGUE, "season": AF_SEASON}, key)
    if not resp:
        resp = af_get("teams", {"search": "ipswich"}, key)
    ips_id = next((t["team"]["id"] for t in resp
                   if TEAM_NAME_MATCH in t["team"]["name"].lower()), None)
    if not ips_id:
        return out

    # team news — dedupe to most recent record per player
    seen = {}
    for rec in af_get("injuries", {"team": ips_id, "season": AF_SEASON}, key):
        p = rec.get("player", {}) or {}
        name = p.get("name")
        if not name:
            continue
        date = (rec.get("fixture", {}) or {}).get("date", "")
        if name not in seen or date > seen[name]["_date"]:
            seen[name] = {"player": name, "type": p.get("type"),
                          "reason": p.get("reason"), "_date": date}
    out["team_news"] = [{k: v for k, v in r.items() if not k.startswith("_")}
                        for r in sorted(seen.values(), key=lambda r: r["_date"], reverse=True)][:12]

    # next fixture → opponent id + fixture id + Ipswich's home/away
    nxt = af_get("fixtures", {"team": ips_id, "next": 1}, key)
    if nxt:
        fx = nxt[0]
        fid = fx["fixture"]["id"]
        home = fx["teams"]["home"]["id"] == ips_id
        opp_id = fx["teams"]["away"]["id"] if home else fx["teams"]["home"]["id"]

        # head-to-head, most recent meetings
        w = d = l = 0
        for m in af_get("fixtures/headtohead", {"h2h": f"{ips_id}-{opp_id}", "last": 6}, key):
            gh, ga = m["goals"]["home"], m["goals"]["away"]
            if gh is None:
                continue
            ips_home = m["teams"]["home"]["id"] == ips_id
            our, their = (gh, ga) if ips_home else (ga, gh)
            res = "W" if our > their else "L" if our < their else "D"
            w += res == "W"; d += res == "D"; l += res == "L"
            out["h2h"].append({"date": m["fixture"]["date"][:10],
                               "opponent": (m["teams"]["away"] if ips_home else m["teams"]["home"])["name"],
                               "home": ips_home, "score": f"{our}-{their}", "result": res})
        if out["h2h"]:
            out["h2h_record"] = {"w": w, "d": d, "l": l}

        # win probability from the predictions endpoint
        pred = af_get("predictions", {"fixture": fid}, key)
        if pred:
            pc = (pred[0].get("predictions") or {}).get("percent") or {}
            ph, pdrw, pa = _pct(pc.get("home")), _pct(pc.get("draw")), _pct(pc.get("away"))
            if ph is not None and pa is not None:
                out["prob"] = {"ipswich": ph if home else pa, "draw": pdrw,
                               "opponent": pa if home else ph}
    return out


# --------------------------------------------------------------------------- #
def main():
    fpl = fetch_fpl()
    tid, teams, ipswich = fpl["tid"], fpl["teams"], fpl["ipswich"]

    badges = {}
    try:
        badges = fetch_badges(teams)
        print(f"  badges: matched {sum(1 for v in badges.values() if v)}/{len(badges)} clubs")
    except Exception as e:
        print(f"  badges: skipped ({e})")

    def badge_for(short):
        return badges.get(short)

    for f in fpl["upcoming"]:
        f["badge"] = badge_for(f["opponent_short"])
    for r in fpl["results"]:
        r["badge"] = badge_for(r["opponent_short"])

    table, position = None, None
    try:
        table, position = fetch_table()
        # graft TheSportsDB badges onto table rows, ESPN logo as fallback
        if table:
            short_by_norm = {_norm(t["name"]): t["short_name"] for t in teams.values()}
            for row in table:
                short = short_by_norm.get(_norm(row["team"]))
                row["badge"] = (badges.get(short) if short else None) or row.get("espn_logo")
        print(f"  table: {len(table) if table else 0} teams, Ipswich {position or '—'}")
    except Exception as e:
        print(f"  table: skipped ({e})")

    understat = {"matches": [], "shot_maps": [], "players": []}
    try:
        understat = fetch_understat()
        print(f"  understat: {len(understat['matches'])} matches, "
              f"{len(understat['shot_maps'])} shot maps, {len(understat['players'])} players")
    except Exception as e:
        print(f"  understat: skipped ({e})")

    upcoming = fpl["upcoming"][:8]
    next_fixture = dict(upcoming[0]) if upcoming else None

    # ---- league-wide comparison data (Understat league page) -------------- #
    league_teams, league_players = {}, []
    try:
        league_teams, league_players = fetch_understat_league()
        print(f"  understat league: {len(league_teams)} teams, {len(league_players)} players")
    except Exception as e:
        print(f"  understat league: skipped ({e})")

    # short-name + badge lookup for Understat team titles
    meta_by_norm = {_norm(t["name"]): (t["short_name"], badges.get(t["short_name"]))
                    for t in teams.values()}
    def team_meta(title):
        k = _norm(title)
        if k in meta_by_norm: return meta_by_norm[k]
        if k in ALIASES and ALIASES[k] in meta_by_norm: return meta_by_norm[ALIASES[k]]
        for nk, v in meta_by_norm.items():
            if len(k) > 3 and (k in nk or nk in k): return v
        return (title[:3].upper(), None)

    # team scatter: xG vs xGA per game, all clubs
    team_scatter = []
    for title, a in league_teams.items():
        short, badge = team_meta(title)
        team_scatter.append({"team": title, "short": short, "badge": badge,
                             "xg_pg": a["xg_pg"], "xga_pg": a["xga_pg"],
                             "is_ipswich": TEAM_NAME_MATCH in title.lower()})

    # team ranks: where Ipswich sit among the 20 on each metric
    team_ranks = []
    ips_title = next((t for t in league_teams if TEAM_NAME_MATCH in t.lower()), None)
    if ips_title:
        n = len(league_teams)
        ips = league_teams[ips_title]
        def rank_on(key, low_good):
            arr = [a for a in league_teams.values() if a.get(key) is not None]
            arr.sort(key=lambda a: a[key], reverse=not low_good)
            return next((i for i, a in enumerate(arr, 1) if a["title"] == ips_title), None)
        for key, label, low in [("xg_pg", "xG per game", False), ("xga_pg", "xGA per game", True),
                                ("npxg", "Non-penalty xG", False), ("ppda", "Pressing (PPDA)", True)]:
            if ips.get(key) is not None:
                team_ranks.append({"label": label, "value": ips[key],
                                   "rank": rank_on(key, low), "total": n, "low_good": low})

    # points & goal-difference ranks come from the ESPN table
    if table:
        nt = len(table)
        ips_row = next((r for r in table if r.get("is_ipswich")), None)
        if ips_row:
            gd_rank = next((i for i, r in enumerate(
                sorted(table, key=lambda r: -r["gd"]), 1) if r.get("is_ipswich")), None)
            team_ranks.insert(0, {"label": "Points", "value": ips_row["points"],
                                  "rank": ips_row["rank"], "total": nt, "low_good": False})
            team_ranks.append({"label": "Goal difference", "value": ips_row["gd"],
                               "rank": gd_rank, "total": nt, "low_good": False})

    # player profiles: per-90 + percentile vs positional peers (league-wide)
    player_profiles = []
    if league_players:
        def per90(v, m): return round(v / (m / 90), 2) if m > 0 else 0.0
        pool, rows = {}, []
        for p in league_players:
            m = int(p.get("time", 0) or 0)
            if m <= 0:
                continue
            pos = simplify_pos(p.get("position", ""))
            vals = {"goals": per90(int(p["goals"]), m), "assists": per90(int(p["assists"]), m),
                    "npxg": per90(to_float(p.get("npxG", p["xG"])), m), "xa": per90(to_float(p["xA"]), m),
                    "shots": per90(int(p["shots"]), m), "key_passes": per90(int(p["key_passes"]), m),
                    "xgchain": per90(to_float(p.get("xGChain", 0)), m),
                    "xgbuildup": per90(to_float(p.get("xGBuildup", 0)), m)}
            rows.append({"name": p["player_name"], "team": p.get("team_title", ""),
                         "pos": pos, "minutes": m, "per90": vals})
            pool.setdefault(pos, []).append(vals)
        def pctile(pos, metric, val):
            peers = [v[metric] for v in pool.get(pos, [])]
            return round(sum(1 for x in peers if x <= val) / len(peers) * 100) if peers else 0
        keys = ["goals", "assists", "npxg", "xa", "shots", "key_passes", "xgchain", "xgbuildup"]
        for r in rows:
            if TEAM_NAME_MATCH in r["team"].lower():
                r["pct"] = {k: pctile(r["pos"], k, r["per90"][k]) for k in keys}
                player_profiles.append(r)
        player_profiles.sort(key=lambda r: -r["minutes"])

    # next-opponent preview (table position/points + Understat xG + recent form)
    next_opponent = None
    if next_fixture:
        opp = next_fixture["opponent"]
        row = next((r for r in (table or [])
                    if _norm(r["team"]) == _norm(opp) or _norm(opp) in _norm(r["team"])
                    or _norm(r["team"]) in _norm(opp)), None)
        agg = next((a for tt, a in league_teams.items()
                    if _norm(tt) == _norm(opp) or _norm(tt) in _norm(opp)
                    or _norm(opp) in _norm(tt)), None)
        short, badge = team_meta(opp)
        next_opponent = {"name": opp, "short": next_fixture.get("opponent_short", short),
                         "badge": next_fixture.get("badge") or badge, "home": next_fixture["home"],
                         "position": row["rank"] if row else None,
                         "points": row["points"] if row else None,
                         "gd": row["gd"] if row else None,
                         "xg_pg": agg["xg_pg"] if agg else None,
                         "xga_pg": agg["xga_pg"] if agg else None,
                         "form": agg["form"] if agg else []}

    # match reports: join team xG onto each shot map
    xg_by_mid = {m["match_id"]: m for m in understat["matches"]}
    for sm in understat["shot_maps"]:
        mm = xg_by_mid.get(sm["match_id"])
        if mm:
            sm["xg_for"] = mm["xg_for"]; sm["xg_against"] = mm["xg_against"]

    # ---- API-Football: team news, head-to-head, win probability ----------- #
    team_news = []
    af_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if af_key:
        try:
            af = fetch_api_football(af_key)
            team_news = af.get("team_news", [])
            if next_opponent:
                if af.get("prob"): next_opponent["prob"] = af["prob"]
                if af.get("h2h"):
                    next_opponent["h2h"] = af["h2h"]
                    next_opponent["h2h_record"] = af.get("h2h_record")
            print(f"  api-football: {len(team_news)} team-news, h2h {len(af.get('h2h', []))}, "
                  f"prob {'yes' if af.get('prob') else 'no'}")
        except Exception as e:
            print(f"  api-football: skipped ({e})")
    else:
        print("  api-football: no API_FOOTBALL_KEY set — skipping team news / H2H / win prob")

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": "2026/27",
        "team": {"id": tid, "name": ipswich["name"], "short_name": ipswich["short_name"],
                 "badge": badges.get(ipswich["short_name"])},
        "current_event": fpl["current"], "next_event": fpl["next"],
        "next_fixture": next_fixture,
        "next_opponent": next_opponent,
        "team_news": team_news,
        "position": position,
        "summary": fpl["summary"],
        "table": table or [],
        "team_scatter": team_scatter,
        "team_ranks": team_ranks,
        "player_profiles": player_profiles,
        "by_gameweek": fpl["by_gameweek"],
        "understat_matches": understat["matches"],
        "shot_maps": understat["shot_maps"],
        "understat_players": understat["players"][:14],
        "upcoming": upcoming,
        "results": list(reversed(fpl["results"]))[:10],
        "squad": fpl["squad"],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2))
    print(f"Wrote {OUT} — {ipswich['name']}: {len(data['squad'])} players, "
          f"{fpl['summary']['played']} played, pos {position or '—'}.")


if __name__ == "__main__":
    main()
