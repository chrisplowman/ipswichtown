"""
Pull Ipswich Town data from the (keyless) Fantasy Premier League API and write
a clean data/itfc.json that build.py renders into the static page.

Sources (no API key required):
  - https://fantasy.premierleague.com/api/bootstrap-static/   (teams, players, gameweeks)
  - https://fantasy.premierleague.com/api/fixtures/            (fixtures + FPL difficulty)

Run:  python ingest.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://fantasy.premierleague.com/api"
TEAM_NAME_MATCH = "ipswich"          # matched case-insensitively against team names
OUT = Path("data/itfc.json")
TIMEOUT = 30
HEADERS = {"User-Agent": "itfc-stats/1.0 (+github pages reference page)"}


def get(path):
    r = requests.get(f"{BASE}/{path}", headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def to_float(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


def main():
    boot = get("bootstrap-static/")
    fixtures = get("fixtures/")

    teams = {t["id"]: t for t in boot["teams"]}
    positions = {p["id"]: p["singular_name_short"] for p in boot["element_types"]}

    # Find Ipswich's team id by name (robust to id changes season to season).
    ipswich = next(
        (t for t in boot["teams"] if TEAM_NAME_MATCH in t["name"].lower()), None
    )
    if not ipswich:
        sys.exit(
            "Ipswich Town not found in the current FPL data — are they in the "
            "Premier League this season? (No top-flight data = nothing to build.)"
        )
    tid = ipswich["id"]

    # Map every player to their team id — needed to aggregate per-gameweek xG
    # (for Ipswich) and xG-against (for that week's opponent) from the live feed.
    player_team = {p["id"]: p["team"] for p in boot["elements"]}

    # Gameweek pointers
    current = next((e["id"] for e in boot["events"] if e["is_current"]), None)
    nxt = next((e["id"] for e in boot["events"] if e["is_next"]), None)

    # --- Fixtures & results -------------------------------------------------
    upcoming, results = [], []
    finished_meta = []  # per finished match, for the gameweek time series
    won = drawn = lost = gf = ga = 0

    club_fixtures = [f for f in fixtures if tid in (f["team_h"], f["team_a"])]
    club_fixtures.sort(key=lambda f: (f["event"] or 999, f["kickoff_time"] or ""))

    for f in club_fixtures:
        home = f["team_h"] == tid
        opp_id = f["team_a"] if home else f["team_h"]
        opp = teams[opp_id]
        difficulty = f["team_h_difficulty"] if home else f["team_a_difficulty"]

        if f["finished"] and f["team_h_score"] is not None:
            our = f["team_h_score"] if home else f["team_a_score"]
            their = f["team_a_score"] if home else f["team_h_score"]
            gf += our
            ga += their
            if our > their:
                res = "W"
                won += 1
            elif our < their:
                res = "L"
                lost += 1
            else:
                res = "D"
                drawn += 1
            results.append(
                {
                    "event": f["event"],
                    "opponent": opp["name"],
                    "opponent_short": opp["short_name"],
                    "home": home,
                    "score": f"{our}-{their}",
                    "result": res,
                }
            )
            finished_meta.append(
                {
                    "gw": f["event"],
                    "gf": our,
                    "ga": their,
                    "pts": 3 if res == "W" else 1 if res == "D" else 0,
                    "opp_id": opp_id,
                }
            )
        else:
            upcoming.append(
                {
                    "event": f["event"],
                    "opponent": opp["name"],
                    "opponent_short": opp["short_name"],
                    "home": home,
                    "kickoff": f["kickoff_time"],
                    "difficulty": difficulty,
                }
            )

    played = won + drawn + lost
    summary = {
        "played": played,
        "won": won,
        "drawn": drawn,
        "lost": lost,
        "gf": gf,
        "ga": ga,
        "gd": gf - ga,
        "points": won * 3 + drawn,
    }

    # --- Per-gameweek time series (for the trend charts) --------------------
    # Points/goals come from the fixtures; per-week xG and xG-against are
    # aggregated from each gameweek's live feed (one call per finished GW).
    finished_meta.sort(key=lambda m: m["gw"])
    by_gameweek = []
    cum = 0
    for m in finished_meta:
        cum += m["pts"]
        rec = {
            "gw": m["gw"],
            "gf": m["gf"],
            "ga": m["ga"],
            "pts": m["pts"],
            "cum_points": cum,
            "team_xg": None,
            "team_xga": None,
        }
        try:
            live = get(f"event/{m['gw']}/live/")
            xg_for = xg_against = 0.0
            for el in live.get("elements", []):
                team = player_team.get(el["id"])
                exg = to_float(el.get("stats", {}).get("expected_goals", 0))
                if team == tid:
                    xg_for += exg
                elif team == m["opp_id"]:
                    xg_against += exg
            rec["team_xg"] = round(xg_for, 2)
            rec["team_xga"] = round(xg_against, 2)
        except requests.RequestException:
            pass  # leave xG null for this GW; charts skip nulls gracefully
        by_gameweek.append(rec)

    # --- Squad --------------------------------------------------------------
    squad = []
    for p in boot["elements"]:
        if p["team"] != tid:
            continue
        squad.append(
            {
                "name": p["web_name"],
                "full_name": f"{p['first_name']} {p['second_name']}".strip(),
                "pos": positions.get(p["element_type"], "?"),
                "pos_id": p["element_type"],
                "price": round(p["now_cost"] / 10, 1),
                "points": p["total_points"],
                "form": to_float(p["form"]),
                "minutes": p["minutes"],
                "starts": p.get("starts", 0),
                "goals": p["goals_scored"],
                "assists": p["assists"],
                "xg": to_float(p["expected_goals"]),
                "xa": to_float(p["expected_assists"]),
                "xgi": to_float(p["expected_goal_involvements"]),
                "clean_sheets": p["clean_sheets"],
                "selected": to_float(p["selected_by_percent"]),
            }
        )
    # Sort by points desc, then minutes desc — most relevant players first.
    squad.sort(key=lambda x: (-x["points"], -x["minutes"]))

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": "2026/27",
        "team": {
            "id": tid,
            "name": ipswich["name"],
            "short_name": ipswich["short_name"],
        },
        "current_event": current,
        "next_event": nxt,
        "next_fixture": upcoming[0] if upcoming else None,
        "summary": summary,
        "by_gameweek": by_gameweek,
        "upcoming": upcoming[:8],
        "results": list(reversed(results))[:10],  # most recent first
        "squad": squad,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2))
    print(
        f"Wrote {OUT} — {ipswich['name']} (id {tid}): "
        f"{len(squad)} players, {played} played, {len(upcoming)} upcoming."
    )


if __name__ == "__main__":
    main()
