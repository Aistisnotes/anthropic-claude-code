import { chromium } from 'playwright';
import { writeFileSync, existsSync, mkdirSync, readFileSync } from 'fs';
import { join } from 'path';
import { config, ensureDataDirs } from '../utils/config.js';
import { log } from '../utils/logger.js';

/**
 * Selective ad creative downloader.
 *
 * Takes selected ads (output of ad-selector) and fetches additional creative
 * data from Meta's snapshot URLs using Playwright browser automation.
 * This avoids 403 errors from Meta's bot detection.
 */

const SNAPSHOT_TIMEOUT_MS = 30000;
const DELAY_BETWEEN_FETCHES_MS = 800;

/**
 * Download/enrich creative data for a batch of selected ads.
 *
 * @param {Array} selectedAds - Ads from selectAdsForBrand() with priority assigned
 * @param {object} opts
 * @param {string} opts.brandSlug - Slug for file naming (e.g. "brand-name")
 * @param {string} opts.keyword - Original search keyword
 * @param {boolean} opts.fetchSnapshots - Whether to attempt snapshot fetches (default: true)
 * @param {string} opts.outputDir - Override output directory
 * @returns {{ ads: Array, downloaded: number, failed: number, skippedNoUrl: number }}
 */
export async function downloadAdCreatives(selectedAds, opts = {}) {
  const fetchSnapshots = opts.fetchSnapshots ?? true;
  ensureDataDirs();

  const brandSlug = opts.brandSlug || 'unknown-brand';
  const outputDir = opts.outputDir || join(config.paths.downloads, brandSlug);

  if (!existsSync(outputDir)) {
    mkdirSync(outputDir, { recursive: true });
  }

  let downloaded = 0;
  let failed = 0;
  let skippedNoUrl = 0;

  const enrichedAds = [];

  // Launch browser once and reuse for all downloads
  let browser = null;
  let page = null;

  try {
    if (fetchSnapshots && selectedAds.some(ad => ad.snapshotUrl)) {
      browser = await chromium.launch({
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

      page = await context.newPage();
    }

    for (let i = 0; i < selectedAds.length; i++) {
      const ad = { ...selectedAds[i] };
      ad.creative = {
        imageUrls: [],
        videoUrls: [],
        ctaText: null,
        landingPageUrl: null,
        rawSnapshotHtml: null,
        fetchStatus: 'pending',
      };

      if (!fetchSnapshots || !ad.snapshotUrl) {
        ad.creative.fetchStatus = ad.snapshotUrl ? 'skipped' : 'no_url';
        if (!ad.snapshotUrl) skippedNoUrl++;
        enrichedAds.push(ad);
        continue;
      }

      try {
        const html = await fetchSnapshotHtml(ad.snapshotUrl, page);
        const extracted = extractCreativeData(html);

        ad.creative = {
          ...ad.creative,
          ...extracted,
          fetchStatus: 'success',
        };

        // Save raw HTML for debugging/deep analysis
        const htmlPath = join(outputDir, `${ad.id}.html`);
        writeFileSync(htmlPath, html, 'utf-8');

        downloaded++;
        log.dim(`  [${i + 1}/${selectedAds.length}] Downloaded ${ad.id}`);
      } catch (err) {
        ad.creative.fetchStatus = 'failed';
        ad.creative.fetchError = err.message;
        failed++;
        log.dim(`  [${i + 1}/${selectedAds.length}] Failed ${ad.id}: ${err.message.slice(0, 60)}`);
      }

      // Rate limit
      if (i < selectedAds.length - 1) {
        await sleep(DELAY_BETWEEN_FETCHES_MS);
      }

      enrichedAds.push(ad);
    }
  } finally {
    // Clean up browser
    if (browser) {
      await browser.close();
    }
  }

  // Save enriched ad data as JSON
  const jsonPath = join(outputDir, `_enriched_ads.json`);
  writeFileSync(jsonPath, JSON.stringify(enrichedAds, null, 2), 'utf-8');

  return { ads: enrichedAds, downloaded, failed, skippedNoUrl };
}

/**
 * Fetch the HTML from a Meta ad snapshot URL using Playwright.
 * Avoids 403 errors from Meta's bot detection.
 */
async function fetchSnapshotHtml(url, page) {
  try {
    // Navigate to the ad snapshot page
    await page.goto(url, {
      waitUntil: 'domcontentloaded',
      timeout: SNAPSHOT_TIMEOUT_MS,
    });

    // Wait a bit for any dynamic content to load
    await page.waitForTimeout(2000);

    // Get the full HTML content
    const html = await page.content();

    return html;
  } catch (err) {
    throw new Error(`Failed to fetch snapshot: ${err.message}`);
  }
}

/**
 * Extract creative elements from snapshot HTML.
 *
 * This is best-effort parsing — Meta's snapshot format changes over time.
 * We extract what we can and fall back gracefully.
 */
function extractCreativeData(html) {
  const result = {
    imageUrls: [],
    videoUrls: [],
    ctaText: null,
    landingPageUrl: null,
  };

  // Extract image URLs (common patterns in Meta ad snapshots)
  const imgMatches = html.matchAll(/<img[^>]+src="([^"]+)"/gi);
  for (const match of imgMatches) {
    const src = decodeHtmlEntities(match[1]);
    // Filter out tracking pixels and icons (small images)
    if (!src.includes('pixel') && !src.includes('tr?') && !src.includes('1x1')) {
      result.imageUrls.push(src);
    }
  }

  // Extract video source URLs
  const videoMatches = html.matchAll(/<(?:video|source)[^>]+src="([^"]+)"/gi);
  for (const match of videoMatches) {
    result.videoUrls.push(decodeHtmlEntities(match[1]));
  }

  // Extract CTA button text
  const ctaPatterns = [
    /<[^>]*class="[^"]*cta[^"]*"[^>]*>([^<]+)</i,
    /<button[^>]*>([^<]+)<\/button>/i,
    /data-cta[^>]*>([^<]+)</i,
  ];
  for (const pattern of ctaPatterns) {
    const ctaMatch = html.match(pattern);
    if (ctaMatch) {
      result.ctaText = ctaMatch[1].trim();
      break;
    }
  }

  // Extract landing page URL
  const linkPatterns = [
    /href="(https?:\/\/[^"]+)"[^>]*(?:target|rel)/i,
    /data-link-url="([^"]+)"/i,
    /window\.open\('([^']+)'/i,
  ];
  for (const pattern of linkPatterns) {
    const linkMatch = html.match(pattern);
    if (linkMatch) {
      result.landingPageUrl = decodeHtmlEntities(linkMatch[1]);
      break;
    }
  }

  return result;
}

/**
 * Load previously downloaded enriched ads from disk.
 */
export function loadEnrichedAds(brandSlug) {
  const jsonPath = join(config.paths.downloads, brandSlug, '_enriched_ads.json');
  if (!existsSync(jsonPath)) return null;
  return JSON.parse(readFileSync(jsonPath, 'utf-8'));
}

/**
 * Decode common HTML entities.
 */
function decodeHtmlEntities(str) {
  return str
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
