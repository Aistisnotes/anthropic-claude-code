/* Ads Library Patterns — Frontend */

const state = {
  ads: [],
  selectedIds: new Set(),
  results: {},
  patternSummary: null,
  currentFilter: 'all',
  keysReady: false,
  sessionId: null,
  brandName: null,
  searchQuery: null,
};

// --- DOM refs ---
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const stepFetch = $('#step-fetch');
const stepSelect = $('#step-select');
const stepAnalyze = $('#step-analyze');
const stepResults = $('#step-results');

const metaUrlInput = $('#meta-url');
const keyStatus = $('#key-status');
const btnFetch = $('#btn-fetch');
const fetchProgress = $('#fetch-progress');
const fetchStatus = $('#fetch-status');
const fetchError = $('#fetch-error');

const filterInfo = $('#filter-info');
const adsGrid = $('#ads-grid');
const selectCounter = $('#select-counter');
const btnSelectAll = $('#btn-select-all');
const btnDeselectAll = $('#btn-deselect-all');
const btnToAnalyze = $('#btn-to-analyze');

const btnAnalyze = $('#btn-analyze');
const analyzeProgress = $('#analyze-progress');
const analyzeBar = $('#analyze-bar');
const analyzeStatus = $('#analyze-status');

const patternSummaryEl = $('#pattern-summary');
const resultsGrid = $('#results-grid');
const reportPanel = $('#report-panel');
const btnPdfReport = $('#btn-pdf-report');

// ==========================================
// INIT: Check API key config on load
// ==========================================
(async function checkConfig() {
  console.log('[ALP] Checking API key config...');
  try {
    const resp = await fetch('/api/config');
    const cfg = await resp.json();
    console.log('[ALP] Config response:', cfg);

    const searchOk = cfg.searchApiConfigured;
    const geminiOk = cfg.geminiConfigured;

    if (searchOk && geminiOk) {
      keyStatus.textContent = 'API keys configured (SearchAPI + Gemini)';
      keyStatus.className = 'key-status ok';
      state.keysReady = true;
    } else {
      const missing = [];
      if (!searchOk) missing.push('SEARCHAPI_KEY');
      if (!geminiOk) missing.push('GEMINI_API_KEY');
      keyStatus.textContent = `Missing in .env: ${missing.join(', ')}`;
      keyStatus.className = 'key-status missing';
      state.keysReady = false;
    }
  } catch (err) {
    keyStatus.textContent = 'Cannot reach server — is it running?';
    keyStatus.className = 'key-status missing';
  }
})();

// ==========================================
// STEP 1: FETCH
// ==========================================
btnFetch.addEventListener('click', async () => {
  console.log('[ALP] Fetch button clicked');
  const url = metaUrlInput.value.trim();

  if (!url) {
    showError(fetchError, 'Please enter a Meta Ads Library URL.');
    return;
  }

  if (!state.keysReady) {
    showError(fetchError, 'API keys not configured. Add SEARCHAPI_KEY and GEMINI_API_KEY to your .env file and restart the server.');
    return;
  }

  hideError(fetchError);
  btnFetch.disabled = true;
  fetchProgress.classList.remove('hidden');
  fetchStatus.textContent = 'Connecting...';

  try {
    const response = await fetch('/api/fetch-ads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });

    console.log('[ALP] Fetch response status:', response.status, 'content-type:', response.headers.get('content-type'));

    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('text/event-stream')) {
      let errMsg = `Server error (${response.status})`;
      try {
        const errData = await response.json();
        errMsg = errData.error || errMsg;
      } catch {}
      console.error('[ALP] Non-SSE error:', errMsg);
      showError(fetchError, errMsg);
      btnFetch.disabled = false;
      fetchProgress.classList.add('hidden');
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const event = JSON.parse(line.slice(6));
          if (event.type === 'progress') {
            fetchStatus.textContent = event.message;
          } else if (event.type === 'error') {
            showError(fetchError, event.message);
          } else if (event.type === 'complete') {
            state.ads = event.ads;
            filterInfo.textContent = `${event.filtered_count} qualifying ads (${event.excluded_count} excluded of ${event.total_fetched} total)`;
            if (event.filtered_count === 0) {
              showError(fetchError, `Fetched ${event.total_fetched} ads but none matched filters (video ads, or static with >400 words). ${event.excluded_count} were excluded.`);
            } else {
              renderAdsGrid();
              stepSelect.classList.remove('hidden');
              stepSelect.scrollIntoView({ behavior: 'smooth' });
            }
            fetchProgress.classList.add('hidden');
          }
        } catch (e) {
          console.error('SSE parse error:', e, 'line:', line);
        }
      }
    }
  } catch (err) {
    showError(fetchError, `Fetch failed: ${err.message}`);
  }

  btnFetch.disabled = false;
  fetchProgress.classList.add('hidden');
});

// ==========================================
// STEP 2: SELECT
// ==========================================
function renderAdsGrid() {
  adsGrid.innerHTML = '';

  state.ads.forEach((ad) => {
    const card = document.createElement('div');
    card.className = 'ad-card';
    card.dataset.id = String(ad.ad_archive_id);
    card.dataset.format = ad.display_format;
    card.dataset.active = ad.is_active ? 'true' : 'false';

    const placeholderLabel = ad.is_video ? '<span class="play-icon">\u25B6</span> VIDEO' : 'IMAGE';
    const thumbHtml = ad.thumbnail
      ? `<img class="ad-thumb" src="${escHtml(ad.thumbnail)}" alt="" loading="lazy" onerror="this.outerHTML='<div class=\\'ad-thumb-placeholder\\'>${placeholderLabel}</div>'">`
      : `<div class="ad-thumb-placeholder">${placeholderLabel}</div>`;

    const copyPreview = ad.body_text ? ad.body_text.slice(0, 150) : 'No copy';

    card.innerHTML = `
      <div class="ad-card-checkbox"></div>
      ${thumbHtml}
      <div class="ad-info">
        <div class="ad-brand">${escHtml(ad.page_name)}</div>
        <div class="ad-badges">
          <span class="badge ${ad.is_video ? 'badge-video' : 'badge-static'}">${ad.is_video ? 'VIDEO' : 'STATIC'}</span>
          <span class="badge ${ad.is_active ? 'badge-active' : 'badge-inactive'}">${ad.is_active ? 'ACTIVE' : 'INACTIVE'}</span>
          ${!ad.is_video ? `<span class="badge badge-words">${ad.word_count}w</span>` : ''}
        </div>
        <div class="ad-date">${escHtml(ad.start_date || 'Unknown date')} · ${escHtml(ad.publisher_platform)}</div>
        <div class="ad-copy-preview">${escHtml(copyPreview)}</div>
      </div>
    `;

    card.addEventListener('click', () => toggleSelect(String(ad.ad_archive_id), card));
    adsGrid.appendChild(card);
  });

  updateCounter();
}

function toggleSelect(id, card) {
  if (state.selectedIds.has(id)) {
    state.selectedIds.delete(id);
    card.classList.remove('selected');
  } else {
    state.selectedIds.add(id);
    card.classList.add('selected');
  }
  updateCounter();
}

function updateCounter() {
  const visible = adsGrid.querySelectorAll('.ad-card:not(.hidden-by-filter)').length;
  selectCounter.textContent = `${state.selectedIds.size} of ${visible} selected`;
}

btnSelectAll.addEventListener('click', () => {
  adsGrid.querySelectorAll('.ad-card:not(.hidden-by-filter)').forEach((card) => {
    state.selectedIds.add(card.dataset.id);
    card.classList.add('selected');
  });
  updateCounter();
});

btnDeselectAll.addEventListener('click', () => {
  state.selectedIds.clear();
  adsGrid.querySelectorAll('.ad-card').forEach((c) => c.classList.remove('selected'));
  updateCounter();
});

$$('.filter-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('.filter-btn').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    state.currentFilter = btn.dataset.filter;
    applyFilter();
  });
});

function applyFilter() {
  adsGrid.querySelectorAll('.ad-card').forEach((card) => {
    let show = true;
    if (state.currentFilter === 'video') show = card.dataset.format === 'video';
    if (state.currentFilter === 'static') show = card.dataset.format === 'static';
    if (state.currentFilter === 'active') show = card.dataset.active === 'true';
    card.classList.toggle('hidden-by-filter', !show);
  });
  updateCounter();
}

btnToAnalyze.addEventListener('click', () => {
  if (state.selectedIds.size === 0) {
    alert('Select at least one ad to analyze.');
    return;
  }
  stepAnalyze.classList.remove('hidden');
  stepAnalyze.scrollIntoView({ behavior: 'smooth' });
});

// ==========================================
// STEP 3: ANALYZE
// ==========================================
btnAnalyze.addEventListener('click', async () => {
  const layers = {
    L1: $('#toggle-l1').checked,
    L2: $('#toggle-l2').checked,
    L3: $('#toggle-l3').checked,
  };

  const selectedAds = state.ads.filter((a) => state.selectedIds.has(String(a.ad_archive_id)));
  const total = selectedAds.length;
  console.log('[ALP] Analyze clicked, selected:', total, 'ads');

  if (total === 0) {
    alert('No ads selected. Go back and select ads first.');
    return;
  }

  // Create session
  console.log('[ALP] Creating session...');
  try {
    const sessResp = await fetch('/api/session', { method: 'POST' });
    const sessData = await sessResp.json();
    state.sessionId = sessData.sessionId;
    console.log('[ALP] Session created:', state.sessionId);
  } catch (err) {
    state.sessionId = `${Date.now()}_local`;
    console.error('[ALP] Session creation failed, using local ID:', state.sessionId, err);
  }

  state.brandName = selectedAds[0]?.page_name || null;
  state.searchQuery = metaUrlInput.value.trim();

  let completed = 0;

  btnAnalyze.disabled = true;
  analyzeProgress.classList.remove('hidden');
  stepResults.classList.remove('hidden');
  reportPanel.classList.add('hidden'); // hide until done
  resultsGrid.innerHTML = '';
  state.results = {};
  state.patternSummary = null;

  selectedAds.forEach((ad) => {
    resultsGrid.appendChild(createResultCard(ad));
  });

  stepResults.scrollIntoView({ behavior: 'smooth' });

  // Process in batches of 5
  const batchSize = 5;
  for (let i = 0; i < selectedAds.length; i += batchSize) {
    const batch = selectedAds.slice(i, i + batchSize);
    const promises = batch.map(async (ad) => {
      try {
        const resp = await fetch('/api/analyze-ad', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ad, layers }),
        });
        const data = await resp.json();
        if (data.success) {
          state.results[ad.ad_archive_id] = data.result;
          updateResultCard(ad.ad_archive_id, 'done', data.result);
        } else {
          state.results[ad.ad_archive_id] = { error: data.error };
          updateResultCard(ad.ad_archive_id, 'error', data.error);
        }
      } catch (err) {
        state.results[ad.ad_archive_id] = { error: err.message };
        updateResultCard(ad.ad_archive_id, 'error', err.message);
      }
      completed++;
      analyzeBar.style.width = `${(completed / total) * 100}%`;
      analyzeStatus.textContent = `${completed} / ${total} complete`;
    });
    await Promise.all(promises);
  }

  console.log('[ALP] All ads analyzed. Results keys:', Object.keys(state.results).length);

  // === POST-ANALYSIS FLOW ===
  // Everything below is wrapped so one failure cannot prevent the report button from appearing.
  const statusArea = document.getElementById('post-analysis-status');
  statusArea.innerHTML = '';
  statusArea.classList.remove('hidden');

  function addStatusMsg(text, type) {
    const div = document.createElement('div');
    div.className = `post-analysis-msg ${type}`;
    div.textContent = text;
    statusArea.appendChild(div);
    console.log(`[ALP] [${type}] ${text}`);
  }

  const successfulAnalyses = Object.values(state.results).filter((r) => !r.error && !r.parse_error);
  const failedCount = Object.keys(state.results).length - successfulAnalyses.length;
  console.log('[ALP] Successful analyses:', successfulAnalyses.length, 'Failed:', failedCount);

  if (failedCount > 0) {
    addStatusMsg(`${failedCount} ad(s) failed analysis — see individual cards for errors.`, 'error');
  }

  // --- Pattern summary ---
  if (successfulAnalyses.length >= 1) {
    analyzeStatus.textContent = 'Generating pattern summary...';
    addStatusMsg('Generating cross-ad pattern summary...', 'info');
    try {
      const resp = await fetch('/api/pattern-summary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analyses: successfulAnalyses }),
      });
      console.log('[ALP] Pattern summary response status:', resp.status);
      const data = await resp.json();
      console.log('[ALP] Pattern summary response data:', data.success, data.error);
      if (data.success) {
        state.patternSummary = data.result;
        renderPatternSummary(data.result);
        addStatusMsg('Pattern summary generated.', 'success');
      } else {
        addStatusMsg(`Pattern summary failed: ${data.error || 'Unknown error'}`, 'error');
      }
    } catch (err) {
      console.error('[ALP] Pattern summary error:', err);
      addStatusMsg(`Pattern summary failed: ${err.message}`, 'error');
    }
  } else {
    addStatusMsg('Pattern summary skipped — no successful ad analyses.', 'info');
  }

  // --- Save session ---
  try {
    analyzeStatus.textContent = 'Saving results...';
    console.log('[ALP] Saving session', state.sessionId);
    const saveResp = await fetch(`/api/session/${state.sessionId}/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        results: state.results,
        patternSummary: state.patternSummary,
        brandName: state.brandName,
        searchQuery: state.searchQuery,
      }),
    });
    const saveData = await saveResp.json();
    console.log('[ALP] Save response:', saveData);
    if (saveData.success) {
      addStatusMsg(`Results saved (${saveData.fileSize} bytes).`, 'success');
    } else {
      addStatusMsg(`Save failed: ${saveData.error || 'Unknown error'}`, 'error');
    }
  } catch (err) {
    console.error('[ALP] Save error:', err);
    addStatusMsg(`Save failed: ${err.message}`, 'error');
  }

  // --- ALWAYS show report button ---
  console.log('[ALP] Showing report panel');
  reportPanel.classList.remove('hidden');

  analyzeStatus.textContent = `${completed} / ${total} complete — Done`;
  btnAnalyze.disabled = false;
});

// ==========================================
// REPORT DOWNLOAD
// ==========================================
btnPdfReport.addEventListener('click', async () => {
  console.log('[ALP] PDF download clicked, sessionId:', state.sessionId);
  btnPdfReport.disabled = true;
  btnPdfReport.textContent = 'Generating...';
  try {
    const resp = await fetch(`/api/report/${state.sessionId}`);
    console.log('[ALP] PDF response:', resp.status, resp.headers.get('content-type'));
    if (!resp.ok) {
      let errMsg = 'Failed to generate PDF';
      try {
        const err = await resp.json();
        errMsg = err.error || errMsg;
      } catch {}
      alert(errMsg);
      return;
    }
    const blob = await resp.blob();
    console.log('[ALP] PDF blob size:', blob.size);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = resp.headers.get('content-disposition')?.match(/filename="(.+)"/)?.[1] || 'report.pdf';
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error('[ALP] PDF download error:', err);
    alert('PDF generation failed: ' + err.message);
  } finally {
    btnPdfReport.disabled = false;
    btnPdfReport.textContent = 'Download Report';
  }
});

// ==========================================
// RESULT CARDS
// ==========================================
function createResultCard(ad) {
  const card = document.createElement('div');
  card.className = 'result-card';
  card.id = `result-${ad.ad_archive_id}`;

  card.innerHTML = `
    <div class="result-card-header" onclick="toggleResultCard('${ad.ad_archive_id}')">
      <div class="result-card-title">
        <div class="result-status loading"><div class="spinner"></div></div>
        <span>${escHtml(ad.page_name)} — ${ad.display_format.toUpperCase()} — ${ad.ad_archive_id}</span>
      </div>
      <span class="result-toggle">&#9660;</span>
    </div>
    <div class="result-card-body">
      <div class="json-tree">Analyzing...</div>
    </div>
  `;

  return card;
}

window.toggleResultCard = function (id) {
  const card = document.getElementById(`result-${id}`);
  if (card) card.classList.toggle('expanded');
};

function updateResultCard(id, status, data) {
  const card = document.getElementById(`result-${id}`);
  if (!card) return;

  const statusEl = card.querySelector('.result-status');
  statusEl.classList.remove('loading');

  if (status === 'done') {
    statusEl.classList.add('done');
    statusEl.innerHTML = '&#10003;';
    card.querySelector('.result-card-body').innerHTML = renderAnalysisResult(data);
  } else {
    statusEl.classList.add('error');
    statusEl.innerHTML = '&#10007;';
    card.querySelector('.result-card-body').innerHTML = `<div class="error-msg">${escHtml(String(data))}</div>`;
  }
}

function renderAnalysisResult(data) {
  let html = '';

  if (data.layer_1) {
    html += `<div class="layer-section">
      <div class="layer-title">LAYER 1 — AD DISSECTION</div>
      <div class="json-tree">${renderJson(data.layer_1)}</div>
    </div>`;
  }

  if (data.layer_2) {
    html += `<div class="layer-section">
      <div class="layer-title">LAYER 2 — PATTERN INTELLIGENCE</div>`;

    if (data.layer_2.loopholes && Array.isArray(data.layer_2.loopholes)) {
      const sorted = [...data.layer_2.loopholes].sort((a, b) => (b.score || 0) - (a.score || 0));
      html += `<table class="loopholes-table">
        <thead><tr><th>Score</th><th>Gap</th><th>Science</th><th>Effort</th><th>Timeline</th></tr></thead>
        <tbody>`;
      sorted.forEach((l) => {
        html += `<tr>
          <td><span class="loophole-score">${l.score || 0}/50</span></td>
          <td>${escHtml(l.gap || '')}</td>
          <td>${escHtml(l.science || '')}</td>
          <td>${escHtml(l.effort || '')}</td>
          <td>${escHtml(l.timeline || '')}</td>
        </tr>`;
      });
      html += `</tbody></table>`;

      const l2Rest = { ...data.layer_2 };
      delete l2Rest.loopholes;
      html += `<div class="json-tree" style="margin-top:12px">${renderJson(l2Rest)}</div>`;
    } else {
      html += `<div class="json-tree">${renderJson(data.layer_2)}</div>`;
    }

    html += `</div>`;
  }

  if (data.layer_3) {
    html += `<div class="layer-section">
      <div class="layer-title">LAYER 3 — STRATEGIC DIMENSION MAP</div>
      <div class="json-tree">${renderJson(data.layer_3)}</div>
    </div>`;
  }

  if (!data.layer_1 && !data.layer_2 && !data.layer_3) {
    html += `<div class="json-tree">${renderJson(data)}</div>`;
  }

  return html;
}

// ==========================================
// PATTERN SUMMARY
// ==========================================
function renderPatternSummary(data) {
  patternSummaryEl.classList.remove('hidden');
  const summary = data.pattern_summary || data;

  let html = '<h3>Pattern Summary</h3><div class="pattern-grid">';

  const items = [
    ['Biggest Market Loophole', summary.biggest_market_loophole],
    ['Common Hook Types', summary.most_common_hook_types],
    ['Dominant RC+Mechanism Combos', summary.dominant_rc_mechanism_combos],
    ['Recurring Proof Gaps', summary.recurring_proof_gaps],
    ['Recurring Objection Gaps', summary.recurring_objection_gaps],
    ['Brand Strengths', summary.brand_strengths],
    ['Brand Weaknesses', summary.brand_weaknesses],
    ['Awareness Distribution', summary.awareness_level_distribution],
    ['Sophistication Distribution', summary.sophistication_distribution],
    ['Ads Analyzed', summary.total_ads_analyzed],
    ['Avg Copy Quality', summary.average_copy_quality],
    ['Avg Confidence', summary.average_analysis_confidence],
  ];

  items.forEach(([label, value]) => {
    if (value === undefined || value === null) return;
    html += `<div class="pattern-item">
      <div class="pattern-item-label">${escHtml(label)}</div>
      <div class="pattern-item-value">${formatPatternValue(value)}</div>
    </div>`;
  });

  html += '</div>';
  patternSummaryEl.innerHTML = html;
}

function formatPatternValue(val) {
  if (Array.isArray(val)) {
    return '<ul>' + val.map((v) => `<li>${escHtml(String(v))}</li>`).join('') + '</ul>';
  }
  if (typeof val === 'object') {
    return '<ul>' + Object.entries(val).map(([k, v]) => `<li>${escHtml(k)}: ${escHtml(String(v))}</li>`).join('') + '</ul>';
  }
  return escHtml(String(val));
}

// ==========================================
// UTILITIES
// ==========================================
function escHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function showError(el, msg) {
  el.textContent = msg;
  el.classList.remove('hidden');
}

function hideError(el) {
  el.classList.add('hidden');
}

function renderJson(obj, indent = 0) {
  if (obj === null) return '<span class="json-null">null</span>';
  if (typeof obj === 'boolean') return `<span class="json-bool">${obj}</span>`;
  if (typeof obj === 'number') return `<span class="json-number">${obj}</span>`;
  if (typeof obj === 'string') return `<span class="json-string">"${escHtml(obj)}"</span>`;

  const pad = '  '.repeat(indent);
  const padInner = '  '.repeat(indent + 1);

  if (Array.isArray(obj)) {
    if (obj.length === 0) return '<span class="json-bracket">[]</span>';
    const items = obj.map((v) => `${padInner}${renderJson(v, indent + 1)}`).join(',\n');
    return `<span class="json-bracket">[</span>\n${items}\n${pad}<span class="json-bracket">]</span>`;
  }

  const keys = Object.keys(obj);
  if (keys.length === 0) return '<span class="json-bracket">{}</span>';
  const entries = keys.map((k) => {
    return `${padInner}<span class="json-key">"${escHtml(k)}"</span>: ${renderJson(obj[k], indent + 1)}`;
  }).join(',\n');
  return `<span class="json-bracket">{</span>\n${entries}\n${pad}<span class="json-bracket">}</span>`;
}
