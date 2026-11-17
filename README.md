# social2md

[English](README.md) · [中文](README.zh-CN.md)

**A share link in, a complete structured document out.**

Turn Xiaohongshu (RED), Douyin, and Kuaishou share links into structured Markdown with the **full video transcript, text from images, and key details** — plus a styled HTML preview. Not just the title and caption.

- **Douyin**: Scan a QR code once. The logged-in browser signs its own requests and CDP captures the data — no reverse-engineering `a_bogus`, no hand-maintained cookies.
- **Image notes**: Apple Vision OCR extracts text baked into images.
- **One skill, every agent**: Auto-discovered by Claude Code, Codex, WorkBuddy, Pi, Hermes, and OpenClaw.
- **Fully local**: faster-whisper transcription, Apple Vision OCR, and Markdown→HTML all run on your machine. Nothing is uploaded to third parties.

---

## Why this exists

You find a useful video or image post. Usually you have three bad options:

1. Download the video — a folder of mp4s you never reopen.
2. Copy the title and caption — the real substance is spoken or baked into images, and you lose all of it.
3. Use an online parser — your content goes to someone else's server, and the API breaks whenever they feel like it.

Existing open-source tools either cover only YouTube/TikTok, stop at downloading, or make you reverse-engineer signatures and babysit cookies. `social2md` is the **fourth option**: give it a link, get back a document you can actually read, search, and hand to an agent.

## How it compares

Public information as of 2026-11, an honest comparison:

| Project | Stars | Coverage | Speech-to-text | Image OCR | Login |
|---|---:|---|---|---|---|
| **social2md** | — | Xiaohongshu + Douyin + Kuaishou | Local faster-whisper | **Apple Vision** | Douyin QR once, others none |
| `chubbyguan/chubbyskills` | ~1300 | 10+ CN platforms + knowledge base | Captions first + ASR | None | XHS needs your own cookie |
| `JimmySadek/video-fetcher-to-markdown` | ~530 | YouTube / IG / TikTok / X | Local Whisper | Video frames | Varies by site |
| `chenxiachan/xhs-claude-skills` | ~430 | Xiaohongshu only | Partial | Not a focus | Claude Code only |
| `putyy/res-downloader`, `JoeanAmier/XHS-Downloader` | 13k–21k | Many platforms | No | No | Mostly downloaders |

In short: **downloaders don't produce content, English-first tools don't cover Chinese platforms, and Chinese knowledge-base tools skip OCR and make you manage cookies.** We fill the gap in the middle.

## Supported platforms

| Platform | Link formats | Login | Output |
|---|---|---|---|
| Xiaohongshu (RED) | `xhslink.cn`, `xiaohongshu.com` | None | Video transcript / image OCR / structured doc |
| Douyin | `v.douyin.com`, `douyin.com`, 15–19 digit aweme_id | **One-time QR scan** | Video transcript / structured doc |
| Kuaishou | `v.kuaishou.com`, `kuaishou.com` | None | Video transcript / structured doc |

> Some older Xiaohongshu notes without `xsec_token` fail to parse — grab a fresh share link from the app. Platform internals change; if a fetch fails, re-run the adapter to get a new signed URL.

---

## Quick start

### 1. Install

```bash
git clone https://github.com/EvansShuyw/social2md.git
cd social2md
python3 -m pip install faster-whisper av
```

The first transcription downloads a ~1.6 GB model from `hf-mirror`. If you're in mainland China, set:

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

Let your agent framework discover the skill — run the one-shot script to symlink it into all 8 framework paths (idempotent, safe to re-run):

```bash
chmod +x install.sh && ./install.sh
```

Or link just the framework you use:

```bash
ln -s "$(pwd)" ~/.claude/skills/social2md           # Claude Code
ln -s "$(pwd)" ~/.codex/skills/social2md            # Codex
ln -s "$(pwd)" ~/.workbuddy/skills/social2md        # WorkBuddy
ln -s "$(pwd)" ~/.hermes/skills/social2md           # Hermes
```

No hardcoded `/Users/...` paths — clone it anywhere.

> The repo root *is* the skill directory. `SKILL.md` already declares `name: social2md`.

### 2. One-time Douyin login

```bash
node scripts/douyin/login.mjs --timeout 600
```

A browser window opens with a QR code — scan it with the Douyin app. Codes expire in ~2–3 minutes and refresh automatically. Login state is stored in `~/.workbuddy/douyin-profile` (override with `DOUYIN_PROFILE`).

> If you don't see the window, it may be behind another app. The script tries to activate the browser; you can also switch to it manually.

### 3. Run a link

```bash
# Xiaohongshu: fetch metadata first
python3 scripts/xhs/fetch_xhs.py "<XHS link>" --out note.json

# Douyin: short link -> aweme_id -> CDP interception
node scripts/douyin/resolve_link.mjs "<Douyin share link>"
node scripts/douyin/cdp_extract.mjs "<aweme_id or link>" --out meta.json

# Kuaishou: parse directly from the share page
node scripts/kuaishou/resolve_kuaishou.mjs "<Kuaishou link>" --out meta.json
```

Once you have the signed media URL: download, transcribe, render:

```bash
python3 scripts/core/download_video.py "<SIGNED_URL>" --out media.mp4
python3 scripts/core/transcribe.py media.mp4 --out-prefix transcript
python3 scripts/core/md_to_html.py digest.md --out digest.html \
    --title "Title" --subtitle "Author · Source" --theme blue
```

Image/text notes take a different branch:

```bash
python3 scripts/xhs/download_images.py note.json --out-dir images
python3 scripts/xhs/ocr_images.py images/manifest.json --out ocr.txt
```

Then turn the OCR text + metadata into a structured Markdown digest.

**In normal use you don't type these commands.** Give the link to any agent with this skill installed — it routes by domain, loads the right platform reference, runs the pipeline, and produces the document. The commands above are for manual invocation and hacking.

---

## What you get

- `digest.md` — a structured Chinese digest: key conclusions, themed sections, timestamped passages, terminology and figures, flagged uncertainties.
- `digest.html` — a styled reading version in blue / orange / green themes.
- `transcript.txt` / `transcript.srt` — timestamped transcript and subtitles.
- `ocr.txt` — text extracted from images in image notes (macOS).

Caption ≠ content. The digest explicitly flags where a clickbait title diverges from the actual content. Nothing is fabricated. Finance-related figures are marked for verification against live market data.

## How it works

```
share link
  → platform adapter (Xiaohongshu / Douyin / Kuaishou)
      → metadata + signed media URL
  → shared core: resumable download (UA + Referer auto-inferred)
  → local faster-whisper ASR / local Apple Vision OCR
  → structured Markdown → styled HTML
```

Key design decisions:

- **Single source of truth**: download, transcription, and HTML rendering live in `scripts/core/` — one fix benefits all three platforms. Platform differences stay in thin adapters.
- **No signature reverse-engineering**: a logged-in browser signs its own requests; CDP captures responses after `loadingFinished`, sidestepping `a_bogus`, `msToken`, and ArgusSecurity.
- **Silent-failure guard**: an expired Douyin login returns plausible-looking stale JSON. `cdp_extract.mjs` emits `VERDICT=OK/EMPTY/BAD_STATUS/NO_PLAY_URL/STALE` — only `OK` is safe to continue.
- **CDN quirks**: Douyin's signed play URL returns a 355-byte 403 HTML page without a browser UA + Referer. The core script handles this by default.

Full pitfall notes for each platform live in `references/`, loaded on demand so they don't eat your context.

## Agent framework support

The skill follows the open Agent Skills convention (`SKILL.md` + YAML frontmatter + `references/` + `scripts/`). Verified or officially symlink-compatible:

| Framework | Directory |
|---|---|
| WorkBuddy | `~/.workbuddy/skills/` |
| Claude Code | `~/.claude/skills/` |
| Codex | `~/.agents/skills/`, `~/.codex/skills/` |
| Pi | `~/.agents/skills/`, `~/.pi/agent/skills/` |
| DeepSeek Harness | `~/.agents/skills/`, `~/.dsh/skills/` |
| OpenClaw | `~/.openclaw/workspace/skills/` |
| Hermes | `~/.hermes/skills/` |

`~/.agents/skills/` is the shared scan root for Codex, Pi, and DeepSeek Harness — one link covers all three.

## Requirements

| Need | Dependency |
|---|---|
| Local transcription | Python 3.10+, `faster-whisper`, `av`; ~1.6 GB model on first run |
| Image OCR | macOS + Xcode command-line tools (`swiftc`); on other OSes, use your agent's own vision capability |
| Douyin / Kuaishou | Node.js 22+, Chrome/Chromium, Playwright |
| Download | `curl` (with a pure-Python Range fallback built in) |

Browser path is auto-discovered, or set explicitly:

```bash
export DOUYIN_CHROME=/path/to/Chromium
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Douyin returns stale or empty data | Login expired or risk control triggered — check `VERDICT` | Re-run `login.mjs` |
| Downloaded file is 355 bytes | 403 HTML mistaken for video | Use the core script, not bare `curl` |
| Xiaohongshu parse fails | Link missing `xsec_token` | Get a fresh in-app share link |
| Kuaishou title missing | Share-page structure changed | The script falls back to DOM extraction; update the adapter if needed |
| `metadata_errors` on transcription | PyAV 19+ vs faster-whisper incompatibility | Core script has a built-in patch |
| `SingletonLock` error | Two browsers on one profile | Close the other; remove lock files |
| QR code not visible | Window hidden behind another app | Switch to the browser window; it refreshes every ~100s |

## Privacy and safety

- Transcription, OCR, and HTML rendering are all local. Audio, video, and images are never uploaded to third parties.
- The Douyin login profile lives only on your machine. Never commit or share that directory.
- Before publishing a fork, check for stray `*.env`, cookies, tokens, or personal open_ids.
- Platform links and interfaces belong to their respective owners. This project is unaffiliated and unendorsed. Use it lawfully and respect platform terms.

## Project structure

```
social2md/
├── SKILL.md                    Agent entry point: routing + common workflow
├── references/
│   ├── xhs.md                  Xiaohongshu pitfalls and field schema
│   ├── douyin.md               Anti-bot, CDP timing, login, verdict gate
│   └── kuaishou.md             Share-page parsing fallbacks
├── scripts/
│   ├── core/                   Download / transcribe / HTML (shared)
│   │   ├── download_video.py
│   │   ├── transcribe.py
│   │   └── md_to_html.py
│   ├── xhs/                    fetch_xhs.py · download_images.py · ocr_images.py · ocr_vision.swift
│   ├── douyin/                 resolve_link.mjs · login.mjs · cdp_extract.mjs · dy_common.mjs
│   └── kuaishou/               resolve_kuaishou.mjs
├── install.sh                  One-shot symlink into all agent frameworks
├── LICENSE
└── .gitignore
```

## Roadmap

- [ ] Caption-first path (skip Whisper when official subtitles exist)
- [ ] More platforms: Bilibili / WeChat Official Accounts / Weibo
- [ ] Structured output fields (YAML frontmatter) for Obsidian / Dataview
- [ ] Finance-specific figure verification and terminology dictionary
- [ ] One-command `npx skills add` install

## Contributing

Issues and PRs are welcome. New platforms should follow the thin-adapter + shared-core pattern, and pitfalls belong in `references/<platform>.md` so nobody has to rediscover them. Before submitting: test the commands, replace personal paths, and never commit cookies, tokens, or collected content.

## License

MIT — see [LICENSE](LICENSE).

---

> If this saved you time, a star helps others find it. The problem is simple: keep the content you scroll past, instead of losing it.
