#!/usr/bin/env python3
"""OCR all downloaded images via Apple Vision (local, no cloud, Simplified Chinese).

Compiles the bundled Swift helper (ocr_vision.swift) on first use, then feeds it
all image paths from download_images.py's manifest. Groups the recognized text
per image into a single Markdown transcript.

Requirements: macOS with Xcode command-line tools (`swiftc`). The compiled
binary is cached next to the source; pass --recompile to rebuild.

Usage:
    python3 ocr_images.py /path/images/manifest.json --out /path/images_ocr.txt

    # Force recompile the helper:
    python3 ocr_images.py /path/images/manifest.json --out /path/ocr.txt --recompile

If Vision OCR is unavailable (non-macOS / no swiftc), the script still writes a
skeleton file listing the images so the agent can fall back to reading images
directly with its own vision capability.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SWIFT_SRC = os.path.join(HERE, "ocr_vision.swift")
SWIFT_BIN = os.path.join(HERE, "ocr_vision")
SEPARATOR = "<<<XHS_OCR_IMAGE>>>"


def ensure_binary(recompile=False):
    if not shutil.which("swiftc"):
        return None, "swiftc not found"
    if recompile or not os.path.exists(SWIFT_BIN):
        try:
            subprocess.run(
                ["swiftc", "-O", SWIFT_SRC, "-o", SWIFT_BIN],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            return None, f"swiftc build failed: {e.stderr[:500]}"
    return SWIFT_BIN, None


def parse_output(raw: str, manifest_paths: list) -> list:
    """Parse the delimited Swift output into {path, text} blocks."""
    blocks = []
    current_path = None
    lines = []
    for line in raw.splitlines():
        if line.startswith("@@PATH@@"):
            if current_path is not None:
                blocks.append({"path": current_path, "text": "\n".join(lines).strip()})
            current_path = line[len("@@PATH@@"):]
            lines = []
        elif line.startswith("@@ERROR@@") or line.startswith("@@EMPTY@@"):
            continue
        elif line == SEPARATOR:
            continue
        else:
            lines.append(line)
    if current_path is not None:
        blocks.append({"path": current_path, "text": "\n".join(lines).strip()})
    return blocks


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", help="manifest.json produced by download_images.py")
    ap.add_argument("--out", required=True, help="Output text file for the per-image OCR transcript")
    ap.add_argument("--recompile", action="store_true", help="Force recompile the Swift OCR helper")
    args = ap.parse_args()

    data = json.load(open(args.manifest, encoding="utf-8"))
    entries = [e for e in data.get("images", []) if e.get("ok") and os.path.exists(e["path"])]
    if not entries:
        print("ERROR: no downloaded images found in manifest", file=sys.stderr)
        sys.exit(1)

    binary, err = ensure_binary(args.recompile)
    if not binary:
        # Graceful fallback: write skeleton so agent can use its own vision.
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("# 图片 OCR（本地 Vision 不可用）\n\n")
            f.write(f"> 说明：{err}。以下为图片路径，可用 agent 自身的视觉能力读取。\n\n")
            for e in entries:
                f.write(f"## 图片 {e['index']}\n\n路径：`{e['path']}`\n\n")
        print(f"FALLBACK written (reason: {err})", flush=True)
        print(f"OCR_OUT={args.out}", flush=True)
        sys.exit(0)

    paths = [e["path"] for e in entries]
    print(f"OCR on {len(paths)} images...", flush=True)
    try:
        proc = subprocess.run([binary] + paths, capture_output=True, text=True, timeout=600)
        raw = proc.stdout
        if proc.stderr.strip():
            print(f"  (stderr) {proc.stderr.strip()[:300]}", flush=True)
    except subprocess.TimeoutExpired:
        print("ERROR: OCR timed out", file=sys.stderr)
        sys.exit(1)

    blocks = parse_output(raw, paths)
    path_to_text = {b["path"]: b["text"] for b in blocks}

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# 图文笔记 · 图片文字 OCR（本地识别）\n\n")
        total_chars = 0
        for e in entries:
            text = path_to_text.get(e["path"], "")
            total_chars += len(text)
            f.write(f"## 图片 {e['index']}\n\n")
            dims = ""
            if e.get("width") and e.get("height"):
                dims = f"（{e['width']}×{e['height']}）"
            f.write(f"`{os.path.basename(e['path'])}`{dims}\n\n")
            if text:
                f.write(text + "\n\n")
            else:
                f.write("［此图未识别到文字，可能为纯图片/手绘图，需结合视觉查看原图］\n\n")
        f.write(f"\n---\n共 {len(entries)} 张图片，识别文字约 {total_chars} 字。\n")

    print(f"OCR_OUT={args.out}", flush=True)
    print(f"IMAGES={len(entries)}", flush=True)


if __name__ == "__main__":
    main()
