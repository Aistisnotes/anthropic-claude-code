import express from 'express';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import fs from 'fs';
import https from 'https';
import http from 'http';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// --- Load .env file ---
function loadEnv() {
  const envPath = join(__dirname, '.env');
  if (!fs.existsSync(envPath)) return;
  const lines = fs.readFileSync(envPath, 'utf-8').split('\n');
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eqIdx = trimmed.indexOf('=');
    if (eqIdx === -1) continue;
    const key = trimmed.slice(0, eqIdx).trim();
    const val = trimmed.slice(eqIdx + 1).trim();
    if (!process.env[key]) process.env[key] = val;
  }
}
loadEnv();

const SEARCHAPI_KEY = process.env.SEARCHAPI_KEY || '';
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || '';

const app = express();
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.sendStatus(200);
  next();
});
app.use(express.json({ limit: '50mb' }));
app.use(express.static(join(__dirname, 'public')));

// Ensure results directory exists
const resultsDir = join(__dirname, 'results');
if (!fs.existsSync(resultsDir)) fs.mkdirSync(resultsDir, { recursive: true });

// --- Route: Check which API keys are configured ---
app.get('/api/config', (req, res) => {
  res.json({
    searchApiConfigured: !!SEARCHAPI_KEY,
    geminiConfigured: !!GEMINI_API_KEY,
  });
});

// --- Utility: HTTP GET with JSON response ---
function httpGetJson(url) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    mod.get(url, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error(`Failed to parse JSON from ${url.split('?')[0]}: ${data.slice(0, 200)}`)); }
      });
    }).on('error', reject);
  });
}

// --- Utility: HTTP GET raw buffer ---
function httpGetBuffer(url) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    mod.get(url, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        return httpGetBuffer(res.headers.location).then(resolve).catch(reject);
      }
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => resolve(Buffer.concat(chunks)));
    }).on('error', reject);
  });
}

// --- Utility: HTTP request with body ---
function httpRequest(url, options, body) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    const parsedUrl = new URL(url);
    const reqOptions = {
      hostname: parsedUrl.hostname,
      port: parsedUrl.port,
      path: parsedUrl.pathname + parsedUrl.search,
      ...options,
    };
    const req = mod.request(reqOptions, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try { resolve({ status: res.statusCode, data: JSON.parse(data) }); }
        catch { resolve({ status: res.statusCode, data }); }
      });
    });
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

// --- Extract page_id from Meta Ads Library URL ---
function extractPageId(url) {
  try {
    const parsed = new URL(url);
    const viewAll = parsed.searchParams.get('view_all_page_id');
    if (viewAll) return viewAll;
    // Try to find page_id in various patterns
    const match = url.match(/page_id[=:](\d+)/);
    if (match) return match[1];
    return null;
  } catch {
    return null;
  }
}

// --- Route: Fetch ads from SearchAPI ---
app.post('/api/fetch-ads', async (req, res) => {
  const { url: metaUrl } = req.body;

  if (!SEARCHAPI_KEY) {
    return res.status(500).json({ error: 'SEARCHAPI_KEY not configured. Add it to your .env file.' });
  }

  if (!metaUrl) {
    return res.status(400).json({ error: 'URL is required.' });
  }

  const pageId = extractPageId(metaUrl);
  if (!pageId) {
    return res.status(400).json({ error: 'Could not extract page_id from URL. Use a URL with view_all_page_id parameter (e.g. https://www.facebook.com/ads/library/?view_all_page_id=123456789).' });
  }

  try {
    const allAds = [];
    let nextPageToken = null;
    let pageNum = 0;
    const MAX_ADS = 200;

    // Set up SSE for progress
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.flushHeaders();

    const sendEvent = (type, data) => {
      res.write(`data: ${JSON.stringify({ type, ...data })}\n\n`);
    };

    sendEvent('progress', { message: `Starting fetch for page_id=${pageId}...`, count: 0 });

    while (allAds.length < MAX_ADS) {
      pageNum++;
      let apiUrl = `https://www.searchapi.io/api/v1/search?engine=meta_ad_library&page_id=${pageId}&ad_type=all&active_status=all&media_type=all&api_key=${SEARCHAPI_KEY}`;
      if (nextPageToken) {
        apiUrl += `&next_page_token=${encodeURIComponent(nextPageToken)}`;
      }

      sendEvent('progress', { message: `Fetching page ${pageNum}...`, count: allAds.length });

      let result;
      try {
        result = await httpGetJson(apiUrl);
      } catch (err) {
        sendEvent('error', { message: `API error on page ${pageNum}: ${err.message}` });
        break;
      }

      if (result.error) {
        sendEvent('error', { message: `SearchAPI error: ${JSON.stringify(result.error)}` });
        break;
      }

      const ads = result.ads || result.organic_results || [];
      if (ads.length === 0) {
        if (pageNum === 1) {
          sendEvent('error', { message: 'No ads found for this page. Check that the page_id is correct.' });
        }
        break;
      }

      allAds.push(...ads);
      sendEvent('progress', { message: `Fetched ${allAds.length} ads so far...`, count: allAds.length });

      nextPageToken = result.next_page_token || result.pagination?.next_page_token;
      if (!nextPageToken) break;
      if (allAds.length >= MAX_ADS) break;
    }

    // Process and filter ads
    const processed = allAds.slice(0, MAX_ADS).map((ad) => {
      const snapshot = ad.snapshot || ad;
      const bodyText = snapshot.body?.text || snapshot.body_text || ad.ad_creative_bodies?.join(' ') || '';
      const wordCount = bodyText.trim().split(/\s+/).filter(Boolean).length;

      const videoUrl = snapshot.video_hd_url || snapshot.video_sd_url
        || (snapshot.videos && snapshot.videos[0]?.video_hd_url)
        || (snapshot.videos && snapshot.videos[0]?.video_sd_url)
        || ad.video_hd_url || ad.video_sd_url || null;

      const imageUrl = (snapshot.images && snapshot.images[0]?.url)
        || (snapshot.images && snapshot.images[0]?.original_image_url)
        || (snapshot.cards && snapshot.cards[0]?.image_url)
        || ad.ad_creative_link_captions?.[0]
        || ad.image_url || null;

      const isVideo = !!videoUrl;
      const hasMedia = isVideo || !!imageUrl;

      return {
        ad_archive_id: ad.ad_archive_id || ad.id,
        page_name: ad.page_name || ad.advertiser_name || 'Unknown',
        start_date: ad.start_date || ad.ad_delivery_start_time,
        end_date: ad.end_date || ad.ad_delivery_stop_time || null,
        is_active: ad.is_active !== undefined ? ad.is_active : (ad.ad_delivery_stop_time ? false : true),
        publisher_platform: ad.publisher_platform || ad.publisher_platforms?.join(', ') || 'facebook',
        display_format: isVideo ? 'video' : 'static',
        body_text: bodyText,
        word_count: wordCount,
        video_url: videoUrl,
        image_url: imageUrl,
        cta_text: snapshot.cta_text || ad.ad_creative_link_titles?.[0] || '',
        thumbnail: imageUrl || null,
        has_media: hasMedia,
        is_video: isVideo,
      };
    });

    // Filter: include video ads always, static only if >400 words, exclude no-media-no-copy
    const filtered = processed.filter((ad) => {
      if (!ad.has_media && ad.word_count === 0) return false;
      if (ad.is_video) return true;
      if (ad.word_count > 400) return true;
      return false;
    });

    const excluded = processed.length - filtered.length;

    sendEvent('complete', {
      ads: filtered,
      total_fetched: processed.length,
      filtered_count: filtered.length,
      excluded_count: excluded,
    });
    res.end();
  } catch (err) {
    if (!res.headersSent) {
      return res.status(500).json({ error: err.message });
    }
    res.write(`data: ${JSON.stringify({ type: 'error', message: err.message })}\n\n`);
    res.end();
  }
});

// --- Route: Analyze a single ad with Gemini ---
app.post('/api/analyze-ad', async (req, res) => {
  const { ad, layers } = req.body;

  if (!GEMINI_API_KEY) {
    return res.status(500).json({ error: 'GEMINI_API_KEY not configured. Add it to your .env file.' });
  }

  if (!ad) {
    return res.status(400).json({ error: 'Ad data is required.' });
  }

  try {
    let analysisResult;

    if (ad.is_video && ad.video_url) {
      analysisResult = await analyzeVideoAd(ad, layers);
    } else {
      analysisResult = await analyzeStaticAd(ad, layers);
    }

    // Save result
    const filename = `ad_${ad.ad_archive_id}_${Date.now()}.json`;
    fs.writeFileSync(join(resultsDir, filename), JSON.stringify(analysisResult, null, 2));

    res.json({ success: true, result: analysisResult, filename });
  } catch (err) {
    console.error(`Analysis failed for ad ${ad.ad_archive_id}: ${err.message}`);
    res.status(500).json({ error: err.message, ad_id: ad.ad_archive_id });
  }
});

// --- Route: Cross-ad pattern summary ---
app.post('/api/pattern-summary', async (req, res) => {
  const { analyses } = req.body;

  if (!GEMINI_API_KEY) {
    return res.status(500).json({ error: 'GEMINI_API_KEY not configured. Add it to your .env file.' });
  }

  if (!analyses) {
    return res.status(400).json({ error: 'Analyses data required.' });
  }

  try {
    const prompt = buildPatternSummaryPrompt(analyses);
    const result = await callGemini(prompt, null);

    const filename = `pattern_summary_${Date.now()}.json`;
    fs.writeFileSync(join(resultsDir, filename), JSON.stringify(result, null, 2));

    res.json({ success: true, result, filename });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// --- Analyze video ad ---
async function analyzeVideoAd(ad, layers) {
  let fileUri = null;

  try {
    // Download video
    const videoBuffer = await httpGetBuffer(ad.video_url);

    // Upload to Gemini Files API
    const uploadUrl = `https://generativelanguage.googleapis.com/upload/v1beta/files?key=${GEMINI_API_KEY}`;

    const metadata = JSON.stringify({
      file: { display_name: `ad_${ad.ad_archive_id}` }
    });

    const boundary = '---BOUNDARY' + Date.now();
    const bodyParts = [
      `--${boundary}\r\n`,
      'Content-Type: application/json; charset=UTF-8\r\n\r\n',
      metadata + '\r\n',
      `--${boundary}\r\n`,
      'Content-Type: video/mp4\r\n\r\n',
    ];

    const bodyStart = Buffer.from(bodyParts.join(''));
    const bodyEnd = Buffer.from(`\r\n--${boundary}--\r\n`);
    const fullBody = Buffer.concat([bodyStart, videoBuffer, bodyEnd]);

    const uploadResult = await httpRequest(uploadUrl, {
      method: 'POST',
      headers: {
        'Content-Type': `multipart/related; boundary=${boundary}`,
        'Content-Length': fullBody.length,
      },
    }, fullBody);

    if (uploadResult.data?.file?.uri) {
      fileUri = uploadResult.data.file.uri;

      // Wait for file processing
      const fileName = uploadResult.data.file.name;
      let fileState = uploadResult.data.file.state;
      let attempts = 0;
      while (fileState === 'PROCESSING' && attempts < 30) {
        await new Promise(r => setTimeout(r, 2000));
        const statusUrl = `https://generativelanguage.googleapis.com/v1beta/${fileName}?key=${GEMINI_API_KEY}`;
        const statusResult = await httpGetJson(statusUrl);
        fileState = statusResult.state;
        attempts++;
      }

      if (fileState !== 'ACTIVE') {
        throw new Error('Video file processing timed out');
      }
    }
  } catch (err) {
    console.error(`Video upload failed for ad ${ad.ad_archive_id}: ${err.message}`);
    fileUri = null;
  }

  const prompt = buildAnalysisPrompt(ad, layers, true);

  if (fileUri) {
    return await callGemini(prompt, fileUri);
  } else {
    const fallbackPrompt = `[VIDEO COULD NOT BE PROCESSED — analyze based on copy text only]\n\n${prompt}`;
    return await callGemini(fallbackPrompt, null);
  }
}

// --- Analyze static ad ---
async function analyzeStaticAd(ad, layers) {
  const prompt = buildAnalysisPrompt(ad, layers, false);
  const imageUrl = ad.image_url;

  if (imageUrl) {
    return await callGemini(prompt, null, imageUrl);
  } else {
    return await callGemini(prompt, null);
  }
}

// --- Call Gemini API ---
async function callGemini(prompt, fileUri, imageUrl) {
  const model = 'gemini-2.5-flash-preview-05-20';
  const apiUrl = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${GEMINI_API_KEY}`;

  const parts = [];

  if (fileUri) {
    parts.push({ fileData: { mimeType: 'video/mp4', fileUri } });
  }

  if (imageUrl) {
    parts.push({ text: `Image URL for this ad: ${imageUrl}` });
    try {
      const imgBuffer = await httpGetBuffer(imageUrl);
      const base64 = imgBuffer.toString('base64');
      const mime = imageUrl.includes('.png') ? 'image/png' : 'image/jpeg';
      parts.push({ inlineData: { mimeType: mime, data: base64 } });
    } catch {
      // If image download fails, just use the URL reference in prompt
    }
  }

  parts.push({ text: prompt });

  const body = JSON.stringify({
    contents: [{ parts }],
    generationConfig: {
      temperature: 0.2,
      maxOutputTokens: 65536,
      responseMimeType: 'application/json',
    },
  });

  const result = await httpRequest(apiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  }, body);

  if (result.status !== 200) {
    throw new Error(`Gemini API error (${result.status}): ${JSON.stringify(result.data)}`);
  }

  const text = result.data?.candidates?.[0]?.content?.parts?.[0]?.text || '';

  // Strip markdown fences if present
  const cleaned = text.replace(/^```(?:json)?\s*\n?/i, '').replace(/\n?```\s*$/i, '').trim();

  try {
    return JSON.parse(cleaned);
  } catch {
    return { raw_response: cleaned, parse_error: true };
  }
}

// --- Build analysis prompt ---
function buildAnalysisPrompt(ad, layers, isVideo) {
  const enableL1 = !layers || layers.L1 !== false;
  const enableL2 = !layers || layers.L2 !== false;
  const enableL3 = !layers || layers.L3 !== false;

  let prompt = '';

  if (isVideo) {
    prompt += `You are analyzing a direct-response video ad. Watch the FULL video before analyzing. `;
  } else {
    prompt += `You are analyzing a direct-response static/image ad. Read the FULL copy and examine the image carefully. `;
  }

  prompt += `Extract ONLY what is explicitly shown or stated in the ad — NEVER infer or invent information that isn't present.

AD METADATA:
- Brand: ${ad.page_name}
- Ad ID: ${ad.ad_archive_id}
- Platform: ${ad.publisher_platform}
- Format: ${ad.display_format}
- Active: ${ad.is_active ? 'Yes' : 'No'}
- Start Date: ${ad.start_date || 'Unknown'}
- CTA: ${ad.cta_text || 'None'}

AD COPY TEXT:
${ad.body_text || '[No copy text available]'}

Return a single valid JSON object with the following structure:
{
  "ad_archive_id": "${ad.ad_archive_id}",
  "page_name": "${ad.page_name}",
  "format": "${ad.display_format}",`;

  if (enableL1) {
    prompt += `
  "layer_1": {
    "target": {
      "target_customer_profile": "...",
      "target_demographics": "...",
      "target_psychographics": "...",
      "avatar": "Full composite description of ideal customer"
    },
    "pain": {
      "pain_points": ["exact language from ad"],
      "pain_point_symptoms": ["observable daily experiences"]
    },
    "root_cause": {
      "root_cause": "stated root cause",
      "root_cause_chain": ["upstream", "stated", "downstream", "symptom"],
      "root_cause_depth": "surface | moderate | deep | cellular"
    },
    "mechanism": {
      "mechanism": "how product solves it",
      "mechanism_depth": "claim-only | process-level | cellular-molecular",
      "scientific_note": "real science behind it if any"
    },
    "concept": "RC + mechanism combined as single argument unit",
    "proof": {
      "proof_elements": ["..."],
      "proof_gaps": ["claims without evidence"]
    },
    "beliefs": {
      "beliefs_installed": ["..."],
      "beliefs_missing": ["what a skeptic still questions"]
    },
    "objections": {
      "objections_handled": ["..."],
      "objections_open": ["..."]
    },
    "ingredient_transparency": {
      "score": 0,
      "notes": "..."
    },
    "unfalsifiability": {
      "techniques": ["..."],
      "cracks": ["..."]
    },
    "persuasion_architecture": {
      "mass_desire": "...",
      "big_idea": "...",
      "ad_angle": "...",
      "emotional_triggers": ["..."],
      "emotional_sequence": ["ordered array"],
      "awareness_level": "Unaware | Problem Aware | Solution Aware | Product Aware | Most Aware",
      "sophistication_level": 1,
      "hook_type": "...",
      "hook_psychology": "...",
      "cta_strategy": "..."
    },
    "scores": {
      "analysis_confidence": 0.0,
      "copy_quality_score": 0.0
    }
  },`;
  }

  if (enableL2) {
    prompt += `
  "layer_2": {
    "competitive_verdict": "single biggest vulnerability",
    "root_cause_gaps": {
      "missing_upstream_explanations": ["..."],
      "execution_angles": ["..."]
    },
    "mechanism_gaps": {
      "where_mechanism_stops_short": ["..."],
      "how_to_go_deeper": ["..."]
    },
    "proof_gaps": {
      "unproven_claims": ["..."],
      "how_to_exploit": ["..."]
    },
    "belief_gaps": {
      "missing_belief_installations": ["..."],
      "competitive_moat_opportunity": "..."
    },
    "objection_gaps": {
      "unhandled_objections": ["..."],
      "steal_angle": "..."
    },
    "what_nobody_does_well": ["market-wide openings"],
    "loopholes": [
      {
        "gap": "...",
        "science": "real biochemistry",
        "execution_hooks": ["..."],
        "score": 0,
        "effort": "low | medium | high",
        "timeline": "..."
      }
    ],
    "what_not_to_do": ["tempting-but-wrong approaches"]
  },`;
  }

  if (enableL3) {
    prompt += `
  "layer_3": {
    "root_causes": [
      {
        "claim": "...",
        "depth_level": "...",
        "upstream_gap": "...",
        "psychological_principle": "villain externalization | KISS | processing fluency"
      }
    ],
    "mechanisms": [
      {
        "mechanism": "...",
        "type": "new_mechanism | new_information | new_identity",
        "believability_score": 0.0,
        "notes": "..."
      }
    ],
    "target_audiences": [
      {
        "demographics": "...",
        "psychographics": "...",
        "identity": "People who are..."
      }
    ],
    "pain_points": [
      {
        "pain": "...",
        "intensity": "low | medium | high",
        "emotional_trigger": "fear | shame | frustration | anxiety | loss | regret"
      }
    ],
    "symptoms": ["daily lived experiences"],
    "mass_desires": [
      {
        "transformation": "...",
        "timeframe": "...",
        "specificity": "vague | moderate | measurable"
      }
    ]
  },`;
  }

  prompt += `
}

CRITICAL: Return ONLY valid JSON. No markdown, no explanation, no text outside the JSON object. Every array must have at least one item. Loopholes array must have 5-8 items, each scored 0-50.`;

  return prompt;
}

// --- Build pattern summary prompt ---
function buildPatternSummaryPrompt(analyses) {
  const analysesJson = JSON.stringify(analyses, null, 2);

  return `You are a direct-response marketing strategist analyzing a batch of ad analyses. Below are the Layer 1 analysis results for multiple ads from the same brand or market.

ALL AD ANALYSES:
${analysesJson}

Perform a meta-analysis and return a single valid JSON object with:
{
  "pattern_summary": {
    "most_common_hook_types": ["..."],
    "awareness_level_distribution": {"Unaware": 0, "Problem Aware": 0, "Solution Aware": 0, "Product Aware": 0, "Most Aware": 0},
    "dominant_rc_mechanism_combos": ["RC + Mechanism description"],
    "recurring_proof_gaps": ["..."],
    "recurring_objection_gaps": ["..."],
    "biggest_market_loophole": "the single biggest market-wide loophole across all ads",
    "sophistication_distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
    "brand_strengths": ["what the brand does consistently well"],
    "brand_weaknesses": ["what the brand consistently misses"],
    "emotional_trigger_frequency": {"trigger": "count"},
    "total_ads_analyzed": ${analyses.length},
    "average_copy_quality": 0.0,
    "average_analysis_confidence": 0.0
  }
}

CRITICAL: Return ONLY valid JSON. No markdown, no explanation.`;
}

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Ads Library Patterns server running on http://localhost:${PORT}`);
  console.log(`  SearchAPI key: ${SEARCHAPI_KEY ? 'configured' : 'MISSING — add SEARCHAPI_KEY to .env'}`);
  console.log(`  Gemini key:    ${GEMINI_API_KEY ? 'configured' : 'MISSING — add GEMINI_API_KEY to .env'}`);
});
