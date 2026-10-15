"""Open the Streamlit app in a headless browser so Community Cloud doesn't put it to sleep.

If it is already asleep, press the wake-up button and wait for it to boot.
Usage: python scripts/keep_awake.py https://<your-app>.streamlit.app
"""
import sys

from playwright.sync_api import sync_playwright

url = sys.argv[1]
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(10_000)
    wake = page.get_by_role("button", name="Yes, get this app back up!")
    if wake.count():
        print("App was asleep, waking it up")
        wake.first.click()
        page.wait_for_timeout(90_000)
    else:
        page.wait_for_timeout(20_000)
    print("Visited", url, "-", page.title())
    browser.close()
