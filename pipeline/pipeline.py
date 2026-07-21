"""
pipeline.py
Job orchestration for the local Flask app. Accepts one or more video URLs
per job, runs them one after another through pipeline/core.py, and keeps a
shared in-memory status dict the web UI polls. Fine for a personal,
single-user local tool - no database, no queue needed.
"""
import os
import shutil
import traceback
import uuid

from . import core

JOBS = {}  # job_id -> status dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK_DIR = os.path.join(BASE_DIR, "jobs")
OUT_DIR = os.path.join(BASE_DIR, "outputs")


def _set(job_id, **kwargs):
    JOBS[job_id].update(kwargs)


def new_job(urls, options):
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "id": job_id,
        "urls": urls,
        "options": options,
        "stage": "queued",
        "message": "Queued...",
        "percent": 0,
        "videos": [],   # one entry per URL once processed
        "error": None,
    }
    return job_id


def run_job(job_id):
    job = JOBS[job_id]
    urls = job["urls"]
    opts = job["options"]
    job_out_dir = os.path.join(OUT_DIR, job_id)
    job_work_dir = os.path.join(WORK_DIR, job_id)
    os.makedirs(job_out_dir, exist_ok=True)
    os.makedirs(job_work_dir, exist_ok=True)

    n_videos = len(urls)
    videos = []
    try:
        for v_idx, url in enumerate(urls):
            video_slug = f"video_{v_idx + 1:02d}"
            video_work_dir = os.path.join(job_work_dir, video_slug)
            video_out_dir = os.path.join(job_out_dir, video_slug)

            base_pct = int(100 * v_idx / n_videos)
            span_pct = int(100 / n_videos)

            def on_progress(stage, message, pct, _base=base_pct, _span=span_pct, _v=v_idx):
                overall = _base + int(_span * pct / 100)
                _set(job_id, stage=stage,
                     message=f"[Video {_v + 1}/{n_videos}] {message}",
                     percent=overall)

            summary = core.process_video(url, video_work_dir, video_out_dir, opts, on_progress)
            summary["slug"] = video_slug
            videos.append(summary)
            _set(job_id, videos=list(videos))

        _set(job_id, stage="done", message="All shorts are ready.", percent=100, videos=videos)

    except Exception as e:
        _set(job_id, stage="error", message=str(e), error=str(e))
        traceback.print_exc()
    finally:
        try:
            shutil.rmtree(job_work_dir, ignore_errors=True)
        except OSError:
            pass


def zip_results(job_id):
    job_out_dir = os.path.join(OUT_DIR, job_id)
    archive_base = os.path.join(OUT_DIR, f"{job_id}_all")
    archive_path = shutil.make_archive(archive_base, "zip", job_out_dir)
    return archive_path
