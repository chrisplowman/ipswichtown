from playwright.sync_api import sync_playwright

URL = "https://chrisplowman.github.io/ipswichtown/women/match/2026-09-06-nottingham-forest-wfc-h.html"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1200, "height": 2400})
    page.goto(URL, wait_until="networkidle")
    page.screenshot(path="pitch_probe.png", full_page=True)
    svg = page.query_selector(".pitch")
    if svg:
        svg.screenshot(path="pitch_only.png")
        circles = page.eval_on_selector_all(
            ".pitch circle",
            "els => els.map(e => ({cx: e.getAttribute('cx'), cy: e.getAttribute('cy'), fill: e.getAttribute('fill')}))",
        )
        print("circles:", circles)
    browser.close()
