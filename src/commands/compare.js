import { readFileSync, existsSync, readdirSync } from 'fs';
import { join } from 'path';
import ora from 'ora';
import { scanAdLibrary, rankAdvertisers } from '../scraper/meta-ad-library.js';
import { selectAdsForBrand } from '../selection/ad-selector.js';
import { downloadAdCreatives } from '../scraper/ad-downloader.js';
import { analyzeAdBatch } from '../analysis/pipeline.js';
import { generateBrandReport, saveBrandReport, formatBrandReportText } from '../reports/brand-report.js';
import { generateMarketMap, saveMarketMap, formatMarketMapText } from '../reports/market-map.js';
import { generateLoopholeDoc, saveLoopholeDoc, formatLoopholeDocText } from '../reports/loophole-doc.js';
import { config, ensureDataDirs } from '../utils/config.js';
import { log } from '../utils/logger.js';

/**
 * Register the `compare` command on the Commander program.
 */
export function registerCompareCommand(program) {
  program
    .command('compare')
    .description('Compare brands — Market Map + Loophole Document')
    .argument('<keyword>', 'Market keyword used for the scan')
    .option('--brand <name>', 'Focus brand for brand-specific gap analysis')
    .option('--from-reports <dir>', 'Load brand reports from directory (default: data/reports/)')
    .option('--from-scan <path>', 'Run fresh analysis from a saved scan JSON')
    .option('--top-brands <n>', 'Number of top brands when running from scan', parseInt, 5)
    .option('--ads-per-brand <n>', 'Max ads per brand when running from scan', parseInt, 15)
    .option('--no-download', 'Skip snapshot downloads when running from scan')
    .option('--json', 'Output as JSON to stdout')
    .option('-o, --output <dir>', 'Output directory for reports')
    .action(runCompare);
}

/**
 * Execute the compare command.
 *
 * Two modes:
 *   1. Load existing brand reports from disk (default or --from-reports)
 *   2. Run fresh scan → analyze → compare (--from-scan)
 */
async function runCompare(keyword, opts) {
  log.header(`Market Comparison: "${keyword}"`);

  let brandReports;

  if (opts.fromScan) {
    // Mode 2: Run fresh analysis from a scan file
    brandReports = await runFreshAnalysis(keyword, opts);
  } else {
    // Mode 1: Load existing brand reports
    brandReports = loadBrandReports(keyword, opts.fromReports);
  }

  if (!brandReports || brandReports.length < 2) {
    log.warn(`Need at least 2 brand reports for comparison. Found: ${brandReports?.length || 0}`);
    log.info('Run `meta-ads market "keyword"` first, or use --from-scan to analyze a saved scan.');
    process.exit(1);
  }

  log.info(`Loaded ${brandReports.length} brand reports`);
  log.blank();

  // ── Generate Market Map ────────────────────────────────────

  const mapSpinner = ora('Generating Market Map...').start();
  const scanDate = brandReports[0]?.meta?.scanDate || new Date().toISOString();
  const marketMap = generateMarketMap(brandReports, { keyword, scanDate });
  const mapPath = saveMarketMap(marketMap, keyword);
  mapSpinner.succeed(`Market Map saved: ${mapPath}`);

  // ── Generate Loophole Document ─────────────────────────────

  const loopSpinner = ora('Generating Loophole Document...').start();
  const loopholeDoc = generateLoopholeDoc(marketMap, brandReports, opts.brand || null);
  const loopPath = saveLoopholeDoc(loopholeDoc, keyword);
  loopSpinner.succeed(`Loophole Document saved: ${loopPath}`);

  // ── Output ─────────────────────────────────────────────────

  if (opts.json) {
    console.log(JSON.stringify({
      keyword,
      marketMap,
      loopholeDoc,
    }, null, 2));
  } else {
    log.blank();
    console.log(formatMarketMapText(marketMap));
    log.blank();
    console.log(formatLoopholeDocText(loopholeDoc));
  }

  log.blank();
  log.header('Comparison Complete');
  log.success(`Market Map: ${mapPath}`);
  log.success(`Loophole Doc: ${loopPath}`);

  const p1Count = loopholeDoc.priorityMatrix.filter((p) => p.tier === 'P1_HIGH').length;
  const p2Count = loopholeDoc.priorityMatrix.filter((p) => p.tier === 'P2_MEDIUM').length;
  log.info(`Opportunities found: ${p1Count} high priority, ${p2Count} medium priority`);

  if (opts.brand && loopholeDoc.brandGaps) {
    log.info(`Brand gaps for "${opts.brand}": ${loopholeDoc.brandGaps.length} blind spots`);
  }
}

/**
 * Load brand reports from the reports directory matching a keyword.
 */
function loadBrandReports(keyword, reportsDir) {
  const dir = reportsDir || config.paths.reports;

  if (!existsSync(dir)) {
    log.warn(`Reports directory not found: ${dir}`);
    return [];
  }

  const kwSlug = keyword.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 30);
  const files = readdirSync(dir).filter((f) => {
    // Match brand report files for this keyword (not market-map or loophole files)
    return f.startsWith(kwSlug) && f.endsWith('.json') &&
      !f.startsWith('market-map') && !f.startsWith('loopholes');
  });

  if (files.length === 0) {
    log.warn(`No brand reports found for keyword "${keyword}" in ${dir}`);
    return [];
  }

  const reports = [];
  for (const file of files) {
    try {
      const raw = JSON.parse(readFileSync(join(dir, file), 'utf-8'));
      if (raw.brand && raw.analysis && raw.strategy) {
        reports.push(raw);
      }
    } catch {
      log.dim(`Skipping invalid report: ${file}`);
    }
  }

  log.dim(`Found ${reports.length} brand reports for "${keyword}"`);
  return reports;
}

/**
 * Run fresh scan → analyze → return brand reports.
 * Used when --from-scan is provided.
 */
async function runFreshAnalysis(keyword, opts) {
  const shouldDownload = opts.download !== false;

  // Load scan data
  let scanResult;
  let ranked;

  const scanSpinner = ora('Loading scan data...').start();
  try {
    const loaded = loadScanFile(opts.fromScan);
    scanResult = loaded.scanResult;
    ranked = loaded.ranked;
    scanSpinner.succeed(`Loaded ${scanResult.ads.length} ads from scan`);
  } catch (err) {
    scanSpinner.fail(`Failed to load scan: ${err.message}`);
    process.exit(1);
  }

  // Pick top brands
  const topBrands = opts.topBrands;
  const adsPerBrand = opts.adsPerBrand;
  const selectedBrands = ranked.slice(0, topBrands);

  if (selectedBrands.length < 2) {
    log.warn('Need at least 2 brands for comparison.');
    return [];
  }

  log.info(`Analyzing ${selectedBrands.length} brands...`);
  log.blank();

  // Process each brand
  const reports = [];

  for (let i = 0; i < selectedBrands.length; i++) {
    const brand = selectedBrands[i];
    const brandSlug = brand.pageName.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);

    const brandSpinner = ora(`[${i + 1}/${selectedBrands.length}] ${brand.pageName}...`).start();

    // Select ads
    const { selected, stats: selectionStats } = selectAdsForBrand(
      scanResult.ads, brand.pageName, adsPerBrand
    );

    if (selected.length === 0) {
      brandSpinner.warn(`${brand.pageName}: no ads passed selection`);
      continue;
    }

    // Download (optional)
    let enrichedAds;
    if (shouldDownload) {
      try {
        const dlResult = await downloadAdCreatives(selected, { brandSlug, keyword, fetchSnapshots: true });
        enrichedAds = dlResult.ads;
      } catch {
        enrichedAds = selected.map((ad) => ({
          ...ad, creative: { fetchStatus: 'skipped', imageUrls: [], videoUrls: [] },
        }));
      }
    } else {
      enrichedAds = selected.map((ad) => ({
        ...ad, creative: { fetchStatus: 'skipped', imageUrls: [], videoUrls: [] },
      }));
    }

    // Analyze
    const analysisResult = analyzeAdBatch(enrichedAds);

    // Generate report
    const report = generateBrandReport(brand, analysisResult, selectionStats, {
      keyword, scanDate: scanResult.scanDate,
    });

    saveBrandReport(report, keyword);
    reports.push(report);

    brandSpinner.succeed(
      `${brand.pageName}: ${selected.length} ads, ` +
      `hook=${report.strategy.primaryHook}, angle=${report.strategy.primaryAngle}`
    );
  }

  return reports;
}

/**
 * Load a saved scan file.
 */
function loadScanFile(filepath) {
  const resolvedPath = filepath.startsWith('/') ? filepath : join(process.cwd(), filepath);

  if (!existsSync(resolvedPath)) {
    throw new Error(`Scan file not found: ${resolvedPath}`);
  }

  const raw = JSON.parse(readFileSync(resolvedPath, 'utf-8'));
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
