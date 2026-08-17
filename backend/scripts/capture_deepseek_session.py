"""Capture a logged-in DeepSeek session for the backend to reuse.

Opens a real Chromium window, waits for you to log in to chat.deepseek.com,
then saves cookies *and* localStorage (including the `userToken` bearer that
DeepSeek actually authenticates with) to a Playwright storage-state file.

Usage:
    cd backend
    ..\\venv\\Scripts\\python.exe scripts\\capture_deepseek_session.py

Then point backend/.env at the file it writes:
    DEEPSEEK_STORAGE_STATE=secrets/deepseek_session.json
"""

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

DEEPSEEK_ORIGIN = "https://chat.deepseek.com"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "secrets" / "deepseek_session.json"


def _has_usable_user_token(raw_value: object) -> bool:
    """Reject DeepSeek's logged-out ``{"value": null}`` placeholder."""
    if not isinstance(raw_value, str) or not raw_value.strip():
        return False
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return True
    if isinstance(parsed, dict) and "value" in parsed:
        return bool(parsed["value"])
    return bool(parsed)


async def main() -> int:
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        await page.goto(DEEPSEEK_ORIGIN)

        print()
        print("A browser window has opened.")
        print("  1. Log in to DeepSeek (and clear any Cloudflare check).")
        print("  2. Wait until you can see the chat input box.")
        print("  3. Come back here and press Enter to save the session.")
        print()
        await asyncio.get_event_loop().run_in_executor(None, input, "Press Enter once logged in... ")

        state = await context.storage_state()
        await browser.close()

    token_found = any(
        item.get("name") == "userToken" and _has_usable_user_token(item.get("value"))
        for origin in state.get("origins", [])
        for item in origin.get("localStorage", [])
    )

    if not token_found:
        print()
        print("Session was not saved: `userToken` contains no authenticated value.")
        print("Re-run and make sure the DeepSeek chat screen is fully loaded.")
        return 1

    output_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    print()
    print(f"Saved session -> {output_path}")
    print(f"  cookies:    {len(state.get('cookies', []))}")
    print("  userToken:  found")

    print()
    print("Now set this in backend/.env:")
    print(f"  DEEPSEEK_STORAGE_STATE={output_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
