import json
import requests

r = requests.get("https://chrisplowman.github.io/ipswichtown/women/data.json", timeout=20)
r.raise_for_status()
data = r.json()

match_pages = data.get("match_pages") or []
print("match_pages:", len(match_pages))
for mp in match_pages:
    print("---", mp.get("slug"), mp.get("opponent"), mp.get("date"))
    print("starters:", len(mp.get("starters") or []))
    print("opponent_starters:", len(mp.get("opponent_starters") or []))
    for p in (mp.get("starters") or [])[:3]:
        print("  ips:", p.get("name"), p.get("x"), p.get("y"))
    for p in (mp.get("opponent_starters") or [])[:3]:
        print("  opp:", p.get("name"), p.get("x"), p.get("y"))
    print("team_stats:", mp.get("team_stats"))
