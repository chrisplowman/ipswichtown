import json
import requests

r = requests.get("https://www.fotmob.com/api/data/leagues?id=47",
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
r.raise_for_status()
league = r.json()
stats = league.get("stats") or {}

team_cats = {s["name"]: s for s in stats.get("teams") or [] if s.get("name")}

# Fetch the FULL list for rating_team (already in production) and one new
# category (fk_foul_lost_team) to confirm the real StatList field names/casing
# for TEAM entries specifically (never actually verified against live data —
# only assumed to match player entries' TeamId/Rank/StatValue casing).
for name in ("rating_team", "fk_foul_lost_team", "total_yel_card_team"):
    cat = team_cats.get(name)
    if not cat or not cat.get("fetchAllUrl"):
        print(name, "NOT FOUND in league payload")
        continue
    resp = requests.get(cat["fetchAllUrl"], headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    data = resp.json()
    top_lists = data.get("TopLists") or []
    stat_list = (top_lists[0].get("StatList") or []) if top_lists else []
    print(f"=== {name} ({cat.get('header')}) — {len(stat_list)} entries ===")
    if stat_list:
        print(json.dumps(stat_list[0], indent=2))
        ipswich = next((t for t in stat_list if t.get("TeamId") == 9902 or t.get("teamId") == 9902), None)
        print("ipswich entry:", json.dumps(ipswich))
    print()
