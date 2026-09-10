"""Throwaway diagnostic — see probe.yml. Final detail pass on FotMob's
matchDetails shape before implementing: full team-stats list, a goal
scorer's playerStats entry, team-level lineup fields (minus the noisy
starters list), subs shape, and h2h/weather.
"""

import json

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ipswichtown-stats-probe/1.0)"}
MATCH_ID = 1000018674


def get_json(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    print(f"\n=== GET {url} -> {r.status_code} ({len(r.content)} bytes) ===")
    return r.json() if r.status_code == 200 else None


data = get_json(f"https://www.fotmob.com/api/data/matchDetails?matchId={MATCH_ID}")
content = data.get("content") or {}

print("\n--- FULL top_stats stat titles (content.stats) ---")
stats_section = content.get("stats") or {}
top_stats = ((stats_section.get("Periods") or {}).get("All") or {}).get("stats") or []
for group in top_stats:
    print(f"group: {group.get('title')} ({group.get('key')})")
    for s in group.get("stats") or []:
        print(f"  {s.get('title')} ({s.get('key')}): {s.get('stats')}")

lineup = content.get("lineup") or {}
print("\n--- lineup.homeTeam top-level (no starters/subs) ---")
home = lineup.get("homeTeam") or {}
print({k: v for k, v in home.items() if k not in ("starters", "subs")})
print("\n--- lineup.homeTeam.subs[0] full ---")
print(json.dumps((home.get("subs") or [{}])[0], indent=2))
away = lineup.get("awayTeam") or {}
print("\n--- lineup.awayTeam top-level (no starters/subs) ---")
print({k: v for k, v in away.items() if k not in ("starters", "subs")})

# Find Meg Hornby (Ipswich's goal scorer) in lineup + cross-reference playerStats by id.
player_stats = content.get("playerStats") or {}
for p in (home.get("starters") or []) + (home.get("subs") or []):
    if "hornby" in (p.get("name") or "").lower():
        print(f"\n--- Meg Hornby in lineup: id={p.get('id')} ---")
        print(json.dumps(p, indent=2))
        ps = player_stats.get(str(p["id"]))
        print(f"\n--- Meg Hornby in playerStats[{p['id']}] ---")
        print(json.dumps(ps, indent=2))

print("\n--- content.h2h ---")
print(json.dumps(content.get("h2h"), indent=2)[:1500])
print("\n--- content.weather ---")
print(json.dumps(content.get("weather"), indent=2)[:800])
print("\n--- content.matchFacts.playerOfTheMatch top-level ---")
potm = (content.get("matchFacts") or {}).get("playerOfTheMatch") or {}
print({k: v for k, v in potm.items() if k != "stats"})
