import json
import requests

r = requests.get("https://www.fotmob.com/api/data/leagues?id=47",
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
r.raise_for_status()
league = r.json()
stats = league.get("stats") or {}

print("=== stats top-level keys ===")
print(list(stats.keys()))

print("=== seasonStatLinks (full) ===")
print(json.dumps(stats.get("seasonStatLinks"), indent=2)[:6000])

print("=== stats.players[0] (full, one category) ===")
print(json.dumps((stats.get("players") or [None])[0], indent=2)[:4000])

print("=== stats.teams[0] (full, one category) ===")
print(json.dumps((stats.get("teams") or [None])[0], indent=2)[:4000])

print("=== how many player-stat categories / team-stat categories ===")
print("players:", len(stats.get("players") or []))
print("teams:", len(stats.get("teams") or []))
