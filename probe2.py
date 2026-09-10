"""Throwaway diagnostic — NOT part of the site build. Investigates what extra
match-level stats FotMob's team endpoint and wslfootball.com's fantasy game
expose, beyond what the women's match report page currently shows, so we can
decide what's worth adding. Delete this file and its probe workflow once done.
"""

import json

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ipswichtown-stats-probe/1.0)"}


def get_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        print(f"\n=== GET {url} -> {r.status_code} ({len(r.content)} bytes) ===")
        if r.status_code == 200:
            return r.json()
        print(r.text[:300])
    except requests.RequestException as e:
        print(f"\n=== GET {url} -> ERROR: {e} ===")
    return None


print("---- FotMob team endpoint ----")
team = get_json("https://www.fotmob.com/api/data/teams?id=1134184")
if team:
    print("Top-level keys:", sorted(team.keys()))
    overview = team.get("overview") or {}
    print("overview keys:", sorted(overview.keys()))
    lls = overview.get("lastLineupStats") or {}
    print("lastLineupStats keys:", sorted(lls.keys()))
    print("lastMatch:", json.dumps(lls.get("lastMatch"), indent=2))
    # Any other match-identifying fields at the top of lastLineupStats?
    for k, v in lls.items():
        if k not in ("starters", "subs", "lastMatch", "coach"):
            print(f"  lastLineupStats.{k} = {json.dumps(v)[:200]}")
    stats = team.get("stats") or {}
    print("stats keys:", sorted(stats.keys()))

    match_id = None
    for key in ("id", "matchId", "leagueMatchId"):
        if lls.get("lastMatch", {}).get(key):
            match_id = lls["lastMatch"][key]
            print(f"Found match id via lastMatch.{key}: {match_id}")
    if not match_id:
        print("No obvious match id found on lastMatch — trying full lastLineupStats dump")
        print(json.dumps(lls, indent=2)[:3000])

if match_id:
    for base in ("https://www.fotmob.com/api/matchDetails",
                 "https://www.fotmob.com/api/data/matchDetails"):
        get_json(f"{base}?matchId={match_id}")

print("\n\n---- WSL Fantasy per-match data ----")
WSL_BASE = "https://gaming.wslfootball.com"
listing = get_json(f"{WSL_BASE}/feeds/players/matchday_en_1_1.json?v=3")
if listing:
    players = (listing.get("Data") or {}).get("Value") or []
    ipswich = [p for p in players if p.get("teamId") == "wpll::Football_Team::9c259ee665104c388ab23a585c5dda18"]
    if ipswich:
        p = ipswich[0]
        print(f"Sample player: {p.get('mediaFirstName')} {p.get('mediaLastName')}")
        print("matches[0] full:", json.dumps(p.get("matches", [{}])[0], indent=2))
        print("upcomingFixtures[0] full:", json.dumps(p.get("upcomingFixtures", [{}])[0], indent=2))

popup = get_json(f"{WSL_BASE}/feeds/popup/stats/player_en_1_wpll::Football_Player::d60a64442b384d0e885d07d3f7f89f25.json")
if popup:
    value = (popup.get("Data") or {}).get("Value") or {}
    print("popup top-level keys:", sorted(value.keys()))
    print("recentForm[0] full:", json.dumps((value.get("recentForm") or [{}])[0], indent=2))
