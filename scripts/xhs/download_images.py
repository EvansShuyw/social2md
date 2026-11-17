#!/usr/bin/env python3
"""Download all images from a Xiaohongshu image/text note (from fetch_xhs.py JSON).

Picks the best available URL per image (largest declared dimensions / original
scene) and downloads with retries, since the image CDN can also be flaky and
URLs carry time-limited signatures. Writes a manifest JSON mapping each image
to its local file so ocr_images.py can consume it.

Usage:
    python3 download_images.py /path/note.json --out-dir /path/images

    # Limit how many images to download (default: all):
    python3 download_images.py /path/note.json --out-dir /path/images --limit 9

Outputs:
    <out-dir>/img_001.jpg ...         downloaded images
    <out-dir>/manifest.json           {images: [{index, path, width, height, source_url}], ...}
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)


def best_url(image: dict) -> str:
    """Choose the highest-quality URL for one image entry."""
    urls = image.get("urls") or []
    scenes = image.get("scenes") or {}
    if not urls:
        return ""
    # Prefer the detail-scene original (h5_1080jpg / WB_DFT) over style-preview.
    for key in ("H5_DTL", "WB_DFT", "default"):
        if scenes.get(key):
            return scenes[key]
    # Among all URLs, prefer ones without a style_ transform suffix.
    plain = [u for u in urls if "style_" not in u]
    chosen = plain[0] if plain else urls[0]
    # Strip the CDN processing suffix to request the original where possible.
    # Keep a fallback to the suffixed URL if the stripped one fails.
    return chosen


def fetch_one(url: str, path: str, timeout: int, retries: int) -> bool:
    curl = shutil.which("curl")
    for attempt in range(1, retries + 1):
        try:
            if curl:
                subprocess.run(
                    [curl, "-L", "--max-time", str(timeout), "--retry", "2",
                     "--retry-delay", "1", "-s", "-A", UA, "-o", path, url],
                    timeout=timeout + 10,
                )
            else:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=timeout) as resp, open(path, "wb") as f:
                    f.write(resp.read())
            if os.path.exists(path) and os.path.getsize(path) > 1024:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("note_json", help="JSON produced by fetch_xhs.py")
    ap.add_argument("--out-dir", required=True, help="Directory to save images + manifest.json")
    ap.add_argument("--limit", type=int, help="Max number of images to download (default: all)")
    ap.add_argument("--timeout", type=int, default=40, help="Per-request timeout in seconds")
    ap.add_argument("--retries", type=int, default=4, help="Retries per image")
    args = ap.parse_args()

    data = json.load(open(args.note_json, encoding="utf-8"))
    images = data.get("image_list") or []
    if not images:
        print("ERROR: no images in note JSON (is this a video note?)", file=sys.stderr)
        sys.exit(1)
    if args.limit:
        images = images[: args.limit]

    os.makedirs(args.out_dir, exist_ok=True)
    manifest = []
    ok_count = 0
    for i, img in enumerate(images, start=1):
        url = best_url(img)
        if not url:
            print(f"[{i}] no URL, skip", flush=True)
            continue
        ext = ".jpg"
        path = os.path.join(args.out_dir, f"img_{i:03d}{ext}")
        ok = fetch_one(url, path, args.timeout, args.retries)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        status = "OK" if ok else "FAILED"
        print(f"[{i}] {status} {size} bytes <- {url[:80]}", flush=True)
        if ok:
            ok_count += 1
        manifest.append({
            "index": i,
            "path": path,
            "width": img.get("width"),
            "height": img.get("height"),
            "source_url": url,
            "ok": ok,
        })
        time.sleep(0.3)

    manifest_path = os.path.join(args.out_dir, "manifest.json")
    json.dump({"images": manifest}, open(manifest_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"DOWNLOADED={ok_count}/{len(images)}", flush=True)
    print(f"MANIFEST={manifest_path}", flush=True)
    sys.exit(0 if ok_count > 0 else 1)


if __name__ == "__main__":
    main()
