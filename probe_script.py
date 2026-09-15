import json
import requests

for name in ("goals", "expected_goals", "defensive_contributions", "saves", "rating"):
    url = f"https://data.fotmob.com/stats/47/season/36781/{name}.json"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    print(f"=== {name} ({r.status_code}) ===")
    if r.status_code != 200:
        continue
    data = r.json()
    print("type:", type(data).__name__)
    if isinstance(data, dict):
        print("keys:", list(data.keys()))
        arr = data.get("TopLists") or data.get("statList") or None
        print(json.dumps(data, indent=2)[:1500])
    print()
