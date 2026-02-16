import axios from 'axios';
import { config } from '../utils/config.js';
import { log } from '../utils/logger.js';

/**
 * Meta Ad Library web scraper — direct page scraping, no API token required.
 *
 * Fetches ad data by scraping the public Meta Ad Library search page.
 * Extracts ad metadata from embedded JSON data in the page's HTML.
 *
 * Public URL: https://www.facebook.com/ads/library/
 */

const AD_LIBRARY_BASE = 'https://www.facebook.com/ads/library/';
const GRAPHQL_ENDPOINT = 'https://www.facebook.com/api/graphql/';

const BROWSER_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
  'Accept-Language': 'en-US,en;q=0.9',
  'Cache-Control': 'no-cache',
  'Sec-Fetch-Dest': 'document',
  'Sec-Fetch-Mode': 'navigate',
  'Sec-Fetch-Site': 'none',
  'Sec-Fetch-User': '?1',
  'Upgrade-Insecure-Requests': '1',
};

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

// ─── Session Management ──────────────────────────────────────

/**
 * Establish a session with the Ad Library page.
 * Fetches the main page to get cookies and CSRF tokens.
 */
async function createSession() {
  const response = await axios.get(AD_LIBRARY_BASE, {
    headers: BROWSER_HEADERS,
    maxRedirects: 5,
    timeout: 20000,
    // Capture cookies from response
    transformResponse: [(data) => data],
  });

  const html = response.data;
  const setCookies = response.headers['set-cookie'] || [];
  const cookieStr = setCookies.map((c) => c.split(';')[0]).join('; ');

  // Extract CSRF token (fb_dtsg)
  const dtsgMatch = html.match(/"DTSGInitialData"[^}]*"token":"([^"]+)"/)
    || html.match(/name="fb_dtsg" value="([^"]+)"/)
    || html.match(/"dtsg":\{"token":"([^"]+)"/);
  const fbDtsg = dtsgMatch ? dtsgMatch[1] : null;

  // Extract LSD token
  const lsdMatch = html.match(/name="lsd" value="([^"]+)"/)
    || html.match(/"LSD"[^}]*\[.*?"([^"]+)"\]/);
  const lsd = lsdMatch ? lsdMatch[1] : null;

  // Extract jazoest
  const jazoestMatch = html.match(/name="jazoest" value="([^"]+)"/);
  const jazoest = jazoestMatch ? jazoestMatch[1] : null;

  return { cookies: cookieStr, fbDtsg, lsd, jazoest, html };
}

// ─── Data Extraction ─────────────────────────────────────────

/**
 * Extract ad data from an Ad Library search page HTML response.
 * Tries multiple parsing strategies for resilience.
 */
function extractAdsFromHtml(html) {
  const ads = [];

  // Strategy 1: Extract from <script data-sjs> JSON blocks
  const sjsMatches = html.matchAll(/<script[^>]*data-sjs[^>]*>([\s\S]*?)<\/script>/gi);
  for (const match of sjsMatches) {
    try {
      const data = JSON.parse(match[1]);
      findAdNodes(data, ads);
    } catch {
      // Not valid JSON, skip
    }
  }

  // Strategy 2: Extract from generic <script type="application/json"> blocks
  const jsonScripts = html.matchAll(/<script type="application\/json"[^>]*>([\s\S]*?)<\/script>/gi);
  for (const match of jsonScripts) {
    try {
      const data = JSON.parse(match[1]);
      findAdNodes(data, ads);
    } catch {
      // Skip invalid
    }
  }

  // Strategy 3: Extract from require("ServerJS") handler blocks
  const serverJsMatches = html.matchAll(/\{(?:"require"|require)\s*:\s*(\[[\s\S]*?\])\s*\}/g);
  for (const match of serverJsMatches) {
    try {
      const data = JSON.parse(`{"require":${match[1]}}`);
      findAdNodes(data, ads);
    } catch {
      // Skip
    }
  }

  // Strategy 4: Direct regex extraction as fallback
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
  if (!data || typeof data !== 'object' || depth > 15) return;

  // Check if this looks like an ad record
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
  // Must have some combination of ad-identifying fields
  return (
    (data.adArchiveID || data.ad_archive_id || data.adid) &&
    (data.pageName || data.page_name || data.snapshot?.page_name || data.collation_id)
  ) || (
    data.ad_delivery_start_time && data.page_name
  ) || (
    data.snapshot && (data.snapshot.page_name || data.snapshot.body)
  );
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
 * Scan Meta Ad Library for a keyword by scraping the public page.
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

  // Step 1: Establish session
  let session;
  try {
    session = await createSession();
    log.dim('Session established');
  } catch (err) {
    throw new Error(
      `Failed to connect to Meta Ad Library: ${err.message}\n` +
      'Check your internet connection and try again.'
    );
  }

  const allAds = [];
  let pageNum = 0;
  let forwardCursor = null;

  // Step 2: Fetch initial search results page
  pageNum++;
  try {
    const searchUrl = buildSearchUrl(keyword, { country, activeStatus });
    const response = await axios.get(searchUrl, {
      headers: {
        ...BROWSER_HEADERS,
        'Cookie': session.cookies,
        'Referer': AD_LIBRARY_BASE,
      },
      maxRedirects: 5,
      timeout: 30000,
      transformResponse: [(data) => data],
    });

    const html = response.data;

    // Update cookies from response
    const newCookies = response.headers['set-cookie'] || [];
    if (newCookies.length > 0) {
      const extraCookies = newCookies.map((c) => c.split(';')[0]).join('; ');
      session.cookies = session.cookies
        ? `${session.cookies}; ${extraCookies}`
        : extraCookies;
    }

    // Extract ads from page HTML
    const pageAds = extractAdsFromHtml(html);
    allAds.push(...pageAds);

    // Try to extract pagination cursor
    forwardCursor = extractForwardCursor(html);

    log.dim(`Page ${pageNum}: ${pageAds.length} ads (${allAds.length} total)`);
  } catch (err) {
    throw new Error(
      `Failed to scrape search results: ${err.message}\n` +
      'Meta may be blocking automated requests. Try again later.'
    );
  }

  // Step 3: Fetch additional pages via GraphQL endpoint
  while (forwardCursor && pageNum < maxPages && allAds.length < 500) {
    pageNum++;
    await sleep(config.meta.requestDelayMs);

    try {
      const pageAds = await fetchNextPage(
        keyword, country, activeStatus, forwardCursor, session
      );

      if (pageAds.ads.length === 0) {
        log.dim(`Page ${pageNum}: no more results`);
        break;
      }

      allAds.push(...pageAds.ads);
      forwardCursor = pageAds.cursor;

      log.dim(`Page ${pageNum}: ${pageAds.ads.length} ads (${allAds.length} total)`);
    } catch (err) {
      log.warn(`Page ${pageNum} failed: ${err.message}. Continuing with results so far.`);
      break;
    }
  }

  if (allAds.length === 0) {
    log.warn('No ads found. This could mean:');
    log.warn('  1. No ads match this keyword');
    log.warn('  2. Meta is blocking the request (try again later)');
    log.warn('  3. The page format has changed (check for updates)');
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

/**
 * Fetch the next page of results via GraphQL.
 */
async function fetchNextPage(keyword, country, activeStatus, cursor, session) {
  const variables = JSON.stringify({
    activeStatus: activeStatus.toUpperCase(),
    adType: 'ALL',
    bylines: [],
    collationToken: null,
    contentLanguages: [],
    countries: [country],
    excludedIDs: [],
    first: 30,
    location: null,
    mediaType: 'ALL',
    potentialReachInput: [],
    publisherPlatforms: [],
    queryString: keyword,
    regions: [],
    searchType: 'KEYWORD_UNORDERED',
    source: null,
    startDate: null,
    endDate: null,
    v: 'default',
    after: cursor,
  });

  const params = new URLSearchParams();
  params.append('variables', variables);
  if (session.fbDtsg) params.append('fb_dtsg', session.fbDtsg);
  if (session.lsd) params.append('lsd', session.lsd);
  // The doc_id for Ad Library search — this may need updating over time
  params.append('doc_id', '7826966037373498');

  const response = await axios.post(GRAPHQL_ENDPOINT, params.toString(), {
    headers: {
      ...BROWSER_HEADERS,
      'Content-Type': 'application/x-www-form-urlencoded',
      'Cookie': session.cookies,
      'Referer': buildSearchUrl(keyword, { country }),
      'X-FB-Friendly-Name': 'AdLibrarySearchPaginationQuery',
    },
    timeout: 20000,
    transformResponse: [(data) => data],
  });

  let json;
  try {
    // Response may be prefixed with "for (;;);" anti-hijack
    const text = response.data.replace(/^for\s*\(;;\)\s*;\s*/, '');
    json = JSON.parse(text);
  } catch {
    return { ads: [], cursor: null };
  }

  const ads = [];
  findAdNodes(json, ads);

  // Extract next cursor
  const pageInfo = findPageInfo(json);
  const nextCursor = pageInfo?.has_next_page ? pageInfo.end_cursor : null;

  return { ads, cursor: nextCursor };
}

/**
 * Extract forward pagination cursor from HTML.
 */
function extractForwardCursor(html) {
  // Look for cursor/after values in the embedded data
  const cursorPatterns = [
    /"forward_cursor"\s*:\s*"([^"]+)"/,
    /"end_cursor"\s*:\s*"([^"]+)"/,
    /"after"\s*:\s*"([^"]+)"/,
    /"cursor"\s*:\s*"([^"]+)"/,
  ];
  for (const pattern of cursorPatterns) {
    const match = html.match(pattern);
    if (match) return match[1];
  }
  return null;
}

/**
 * Find page info in a response data tree.
 */
function findPageInfo(data, depth = 0) {
  if (!data || typeof data !== 'object' || depth > 10) return null;
  if (data.page_info?.has_next_page !== undefined) return data.page_info;
  if (data.pageInfo?.hasNextPage !== undefined) {
    return {
      has_next_page: data.pageInfo.hasNextPage,
      end_cursor: data.pageInfo.endCursor,
    };
  }

  if (Array.isArray(data)) {
    for (const item of data) {
      const found = findPageInfo(item, depth + 1);
      if (found) return found;
    }
  } else {
    for (const value of Object.values(data)) {
      if (typeof value === 'object' && value !== null) {
        const found = findPageInfo(value, depth + 1);
        if (found) return found;
      }
    }
  }
  return null;
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
