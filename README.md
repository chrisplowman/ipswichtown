# Ipswich Town — season stats reference

A static, auto-updating reference page for Ipswich Town's Premier League season,
organised into four tabs:

- **Overview** — next fixture, season record, upcoming fixtures with difficulty, recent results (with club badges)
- **Table** — the full Premier League table, Ipswich highlighted, European and relegation edges marked
- **Charts** — points progression, goals by gameweek, goals vs xG (attack and defence, from Understat),
  a non-penalty finishing chart (goals vs npxG), an interactive **shot map** per recent match, and the fixture-difficulty run
- **Squad** — full player stats, sortable by any column

No server, no database — a scheduled GitHub Action pulls the data and publishes a
static page to GitHub Pages. Charts render client-side with Chart.js (one CDN tag,
no build step); the shot map is inline SVG. Each data source degrades gracefully:
if one is unavailable on a given run, the page still builds from the rest.

**Data sources** (all free, no API key required):

- **Fantasy Premier League API** — `bootstrap-static`, `fixtures`, and `event/{gw}/live`
  for squad, schedule, difficulty ratings and per-gameweek points/goals.
- **Understat** — shot-level xG with x/y coordinates (the shot maps), per-match team xG
  and xG-against, and player non-penalty xG for the finishing chart.
- **ESPN** (public endpoint) — the live Premier League table.
- **TheSportsDB** (public test key) — club badges.

No keys or accounts are needed. Understat is parsed from its embedded page JSON with
the standard library, so there are no extra dependencies beyond `requests` and `jinja2`.

## How it works

```
ingest.py   →  data/itfc.json   →  build.py  →  site/  →  GitHub Pages
(fetch FPL)    (clean data)         (render)     (html)    (deploy)
```

The Action in `.github/workflows/deploy.yml` runs the two scripts and deploys
`site/` every 3 hours (and on every push, and on demand from the Actions tab).

## One-time setup

1. Create a **public** repo on GitHub and push these files to `main`.
2. In the repo, go to **Settings → Pages** and set **Source: GitHub Actions**.
3. That's it. The workflow runs on push; the first successful run publishes the
   site. The live URL appears under **Settings → Pages** and in the Actions run
   summary (usually `https://<you>.github.io/<repo>/`).

To force a refresh any time: **Actions tab → Build & deploy Ipswich stats → Run
workflow**.

> Note: GitHub disables scheduled workflows after ~60 days of no repo activity.
> Any push (or a manual run) re-arms the schedule.

## Run it locally

```bash
pip install -r requirements.txt
python ingest.py      # writes data/itfc.json
python build.py       # writes site/index.html
# then open site/index.html
```

## Extending it

- **More stats / shot maps:** add an Understat or FotMob fetch to `ingest.py`
  and merge into `data/itfc.json` (both keyless). Note early-season data is
  sparse until a few matches have been played.
- **League table position:** add a call to a standings source (e.g.
  football-data.org, free tier) — FPL doesn't expose the live table.
- **Styling:** everything is one self-contained `templates/index.html.j2`
  (inline CSS + a small vanilla-JS table sorter). No build step for the front end.
