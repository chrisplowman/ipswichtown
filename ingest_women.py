"""
Pull Ipswich Town Women data from free/open sources and write data/itfc_women.json
for build.py's women's-team pages (site/women/).

Sources (all free):
  TheSportsDB   https://www.thesportsdb.com/api/v1/json/3/...   table, fixtures, squad, badges
  RSS           same feeds as ingest.py's NEWS_FEEDS              news, filtered to women's-team items

TheSportsDB's women's-football coverage is community-contributed and much
thinner than the men's Premier League, so team/league names, IDs and even
whether a competition is indexed at all can't be assumed — this searches by
name at each step and degrades gracefully (empty section, not a crash) if
something isn't found. No free source exists for shot-level/xG data for
WSL2, so this intentionally has no equivalent to ingest.py's Understat/
ClubElo/football-data.co.uk sections — see templates/women.html.j2's footer.

This has not been run against the live APIs (no network access in the
environment it was written in) — the field names below follow TheSportsDB's
documented v1 schema, but treat the first real run as a validation pass, not
a formality. Watch for: wrong league/team match (name search picking the
wrong entry), and TheSportsDB simply not carrying WSL2 at all, in which case
`table`/`squad` will legitimately come back empty and the site falls back to
its "unavailable" messaging.

Run:  python ingest_women.py
"""

import re
from datetime import datetime, timezone
from pathlib import Path

from ingest import (
    ATOM, CONTENT, DC, NEWS_FEEDS, SUMMARY_CHARS,
    _get, _item_image, _parse_feed_date, _strip_html, get_json,
)
import json
import xml.etree.ElementTree as ET

import requests

OUT = Path("data/itfc_women.json")
SEASON_LABEL = "2026/27"
TSDB_SEASON = "2026-2027"          # TheSportsDB's season-string format
TEAM_NAME_CANDIDATES = ["Ipswich Town Women", "Ipswich Town Ladies"]
NEWS_KEYWORDS = ("women", "ladies", "wsl")
NEWS_LIMIT = 12


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_team():
    """Search TheSportsDB for the club under a few plausible name spellings.
    Returns the raw team dict, or None if nothing matches."""
    for name in TEAM_NAME_CANDIDATES:
        try:
            j = get_json("https://www.thesportsdb.com/api/v1/json/3/searchteams.php"
                         f"?t={name.replace(' ', '%20')}")
        except (requests.RequestException, ValueError):
            continue
        for t in (j.get("teams") or []):
            if "ipswich" in _norm(t.get("strTeam", "")):
                return t
    return None


def find_league(country="England"):
    """Search TheSportsDB's English leagues for whichever name WSL2 is
    currently indexed under there (it has been renamed more than once)."""
    try:
        j = get_json(f"https://www.thesportsdb.com/api/v1/json/3/search_all_leagues.php?c={country}")
    except (requests.RequestException, ValueError):
        return None
    for lg in (j.get("countries") or []):
        name = (lg.get("strLeague") or "").lower()
        if "women" in name and ("super league 2" in name or "championship" in name):
            return lg
    return None


def fetch_table(league_id):
    if not league_id:
        return []
    try:
        j = get_json("https://www.thesportsdb.com/api/v1/json/3/lookuptable.php"
                     f"?l={league_id}&s={TSDB_SEASON}")
    except (requests.RequestException, ValueError):
        return []
    out = []
    for r in (j.get("table") or []):
        name = r.get("strTeam", "")
        out.append({
            "rank": int(r.get("intRank") or 0), "team": name, "badge": r.get("strBadge"),
            "played": int(r.get("intPlayed") or 0), "won": int(r.get("intWin") or 0),
            "drawn": int(r.get("intDraw") or 0), "lost": int(r.get("intLoss") or 0),
            "gf": int(r.get("intGoalsFor") or 0), "ga": int(r.get("intGoalsAgainst") or 0),
            "gd": int(r.get("intGoalDifference") or 0), "points": int(r.get("intPoints") or 0),
            "form": list((r.get("strForm") or "").upper())[-5:],
            "is_ipswich": "ipswich" in _norm(name),
        })
    out.sort(key=lambda x: x["rank"])
    return out


def fetch_fixtures(league_id):
    """Full season's events for the league; split into finished results and
    upcoming fixtures for whichever rows involve Ipswich."""
    if not league_id:
        return [], []
    try:
        j = get_json("https://www.thesportsdb.com/api/v1/json/3/eventsseason.php"
                     f"?id={league_id}&s={TSDB_SEASON}")
    except (requests.RequestException, ValueError):
        return [], []
    results, upcoming = [], []
    for e in (j.get("events") or []):
        home, away = e.get("strHomeTeam", ""), e.get("strAwayTeam", "")
        is_home = "ipswich" in _norm(home)
        is_away = "ipswich" in _norm(away)
        if not (is_home or is_away):
            continue
        opponent = away if is_home else home
        hs, as_ = e.get("intHomeScore"), e.get("intAwayScore")
        date = e.get("dateEvent") or ""
        round_ = e.get("intRound")
        if hs is not None and as_ is not None:
            our, their = (int(hs), int(as_)) if is_home else (int(as_), int(hs))
            result = "W" if our > their else "L" if our < their else "D"
            results.append({"event": int(round_) if round_ else None, "opponent": opponent,
                            "opponent_short": opponent[:3].upper(), "home": is_home,
                            "score": f"{our}-{their}", "result": result, "date": date})
        else:
            kickoff = e.get("strTimestamp") or (date + "T15:00:00Z" if date else None)
            upcoming.append({"event": int(round_) if round_ else None, "opponent": opponent,
                             "opponent_short": opponent[:3].upper(), "home": is_home,
                             "kickoff": kickoff})
    results.sort(key=lambda x: x["date"], reverse=True)   # most recent first
    upcoming.sort(key=lambda x: x.get("kickoff") or "")
    return results, upcoming


def fetch_squad(team_id):
    if not team_id:
        return []
    try:
        j = get_json(f"https://www.thesportsdb.com/api/v1/json/3/lookup_all_players.php?id={team_id}")
    except (requests.RequestException, ValueError):
        return []
    pos_map = {"goalkeeper": "GKP", "defender": "DEF", "midfielder": "MID", "forward": "FWD"}
    squad = []
    for p in (j.get("player") or []):
        pos_raw = (p.get("strPosition") or "").lower()
        pos = next((v for k, v in pos_map.items() if k in pos_raw), "MID")
        full_name = p.get("strPlayer", "")
        squad.append({"name": full_name.split()[-1] if full_name else "", "full_name": full_name,
                      "pos": pos, "apps": None, "goals": None, "assists": None})
    return squad


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

    team = None
    try:
        team = find_team()
        print(f"  team: {'found ' + team['strTeam'] if team else 'not found on TheSportsDB'}")
    except Exception as e:
        print(f"  team: skipped ({e})")
    if not team:
        missing.append("club badge/id")

    league = None
    try:
        league = find_league()
        print(f"  league: {'found ' + league['strLeague'] if league else 'not found on TheSportsDB'}")
    except Exception as e:
        print(f"  league: skipped ({e})")
    if not league:
        missing.append("league table")

    league_id = league.get("idLeague") if league else None
    league_name = league.get("strLeague") if league else "Barclays Women's Super League 2"

    table = []
    try:
        table = fetch_table(league_id)
        print(f"  table: {len(table)} teams")
    except Exception as e:
        print(f"  table: skipped ({e})")

    results, upcoming = [], []
    try:
        results, upcoming = fetch_fixtures(league_id)
        print(f"  fixtures: {len(results)} results, {len(upcoming)} upcoming")
    except Exception as e:
        print(f"  fixtures: skipped ({e})")
    if not results and not upcoming:
        missing.append("fixtures & results")

    squad = []
    try:
        squad = fetch_squad(team.get("idTeam") if team else None)
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

    data = {
        "season": SEASON_LABEL, "league_name": league_name,
        "team": {"short_name": "Ipswich", "badge": team.get("strTeamBadge") if team else None},
        "position": position, "summary": summary, "summary_text": summary_text,
        "next_fixture": dict(upcoming[0], badge=None) if upcoming else None,
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
