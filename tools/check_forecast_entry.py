"""Exercise the ordinary menu entry on a running FlightCost site (requires the screenshots extra)."""
import argparse
import re
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import expect, sync_playwright

from flightcostapp.probe import probe_url


def check(browser, origin, lang):
    with browser.new_context() as context:
        def marked_request(route):
            url = route.request.url
            if urlsplit(url).netloc == urlsplit(origin).netloc:
                route.continue_(url=probe_url(url))
            else:
                route.continue_()

        context.route("**/*", marked_request)
        page = context.new_page()
        page.goto(probe_url(urljoin(origin, f"/{lang}/about")))
        entry = page.locator(f'.site-nav a[href="/{lang}/forecast"]')
        expect(entry).to_have_count(1)
        entry.click()
        section = page.locator("#manufacturer")
        study = section.locator('[data-u="study"]')
        expect(study).to_have_value("ten_116")
        legend = section.locator('[data-mp="legend"]')
        for aircraft, passengers, km in [("B752", 255, 7994), ("T214", 230, 7572)]:
            section.locator('[data-u="aircraft"]').select_option(aircraft)
            expect(legend).to_contain_text(str(passengers))
            groups = f"{km:,}".split(",")
            separator = {"en": ",", "de": r"\.", "ru": r"\s"}[lang]
            expect(legend).to_contain_text(re.compile(separator.join(groups)))
        expect(page.locator("html")).to_have_attribute("lang", lang)
        if lang != "ru":
            for selector in ["main h1", "#operations h2", "#flow-fleet h2",
                             "#scenario-methods h2", "#manufacturer .mr-modernization-description", "#modernization"]:
                expect(page.locator(selector)).not_to_contain_text(re.compile("[А-Яа-яЁё]"))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("origin", help="FlightCost origin, e.g. http://127.0.0.1:8795")
    cli.add_argument("--channel", help="Use an installed browser, e.g. chrome")
    args = cli.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel)
        for language in ("ru", "en", "de"):
            check(browser, args.origin, language)
            print(language, "menu, modernization scenario, chart and page language verified")
        browser.close()
