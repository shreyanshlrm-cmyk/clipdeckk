# Clipdeck

Paste in one or more video links, get back a folder of ready-to-upload
vertical shorts — downloaded, transcribed, auto-clipped, smart-cropped to
9:16, captioned, and packaged with an **SEO-optimized title + description**,
**tags + hashtags**, and an **estimated virality score** for every clip.

No subscription. Two ways to run it, pick whichever suits you:

| | **A. Local web app** | **B. GitHub-hosted** |
|---|---|---|
| Where it runs | your machine | your GitHub repo's Actions runners (free) |
| Frontend | Flask page at `127.0.0.1:5000` | a static page (e.g. GitHub Pages) |
| Needs your computer on? | yes, while it runs | no — GitHub does the work |
| AI key entry | typed into the page each time | set once as a repo secret |
| Best for | quick one-offs, full control | "paste a link from my phone" style use |

Both modes share the exact same pipeline code, so quality is identical.

---

## What actually happens to a video

1. **Download** — `yt-dlp` grabs the best-quality version of the source.
2. **Transcribe** — `faster-whisper` runs locally/on-runner (free, offline)
   to get word-level timestamps.
3. **Pick the moments + write the SEO metadata** — either:
   - **AI mode**: the transcript goes to **any** of Anthropic, OpenAI, or
     Google Gemini — whichever key you provide. It returns the strongest
     clips plus, for each one: a hook-first keyword-rich **title**, a
     search-optimized **description** (keyword up front, natural supporting
     copy, a call-to-action, hashtags at the end), a **tags** list, extra
     **hashtags**, and a **virality score (0–100) with a one-line reason**.
   - **Offline mode** (default, no key needed anywhere): a scoring
     heuristic (punctuation, hook keywords, pacing, filler-word density)
     picks the strongest windows and generates the same fields with simpler
     text methods — still fully populated, just a notch below AI quality.
   Either way, every clip's start/end is snapped onto real sentence
   boundaries, so cuts never land mid-word.
4. **Render** — accurate trim, OpenCV face-aware 9:16 crop (falls back to
   center-crop for gameplay/slides/no-face content), scaled to 1080×1920,
   bold burned-in captions synced word-by-word, clean H.264/AAC + faststart
   so it uploads cleanly to Shorts/Reels/TikTok.

### About the SEO fields specifically
- **Title**: hook/keyword frontloaded into the first ~40 characters (mobile
  truncates past that), 40–70 characters total, no clickbait that
  misrepresents the clip.
- **Description**: sentence 1 carries the primary keyword + the hook
  (platforms only preview this much before "...more"), then supporting
  keywords, then a short call-to-action, then hashtags at the very end.
- **Tags**: 8–15 plain search-phrase keywords for the platform's tags field.
- **Hashtags**: 3–6, mixing one broad discovery tag with specific ones.
- **Virality score**: an *estimate*, not a guarantee — in AI mode it's the
  model's judgement of hook strength/pacing/shareability; in offline mode
  it's a normalized heuristic score. Treat it as a ranking signal across
  your own clips, not an absolute prediction.

---

## Mode A — Local web app

**One-time setup:**
- Python 3.10+
- `ffmpeg` on your PATH (`brew install ffmpeg` / `sudo apt install ffmpeg` /
  `winget install ffmpeg`)

```bash
python3 -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000**. Paste one or more links (one per line),
optionally expand "Advanced settings" to paste an API key from *any*
provider (Anthropic/OpenAI/Gemini — it's auto-detected from the key's
prefix, or pick the provider explicitly) and tune clip length/count/caption
style. Leave the key blank to stay fully offline and free.

Outputs land in `outputs/<job_id>/video_XX/short_XX.mp4` and are also
downloadable individually or as one zip from the page.

---

## Mode B — GitHub-hosted (paste a link from anywhere, GitHub renders it)

This turns **GitHub Actions into your free render backend** and a static
page (no server at all) into your frontend. You trigger a run from the
page, it runs inside your own repo, and finishes as a **GitHub Release**
containing every clip + a `manifest.json` with all the SEO/virality data,
which the page reads back and displays.

### Setup (once)

1. **Create a repo** and push this whole project to it. A **public** repo
   is simplest: public repos get unlimited free Actions minutes. (A private
   repo works too, just against your account's monthly Actions-minutes
   quota — and note, see the privacy callout below, this is *why* public
   vs private matters here beyond just cost.)

2. **Add an AI key as a repo secret** (optional — skip for offline mode):
   `Settings → Secrets and variables → Actions → New repository secret`.
   Add **one** of:
   - `ANTHROPIC_API_KEY`
   - `OPENAI_API_KEY`
   - `GEMINI_API_KEY`

   The workflow reads whichever is present — that's the "any key" part.
   Your key is never sent to, or stored in, the browser page.

3. **Add a `YTDLP_COOKIES_B64` repo secret (recommended for YouTube links).**
   GitHub Actions runners run on cloud IPs, and YouTube frequently responds
   to cloud IPs with "Sign in to confirm you're not a bot" — this isn't a
   Clipdeck bug, it happens to any automated downloader running in the
   cloud. Logged-in browser cookies fix this in most cases.

   **Export your cookies (do this in a normal browser window, while logged
   into YouTube):**
   - Install a well-reviewed, currently-maintained "cookies.txt" export
     extension for your browser (search your browser's extension store for
     "cookies.txt" — check it's still updated/maintained before installing,
     since some older ones have been abandoned or flagged). Firefox-based
     exports tend to be the most reliable currently.
   - With youtube.com open and logged in, export cookies for that site to a
     `cookies.txt` file (Netscape format — the standard export format).
   - This file contains your session cookies — treat it like a password.
     Don't commit it to the repo; it only ever goes into the secret below.
   - Base64-encode it so it survives being stored as a single-line secret:
     - Mac/Linux: `base64 -w0 cookies.txt` (copy the output)
     - Windows (PowerShell): `[Convert]::ToBase64String([IO.File]::ReadAllBytes("cookies.txt")) | Set-Clipboard`
   - `Settings → Secrets and variables → Actions → New repository secret`,
     name it `YTDLP_COOKIES_B64`, paste the base64 string as the value.
   - Delete the local `cookies.txt` once it's saved as a secret.

   **Caveat, honestly:** cookies are the standard first fix and work for a
   meaningful share of videos, but they're not a guaranteed permanent
   workaround — YouTube keeps tightening bot detection (some requests now
   also want a per-video "PO token" that a static cookies file can't
   provide). If downloads still fail on some videos after adding cookies,
   that's a known limitation, not a sign something's misconfigured — re-export
   fresh cookies periodically (they expire), and if failures persist, a
   self-hosted PO-token-provider is the documented escalation path, at the
   cost of noticeably more setup.

4. **Turn on GitHub Pages** for the frontend:
   `Settings → Pages → Source: Deploy from a branch → Branch: main, folder: /docs → Save`.
   Your page will be live at `https://<owner>.github.io/<repo>/` within a
   minute or two. (No Pages access? Just open `docs/index.html` as a local
   file instead — it works the same, it's 100% static.)

5. **Create a fine-grained personal access token**:
   `github.com/settings/personal-access-tokens/new` → Resource owner: you →
   Repository access: **Only select repositories** → pick this repo →
   Permissions: **Actions: Read and write**, **Contents: Read and write**
   (Contents is what lets it read back the Release the workflow publishes).
   Copy the token — you'll paste it into the page, not into the repo.

### Using it

Open the Pages URL, fill in **owner**, **repo**, **branch** (`main`), and
your **token**, optionally check "remember" to keep them in this browser.
Paste video link(s), tweak advanced settings if you like, hit **Cut it up**.

The page will:
1. Dispatch the `make_shorts.yml` workflow with your inputs.
2. Find and poll that run, showing which step is active.
3. Once it finishes, pull the Release it published and show every clip with
   its thumbnail, SEO title/description, tags, hashtags, and virality score
   — each downloadable individually, or all together as one zip.

You can also just watch/trigger runs directly from the repo's **Actions**
tab on GitHub if you'd rather skip the page entirely.

### Things worth knowing about this mode
- **No GPU** on standard GitHub runners, so transcription runs on CPU —
  fine for `base`/`small` whisper accuracy, noticeably slower on `medium`
  for long videos. A job can run up to ~5.8 hours before GitHub's hard cap.
- **Public repos are public.** Workflow-run inputs (including the video
  URLs you paste) are visible to anyone who can see the Actions tab. Your
  AI key is safe either way (it's a secret, always redacted) — but if the
  *links themselves* are sensitive, use a private repo instead.
- This repurposes Actions as general compute, which is a common pattern for
  personal projects but isn't what it's "for" — keep runs reasonable, and
  if you outgrow the free tier, a small VPS running Mode A is the natural
  next step.

---

## A note on rights

This tool will clip *any* video a link points to, but re-uploading someone
else's content without permission can violate copyright and platform terms
— it's built for your own long-form content (podcasts, streams, YouTube
videos, talks) or anything you have clear rights to repurpose.

## Project layout

```
app.py                        # Mode A: local Flask app
cli.py                        # Mode B: headless runner invoked by the workflow
pipeline/
  core.py                     # shared: one video in, rendered clips out
  download.py                 # yt-dlp wrapper
  transcribe.py                # faster-whisper wrapper
  highlight_select.py          # any-provider AI + offline heuristic, SEO + virality
  crop.py                      # OpenCV face-aware 9:16 crop
  captions.py                  # burned-in ASS caption generation
  render.py                    # ffmpeg trim/crop/scale/caption/encode
  pipeline.py                  # Mode A job orchestration (multi-video, in-memory)
.github/workflows/make_shorts.yml   # Mode B: the Actions backend
docs/                          # Mode B: static frontend (GitHub Pages root)
templates/, static/            # Mode A: Flask frontend
```

## Extending it

- `highlight_select.py` — tune the heuristic scoring, the SEO prompt
  wording, or add another AI provider next to Anthropic/OpenAI/Gemini.
- `crop.py` — currently a static smart-crop per clip; could be extended to
  a per-second tracked/panning crop.
- `captions.py` — tweak the ASS style (font, colors, position, one-word-at-
  a-time vs grouped).
- `render.py` — tweak encode settings (CRF/preset) for a size/quality trade-off.
