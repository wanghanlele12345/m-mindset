import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # Capture console messages
        page.on("console", lambda msg: print(f"CONSOLE [{msg.type}]: {msg.text}"))
        
        # Capture page errors
        page.on("pageerror", lambda exc: print(f"PAGE ERROR: {exc}"))
        
        await page.goto("http://localhost:8000/")
        await page.wait_for_timeout(2000)
        await browser.close()

asyncio.run(run())
