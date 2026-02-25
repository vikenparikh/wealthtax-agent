# Playwright script to automate UI screenshots for WealthTax Agent Streamlit app
# Save this as scripts/ui_screenshot_playwright.py
# Requires: pip install playwright && playwright install

import asyncio
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pathlib import Path

SCREENSHOTS = [ 
    ("step1_upload.png", "Upload your tax slips"),
    ("step2_review_slips.png", "Review extracted slips"),
    ("step3_draft_return.png", "Generate draft return"),
    ("step4_approve.png", "Approve and download"),
]
# Configurable parameters
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 1100
WAIT_SHORT = 2000
WAIT_MED = 3500
WAIT_LONG = 5000

async def run():
    docs_dir = Path(__file__).parent.parent / "docs"
    docs_dir.mkdir(exist_ok=True)
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        # Enable video recording for the context
        context = await browser.new_context(
            viewport={"width": 1280, "height": 1100},
            record_video_dir=str(docs_dir),
            record_video_size={"width": 1280, "height": 1100}
        )
        page = await context.new_page()
        await page.goto("http://localhost:8511/")
        await page.wait_for_selector("input[type='file']")
        await page.wait_for_timeout(2000)
        # 1. Screenshot: Upload screen
        await page.screenshot(path=str(docs_dir / SCREENSHOTS[0][0]), full_page=True)
        await page.wait_for_timeout(2000)
        # 2. Upload sample files (update path as needed)
        sample_dir = Path(__file__).parent.parent / "sample_tax_slips"
        files = [str(sample_dir / f) for f in ["t4_sample_2025.pdf", "t5_sample_2025.pdf", "rrsp_receipt_2025.pdf"] if (sample_dir / f).exists()]
        await page.set_input_files("input[type='file']", files)
        await page.wait_for_timeout(3500)
        # 2. Screenshot: Review slips
        await page.screenshot(path=str(docs_dir / SCREENSHOTS[1][0]), full_page=True)
        await page.wait_for_timeout(2000)
        # 3. Click 'Generate draft return'
        await page.click("text=Generate draft return")
        await page.wait_for_selector("text=Approve this draft", timeout=15000)
        await page.wait_for_timeout(2500)
        # 3. Screenshot: Draft return
        await page.screenshot(path=str(docs_dir / SCREENSHOTS[2][0]), full_page=True)
        await page.wait_for_timeout(2000)
        # 4. Scroll approval section into view and check all approval checkboxes robustly
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
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
                    await page.wait_for_timeout(800)
                else:
                    # Fallback: set checkbox via JS
                    await page.evaluate(f"Array.from(document.querySelectorAll('label')).find(l => l.textContent.includes('{label_text}')).querySelector('input[type=checkbox]').checked = true;")
                    await page.wait_for_timeout(800)
            except Exception:
                # Fallback: set checkbox via JS
                await page.evaluate(f"Array.from(document.querySelectorAll('label')).find(l => l.textContent.includes('{label_text}')).querySelector('input[type=checkbox]').checked = true;")
                await page.wait_for_timeout(800)
        await page.wait_for_timeout(1500)
        # 5. Click 'Approve this draft'
        await page.click("text=Approve this draft")
        await page.wait_for_timeout(2500)
        # 6. Screenshot: Approve/download
        await page.screenshot(path=str(docs_dir / SCREENSHOTS[3][0]), full_page=True)
        await page.wait_for_timeout(2000)
        # 7. Set background to white for html and body
        await page.evaluate("document.body.style.background='white'; document.documentElement.style.background='white';")
        # Dynamically resize viewport to fit content
        doc_height = await page.evaluate("document.documentElement.scrollHeight")
        await page.set_viewport_size({"width": 1280, "height": int(doc_height)})
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        await page.screenshot(path=str(docs_dir / "full_flow.png"), full_page=False)
        await page.wait_for_timeout(1200)
        # Scroll to top before ending video to avoid empty last frame
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(2000)
        # End and save video
        video_path = await page.video.path() if hasattr(page, 'video') else None
        await context.close()
        await browser.close()
        # Rename the video file to a friendly name if video was recorded
        if video_path:
            final_video = docs_dir / "full_flow.webm"
            Path(video_path).rename(final_video)
        except PlaywrightTimeoutError as e:
            print(f"[ERROR] Playwright timeout: {e}", file=sys.stderr)
            await page.screenshot(path=str(docs_dir / "error_timeout.png"), full_page=True)
        except Exception as e:
            print(f"[ERROR] Unexpected error: {e}", file=sys.stderr)
            try:
                await page.screenshot(path=str(docs_dir / "error_unexpected.png"), full_page=True)
            except Exception:
                pass

if __name__ == "__main__":
    asyncio.run(run())
