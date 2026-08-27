# Ipswich Town — season stats reference

A static, auto-updating reference page for Ipswich Town's Premier League season,
organised into four tabs:

- **Overview** — next fixture, a **next-opponent preview** (their position, form, xG, plus a modelled **win probability** and recent **head-to-head**), a **team-news** panel (injuries/suspensions/doubts), season record, upcoming fixtures with difficulty, recent results (with club badges)
- **Table** — the full Premier League table, Ipswich highlighted, European and relegation edges marked
- **Charts** — points progression, goals by gameweek, goals vs xG (attack and defence), non-penalty finishing, a **league-wide xG-vs-xGA scatter** of all 20 clubs, a **"how Ipswich compare"** panel ranking them against the league on each measure, an interactive **shot map with a match report** per recent match, and the fixture-difficulty run
- **Squad** — full player stats with a **per-90 toggle**, plus **player profile radars** showing each player's percentile ranks vs positional peers league-wide, with a compare-two-players mode
- **News** — latest headlines merged from Ipswich-specific RSS feeds (BBC Sport, TWTD, Vital), newest first, linking out to each publisher

No server, no database — a scheduled GitHub Action pulls the data and publishes a
static page to GitHub Pages. Charts render client-side with Chart.js (one CDN tag,
no build step); the shot map is inline SVG. Each data source degrades gracefully:
if one is unavailable on a given run, the page still builds from the rest.

**Data sources** (all free, no API key required):

- **Fantasy Premier League API** — `bootstrap-static`, `fixtures`, and `event/{gw}/live`
  for squad, schedule, difficulty ratings and per-gameweek points/goals.
- **Understat** — shot-level xG with x/y coordinates (the shot maps), per-match team xG
  and xG-against, player non-penalty xG for the finishing chart, and the **league page**
  (every club's season aggregates and every player league-wide) that powers the team
  scatter, the rank comparison, and the player percentile radars.
- **ESPN** (public endpoint) — the live Premier League table.
- **TheSportsDB** (public test key) — club badges.
- **FPL player flags** — team news (injuries, suspensions, doubts) from each player's
  status and news fields.
- **football-data.co.uk** — historical results (recent PL and Championship seasons)
  for the next-opponent head-to-head.
- **ClubElo** — club Elo ratings, used to model the next-match win probability.
- **RSS feeds** — Ipswich-specific news feeds (BBC Sport, TWTD, Vital) for the News tab. Edit the list in `NEWS_FEEDS` at the top of `ingest.py` to add or remove sources.

Every source is free and keyless. Each is wrapped so that if one is unavailable on a
given run, the page still builds from the rest.

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

### Optional: Google Analytics

To add GA without committing the measurement ID to the repo, add it as a repo
secret instead: **Settings → Secrets and variables → Actions → New repository
secret**, name `GA_MEASUREMENT_ID`, value your `G-XXXXXXX` ID. The next build
picks it up automatically (`build.py` reads it from the environment) and every
page gets the standard `gtag.js` snippet; leave the secret unset and no
analytics code is added at all, including for a local `python build.py` run.
Keeping it out of the repo only keeps it out of the git history — like any
client-side analytics, the ID is still visible in the deployed page's source
to anyone who looks.

## Run it locally

```bash
pip install -r requirements.txt
python ingest.py      # writes data/itfc.json
python build.py       # writes site/index.html
# then open site/index.html
```

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Covers the pure helper functions in `ingest.py` and `build.py` (name
normalisation, date formatting, win-probability modelling, etc.).

## Customising the look

The entire visual design is driven by CSS variables in one place: the `:root`
block at the top of the `<style>` section in `templates/index.html.j2`
(`--primary`, `--brand-navy`, `--surface`, `--hairline`, `--radius-lg`,
`--space-md`, and so on).

- **Change a colour, radius, spacing value or font once in `:root`** and it applies
  everywhere it's used.
- **The charts read the same variables at runtime** (via `getComputedStyle`), so
  recolouring `--primary`, `--win`/`--draw`/`--loss` or the `--fdr-*` tokens
  restyles the graphs, shot map and rank bars too — no need to touch the JavaScript.
- Football-specific colours are their own tokens (`--win`, `--draw`, `--loss`,
  `--fdr-1`…`--fdr-5`) so you can retheme results and difficulty without disturbing
  the brand palette.

After any edit, run `python build.py` and open `site/index.html` to preview.

## Extending it

- **More stats / shot maps:** add an Understat or FotMob fetch to `ingest.py`
  and merge into `data/itfc.json` (both keyless). Note early-season data is
  sparse until a few matches have been played.
- **League table position:** add a call to a standings source (e.g.
  football-data.org, free tier) — FPL doesn't expose the live table.
- **Styling:** everything is one self-contained `templates/index.html.j2`
  (inline CSS + a small vanilla-JS table sorter). No build step for the front end.
