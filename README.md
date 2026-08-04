# Ipswich Town — season stats reference

A static, auto-updating reference page for Ipswich Town's Premier League season,
organised into three tabs:

- **Overview** — next fixture, season record, upcoming fixtures with difficulty, recent results
- **Charts** — points progression, goals by gameweek, goals vs xG (attack and defence),
  a squad xG-vs-xA scatter, and the upcoming fixture-difficulty run
- **Squad** — full player stats, sortable by any column

No server, no database — a scheduled GitHub Action pulls the data and publishes a
static page to GitHub Pages. Charts render client-side with Chart.js (one CDN tag,
no build step) from the same data the page publishes.

**Data source:** the (keyless) Fantasy Premier League API — `bootstrap-static`
for teams/players/gameweeks, `fixtures` for the schedule and difficulty ratings,
and `event/{gw}/live` (one call per finished gameweek) to aggregate team xG and
xG-against for the trend charts. No API key or account needed.

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
