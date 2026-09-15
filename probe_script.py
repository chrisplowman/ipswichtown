import json
import re
import requests

r = requests.get("https://www.fotmob.com/api/data/leagues?id=47",
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
r.raise_for_status()
league = r.json()


def find_ipswich(node, path=""):
    hits = []
    if isinstance(node, dict):
        if node.get("name") == "Ipswich Town" or node.get("TeamName") == "Ipswich Town" \
           or node.get("teamName") == "Ipswich Town" or node.get("Name") == "Ipswich Town":
            hits.append((path, node))
        for k, v in node.items():
            hits += find_ipswich(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            hits += find_ipswich(v, f"{path}[{i}]")
    return hits


hits = find_ipswich(league)
print(f"found {len(hits)} hits")
for path, node in hits[:5]:
    print(path, "->", json.dumps(node)[:300])

# season id extraction from any player-category fetchAllUrl
stats = league.get("stats") or {}
sample = (stats.get("players") or [{}])[0]
url = sample.get("fetchAllUrl", "")
m = re.search(r"/season/(\d+)/", url)
print("season id from fetchAllUrl:", m.group(1) if m else None)

# defensive_contributions leader + participant shape, to check if it also
# includes Ipswich players at all (spot check a mid-table-ish category)
dc = next((s for s in stats.get("players") or [] if s.get("name") == "defensive_contributions"), None)
print("defensive_contributions fetchAllUrl:", dc.get("fetchAllUrl") if dc else None)
