#!/usr/bin/env python3
"""Fetch a Xiaohongshu (RED) note page and extract structured metadata.

Given a Xiaohongshu share link (short xhslink.cn URL or a full
xiaohongshu.com/explore/<id> URL), this script:

  1. Resolves the link with a mobile User-Agent (required for XHS to serve
     the __INITIAL_STATE__ payload).
  2. Parses window.__INITIAL_STATE__ with a brace-balancing scanner.
  3. Extracts note id, title, body text, author, interaction counts, comments,
     and — when the note is a video — the best direct video stream URL.

It writes a JSON file and also prints shell-friendly KEY=value lines so an
agent can consume the values without parsing JSON.

Usage:
    python3 fetch_xhs.py "https://xhslink.cn/o/XXXX" --out /path/note.json

Important: direct video URLs carry a time-limited signature. Download the
video right after fetching; do not cache the URL for later reuse.
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.error

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def fetch_html(url: str, timeout: int = 30) -> str:
    """Resolve redirects and return the final HTML with a mobile UA."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        # Some environments get a 4xx from urllib but curl still works; fall back.
        raise RuntimeError(f"HTTP {e.code} fetching {url}: {e.reason}")
    # XHS pages are UTF-8; ignore isolated decode errors.
    return raw.decode("utf-8", errors="ignore")


def extract_initial_state(html: str):
    """Extract and JSON-decode window.__INITIAL_STATE__ from page HTML."""
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*", html)
    if not m:
        raise RuntimeError(
            "window.__INITIAL_STATE__ not found. XHS may be serving an anti-bot "
            "or login page; try again or open the link in a browser and paste "
            "a full xiaohongshu.com/explore/<id> URL."
        )
    start = m.end()
    depth = 0
    in_str = False
    esc = False
    end = None
    for j in range(start, len(html)):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
    if end is None:
        raise RuntimeError("Unbalanced braces while parsing __INITIAL_STATE__.")
    raw = html[start:end]
    # XHS JS state contains bare `undefined`, which is not valid JSON.
    raw = re.sub(r"\bundefined\b", "null", raw)
    return json.loads(raw)


def pick_best_stream(video_media: dict):
    """Choose the highest-resolution direct stream, preferring H.264."""
    stream = video_media.get("stream", {}) or {}
    candidates = []
    for codec in ("h264", "h265", "av1"):
        for item in stream.get(codec, []) or []:
            if item.get("masterUrl"):
                candidates.append((codec, item))
    if not candidates:
        return None
    # Prefer h264 for compatibility, then largest pixel area.
    codec_priority = {"h264": 0, "h265": 1, "av1": 2}

    def rank(pair):
        codec, item = pair
        area = (item.get("width") or 0) * (item.get("height") or 0)
        return (codec_priority.get(codec, 9), -area)

    codec, item = sorted(candidates, key=rank)[0]
    return {
        "codec": codec,
        "url": item.get("masterUrl"),
        "width": item.get("width"),
        "height": item.get("height"),
        "duration": item.get("duration") or video_media.get("duration"),
    }


def parse_note(url: str) -> dict:
    html = fetch_html(url)
    state = extract_initial_state(html)
    try:
        note = state["noteData"]["data"]["noteData"]
    except (KeyError, TypeError):
        raise RuntimeError(
            "noteData not present in __INITIAL_STATE__; the link may not be a "
            "note page or may require login."
        )

    user = note.get("user", {}) or {}
    interact = note.get("interactInfo", {}) or {}
    media = (note.get("video", {}) or {}).get("media", {}) or {}

    def uname(u):
        u = u or {}
        return u.get("nickName") or u.get("nickname")  # XHS uses nickName (capital N)

    comments_raw = []
    comment_data = (state.get("noteData", {}).get("data", {}) or {}).get("commentData", {}) or {}
    for c in comment_data.get("comments", []) or []:
        entry = {
            "user": uname(c.get("user")),
            "content": c.get("content"),
            "likes": c.get("likeCount"),
            "time": c.get("time"),
            "sub_comments": [
                {"user": uname(sc.get("user")), "content": sc.get("content")}
                for sc in (c.get("subComments", []) or [])
            ],
        }
        comments_raw.append(entry)

    # Rich image list: keep every scene URL + dimensions so downstream can pick
    # the highest-quality original for OCR. XHS image items carry `url` plus an
    # `infoList` of scene-specific URLs (H5_DTL / H5_PRV / WB_DFT ...).
    images = []
    for item in (note.get("imageList", []) or []):
        if not isinstance(item, dict):
            continue
        scenes = {}
        for info in item.get("infoList", []) or []:
            if isinstance(info, dict) and info.get("url"):
                scenes[info.get("imageScene") or "unknown"] = info["url"]
        candidates = [item.get("urlDefault"), item.get("url"), item.get("urlPre")]
        candidates += list(scenes.values())
        urls = [u for u in candidates if u]
        images.append({
            "file_id": item.get("fileId"),
            "width": item.get("width"),
            "height": item.get("height"),
            "urls": urls,              # ordered; downloader picks the best
            "scenes": scenes,
            "live_photo": item.get("livePhoto", False),
        })

    result = {
        "note_id": note.get("noteId") or note.get("id"),
        "title": note.get("title") or note.get("displayTitle"),
        "desc": note.get("desc"),
        "author": uname(user),
        "author_id": user.get("userId"),
        "note_type": note.get("type"),  # "video" or "normal" (image/text)
        "interaction": {
            "liked": interact.get("likedCount"),
            "collected": interact.get("collectedCount"),
            "comments": interact.get("commentCount"),
            "shared": interact.get("shareCount"),
        },
        "video": pick_best_stream(media) if media else None,
        "image_list": images,
        "comments": comments_raw,
        "source_url": url,
    }
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="Xiaohongshu share link (xhslink.cn short URL or full note URL)")
    ap.add_argument("--out", help="Path to write the note JSON (default: <note_id>.json in cwd)")
    ap.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    args = ap.parse_args()

    try:
        note = parse_note(args.url)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    out = args.out
    if not out:
        nid = note.get("note_id") or "xhs_note"
        out = f"{nid}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(note, f, ensure_ascii=False, indent=2)

    # Shell-friendly lines for agents that consume stdout.
    print(f"NOTE_ID={note.get('note_id') or ''}")
    print(f"TITLE={note.get('title') or ''}")
    print(f"AUTHOR={note.get('author') or ''}")
    print(f"NOTE_TYPE={note.get('note_type') or ''}")
    v = note.get("video")
    images = note.get("image_list") or []
    if v:
        print(f"VIDEO_URL={v.get('url') or ''}")
        print(f"VIDEO_DURATION={v.get('duration') or ''}")
        print(f"VIDEO_SIZE={v.get('width') or ''}x{v.get('height') or ''}")
    else:
        print("VIDEO_URL=")  # image/text note — no video stream
    print(f"IMAGE_COUNT={len(images)}")
    print(f"COMMENTS={len(note.get('comments') or [])}")
    print(f"JSON_OUT={out}")


if __name__ == "__main__":
    main()
