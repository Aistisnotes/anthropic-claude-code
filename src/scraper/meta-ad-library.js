import { chromium } from 'playwright';
import { config } from '../utils/config.js';
import { log } from '../utils/logger.js';

/**
 * Meta Ad Library scraper — Playwright headless Chromium.
 *
 * Uses a real browser to bypass Meta's anti-bot protections that block
 * raw HTTP requests. Extracts ad data via two strategies:
 *   1. Network interception of GraphQL API responses (structured JSON)
 *   2. DOM extraction from rendered ad cards (fallback)
 *
 * Public URL: https://www.facebook.com/ads/library/
 */

const AD_LIBRARY_BASE = 'https://www.facebook.com/ads/library/';

// Stealth browser args to reduce automation detection
const BROWSER_ARGS = [
  '--disable-blink-features=AutomationControlled',
  '--no-sandbox',
  '--disable-setuid-sandbox',
  '--disable-dev-shm-usage',
  '--disable-accelerated-2d-canvas',
  '--no-first-run',
  '--no-zygote',
  '--disable-gpu',
];

const VIEWPORT = { width: 1440, height: 900 };

const USER_AGENT =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

/**
 * Sleep helper for rate limiting.
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ─── Browser Management ─────────────────────────────────────

/**
 * Launch headless Chromium with stealth settings.
 */
async function launchBrowser() {
  const browser = await chromium.launch({
    headless: true,
    args: BROWSER_ARGS,
  });

  const context = await browser.newContext({
    viewport: VIEWPORT,
    userAgent: USER_AGENT,
    locale: 'en-US',
    timezoneId: 'America/New_York',
    // Bypass CSP to allow our scripts
    bypassCSP: true,
  });

  // Mask automation indicators
  await context.addInitScript(() => {
    // Hide webdriver flag
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    // Mock chrome runtime
    window.chrome = { runtime: {} };
    // Mock permissions
    const originalQuery = window.navigator.permissions?.query;
    if (originalQuery) {
      window.navigator.permissions.query = (params) =>
        params.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission })
          : originalQuery(params);
    }
    // Mock plugins
    Object.defineProperty(navigator, 'plugins', {
      get: () => [1, 2, 3, 4, 5],
    });
    // Mock languages
    Object.defineProperty(navigator, 'languages', {
      get: () => ['en-US', 'en'],
    });
  });

  return { browser, context };
}

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

// ─── Network Interception ───────────────────────────────────

/**
 * Set up response interception to capture GraphQL ad data.
 * Returns a reference to the captured ads array.
 */
function setupNetworkCapture(page) {
  const captured = [];

  page.on('response', async (response) => {
    const url = response.url();

    // Capture GraphQL responses that contain ad data
    const isGraphQL = url.includes('/api/graphql/');
    const isAsyncSearch = url.includes('ads/library/async');
    const isAdSearch = url.includes('ad_library');

    if (!isGraphQL && !isAsyncSearch && !isAdSearch) return;

    try {
      const text = await response.text();
      // Meta prefixes GraphQL responses with "for (;;);" as XSS protection
      const cleaned = text.replace(/^for\s*\(;;\)\s*;\s*/, '');

      // Handle multi-line JSON responses (each line is a separate JSON object)
      const lines = cleaned.split('\n').filter((l) => l.trim());
      for (const line of lines) {
        try {
          const json = JSON.parse(line);
          findAdNodes(json, captured);
        } catch {
          // Not valid JSON line, skip
        }
      }
    } catch {
      // Response may not be text (images, etc.)
    }
  });

  return captured;
}

// ─── DOM Extraction ─────────────────────────────────────────

/**
 * Extract ad data directly from the rendered DOM.
 * Fallback when network interception doesn't capture enough data.
 */
async function extractAdsFromDOM(page) {
  return page.evaluate(() => {
    const ads = [];

    // Meta Ad Library renders ad cards in a scrollable container.
    // Each card has a consistent structure with:
    //   - Page name link
    //   - "Started running on" date
    //   - Body text
    //   - Platform icons
    //   - "See ad details" link

    // Strategy 1: Find ad containers by their structural pattern
    // Meta uses data attributes and aria labels on ad cards
    const adContainers = document.querySelectorAll(
      // Multiple selector strategies for resilience
      [
        '[class*="AdLibrarySearchResult"]',
        '[class*="adLibrarySearchResult"]',
        '[data-testid*="ad_library"]',
        '[role="article"]',
        // Generic: divs that contain "Started running on" text
      ].join(', ')
    );

    for (const container of adContainers) {
      const ad = extractAdFromContainer(container);
      if (ad && (ad.pageName || ad.bodyText)) {
        ads.push(ad);
      }
    }

    // Strategy 2: If no containers found via selectors, search by text patterns
    if (ads.length === 0) {
      // Find all elements containing "Started running on"
      const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
        {
          acceptNode: (node) =>
            node.textContent.includes('Started running on')
              ? NodeFilter.FILTER_ACCEPT
              : NodeFilter.FILTER_REJECT,
        }
      );

      const dateNodes = [];
      while (walker.nextNode()) {
        dateNodes.push(walker.currentNode);
      }

      for (const dateNode of dateNodes) {
        // Walk up to find the ad card container
        let cardEl = dateNode.parentElement;
        for (let i = 0; i < 10 && cardEl; i++) {
          // Ad cards are typically larger containers
          if (cardEl.offsetHeight > 200 || cardEl.querySelector('a[href*="ads/library"]')) {
            break;
          }
          cardEl = cardEl.parentElement;
        }
        if (cardEl) {
          const ad = extractAdFromContainer(cardEl);
          if (ad && (ad.pageName || ad.bodyText)) {
            ads.push(ad);
          }
        }
      }
    }

    // Strategy 3: Extract from embedded JSON in script tags
    const scripts = document.querySelectorAll('script[type="application/json"], script[data-sjs]');
    for (const script of scripts) {
      try {
        const data = JSON.parse(script.textContent);
        // Look for ad-like structures in the JSON
        findAdsInJson(data, ads, 0);
      } catch {
        // Not valid JSON
      }
    }

    return ads;

    // ── Helper functions (run in browser context) ──

    function extractAdFromContainer(el) {
      const ad = {};

      // Page name: usually the first prominent link
      const pageLink = el.querySelector('a[href*="/ads/library/"]') ||
        el.querySelector('a[href*="facebook.com/"]') ||
        el.querySelector('h4, h3, [class*="name"], [class*="Name"]');
      if (pageLink) {
        ad.pageName = pageLink.textContent?.trim();
      }

      // Date: "Started running on Mon DD, YYYY" or similar
      const textContent = el.textContent || '';
      const dateMatch = textContent.match(
        /Started running on\s+(\w+\s+\d{1,2},?\s+\d{4})/
      );
      if (dateMatch) {
        try {
          ad.startDate = new Date(dateMatch[1]).toISOString();
        } catch { /* ignore */ }
      }

      // Body text: longest text block in the container
      const textBlocks = [];
      el.querySelectorAll('div, span, p').forEach((node) => {
        const text = node.textContent?.trim();
        if (text && text.length > 30 && !text.includes('Started running on')) {
          textBlocks.push(text);
        }
      });
      // Pick the longest as the body text
      if (textBlocks.length > 0) {
        textBlocks.sort((a, b) => b.length - a.length);
        ad.bodyText = textBlocks[0];
      }

      // Snapshot URL: "See ad details" link
      const detailLink = el.querySelector('a[href*="ads/library/?id="]');
      if (detailLink) {
        ad.snapshot_url = detailLink.href;
        // Extract ad ID from URL
        const idMatch = detailLink.href.match(/[?&]id=(\d+)/);
        if (idMatch) ad.id = idMatch[1];
      }

      // Impressions text: look for impression range patterns
      const impMatch = textContent.match(
        /(\d[\d,]*[KkMm]?)\s*[-–]\s*(\d[\d,]*[KkMm]?)\s*impression/i
      );
      if (impMatch) {
        ad.impressions_lower_bound = parseImpNumber(impMatch[1]);
        ad.impressions_upper_bound = parseImpNumber(impMatch[2]);
      }

      // Platforms
      const platforms = [];
      if (textContent.includes('Facebook')) platforms.push('facebook');
      if (textContent.includes('Instagram')) platforms.push('instagram');
      if (textContent.includes('Messenger')) platforms.push('messenger');
      if (textContent.includes('Audience Network')) platforms.push('audience_network');
      if (platforms.length > 0) ad.publisher_platforms = platforms;

      return Object.keys(ad).length > 0 ? ad : null;
    }

    function parseImpNumber(str) {
      const cleaned = str.replace(/,/g, '');
      const num = parseFloat(cleaned);
      if (/[Kk]/.test(str)) return num * 1000;
      if (/[Mm]/.test(str)) return num * 1000000;
      return num;
    }

    function findAdsInJson(data, results, depth) {
      if (!data || typeof data !== 'object' || depth > 12) return;
      if (
        (data.adArchiveID || data.ad_archive_id) &&
        (data.pageName || data.page_name || data.snapshot?.page_name)
      ) {
        results.push(data);
        return;
      }
      const arr = Array.isArray(data) ? data : Object.values(data);
      for (const val of arr) {
        if (typeof val === 'object' && val !== null) {
          findAdsInJson(val, results, depth + 1);
        }
      }
    }
  });
}

// ─── Pagination via Scrolling ───────────────────────────────

/**
 * Scroll the page to trigger infinite scroll loading.
 * Returns true if new content appeared, false if we've reached the end.
 */
async function scrollForMore(page) {
  const previousHeight = await page.evaluate(() => document.body.scrollHeight);

  await page.evaluate(() => {
    window.scrollTo(0, document.body.scrollHeight);
  });

  // Wait for new content to load
  try {
    await page.waitForFunction(
      (prevHeight) => document.body.scrollHeight > prevHeight,
      previousHeight,
      { timeout: 5000 }
    );
    // Small extra wait for rendering
    await sleep(500);
    return true;
  } catch {
    return false;
  }
}

/**
 * Dismiss cookie consent banner or login wall if present.
 */
async function dismissOverlays(page) {
  // Cookie consent buttons
  const consentSelectors = [
    'button[data-cookiebanner="accept_button"]',
    'button[title="Allow all cookies"]',
    'button[title="Accept All"]',
    '[data-testid="cookie-policy-manage-dialog-accept-button"]',
    'button:has-text("Allow essential and optional cookies")',
    'button:has-text("Accept All")',
    'button:has-text("Allow all")',
  ];

  for (const selector of consentSelectors) {
    try {
      const btn = page.locator(selector).first();
      if (await btn.isVisible({ timeout: 1000 })) {
        await btn.click();
        await sleep(500);
        return;
      }
    } catch {
      // Selector not found, try next
    }
  }

  // Close any modal dialogs
  try {
    const closeBtn = page.locator('[aria-label="Close"], [role="dialog"] button').first();
    if (await closeBtn.isVisible({ timeout: 500 })) {
      await closeBtn.click();
      await sleep(300);
    }
  } catch {
    // No modal
  }
}

// ─── Data Extraction from Network Responses ─────────────────

/**
 * Recursively search a data tree for ad-like objects.
 */
function findAdNodes(data, results, depth = 0) {
  if (!data || typeof data !== 'object' || depth > 15) return;

  if (isAdNode(data)) {
    const normalized = normalizeScrapedAd(data);
    if (normalized) results.push(normalized);
    return;
  }

  // Check for search results arrays
  const edges = data.edges || data.results || data.search_results
    || data.ad_library_search_results || data.data?.ad_library_main?.search_results;
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
  return (
    (data.adArchiveID || data.ad_archive_id || data.adid) &&
    (data.pageName || data.page_name || data.snapshot?.page_name || data.collation_id)
  ) || (
    data.ad_delivery_start_time && data.page_name
  ) || (
    data.snapshot && (data.snapshot.page_name || data.snapshot.body)
  );
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
  const startRaw = raw.startDate || raw.start_date || raw.ad_delivery_start_time
    || raw.snapshot?.ad_delivery_start_time;
  const stopRaw = raw.endDate || raw.end_date || raw.ad_delivery_stop_time
    || raw.snapshot?.ad_delivery_stop_time;

  const launchDate = parseDate(startRaw);
  const stopDate = parseDate(stopRaw);

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

  // Impressions
  const impLower = parseInt(
    raw.impressions_lower_bound || raw.impressions?.lower_bound || 0
  ) || 0;
  const impUpperRaw = raw.impressions_upper_bound || raw.impressions?.upper_bound;
  const impUpper = impUpperRaw ? parseInt(impUpperRaw) : null;

  // Spend
  const spendLower = parseFloat(
    raw.spend_lower_bound || raw.spend?.lower_bound || 0
  ) || 0;
  const spendUpperRaw = raw.spend_upper_bound || raw.spend?.upper_bound;
  const spendUpper = spendUpperRaw ? parseFloat(spendUpperRaw) : null;

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
    isActive: !stopDate,
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
    platforms: raw.publisher_platforms || [],
    languages: raw.languages || [],
    demographics: raw.demographic_distribution || [],
    regions: raw.delivery_by_region || [],
    bylines: raw.bylines || [],
  };
}

function parseDate(raw) {
  if (!raw) return null;
  if (typeof raw === 'string') {
    return raw.includes('T') ? raw : new Date(raw).toISOString();
  }
  if (typeof raw === 'number') {
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

/**
 * Format an impression range into a human-readable label.
 */
function formatImpressionRange(lower, upper) {
  const fmt = (n) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
    return String(n);
  };
  if (upper === null) return `${fmt(lower)}+`;
  return `${fmt(lower)}-${fmt(upper)}`;
}

// ─── Main Scan Function ──────────────────────────────────────

/**
 * Scan Meta Ad Library for a keyword using Playwright headless Chromium.
 *
 * Launches a real browser to bypass Meta's anti-bot protections.
 * Extracts ads via network interception (GraphQL responses) and DOM scraping.
 *
 * @param {string} keyword - Search term
 * @param {object} opts
 * @param {string} opts.country - ISO country code (default: US)
 * @param {number} opts.maxPages - Max scroll iterations for pagination
 * @param {string} opts.activeStatus - ACTIVE, INACTIVE, ALL
 * @returns {{ ads: Array, advertisers: Map, totalFetched: number, pagesScanned: number }}
 */
export async function scanAdLibrary(keyword, opts = {}) {
  const country = opts.country || config.meta.defaultCountry;
  const maxPages = opts.maxPages || config.meta.maxPagesPerScan;
  const activeStatus = opts.activeStatus || 'ALL';

  log.step(`Scraping Meta Ad Library for "${keyword}" (${country}, ${activeStatus})`);

  // Step 1: Launch browser
  let browser, context;
  try {
    ({ browser, context } = await launchBrowser());
    log.dim('Browser launched');
  } catch (err) {
    throw new Error(
      `Failed to launch browser: ${err.message}\n` +
      'Ensure Playwright browsers are installed: npx playwright install chromium'
    );
  }

  const allAds = [];
  let pagesScrolled = 0;

  try {
    const page = await context.newPage();

    // Set up network interception to capture GraphQL ad data
    const networkAds = setupNetworkCapture(page);

    // Step 2: Navigate to search page
    const searchUrl = buildSearchUrl(keyword, { country, activeStatus });
    log.dim(`Navigating to: ${searchUrl}`);

    await page.goto(searchUrl, {
      waitUntil: 'domcontentloaded',
      timeout: config.meta.pageTimeoutMs,
    });

    // Dismiss cookie consent / login overlays
    await dismissOverlays(page);

    // Wait for results to render (the page dynamically loads ad cards)
    try {
      await page.waitForSelector(
        '[role="article"], [class*="result"], [class*="AdCard"], [class*="adCard"]',
        { timeout: 15000 }
      );
    } catch {
      // Results may load with different selectors — wait for network idle instead
      await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    }

    // Give initial batch time to fully render + fire API calls
    await sleep(2000);

    log.dim(`Page 1: ${networkAds.length} ads captured from network`);
    pagesScrolled = 1;

    // Step 3: Scroll for more pages
    let consecutiveEmptyScrolls = 0;
    const maxEmptyScrolls = 3;

    while (pagesScrolled < maxPages && consecutiveEmptyScrolls < maxEmptyScrolls) {
      const adsBefore = networkAds.length;

      const hasMore = await scrollForMore(page);
      pagesScrolled++;

      await sleep(config.meta.requestDelayMs);

      const newAds = networkAds.length - adsBefore;
      log.dim(`Scroll ${pagesScrolled}: +${newAds} ads (${networkAds.length} total from network)`);

      if (newAds === 0 && !hasMore) {
        consecutiveEmptyScrolls++;
      } else {
        consecutiveEmptyScrolls = 0;
      }
    }

    // Step 4: Merge network-captured ads
    const seenIds = new Set();
    for (const ad of networkAds) {
      if (!seenIds.has(ad.id)) {
        seenIds.add(ad.id);
        allAds.push(ad);
      }
    }

    // Step 5: DOM fallback — extract any ads the network interception missed
    log.dim('Extracting additional ads from DOM...');
    const domRawAds = await extractAdsFromDOM(page);

    for (const rawAd of domRawAds) {
      const normalized = normalizeScrapedAd(rawAd);
      if (normalized && !seenIds.has(normalized.id)) {
        seenIds.add(normalized.id);
        allAds.push(normalized);
      }
    }

    log.dim(`Total: ${allAds.length} ads (${networkAds.length} network + ${domRawAds.length} DOM)`);

  } finally {
    // Always close the browser
    await browser.close().catch(() => {});
  }

  if (allAds.length === 0) {
    log.warn('No ads found. This could mean:');
    log.warn('  1. No ads match this keyword');
    log.warn('  2. Meta is blocking automated browsers (try later)');
    log.warn('  3. The page structure has changed');
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
    pagesScanned: pagesScrolled,
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
