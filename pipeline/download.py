"""
download.py
Wraps yt-dlp to fetch the best-quality version of a YouTube (or other
yt-dlp-supported site) video to a local folder. No API key, no subscription -
yt-dlp is free and open source.
"""
import os
import subprocess
import yt_dlp


class DownloadError(Exception):
    pass


def get_video_info(url: str) -> dict:
    """Fetch metadata without downloading, so the UI can show a title fast."""
    ydl_opts = {"quiet": True, "noplaylist": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "id": info.get("id"),
                "title": info.get("title"),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"),
            }
    except Exception as e:
        raise DownloadError(f"Could not read video info: {e}")


def download_video(url: str, out_dir: str, progress_hook=None) -> dict:
    """
    Downloads best video+audio (up to 1080p, falls back gracefully) and
    merges to a single mp4. Returns dict with local filepath + metadata.
    """
    os.makedirs(out_dir, exist_ok=True)

    hooks = [progress_hook] if progress_hook else []

    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": hooks,
        # Keep only one file on disk once merged.
        "keepvideo": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            base, _ext = os.path.splitext(filepath)
            mp4_path = base + ".mp4"
            if os.path.exists(mp4_path):
                filepath = mp4_path
            if not os.path.exists(filepath):
                raise DownloadError("Download finished but output file was not found.")
            return {
                "filepath": filepath,
                "id": info.get("id"),
                "title": info.get("title") or "video",
                "duration": info.get("duration") or probe_duration(filepath),
            }
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(str(e))


def probe_duration(filepath: str) -> float:
    """Fallback duration probe via ffprobe if yt-dlp didn't report one."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", filepath,
            ],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def extract_audio(video_path: str, out_wav_path: str) -> str:
    """Extract mono 16kHz wav for whisper transcription."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
        out_wav_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_wav_path
