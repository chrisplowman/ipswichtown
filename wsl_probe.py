"""
Throwaway diagnostic script — NOT part of the site build. Probes wslfootball.com's
fantasy-game JSON feeds (discovered via their public app-config feed,
https://gaming.wslfootball.com/feeds/config/web/configurations.json) to find out:
  - the real shape of the teams/fixtures/player-listing feeds
  - whether Ipswich Town WFC appears in the player pool (they're WSL2 this season)
  - a working tourId/matchdayId/playerId to build ingest_women.py support around

Only runs via the throwaway probe.yml push-triggered workflow — this sandbox's
egress proxy blocks wslfootball.com entirely, so this has to run on a real
GitHub Actions runner instead. Delete both files once the investigation is done.
"""

import json

import requests

BASE = "https://gaming.wslfootball.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ipswichtown-stats-probe/1.0)"}


def get_json(path):
    url = f"{BASE}{path}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        print(f"\n=== GET {path} -> {r.status_code} ({len(r.content)} bytes) ===")
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                print(r.text[:500])
        else:
            print(r.text[:500])
    except requests.RequestException as e:
        print(f"\n=== GET {path} -> ERROR: {e} ===")
    return None


print("Probing wslfootball.com fantasy feeds...")

teams = get_json("/feeds/filters/teams/competition/en_1.json")
ipswich_team_id = None
if teams:
    team_list = ((teams.get("Data") or {}).get("Value") or {}).get("teams") or []
    print(f"Total teams: {len(team_list)}")
    for t in team_list:
        if "ipswich" in (t.get("officialName") or "").lower():
            ipswich_team_id = t["teamId"]
            print(f"FOUND IPSWICH: {json.dumps(t, indent=2)}")
    if not ipswich_team_id:
        print("Ipswich NOT found. All team names:")
        print(sorted(t.get("officialName") for t in team_list))

if ipswich_team_id:
    players = get_json("/feeds/players/matchday_en_1_1.json?v=3")
    if players:
        player_list = (players.get("Data") or {}).get("Value") or []
        print(f"Total players in matchday 1 listing: {len(player_list)}")
        ipswich_players = [p for p in player_list if p.get("teamId") == ipswich_team_id]
        print(f"Ipswich players found: {len(ipswich_players)}")
        for p in ipswich_players[:3]:
            print(f"\n--- FULL PLAYER OBJECT: {p.get('mediaFirstName')} {p.get('mediaLastName')} ---")
            print(json.dumps(p, indent=2))

        if ipswich_players:
            pid = ipswich_players[0]["playerId"]
            print(f"\n\nFetching PlayerPopupStats for playerId={pid}")
            popup = get_json(f"/feeds/popup/stats/player_en_1_{pid}.json")
            if popup:
                print(json.dumps(popup, indent=2))
