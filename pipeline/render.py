"""
render.py
Turns one selected (start, end) window of the source video into a finished,
ready-to-upload vertical short: accurate trim, smart crop, scale to
1080x1920, burned-in captions, high-quality H.264/AAC encode with a
faststart flag so it uploads cleanly everywhere.

Cutting is done in two stages for speed + accuracy on long source videos:
  1. A fast, stream-copy rough extraction around the target window (keyframe
     seek, no re-encode) with a small buffer on each side.
  2. An accurate, frame-level trim + crop + scale + caption re-encode of that
     small buffered extract.
"""
import os
import subprocess

from . import crop as crop_mod
from . import captions as captions_mod


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd)}\n{result.stderr[-2000:]}")


def render_clip(source_path: str, start: float, end: float, words, out_path: str,
                 tmp_dir: str, clip_name: str, video_w: int = 1080, video_h: int = 1920,
                 words_per_caption: int = 3, crf: int = 18, preset: str = "medium"):
    duration = end - start
    buffer = 3.0
    rough_start = max(0.0, start - buffer)
    rough_duration = duration + 2 * buffer

    rough_path = os.path.join(tmp_dir, f"{clip_name}_rough.mp4")
    _run([
        "ffmpeg", "-y",
        "-ss", f"{rough_start:.3f}",
        "-i", source_path,
        "-t", f"{rough_duration:.3f}",
        "-c", "copy", "-avoid_negative_ts", "make_zero",
        rough_path,
    ])

    precise_offset = start - rough_start

    # Compute the smart crop window against the original source for accuracy.
    crop_info = crop_mod.compute_crop_window(source_path, start, end)

    ass_path = os.path.join(tmp_dir, f"{clip_name}.ass")
    captions_mod.build_ass(
        words, clip_start=start, clip_end=end, out_path=ass_path,
        video_w=video_w, video_h=video_h, words_per_group=words_per_caption,
    )
    # ffmpeg filtergraph paths need escaping on Windows-style drives / special chars
    ass_filter_path = ass_path.replace("\\", "/").replace(":", "\\:")

    vf = (
        f"crop={crop_info['crop_w']}:{crop_info['crop_h']}:{crop_info['crop_x']}:{crop_info['crop_y']},"
        f"scale={video_w}:{video_h}:flags=lanczos,"
        f"ass='{ass_filter_path}'"
    )

    _run([
        "ffmpeg", "-y",
        "-ss", f"{precise_offset:.3f}",
        "-i", rough_path,
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_path,
    ])

    try:
        os.remove(rough_path)
    except OSError:
        pass

    return out_path


def make_thumbnail(clip_path: str, out_path: str, at_seconds: float = 0.3):
    _run([
        "ffmpeg", "-y", "-ss", f"{at_seconds:.2f}", "-i", clip_path,
        "-frames:v", "1", "-q:v", "3", out_path,
    ])
    return out_path
