import { readFileSync, existsSync } from 'fs';
import { join } from 'path';
import ora from 'ora';
import chalk from 'chalk';
import { scanAdLibrary, rankAdvertisers } from '../scraper/meta-ad-library.js';
import { selectAdsForBrand } from '../selection/ad-selector.js';
import { downloadAdCreatives } from '../scraper/ad-downloader.js';
import { analyzeAdBatch } from '../analysis/pipeline.js';
import { generateBrandReport, saveBrandReport, formatBrandReportText } from '../reports/brand-report.js';
import { config, ensureDataDirs } from '../utils/config.js';
import { log } from '../utils/logger.js';

/**
 * Register the `market` command on the Commander program.
 */
export function registerMarketCommand(program) {
  program
    .command('market')
    .description('Full market research — scan, select, download, analyze, report')
    .argument('<keyword>', 'Search keyword or phrase')
    .option('-c, --country <code>', 'ISO country code', 'US')
    .option('-p, --pages <n>', 'Max API pages to fetch', parseInt, 20)
    .option('-s, --status <status>', 'Ad status: ACTIVE, INACTIVE, ALL', 'ALL')
    .option('--top-brands <n>', 'Number of top brands to analyze', parseInt, 5)
    .option('--ads-per-brand <n>', 'Max ads to select per brand', parseInt, 15)
    .option('--no-download', 'Skip snapshot downloads (metadata-only analysis)')
    .option('--from-scan <path>', 'Load from a saved scan JSON instead of scanning')
    .option('--json', 'Output reports as JSON to stdout')
    .option('-o, --output <dir>', 'Output directory for reports')
    .action(runMarket);
}

/**
 * Execute the market command.
 *
 * Pipeline:
 *   1. Scan (or load saved scan)
 *   2. Rank advertisers → pick top N brands
 *   3. Select best ads per brand (P1-P4)
 *   4. Download selected ad creatives (optional)
 *   5. Run analysis pipeline
 *   6. Generate per-brand mini-reports
 */
async function runMarket(keyword, opts) {
  const topBrands = opts.topBrands;
  const adsPerBrand = opts.adsPerBrand;
  const shouldDownload = opts.download !== false;

  log.header(`Market Research: "${keyword}"`);
  log.info(`Top brands: ${topBrands} | Ads per brand: ${adsPerBrand} | Download: ${shouldDownload}`);
  log.blank();

  // ── Step 1: Get scan data ──────────────────────────────────

  let scanResult;
  let ranked;

  if (opts.fromScan) {
    const loadSpinner = ora('Loading saved scan...').start();
    try {
      const loaded = loadScanFromFile(opts.fromScan);
      scanResult = loaded.scanResult;
      ranked = loaded.ranked;
      loadSpinner.succeed(`Loaded ${scanResult.ads.length} ads from saved scan`);
    } catch (err) {
      loadSpinner.fail('Failed to load scan file');
      log.error(err.message);
      process.exit(1);
    }
  } else {
    const scanSpinner = ora('Scanning Meta Ad Library...').start();
    try {
      scanResult = await scanAdLibrary(keyword, {
        country: opts.country,
        maxPages: opts.pages,
        activeStatus: opts.status,
      });
      ranked = rankAdvertisers(scanResult.advertisers);
      scanSpinner.succeed(`Scanned ${scanResult.totalFetched} ads, ${ranked.length} advertisers`);
    } catch (err) {
      scanSpinner.fail('Scan failed');
      log.error(err.message);
      process.exit(1);
    }
  }

  // ── Step 2: Pick top N brands ──────────────────────────────

  const selectedBrands = ranked.slice(0, topBrands);

  if (selectedBrands.length === 0) {
    log.warn('No advertisers found. Try a different keyword or broader search.');
    process.exit(0);
  }

  log.blank();
  log.header('Selected Brands');
  for (let i = 0; i < selectedBrands.length; i++) {
    const b = selectedBrands[i];
    log.info(`  ${i + 1}. ${b.pageName} (${b.adCount} ads, score: ${b.relevanceScore})`);
  }
  log.blank();

  // ── Steps 3-6: Process each brand ─────────────────────────

  const allReports = [];

  for (let i = 0; i < selectedBrands.length; i++) {
    const brand = selectedBrands[i];
    const brandSlug = brand.pageName.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);

    log.header(`[${i + 1}/${selectedBrands.length}] ${brand.pageName}`);

    // Step 3: Select best ads for this brand
    const selectSpinner = ora('Selecting ads...').start();
    const { selected, stats: selectionStats } = selectAdsForBrand(
      scanResult.ads, brand.pageName, adsPerBrand
    );
    selectSpinner.succeed(
      `Selected ${selected.length} ads ` +
      `(P1:${selectionStats.byPriority.activeWinners} P2:${selectionStats.byPriority.provenRecent} ` +
      `P3:${selectionStats.byPriority.strategicDirection} P4:${selectionStats.byPriority.recentModerate})`
    );

    if (selected.length === 0) {
      log.warn('  No ads passed selection criteria. Skipping brand.');
      log.blank();
      continue;
    }

    // Step 4: Download creatives (optional)
    let enrichedAds;
    if (shouldDownload) {
      const dlSpinner = ora('Downloading creatives...').start();
      try {
        const dlResult = await downloadAdCreatives(selected, {
          brandSlug,
          keyword,
          fetchSnapshots: true,
        });
        enrichedAds = dlResult.ads;
        dlSpinner.succeed(
          `Downloaded ${dlResult.downloaded} creatives ` +
          `(${dlResult.failed} failed, ${dlResult.skippedNoUrl} no URL)`
        );
      } catch (err) {
        dlSpinner.warn(`Download failed: ${err.message}. Continuing with metadata only.`);
        enrichedAds = selected.map((ad) => ({
          ...ad,
          creative: { fetchStatus: 'skipped', imageUrls: [], videoUrls: [] },
        }));
      }
    } else {
      enrichedAds = selected.map((ad) => ({
        ...ad,
        creative: { fetchStatus: 'skipped', imageUrls: [], videoUrls: [] },
      }));
      log.dim('  Skipping downloads (--no-download)');
    }

    // Step 5: Run analysis pipeline
    const analyzeSpinner = ora('Analyzing ads...').start();
    const analysisResult = analyzeAdBatch(enrichedAds);
    analyzeSpinner.succeed(
      `Analyzed ${analysisResult.summary.totalAnalyzed} ads ` +
      `(hook: ${getTopKey(analysisResult.summary.hookDistribution)}, ` +
      `angle: ${getTopKey(analysisResult.summary.angleDistribution)})`
    );

    // Step 6: Generate report
    const reportSpinner = ora('Generating report...').start();
    const report = generateBrandReport(brand, analysisResult, selectionStats, {
      keyword,
      scanDate: scanResult.scanDate,
    });

    const reportPath = saveBrandReport(report, keyword);
    reportSpinner.succeed(`Report saved: ${reportPath}`);

    allReports.push(report);

    // Print report to terminal
    if (!opts.json) {
      log.blank();
      console.log(formatBrandReportText(report));
    }

    log.blank();
  }

  // ── Final summary ─────────────────────────────────────────

  if (opts.json) {
    console.log(JSON.stringify({
      keyword,
      scanDate: scanResult.scanDate,
      brandsAnalyzed: allReports.length,
      reports: allReports,
    }, null, 2));
  } else {
    log.header('Market Research Complete');
    log.success(`Analyzed ${allReports.length} brands for "${keyword}"`);
    log.info(`Reports saved to ${config.paths.reports}`);

    // Quick cross-brand summary
    if (allReports.length >= 2) {
      log.blank();
      log.header('Cross-Brand Quick Summary');
      for (const r of allReports) {
        const s = r.strategy;
        log.info(
          `  ${r.brand.name}: ${s.activityLevel} | ` +
          `hook=${s.primaryHook} angle=${s.primaryAngle} ` +
          `emotion=${s.primaryEmotion}`
        );
      }
    }
  }
}

/**
 * Load a saved scan JSON file and reconstruct the data structures.
 */
function loadScanFromFile(filepath) {
  const resolvedPath = filepath.startsWith('/')
    ? filepath
    : join(process.cwd(), filepath);

  if (!existsSync(resolvedPath)) {
    throw new Error(`Scan file not found: ${resolvedPath}`);
  }

  const raw = JSON.parse(readFileSync(resolvedPath, 'utf-8'));

  // Reconstruct scanResult from saved JSON
  // The saved JSON has meta, advertisers[], and selection
  // We need to reconstruct the ads array from selection.selected + any additional data
  // If the full ads aren't saved, we work with what we have

  const ads = raw.selection?.selected || [];
  const advertisersMap = new Map();

  for (const a of raw.advertisers || []) {
    advertisersMap.set(a.pageName, {
      ...a,
      ads: [],
      headlines: new Set(a.headlines || []),
    });
  }

  const scanResult = {
    keyword: raw.meta?.keyword || 'unknown',
    country: raw.meta?.country || 'US',
    scanDate: raw.meta?.scanDate || new Date().toISOString(),
    ads,
    advertisers: advertisersMap,
    totalFetched: raw.meta?.totalAds || ads.length,
    pagesScanned: raw.meta?.pagesScanned || 0,
  };

  const ranked = rankAdvertisers(advertisersMap);

  return { scanResult, ranked };
}

/**
 * Get the key with the highest count from a distribution object.
 */
function getTopKey(distribution) {
  let topKey = 'unknown';
  let topCount = 0;
  for (const [key, count] of Object.entries(distribution)) {
    if (count > topCount) {
      topCount = count;
      topKey = key;
    }
  }
  return topKey;
}
