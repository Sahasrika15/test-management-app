from playwright.sync_api import sync_playwright

URL = "https://the-internet.herokuapp.com/add_remove_elements/"
TEXT = "Add/Remove Elements"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)

    print("page title:", page.title())
    print("all matches for text:", page.get_by_text(TEXT).count())
    print("visible matches:", page.get_by_text(TEXT).filter(visible=True).count())
    print("h3 texts:", page.locator("h3").all_inner_texts())
    print("h3 visible:", page.locator("h3").first.is_visible())
    browser.close()