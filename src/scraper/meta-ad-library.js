import { chromium } from 'playwright';
import { config } from '../utils/config.js';
import { log } from '../utils/logger.js';

/**
 * Meta Ad Library web scraper — direct page scraping, no API token required.
 *
 * Fetches ad data by scraping the public Meta Ad Library search page using Playwright.
 * Extracts ad metadata from embedded JSON data in the page's HTML.
 *
 * Public URL: https://www.facebook.com/ads/library/
 */

const AD_LIBRARY_BASE = 'https://www.facebook.com/ads/library/';

/**
 * Build the Ad Library search URL.
 */
function buildSearchUrl(keyword, opts = {}) {
  const params = new URLSearchParams({
    active_status: (opts.activeStatus || 'all').toLowerCase(),
    ad_type: 'all',
    country: opts.country || 'US',
    q: keyword,
    search_type: 'keyword_unordered',
    media_type: 'all',
  });
  return `${AD_LIBRARY_BASE}?${params}`;
}

/**
 * Sleep helper for rate limiting.
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ─── Browser Management ──────────────────────────────────────

/**
 * Launch a Playwright browser instance.
 */
async function launchBrowser() {
  const browser = await chromium.launch({
    headless: true,
    args: [
      '--disable-blink-features=AutomationControlled',
      '--disable-dev-shm-usage',
      '--no-sandbox',
    ],
  });

  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    viewport: { width: 1920, height: 1080 },
    locale: 'en-US',
  });

  const page = await context.newPage();
  return { browser, context, page };
}

// ─── Data Extraction ─────────────────────────────────────────

/**
 * Extract ad data from an Ad Library search page HTML response.
 * Tries multiple parsing strategies for resilience.
 */
function extractAdsFromHtml(html) {
  const ads = [];

  // Primary strategy: Extract from <script type="application/json"> blocks with Relay data
  const jsonScripts = html.matchAll(/<script type="application\/json"[^>]*>([\s\S]*?)<\/script>/gi);
  for (const match of jsonScripts) {
    try {
      const data = JSON.parse(match[1]);
      findAdNodes(data, ads);
    } catch {
      // Skip invalid JSON
    }
  }

  // Fallback: Extract from <script data-sjs> JSON blocks
  if (ads.length === 0) {
    const sjsMatches = html.matchAll(/<script[^>]*data-sjs[^>]*>([\s\S]*?)<\/script>/gi);
    for (const match of sjsMatches) {
      try {
        const data = JSON.parse(match[1]);
        findAdNodes(data, ads);
      } catch {
        // Not valid JSON, skip
      }
    }
  }

  // Last resort: Direct regex extraction
  if (ads.length === 0) {
    extractAdsViaRegex(html, ads);
  }

  // Deduplicate by ID
  const seen = new Set();
  return ads.filter((ad) => {
    if (seen.has(ad.id)) return false;
    seen.add(ad.id);
    return true;
  });
}

/**
 * Recursively search a data tree for ad-like objects.
 */
function findAdNodes(data, results, depth = 0) {
  if (!data || typeof data !== 'object' || depth > 30) return;

  // Check if this looks like an ad record
  if (isAdNode(data)) {
    const normalized = normalizeScrapedAd(data);
    if (normalized) results.push(normalized);
    return;
  }

  // Check for search results arrays
  const edges = data.edges || data.results || data.search_results
    || data.ad_library_search_results || data.data?.ad_library_main?.search_results
    || data.collated_results;  // New Meta Relay format
  if (Array.isArray(edges)) {
    for (const edge of edges) {
      const node = edge.node || edge;
      if (isAdNode(node)) {
        const normalized = normalizeScrapedAd(node);
        if (normalized) results.push(normalized);
      } else {
        findAdNodes(node, results, depth + 1);
      }
    }
    return;
  }

  // Check for search_results_connection in Relay data
  if (data.search_results_connection) {
    findAdNodes(data.search_results_connection, results, depth + 1);
    return;
  }

  // Recurse
  if (Array.isArray(data)) {
    for (const item of data) {
      findAdNodes(item, results, depth + 1);
    }
  } else {
    for (const value of Object.values(data)) {
      if (typeof value === 'object' && value !== null) {
        findAdNodes(value, results, depth + 1);
      }
    }
  }
}

/**
 * Check if a data node looks like an ad record.
 */
function isAdNode(data) {
  if (!data || typeof data !== 'object') return false;

  // Check for new Meta format (primary)
  const hasNewFormat = data.ad_archive_id && data.snapshot?.page_name;

  // Check for old formats (fallback)
  const hasOldFormat = (
    (data.adArchiveID || data.ad_archive_id || data.adid) &&
    (data.pageName || data.page_name || data.collation_id)
  ) || (
    data.ad_delivery_start_time && data.page_name
  ) || (
    data.snapshot && (data.snapshot.page_name || data.snapshot.body)
  );

  return hasNewFormat || hasOldFormat;
}

/**
 * Regex-based ad extraction as fallback when JSON parsing fails.
 */
function extractAdsViaRegex(html, results) {
  // Pattern: Match ad-like JSON objects embedded in the HTML
  const adIdPattern = /"(?:adArchiveID|ad_archive_id|adid)"\s*:\s*"(\d+)"/g;
  const adIds = new Set();

  for (const match of html.matchAll(adIdPattern)) {
    adIds.add(match[1]);
  }

  for (const adId of adIds) {
    // Try to extract surrounding context for each ad ID
    const ad = { id: adId };

    // Page name
    const pageNameRe = new RegExp(`"${adId}"[\\s\\S]{0,500}"page_?[Nn]ame"\\s*:\\s*"([^"]+)"`, 's');
    const pageNameAlt = new RegExp(`"page_?[Nn]ame"\\s*:\\s*"([^"]+)"[\\s\\S]{0,500}"${adId}"`, 's');
    const pm = html.match(pageNameRe) || html.match(pageNameAlt);
    if (pm) ad.pageName = pm[1];

    // Start date
    const startRe = new RegExp(`"${adId}"[\\s\\S]{0,800}"(?:startDate|ad_delivery_start_time)"\\s*:\\s*"?([\\d]+)"?`, 's');
    const sm = html.match(startRe);
    if (sm) ad.startDate = parseInt(sm[1]);

    // Body text
    const bodyRe = new RegExp(`"${adId}"[\\s\\S]{0,1000}"body"\\s*:\\s*\\{[^}]*"text"\\s*:\\s*"([^"]{10,})"`, 's');
    const bm = html.match(bodyRe);
    if (bm) ad.bodyText = unescapeJson(bm[1]);

    if (ad.pageName || ad.bodyText) {
      const normalized = normalizeScrapedAd(ad);
      if (normalized) results.push(normalized);
    }
  }
}

// ─── Normalization ───────────────────────────────────────────

/**
 * Normalize a scraped ad object into our standard internal format.
 */
function normalizeScrapedAd(raw) {
  const id = String(
    raw.adArchiveID || raw.ad_archive_id || raw.adid || raw.id
    || `s_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
  );

  const pageId = String(
    raw.pageID || raw.page_id || raw.collation_id
    || raw.snapshot?.page_id || ''
  );

  const pageName = raw.pageName || raw.page_name
    || raw.snapshot?.page_name || 'Unknown';

  // Date handling — could be epoch seconds, epoch ms, or ISO string
  // New Meta format uses start_date/end_date at top level (epoch seconds)
  const startRaw = raw.start_date || raw.startDate || raw.ad_delivery_start_time
    || raw.snapshot?.ad_delivery_start_time;
  const stopRaw = raw.end_date || raw.endDate || raw.ad_delivery_stop_time
    || raw.snapshot?.ad_delivery_stop_time;

  const launchDate = parseDate(startRaw);
  const stopDate = parseDate(stopRaw);

  // Active status from is_active field (new format) or check if stopDate is null
  const isActive = raw.is_active !== undefined
    ? raw.is_active
    : !stopDate;

  // Text content extraction
  const bodyRaw = raw.body?.markup?.__html || raw.body?.text || raw.body
    || raw.bodyText || raw.ad_creative_bodies?.[0]
    || raw.snapshot?.body?.markup?.__html || raw.snapshot?.body?.text
    || raw.snapshot?.body || '';
  const bodyText = typeof bodyRaw === 'string' ? cleanHtml(bodyRaw) : '';
  const primaryTexts = bodyText ? [bodyText] : [];

  const titleRaw = raw.title || raw.link_title || raw.ad_creative_link_titles?.[0]
    || raw.snapshot?.title || raw.snapshot?.link_title || '';
  const headlines = (typeof titleRaw === 'string' && titleRaw) ? [titleRaw] : [];

  const descRaw = raw.link_description || raw.ad_creative_link_descriptions?.[0]
    || raw.snapshot?.link_description || '';
  const descriptions = (typeof descRaw === 'string' && descRaw) ? [descRaw] : [];

  // Impressions - Meta now hides this data in public search results
  // Try to parse impressions_with_index.impressions_text if available
  const impText = raw.impressions_with_index?.impressions_text;
  let impLower = 0;
  let impUpper = null;

  if (impText) {
    // Parse text like "10K-50K" or "100K-1M"
    const impMatch = impText.match(/(\d+(?:\.\d+)?[KM]?)-(\d+(?:\.\d+)?[KM]?)/);
    if (impMatch) {
      impLower = parseImpressionText(impMatch[1]);
      impUpper = parseImpressionText(impMatch[2]);
    }
  } else {
    // Fallback to old field names (likely won't have data)
    impLower = parseInt(
      raw.impressions_lower_bound || raw.impressions?.lower_bound || 0
    ) || 0;
    const impUpperRaw = raw.impressions_upper_bound || raw.impressions?.upper_bound;
    impUpper = impUpperRaw ? parseInt(impUpperRaw) : null;
  }

  // Spend - also hidden now
  const spendRaw = raw.spend;
  let spendLower = 0;
  let spendUpper = null;

  if (spendRaw && typeof spendRaw === 'object' && spendRaw.lower_bound) {
    spendLower = parseFloat(spendRaw.lower_bound) || 0;
    spendUpper = spendRaw.upper_bound ? parseFloat(spendRaw.upper_bound) : null;
  } else {
    spendLower = parseFloat(
      raw.spend_lower_bound || raw.spend?.lower_bound || 0
    ) || 0;
    const spendUpperRaw = raw.spend_upper_bound || raw.spend?.upper_bound;
    spendUpper = spendUpperRaw ? parseFloat(spendUpperRaw) : null;
  }

  // Snapshot URL
  const snapshotUrl = raw.snapshot_url || raw.ad_snapshot_url
    || `https://www.facebook.com/ads/library/?id=${id}`;

  // Word count
  const maxPrimaryTextWords = primaryTexts.reduce((max, text) => {
    const words = text.trim().split(/\s+/).length;
    return Math.max(max, words);
  }, 0);

  return {
    id,
    pageId,
    pageName,
    snapshotUrl,
    launchDate,
    stopDate,
    isActive,
    impressions: {
      lower: impLower,
      upper: impUpper,
      label: formatImpressionRange(impLower, impUpper),
    },
    spend: {
      lower: spendLower,
      upper: spendUpper,
      currency: raw.currency || 'USD',
    },
    primaryTexts,
    headlines,
    descriptions,
    maxPrimaryTextWords,
    platforms: raw.publisher_platform || raw.publisher_platforms || [],
    languages: raw.languages || [],
    demographics: raw.demographic_distribution || [],
    regions: raw.delivery_by_region || [],
    bylines: raw.bylines || [],
  };
}

function parseDate(raw) {
  if (!raw) return null;
  if (typeof raw === 'string') {
    // ISO string or date string
    return raw.includes('T') ? raw : new Date(raw).toISOString();
  }
  if (typeof raw === 'number') {
    // Epoch — seconds if < 1e12, milliseconds otherwise
    const ms = raw > 1e12 ? raw : raw * 1000;
    return new Date(ms).toISOString();
  }
  return null;
}

/**
 * Strip HTML tags and decode entities.
 */
function cleanHtml(str) {
  return str
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .trim();
}

function unescapeJson(str) {
  try {
    return JSON.parse(`"${str}"`);
  } catch {
    return str.replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
  }
}

/**
 * Parse impression text like "10K" or "1.5M" into a number.
 */
function parseImpressionText(text) {
  if (!text) return 0;
  const match = text.match(/^(\d+(?:\.\d+)?)\s*([KM])?$/i);
  if (!match) return 0;

  const num = parseFloat(match[1]);
  const multiplier = match[2];

  if (multiplier === 'K') return Math.round(num * 1000);
  if (multiplier === 'M') return Math.round(num * 1000000);
  return Math.round(num);
}

/**
 * Format an impression range into a human-readable label.
 */
function formatImpressionRange(lower, upper) {
  const fmt = (n) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
    return String(n);
  };
  if (upper === null || upper === 0) return `${fmt(lower)}+`;
  return `${fmt(lower)}-${fmt(upper)}`;
}

// ─── Main Scan Function ──────────────────────────────────────

/**
 * Scan Meta Ad Library for a keyword by scraping the public page with Playwright.
 *
 * @param {string} keyword - Search term
 * @param {object} opts
 * @param {string} opts.country - ISO country code (default: US)
 * @param {number} opts.maxPages - Max pages to scrape
 * @param {string} opts.activeStatus - ACTIVE, INACTIVE, ALL
 * @returns {{ ads: Array, advertisers: Map, totalFetched: number, pagesScanned: number }}
 */
export async function scanAdLibrary(keyword, opts = {}) {
  const country = opts.country || config.meta.defaultCountry;
  const maxPages = opts.maxPages || config.meta.maxPagesPerScan;
  const activeStatus = opts.activeStatus || 'ALL';

  log.step(`Scraping Meta Ad Library for "${keyword}" (${country}, ${activeStatus})`);

  let browser, page;
  const allAds = [];
  let pageNum = 0;

  try {
    // Step 1: Launch browser
    const browserContext = await launchBrowser();
    browser = browserContext.browser;
    page = browserContext.page;
    log.dim('Browser launched');

    // Step 2: Navigate to search results page
    pageNum++;
    const searchUrl = buildSearchUrl(keyword, { country, activeStatus });
    log.dim(`Navigating to ${searchUrl}`);

    await page.goto(searchUrl, {
      waitUntil: 'domcontentloaded',
      timeout: 60000
    });

    // Wait for ad results to appear
    log.dim('Waiting for ads to load...');
    try {
      await page.waitForSelector('[role="article"]', { timeout: 15000 });
    } catch (err) {
      log.warn('No ad articles found, trying alternative selectors');
    }

    // Give JavaScript time to fully populate the page data
    await page.waitForTimeout(5000);

    // Scroll to trigger lazy loading
    await page.evaluate(() => {
      window.scrollTo(0, document.body.scrollHeight / 2);
    });
    await page.waitForTimeout(2000);

    // Get page HTML
    const html = await page.content();

    // Extract ads from page HTML
    const pageAds = extractAdsFromHtml(html);
    allAds.push(...pageAds);

    log.dim(`Page ${pageNum}: ${pageAds.length} ads (${allAds.length} total)`);

    // For now, we'll just get the first page
    // Additional pagination can be added later if needed
    if (pageAds.length > 0 && pageNum < maxPages) {
      // Try scrolling to load more ads
      for (let scroll = 1; scroll < maxPages && allAds.length < 500; scroll++) {
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
        await page.waitForTimeout(config.meta.requestDelayMs || 2000);

        const newHtml = await page.content();
        const beforeCount = allAds.length;
        const moreAds = extractAdsFromHtml(newHtml);

        // Deduplicate
        const existingIds = new Set(allAds.map(ad => ad.id));
        const newAds = moreAds.filter(ad => !existingIds.has(ad.id));

        if (newAds.length === 0) {
          log.dim('No more ads found after scrolling');
          break;
        }

        allAds.push(...newAds);
        log.dim(`Scroll ${scroll}: +${newAds.length} new ads (${allAds.length} total)`);
      }
    }

    if (allAds.length === 0) {
      log.warn('No ads found. This could mean:');
      log.warn('  1. No ads match this keyword');
      log.warn('  2. Meta is blocking the request (try again later)');
      log.warn('  3. The page format has changed (check for updates)');
    }

  } catch (err) {
    throw new Error(
      `Failed to scrape search results: ${err.message}\n` +
      'Check your internet connection and try again.'
    );
  } finally {
    // Clean up browser
    if (browser) {
      await browser.close();
      log.dim('Browser closed');
    }
  }

  // Aggregate by advertiser
  const advertisers = aggregateByAdvertiser(allAds);

  return {
    keyword,
    country,
    scanDate: new Date().toISOString(),
    ads: allAds,
    advertisers,
    totalFetched: allAds.length,
    pagesScanned: pageNum,
  };
}


// ─── Aggregation ─────────────────────────────────────────────

/**
 * Aggregate ad records by advertiser (page_name).
 * Returns a Map of pageName → { pageId, pageName, adCount, ads, recentAdCount, ... }
 */
function aggregateByAdvertiser(ads) {
  const map = new Map();

  for (const ad of ads) {
    const key = ad.pageName;
    if (!map.has(key)) {
      map.set(key, {
        pageId: ad.pageId,
        pageName: ad.pageName,
        ads: [],
        adCount: 0,
        activeAdCount: 0,
        recentAdCount: 0,
        totalImpressionLower: 0,
        maxImpressionUpper: 0,
        earliestLaunch: null,
        latestLaunch: null,
        headlines: new Set(),
      });
    }

    const entry = map.get(key);
    entry.ads.push(ad);
    entry.adCount++;
    if (ad.isActive) entry.activeAdCount++;

    if (ad.launchDate) {
      const daysSinceLaunch = daysBetween(new Date(ad.launchDate), new Date());
      if (daysSinceLaunch <= 30) entry.recentAdCount++;
      if (!entry.earliestLaunch || ad.launchDate < entry.earliestLaunch) {
        entry.earliestLaunch = ad.launchDate;
      }
      if (!entry.latestLaunch || ad.launchDate > entry.latestLaunch) {
        entry.latestLaunch = ad.launchDate;
      }
    }

    entry.totalImpressionLower += ad.impressions.lower;
    if (ad.impressions.upper !== null) {
      entry.maxImpressionUpper = Math.max(entry.maxImpressionUpper, ad.impressions.upper);
    }

    for (const h of ad.headlines) {
      if (h.trim()) entry.headlines.add(h.trim());
    }
  }

  return map;
}

/**
 * Calculate days between two dates.
 */
function daysBetween(d1, d2) {
  const ms = Math.abs(d2.getTime() - d1.getTime());
  return Math.floor(ms / (1000 * 60 * 60 * 24));
}

/**
 * Sort advertisers by recent activity + impression volume.
 * Returns array sorted by composite score (higher = more relevant).
 */
export function rankAdvertisers(advertisersMap) {
  const entries = Array.from(advertisersMap.values());

  for (const entry of entries) {
    const recentRatio = entry.adCount > 0 ? entry.recentAdCount / entry.adCount : 0;
    const recentScore = (recentRatio * 50) + Math.min(entry.recentAdCount * 5, 50);

    const impressionScore = entry.totalImpressionLower > 0
      ? Math.min(Math.log10(entry.totalImpressionLower) * 15, 100)
      : 0;

    const activeBonus = Math.min(entry.activeAdCount * 3, 30);

    entry.relevanceScore = Math.round(recentScore + impressionScore + activeBonus);
  }

  return entries.sort((a, b) => b.relevanceScore - a.relevanceScore);
}

export { daysBetween, formatImpressionRange, normalizeScrapedAd as normalizeAdRecord };
