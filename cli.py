#!/usr/bin/env python3
"""
cli.py
Headless runner used by the GitHub Actions backend (.github/workflows/make_shorts.yml)
and usable directly from a terminal too. Processes one or more video URLs
through the same pipeline as the web app, writes results under
outputs/<slug>/, and writes a top-level manifest.json aggregating every
clip from every video (this is what the static frontend on GitHub Pages
reads after downloading the run's Release assets).

Usage:
    python cli.py --urls "https://youtu.be/abc,https://youtu.be/xyz" \\
                   --provider auto --min-len 18 --max-len 75 \\
                   --whisper-model small --words-per-caption 3

AI key resolution (first match wins):
    --api-key flag > ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
    environment variables (this is how GitHub Actions secrets reach it)
    > offline heuristic mode if nothing is found.
"""
import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import core  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="Turn a long video into ready-to-upload shorts.")
    p.add_argument("--urls", required=True,
                   help="Comma or newline separated list of video URLs.")
    p.add_argument("--provider", default="auto",
                   choices=["auto", "anthropic", "openai", "gemini", "none"],
                   help="AI provider for clip selection + SEO metadata. 'none' skips AI entirely.")
    p.add_argument("--api-key", default=None,
                   help="AI API key. If omitted, falls back to ANTHROPIC_API_KEY / "
                        "OPENAI_API_KEY / GEMINI_API_KEY environment variables.")
    p.add_argument("--model", default=None, help="Override the default model for the chosen provider.")
    p.add_argument("--min-len", type=float, default=18)
    p.add_argument("--max-len", type=float, default=75)
    p.add_argument("--num-clips", type=int, default=None)
    p.add_argument("--whisper-model", default="small", choices=["base", "small", "medium"])
    p.add_argument("--words-per-caption", type=int, default=3)
    p.add_argument("--work-dir", default="work")
    p.add_argument("--out-dir", default="outputs")
    return p.parse_args()


def split_urls(raw: str):
    import re
    return [u.strip() for u in re.split(r"[\n,]+", raw) if u.strip()]


def main():
    args = parse_args()
    urls = split_urls(args.urls)
    if not urls:
        print("::error::No video URLs given.")
        sys.exit(1)

    options = {
        "provider": args.provider,
        "api_key": args.api_key,
        "model": args.model,
        "min_len": args.min_len,
        "max_len": max(args.max_len, args.min_len + 5),
        "num_clips": args.num_clips,
        "whisper_model": args.whisper_model,
        "words_per_caption": args.words_per_caption,
    }

    manifest = {"created_at": int(time.time()), "videos": []}
    had_error = False

    for idx, url in enumerate(urls):
        slug_hint = f"video_{idx + 1:02d}"
        video_work_dir = os.path.join(args.work_dir, slug_hint)
        video_out_dir = os.path.join(args.out_dir, slug_hint)

        def on_progress(stage, message, pct, _slug=slug_hint):
            print(f"[{_slug}] ({pct:3d}%) {stage}: {message}", flush=True)

        print(f"\n=== Processing {url} -> {slug_hint} ===", flush=True)
        try:
            summary = core.process_video(url, video_work_dir, video_out_dir, options, on_progress)
            summary["slug"] = slug_hint
            manifest["videos"].append(summary)
        except Exception as e:
            had_error = True
            print(f"::error::Failed on {url}: {e}", flush=True)
            manifest["videos"].append({
                "slug": slug_hint, "source_url": url, "error": str(e), "clips": [],
            })

    os.makedirs(args.out_dir, exist_ok=True)

    # Flatten every clip's video + thumbnail into one directory with globally
    # unique filenames, so they can be attached individually as GitHub
    # Release assets (release assets must have unique names across the whole
    # release, but every video's clips are independently named short_01.mp4,
    # short_02.mp4, ...). The manifest is enriched with these final names so
    # the static frontend never has to guess a naming convention.
    release_dir = "release_assets"
    os.makedirs(release_dir, exist_ok=True)
    for video in manifest["videos"]:
        slug = video.get("slug", "video")
        video_out_dir = os.path.join(args.out_dir, slug)
        for clip in video.get("clips", []):
            for key, out_key in (("file", "asset_video"), ("thumbnail", "asset_thumbnail")):
                fname = clip.get(key)
                if not fname:
                    continue
                src = os.path.join(video_out_dir, fname)
                if not os.path.exists(src):
                    continue
                asset_name = f"{slug}__{fname}"
                shutil.copy(src, os.path.join(release_dir, asset_name))
                clip[out_key] = asset_name

    manifest_path = os.path.join(args.out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {manifest_path}")
    # A copy alongside the flattened assets makes it trivial to upload
    # everything in release_assets/ as one glob in the Actions workflow.
    shutil.copy(manifest_path, os.path.join(release_dir, "manifest.json"))

    # Also drop a zip of everything for a single one-click download.
    zip_path = shutil.make_archive("shorts_bundle", "zip", args.out_dir)
    print(f"Wrote {zip_path}")
    shutil.copy(zip_path, os.path.join(release_dir, "shorts_bundle.zip"))

    total_clips = sum(len(v.get("clips", [])) for v in manifest["videos"])
    print(f"\nDone: {len(urls)} video(s), {total_clips} clip(s) total.")

    if had_error and total_clips == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
