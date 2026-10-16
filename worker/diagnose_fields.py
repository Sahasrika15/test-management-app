import os
import sys

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BASE = os.getenv("APP_URL", "").rstrip("/")
PAGE = sys.argv[1] if len(sys.argv) > 1 else "/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(BASE + PAGE, wait_until="domcontentloaded")
    for field in page.locator("input, textarea, select").all():
        if field.is_visible():
            print(field.get_attribute("type"), field.get_attribute("name"),
                  field.get_attribute("aria-label"), field.get_attribute("placeholder"))
    browser.close()