# DeepSeek session setup

Skill extraction drives **chat.deepseek.com in a real browser** using your
logged-in session — no `platform.deepseek.com` API key, no billing.

> **The single most important detail:** DeepSeek keeps its auth bearer in
> **`localStorage.userToken`**, not in a cookie. Copying cookies alone will
> *not* log you in. The capture script below grabs both; if you export by
> hand, you must grab the token separately.

---

## Option A — capture script (recommended)

One command, grabs cookies *and* `userToken`, writes a Playwright
storage-state file:

```powershell
cd "d:\Resume Tailor\backend"
..\venv\Scripts\python.exe scripts\capture_deepseek_session.py
```

1. A Chromium window opens on chat.deepseek.com.
2. Log in (and clear any Cloudflare "Just a moment…" check).
3. Wait until the chat input is visible.
4. Return to the terminal and press **Enter**.

It writes `backend/secrets/deepseek_session.json` and prints whether
`userToken` was found. Then set in `backend/.env`:

```
DEEPSEEK_STORAGE_STATE=secrets/deepseek_session.json
```

Restart the backend. Done.

---

## Option B — manual export from Chrome

Use this if you'd rather not run the script.

### B1. Cookies

**With the Cookie-Editor extension** (easiest):

1. Log in to <https://chat.deepseek.com> in Chrome.
2. Click the Cookie-Editor icon → **Export** → **Export as JSON**.
3. Save to `backend/secrets/deepseek_cookies.json`.

**Or with DevTools** (no extension):

1. On chat.deepseek.com press **F12** → **Network** tab.
2. Refresh, click any request to `chat.deepseek.com`.
3. Under **Request Headers**, copy the whole `cookie:` value.
4. Put it in `.env` as `DEEPSEEK_COOKIES="…"` (keep it on one line, in quotes).

### B2. The `userToken` (required — cookies are not enough)

1. On chat.deepseek.com press **F12** → **Application** tab.
2. Left sidebar → **Local Storage** → `https://chat.deepseek.com`.
3. Find the **`userToken`** row and copy its value.
4. Put it in `.env` as `DEEPSEEK_USER_TOKEN=…`.

### B3. Wire it up

```
# either the cookie file…
DEEPSEEK_COOKIE_FILE=secrets/deepseek_cookies.json
# …or the raw header string
# DEEPSEEK_COOKIES="a=1; b=2"

DEEPSEEK_USER_TOKEN=<value from Local Storage>
```

Precedence is `DEEPSEEK_STORAGE_STATE` → `DEEPSEEK_COOKIE_FILE` →
`DEEPSEEK_COOKIES`. `DEEPSEEK_USER_TOKEN` is merged on top of whichever wins.

> Save JSON files as UTF-8. A BOM (what Notepad and PowerShell `Out-File`
> add by default) is handled automatically, so you don't have to fight it.

---

## Refreshing an expired session

DeepSeek sessions last roughly a few hours to a few days. When yours lapses:

**Symptom** — clicking **✨ Extract** shows:

> DeepSeek session expired. Re-run scripts/capture_deepseek_session.py to refresh it.

The backend returns **HTTP 401** with the reason in `detail`, and logs it.

**Fix** — re-run the same capture command; it overwrites the file in place:

```powershell
cd "d:\Resume Tailor\backend"
..\venv\Scripts\python.exe scripts\capture_deepseek_session.py
```

Then restart the backend (the browser context is created per request, but
`.env` is only read at startup, so a restart is needed if you changed paths).
If you exported manually, repeat **B1** and **B2** — `userToken` rotates, so
refreshing cookies alone will not fix it.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| 401, "chat input not found" | Session expired, or Cloudflare is blocking headless | Re-capture; if it persists set `DEEPSEEK_HEADLESS=false` |
| 401, "redirected to the login page" | Session definitely expired | Re-capture |
| 504 timeout | DeepSeek slow or rate-limiting the account | Retry; extraction is one job at a time by design |
| Replies come back empty | DeepSeek changed their frontend markup | Update the selector constants at the top of `app/services/deepseek/service.py` |
| Works headful, fails headless | Bot detection | `DEEPSEEK_HEADLESS=false` in `.env` |

### Watching it work

To see the automation live instead of headless:

```
DEEPSEEK_HEADLESS=false
```

A Chromium window opens per extraction — useful for diagnosing selector
breakage or a Cloudflare wall.

---

## Security notes

- `secrets/` and `*deepseek_session*.json` are git-ignored — these files are
  **live credentials**; anyone with them can use your DeepSeek account.
- Nothing is written into source files; everything is env-var or file based.
- This automates a logged-in web UI, which is likely outside DeepSeek's terms
  of service. It's your own account for personal use — fine for this, but
  don't scale it up or share the session.

---

## Why not an unofficial wrapper?

Checked August 2026:

| Repo | Status |
|---|---|
| [thinhdanggroup/chat-deepseek-api](https://github.com/thinhdanggroup/chat-deepseek-api) | Archived Feb 2025 |
| [xtekky/deepseek4free](https://github.com/xtekky/deepseek4free) | Last commit Feb 2025 |
| [smkttl/deepseek-api](https://github.com/smkttl/deepseek-api) | 12 stars, minimal activity |
| [sums001/Deepseek-API](https://github.com/sums001/Deepseek-API) | Maintained (Jun 2026), but clone-only (not on PyPI), keeps its own session store, and its bundled server also binds port 8000 |

The only maintained option would mean vendoring an unaudited repo that handles
your DeepSeek credentials, and it drives Playwright internally anyway — so
direct Playwright is fewer moving parts, not more.
