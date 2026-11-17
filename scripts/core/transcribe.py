#!/usr/bin/env python3
"""Transcribe a video/audio file locally with faster-whisper (no cloud upload).

Bakes in all the fixes discovered in practice:
  - PyAV 19+ removed the `metadata_errors` kwarg that faster-whisper still
    passes to av.open -> monkey-patch to strip it.
  - HuggingFace direct download often times out in CN -> set HF_ENDPOINT to
    the hf-mirror.com endpoint before importing faster_whisper.
  - Apple Silicon: device="mps" + compute_type="float16" is ~3.8x FASTER than
    CPU int8 with equivalent quality (benchmarked: 3-min audio 39.9s -> 10.5s).
    Default device="auto" picks MPS on Apple Silicon and falls back to CPU int8
    automatically if MPS is unavailable or fails. Explicit --device still works.

Detects language automatically, outputs a timestamped plain-text transcript
and an SRT subtitle file.

Usage:
    python3 transcribe.py /path/video.mp4 --out-prefix /path/transcript

    # Force a language / different model:
    python3 transcribe.py /path/video.mp4 --out-prefix /path/transcript \
        --language en --model large-v3-turbo

First run downloads the model (~1.6 GB) — ensure enough disk and network.
Install deps: pip install faster-whisper av
"""

import argparse
import os
import sys
import time

# 1) HF mirror: must be set before faster_whisper/huggingface_hub are imported.
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# 2) PyAV compatibility shim: newer av.open dropped the metadata_errors kwarg.
import av
_real_av_open = av.open

def _patched_av_open(*args, **kwargs):
    kwargs.pop("metadata_errors", None)
    return _real_av_open(*args, **kwargs)

av.open = _patched_av_open

from faster_whisper import WhisperModel


def fmt(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def srt_time(sec):
    ms = int((sec - int(sec)) * 1000)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def load_model(model_name, device, compute_type):
    """Load the model, with automatic device fallback.

    device="auto" (default): try MPS+float16 first (Apple Silicon, ~3.8x faster),
    then fall back to CPU+int8. Explicit device values are honored as-is.
    """
    if device == "auto":
        candidates = [("mps", "float16"), ("cpu", "int8")]
    else:
        ct = compute_type if compute_type != "auto" else (
            "float16" if device in ("mps", "cuda") else "int8"
        )
        candidates = [(device, ct)]

    last_err = None
    for dev, ct in candidates:
        try:
            print(f"Loading model {model_name} (device={dev}, compute={ct})...", flush=True)
            model = WhisperModel(model_name, device=dev, compute_type=ct)
            print(f"  using device={dev}, compute={ct}", flush=True)
            return model
        except Exception as e:
            last_err = e
            if device == "auto":
                print(f"  {dev} unavailable ({type(e).__name__}), falling back...", flush=True)
    raise last_err


def transcribe(video, out_prefix, model_name, language, device, compute_type, beam_size):
    t0 = time.time()
    model = load_model(model_name, device, compute_type)
    print(f"Model loaded in {time.time()-t0:.1f}s. Starting transcription...", flush=True)

    kwargs = dict(
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        condition_on_previous_text=False,
    )
    if language:
        kwargs["language"] = language
    segments, info = model.transcribe(video, **kwargs)
    print(
        f"Detected language: {info.language} ({info.language_probability:.2f}), "
        f"duration {info.duration:.1f}s",
        flush=True,
    )

    txt_path = out_prefix + ".txt"
    srt_path = out_prefix + ".srt"
    txt_f = open(txt_path, "w", encoding="utf-8")
    srt_f = open(srt_path, "w", encoding="utf-8")
    count = 0
    for seg in segments:
        text = seg.text.strip()
        txt_f.write(f"[{fmt(seg.start)} --> {fmt(seg.end)}] {text}\n")
        txt_f.flush()
        srt_f.write(f"{count+1}\n{srt_time(seg.start)} --> {srt_time(seg.end)}\n{text}\n\n")
        srt_f.flush()
        count += 1
        if count % 20 == 0:
            print(f"  segments={count}, at {fmt(seg.end)}, elapsed {time.time()-t0:.0f}s", flush=True)
    txt_f.close()
    srt_f.close()
    print(f"DONE. total segments={count}, elapsed {time.time()-t0:.1f}s", flush=True)
    print(f"TXT_OUT={txt_path}", flush=True)
    print(f"SRT_OUT={srt_path}", flush=True)
    print(f"SEGMENTS={count}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="Path to the video/audio file")
    ap.add_argument("--out-prefix", help="Output prefix for .txt and .srt (default: <video> without extension)")
    ap.add_argument("--model", default="large-v3-turbo", help="Whisper model (default large-v3-turbo)")
    ap.add_argument("--language", help="Force language code (e.g. zh, en). Auto-detect if omitted.")
    ap.add_argument("--device", default="auto", help="auto (MPS on Apple Silicon, else CPU) / mps / cpu / cuda (default auto)")
    ap.add_argument("--compute-type", default="auto", help="auto / int8 / float16 etc. (default auto)")
    ap.add_argument("--beam-size", type=int, default=5, help="Beam size (default 5)")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        print(f"ERROR: video not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    out_prefix = args.out_prefix or os.path.splitext(args.video)[0]
    try:
        transcribe(
            args.video, out_prefix, args.model, args.language,
            args.device, args.compute_type, args.beam_size,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
