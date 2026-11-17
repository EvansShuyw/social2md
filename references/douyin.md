# Douyin anti-bot notes, failed approaches & field schema

Read this before debugging any failure. It records everything learned the hard
way while getting Douyin video extraction working. The single most important
conclusion: **log in once with a real browser, then intercept that browser's own
API traffic via CDP. Do not try to scrape anonymously or reimplement signatures.**

## 1. Why anonymous / pure-HTTP approaches FAIL (do not retry)

Douyin's web detail endpoint
`https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=<id>` is protected by
ByteDance's **ArgusSecurity** risk-control stack. Relevant parameters/headers:

- `a_bogus` — request signature (the successor to `X-Bogus` / `_signature`).
- `msToken` — device/session token.
- `s_v_web_id` — verify/fp id (`getVerifyFp()`).
- `ttwid` — edge token.
- `uifid` — a device fingerprint cookie. **Missing/invalid uifid is fatal.**
- `x-secsdk-web-signature` — extra secsdk signature derived from uifid + ts.

Every one of these was tried and FAILED:

| Approach | What we did | Exact failure |
|---|---|---|
| Pure HTTP + `abogus` lib | Generated `msToken`/`a_bogus`/`verifyFp`/`signWebUrl`, hardcoded a `uifid`, requested detail API directly | `Uifid Not Found` → `Validate Error`. A made-up uifid doesn't pass; a real one must be minted by the browser's JS. |
| Anonymous detail API | GET with various param sets, no login | `HTTP 200` but **body length = 0**. Extremely misleading — a 200 suggests success but there is no data. |
| `yt-dlp` | Standard extractor on the video URL | Requires **fresh cookies**; without a logged-in cookie jar it can't get the media. |
| Safari WebDriver (`safaridriver`) | Open video page, wait for JS challenge, read `_ROUTER_DATA` / video src | Proxy caused `502`; macOS required GUI/accessibility authorization; unreliable. |
| Mobile share page `www.iesdouyin.com/share/video/<id>/` | Mobile UA, read rendered `window._ROUTER_DATA` | Anonymous `_ROUTER_DATA` contained **only route params**, no `aweme_detail`. |
| Anonymous CDP | Playwright + CDP, capture detail response without login | Detail request returned `HTTP 200`, body `len=0` — same as plain HTTP. |

**Conclusion:** all of the above are dead ends. The working approach (below) is
login + CDP interception. Do not spend time regenerating signatures.

## 2. The working approach: login + CDP interception

Principle: **let the real browser execute all the anti-bot JS and sign its own
requests; we just watch the network and read the response.**

### 2.1 One-time login (`login.mjs`)

- Launch a **visible** persistent Chromium context (`headless: false`) pointed at
  `https://www.douyin.com/`.
- User scans the QR in the Douyin app and confirms on the phone.
- Poll `context.cookies()` for `sessionid` / `sessionid_ss`.
- **Gracefully `context.close()`** — a hard kill (SIGKILL) drops the `sessionid`
  cookie and the whole login is lost.
- Cookies land in the profile dir (default `~/.workbuddy/douyin-profile`). Reuse
  this dir for all future runs.

Login gotchas actually encountered:

- **Invisible QR window.** The Chromium window opened *behind* Tencent Meeting /
  VS Code, so the user saw no QR code. Fix: `osascript -e 'tell application
  "Chromium" to activate'` (and the same for Google Chrome) after navigation.
  If the user reports "I don't see a QR code", take a screenshot
  (`screencapture -x /tmp/s.png`) and view it to confirm before assuming failure.
- **QR expiry.** Codes expire in ~2–3 min. Refresh the page periodically
  (login.mjs reloads every ~100 s) to force a fresh code.
- **Short timeout.** Original script had a 180 s window; too tight if the user is
  away. Default is now 600 s (`--timeout`).
- **One browser per profile.** A persistent profile cannot be opened by two
  Chromium instances at once (SingletonLock). Close login fully before running
  extract. If a stale lock remains, remove `SingletonLock`/`SingletonCookie`/
  `SingletonSocket` in the profile dir after killing the old process.

### 2.2 CDP interception (`cdp_extract.mjs`) — the critical pattern

Open the video page with the saved login and a CDP session:

```js
const context = await chromium.launchPersistentContext(PROFILE, { headless: true, ... });
const page = context.pages()[0] || await context.newPage();
const cdp = await context.newCDPSession(page);
await cdp.send('Network.enable');
```

**Event order matters** (getting this wrong was a major time sink):

1. `Network.requestWillBeSent` → record `requestId -> url` for URLs matching
   `/aweme/v1/web/aweme/(detail|post)/`.
2. `Network.responseReceived` → record only `status`/`mimeType`.
   **Do NOT call `getResponseBody` here** — it returns the error
   `"No data found"` because the body isn't ready.
3. `Network.loadingFinished` → **now** call
   `cdp.send('Network.getResponseBody', { requestId })`, parse `body` as JSON,
   grab `aweme_detail`.
4. `Network.loadingFailed` → drop the pending entry.

Extra waits: after `goto(..., {waitUntil:'domcontentloaded'})`, wait ~10–15 s for
the risk-control JS and API calls to complete; a small scroll up/down can trigger
lazy detail requests.

**Fallback:** if no hit was captured, run an in-page
`fetch('/aweme/v1/web/aweme/detail/?aweme_id=...', {credentials:'include'})`
from `page.evaluate()` — the page context already has all cookies and has run
the signing JS, so a relative fetch often succeeds. cdp_extract.mjs does this.

**Anti-detect patches** (in dy_common.mjs `addInitScript`):
`navigator.webdriver = undefined`, fake `plugins` and `languages`. Launch args:
`--no-sandbox`, `--disable-blink-features=AutomationControlled`.

## 3. Chromium setup (Playwright)

- The skill auto-discovers a browser: `DOUYIN_CHROME` env → `/tmp/chrome_path.txt`
  → common macOS/Linux paths → Playwright's bundled executable. Override with
  `DOUYIN_CHROME=/path/to/Chromium`.
- **Playwright's own `npx playwright install chromium` download stalled** in this
  environment. Workaround that worked: download Chromium from the npmmirror
  mirror (`cdn.npmmirror.com`) — a ~130 MB zip (rev 1187, Chromium 140.0.7339.16)
  — with a resumable download, unzip, and pass its binary via `executablePath`.
  Because the Chromium version didn't match Playwright's expected build, always
  launch with an explicit `executablePath` (dy_common handles this) rather than
  relying on the bundled one.
- The working binary path was recorded in `/tmp/chrome_path.txt`; the skill reads
  it as a hint if present, otherwise falls through to other candidates. On a
  fresh machine, set `DOUYIN_CHROME` or install a normal Chrome/Chromium.

## 4. Detail API field schema (verified)

The intercepted JSON's root has `aweme_detail` (or `aweme_list[0]`). Useful fields:

| Field | Meaning | Notes |
|---|---|---|
| `aweme_id` | video id | 15–19 digits |
| `desc` | caption / title text | first line used as TITLE; may be marketing copy ≠ speech |
| `duration` | duration | **milliseconds** (stored as `duration_ms`) |
| `create_time` | publish time | epoch seconds |
| `author.nickname` / `unique_id` / `sec_uid` | author info | |
| `statistics` | likes/comments/shares/collects | `digg_count`, `comment_count`, `share_count`, `collect_count` |
| `video.play_addr.url_list` | **signed play URL(s)** | time-limited; first URL used as VIDEO_URL |
| `video.download_addr.url_list` | watermarked download URL(s) | fallback |
| `video.bitrate_info` | quality variants | may contain higher-res options |
| `video.cover.url_list` | cover images | |
| `music.title` / `music.author` | background music | |
| `images[]` | present for image notes | each with `url_list`, `width`, `height` → `IS_IMAGE=true` |

`cdp_extract.mjs` writes a normalized `detail` object plus shell-friendly lines
(`VIDEO_URL`, `TITLE`, `AUTHOR`, `DURATION_MS`, `IS_IMAGE`, `OK`).

## 5. Download & transcription notes

- **Download:** play URLs are signed and time-limited — resolve and download in
  the same session. `download_video.py` loops `curl -L -C - --retry` until the
  file reaches `Content-Length`. If it stalls, re-run extraction for a fresh URL
  rather than reusing a stale one. (Shared core script `scripts/core/download_video.py`;
  auto-infers Referer from the media host — works for XHS/Douyin/Kuaishou.)
- **Transcription:** `transcribe.py` — `large-v3-turbo`, `device=auto`
  (MPS+float16 on Apple Silicon ≈3.8× faster than CPU int8; falls back to
  CPU+int8). Baked-in fixes: `HF_ENDPOINT=https://hf-mirror.com`, PyAV
  `av.open` monkey-patch stripping `metadata_errors`, MPS-first selection.
  First run downloads ~1.6 GB model. Install: `python3 -m pip install faster-whisper av`.
- **Unclear speech:** restore from context and mark inline; never fabricate.
- **Caption vs content:** Douyin captions are often marketing rewrites — trust
  the transcript, and explicitly note where they differ.

## 6. Troubleshooting quick table

| Symptom | Cause | Fix |
|---|---|---|
| `REASON=NO_LOGIN` | no sessionid in profile | run `login.mjs` |
| User sees no QR window | browser behind other apps | `osascript ... activate`; screenshot to verify |
| `OK=false`, `raw_hits` body len 0 | session expired / risk control | re-login; retry; if persists, video needs higher permission |
| `VERDICT=EMPTY` / `BAD_STATUS` | expired login / risk control returning frozen snapshot | re-login; never trust HTTP 200 alone |
| `Uifid Not Found / Validate Error` | tried pure-HTTP abogus | abandon; use login + CDP |
| `getResponseBody` → "No data found" | called too early | only call in `loadingFinished` |
| Chromium won't launch / version mismatch | wrong binary | set `DOUYIN_CHROME`; use explicit `executablePath` |
| SingletonLock error | two browsers on one profile | close the other; remove lock files after kill |
| **Download 403, 355-byte file** | signed URL needs UA + Referer | fixed in `download_video.py` (sends `-A UA -e referer`) |
| Signed URL 403 on download | URL expired | re-run Step 3 for a fresh URL, download immediately |

## 8. Validity / freshness gate (verdict)

Borrowed from a sibling production skill (see §9). A logged-in browser still
sometimes returns a *frozen snapshot* — status_code 0, plausible JSON, but stale
or empty data — the silent failure mode that is far worse than an outright error.
`cdp_extract.mjs` therefore emits a `VERDICT`:

- `OK` — real `aweme_detail` + `status_code === 0` + play URL present.
- `EMPTY` — `aweme_detail` null (expired login / risk control) → re-login.
- `BAD_STATUS` — `status_code !== 0` → data untrustworthy.
- `NO_PLAY_URL` — image note or no play permission (check `IS_IMAGE`).
- `STALE` — `create_time` implausibly old → suspected frozen snapshot.

A digest should only be written when `VERDICT=OK`. Always surface the verdict in
the final report so stale data can't masquerade as fresh.

## 9. Cross-skill lessons (sibling agent `douyin-kuaishou-blogger-intel`)

A parallel skill that runs a daily finance-digest pipeline was cross-checked.
Its hard-won lessons, now absorbed here:

1. **Active in-page `fetch` beats passive CDP capture when available.** That
   skill runs `fetch(url, {credentials:'include'})` inside `agent_browser_eval`:
   simpler timing than CDP's getResponseBody (which we hit "No resource with
   given identifier found" 3×). Our `cdp_extract.mjs` keeps CDP for
   self-containment but already has the same in-page fetch as a fallback — if
   your agent exposes a browser-eval tool, prefer it as the primary path.
2. **Never judge login by cookie alone.** `sessionid`/`sid_tt` are HttpOnly
   (invisible to `document.cookie`); `profile/self` returning status 8 is also
   unreliable. The reliable test is whether the API returns *today's* data.
   Our verdict gate (§8) encodes this.
3. **Big browser return values get truncated (~31k chars).** A 20-item list with
   play URLs exceeds 50k. That skill has the browser write a Blob via
   `<a download>` and returns only a short status string. If you add batch/list
   extraction, do the same — don't pull large JSON through the eval return.
4. **Download needs UA + Referer, no cookie.** Confirmed independently today:
   plain `curl` on a signed play URL → 355-byte 403 page; with `-A <Chrome UA>
   -e https://www.douyin.com/` → full 19 MB video. Fixed in `download_video.py`.
5. **Filter pinned/old videos (`duration === 0`) and image posts (no
   `video.play_addr`)** in batch/list workflows, else ffmpeg fails. Relevant
   when extending to a per-author feed (see §10).
6. **ASR alternative: mlx-whisper** (Apple Silicon native, ~5× realtime) exists
   in the sibling skill's `finance/asr/.venv`; our `transcribe.py` uses
   faster-whisper (MPS ~3.8× faster than CPU). Both are local; pick per machine.

## 10. This is now part of the `social-media-extractor` skill family

The two former standalone skills (`xhs-video-extractor`, `douyin-video-extractor`)
have been consolidated into ONE skill with a shared core and thin platform
adapters. This file is now `references/douyin.md` in that unified skill:

```
social-media-extractor/
  SKILL.md                 domain routing + common workflow
  references/{xhs,douyin,kuaishou}.md
  scripts/
    core/    download_video.py (UA+Referer, auto-inferred) · transcribe.py · md_to_html.py
    xhs/     fetch_xhs.py · download_images.py · ocr_images.py · ocr_vision.swift
    douyin/  resolve_link.mjs · login.mjs · cdp_extract.mjs · dy_common.mjs
    kuaishou/ resolve_kuaishou.mjs
```

The three core scripts are now a single source of truth — fixes apply once.
Kuaishou share pages (`https://v.m.chenzhongtech.com/fw/photo/<id>`) expose
`mainMvUrls[0].url`, downloadable with plain curl — a thin adapter. Per-author
feeds are NOT yet solved for Kuaishou.

## 7. Environment used when authoring

- macOS (darwin), Apple Silicon (arm64), Node.js 22, Playwright 1.52,
  Chromium 140.0.7339.16 (npmmirror rev 1187), Python 3.13.
- Verified end-to-end: short link → aweme_id; login + sessionid capture; CDP
  detail interception (VERDICT=OK, status_code=0); UA+Referer download (full
  19,795,272-byte video, not the 355-byte 403 page); faster-whisper MPS
  transcription (308 segments / 47s for a 7:57 video). All failure modes above
  were observed directly.
- If `OK=false` persists after a confirmed login, inspect `raw_hits`/`fallback`
  in the output JSON and revisit §2.2.
