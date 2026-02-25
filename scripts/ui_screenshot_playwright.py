# Playwright script to automate UI screenshots for WealthTax Agent Streamlit app
# Save this as scripts/ui_screenshot_playwright.py
# Requires: pip install playwright && playwright install

import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

SCREENSHOTS = [
    ("step1_upload.png", "Upload your tax slips"),
    ("step2_review_slips.png", "Review extracted slips"),
    ("step3_draft_return.png", "Generate draft return"),
    ("step4_approve.png", "Approve and download"),
]

async def run():
    docs_dir = Path(__file__).parent.parent / "docs"
    docs_dir.mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("http://localhost:8511/")
        await page.wait_for_selector("input[type='file']")
        # 1. Screenshot: Upload screen
        await page.screenshot(path=str(docs_dir / SCREENSHOTS[0][0]), full_page=True)
        # 2. Upload sample files (update path as needed)
        sample_dir = Path(__file__).parent.parent / "sample_tax_slips"
        files = [str(sample_dir / f) for f in ["t4_sample_2025.pdf", "t5_sample_2025.pdf", "rrsp_receipt_2025.pdf"] if (sample_dir / f).exists()]
        await page.set_input_files("input[type='file']", files)
        await page.wait_for_timeout(1500)
        # 2. Screenshot: Review slips
        await page.screenshot(path=str(docs_dir / SCREENSHOTS[1][0]), full_page=True)
        # 3. Click 'Generate draft return'
        await page.click("text=Generate draft return")
        await page.wait_for_selector("text=Approve this draft", timeout=15000)
        # 3. Screenshot: Draft return
        await page.screenshot(path=str(docs_dir / SCREENSHOTS[2][0]), full_page=True)
        # 4. Scroll approval section into view and check all approval checkboxes robustly
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)
        # Try clicking the label for each checkbox, fallback to JS if needed
        checkbox_labels = [
            "I verified all summary totals",
            "I reviewed the explanations",
            "I understand this tool does not file"
        ]
        for label_text in checkbox_labels:
            try:
                label = await page.query_selector(f"label:has-text('{label_text}')")
                if label:
                    await label.scroll_into_view_if_needed()
                    await label.click(force=True)
                    await page.wait_for_timeout(200)
                else:
                    # Fallback: set checkbox via JS
                    await page.evaluate(f"Array.from(document.querySelectorAll('label')).find(l => l.textContent.includes('{label_text}')).querySelector('input[type=checkbox]').checked = true;")
                    await page.wait_for_timeout(200)
            except Exception:
                # Fallback: set checkbox via JS
                await page.evaluate(f"Array.from(document.querySelectorAll('label')).find(l => l.textContent.includes('{label_text}')).querySelector('input[type=checkbox]').checked = true;")
                await page.wait_for_timeout(200)
        await page.wait_for_timeout(500)
        # 5. Click 'Approve this draft'
        await page.click("text=Approve this draft")
        await page.wait_for_timeout(1000)
        # 6. Screenshot: Approve/download
        await page.screenshot(path=str(docs_dir / SCREENSHOTS[3][0]), full_page=True)
        # 7. Zoom out to fit more content, then take full-page screenshot
        await page.evaluate("document.body.style.zoom='0.5'")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=str(docs_dir / "full_flow.png"), full_page=True)
        await page.evaluate("document.body.style.zoom='1.0'")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
