import json
import re
import requests
from playwright.sync_api import sync_playwright

# 1) Inspect the raw /leagues?id=47 payload for anything stats-shaped.
r = requests.get("https://www.fotmob.com/api/data/leagues?id=47",
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
r.raise_for_status()
league = r.json()
print("=== top-level keys ===")
print(list(league.keys()))


def find_stat_keys(node, path=""):
    hits = []
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            if re.search(r"stat", k, re.I):
                hits.append(p)
            hits += find_stat_keys(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node[:2]):
            hits += find_stat_keys(v, f"{path}[{i}]")
    return hits


print("=== keys matching 'stat' ===")
for p in find_stat_keys(league):
    print(p)

# 2) Drive the actual stats page with a browser and click through the
# category dropdown, capturing every fotmob.com/api response along the way.
api_calls = []


def on_response(resp):
    u = resp.url
    if "fotmob.com/api" in u and "image" not in u:
        api_calls.append(u)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    page.on("response", on_response)
    page.goto("https://www.fotmob.com/en-GB/leagues/47/stats/premier-league/players",
              wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(2000)
    # try to find and click a stat-category dropdown/selector to trigger a
    # category switch (selector guessed; failure here is fine, we still
    # keep whatever the initial page load captured)
    try:
        combo = page.query_selector("[role=combobox], select, button[aria-haspopup]")
        if combo:
            combo.click()
            page.wait_for_timeout(1000)
            opt = page.query_selector("[role=option]:nth-child(2), li:nth-child(2)")
            if opt:
                opt.click()
                page.wait_for_timeout(2000)
    except Exception as e:
        print("interaction error:", e)
    html = page.content()
    browser.close()

print("=== API calls seen (browser) ===")
for u in sorted(set(api_calls)):
    print(u)

print("=== page title ===")
m = re.search(r"<title>(.*?)</title>", html)
print(m.group(1) if m else None)
print("=== html length ===", len(html))
# dump any __NEXT_DATA__ or similar embedded JSON blob
m2 = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
print("has __NEXT_DATA__:", bool(m2))
if m2:
    try:
        nd = json.loads(m2.group(1))
        print("next_data top keys:", list(nd.keys()))
    except Exception as e:
        print("parse error", e)
