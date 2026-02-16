import { config } from '../utils/config.js';
import { log } from '../utils/logger.js';

/**
 * Smart ad selection engine.
 *
 * Assigns each ad a priority level (1-4) or marks it for skip based on:
 *   - Launch recency (days since ad_delivery_start_time)
 *   - Impression volume (lower bound from Meta's range)
 *   - Primary text word count (skip thin ads)
 *   - Duplicate detection (keep highest impression version)
 *
 * Priority 1: ACTIVE WINNERS      — <14 days + high impressions
 * Priority 2: PROVEN RECENT       — <30 days + moderate-high impressions
 * Priority 3: STRATEGIC DIRECTION  — <7 days (any impressions)
 * Priority 4: RECENT MODERATE     — <60 days + high impressions
 * SKIP: Legacy, failed tests, duplicates, thin text
 */

const {
  activeWinnerMaxDays,
  provenRecentMaxDays,
  strategicDirectionMaxDays,
  recentModerateMaxDays,
  skipOlderThanDays,
  minPrimaryTextWords,
} = config.selection;

const { highMin, moderateMin, lowMax } = config.impressions;

/**
 * Calculate priority for a single ad.
 *
 * @param {object} ad - Normalized ad record from meta-ad-library.js
 * @param {Date} now - Current date (injectable for testing)
 * @returns {{ priority: number|null, label: string, skipReason: string|null }}
 */
export function classifyAd(ad, now = new Date()) {
  const daysSinceLaunch = ad.launchDate
    ? Math.floor((now.getTime() - new Date(ad.launchDate).getTime()) / (1000 * 60 * 60 * 24))
    : null;

  const impressionLower = ad.impressions?.lower || 0;

  // --- SKIP RULES (evaluated first) ---

  // Skip: No launch date means we can't classify
  if (daysSinceLaunch === null) {
    return { priority: null, label: 'SKIP', skipReason: 'no_launch_date' };
  }

  // Skip: Legacy ads (6+ months regardless of impressions)
  if (daysSinceLaunch >= skipOlderThanDays) {
    return { priority: null, label: 'SKIP', skipReason: 'legacy_autopilot' };
  }

  // Skip: Failed tests (low impressions + older than 30 days)
  if (impressionLower < lowMax && daysSinceLaunch > provenRecentMaxDays) {
    return { priority: null, label: 'SKIP', skipReason: 'failed_test' };
  }

  // Skip: Too thin to analyze (<50 words primary text)
  if (ad.maxPrimaryTextWords < minPrimaryTextWords) {
    return { priority: null, label: 'SKIP', skipReason: 'thin_text' };
  }

  // --- PRIORITY ASSIGNMENT ---

  // Priority 1: ACTIVE WINNERS — launched <14 days ago + high impressions
  // These are ads the brand is actively scaling RIGHT NOW
  if (daysSinceLaunch <= activeWinnerMaxDays && impressionLower >= highMin) {
    return { priority: 1, label: 'ACTIVE_WINNER', skipReason: null };
  }

  // Priority 2: PROVEN RECENT — launched <30 days ago + moderate-high impressions
  // Recently proven angles that survived initial testing
  if (daysSinceLaunch <= provenRecentMaxDays && impressionLower >= moderateMin) {
    return { priority: 2, label: 'PROVEN_RECENT', skipReason: null };
  }

  // Priority 3: STRATEGIC DIRECTION — launched <7 days ago (any impression level)
  // Brand new tests showing where the brand is heading
  if (daysSinceLaunch <= strategicDirectionMaxDays) {
    return { priority: 3, label: 'STRATEGIC_DIRECTION', skipReason: null };
  }

  // Priority 4: RECENT MODERATE — launched <60 days ago + high impressions
  // Still relevant but less strategic signal
  if (daysSinceLaunch <= recentModerateMaxDays && impressionLower >= highMin) {
    return { priority: 4, label: 'RECENT_MODERATE', skipReason: null };
  }

  // Everything else: doesn't meet any priority criteria
  // Older than 7 days with low impressions, or 30-60 days with moderate impressions
  return { priority: null, label: 'SKIP', skipReason: 'below_threshold' };
}

/**
 * Deduplicate ads: for ads with similar headlines under the same advertiser,
 * keep only the version with the highest impressions.
 *
 * "Similar" = same first 60 chars of the primary text (catches minor variations).
 *
 * @param {Array} ads - Array of normalized ad records
 * @returns {{ kept: Array, duplicatesRemoved: number }}
 */
export function deduplicateAds(ads) {
  const seen = new Map(); // key → ad with highest impressions
  let duplicatesRemoved = 0;

  for (const ad of ads) {
    // Build dedup key from advertiser + primary text prefix
    const textPrefix = (ad.primaryTexts[0] || '').slice(0, 60).toLowerCase().trim();
    const key = `${ad.pageName}::${textPrefix}`;

    if (!seen.has(key)) {
      seen.set(key, ad);
    } else {
      const existing = seen.get(key);
      if (ad.impressions.lower > existing.impressions.lower) {
        seen.set(key, ad); // Replace with higher-impression version
      }
      duplicatesRemoved++;
    }
  }

  return { kept: Array.from(seen.values()), duplicatesRemoved };
}

/**
 * Full selection pipeline: classify → deduplicate → sort by priority.
 *
 * @param {Array} ads - All ads from a scan
 * @param {object} opts
 * @param {number} opts.limit - Max ads to return (for per-brand capping)
 * @param {Date} opts.now - Current date (injectable for testing)
 * @returns {{ selected: Array, skipped: Array, stats: object }}
 */
export function selectAds(ads, opts = {}) {
  const now = opts.now || new Date();
  const limit = opts.limit || Infinity;

  // Step 1: Classify every ad
  const classified = ads.map((ad) => {
    const classification = classifyAd(ad, now);
    return { ...ad, ...classification };
  });

  // Step 2: Separate selected from skipped
  const candidates = classified.filter((ad) => ad.priority !== null);
  const skipped = classified.filter((ad) => ad.priority === null);

  // Step 3: Deduplicate candidates
  const { kept, duplicatesRemoved } = deduplicateAds(candidates);

  // Step 4: Sort by priority (1 first), then by impressions within same priority
  kept.sort((a, b) => {
    if (a.priority !== b.priority) return a.priority - b.priority;
    return b.impressions.lower - a.impressions.lower;
  });

  // Step 5: Apply limit
  const selected = kept.slice(0, limit);

  // Step 6: Build stats
  const stats = {
    totalScanned: ads.length,
    totalSelected: selected.length,
    totalSkipped: skipped.length,
    duplicatesRemoved,
    byPriority: {
      activeWinners: selected.filter((a) => a.priority === 1).length,
      provenRecent: selected.filter((a) => a.priority === 2).length,
      strategicDirection: selected.filter((a) => a.priority === 3).length,
      recentModerate: selected.filter((a) => a.priority === 4).length,
    },
    skipReasons: {},
  };

  for (const ad of skipped) {
    stats.skipReasons[ad.skipReason] = (stats.skipReasons[ad.skipReason] || 0) + 1;
  }

  return { selected, skipped, stats };
}

/**
 * Select ads for a specific brand from the full scan results.
 * Applies the same priority logic but scoped to one advertiser.
 *
 * @param {Array} allAds - All ads from scan
 * @param {string} brandName - Advertiser page name
 * @param {number} maxAds - Max ads to select for this brand
 * @param {Date} now - Current date
 * @returns {{ selected: Array, stats: object }}
 */
export function selectAdsForBrand(allAds, brandName, maxAds = 15, now = new Date()) {
  const brandAds = allAds.filter(
    (ad) => ad.pageName.toLowerCase() === brandName.toLowerCase()
  );

  if (brandAds.length === 0) {
    return {
      selected: [],
      stats: { totalScanned: 0, totalSelected: 0, totalSkipped: 0, byPriority: {} },
    };
  }

  return selectAds(brandAds, { limit: maxAds, now });
}

/**
 * Given ranked advertisers and a scan, pick top N brands and select
 * the best ads per brand. This is the core logic for `meta-ads market`.
 *
 * @param {Array} rankedAdvertisers - Output of rankAdvertisers()
 * @param {Array} allAds - All ads from scan
 * @param {number} topBrands - How many brands to analyze
 * @param {number} adsPerBrand - Max ads per brand
 * @returns {Array<{ brand: object, selection: object }>}
 */
export function selectMarketAds(rankedAdvertisers, allAds, topBrands = 5, adsPerBrand = 15) {
  const now = new Date();
  const topN = rankedAdvertisers.slice(0, topBrands);

  return topN.map((brand) => {
    const selection = selectAdsForBrand(allAds, brand.pageName, adsPerBrand, now);
    return { brand, selection };
  });
}
