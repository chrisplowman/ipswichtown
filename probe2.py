"""Throwaway diagnostic — see probe.yml. Dumps the structure of FotMob's
matchDetails endpoint for the Ipswich Women v Nottingham Forest match, to see
what's available (opposing lineup? match stats? shot map/xG?) beyond what the
women's site currently pulls from the team endpoint's lastLineupStats.
"""

import json

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ipswichtown-stats-probe/1.0)"}
MATCH_ID = 1000018674


def get_json(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    print(f"\n=== GET {url} -> {r.status_code} ({len(r.content)} bytes) ===")
    return r.json() if r.status_code == 200 else None


def walk_keys(d, prefix="", max_depth=3, depth=0):
    if depth > max_depth or not isinstance(d, dict):
        return
    for k, v in d.items():
        shape = ("dict" if isinstance(v, dict) else "list[%d]" % len(v) if isinstance(v, list) else type(v).__name__)
        print(f"{prefix}{k}: {shape}")
        if isinstance(v, dict):
            walk_keys(v, prefix + "  ", max_depth, depth + 1)
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            print(f"{prefix}  [0]:")
            walk_keys(v[0], prefix + "    ", max_depth, depth + 1)


data = get_json(f"https://www.fotmob.com/api/data/matchDetails?matchId={MATCH_ID}")
if data:
    print("\n--- top-level structure (depth 3) ---")
    walk_keys(data, max_depth=3)

    content = data.get("content") or {}
    print("\n--- content keys ---")
    print(sorted(content.keys()))

    for section in ("stats", "lineup", "shotmap", "matchFacts", "playerStats", "liveticker", "insights"):
        sec = content.get(section)
        print(f"\n--- content.{section} ({'present' if sec is not None else 'ABSENT'}) ---")
        if sec is not None:
            print(json.dumps(sec, indent=2)[:2500])

    general = data.get("general") or {}
    print("\n--- general ---")
    print(json.dumps(general, indent=2)[:1500])
