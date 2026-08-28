"""
Pull Ipswich Town Women data from free/open sources and write data/itfc_women.json
for build.py's women's-team pages (site/women/).

Sources (all free):
  FotMob        https://www.fotmob.com/api/data/...              table, fixtures, results, squad, crests
  RSS           same feeds as ingest.py's NEWS_FEEDS              news, filtered to women's-team items

TheSportsDB previously turned up nothing for this competition (team, league
and squad all came back empty on a real run) and ESPN doesn't carry WSL2
standings at all (its eng.w.2 slug 400s, and WSL2 isn't listed on espn.com
either) — FotMob is the only free source found so far with real WSL2 data.
It's unofficial: this uses the same undocumented JSON endpoints fotmob.com's
own site calls (https://www.fotmob.com/api/data/{resource}?id={id} — note
that's NOT /api/{resource}, which 404s, and NOT apiv3.fotmob.com, which
doesn't resolve), so the response shapes below are inferred from real
responses rather than a spec, and FotMob is free to reshuffle them without
notice. The extraction functions below therefore search the response for
the first list that *looks* like a standings/fixtures/squad array (by the
keys its entries carry) rather than hard-coding an exact path, so a minor
FotMob change degrades to an empty section instead of a crash.

Treat the first real run as a validation pass — confirm the counts printed
below look right, and check data/itfc_women.json's "health" field for
anything reported missing.

Run:  python ingest_women.py
"""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

from ingest import (
    ATOM, CONTENT, DC, NEWS_FEEDS, SUMMARY_CHARS,
    _get, _item_image, _parse_feed_date, _strip_html, get_json,
)

OUT = Path("data/itfc_women.json")
SEASON_LABEL = "2026/27"
NEWS_KEYWORDS = ("women", "ladies", "wsl")
NEWS_LIMIT = 12

# FotMob's unofficial API — https://www.fotmob.com/api/data/{resource}?id={id}.
# IDs found by searching fotmob.com and reading them off the team/league URLs:
#   https://www.fotmob.com/en-GB/teams/1134184/overview/ipswich-town-wfc
#   https://www.fotmob.com/en-GB/leagues/9294/overview/wsl-2
# Ipswich also play in FotMob league 9717 ("Women's League Cup") — deliberately
# ignored here so this stays scoped to the WSL2 table/fixtures the site is
# built around, matching the "Barclays Women's Super League 2" framing below.
FOTMOB_BASE = "https://www.fotmob.com/api/data"
FOTMOB_LEAGUE_ID = 9294
FOTMOB_TEAM_ID = 1134184

POS_BY_GROUP = {"keepers": "GKP", "defenders": "DEF", "midfielders": "MID", "attackers": "FWD"}
POS_MAP = {"keeper": "GKP", "defender": "DEF", "midfielder": "MID",
           "attacker": "FWD", "forward": "FWD", "winger": "FWD"}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _team_badge(team_id):
    return f"https://images.fotmob.com/image_resources/logo/teamlogo/{team_id}.png" if team_id else None


def fetch_fotmob_league():
    return get_json(f"{FOTMOB_BASE}/leagues?id={FOTMOB_LEAGUE_ID}")


def fetch_fotmob_team():
    return get_json(f"{FOTMOB_BASE}/teams?id={FOTMOB_TEAM_ID}")


def _find_list(node, looks_like):
    """Depth-first search for the first list whose dict entries all satisfy
    `looks_like` — used instead of a hard-coded path into FotMob's response so
    a nesting change there degrades to an empty result instead of a crash."""
    if isinstance(node, list):
        if node and all(isinstance(x, dict) and looks_like(x) for x in node):
            return node
        for item in node:
            found = _find_list(item, looks_like)
            if found:
                return found
    elif isinstance(node, dict):
        for v in node.values():
            found = _find_list(v, looks_like)
            if found:
                return found
    return None


def parse_table(league_json):
    rows = _find_list(league_json, lambda x: "pts" in x and "played" in x) or []
    out = []
    for i, r in enumerate(rows, start=1):
        name = r.get("name") or r.get("shortName") or ""
        scores = (r.get("scoresStr") or "").split("-")
        gf = int(scores[0]) if len(scores) == 2 and scores[0].strip().lstrip("-").isdigit() else 0
        ga = int(scores[1]) if len(scores) == 2 and scores[1].strip().isdigit() else 0
        gd = r.get("goalConDiff")
        out.append({
            "rank": r.get("idx") or i, "team": name, "badge": _team_badge(r.get("id")),
            "played": r.get("played") or 0, "won": r.get("wins") or 0, "drawn": r.get("draws") or 0,
            "lost": r.get("losses") or 0, "gf": gf, "ga": ga,
            "gd": gd if gd is not None else gf - ga, "points": r.get("pts") or 0,
            "form": [(m.get("resultString") or "").upper() for m in (r.get("form") or [])][-5:],
            "is_ipswich": "ipswich" in _norm(name),
        })
    out.sort(key=lambda x: x["rank"])
    return out


def parse_fixtures(league_json):
    """Full season's matches for the league, split into finished results and
    upcoming fixtures for whichever rows involve Ipswich."""
    matches = _find_list(league_json, lambda x: "status" in x and "home" in x and "away" in x) or []
    results, upcoming = [], []
    for m in matches:
        home, away = m.get("home") or {}, m.get("away") or {}
        home_name, away_name = home.get("name") or "", away.get("name") or ""
        is_home, is_away = "ipswich" in _norm(home_name), "ipswich" in _norm(away_name)
        if not (is_home or is_away):
            continue
        opponent = away_name if is_home else home_name
        opponent_id = (away if is_home else home).get("id")
        status = m.get("status") or {}
        if status.get("cancelled"):
            continue
        try:
            round_num = int(m.get("round"))
        except (TypeError, ValueError):
            round_num = None
        base = {"event": round_num, "opponent": opponent, "opponent_short": opponent[:3].upper(),
                "home": is_home}
        if status.get("finished"):
            hs, as_ = home.get("score"), away.get("score")
            if hs is None or as_ is None:
                parts = (status.get("scoreStr") or "").split("-")
                hs = int(parts[0]) if len(parts) == 2 and parts[0].strip().lstrip("-").isdigit() else None
                as_ = int(parts[1]) if len(parts) == 2 and parts[1].strip().isdigit() else None
            if hs is None or as_ is None:
                continue
            our, their = (hs, as_) if is_home else (as_, hs)
            result = "W" if our > their else "L" if our < their else "D"
            results.append(dict(base, score=f"{our}-{their}", result=result,
                                 date=(status.get("utcTime") or "")[:10],
                                 opponent_badge=_team_badge(opponent_id)))
        else:
            upcoming.append(dict(base, kickoff=status.get("utcTime"), opponent_id=opponent_id))
    results.sort(key=lambda x: x["date"], reverse=True)   # most recent first
    upcoming.sort(key=lambda x: x.get("kickoff") or "")
    return results, upcoming


def _pos_from_code(desc):
    """FotMob's positionIdsDesc is a comma list like "CM,CDM,CAM" (multiple
    positions a player covers) — take the first and bucket it the same
    coarse way as POS_BY_GROUP."""
    code = (desc or "").split(",")[0].strip().upper()
    if code == "GK":
        return "GKP"
    if code.endswith("B"):
        return "DEF"
    if code in ("ST", "CF") or code.endswith("W"):
        return "FWD"
    return "MID" if code else None


def _map_player(p, pos):
    if pos is None:
        role = p.get("role") or {}
        role_text = f"{role.get('key') or ''} {role.get('fallback') or ''}".lower()
        pos = _pos_from_code(p.get("positionIdsDesc")) or \
            next((v for k, v in POS_MAP.items() if k in role_text), "MID")
    full_name = p.get("name") or ""
    return {"name": full_name.split()[-1] if full_name else "", "full_name": full_name, "pos": pos,
            "apps": p.get("matchesPlayed"), "goals": p.get("goals"), "assists": p.get("assists")}


def parse_squad(team_json):
    """FotMob nests the real squad list two levels down: team_json["squad"]
    is itself a dict ({"squad": [...], "isNationalTeam": ...}), and each
    entry in that inner list is a position group ({"title": "keepers",
    "members": [...]}) — including a non-playing "coach" group, which is
    dropped here rather than shown as a player."""
    squad_field = team_json.get("squad")
    if isinstance(squad_field, dict):
        groups = squad_field.get("squad") or []
    elif isinstance(squad_field, list):
        groups = squad_field
    else:
        groups = []

    squad = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        title = (g.get("title") or "").lower()
        if title == "coach":
            continue
        pos = POS_BY_GROUP.get(title)
        for p in g.get("members") or []:
            squad.append(_map_player(p, pos))
    if squad:
        return squad

    # FotMob reshuffled the nesting — fall back to a generic search for a
    # flat list of player-shaped dicts anywhere in the response.
    members = _find_list(team_json, lambda x: "shirtNumber" in x and "name" in x) or []
    return [_map_player(p, None) for p in members if (p.get("role") or {}).get("key") != "coach"]


def fetch_women_news():
    """Reuses ingest.py's Ipswich-wide RSS feeds (they cover the whole club,
    not just the men's team) and keeps only women's-team-tagged articles."""
    items = []
    for source, url in NEWS_FEEDS:
        try:
            root = ET.fromstring(_get(url).content)
        except (requests.RequestException, ET.ParseError, ValueError):
            continue
        entries = root.findall(".//item") or root.findall(f".//{ATOM}entry")
        for e in entries:
            title = (e.findtext("title") or e.findtext(f"{ATOM}title") or "").strip()
            if not any(k in title.lower() for k in NEWS_KEYWORDS):
                continue
            link = (e.findtext("link") or "").strip()
            if not link:
                a = e.find(f"{ATOM}link")
                link = a.get("href", "").strip() if a is not None else ""
            if not link.startswith(("http://", "https://")):
                continue
            dt = _parse_feed_date(e.findtext("pubDate") or e.findtext(f"{ATOM}updated")
                                   or e.findtext(f"{DC}date"))
            desc_raw = (e.findtext("description") or e.findtext(f"{CONTENT}encoded")
                        or e.findtext(f"{ATOM}summary") or e.findtext(f"{ATOM}content") or "")
            items.append({"title": title, "link": link, "source": source,
                          "date": dt.isoformat() if dt else "",
                          "date_display": dt.strftime("%-d %b") if dt else "",
                          "image": _item_image(e, desc_raw),
                          "summary": _strip_html(desc_raw)[:SUMMARY_CHARS].strip()})
    items.sort(key=lambda x: x["date"], reverse=True)
    seen, out = set(), []
    for it in items:
        if it["link"] not in seen:
            seen.add(it["link"])
            out.append(it)
    return out[:NEWS_LIMIT]


def main():
    missing = []

    league_json = None
    try:
        league_json = fetch_fotmob_league()
        print("  fotmob league: fetched")
    except Exception as e:
        print(f"  fotmob league: skipped ({e})")

    team_json = None
    try:
        team_json = fetch_fotmob_team()
        print("  fotmob team: fetched")
    except Exception as e:
        print(f"  fotmob team: skipped ({e})")

    league_name = ((league_json or {}).get("details") or {}).get("name") \
        or "Barclays Women's Super League 2"
    team_badge = _team_badge(FOTMOB_TEAM_ID)

    table = []
    try:
        table = parse_table(league_json) if league_json else []
        print(f"  table: {len(table)} teams")
    except Exception as e:
        print(f"  table: skipped ({e})")
    if not table:
        missing.append("league table")

    results, upcoming = [], []
    try:
        results, upcoming = parse_fixtures(league_json) if league_json else ([], [])
        print(f"  fixtures: {len(results)} results, {len(upcoming)} upcoming")
    except Exception as e:
        print(f"  fixtures: skipped ({e})")
    if not results and not upcoming:
        missing.append("fixtures & results")

    squad = []
    try:
        squad = parse_squad(team_json) if team_json else []
        print(f"  squad: {len(squad)} players")
    except Exception as e:
        print(f"  squad: skipped ({e})")
    if not squad:
        missing.append("squad")

    news = []
    try:
        news = fetch_women_news()
        print(f"  news: {len(news)} articles")
    except Exception as e:
        print(f"  news: skipped ({e})")

    ips_row = next((r for r in table if r["is_ipswich"]), None)
    position = ips_row["rank"] if ips_row else None
    summary = ({"played": ips_row["played"], "won": ips_row["won"], "drawn": ips_row["drawn"],
               "lost": ips_row["lost"], "gf": ips_row["gf"], "ga": ips_row["ga"],
               "gd": ips_row["gd"], "points": ips_row["points"]} if ips_row else
              {"played": len(results), "won": sum(r["result"] == "W" for r in results),
               "drawn": sum(r["result"] == "D" for r in results),
               "lost": sum(r["result"] == "L" for r in results),
               "gf": sum(int(r["score"].split("-")[0]) for r in results),
               "ga": sum(int(r["score"].split("-")[1]) for r in results), "gd": 0,
               "points": sum(r["result"] == "W" for r in results) * 3
                         + sum(r["result"] == "D" for r in results)})
    summary["gd"] = summary["gf"] - summary["ga"]

    summary_text = None
    if summary["played"]:
        summary_text = (f"Ipswich Town Women sit {position or '—'}{'th' if position else ''} in "
                        f"{league_name} after {summary['played']} matches, with {summary['won']} wins, "
                        f"{summary['drawn']} draws and {summary['lost']} defeats.")

    next_fixture = None
    if upcoming:
        next_fixture = dict(upcoming[0])
        next_fixture["badge"] = _team_badge(next_fixture.pop("opponent_id", None))
    upcoming = [{k: v for k, v in u.items() if k != "opponent_id"} for u in upcoming]

    data = {
        "season": SEASON_LABEL, "league_name": league_name,
        "team": {"short_name": "Ipswich", "badge": team_badge},
        "position": position, "summary": summary, "summary_text": summary_text,
        "next_fixture": next_fixture,
        "results": results, "upcoming": upcoming, "table": table, "squad": squad, "news": news,
        "health": {"missing": missing},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=None))
    print(f"Wrote {OUT} ({len(table)} table rows, {len(results)} results, {len(squad)} players, "
          f"{len(news)} news items).")


if __name__ == "__main__":
    main()
