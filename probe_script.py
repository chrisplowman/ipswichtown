import json
from playwright.sync_api import sync_playwright

URL = "https://www.fotmob.com/en-GB/leagues/47/stats/premier-league/players"

api_calls = []


def on_response(resp):
    u = resp.url
    if "fotmob.com/api" in u and "image" not in u:
        api_calls.append(u)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    page.on("response", on_response)
    page.goto(URL, wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(3000)
    browser.close()

print("=== API calls seen ===")
for u in sorted(set(api_calls)):
    print(u)
