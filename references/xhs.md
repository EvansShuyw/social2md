# Field schema, verified pitfalls & environment notes

Detailed notes for debugging `fetch_xhs.py` and `transcribe.py`. Load this file
only when a link fails to parse, a field is missing, or transcription breaks.

## 1. Link resolution

- Accept both `https://xhslink.cn/o/<token>` short links and full
  `https://www.xiaohongshu.com/explore/<24-hex-id>?xsec_token=...` URLs.
- A **mobile User-Agent is mandatory**. With a desktop UA, XHS often serves a
  login/anti-bot page without `__INITIAL_STATE__`. The fetch script sets an
  iPhone Safari UA (see `MOBILE_UA`).
- Resolution follows HTTP 302 redirects. `urllib.request.urlopen` follows them
  automatically. If the environment blocks urllib but allows curl, the script's
  error message suggests falling back to curl or pasting a full note URL.

## 2. `__INITIAL_STATE__` structure

The page embeds `window.__INITIAL_STATE__ = { ... };` (a JS object literal).
Parse with a brace-balancing scanner that respects strings and escapes, then
`json.loads`. **Before decoding, replace bare `undefined` with `null`** — XHS
emits bare `undefined` which is not valid JSON.

Verified data paths (as of the notes processed when authoring this skill):

```
state["noteData"]["data"]["noteData"]                  -> note detail
state["noteData"]["data"]["commentData"]["comments"]   -> top-level comments (+ subComments)
```

Note detail fields:

| Field | Meaning | Notes |
|---|---|---|
| `noteId` / `id` | 24-hex note id | |
| `title` / `displayTitle` | note title | |
| `desc` | body text (caption) | may be marketing copy ≠ video content |
| `user.nickName` | author nickname | **capital N** — not `nickname` |
| `user.userId` | author id | |
| `interactInfo.likedCount` / `collectedCount` / `commentCount` / `shareCount` | stats | values are strings |
| `type` | `video` or `normal` | `normal` = image/text note (图文) |
| `video.media.stream` | video streams | `h264` / `h265` / `av1`, each a list |
| `video.media.duration` | duration | may be in ms (e.g. 3323264 ≈ 55 min) — do not trust as seconds |
| `imageList[]` | images | see "Image fields" below |

Comment fields: `user.nickName` (capital N), `content`, `likeCount`, `time`
(epoch ms), `subComments[]` with the same shape.

### Image fields (图文 notes)

Each `imageList[]` item:

| Field | Meaning |
|---|---|
| `url` / `urlDefault` | primary image URL (often with `!h5_1080jpg` processing suffix) |
| `urlPre` | preview variant |
| `infoList[]` | scene-specific URLs: `imageScene` (`H5_DTL`, `H5_PRV`, `WB_DFT`, …) + `url` |
| `width` / `height` | pixel dimensions |
| `fileId` | stable file identifier |
| `livePhoto` | whether it is a Live Photo |

`fetch_xhs.py` flattens these into `image_list[].urls` (ordered candidates) and
`image_list[].scenes` (scene→URL map). `download_images.py` prefers the
`H5_DTL`/`WB_DFT` detail-scene URL (full quality) over `H5_PRV`/`style_` previews.
Image URLs are signed + time-limited (timestamp in path) — download promptly.

Stream selection: prefer `h264` (broadest compatibility), then largest
`width*height`. Each stream item's direct URL key is `masterUrl`.

## 3. Video download pitfalls

- XHS CDN (`sns-video-*.xhscdn.com`) is flaky — `curl` frequently exits with
  code 18 (partial transfer). A single `curl` call is not enough.
- The working approach: loop `curl -L -C -` (resume) until the local file size
  reaches the `Content-Length` from a HEAD request. `download_video.py` does
  this, defaulting to 20 attempts, 120 s per attempt.
- If curl is unavailable, a pure-Python `Range: bytes=<start>-` downloader is
  used as fallback.
- `masterUrl` carries `sign` + `t` (expiry) query params — **it goes stale**.
  Always fetch a fresh URL right before downloading. Do not save URLs in the
  digest or rely on a URL captured much earlier.
- Expected sizes seen in practice: ~125 MB and ~155 MB for ~55-min 720p videos.

## 4. Local transcription pitfalls (all baked into transcribe.py)

- **HuggingFace direct connect times out** in CN environments. Set
  `HF_ENDPOINT=https://hf-mirror.com` *before* importing faster_whisper /
  huggingface_hub. `hf-mirror.com` was verified reachable; `modelscope.cn` was
  an alternative but not needed. `transcribe.py` sets the env var itself via
  `os.environ.setdefault`, so no need to prefix the command manually (still fine
  to do).
- **PyAV incompatibility**: PyAV 19+ removed the `metadata_errors` kwarg that
  faster-whisper still passes to `av.open`, causing an immediate crash.
  `transcribe.py` monkey-patches `av.open` to strip that kwarg. This is the
  single most important fix — do not remove it.
- **Device / speed (2026-11-16 benchmark)**: `device="auto"` (the default) picks
  **MPS + float16 on Apple Silicon**, falling back to CPU+int8 if MPS fails.
  MPS is ~3.8x faster than CPU int8 with equivalent quality — benchmarked on a
  3-min clip: CPU int8 39.9s (RTF 0.222) vs MPS float16 10.5s (RTF 0.058),
  98.5% word-level similarity between outputs (MPS even fixed some CPU ASR
  errors like "classical"→"cloud sql"). A full 12-min video transcribes in
  ~40s end-to-end on M6; extrapolating, a 55-min video ~3 min (was ~12 min on
  CPU). `int8`/`int8_float16` on MPS silently resolve to float16 anyway. VAD
  filtering and beam_size=1 give little extra. `large-v3-turbo` remains the
  best speed/accuracy model. On non-Apple hardware, auto falls back to CPU.
- **Language**: auto-detection works; a RED video caption in Chinese can hide
  an English talk — detection reported `en` at 100% and produced correct
  English text. Force `--language zh|en` only if auto-detection is wrong.
- **Unclear segments**: multi-speaker overlaps / accents occasionally produce
  garbled output. These are rare; restore from surrounding context and mark the
  restoration inline. Never invent content.
- Model download is ~1.6 GB on first run; ensure disk/network. Install deps with
  `python3 -m pip install faster-whisper av`.

## 5. Image OCR pitfalls (图文 notes)

- **Apple Vision is the OCR engine.** `ocr_vision.swift` uses `VNRecognizeTextRequest`
  with `recognitionLevel = .accurate`, `usesLanguageCorrection = true`, and
  `recognitionLanguages = ["zh-Hans", "en-US"]`. It handles Simplified Chinese
  well and needs no model download and no network.
- **Compile once, cache the binary.** `ocr_images.py` runs
  `swiftc -O ocr_vision.swift -o ocr_vision` on first use; the binary sits next
  to the Swift source. Requires macOS + Xcode command-line tools (`swiftc`).
  Verified: `/usr/bin/swiftc` present; a real test image yielded "小红书 / SPACEX".
- **Non-macOS fallback.** If `swiftc` is missing, `ocr_images.py` writes a
  skeleton listing image paths instead of failing — the agent should then read
  the images with its own multimodal vision capability.
- **Batch protocol.** The Swift tool prints `@@PATH@@<path>` markers and a
  `<<<XHS_OCR_IMAGE>>>` separator between images; `ocr_images.py` parses these
  into per-image blocks. Don't change the markers without updating both files.
- **Quality caveats.** Text rendered artistically, vertically, or at low contrast
  can OCR imperfectly. Images may genuinely contain no text. Always cross-check
  with the note `desc` and comments, and use the agent's own vision on any image
  whose OCR looks suspicious.
- Image download: `download_images.py` uses `curl -A <mobile UA>` with retries;
  treats files >1 KB as success. Image CDN URLs carry expiring signatures too.

## 6. Environment used when authoring

- macOS (darwin), Apple Silicon (arm64), Python 3.13.
- `curl` at `/usr/bin/curl`; `swiftc`/`swift` at `/usr/bin/`; no `tesseract`.
- Verified end-to-end on two ~55-min RED videos (note ids
  `6af6a770000000002b01bfc3`, `6afada97000000001f016b6a`), producing 743 and
  1048 transcript segments respectively — confirming the pipeline is reusable.
- Image pipeline verified: fetch (rich image fields) → download_images → ocr_images
  on a real RED note's cover image, Chinese + English OCR confirmed working.
