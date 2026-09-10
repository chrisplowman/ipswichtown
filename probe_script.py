import json
import requests

FOTMOB_BASE = "https://www.fotmob.com/api/data"
FOTMOB_TEAM_ID = 1134184


def get_json(url):
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    return r.json()


team_json = get_json(f"{FOTMOB_BASE}/teams?id={FOTMOB_TEAM_ID}")
lls = ((team_json or {}).get("overview") or {}).get("lastLineupStats") or {}
match_id = (lls.get("lastMatch") or {}).get("matchId")
print("match_id:", match_id)

details = get_json(f"{FOTMOB_BASE}/matchDetails?matchId={match_id}")
content = details.get("content") or {}
lineup = content.get("lineup") or {}
home, away = lineup.get("homeTeam") or {}, lineup.get("awayTeam") or {}
print("home team id/name:", home.get("id"), home.get("name"))
print("away team id/name:", away.get("id"), away.get("name"))


def summarize(label, team):
    starters = team.get("starters") or []
    print(f"--- {label} ({len(starters)} starters) ---")
    for p in starters:
        layout = p.get("horizontalLayout") or p.get("layout") or {}
        print(json.dumps({
            "name": p.get("name"), "pos": p.get("positionStringShort") or p.get("role"),
            "x": layout.get("x"), "y": layout.get("y"),
        }))


summarize("HOME", home)
summarize("AWAY", away)

# dump one raw starter entry fully to check exact field names/shape
if home.get("starters"):
    print("RAW HOME STARTER 0:", json.dumps(home["starters"][0], indent=2)[:2000])
if away.get("starters"):
    print("RAW AWAY STARTER 0:", json.dumps(away["starters"][0], indent=2)[:2000])
