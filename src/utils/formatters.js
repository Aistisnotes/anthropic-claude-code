import Table from 'cli-table3';
import chalk from 'chalk';

/**
 * Format scan results into a ranked advertiser table.
 */
export function formatAdvertiserTable(rankedAdvertisers, limit = 25) {
  const table = new Table({
    head: [
      chalk.bold('#'),
      chalk.bold('Advertiser'),
      chalk.bold('Total Ads'),
      chalk.bold('Active'),
      chalk.bold('Recent (30d)'),
      chalk.bold('Impressions'),
      chalk.bold('Latest Launch'),
      chalk.bold('Score'),
    ],
    colWidths: [4, 30, 10, 8, 13, 14, 14, 7],
    style: { head: ['cyan'] },
  });

  const display = rankedAdvertisers.slice(0, limit);

  for (let i = 0; i < display.length; i++) {
    const a = display[i];
    const impressionLabel = a.totalImpressionLower > 0
      ? formatNumber(a.totalImpressionLower)
      : '—';
    const latestDate = a.latestLaunch
      ? new Date(a.latestLaunch).toISOString().slice(0, 10)
      : '—';

    table.push([
      i + 1,
      truncate(a.pageName, 28),
      a.adCount,
      a.activeAdCount,
      a.recentAdCount,
      impressionLabel,
      latestDate,
      a.relevanceScore || 0,
    ]);
  }

  return table.toString();
}

/**
 * Format ad selection stats into a readable summary.
 */
export function formatSelectionStats(stats) {
  const lines = [
    `Scanned: ${stats.totalScanned} ads`,
    `Selected: ${stats.totalSelected} ads`,
    `Skipped: ${stats.totalSkipped} ads`,
    `Duplicates removed: ${stats.duplicatesRemoved}`,
    '',
    'By Priority:',
    `  P1 Active Winners:       ${stats.byPriority.activeWinners}`,
    `  P2 Proven Recent:        ${stats.byPriority.provenRecent}`,
    `  P3 Strategic Direction:   ${stats.byPriority.strategicDirection}`,
    `  P4 Recent Moderate:      ${stats.byPriority.recentModerate}`,
  ];

  if (Object.keys(stats.skipReasons).length > 0) {
    lines.push('', 'Skip Reasons:');
    for (const [reason, count] of Object.entries(stats.skipReasons)) {
      lines.push(`  ${reason}: ${count}`);
    }
  }

  return lines.join('\n');
}

/**
 * Format a selected ad as a compact summary line.
 */
export function formatAdSummary(ad, index) {
  const prioLabel = {
    1: chalk.green('P1:WINNER'),
    2: chalk.yellow('P2:PROVEN'),
    3: chalk.blue('P3:STRAT'),
    4: chalk.dim('P4:RECENT'),
  };

  const date = ad.launchDate
    ? new Date(ad.launchDate).toISOString().slice(0, 10)
    : '—';

  const headline = ad.headlines[0] || ad.primaryTexts[0]?.slice(0, 50) || '(no text)';

  return [
    chalk.dim(`${String(index + 1).padStart(3)}.`),
    prioLabel[ad.priority] || chalk.dim('SKIP'),
    chalk.dim(`[${ad.impressions.label}]`),
    chalk.dim(date),
    truncate(headline, 50),
  ].join(' ');
}

/**
 * Format headlines grouped by advertiser.
 */
export function formatHeadlinesByBrand(rankedAdvertisers, limit = 10) {
  const lines = [];

  const display = rankedAdvertisers.slice(0, limit);
  for (const a of display) {
    lines.push(chalk.bold(`\n${a.pageName}`) + chalk.dim(` (${a.adCount} ads)`));
    const headlines = Array.from(a.headlines).slice(0, 5);
    for (const h of headlines) {
      lines.push(chalk.dim(`  • ${truncate(h, 70)}`));
    }
    if (a.headlines.size > 5) {
      lines.push(chalk.dim(`  ... +${a.headlines.size - 5} more`));
    }
  }

  return lines.join('\n');
}

/**
 * Format the full scan result as JSON for file output.
 */
export function formatScanJSON(scanResult, rankedAdvertisers, selectionResult) {
  return JSON.stringify({
    meta: {
      keyword: scanResult.keyword,
      country: scanResult.country,
      scanDate: scanResult.scanDate,
      totalAds: scanResult.totalFetched,
      pagesScanned: scanResult.pagesScanned,
      uniqueAdvertisers: scanResult.advertisers.size,
    },
    advertisers: rankedAdvertisers.map((a) => ({
      pageName: a.pageName,
      pageId: a.pageId,
      adCount: a.adCount,
      activeAdCount: a.activeAdCount,
      recentAdCount: a.recentAdCount,
      totalImpressionLower: a.totalImpressionLower,
      maxImpressionUpper: a.maxImpressionUpper,
      earliestLaunch: a.earliestLaunch,
      latestLaunch: a.latestLaunch,
      headlines: Array.from(a.headlines),
      relevanceScore: a.relevanceScore,
    })),
    selection: selectionResult ? {
      stats: selectionResult.stats,
      selected: selectionResult.selected.map((ad) => ({
        id: ad.id,
        pageName: ad.pageName,
        priority: ad.priority,
        label: ad.label,
        launchDate: ad.launchDate,
        impressions: ad.impressions,
        headlines: ad.headlines,
        primaryTextPreview: ad.primaryTexts[0]?.slice(0, 200) || null,
        snapshotUrl: ad.snapshotUrl,
      })),
    } : null,
  }, null, 2);
}

/** Truncate string with ellipsis */
function truncate(str, max) {
  if (!str) return '';
  return str.length > max ? str.slice(0, max - 1) + '…' : str;
}

/** Format large number with K/M suffix */
function formatNumber(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
