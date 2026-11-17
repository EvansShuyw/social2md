# Kuaishou adapter notes

Platform reference for `social-media-extractor`. Load this when the link is a
Kuaishou (快手) share link. This is the thinnest of the three adapters.

## Link forms

- Share link: `https://v.m.chenzhongtech.com/fw/photo/<photoId>` (mobile share page).
- Also seen: `https://www.kuaishou.com/short-video/<photoId>`,
  `https://v.kuaishou.com/<token>` (short link → 302 to one of the above).
- `<photoId>` is a long digit string.

## Verified data path

Per a sibling production skill that ran this in a daily pipeline:

- The share page `https://v.m.chenzhongtech.com/fw/photo/<photoId>` exposes the
  media URL at **`mainMvUrls[0].url`** (in the page's rendered state / API response).
- That URL is downloadable with **plain curl** — a browser UA is sufficient;
  **no login cookie needed** (unlike Douyin). The shared core `download_video.py`
  auto-infers referer `https://www.kuaishou.com/` for chenzhongtech/kuaishou hosts.
- Kuaishou videos are often long (e.g. 180 s) — use background execution for
  download + ASR.

## Not supported

- **Per-author feed listing is NOT solved for Kuaishou.** If the task needs "all
  videos from author X", use their Douyin profile instead (many creators cross-post
  the same video to both). A Kuaishou link only works when the user supplies it directly.
- No image/图文 pipeline for Kuaishou in this skill.

## How the adapter works

`scripts/kuaishou/resolve_kuaishou.mjs` opens the share page in a headless browser
(Playwright, with basic anti-detect), then tries, in order:

1. Read rendered page state (`window.__APOLLO_STATE__` / `_ROUTER_DATA` /
   any global containing `mainMvUrls` or a `photoId`-keyed object) via
   `page.evaluate()`.
2. CDP-intercept the page's own `graphql` / `photo` API responses and search the
   JSON bodies recursively for `mainMvUrls`.
3. Fall back to the `<video>` element's `src`/`currentSrc`.

It writes a normalized JSON with `MEDIA_URL`, `TITLE`, `AUTHOR`, `DURATION_MS`,
`VERDICT` and the same shell-friendly KEY=value lines as the other adapters, so
the common workflow (core download → transcribe → digest → HTML) is identical.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `VERDICT=EMPTY` | share page blocked / needs JS / region | retry with a full share link; check page in a real browser |
| Media URL 403 on download | URL expired or hotlink-protected | re-run resolver for fresh URL; core sets UA + kuaishou referer |
| Short link won't resolve | token expired | ask user for the direct `/fw/photo/<id>` link |
| Browser won't launch | Playwright/Chromium missing | set `DOUYIN_CHROME=/path` (shared with douyin adapter) |

## Verified quirks from a live link (2026-11-16)

Tested on `https://v.kuaishou.com/nXJUt81w` (高鑫屈 gold analysis), full chain
resolve → download → transcribe → digest passed:

- The share page 302s to `v.m.chenzhongtech.com/fw/photo/<photoId>?...&photoId=<id>`.
- **Media host is `*.kwimgs.com`** (e.g. `s1-111422.kwimgs.com`). Added to core
  `auto_referer()` so it maps to `https://www.kuaishou.com/` — without the match it
  fell back to the media host itself (download still worked, but the fix is cleaner).
- **CDP `getResponseBody` on the `recommend/photos` API returned nothing** in this
  test (streaming/timing). The media URL came from the rendered page state instead.
  So Strategy 1 (page globals) is the workhorse; CDP is a fallback only.
- **Metadata is in the visible DOM, not `<title>`** (`<title>` is just "快手").
  The caption renders as one line `"<author>：<title>#topic..."` (e.g.
  `高鑫屈：今日黄金，趋势解读#金价#黄金#高鑫屈`). The resolver now:
  - picks the longest `#`-containing DOM line as TITLE,
  - takes the text before `：` as AUTHOR (fallback: line after a standalone `@`),
  - extracts `photoId` from the final URL's query param (a base36 id like
    `3xqc677bz4f9y2y`, NOT all digits).

## Verification status

End-to-end verified on a live link: resolver returned `VERDICT=OK` with a valid
`kwimgs.com` MP4 URL and correct title/author; core download fetched the full
23,886,029-byte video; core transcribe produced 94 segments. If `VERDICT=EMPTY`
on a valid link, inspect `api_hit_count` and the page structure — the page state
shape is the variable part.
