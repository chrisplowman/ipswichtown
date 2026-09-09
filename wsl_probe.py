"""Throwaway diagnostic — see git history / PR discussion for context. Confirms
"onField" in the per-player popup-stats feed's seasonStats block really means
minutes played, by checking it across every Ipswich player rather than just one."""

import json

import requests

BASE = "https://gaming.wslfootball.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ipswichtown-stats-probe/1.0)"}
IPSWICH_TEAM_ID = "wpll::Football_Team::9c259ee665104c388ab23a585c5dda18"


def get_json(path):
    url = f"{BASE}{path}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    print(f"GET {path} -> {r.status_code} ({len(r.content)} bytes)")
    return r.json() if r.status_code == 200 else None


players = get_json("/feeds/players/matchday_en_1_1.json?v=3")
player_list = (players.get("Data") or {}).get("Value") or []
ipswich_players = [p for p in player_list if p.get("teamId") == IPSWICH_TEAM_ID]
print(f"\nIpswich players: {len(ipswich_players)}\n")

for p in ipswich_players:
    popup = get_json(f"/feeds/popup/stats/player_en_1_{p['playerId']}.json")
    stats = ((popup or {}).get("Data") or {}).get("Value") or {}
    ss = stats.get("seasonStats") or {}
    name = f"{p.get('mediaFirstName')} {p.get('mediaLastName')}"
    print(f"{name:25s} pos={p.get('skillName'):4s} onField={ss.get('onField')!s:>4} "
          f"onFieldPts={ss.get('onFieldPoints')!s:>4} goals={ss.get('goals')} assists={ss.get('assists')} "
          f"tackles={ss.get('tackles')} totalPoints={ss.get('totalPoints')}")
