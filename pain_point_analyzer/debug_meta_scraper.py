"""Diagnostic script: see exactly what Playwright sees on Meta Ad Library."""

import asyncio
import re
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def diagnose():
    from playwright.async_api import async_playwright

    url = (
        "https://www.facebook.com/ads/library/"
        "?active_status=active&ad_type=all&country=US"
        "&q=high%20blood%20pressure"
    )

    print(f"\n{'='*80}")
    print(f"DIAGNOSTIC: Meta Ad Library Scraper")
    print(f"URL: {url}")
    print(f"{'='*80}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # Track ALL responses and redirects
        responses = []
        redirects = []

        async def on_response(response):
            responses.append({
                "url": response.url[:120],
                "status": response.status,
                "content_type": response.headers.get("content-type", "?")[:60],
            })

        page.on("response", on_response)

        print("[1] Navigating (wait_until=commit first to see initial response)...")
        try:
            resp = await page.goto(url, wait_until="commit", timeout=30000)
            print(f"    Initial response: status={resp.status if resp else 'None'}")
            if resp:
                print(f"    Response URL: {resp.url[:150]}")
                print(f"    Content-Type: {resp.headers.get('content-type', '?')}")
                # Check if redirected
                if resp.url != url:
                    print(f"    *** REDIRECTED from original URL ***")
        except Exception as e:
            print(f"    Navigation error: {e}")

        print(f"\n[2] Waiting for load event...")
        try:
            await page.wait_for_load_state("load", timeout=30000)
            print("    load state reached")
        except Exception as e:
            print(f"    load state timeout: {e}")

        print(f"\n[3] Waiting 10 more seconds for SPA...")
        await asyncio.sleep(10)

        # Check all frames (Meta may use iframes)
        frames = page.frames
        print(f"\n[4] Page frames: {len(frames)}")
        for i, frame in enumerate(frames):
            print(f"    Frame {i}: {frame.url[:120]}")

        # Get current URL (may have been redirected by JS)
        current_url = page.url
        print(f"\n[5] Current URL after load: {current_url[:150]}")

        # Try to get HTML from main frame
        print(f"\n[6] Attempting page.content()...")
        try:
            html = await page.content()
            print(f"    HTML length: {len(html):,} chars")
        except Exception as e:
            print(f"    page.content() failed: {e}")
            html = ""

        # Save HTML
        html_path = OUTPUT_DIR / "debug_page.html"
        html_path.write_text(html or "(empty)", encoding="utf-8")
        print(f"    Saved to: {html_path}")

        # Try evaluate with null checks
        print(f"\n[7] Page state evaluation...")
        try:
            state = await page.evaluate("""() => {
                return {
                    title: document.title || '(none)',
                    bodyExists: !!document.body,
                    bodyHTML: document.body ? document.body.innerHTML.substring(0, 500) : '(no body)',
                    bodyText: document.body ? (document.body.innerText || '').substring(0, 500) : '(no body)',
                    docElement: document.documentElement ? document.documentElement.outerHTML.substring(0, 300) : '(none)',
                    scripts: document.querySelectorAll('script').length,
                    divs: document.querySelectorAll('div').length,
                    url: window.location.href,
                };
            }""")
            print(f"    Title: {state['title']}")
            print(f"    Body exists: {state['bodyExists']}")
            print(f"    Scripts: {state['scripts']}")
            print(f"    Divs: {state['divs']}")
            print(f"    URL: {state['url'][:150]}")
            print(f"\n    --- Body text (first 500) ---")
            print(f"    {state['bodyText'][:500]}")
            print(f"\n    --- Body HTML (first 500) ---")
            print(f"    {state['bodyHTML'][:500]}")
            print(f"\n    --- Document element (first 300) ---")
            print(f"    {state['docElement'][:300]}")
        except Exception as e:
            print(f"    Evaluation failed: {e}")

        # Print captured HTTP responses
        print(f"\n[8] HTTP responses captured ({len(responses)} total):")
        for i, r in enumerate(responses[:30]):
            print(f"    [{r['status']}] {r['content_type'][:40]:40s} {r['url']}")

        # Try screenshot without fonts
        print(f"\n[9] Attempting screenshot...")
        screenshot_path = OUTPUT_DIR / "debug_screenshot.png"
        try:
            await page.evaluate("document.fonts && document.fonts.ready")
            await page.screenshot(path=str(screenshot_path), full_page=False, timeout=10000)
            print(f"    Saved: {screenshot_path}")
        except Exception as e:
            print(f"    Failed: {e}")
            # Try raw CDP screenshot as fallback
            try:
                cdp = await context.new_cdp_session(page)
                result = await cdp.send("Page.captureScreenshot", {"format": "png"})
                import base64
                screenshot_path.write_bytes(base64.b64decode(result["data"]))
                print(f"    CDP fallback saved: {screenshot_path}")
            except Exception as e2:
                print(f"    CDP fallback also failed: {e2}")

        # Search HTML for patterns
        if html and len(html) > 100:
            print(f"\n[10] Searching HTML for patterns...")
            for pat in ["total_count", "collated_result", "ads_count",
                        "numResults", "search_results", "login_form"]:
                count = html.count(pat)
                if count:
                    idx = html.index(pat)
                    snippet = html[max(0,idx-20):idx+60].replace('\n', ' ')
                    print(f"    '{pat}' found {count}x — context: ...{snippet}...")
                else:
                    print(f"    '{pat}' — NOT FOUND")
        else:
            print(f"\n[10] HTML too short ({len(html)} chars) to search")

        await context.close()
        await browser.close()

    print(f"\n{'='*80}")
    print("DIAGNOSTIC COMPLETE")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(diagnose())
