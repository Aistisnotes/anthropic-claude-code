import axios from 'axios';
import { config } from '../utils/config.js';
import { log } from '../utils/logger.js';

/**
 * Meta Ad Library API client — metadata-only scanning.
 *
 * Fetches ad metadata (advertiser, headlines, launch dates, impression ranges)
 * WITHOUT downloading ad creatives. This is the surgical first pass that lets us
 * decide which ads are worth pulling down for deep analysis.
 *
 * API docs: https://developers.facebook.com/docs/marketing-api/reference/ads_archive/
 */

const FIELDS = [
  'id',
  'ad_creation_time',
  'ad_delivery_start_time',
  'ad_delivery_stop_time',
  'page_id',
  'page_name',
  'ad_snapshot_url',
  'ad_creative_bodies',       // Primary text array
  'ad_creative_link_titles',  // Headlines array
  'ad_creative_link_captions',
  'ad_creative_link_descriptions',
  'bylines',
  'impressions',              // { lower_bound, upper_bound }
  'spend',                    // { lower_bound, upper_bound }
  'currency',
  'languages',
  'publisher_platforms',
  'estimated_audience_size',
  'demographic_distribution',
  'delivery_by_region',
].join(',');

/**
 * Normalize a single raw API ad record into our internal format.
 */
function normalizeAdRecord(raw) {
  const launchDate = raw.ad_delivery_start_time || raw.ad_creation_time || null;
  const impressionsLower = raw.impressions?.lower_bound
    ? parseInt(raw.impressions.lower_bound, 10) : 0;
  const impressionsUpper = raw.impressions?.upper_bound
    ? parseInt(raw.impressions.upper_bound, 10) : null;
  const spendLower = raw.spend?.lower_bound
    ? parseFloat(raw.spend.lower_bound) : 0;
  const spendUpper = raw.spend?.upper_bound
    ? parseFloat(raw.spend.upper_bound) : null;

  const primaryTexts = raw.ad_creative_bodies || [];
  const headlines = raw.ad_creative_link_titles || [];
  const descriptions = raw.ad_creative_link_descriptions || [];

  // Calculate word count of the longest primary text
  const maxPrimaryTextWords = primaryTexts.reduce((max, text) => {
    const words = text.trim().split(/\s+/).length;
    return Math.max(max, words);
  }, 0);

  return {
    id: raw.id,
    pageId: raw.page_id,
    pageName: raw.page_name || 'Unknown',
    snapshotUrl: raw.ad_snapshot_url || null,
    launchDate,
    stopDate: raw.ad_delivery_stop_time || null,
    isActive: !raw.ad_delivery_stop_time,
    impressions: {
      lower: impressionsLower,
      upper: impressionsUpper,
      label: formatImpressionRange(impressionsLower, impressionsUpper),
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
    _raw: raw,
  };
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

/**
 * Sleep helper for rate limiting.
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Scan Meta Ad Library for a keyword. Returns ALL metadata records
 * (paginated, up to maxPages). No ad creatives are downloaded.
 *
 * @param {string} keyword - Search term
 * @param {object} opts
 * @param {string} opts.country - ISO country code (default: US)
 * @param {string} opts.adType - ALL, POLITICAL_AND_ISSUE_ADS, etc.
 * @param {number} opts.maxPages - Max API pages to fetch
 * @param {string} opts.activeStatus - ACTIVE, INACTIVE, ALL
 * @returns {{ ads: Array, advertisers: Map, totalFetched: number, pagesScanned: number }}
 */
export async function scanAdLibrary(keyword, opts = {}) {
  const token = config.meta.accessToken;
  if (!token) {
    throw new Error(
      'META_ACCESS_TOKEN not set. Get a token at:\n' +
      'https://developers.facebook.com/tools/explorer/\n' +
      'Required permission: ads_read\n' +
      'Set it: export META_ACCESS_TOKEN=your_token'
    );
  }

  const country = opts.country || config.meta.defaultCountry;
  const adType = opts.adType || config.meta.defaultAdType;
  const maxPages = opts.maxPages || config.meta.maxPagesPerScan;
  const activeStatus = opts.activeStatus || 'ALL';

  const allAds = [];
  let nextUrl = null;
  let pageNum = 0;

  log.step(`Scanning Meta Ad Library for "${keyword}" (${country}, ${activeStatus})`);

  while (pageNum < maxPages) {
    pageNum++;
    let response;

    try {
      if (nextUrl) {
        response = await axios.get(nextUrl);
      } else {
        response = await axios.get(`${config.meta.apiBase}${config.meta.adLibraryEndpoint}`, {
          params: {
            access_token: token,
            search_terms: keyword,
            ad_reached_countries: JSON.stringify([country]),
            ad_type: adType,
            ad_active_status: activeStatus,
            fields: FIELDS,
            limit: config.meta.resultsPerPage,
            search_page_ids: opts.pageIds || undefined,
          },
        });
      }
    } catch (err) {
      if (err.response?.status === 429) {
        log.warn(`Rate limited on page ${pageNum}. Waiting 10s...`);
        await sleep(10000);
        pageNum--; // Retry this page
        continue;
      }
      if (err.response?.status === 400) {
        const fbError = err.response?.data?.error;
        throw new Error(
          `Meta API error: ${fbError?.message || err.message}\n` +
          `Code: ${fbError?.code || 'unknown'}, Type: ${fbError?.type || 'unknown'}`
        );
      }
      throw err;
    }

    const data = response.data?.data || [];
    if (data.length === 0) {
      log.dim(`Page ${pageNum}: no more results`);
      break;
    }

    const normalized = data.map(normalizeAdRecord);
    allAds.push(...normalized);

    log.dim(`Page ${pageNum}: ${data.length} ads (${allAds.length} total)`);

    // Check for next page
    nextUrl = response.data?.paging?.next || null;
    if (!nextUrl) break;

    // Rate limiting delay
    await sleep(config.meta.requestDelayMs);
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
        recentAdCount: 0,       // Ads launched in last 30 days
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

    // Track recent activity
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

    // Aggregate impressions
    entry.totalImpressionLower += ad.impressions.lower;
    if (ad.impressions.upper !== null) {
      entry.maxImpressionUpper = Math.max(entry.maxImpressionUpper, ad.impressions.upper);
    }

    // Collect unique headlines
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

  // Score: weighted combination of recent activity and impressions
  for (const entry of entries) {
    // Recent activity score (0-100): ratio of recent ads * active ad count
    const recentRatio = entry.adCount > 0 ? entry.recentAdCount / entry.adCount : 0;
    const recentScore = (recentRatio * 50) + Math.min(entry.recentAdCount * 5, 50);

    // Impression score (0-100): log-scaled total impressions
    const impressionScore = entry.totalImpressionLower > 0
      ? Math.min(Math.log10(entry.totalImpressionLower) * 15, 100)
      : 0;

    // Active ad bonus
    const activeBonus = Math.min(entry.activeAdCount * 3, 30);

    entry.relevanceScore = Math.round(recentScore + impressionScore + activeBonus);
  }

  return entries.sort((a, b) => b.relevanceScore - a.relevanceScore);
}

export { daysBetween, formatImpressionRange, normalizeAdRecord };
