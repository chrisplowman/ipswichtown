"""
Pull Ipswich Town data from several free/open football sources and write a clean
data/itfc.json that build.py renders into the static page.

Sources (all free; only football-data-style keys avoided — none needed here):
  FPL              https://fantasy.premierleague.com/api/...   squad, fixtures, difficulty
  Understat        https://understat.com/getTeamData|getMatchData|getLeagueData/...  shot-level xG, match xG, player npxG
  ESPN (hidden)    https://site.web.api.espn.com/.../eng.1/standings  league table  (keyless)
  ESPN Core API    https://sports.core.api.espn.com/.../events/.../plays  bookings/subs, shots/corners/fouls/HT (keyless)
  TheSportsDB      https://www.thesportsdb.com/api/v1/json/3/...   club badges   (public test key)

Each non-FPL source is wrapped so a failure just drops that section — the page
still builds from whatever succeeded.

Run:  python ingest.py
"""

import csv
import io
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

FPL = "https://fantasy.premierleague.com/api"
UNDERSTAT_SEASON = "2026"          # Understat labels 2026/27 as "2026"
ESPN_SEASON = "2026"
UNDERSTAT_TEAM_SLUG = "Ipswich"    # confirmed via Understat's own team dropdown — not "Ipswich_Town"
FBD_SEASONS = ["2223", "2324", "2425", "2526"]  # football-data.co.uk season codes
FBD_CURRENT = "2627"               # current season, for per-match shot stats
FBD_DIVS = ["E0", "E1"]            # Premier League, Championship
CLUBELO_HFA = 65                   # home advantage, in Elo points
# Ipswich-specific RSS feeds (all team-specific, so no filtering needed).
# Add or remove feeds here — each is fetched independently and skipped on failure.
NEWS_FEEDS = [
    ("BBC Sport", "https://feeds.bbci.co.uk/sport/football/teams/ipswich-town/rss.xml"),
    ("TWTD", "https://www.twtd.co.uk/rss/"),
    ("ITFC.CO.UK", "https://www.itfc.co.uk/rss.xml"),
    ("The Athletic", "https://www.nytimes.com/athletic/rss/football/ipswich/"),
    ("EADT", "http://www.eadt.co.uk/sport/ipswich-town/rss/"),
]
NEWS_LIMIT = 18                    # max articles to keep after merging feeds
SHOT_MAP_MATCHES = 5               # how many recent matches to keep shot maps for
LEADERS_LIMIT = 10                 # how many players to keep in the top scorers/assists lists
TEAM_NAME_MATCH = "ipswich"
OUT = Path("data/itfc.json")
TIMEOUT = 30
RETRIES = 3
# A realistic browser User-Agent — some APIs (notably FPL) return 403 to CI/
# datacenter requests that don't look like a browser.
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/xml, application/xml, text/html, */*",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _get(url, headers=None, session=None):
    """GET with a browser UA and a few retries/backoff on transient failures.
    Optional session/headers let callers that need extra headers (e.g. Understat's
    AJAX endpoints, which require X-Requested-With + a matching Referer) reuse
    this same retry logic instead of duplicating it."""
    last = None
    requester = session or requests
    for attempt in range(RETRIES):
        try:
            r = requester.get(url, headers=headers or UA, timeout=TIMEOUT)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            if attempt < RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last


def get_json(url, base=None, headers=None, session=None):
    return _get(f"{base}/{url}" if base else url, headers=headers, session=session).json()


def get_text(url):
    return _get(url).text


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
    all_fixtures = get_json("fixtures/", FPL)

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

    club = [f for f in all_fixtures if tid in (f["team_h"], f["team_a"])]
    club.sort(key=lambda f: (f["event"] or 999, f["kickoff_time"] or ""))
    for f in club:
        home = f["team_h"] == tid
        opp = teams[f["team_a"] if home else f["team_h"]]
        difficulty = f["team_h_difficulty"] if home else f["team_a_difficulty"]
        # FPL flips `finished` only once bonus points are officially confirmed,
        # which can lag kickoff by hours; `finished_provisional` is set right at
        # full-time with the final score already in, so treat that as done too
        # (confirmed via a real gameweek-1 fixtures response: every played match
        # had finished_provisional=true, started=true, minutes=90, real scores,
        # but finished=false for hours afterwards).
        if (f["finished"] or f["finished_provisional"]) and f["team_h_score"] is not None:
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

    # full season fixture list (played + upcoming), in gameweek order
    fixtures = ([{**r, "finished": True} for r in results]
                + [{**u, "finished": False} for u in upcoming])
    fixtures.sort(key=lambda x: (x["event"] or 999, x.get("kickoff") or ""))

    # has the season actually started? (no finished/current gameweek = pre-season)
    season_started = current is not None or any(e.get("finished") for e in boot["events"])

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
        # FPL status 'u'/'n' means the player has left the club (transferred
        # out, released, or sent permanently out of the Premier League) —
        # FPL keeps them tagged to their old team for a few days, so exclude
        # them explicitly rather than showing them as a current squad member.
        if p["team"] != tid or p.get("status") in ("u", "n"):
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

    # Before the season starts FPL still serves last season's totals — show only
    # this season's stats, i.e. zero the accumulated counters until GW1 is under way.
    if not season_started:
        for r in squad:
            for k in ("points", "minutes", "starts", "goals", "assists", "clean_sheets"):
                r[k] = 0
            for k in ("form", "xg", "xa", "xgi"):
                r[k] = 0.0

    # team news — FPL flags injuries/suspensions/doubts via status + news.
    # 'u'/'n' mean the player has left the club entirely (see squad filter
    # above), not a fitness doubt, so they're excluded here too rather than
    # surfaced as "news" about a current squad member.
    status_label = {"i": ("Injured", "out"), "s": ("Suspended", "out"),
                    "d": ("Doubtful", "doubt")}
    team_news = []
    for p in boot["elements"]:
        if p["team"] != tid or p.get("status") in ("u", "n"):
            continue
        status = p.get("status", "a")
        news = (p.get("news") or "").strip()
        if status == "a" and not news:
            continue
        label, sev = status_label.get(status, ("Doubtful", "doubt"))
        chance = p.get("chance_of_playing_next_round")
        if sev == "out" and chance is not None and 0 < chance < 100:
            sev = "doubt"  # flagged but has a chance of featuring
        team_news.append({"player": p["web_name"], "news": news or label,
                          "tag": label, "sev": sev})
    team_news.sort(key=lambda t: 0 if t["sev"] == "out" else 1)

    return {"teams": teams, "ipswich": ipswich, "tid": tid,
            "current": current, "next": nxt, "summary": summary, "team_news": team_news,
            "by_gameweek": by_gameweek, "upcoming": upcoming, "results": results,
            "fixtures": fixtures, "squad": squad, "all_fixtures": all_fixtures}


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
    # site.api.espn.com blocks GitHub Actions' IP ranges with a 403 (confirmed:
    # the same path on this host, site.web.api.espn.com, returns identical valid
    # data from a normal connection and is reported elsewhere as the fix for
    # exactly this CI-blocking symptom). fetch_table_from_fbd() is still the
    # fallback below if this host ever fails too.
    url = (f"https://site.web.api.espn.com/apis/v2/sports/soccer/eng.1/standings?season={ESPN_SEASON}")
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


def fetch_table_from_fbd(fbd_rows):
    """Fallback league table computed from football-data.co.uk's current-season
    CSV (already fetched for match_stats/league_tables) for when ESPN's hidden
    standings API is unreachable — it blocks datacenter/CI IP ranges even
    though the endpoint itself is otherwise fine (confirmed by testing the
    same URL from a normal connection)."""
    teams = {}
    for r in fbd_rows:
        h, a = r.get("HomeTeam", ""), r.get("AwayTeam", "")
        try:
            hg, ag = int(r["FTHG"]), int(r["FTAG"])
        except (KeyError, ValueError):
            continue
        if not h or not a:
            continue
        H = teams.setdefault(canon(h), {"team": h, "played": 0, "won": 0, "drawn": 0,
                                        "lost": 0, "gf": 0, "ga": 0, "espn_logo": None})
        A = teams.setdefault(canon(a), {"team": a, "played": 0, "won": 0, "drawn": 0,
                                        "lost": 0, "gf": 0, "ga": 0, "espn_logo": None})
        H["played"] += 1; H["gf"] += hg; H["ga"] += ag
        A["played"] += 1; A["gf"] += ag; A["ga"] += hg
        if hg > ag: H["won"] += 1; A["lost"] += 1
        elif hg < ag: H["lost"] += 1; A["won"] += 1
        else: H["drawn"] += 1; A["drawn"] += 1
    if not teams:
        return None, None
    rows = list(teams.values())
    for r in rows:
        r["gd"] = r["gf"] - r["ga"]
        r["points"] = r["won"] * 3 + r["drawn"]
    rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["team"]))
    position = None
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["is_ipswich"] = TEAM_NAME_MATCH in r["team"].lower()
        if r["is_ipswich"]:
            position = i
    return rows, position


# --------------------------------------------------------------------------- #
#  ESPN — match bookings & substitutions (Core API play-by-play)              #
# --------------------------------------------------------------------------- #
IPSWICH_ESPN_TEAM_ID = "373"
PLAY_CACHE_DIR = "play_cache"
_TEAM_ID_RE = re.compile(r"/teams/(\d+)")


def fetch_espn_schedule(team_id=IPSWICH_ESPN_TEAM_ID):
    """Ipswich's ESPN fixture list for the current season, keyed by kickoff
    date, so Understat match_pages (keyed by Understat's own match id) can be
    matched to an ESPN event id. Same site.web.api.espn.com host as
    fetch_table() to dodge the CI IP block that hits site.api.espn.com."""
    url = (f"https://site.web.api.espn.com/apis/site/v2/sports/soccer/eng.1/"
           f"teams/{team_id}/schedule?season={ESPN_SEASON}")
    j = get_json(url)
    by_date = {}
    for ev in j.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        if not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        date = (ev.get("date") or "")[:10]
        if date and ev.get("id"):
            by_date[date] = ev["id"]
    return by_date


MATCH_STAT_KEYS = ("shots_for", "shots_against", "sot_for", "sot_against",
                    "corners_for", "corners_against", "fouls_for", "fouls_against",
                    "yellows_for", "yellows_against", "reds_for", "reds_against")
_ESPN_SOT_TYPES = {"shot-on-target"}
_ESPN_OFF_TARGET_TYPES = {"shot-off-target", "shot-blocked", "shot-hit-woodwork"}


def fetch_espn_match_events(event_id, is_home):
    """Cards, substitutions and match stats (shots/SOT/corners/fouls/HT score)
    for one match, from a single ESPN Core API play-by-play fetch — the primary
    source for these, ahead of football-data.co.uk. Verified against a real
    payload (event 740604, Arsenal vs Man Utd): each play's `text` already has
    the full human-readable description, flat `yellowCard`/`redCard`/
    `substitution` booleans make card/sub filtering trivial, and `type.type`
    carries the shot/foul/corner/halftime classification (e.g.
    "shot-on-target", "shot-off-target", "shot-blocked", "shot-hit-woodwork",
    goal types prefixed "goal", "corner-awarded", "foul", "halftime" — the
    latter carrying global (not team-specific) homeScore/awayScore, mapped
    onto Ipswich's for/against via `is_home`). Returns (None, None, None) when
    the match has no play-by-play yet, so callers can fall back cleanly."""
    url = (f"https://sports.core.api.espn.com/v2/sports/soccer/leagues/eng.1/"
           f"events/{event_id}/competitions/{event_id}/plays?limit=300")
    items = get_json(url).get("items", [])
    if not items:
        return None, None, None
    cards, subs = [], []
    stats = {k: 0 for k in MATCH_STAT_KEYS}
    stats["ht_for"] = stats["ht_against"] = None
    for p in items:
        ptype = (p.get("type") or {}).get("type", "")
        m = _TEAM_ID_RE.search((p.get("team") or {}).get("$ref", ""))
        side = "for" if m and m.group(1) == IPSWICH_ESPN_TEAM_ID else "against"

        if ptype == "halftime":
            hs, as_ = p.get("homeScore"), p.get("awayScore")
            if hs is not None and as_ is not None:
                stats["ht_for"], stats["ht_against"] = (hs, as_) if is_home else (as_, hs)
            continue

        if ptype in _ESPN_SOT_TYPES or ptype.startswith("goal"):
            stats[f"shots_{side}"] += 1
            stats[f"sot_{side}"] += 1
        elif ptype in _ESPN_OFF_TARGET_TYPES:
            stats[f"shots_{side}"] += 1
        elif ptype == "corner-awarded":
            stats[f"corners_{side}"] += 1
        elif ptype == "foul":
            stats[f"fouls_{side}"] += 1

        is_card = p.get("yellowCard") or p.get("redCard")
        is_sub = p.get("substitution")
        if not (is_card or is_sub):
            continue
        clock = p.get("clock", {})
        entry = {"minute": (clock.get("displayValue") or "").rstrip("'"),
                 "sort": clock.get("value", 0.0),
                 "text": p.get("text", ""), "side": side}
        if is_card:
            entry["kind"] = "red" if p.get("redCard") else "yellow"
            stats[f"{'reds' if entry['kind'] == 'red' else 'yellows'}_{side}"] += 1
            cards.append(entry)
        else:
            subs.append(entry)
    cards.sort(key=lambda e: e["sort"])
    subs.sort(key=lambda e: e["sort"])
    for e in cards + subs:
        del e["sort"]
    return cards, subs, stats


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
    """TheSportsDB's bulk lookup_all_teams.php?id=<league> serves stale/wrong
    data for the Premier League specifically (confirmed: it returns League
    One's roster even though 4328 is genuinely the Premier League's id) —
    likely that bulk endpoint is now gated behind a paid key and silently
    falls back instead of erroring. Individual searchteams.php calls return
    correct, current data, so badges are fetched one club at a time instead."""
    by_short = {}
    for t in fpl_teams.values():
        try:
            j = get_json("https://www.thesportsdb.com/api/v1/json/3/searchteams.php"
                         f"?t={t['name'].replace(' ', '%20')}")
        except requests.RequestException:
            continue
        want = canon(t["name"])
        best = None
        for team in (j.get("teams") or []):
            if team.get("strSport") != "Soccer":
                continue
            if canon(team.get("strTeam", "")) == want:
                best = team
                break
            best = best or team
        badge = (best.get("strBadge") or best.get("strTeamBadge")) if best else None
        if badge:
            by_short[t["short_name"]] = badge
    return by_short


# --------------------------------------------------------------------------- #
#  Understat — match xG, shot maps, player npxG                               #
#  Understat moved from embedding a JSON blob in each page's HTML (the old
#  `datesData`/`playersData`/`shotsData`/`rostersData`/`teamsData` you'd find
#  via a `JSON.parse('...')` regex) to plain JSON AJAX endpoints the page's own
#  JS calls after load. Confirmed via a real browser Network-tab capture: the
#  field names inside each payload are unchanged, only the delivery mechanism
#  is different — so only the fetch itself changes here, not the parsing below.
#  The endpoints require an X-Requested-With header and a matching Referer (a
#  plain page-navigation request 404s; the AJAX-shaped one succeeds), so calls
#  go through a shared session that also carries cookies the same way a real
#  browser would across the sequence of Understat requests in one run.
# --------------------------------------------------------------------------- #
UNDERSTAT_SESSION = requests.Session()


def _understat_json(path, referer):
    headers = {**UA, "Accept": "application/json, text/javascript, */*; q=0.01",
               "X-Requested-With": "XMLHttpRequest", "Referer": referer}
    return get_json(f"https://understat.com/{path}", headers=headers, session=UNDERSTAT_SESSION)


def fetch_match_detail(mid, side):
    """Both teams' shots + player match-lines, from Understat's getMatchData API."""
    data = _understat_json(f"getMatchData/{mid}", f"https://understat.com/match/{mid}")
    shots = data.get("shots") or {}
    rosters = data.get("rosters") or {}
    them = "a" if side == "h" else "h"

    def shot_list(key):
        return [{"x": to_float(s["X"]), "y": to_float(s["Y"]), "xg": to_float(s["xG"]),
                 "result": s["result"], "player": s["player"], "minute": int(s["minute"]),
                 "situation": s.get("situation", ""), "assist": s.get("player_assisted") or ""}
                for s in shots.get(key, [])]

    def roster_list(key):
        rl = []
        for p in (rosters.get(key, {}) or {}).values():
            if int(p.get("time", 0) or 0) <= 0:
                continue
            rl.append({"name": p.get("player", "?"), "pos": p.get("position", ""),
                       "minutes": int(p.get("time", 0) or 0), "goals": int(p.get("goals", 0) or 0),
                       "assists": int(p.get("assists", 0) or 0), "shots": int(p.get("shots", 0) or 0),
                       "xg": to_float(p.get("xG", 0)), "xa": to_float(p.get("xA", 0)),
                       "key_passes": int(p.get("key_passes", 0) or 0),
                       "yellow": int(p.get("yellow_card", 0) or 0), "red": int(p.get("red_card", 0) or 0),
                       "order": int(p.get("positionOrder", 99) or 99)})
        rl.sort(key=lambda x: x["order"])
        return rl

    return {"shots_for": shot_list(side), "shots_against": shot_list(them),
            "players_for": roster_list(side), "players_against": roster_list(them)}


def fetch_understat():
    team_data = _understat_json(f"getTeamData/{UNDERSTAT_TEAM_SLUG}/{UNDERSTAT_SEASON}",
                                f"https://understat.com/team/{UNDERSTAT_TEAM_SLUG}/{UNDERSTAT_SEASON}")
    dates = team_data.get("dates") or []
    players_raw = team_data.get("players") or []

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
    xg_by_mid = {m["match_id"]: m for m in finished_matches}

    # Full detail for every finished match (most recent first). Finished matches never
    # change, so each match's Understat detail is cached on disk and only fetched once.
    CACHE_DIR = "match_cache"
    os.makedirs(CACHE_DIR, exist_ok=True)
    match_pages, fetched = [], 0
    for mid, opp, home, date, score, side in list(reversed(finished_ids)):
        cache_file = os.path.join(CACHE_DIR, f"{mid}.json")
        det = None
        if os.path.exists(cache_file):
            try:
                with open(cache_file) as fh:
                    det = json.load(fh)
            except (ValueError, OSError):
                det = None
        if det is None:
            try:
                det = fetch_match_detail(mid, side)
            except requests.RequestException:
                continue
            try:
                with open(cache_file, "w") as fh:
                    json.dump(det, fh)
            except OSError:
                pass
            fetched += 1
            time.sleep(0.2)  # be gentle with Understat (only for uncached matches)
        mm = xg_by_mid.get(mid, {})
        gf, ga = mm.get("gf", 0), mm.get("ga", 0)
        goals = ([{"minute": s["minute"], "player": s["player"], "assist": s["assist"], "side": "for"}
                  for s in det["shots_for"] if s["result"] == "Goal"] +
                 [{"minute": s["minute"], "player": s["player"], "assist": s["assist"], "side": "against"}
                  for s in det["shots_against"] if s["result"] == "Goal"])
        goals.sort(key=lambda g: g["minute"])
        match_pages.append({"id": str(mid), "opponent": opp, "home": home, "date": date,
                            "score": score, "gf": gf, "ga": ga,
                            "xg_for": mm.get("xg_for"), "xg_against": mm.get("xg_against"),
                            "result": "W" if gf > ga else "L" if gf < ga else "D",
                            "goals": goals, **det})
    print(f"  match detail: {len(match_pages)} matches ({fetched} freshly fetched, rest cached)")

    # shot maps (recent) for the Charts page, derived from the detail we already have
    shot_maps = [{"match_id": m["id"], "opponent": m["opponent"], "home": m["home"],
                  "date": m["date"], "score": m["score"], "xg_for": m["xg_for"],
                  "xg_against": m["xg_against"], "shots": m["shots_for"]}
                 for m in match_pages[:SHOT_MAP_MATCHES]]

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

    return {"matches": finished_matches, "shot_maps": shot_maps,
            "players": players, "match_pages": match_pages}


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
    league_data = _understat_json(f"getLeagueData/EPL/{UNDERSTAT_SEASON}",
                                  f"https://understat.com/league/EPL/{UNDERSTAT_SEASON}")
    teams_raw = league_data.get("teams") or {}
    players_raw = league_data.get("players") or []

    def _match_pts(h):
        p = h.get("pts")
        if p not in (None, ""):
            try:
                return int(p)
            except (TypeError, ValueError):
                pass
        r = (h.get("result", "") or "").lower()
        return 3 if r == "w" else 1 if r == "d" else 0

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
               "pts": sum(_match_pts(h) for h in hist),
               "xpts": round(sum(to_float(h.get("xpts", 0)) for h in hist), 1),
               "form": [h.get("result", "").upper()[:1] for h in hist[-5:]
                        if h.get("result", "").upper()[:1] in ("W", "D", "L")]}
        league_teams[t["title"]] = agg

    # Ipswich's per-match history (xPts, PPDA, deep completions, etc.) for trend charts
    ips_history = []
    for t in teams_raw.values():
        if TEAM_NAME_MATCH not in t["title"].lower():
            continue
        for h in t.get("history", []):
            ppda = h.get("ppda") or {}
            ppda_a = h.get("ppda_allowed") or {}
            def _ppda(d):
                att, dfn = to_float(d.get("att", 0)), to_float(d.get("def", 0))
                return round(att / dfn, 2) if dfn else None
            ips_history.append({
                "date": (h.get("date", "") or "")[:10], "h_a": h.get("h_a", ""),
                "xg": to_float(h.get("xG", 0)), "xga": to_float(h.get("xGA", 0)),
                "npxg": to_float(h.get("npxG", 0)), "npxga": to_float(h.get("npxGA", 0)),
                "deep": int(h.get("deep", 0) or 0), "deep_allowed": int(h.get("deep_allowed", 0) or 0),
                "scored": int(h.get("scored", 0) or 0), "conceded": int(h.get("missed", 0) or 0),
                "xpts": to_float(h.get("xpts", 0)),
                "pts": int(h["pts"]) if h.get("pts") not in (None, "") else
                       (3 if (h.get("result", "") or "").lower() == "w"
                        else 1 if (h.get("result", "") or "").lower() == "d" else 0),
                "ppda": _ppda(ppda), "ppda_allowed": _ppda(ppda_a)})
        break
    return league_teams, players_raw, ips_history


# --------------------------------------------------------------------------- #
#  Keyless team news / head-to-head / win probability                          #
#  - team news is built from FPL player flags (in fetch_fpl)                    #
#  - head-to-head from football-data.co.uk historical CSVs                      #
#  - win probability modelled from ClubElo ratings                             #
# --------------------------------------------------------------------------- #
CANON = {  # collapse club-name variants (FPL / football-data / ClubElo) to one key
    "man city": "mancity", "manchester city": "mancity",
    "man united": "manutd", "man utd": "manutd", "manchester united": "manutd",
    "nott'm forest": "forest", "nottingham forest": "forest", "forest": "forest",
    "spurs": "tottenham", "tottenham": "tottenham", "tottenham hotspur": "tottenham",
    "wolves": "wolves", "wolverhampton": "wolves", "wolverhampton wanderers": "wolves",
    "west ham": "westham", "west ham united": "westham",
    "newcastle": "newcastle", "newcastle united": "newcastle", "newcastle utd": "newcastle",
    "brighton": "brighton", "brighton & hove albion": "brighton", "brighton and hove albion": "brighton",
    "sheffield united": "sheffutd", "sheffield utd": "sheffutd", "sheff united": "sheffutd",
    "leeds": "leeds", "leeds united": "leeds",
    "west brom": "westbrom", "west bromwich albion": "westbrom",
    "qpr": "qpr", "queens park rangers": "qpr",
}


def canon(name):
    k = (name or "").strip().lower()
    if k in CANON:
        return CANON[k]
    n = _norm(name)
    return CANON.get(n, n)


def _fbd_iso(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime((s or "").strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return s or ""


def fetch_h2h_history():
    """Ipswich results across recent PL (E0) and Championship (E1) seasons."""
    meetings = {}
    for s in FBD_SEASONS:
        for div in FBD_DIVS:
            try:
                text = get_text(f"https://www.football-data.co.uk/mmz4281/{s}/{div}.csv")
            except requests.RequestException:
                continue
            for r in csv.DictReader(io.StringIO(text)):
                h, a = r.get("HomeTeam", ""), r.get("AwayTeam", "")
                if TEAM_NAME_MATCH not in f"{h}{a}".lower():
                    continue
                try:
                    hg, ag = int(r["FTHG"]), int(r["FTAG"])
                except (KeyError, ValueError, TypeError):
                    continue
                ips_home = TEAM_NAME_MATCH in h.lower()
                opp = a if ips_home else h
                our, their = (hg, ag) if ips_home else (ag, hg)
                res = "W" if our > their else "L" if our < their else "D"
                meetings.setdefault(canon(opp), []).append(
                    {"date": _fbd_iso(r.get("Date", "")), "opponent": opp,
                     "home": ips_home, "score": f"{our}-{their}", "result": res})
    return meetings


def _fbd_rows():
    """The full current-season football-data CSV (PL, else Championship) as dict rows."""
    for div in FBD_DIVS:
        try:
            text = get_text(f"https://www.football-data.co.uk/mmz4281/{FBD_CURRENT}/{div}.csv")
        except requests.RequestException:
            continue
        rows = list(csv.DictReader(io.StringIO(text)))
        if any(TEAM_NAME_MATCH in (r.get("HomeTeam", "") + r.get("AwayTeam", "")).lower() for r in rows):
            return rows
    return []


def fetch_match_stats(rows):
    """Ipswich's current-season per-match shots/cards/result from football-data.co.uk.
    Fallback only — ESPN's play-by-play (fetch_espn_match_events) is the primary
    source for these stats and is preferred wherever it's available."""
    out = []
    for r in rows:
        h, a = r.get("HomeTeam", ""), r.get("AwayTeam", "")
        if TEAM_NAME_MATCH not in f"{h}{a}".lower():
            continue

        def gi(k):
            try:
                return int(r.get(k, "") or 0)
            except (ValueError, TypeError):
                return 0
        ips_home = TEAM_NAME_MATCH in h.lower()
        opp = a if ips_home else h
        pick = lambda hk, ak: gi(hk) if ips_home else gi(ak)

        hth, hta = gi("HTHG"), gi("HTAG")
        gf, ga = pick("FTHG", "FTAG"), pick("FTAG", "FTHG")
        htf, hta_ = (hth, hta) if ips_home else (hta, hth)
        out.append({"date": _fbd_iso(r.get("Date", "")), "opponent": opp, "home": ips_home,
                    "gf": gf, "ga": ga, "result": "W" if gf > ga else "L" if gf < ga else "D",
                    "shots_for": pick("HS", "AS"), "shots_against": pick("AS", "HS"),
                    "sot_for": pick("HST", "AST"), "sot_against": pick("AST", "HST"),
                    "corners_for": pick("HC", "AC"), "corners_against": pick("AC", "HC"),
                    "fouls_for": pick("HF", "AF"), "fouls_against": pick("AF", "HF"),
                    "yellows_for": pick("HY", "AY"), "yellows_against": pick("AY", "HY"),
                    "reds_for": pick("HR", "AR"), "reds_against": pick("AR", "HR"),
                    "ht_for": htf, "ht_against": hta_, "ht_state": (
                        "ahead" if htf > hta_ else "behind" if htf < hta_ else "level")})
    return out


def fetch_league_tables(rows):
    """Home-only and away-only tables plus each club's last-five form, from the full
    current-season football-data CSV."""
    teams, hist = {}, {}

    def rec(k, name):
        return teams.setdefault(k, {"team": name, "hp": 0, "hw": 0, "hd": 0, "hl": 0, "hgf": 0,
                                    "hga": 0, "ap": 0, "aw": 0, "ad": 0, "al": 0, "agf": 0, "aga": 0})
    for r in rows:
        h, a = r.get("HomeTeam", ""), r.get("AwayTeam", "")
        try:
            hg, ag = int(r["FTHG"]), int(r["FTAG"])
        except (KeyError, ValueError):
            continue
        if not h or not a:
            continue
        hk, ak = canon(h), canon(a)
        H, A = rec(hk, h), rec(ak, a)
        H["hp"] += 1; H["hgf"] += hg; H["hga"] += ag
        A["ap"] += 1; A["agf"] += ag; A["aga"] += hg
        if hg > ag:
            H["hw"] += 1; A["al"] += 1; hr, ar = "W", "L"
        elif hg < ag:
            H["hl"] += 1; A["aw"] += 1; hr, ar = "L", "W"
        else:
            H["hd"] += 1; A["ad"] += 1; hr, ar = "D", "D"
        d = _fbd_iso(r.get("Date", ""))
        hist.setdefault(hk, []).append((d, hr))
        hist.setdefault(ak, []).append((d, ar))

    def build(side):
        out = []
        for t in teams.values():
            p, w, dr, l, gf, ga = (t["hp"], t["hw"], t["hd"], t["hl"], t["hgf"], t["hga"]) if side == "h" \
                else (t["ap"], t["aw"], t["ad"], t["al"], t["agf"], t["aga"])
            if not p:
                continue
            out.append({"team": t["team"], "played": p, "won": w, "drawn": dr, "lost": l,
                        "gf": gf, "ga": ga, "gd": gf - ga, "points": w * 3 + dr})
        out.sort(key=lambda x: (-x["points"], -x["gd"], -x["gf"]))
        for i, x in enumerate(out, 1):
            x["rank"] = i
        return out

    form = {}
    for k, lst in hist.items():
        form[k] = [c for _, c in sorted(lst, key=lambda x: x[0])[-5:]]
    return build("h"), build("a"), form


def fetch_elo_history(cutoff="2026-07-01"):
    """Ipswich's ClubElo rating trajectory across the current season."""
    text = None
    for scheme in ("http", "https"):
        try:
            text = get_text(f"{scheme}://api.clubelo.com/Ipswich")
            break
        except requests.RequestException:
            continue
    if not text:
        return []
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        frm, elo = r.get("From", ""), r.get("Elo", "")
        if frm >= cutoff and elo:
            try:
                out.append({"date": frm, "elo": round(float(elo))})
            except ValueError:
                continue
    return out


def fetch_clubelo_elos():
    """Current Elo rating for every club, from ClubElo's dated CSV endpoint."""
    today = datetime.now(timezone.utc).date().isoformat()
    # api.clubelo.com's HTTPS cert is invalid, so try HTTP first, then HTTPS.
    text = None
    for scheme in ("http", "https"):
        try:
            text = get_text(f"{scheme}://api.clubelo.com/{today}")
            break
        except requests.RequestException:
            continue
    if text is None:
        raise requests.RequestException("ClubElo unreachable over http and https")
    elos = {}
    for r in csv.DictReader(io.StringIO(text)):
        club, elo = r.get("Club"), r.get("Elo")
        if club and elo:
            try:
                elos[canon(club)] = float(elo)
            except ValueError:
                continue
    return elos


def monte_carlo(teams, all_fixtures, elos, ips_tid, n=10000):
    """Simulate the rest of the season n times from current standings + Elo, returning
    Ipswich's survival odds and every club's relegation probability."""
    import random
    base = {t["id"]: {"name": t["name"], "pts": t.get("points", 0) or 0} for t in teams.values()}
    if ips_tid not in base:
        return None, {}
    # pre-compute home win / draw probabilities for each remaining fixture from Elo
    fx = []
    for f in all_fixtures:
        # same finished_provisional caveat as fetch_fpl() — a played-but-not-yet-
        # officially-confirmed match must still be excluded from "remaining
        # fixtures to simulate", or the sim replays it on top of the real result.
        if (f.get("finished") or f.get("finished_provisional")
                or f["team_h"] not in base or f["team_a"] not in base):
            continue
        eh = elos.get(canon(base[f["team_h"]]["name"]), 1500)
        ea = elos.get(canon(base[f["team_a"]]["name"]), 1500)
        we = 1.0 / (1.0 + 10 ** (-(eh - ea + CLUBELO_HFA) / 400.0))
        pd = 0.28 * (1 - abs(2 * we - 1))
        pw = max(0.0, we - pd / 2)
        pl = max(0.0, (1 - we) - pd / 2)
        tot = pw + pd + pl or 1
        fx.append((f["team_h"], f["team_a"], pw / tot, (pw + pd) / tot))
    if not fx:
        return None, {}
    ids = list(base)
    releg = {i: 0 for i in ids}
    ips_pos, ips_pts = [], []
    rnd = random.random
    for _ in range(n):
        pts = {i: base[i]["pts"] for i in ids}
        for h, a, pw, pwd in fx:
            r = rnd()
            if r < pw:
                pts[h] += 3
            elif r < pwd:
                pts[h] += 1; pts[a] += 1
            else:
                pts[a] += 3
        order = sorted(ids, key=lambda i: (-pts[i], rnd()))   # GD unknown → random tie-break
        for rank, i in enumerate(order, 1):
            if rank >= 18:
                releg[i] += 1
        ips_pos.append(order.index(ips_tid) + 1)
        ips_pts.append(pts[ips_tid])
    ips_pts.sort(); ips_pos.sort()
    pc = lambda arr, p: arr[min(len(arr) - 1, int(p * len(arr)))]
    ips_releg = releg[ips_tid] / n * 100
    survival = {"survive_pct": round(100 - ips_releg, 1), "releg_pct": round(ips_releg, 1),
                "avg_points": round(sum(ips_pts) / n), "pts_lo": pc(ips_pts, 0.1), "pts_hi": pc(ips_pts, 0.9),
                "avg_position": round(sum(ips_pos) / n, 1), "pos_lo": pc(ips_pos, 0.1),
                "pos_hi": pc(ips_pos, 0.9), "sims": n}
    releg_odds = {base[i]["name"]: round(releg[i] / n * 100, 1) for i in ids}
    return survival, releg_odds


def win_probs(elo_ips, elo_opp, home):
    """W/D/L probabilities estimated from an Elo difference (with home edge)."""
    dr = elo_ips - elo_opp + (CLUBELO_HFA if home else -CLUBELO_HFA)
    we = 1.0 / (1.0 + 10 ** (-dr / 400.0))          # Ipswich expected points share
    p_draw = 0.28 * (1 - abs(2 * we - 1))
    p_win = max(0.0, we - p_draw / 2)
    p_loss = max(0.0, (1 - we) - p_draw / 2)
    total = p_win + p_draw + p_loss or 1
    ips = round(p_win / total * 100)
    draw = round(p_draw / total * 100)
    return {"ipswich": ips, "draw": draw, "opponent": 100 - ips - draw}


def fdr_win_probs(difficulty):
    """Rough W/D/L from the FPL fixture difficulty (1 easy … 5 hard) — a fallback
    for when ClubElo is unavailable (e.g. pre-season)."""
    table = {1: (56, 26, 18), 2: (45, 28, 27), 3: (33, 28, 39),
             4: (24, 26, 50), 5: (15, 24, 61)}
    ips, draw, opp = table.get(difficulty, (33, 28, 39))
    return {"ipswich": ips, "draw": draw, "opponent": opp}



# --------------------------------------------------------------------------- #
#  News — merge a few Ipswich-specific RSS feeds (keyless)                      #
# --------------------------------------------------------------------------- #
ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
MEDIA = "{http://search.yahoo.com/mrss/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
SUMMARY_CHARS = 400        # cap the stored snippet; the page clamps it to ~5 lines


def _strip_html(s):
    if not s:
        return ""
    from html import unescape
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)  # drop script/style
    s = re.sub(r"<[^>]+>", " ", s)                              # strip tags
    return re.sub(r"\s+", " ", unescape(s)).strip()


def _item_image(e, desc_html):
    """Best image URL for a feed item, from Media RSS, an enclosure, or the body."""
    thumb = e.find(f".//{MEDIA}thumbnail")
    if thumb is not None and (thumb.get("url") or "").startswith(("http://", "https://")):
        return thumb.get("url")
    for mc in e.findall(f".//{MEDIA}content"):
        url = mc.get("url") or ""
        if url.startswith(("http://", "https://")) and (
                mc.get("medium") == "image" or (mc.get("type") or "").startswith("image")):
            return url
    enc = e.find("enclosure")
    if enc is not None and (enc.get("type") or "").startswith("image") \
            and (enc.get("url") or "").startswith(("http://", "https://")):
        return enc.get("url")
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc_html or "", re.I)
    if m and m.group(1).startswith(("http://", "https://")):
        return m.group(1)
    return None


def _parse_feed_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:                                    # RFC-822 (RSS pubDate)
        dt = parsedate_to_datetime(s)
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    try:                                    # ISO-8601 (Atom)
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def fetch_news():
    items = []
    for source, url in NEWS_FEEDS:
        try:
            root = ET.fromstring(_get(url).content)   # bytes -> honours XML encoding
        except (requests.RequestException, ET.ParseError, ValueError):
            continue
        entries = root.findall(".//item") or root.findall(f".//{ATOM}entry")
        for e in entries:
            title = (e.findtext("title") or e.findtext(f"{ATOM}title") or "").strip()
            link = (e.findtext("link") or "").strip()
            if not link:                    # Atom stores the URL in an attribute
                a = e.find(f"{ATOM}link")
                link = a.get("href", "").strip() if a is not None else ""
            dt = _parse_feed_date(e.findtext("pubDate") or e.findtext(f"{ATOM}updated")
                                  or e.findtext(f"{DC}date"))
            if not title or not link.startswith(("http://", "https://")):
                continue
            desc_raw = (e.findtext("description") or e.findtext(f"{CONTENT}encoded")
                        or e.findtext(f"{ATOM}summary") or e.findtext(f"{ATOM}content") or "")
            items.append({"title": title, "link": link, "source": source,
                          "date": dt.isoformat() if dt else "",
                          "date_display": dt.strftime("%-d %b") if dt else "",
                          "image": _item_image(e, desc_raw),
                          "summary": _strip_html(desc_raw)[:SUMMARY_CHARS].strip()})

    items.sort(key=lambda x: x["date"], reverse=True)  # newest first; undated last
    seen, out = set(), []
    for it in items:
        if it["link"] not in seen:
            seen.add(it["link"])
            out.append(it)
    return out[:NEWS_LIMIT]


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

    # A club's badge: the official Premier League crest, keyed by FPL's own team
    # code (verified URL used on premierleague.com). Complete for all 20 clubs with
    # no name-matching. TheSportsDB / ESPN logos remain a fallback.
    code_by_short = {t["short_name"]: t.get("code") for t in teams.values()}
    espn_by_short = {}

    def badge_for(short):
        code = code_by_short.get(short)
        if code:
            return f"https://resources.premierleague.com/premierleague25/badges/{code}.svg"
        return badges.get(short) or espn_by_short.get(short)

    # league table — football-data.co.uk's current-season CSV is fetched early
    # here so it's ready as a fallback if ESPN's standings API is unreachable
    # (it blocks datacenter/CI IP ranges; see fetch_table_from_fbd's docstring).
    fbd_rows = _fbd_rows()
    table, position, table_source = None, None, "espn"
    try:
        table, position = fetch_table()
    except Exception as e:
        print(f"  table (ESPN): skipped ({e})")
    if not table:
        table, position = fetch_table_from_fbd(fbd_rows)
        table_source = "football-data.co.uk"
    if table:
        short_by_canon = {canon(t["name"]): t["short_name"] for t in teams.values()}
        for row in table:
            short = short_by_canon.get(canon(row["team"]))
            if short and row.get("espn_logo"):
                espn_by_short[short] = row["espn_logo"]
            row["badge"] = badge_for(short) if short else row.get("espn_logo")
    print(f"  table: {len(table) if table else 0} teams, Ipswich {position or '—'} (source: {table_source})")

    # season-record ranks — where Ipswich sit among the league on each basic
    # stat (won/lost/goals for/against/etc.), computed straight from `table`
    # so the Overview page's Season record card can show "Nth in league"
    # next to each number without any extra fetch.
    summary_ranks = {}
    if table and any(r.get("is_ipswich") for r in table):
        def rank_on(key, low_good=False):
            arr = sorted(table, key=lambda r: r[key], reverse=not low_good)
            return next((i for i, r in enumerate(arr, 1) if r.get("is_ipswich")), None)
        summary_ranks = {
            "total": len(table), "points": rank_on("points"), "won": rank_on("won"),
            "lost": rank_on("lost", low_good=True), "gf": rank_on("gf"),
            "ga": rank_on("ga", low_good=True), "gd": rank_on("gd")}

    for f in fpl["upcoming"]:
        f["badge"] = badge_for(f["opponent_short"])
    for r in fpl["results"]:
        r["badge"] = badge_for(r["opponent_short"])
    for x in fpl["fixtures"]:
        x["badge"] = badge_for(x["opponent_short"])

    understat = {"matches": [], "shot_maps": [], "players": []}
    try:
        understat = fetch_understat()
        print(f"  understat: {len(understat['matches'])} matches, "
              f"{len(understat['shot_maps'])} shot maps, {len(understat['players'])} players")
    except Exception as e:
        print(f"  understat: skipped ({e})")

    # the whole remaining season — the fixture-difficulty strip on the Charts
    # page needs every game, not just the next few; next_fixture only ever
    # needs the first entry regardless
    upcoming = fpl["upcoming"]
    next_fixture = dict(upcoming[0]) if upcoming else None

    # ---- league-wide comparison data (Understat league page) -------------- #
    league_teams, league_players, ips_history = {}, [], []
    try:
        league_teams, league_players, ips_history = fetch_understat_league()
        print(f"  understat league: {len(league_teams)} teams, {len(league_players)} players, "
              f"{len(ips_history)} Ipswich matches")
    except Exception as e:
        print(f"  understat league: skipped ({e})")

    fbd_stats, home_table, away_table, league_form = [], [], [], {}
    try:
        fbd_stats = fetch_match_stats(fbd_rows)
        home_table, away_table, league_form = fetch_league_tables(fbd_rows)
        print(f"  match stats (football-data fallback): {len(fbd_stats)} Ipswich matches; "
              f"home/away tables {len(home_table)}/{len(away_table)} clubs")
    except Exception as e:
        print(f"  match stats: skipped ({e})")

    elo_history = []
    try:
        elo_history = fetch_elo_history()
        print(f"  elo history: {len(elo_history)} points")
    except Exception as e:
        print(f"  elo history: skipped ({e})")

    # Ipswich's FPL strength ratings as percentiles vs the league (attack/defence, home/away)
    STR_KEYS = [("strength_attack_home", "Attack home"), ("strength_attack_away", "Attack away"),
                ("strength_defence_home", "Defence home"), ("strength_defence_away", "Defence away"),
                ("strength_overall_home", "Overall home"), ("strength_overall_away", "Overall away")]
    team_strength = []
    all_fpl_teams = list(teams.values())
    for key, label in STR_KEYS:
        vals = [t.get(key, 0) for t in all_fpl_teams if t.get(key)]
        v = ipswich.get(key, 0)
        pct = round(sum(1 for x in vals if x <= v) / len(vals) * 100) if vals else 50
        team_strength.append({"label": label, "value": v, "pct": pct})

    # current Elo for every club (reused for next-opponent probability and the sim)
    elos = {}
    try:
        elos = fetch_clubelo_elos()
    except Exception as e:
        print(f"  clubelo: skipped ({e})")

    # Monte Carlo: simulate the rest of the season for survival odds + relegation odds
    survival, releg_odds = None, {}
    try:
        survival, releg_odds = monte_carlo(teams, fpl["all_fixtures"], elos, tid)
        if survival:
            print(f"  monte carlo: survival {survival['survive_pct']}% "
                  f"(avg {survival['avg_points']} pts, ~{survival['avg_position']}th, {survival['sims']} sims)")
    except Exception as e:
        print(f"  monte carlo: skipped ({e})")

    meetings = {}
    try:
        meetings = fetch_h2h_history()
        print(f"  football-data H2H: {sum(len(v) for v in meetings.values())} historical meetings")
    except Exception as e:
        print(f"  football-data H2H: skipped ({e})")

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

    # top scorers / assists — every club, from the Understat league page's
    # per-player data (already fetched above for team_scatter; just unused
    # until now). Same field names fetch_understat() already relies on for
    # Ipswich's own players (player_name/games/time/goals/assists/xG/xA),
    # plus team_title which the league page adds per player.
    top_scorers, top_assists = [], []
    if league_players:
        def leader_row(p, rank):
            title = p.get("team_title", "")
            short, badge = team_meta(title)
            return {"rank": rank, "player": p.get("player_name", "?"),
                    "team": title, "team_short": short, "badge": badge,
                    "games": int(p.get("games", 0) or 0), "minutes": int(p.get("time", 0) or 0),
                    "goals": int(p.get("goals", 0) or 0), "assists": int(p.get("assists", 0) or 0),
                    "xg": to_float(p.get("xG", 0)), "xa": to_float(p.get("xA", 0)),
                    "is_ipswich": TEAM_NAME_MATCH in title.lower()}
        by_goals = sorted(league_players,
                          key=lambda p: (-int(p.get("goals", 0) or 0), -to_float(p.get("xG", 0))))
        by_assists = sorted(league_players,
                            key=lambda p: (-int(p.get("assists", 0) or 0), -to_float(p.get("xA", 0))))
        top_scorers = [leader_row(p, i) for i, p in enumerate(by_goals[:LEADERS_LIMIT], 1)]
        top_assists = [leader_row(p, i) for i, p in enumerate(by_assists[:LEADERS_LIMIT], 1)]
        print(f"  leaders: top {len(top_scorers)} scorers, top {len(top_assists)} assists")

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

    # full underlying-numbers table: every club's actual points (derived the same
    # way from Understat's own match-by-match record, so it needs no join against
    # the ESPN table) next to xG, xGA, npxG, pressing and current Elo, plus how far
    # actual points have drifted from Understat's xPts — the "who's over/under-
    # performing" read a plain points table can't show.
    league_table = []
    for title, agg in league_teams.items():
        short, badge = team_meta(title)
        pts, xpts = agg.get("pts"), agg.get("xpts")
        league_table.append({
            "team": title, "short": short, "badge": badge,
            "is_ipswich": TEAM_NAME_MATCH in title.lower(),
            "played": agg["games"], "points": pts,
            "gf": agg["scored"], "ga": agg["conceded"], "gd": agg["scored"] - agg["conceded"],
            "xg": agg["xg"], "xga": agg["xga"], "npxg": agg["npxg"],
            "xg_pg": agg["xg_pg"], "xga_pg": agg["xga_pg"], "ppda": agg["ppda"],
            "elo": round(elos[canon(title)]) if elos.get(canon(title)) is not None else None,
            "xpts": xpts,
            "xpts_diff": round(pts - xpts, 1) if pts is not None and xpts is not None else None,
        })
    league_table.sort(key=lambda r: (-(r["points"] or 0), -(r["gd"] or 0), -(r["gf"] or 0)))
    for i, r in enumerate(league_table, 1):
        r["rank"] = i

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
        PROFILE_MIN_MINUTES = 450   # league players need a decent sample to be comparable
        for r in rows:
            r["is_ipswich"] = TEAM_NAME_MATCH in r["team"].lower()
            if r["is_ipswich"] or r["minutes"] >= PROFILE_MIN_MINUTES:
                r["pct"] = {k: pctile(r["pos"], k, r["per90"][k]) for k in keys}
                player_profiles.append(r)
        # Ipswich first, then the rest of the league by minutes
        player_profiles.sort(key=lambda r: (not r["is_ipswich"], -r["minutes"]))

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

    # ---- keyless team news / head-to-head / win probability --------------- #
    team_news = fpl["team_news"]
    print(f"  team news (FPL): {len(team_news)} flagged players")

    if next_opponent:
        opp_name = next_opponent["name"]
        home = next_opponent.get("home", True)
        hist = sorted(meetings.get(canon(opp_name), []), key=lambda m: m["date"], reverse=True)[:6]
        if hist:
            next_opponent["h2h"] = hist
            next_opponent["h2h_record"] = {
                "w": sum(m["result"] == "W" for m in hist),
                "d": sum(m["result"] == "D" for m in hist),
                "l": sum(m["result"] == "L" for m in hist)}
        ei, eo = elos.get(canon("Ipswich")), elos.get(canon(opp_name))
        if ei and eo:
            next_opponent["prob"] = win_probs(ei, eo, home)
        # Fallback so the win-probability bar always renders: derive from FPL
        # fixture difficulty when ClubElo gave us nothing.
        if not next_opponent.get("prob") and next_fixture and next_fixture.get("difficulty"):
            next_opponent["prob"] = fdr_win_probs(next_fixture["difficulty"])

    # ---- assemble a full detail page for every finished match ------------ #
    # Shots/SOT/corners/fouls/cards/HT score come from ESPN's play-by-play
    # (fetch_espn_match_events) wherever a match is matched onto an ESPN event;
    # football-data.co.uk's per-match CSV row is only a fallback for matches
    # ESPN hasn't got yet. Best-effort throughout: an empty/unreachable ESPN
    # schedule (e.g. before a season has any finished fixtures) just leaves
    # each page without cards/subs, same as every other optional source.
    match_pages = understat.get("match_pages", [])
    fbd_by_key = {(canon(m["opponent"]), m["home"]): m for m in fbd_stats}
    hist_by_date = {h["date"]: h for h in ips_history}
    ips_badge = badge_for(ipswich["short_name"])
    try:
        espn_events_by_date = fetch_espn_schedule()
    except Exception as e:
        print(f"  ESPN match events: skipped ({e})")
        espn_events_by_date = {}
    if espn_events_by_date:
        os.makedirs(PLAY_CACHE_DIR, exist_ok=True)

    match_stats = []
    espn_matched, espn_fetched = 0, 0
    for mp in match_pages:
        short, _ = team_meta(mp["opponent"])
        mp["opponent_short"] = short
        mp["opponent_badge"] = badge_for(short)
        mp["team_badge"] = ips_badge
        fb = fbd_by_key.get((canon(mp["opponent"]), mp["home"]))

        cards = subs = stats = None
        event_id = espn_events_by_date.get(mp["date"])
        if event_id:
            cache_file = os.path.join(PLAY_CACHE_DIR, f"{event_id}.json")
            if os.path.exists(cache_file):
                try:
                    with open(cache_file) as fh:
                        cards, subs, stats = json.load(fh)
                except (ValueError, OSError):
                    cards = subs = stats = None
            if cards is None:
                try:
                    cards, subs, stats = fetch_espn_match_events(event_id, mp["home"])
                except requests.RequestException:
                    cards = subs = stats = None
                else:
                    try:
                        with open(cache_file, "w") as fh:
                            json.dump([cards, subs, stats], fh)
                    except OSError:
                        pass
                    espn_fetched += 1
            if cards is not None:
                mp["cards"] = cards
                mp["subs"] = subs
                espn_matched += 1

        if stats:
            mp["fbd"] = {k: stats[k] for k in MATCH_STAT_KEYS}
        elif fb:
            mp["fbd"] = {k: fb[k] for k in MATCH_STAT_KEYS}

        # Half-time score: prefer ESPN's/football-data's explicit HT marker, but
        # always fall back to counting first-half goals from Understat's own goal
        # list (minute <= 45) — that's available for every finished match
        # regardless of ESPN/football-data coverage, so the half-time-state chart
        # can't go stale the way relying solely on those sources did.
        ht_for = (stats or {}).get("ht_for")
        ht_against = (stats or {}).get("ht_against")
        if ht_for is None and fb:
            ht_for, ht_against = fb.get("ht_for"), fb.get("ht_against")
        if ht_for is None:
            ht_for = sum(1 for g in mp["goals"] if g["side"] == "for" and g["minute"] <= 45)
            ht_against = sum(1 for g in mp["goals"] if g["side"] == "against" and g["minute"] <= 45)
        mp["ht_score"] = f"{ht_for}-{ht_against}"
        mp["ht_state"] = "ahead" if ht_for > ht_against else "behind" if ht_for < ht_against else "level"

        if mp.get("fbd"):
            match_stats.append({"opponent": mp["opponent"], "home": mp["home"],
                                "result": mp["result"], "ht_state": mp["ht_state"], **mp["fbd"]})

        hh = hist_by_date.get(mp["date"])
        if hh:
            mp.update({"xpts": hh["xpts"], "deep": hh["deep"], "deep_allowed": hh["deep_allowed"],
                       "ppda": hh["ppda"], "ppda_allowed": hh["ppda_allowed"]})
        mp["h2h"] = sorted(meetings.get(canon(mp["opponent"]), []),
                           key=lambda m: m["date"], reverse=True)[:5]
    print(f"  match pages: {len(match_pages)} assembled, {len(match_stats)} with shot/card stats "
          f"({espn_matched} from ESPN, {espn_fetched} freshly fetched)")

    # link each result row to its match page
    mpid_by_key = {(canon(mp["opponent"]), mp["home"]): mp["id"] for mp in match_pages}
    for r in fpl["results"]:
        r["match_id"] = mpid_by_key.get((canon(r["opponent"]), r["home"]))

    # league form (last five) + home/away sub-tables
    for row in (table or []):
        row["form"] = league_form.get(canon(row["team"]), [])
    for tbl in (home_table, away_table):
        for row in tbl:
            short, _ = team_meta(row["team"])
            row["short"] = short
            row["badge"] = badge_for(short)
            row["is_ipswich"] = TEAM_NAME_MATCH in row["team"].lower()

    news = []
    try:
        news = fetch_news()
        print(f"  news: {len(news)} articles from {len(NEWS_FEEDS)} feeds")
    except Exception as e:
        print(f"  news: skipped ({e})")

    # ---- data-source health check ------------------------------------- #
    # Every source fails soft (an empty section rather than a crash), so this
    # summary makes a broken/blank feed obvious in the build log and on the page.
    checks = {
        "FPL squad": bool(fpl["squad"]),
        "FPL fixtures": bool(fpl["fixtures"]),
        "League table": bool(table),
        "Understat matches": bool(understat["matches"]),
        "Understat players": bool(understat["players"]),
        "Match detail": bool(match_pages),
        "Match stats": bool(match_stats),
        "Home/away tables": bool(home_table),
        "Elo (current)": bool(elos),
        "Elo history": bool(elo_history),
        "Survival model": survival is not None,
        "Badges": bool(badge_for(ipswich["short_name"])),
        "News": bool(news),
        "ESPN match events": bool(espn_events_by_date),
        "Top scorers/assists": bool(top_scorers),
    }
    # Pre-season is expected to have no match-derived data; don't flag those.
    preseason = fpl["summary"]["played"] == 0
    match_derived = {"Understat matches", "Match detail", "Match stats",
                     "Home/away tables", "Understat players", "Survival model",
                     "ESPN match events", "Top scorers/assists"}
    missing = [name for name, ok in checks.items()
               if not ok and not (preseason and name in match_derived)]
    health = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "preseason": preseason, "sources": checks, "missing": missing}
    print("  data health: " + ("all sources OK" if not missing
          else f"{len(missing)} source(s) EMPTY -> " + ", ".join(missing)))

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": "2026/27",
        "team": {"id": tid, "name": ipswich["name"], "short_name": ipswich["short_name"],
                 "badge": badge_for(ipswich["short_name"])},
        "current_event": fpl["current"], "next_event": fpl["next"],
        "next_fixture": next_fixture,
        "next_opponent": next_opponent,
        "team_news": team_news,
        "position": position,
        "summary": fpl["summary"],
        "summary_ranks": summary_ranks,
        "table": table or [],
        "team_scatter": team_scatter,
        "team_ranks": team_ranks,
        "top_scorers": top_scorers,
        "top_assists": top_assists,
        "league_table": league_table,
        "player_profiles": player_profiles,
        "by_gameweek": fpl["by_gameweek"],
        "understat_matches": understat["matches"],
        "understat_history": ips_history,
        "match_stats": match_stats,
        "elo_history": elo_history,
        "home_table": home_table, "away_table": away_table,
        "team_strength": team_strength,
        "survival": survival, "releg_odds": releg_odds,
        "shot_maps": understat["shot_maps"],
        "match_pages": match_pages,
        "understat_players": understat["players"][:14],
        "upcoming": upcoming,
        "fixtures": fpl["fixtures"],
        "results": list(reversed(fpl["results"])),
        "squad": fpl["squad"],
        "news": news,
        "health": health,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2))
    print(f"Wrote {OUT} — {ipswich['name']}: {len(data['squad'])} players, "
          f"{fpl['summary']['played']} played, pos {position or '—'}.")


if __name__ == "__main__":
    main()
