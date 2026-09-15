import json
import requests

r = requests.get("https://www.fotmob.com/api/data/leagues?id=47",
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
r.raise_for_status()
league = r.json()
stats = league.get("stats") or {}

print("=== player stat categories (name : header) ===")
for s in stats.get("players") or []:
    print(f"{s.get('name')} | {s.get('header')} | order={s.get('order')} | category={s.get('category')}")

print()
print("=== team stat categories (name : header) ===")
for s in stats.get("teams") or []:
    print(f"{s.get('name')} | {s.get('header')} | order={s.get('order')} | category={s.get('category')}")

print()
print("=== one fetchAllUrl example (players, goals) ===")
goals = next((s for s in stats.get("players") or [] if s.get("name") == "goals"), None)
print(goals.get("fetchAllUrl") if goals else None)

print()
print("=== a couple of interesting-sounding categories, participant only ===")
for want in ("expected_goals", "big_chance_created", "tackle_won", "accurate_pass",
             "interception", "clearance", "saves", "goals_prevented", "duel_won",
             "dribble_won", "rating"):
    hit = next((s for s in stats.get("players") or [] if s.get("name") == want), None)
    if hit:
        p = hit.get("participant") or {}
        print(f"{want}: leader={p.get('name')} value={p.get('value')} fetchAllUrl={hit.get('fetchAllUrl')}")
    else:
        print(f"{want}: NOT FOUND")
