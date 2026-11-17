---
name: social2md
description: Turn Xiaohongshu / 小红书, Douyin / 抖音 and Kuaishou / 快手 share links into complete structured Chinese Markdown plus a styled HTML preview. Resolves the link, obtains metadata + signed media URL, downloads with resume-on-interrupt, transcribes speech locally with faster-whisper or OCRs text-in-image with Apple Vision. Routes by domain to a thin platform adapter over a shared core. Handles flaky CDNs, Douyin anti-bot (ArgusSecurity / a_bogus / uifid login wall), HF mirror, PyAV compatibility, and silent-frozen-snapshot pitfalls learned the hard way. Use whenever a user gives an xhslink.cn / xiaohongshu.com / v.douyin.com / douyin.com / kuaishou link and asks to 提炼/总结/转录/看内容/整理成文档/提取文案字幕/看图文. Douyin needs ONE-TIME interactive QR login; XHS and Kuaishou need no login.
agent_created: true
---

# Social Media Extractor

## Overview

One skill, three platforms, one shared core. Turn a share link from Xiaohongshu
(RED), Douyin, or Kuaishou into a structured Chinese digest + styled HTML preview.
Everything is local (no cloud upload): local faster-whisper ASR, local Apple
Vision OCR, local Markdown→HTML.

```
scripts/
  core/       download_video.py · transcribe.py · md_to_html.py   (shared, platform-agnostic)
  xhs/        fetch_xhs.py · download_images.py · ocr_images.py · ocr_vision.swift
  douyin/     resolve_link.mjs · login.mjs · cdp_extract.mjs · dy_common.mjs
  kuaishou/   resolve_kuaishou.mjs
references/   xhs.md · douyin.md · kuaishou.md                    (load per platform)
```

The core scripts are the single source of truth — a fix applies to all platforms.
`download_video.py` auto-infers the Referer from the media host (douyin/xhscdn/
kuaishou), so it works everywhere without per-platform flags.

## Routing: pick the platform by link

| Link contains | Platform | Adapter | Login? | Reference |
|---|---|---|---|---|
| `xhslink.cn`, `xiaohongshu.com`, `xhs` | 小红书 | `scripts/xhs/` | No | `references/xhs.md` |
| `v.douyin.com`, `douyin.com`, `iesdouyin.com`, 15–19 digit aweme_id | 抖音 | `scripts/douyin/` | **Yes (one-time QR)** | `references/douyin.md` |
| `v.m.chenzhongtech.com`, `kuaishou.com`, `chenzhongtech` | 快手 | `scripts/kuaishou/` | No (share page) | `references/kuaishou.md` |

If the input is a bare 15–19 digit number, treat it as a Douyin aweme_id. If the
domain is unrecognized, ask the user for a direct share link.

**Before platform-specific work, load that platform's reference file** — it holds
the verified field schema, pitfalls, and troubleshooting. Load only one.

## Common workflow (all platforms)

1. **Route** by domain (table above). Load the matching `references/<platform>.md`.
2. **Fetch metadata + media URL** via the platform adapter (see below).
3. **Download media** with the shared core:
   ```bash
   python3 <skill>/scripts/core/download_video.py "<SIGNED_URL>" --out /path/media.mp4
   ```
   Resumes on interruption; UA + Referer are handled automatically. Prints `FINAL=<bytes>`.
4. **Extract text** — speech → `transcribe.py`; text-in-image → `ocr_images.py`.
5. **Write digest** — thorough Chinese Markdown, preserve source terminology,
   include timestamps, flag uncertain/失真 segments, note where the caption differs
   from the real content. Never fabricate.
6. **Render HTML** with the shared core:
   ```bash
   python3 <skill>/scripts/core/md_to_html.py /path/digest.md --out /path/digest.html \
       --title "标题" --subtitle "来源/作者" --theme blue|orange|green --foot "…"
   ```
7. **Deliver** HTML preview + Markdown source + transcript/OCR text. Keep the chat
   reply concise; the HTML holds the full content.

## Platform quick-start

### 小红书 (XHS) — no login

Video and image/text notes are two branches; type is auto-detected.

```bash
python3 <skill>/scripts/xhs/fetch_xhs.py "<LINK>" --out /path/note.json
# VIDEO_URL non-empty -> video branch; else IMAGE_COUNT>0 -> 图文 branch
```
- Video: download via core `download_video.py` → `transcribe.py` → digest.
- 图文: `download_images.py note.json --out-dir /path/images` →
  `ocr_images.py /path/images/manifest.json --out /path/images/ocr.txt` → digest.
- **Mobile UA is mandatory**; `__INITIAL_STATE__` uses bare `undefined` → `null`;
  author field is `nickName` (capital N). Signed media URLs expire — download promptly.

### 抖音 (Douyin) — one-time QR login required

Douyin cannot be scraped anonymously. Do NOT reverse-engineer signatures
(anonymous detail API → HTTP 200 empty body; abogus → `Uifid Not Found`). Let a
logged-in browser sign its own requests.

```bash
# One time only (QR scan):
node <skill>/scripts/douyin/login.mjs --timeout 600
# Every video:
node <skill>/scripts/douyin/resolve_link.mjs "<SHARE_LINK>"
node <skill>/scripts/douyin/cdp_extract.mjs "<SHARE_LINK_OR_ID>" --out /path/meta.json
```
**Only proceed when `VERDICT=OK`** (other verdicts: EMPTY/BAD_STATUS/NO_PLAY_URL/STALE
= expired login, risk control, or frozen snapshot — re-login, never trust a bare 200).
Then download `VIDEO_URL` via core → `transcribe.py` → digest. Login profile persists
in `~/.workbuddy/douyin-profile` (override with `DOUYIN_PROFILE`). Full details in
`references/douyin.md`.

### 快手 (Kuaishou) — share page, no login

```bash
node <skill>/scripts/kuaishou/resolve_kuaishou.mjs "<SHARE_LINK>" --out /path/ks_meta.json
```
Resolves the share page → `mainMvUrls[0].url` → core `download_video.py` →
`transcribe.py` → digest. Per-author feeds are NOT supported. See `references/kuaishou.md`.

## Important notes / pitfalls (shared)

- **Caption ≠ content.** Extract the actual media (video speech / image text);
  captions are often marketing rewrites. Say so explicitly when they differ.
- **Time-limited signed URLs.** Resolve and download in the same session; stale
  URLs 403. Re-run the adapter's fetch step for a fresh URL.
- **Resumable download is mandatory.** All three CDNs drop connections; core
  `download_video.py` loops `curl -C -`. A 355-byte "success" on Douyin is the 403
  HTML page — fixed by auto Referer.
- **Large media / long ASR** → run in background and poll; first Whisper run
  downloads ~1.6 GB (`HF_ENDPOINT` mirror + PyAV patch baked into `transcribe.py`).
- **macOS-only OCR** (Apple Vision). On other OS, `ocr_images.py` writes a skeleton;
  read images with the agent's own vision capability.
- **Douyin silent failure.** An expired login returns plausible JSON with stale
  data — the `VERDICT` gate exists to catch it. Never skip it.
- **Douyin QR window hidden** behind other apps → script calls `osascript activate`;
  screenshot to verify. QR expires ~2–3 min → auto-refresh. One browser per profile.

## Resources

- `scripts/core/*` — shared download (UA+Referer, auto-inferred), local ASR, HTML renderer.
- `scripts/xhs/*` — XHS metadata fetch + image download + Apple Vision OCR.
- `scripts/douyin/*` — link resolve + QR login + CDP detail interception with verdict gate.
- `scripts/kuaishou/*` — share-page media URL resolver.
- `references/xhs.md`, `references/douyin.md`, `references/kuaishou.md` — per-platform
  field schemas, verified pitfalls, and troubleshooting. **Load before debugging.**
