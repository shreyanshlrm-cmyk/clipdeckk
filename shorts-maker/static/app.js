const goBtn = document.getElementById('go-btn');
const urlInput = document.getElementById('url-input');
const progressSection = document.getElementById('progress-section');
const rulerFill = document.getElementById('ruler-fill');
const playhead = document.getElementById('playhead');
const progressMessage = document.getElementById('progress-message');
const progressPercent = document.getElementById('progress-percent');
const resultsSection = document.getElementById('results-section');
const resultsTitle = document.getElementById('results-title');
const cardsEl = document.getElementById('cards');
const errorBanner = document.getElementById('error-banner');
const downloadAllBtn = document.getElementById('download-all-btn');

let currentJobId = null;
let pollTimer = null;

function showError(msg) {
  errorBanner.hidden = false;
  errorBanner.textContent = msg;
}
function clearError() {
  errorBanner.hidden = true;
  errorBanner.textContent = '';
}

function setProgress(pct, message) {
  const clamped = Math.max(0, Math.min(100, pct));
  rulerFill.style.width = clamped + '%';
  playhead.style.left = clamped + '%';
  progressPercent.textContent = clamped + '%';
  progressMessage.textContent = message || '';
}

function fieldValue(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : '';
}

goBtn.addEventListener('click', submitJob);
urlInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') submitJob(); });

async function submitJob() {
  clearError();
  const urls = urlInput.value.trim();
  if (!urls) { showError('Paste at least one video link first.'); return; }

  const payload = {
    urls,
    provider: fieldValue('provider') || 'auto',
    api_key: fieldValue('api-key') || null,
    model: fieldValue('model'),
    min_len: fieldValue('min-len') || 15,
    max_len: fieldValue('max-len') || 90,
    num_clips: fieldValue('num-clips') || null,
    whisper_model: fieldValue('whisper-model'),
    words_per_caption: fieldValue('caption-words') || 3,
  };

  goBtn.disabled = true;
  goBtn.textContent = 'Working...';
  resultsSection.hidden = true;
  cardsEl.innerHTML = '';
  progressSection.hidden = false;
  setProgress(0, 'Queued...');

  try {
    const res = await fetch('/api/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Could not start the job.');
    currentJobId = data.job_id;
    pollTimer = setInterval(pollStatus, 1200);
  } catch (err) {
    showError(err.message);
    resetGoButton();
  }
}

function resetGoButton() {
  goBtn.disabled = false;
  goBtn.textContent = 'Cut it up';
}

async function pollStatus() {
  if (!currentJobId) return;
  try {
    const res = await fetch(`/api/status/${currentJobId}`);
    const job = await res.json();
    if (!res.ok) throw new Error(job.error || 'Lost track of the job.');

    setProgress(job.percent || 0, job.message || job.stage);
    renderResults(job);

    if (job.stage === 'done' || job.stage === 'error') {
      clearInterval(pollTimer);
      resetGoButton();
      if (job.stage === 'error') showError(job.error || 'Something went wrong.');
    }
  } catch (err) {
    clearInterval(pollTimer);
    resetGoButton();
    showError(err.message);
  }
}

function renderResults(job) {
  if (!job.videos || job.videos.length === 0) return;
  resultsSection.hidden = false;
  resultsTitle.textContent = job.videos.length > 1
    ? `Shorts from ${job.videos.length} videos`
    : `Shorts from “${job.videos[0].video_title || 'your video'}”`;

  cardsEl.innerHTML = '';
  job.videos.forEach((video) => {
    const group = document.createElement('div');
    group.className = 'video-group';

    const heading = document.createElement('p');
    heading.className = 'video-group-title';
    heading.textContent = `${video.video_title || video.slug} · ${(video.clips || []).length} clip(s) · picked via ${video.selection_method}`;
    group.appendChild(heading);

    const grid = document.createElement('div');
    grid.className = 'cards';

    (video.clips || []).forEach((clip, i) => {
      const card = document.createElement('div');
      card.className = 'card';
      card.style.animationDelay = (i * 0.05) + 's';

      const thumbUrl = `/outputs/${currentJobId}/${video.slug}/${clip.thumbnail}`;
      const fileUrl = `/outputs/${currentJobId}/${video.slug}/${clip.file}`;
      const tags = (clip.hashtags || []).join(' ');
      const score = clip.virality_score ?? 50;
      const scoreClass = score >= 70 ? 'virality-high' : 'virality-mid';

      card.innerHTML = `
        <div class="card-perf"></div>
        <img class="card-thumb" src="${thumbUrl}" loading="lazy" alt="${escapeHtml(clip.title)}">
        <div class="card-body">
          <span class="card-dur">${formatTc(clip.start)} – ${formatTc(clip.end)} · ${clip.duration}s</span>
          <span class="virality-badge ${scoreClass}">⚡ ${score}/100</span>
          <p class="card-title">${escapeHtml(clip.title)}</p>
          <p class="card-caption">${escapeHtml(clip.description || '')}</p>
          <p class="virality-reason">${escapeHtml(clip.virality_reason || '')}</p>
          <p class="card-tags">${escapeHtml(tags)}</p>
          <a class="card-dl" href="${fileUrl}" download>Download .mp4</a>
        </div>
      `;
      grid.appendChild(card);
    });

    group.appendChild(grid);
    cardsEl.appendChild(group);
  });
}

downloadAllBtn.addEventListener('click', () => {
  if (!currentJobId) return;
  window.location.href = `/api/download_all/${currentJobId}`;
});

function formatTc(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}
