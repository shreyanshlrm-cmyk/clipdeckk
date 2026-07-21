"""
core.py
The actual download -> transcribe -> select -> render pipeline for ONE
video. Both the local Flask app (pipeline.py) and the headless CLI used by
the GitHub Actions backend (cli.py) call into this, so the two front ends
never drift apart.
"""
import json
import os
import re

from . import download as dl
from . import transcribe as tr
from . import highlight_select as hs
from . import render as rd


def slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "video")).strip("-").lower()
    return (text or "video")[:max_len] or "video"


def process_video(url: str, work_dir: str, out_dir: str, options: dict, on_progress=None):
    """
    options keys: provider, api_key, model, min_len, max_len, num_clips,
                  whisper_model, words_per_caption
    on_progress(stage: str, message: str, percent: int) is called throughout,
    if given, so callers can surface live status.
    Writes short_01.mp4 / short_01.jpg / ... plus metadata.json into out_dir.
    Returns a summary dict (JSON-serializable, no raw word timestamps).
    """
    def progress(stage, message, percent):
        if on_progress:
            on_progress(stage, message, percent)

    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    # 1. Download ---------------------------------------------------------
    progress("downloading", "Downloading source video...", 5)

    def hook(d):
        if d.get("status") == "downloading":
            pct = d.get("_percent_str", "").strip().replace("%", "")
            try:
                p = float(pct)
                progress("downloading", "Downloading source video...", 5 + int(p * 0.25))
            except ValueError:
                pass

    info = dl.download_video(url, work_dir, progress_hook=hook)
    source_path = info["filepath"]
    duration = info["duration"] or dl.probe_duration(source_path)
    progress("downloading", "Download complete.", 30)

    # 2. Transcribe ---------------------------------------------------------
    progress("transcribing", "Transcribing audio (runs locally)...", 35)
    wav_path = os.path.join(work_dir, "audio.wav")
    dl.extract_audio(source_path, wav_path)
    segments, whisper_duration = tr.transcribe(wav_path, model_size=options.get("whisper_model", "small"))
    duration = duration or whisper_duration
    progress("transcribing", "Transcription complete.", 55)

    # 3. Highlight + SEO selection -------------------------------------------
    progress("selecting", "Finding the best moments + writing SEO metadata...", 60)
    clips, method = hs.select_highlights(
        segments, duration,
        min_len=options.get("min_len", 15),
        max_len=options.get("max_len", 90),
        num_clips=options.get("num_clips"),
        provider=options.get("provider"),
        api_key=options.get("api_key"),
        model=options.get("model"),
    )
    progress("selecting", f"Selected {len(clips)} clip(s) via {method}.", 65)

    if not clips:
        raise RuntimeError("No usable clips could be found in this video.")

    # 4. Render each clip -----------------------------------------------------
    results = []
    n = len(clips)
    for idx, clip in enumerate(clips):
        pct = 65 + int(30 * idx / n)
        progress("rendering", f"Rendering short {idx + 1} of {n}...", pct)
        clip_name = f"short_{idx + 1:02d}"
        out_mp4 = os.path.join(out_dir, f"{clip_name}.mp4")
        out_jpg = os.path.join(out_dir, f"{clip_name}.jpg")
        rd.render_clip(
            source_path, clip["start"], clip["end"], clip["words"],
            out_mp4, work_dir, clip_name,
            words_per_caption=options.get("words_per_caption", 3),
        )
        rd.make_thumbnail(out_mp4, out_jpg)
        results.append({
            "file": f"{clip_name}.mp4",
            "thumbnail": f"{clip_name}.jpg",
            "start": round(clip["start"], 2),
            "end": round(clip["end"], 2),
            "duration": round(clip["end"] - clip["start"], 2),
            "title": clip.get("title", ""),
            "description": clip.get("description", ""),
            "tags": clip.get("tags", []),
            "hashtags": clip.get("hashtags", []),
            "virality_score": clip.get("virality_score", 50),
            "virality_reason": clip.get("virality_reason", ""),
        })

    summary = {
        "source_url": url,
        "video_title": info["title"],
        "duration": duration,
        "selection_method": method,
        "clips": results,
    }

    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    progress("done", "All shorts for this video are ready.", 100)
    return summary
