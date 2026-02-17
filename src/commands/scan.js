import { writeFileSync } from 'fs';
import { join } from 'path';
import ora from 'ora';
import chalk from 'chalk';
import { scanAdLibrary, rankAdvertisers } from '../scraper/meta-ad-library.js';
import { selectAds } from '../selection/ad-selector.js';
import { config, ensureDataDirs } from '../utils/config.js';
import { log } from '../utils/logger.js';
import {
  formatAdvertiserTable,
  formatSelectionStats,
  formatAdSummary,
  formatHeadlinesByBrand,
  formatScanJSON,
} from '../utils/formatters.js';

/**
 * Register the `scan` command on the Commander program.
 */
export function registerScanCommand(program) {
  program
    .command('scan')
    .description('Scan Meta Ad Library for a keyword — metadata only, no downloads')
    .argument('<keyword>', 'Search keyword or phrase')
    .option('-c, --country <code>', 'ISO country code', 'US')
    .option('-p, --pages <n>', 'Max API pages to fetch', parseInt, 20)
    .option('-s, --status <status>', 'Ad status: ACTIVE, INACTIVE, ALL', 'ALL')
    .option('--top <n>', 'Show top N advertisers in table', parseInt, 25)
    .option('--headlines', 'Show top headlines per brand')
    .option('--select', 'Run ad selection and show priority breakdown')
    .option('--json', 'Output full results as JSON')
    .option('-o, --output <path>', 'Save scan results to JSON file')
    .action(runScan);
}

/**
 * Execute the scan command.
 */
async function runScan(keyword, opts) {
  const spinner = ora({ text: 'Scanning Meta Ad Library...', spinner: 'dots' }).start();

  let scanResult;
  try {
    scanResult = await scanAdLibrary(keyword, {
      country: opts.country,
      maxPages: opts.pages,
      activeStatus: opts.status,
    });
    spinner.succeed(`Scanned ${scanResult.totalFetched} ads across ${scanResult.pagesScanned} pages`);
  } catch (err) {
    spinner.fail('Scan failed');
    log.error(err.message);
    process.exit(1);
  }

  // Rank advertisers by recent activity + impressions
  const ranked = rankAdvertisers(scanResult.advertisers);

  // Print summary header
  log.header(`Market Scan: "${keyword}"`);
  log.info(`Country: ${scanResult.country}`);
  log.info(`Total ads found: ${scanResult.totalFetched}`);
  log.info(`Unique advertisers: ${ranked.length}`);
  log.info(`Scan date: ${scanResult.scanDate}`);
  log.blank();

  // JSON mode: print and exit
  if (opts.json && !opts.output) {
    const selectionResult = opts.select ? selectAds(scanResult.ads) : null;
    const json = formatScanJSON(scanResult, ranked, selectionResult);
    console.log(json);
    return;
  }

  // Advertiser table
  log.header('Top Advertisers (by recent activity + impressions)');
  console.log(formatAdvertiserTable(ranked, opts.top));

  // Headlines view
  if (opts.headlines) {
    log.header('Top Headlines by Brand');
    console.log(formatHeadlinesByBrand(ranked, 10));
    log.blank();
  }

  // Selection breakdown
  if (opts.select) {
    log.header('Ad Selection Analysis');
    const selectionResult = selectAds(scanResult.ads);

    console.log(formatSelectionStats(selectionResult.stats));
    log.blank();

    if (selectionResult.selected.length > 0) {
      log.header('Selected Ads (by priority)');
      for (let i = 0; i < Math.min(selectionResult.selected.length, 30); i++) {
        console.log(formatAdSummary(selectionResult.selected[i], i));
      }
      if (selectionResult.selected.length > 30) {
        log.dim(`... +${selectionResult.selected.length - 30} more`);
      }
    }
    log.blank();
  }

  // Save to file
  if (opts.output) {
    ensureDataDirs();
    const selectionResult = selectAds(scanResult.ads);
    const json = formatScanJSON(scanResult, ranked, selectionResult);

    const outputPath = opts.output.startsWith('/')
      ? opts.output
      : join(process.cwd(), opts.output);

    writeFileSync(outputPath, json, 'utf-8');
    log.success(`Scan results saved to ${outputPath}`);
  } else {
    // Auto-save to data/scans/
    ensureDataDirs();
    const selectionResult = selectAds(scanResult.ads);
    const json = formatScanJSON(scanResult, ranked, selectionResult);
    const slug = keyword.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
    const ts = new Date().toISOString().slice(0, 10);
    const autoPath = join(config.paths.scans, `${slug}_${ts}.json`);
    writeFileSync(autoPath, json, 'utf-8');
    log.dim(`Auto-saved to ${autoPath}`);
  }
}
