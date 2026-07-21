const API = 'https://api.github.com';
const WORKFLOW_FILE = 'make_shorts.yml';

const els = {
  owner: document.getElementById('gh-owner'),
  repo: document.getElementById('gh-repo'),
  branch: document.getElementById('gh-branch'),
  token: document.getElementById('gh-token'),
  remember: document.getElementById('remember-me'),
  urlInput: document.getElementById('url-input'),
  goBtn: document.getElementById('go-btn'),
  progressSection: document.getElementById('progress-section'),
  rulerFill: document.getElementById('ruler-fill'),
  playhead: document.getElementById('playhead'),
  progressMessage: document.getElementById('progress-message'),
  progressPercent: document.getElementById('progress-percent'),
  runLink: document.getElementById('run-link'),
  resultsSection: document.getElementById('results-section'),
  resultsTitle: document.getElementById('results-title'),
  cards: document.getElementById('cards'),
  errorBanner: document.getElementById('error-banner'),
  downloadAllBtn: document.getElementById('download-all-btn'),
};

const STORE_KEY = 'clipdeck_repo_config';

function loadStoredConfig() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return;
    const cfg = JSON.parse(raw);
    els.owner.value = cfg.owner || '';
    els.repo.value = cfg.repo || '';
    els.branch.value = cfg.branch || 'main';
    els.token.value = cfg.token || '';
    els.remember.checked = true;
  } catch (e) { /* ignore */ }
}
loadStoredConfig();

function persistConfigIfWanted() {
  if (els.remember.checked) {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      owner: els.owner.value.trim(),
      repo: els.repo.value.trim(),
      branch: els.branch.value.trim() || 'main',
      token: els.token.value.trim(),
    }));
  } else {
    localStorage.removeItem(STORE_KEY);
  }
}

function showError(msg) {
  els.errorBanner.hidden = false;
  els.errorBanner.textContent = msg;
}
function clearError() {
  els.errorBanner.hidden = true;
  els.errorBanner.textContent = '';
}

function setProgress(pct, message, pulsing = false) {
  const clamped = Math.max(0, Math.min(100, pct));
  els.rulerFill.style.width = clamped + '%';
  els.playhead.style.left = clamped + '%';
  els.playhead.classList.toggle('pulsing', pulsing);
  els.progressPercent.textContent = clamped + '%';
  els.progressMessage.textContent = message || '';
}

function fieldValue(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : '';
}

function ghHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  };
}

async function ghFetch(url, token, opts = {}) {
  const res = await fetch(url, { ...opts, headers: { ...ghHeaders(token), ...(opts.headers || {}) } });
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json()).message; } catch (e) { /* ignore */ }
    throw new Error(`GitHub API error (${res.status}): ${detail || res.statusText}`);
  }
  return res;
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

els.goBtn.addEventListener('click', submitJob);

async function submitJob() {
  clearError();
  const owner = fieldValue('gh-owner');
  const repo = fieldValue('gh-repo');
  const branch = fieldValue('gh-branch') || 'main';
  const token = fieldValue('gh-token');
  const urls = els.urlInput.value.trim();

  if (!owner || !repo || !token) { showError('Fill in owner, repo name, and a token first.'); return; }
  if (!urls) { showError('Paste at least one video link first.'); return; }

  persistConfigIfWanted();

  const clientRef = `run_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

  const inputs = {
    urls,
    provider: fieldValue('provider') || 'auto',
    min_len: fieldValue('min-len') || '18',
    max_len: fieldValue('max-len') || '75',
    num_clips: fieldValue('num-clips') || '',
    whisper_model: fieldValue('whisper-model') || 'small',
    words_per_caption: fieldValue('caption-words') || '3',
    client_ref: clientRef,
  };

  els.goBtn.disabled = true;
  els.goBtn.textContent = 'Working...';
  els.resultsSection.hidden = true;
  els.cards.innerHTML = '';
  els.progressSection.hidden = false;
  els.runLink.hidden = true;
  setProgress(0, 'Dispatching workflow...');

  try {
    await ghFetch(
      `${API}/repos/${owner}/${repo}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
      token,
      { method: 'POST', body: JSON.stringify({ ref: branch, inputs }) }
    );

    setProgress(2, 'Waiting for GitHub to start the run...');
    const run = await findDispatchedRun(owner, repo, token, clientRef);
    els.runLink.href = run.html_url;
    els.runLink.hidden = false;

    await pollRun(owner, repo, token, run.id);
  } catch (err) {
    showError(err.message);
    resetGoButton();
  }
}

function resetGoButton() {
  els.goBtn.disabled = false;
  els.goBtn.textContent = 'Cut it up';
}

async function findDispatchedRun(owner, repo, token, clientRef) {
  // workflow_dispatch doesn't hand back a run id directly, so we look for a
  // very recent run whose name (driven by `run-name:` in the workflow)
  // contains our client_ref nonce.
  for (let attempt = 0; attempt < 20; attempt++) {
    await sleep(1500);
    const res = await ghFetch(
      `${API}/repos/${owner}/${repo}/actions/workflows/${WORKFLOW_FILE}/runs?event=workflow_dispatch&per_page=10`,
      token
    );
    const data = await res.json();
    const match = (data.workflow_runs || []).find((r) => (r.name || '').includes(clientRef));
    if (match) return match;
  }
  throw new Error('Could not find the dispatched run - check the Actions tab on GitHub directly.');
}

const STEP_LABELS = {
  'Checkout': 'Checking out your repo...',
  'Set up Python': 'Setting up Python...',
  'Install ffmpeg': 'Installing ffmpeg...',
  'Install Python dependencies': 'Installing dependencies...',
  'Run the pipeline': 'Downloading, transcribing, and rendering your shorts (the long part)...',
  'Ensure output artifacts exist': 'Wrapping up...',
  'Write job summary': 'Wrapping up...',
  'Publish results as a Release': 'Publishing your shorts...',
};

async function pollRun(owner, repo, token, runId) {
  while (true) {
    await sleep(2500);
    const runRes = await ghFetch(`${API}/repos/${owner}/${repo}/actions/runs/${runId}`, token);
    const run = await runRes.json();

    const jobsRes = await ghFetch(`${API}/repos/${owner}/${repo}/actions/runs/${runId}/jobs`, token);
    const jobsData = await jobsRes.json();
    const job = (jobsData.jobs || [])[0];

    if (job && job.steps) {
      const steps = job.steps;
      const activeIdx = steps.findIndex((s) => s.status === 'in_progress');
      const doneCount = steps.filter((s) => s.status === 'completed').length;
      const pct = Math.round((doneCount / steps.length) * 100);
      const current = activeIdx >= 0 ? steps[activeIdx] : steps[Math.max(0, doneCount - 1)];
      const label = STEP_LABELS[current?.name] || current?.name || 'Working...';
      setProgress(pct, label, current?.name === 'Run the pipeline');
    }

    if (run.status === 'completed') {
      setProgress(100, run.conclusion === 'success' ? 'Done - fetching your shorts...' : 'Run finished with issues - fetching whatever was produced...');
      await loadResults(owner, repo, token, runId);
      resetGoButton();
      return;
    }
  }
}

async function loadResults(owner, repo, token, runId) {
  const tag = `clipdeck-${runId}`;
  let release;
  try {
    const res = await ghFetch(`${API}/repos/${owner}/${repo}/releases/tags/${tag}`, token);
    release = await res.json();
  } catch (err) {
    showError(`Run finished, but no results Release was found: ${err.message}`);
    return;
  }

  const assets = release.assets || [];
  const manifestAsset = assets.find((a) => a.name === 'manifest.json');
  const errorAsset = assets.find((a) => a.name === 'error.json');
  const bundleAsset = assets.find((a) => a.name === 'shorts_bundle.zip');

  if (!manifestAsset && errorAsset) {
    const text = await (await fetchAssetBlob(owner, repo, token, errorAsset)).text();
    const parsed = JSON.parse(text);
    showError(parsed.error || 'The pipeline did not produce any output.');
    return;
  }
  if (!manifestAsset) {
    showError('No manifest.json in the results Release - something went wrong upstream.');
    return;
  }

  const manifestText = await (await fetchAssetBlob(owner, repo, token, manifestAsset)).text();
  const manifest = JSON.parse(manifestText);

  renderResults(manifest, owner, repo, token, assets);

  if (bundleAsset) {
    els.downloadAllBtn.onclick = () => downloadAsset(owner, repo, token, bundleAsset, 'shorts_bundle.zip');
  }
}

async function fetchAssetBlob(owner, repo, token, asset) {
  // Release assets need the API asset endpoint (not the plain
  // browser_download_url) so this also works for private repos.
  const res = await ghFetch(
    `${API}/repos/${owner}/${repo}/releases/assets/${asset.id}`,
    token,
    { headers: { Accept: 'application/octet-stream' } }
  );
  return res.blob();
}

async function downloadAsset(owner, repo, token, asset, filename) {
  const blob = await fetchAssetBlob(owner, repo, token, asset);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename || asset.name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function renderResults(manifest, owner, repo, token, assets) {
  const videos = manifest.videos || [];
  if (videos.length === 0) { showError('The run completed but produced no videos.'); return; }

  els.resultsSection.hidden = false;
  els.resultsTitle.textContent = videos.length > 1
    ? `Shorts from ${videos.length} videos`
    : `Shorts from “${videos[0].video_title || 'your video'}”`;

  els.cards.innerHTML = '';
  const assetByName = Object.fromEntries(assets.map((a) => [a.name, a]));

  videos.forEach((video) => {
    const group = document.createElement('div');
    group.className = 'video-group';

    const heading = document.createElement('p');
    heading.className = 'video-group-title';
    if (video.error) {
      heading.textContent = `${video.slug}: failed — ${video.error}`;
      group.appendChild(heading);
      els.cards.appendChild(group);
      return;
    }
    heading.textContent = `${video.video_title || video.slug} · ${(video.clips || []).length} clip(s) · picked via ${video.selection_method}`;
    group.appendChild(heading);

    const grid = document.createElement('div');
    grid.className = 'cards';

    (video.clips || []).forEach((clip, i) => {
      const card = document.createElement('div');
      card.className = 'card';
      card.style.animationDelay = (i * 0.05) + 's';
      const score = clip.virality_score ?? 50;
      const scoreClass = score >= 70 ? 'virality-high' : 'virality-mid';
      const tags = (clip.hashtags || []).join(' ');

      card.innerHTML = `
        <div class="card-perf"></div>
        <div class="card-thumb-wrap"><img class="card-thumb" alt="${escapeHtml(clip.title)}"></div>
        <div class="card-body">
          <span class="card-dur">${formatTc(clip.start)} – ${formatTc(clip.end)} · ${clip.duration}s</span>
          <span class="virality-badge ${scoreClass}">⚡ ${score}/100</span>
          <p class="card-title">${escapeHtml(clip.title)}</p>
          <p class="card-caption">${escapeHtml(clip.description || '')}</p>
          <p class="virality-reason">${escapeHtml(clip.virality_reason || '')}</p>
          <p class="card-tags">${escapeHtml(tags)}</p>
          <button class="card-dl">Download .mp4</button>
        </div>
      `;

      const imgEl = card.querySelector('.card-thumb');
      const thumbAsset = assetByName[clip.asset_thumbnail];
      if (thumbAsset) {
        fetchAssetBlob(owner, repo, token, thumbAsset).then((blob) => {
          imgEl.src = URL.createObjectURL(blob);
        }).catch(() => {});
      }

      const dlBtn = card.querySelector('.card-dl');
      dlBtn.addEventListener('click', async () => {
        const videoAsset = assetByName[clip.asset_video];
        if (!videoAsset) { showError('That clip file was not found in the release.'); return; }
        dlBtn.disabled = true;
        dlBtn.textContent = 'Fetching...';
        try {
          await downloadAsset(owner, repo, token, videoAsset, clip.asset_video);
        } catch (err) {
          showError(err.message);
        } finally {
          dlBtn.disabled = false;
          dlBtn.textContent = 'Download .mp4';
        }
      });

      grid.appendChild(card);
    });

    group.appendChild(grid);
    els.cards.appendChild(group);
  });
}

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
