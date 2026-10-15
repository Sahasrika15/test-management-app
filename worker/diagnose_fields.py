from playwright.sync_api import sync_playwright

from worker.runner import login

BASE = "https://oracleapex.com/ords/r/sahasrika_workspace/apex-timesheet-application189604"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    session = login(browser, BASE)
    context = browser.new_context(storage_state="artifacts/session.json")
    page = context.new_page()
    page.goto(f"{BASE}/timesheet-copy?session={session}", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    fields = page.locator("input:visible, textarea:visible")
    print("visible fields:", fields.count())
    for i in range(min(fields.count(), 20)):
        el = fields.nth(i)
        print(
            i,
            "id=", el.get_attribute("id"),
            "name=", el.get_attribute("name"),
            "aria-label=", el.get_attribute("aria-label"),
            "value=", el.input_value(),
        )
    browser.close()