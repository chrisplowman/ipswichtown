"""
Throwaway diagnostic script — NOT part of the site build. Probes wslfootball.com's
fantasy-game JSON feeds (discovered via their public app-config feed,
https://gaming.wslfootball.com/feeds/config/web/configurations.json) to find out:
  - the real shape of the teams/fixtures/player-listing feeds
  - whether Ipswich Town WFC appears in the player pool (they're WSL2 this season)
  - a working tourId/matchdayId/playerId to build ingest_women.py support around

Only runs via the one-off probe.yml workflow_dispatch workflow — this sandbox's
egress proxy blocks wslfootball.com entirely, so this has to run on a real
GitHub Actions runner instead. Delete both files once the investigation is done.
"""

import json

import requests

BASE = "https://gaming.wslfootball.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ipswichtown-stats-probe/1.0)"}


def get(path):
    url = f"{BASE}{path}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print(f"\n=== GET {path} -> {r.status_code} ({len(r.content)} bytes) ===")
        if r.status_code == 200:
            try:
                data = r.json()
                print(json.dumps(data, indent=2)[:4000])
                return data
            except ValueError:
                print(r.text[:1000])
        else:
            print(r.text[:500])
    except requests.RequestException as e:
        print(f"\n=== GET {path} -> ERROR: {e} ===")
    return None


print("Probing wslfootball.com fantasy feeds...")

get("/feeds/filters/teams/competition/en_1.json")
get("/feeds/tour/details/1.json")
get("/feeds/fixtures/fixtures_en_1.json?v=3")

# matchdayId is unknown — try a small range and see which resolve.
for mid in range(1, 6):
    get(f"/feeds/players/matchday_en_1_{mid}.json?v=3")
