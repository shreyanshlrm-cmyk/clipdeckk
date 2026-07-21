"""
app.py
Local web app: paste a video link, get back multiple ready-to-upload
vertical shorts with burned-in captions, sitting in a folder on your own
machine. No account, no subscription, no data leaving your computer except
the optional call to your own Anthropic API key for smarter clip picking.

Run:
    python app.py
Then open:
    http://127.0.0.1:5000
"""
import os
import re
import threading

from flask import Flask, jsonify, render_template, request, send_from_directory, abort

from pipeline import pipeline as pl

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "outputs")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/submit", methods=["POST"])
def submit():
    data = request.get_json(force=True) or {}
    raw_urls = data.get("urls")
    if raw_urls is None:
        raw_urls = data.get("url") or ""
    if isinstance(raw_urls, str):
        urls = [u.strip() for u in re.split(r"[\n,]+", raw_urls) if u.strip()]
    else:
        urls = [str(u).strip() for u in raw_urls if str(u).strip()]
    if not urls:
        return jsonify({"error": "Paste at least one video link first."}), 400

    api_key = (data.get("api_key") or "").strip() or None
    provider = (data.get("provider") or "auto").strip()

    options = {
        "provider": provider,
        "api_key": api_key,
        "model": (data.get("model") or "").strip() or None,
        "min_len": max(5, int(data.get("min_len") or 15)),
        "max_len": max(10, int(data.get("max_len") or 90)),
        "num_clips": int(data["num_clips"]) if data.get("num_clips") else None,
        "whisper_model": data.get("whisper_model") or "small",
        "words_per_caption": max(1, int(data.get("words_per_caption") or 3)),
    }
    if options["max_len"] < options["min_len"]:
        options["max_len"] = options["min_len"] + 15

    job_id = pl.new_job(urls, options)
    thread = threading.Thread(target=pl.run_job, args=(job_id,), daemon=True)
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    job = pl.JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job"}), 404
    return jsonify(job)


@app.route("/outputs/<job_id>/<path:filename>")
def outputs(job_id, filename):
    job_dir = os.path.join(OUT_DIR, job_id)
    if not os.path.isdir(job_dir):
        abort(404)
    return send_from_directory(job_dir, filename)


@app.route("/api/download_all/<job_id>")
def download_all(job_id):
    job = pl.JOBS.get(job_id)
    if not job or job.get("stage") != "done":
        return jsonify({"error": "Job not finished"}), 400
    archive_path = pl.zip_results(job_id)
    directory, filename = os.path.split(archive_path)
    return send_from_directory(directory, filename, as_attachment=True)


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "jobs"), exist_ok=True)
    print("Open http://127.0.0.1:5000 in your browser")
    app.run(host="127.0.0.1", port=5000, debug=False)
