"""
Render data/itfc.json into a self-contained static site in ./site.

Run:  python build.py
Output:  site/index.html  and  site/data/itfc.json  (the raw data, also published)
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    LONDON = ZoneInfo("Europe/London")
except Exception:  # pragma: no cover - zoneinfo/tzdata always present on CI
    LONDON = None

from jinja2 import Environment, FileSystemLoader, select_autoescape

DATA = Path("data/itfc.json")
SITE = Path("site")
TEMPLATES = Path("templates")

# Day-suffix helper: 1 -> 1st, 22 -> 22nd, etc.
def _ord(n):
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def fmt_kickoff(iso):
    """'2026-08-22T14:00:00Z' -> 'Sat 22 Aug, 15:00' (kept simple, UTC-based)."""
    if not iso:
        return "TBC"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "TBC"
    if LONDON:
        dt = dt.astimezone(LONDON)  # show UK kickoff time (BST/GMT), not UTC
    return dt.strftime("%a ") + f"{dt.day}{_ord(dt.day)} " + dt.strftime("%b, %H:%M")


def fmt_updated(iso):
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return dt.strftime("%d %b %Y, %H:%M UTC")


def main():
    data = json.loads(DATA.read_text())

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["kickoff"] = fmt_kickoff
    env.filters["updated"] = fmt_updated
    env.filters["ordinal"] = lambda n: (
        f"{int(n)}{'th' if 11 <= int(n) % 100 <= 13 else {1:'st',2:'nd',3:'rd'}.get(int(n) % 10, 'th')}"
        if str(n).lstrip('-').isdigit() else n
    )
    template = env.get_template("index.html.j2")
    # Inline the data for the charts. Escape "<" so a stray "</script>" in the
    # data can't break out of the script tag; "\u003c" is valid JSON.
    data_json = json.dumps(data).replace("<", "\\u003c")
    html = template.render(data_json=data_json, **data)

    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "data").mkdir(parents=True)
    (SITE / "index.html").write_text(html)
    # Publish the raw JSON too — a tiny read-only "API" for future use.
    (SITE / "data" / "itfc.json").write_text(DATA.read_text())
    # Stops GitHub Pages running the output through Jekyll.
    (SITE / ".nojekyll").write_text("")
    print(f"Built site/ ({len(html):,} bytes).")


if __name__ == "__main__":
    main()
