#!/usr/bin/env python3
"""Robustly download a video URL with resume-on-interrupt.

Works for Xiaohongshu AND Douyin CDNs. Both are flaky (curl often dies
mid-transfer with exit 18); this script repeatedly resumes with HTTP Range
requests until the file reaches the expected size, then verifies it. It prefers
`curl -C -` and falls back to a pure-Python Range downloader.

IMPORTANT (Douyin): signed play URLs return HTTP 403 with a ~355-byte HTML body
unless you send a browser User-Agent AND a Referer. Both the HEAD size probe and
the GET below carry these headers by default. This bit us once — a 403 page was
mistaken for a complete 355-byte "video". Never drop these headers.

Usage:
    python3 download_video.py "<url>" --out /path/video.mp4
    python3 download_video.py "<url>" --out /path/video.mp4 --size 19795272
    # Custom referer (default https://www.douyin.com/):
    python3 download_video.py "<url>" --out /path/video.mp4 \
        --referer "https://www.douyin.com/"

Note: the URL is time-limited; fetch and download promptly.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
REFERER = "https://www.douyin.com/"


def auto_referer(url: str) -> str:
    """Infer a sensible Referer from the media host so this core script is
    platform-agnostic. Douyin CDNs 403 without UA + a matching Referer."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if "douyin" in host or "byte" in host or "ixigua" in host:
        return "https://www.douyin.com/"
    if "xhscdn" in host or "xiaohongshu" in host or "xhs" in host:
        return "https://www.xiaohongshu.com/"
    if ("kuaishou" in host or "chenzhongtech" in host or "kwcdn" in host
            or "kwimgs" in host):
        return "https://www.kuaishou.com/"
    # Fallback: scheme + host of the URL itself (still satisfies "has a referer").
    p = urllib.parse.urlparse(url)
    return f"{p.scheme}://{p.netloc}/" if p.netloc else REFERER


def _headers(referer: str) -> dict:
    return {"User-Agent": UA, "Referer": referer}


def detect_content_length(url: str, timeout: int = 20, referer: str = REFERER):
    """Return the total byte size from a HEAD request, or None.
    Carries UA + Referer — Douyin 403s (355-byte HTML) without them."""
    curl = shutil.which("curl")
    if curl:
        try:
            out = subprocess.run(
                [curl, "-sIL", "--max-time", str(timeout),
                 "-A", UA, "-e", referer, url],
                capture_output=True, text=True, timeout=timeout + 5,
            ).stdout
            sizes = [
                int(line.split(":", 1)[1].strip())
                for line in out.splitlines()
                if line.lower().startswith("content-length:")
            ]
            # A 355-byte "content" from Douyin is the 403 HTML page, not media.
            sizes = [s for s in sizes if s > 1024] or sizes
            if sizes:
                return max(sizes)
        except Exception:
            pass
    try:
        req = urllib.request.Request(url, method="HEAD", headers=_headers(referer))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            length = resp.headers.get("Content-Length")
            return int(length) if length else None
    except Exception:
        return None


def current_size(path: str) -> int:
    return os.path.getsize(path) if os.path.exists(path) else 0


def python_range_download(url: str, out: str, target: int, timeout: int = 120,
                          referer: str = REFERER):
    """Fallback: resume via urllib Range requests when curl is unavailable."""
    start = current_size(out)
    mode = "ab" if start else "wb"
    h = _headers(referer)
    h["Range"] = f"bytes={start}-"
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(out, mode) as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def download(url: str, out: str, target: int, max_attempts: int, timeout: int,
             referer: str = REFERER, ua: str = UA):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    curl = shutil.which("curl")
    for attempt in range(1, max_attempts + 1):
        have = current_size(out)
        if target and have >= target:
            print(f"COMPLETE at attempt {attempt}: {have}/{target} bytes", flush=True)
            return True
        remaining = f" / need {target - have}" if target else ""
        print(f"attempt {attempt}: have {have}{remaining}", flush=True)
        try:
            if curl:
                subprocess.run(
                    [curl, "-L", "-C", "-", "--max-time", str(timeout),
                     "--retry", "3", "--retry-delay", "2", "--retry-all-errors",
                     "-A", ua, "-e", referer,
                     "-s", "-o", out, url],
                    timeout=timeout + 15,
                )
            else:
                python_range_download(url, out, target, timeout, referer)
        except Exception as e:
            print(f"  resume error: {e}", flush=True)
        time.sleep(1)

    have = current_size(out)
    if target and have >= target:
        print(f"COMPLETE: {have}/{target} bytes", flush=True)
        return True
    print(f"INCOMPLETE: {have}" + (f" / {target}" if target else ""), file=sys.stderr, flush=True)
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="Direct video URL (from fetch_xhs.py VIDEO_URL)")
    ap.add_argument("--out", required=True, help="Output .mp4 path")
    ap.add_argument("--size", type=int, help="Expected byte size (auto-detected if omitted)")
    ap.add_argument("--attempts", type=int, default=20, help="Max resume attempts (default 20)")
    ap.add_argument("--timeout", type=int, default=120, help="Per-attempt timeout in seconds")
    ap.add_argument("--referer", default=None, help="Referer header (auto-inferred from URL by default; required to avoid 403)")
    ap.add_argument("--ua", default=UA, help="User-Agent header")
    args = ap.parse_args()
    referer = args.referer or auto_referer(args.url)
    print(f"referer: {referer}", flush=True)

    target = args.size or detect_content_length(args.url, referer=referer)
    print(f"target size: {target}", flush=True)
    ok = download(args.url, args.out, target, args.attempts, args.timeout,
                  referer, args.ua)
    print(f"FINAL={current_size(args.out)}", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
