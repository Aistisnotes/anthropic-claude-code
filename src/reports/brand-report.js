import { writeFileSync } from 'fs';
import { join } from 'path';
import { config, ensureDataDirs } from '../utils/config.js';

/**
 * Per-brand mini-report generator.
 *
 * Takes analyzed ads for a single brand and produces a structured report
 * covering strategy patterns, messaging themes, top performers, and gaps.
 */

/**
 * Generate a mini-report for a single brand.
 *
 * @param {object} brand - Advertiser entry from rankAdvertisers()
 * @param {object} analysisResult - Output of analyzeAdBatch() for this brand's ads
 * @param {object} selectionStats - Output of selectAdsForBrand().stats
 * @param {object} meta - { keyword, scanDate }
 * @returns {object} Structured report object
 */
export function generateBrandReport(brand, analysisResult, selectionStats, meta = {}) {
  const { analyzed, summary } = analysisResult;

  const report = {
    // Header
    brand: {
      name: brand.pageName,
      pageId: brand.pageId,
      totalAds: brand.adCount,
      activeAds: brand.activeAdCount,
      recentAds: brand.recentAdCount,
      relevanceScore: brand.relevanceScore,
      earliestLaunch: brand.earliestLaunch,
      latestLaunch: brand.latestLaunch,
      impressionsLower: brand.totalImpressionLower,
    },

    // Scan context
    meta: {
      keyword: meta.keyword || 'unknown',
      scanDate: meta.scanDate || new Date().toISOString(),
      reportDate: new Date().toISOString(),
    },

    // Selection summary
    selection: {
      totalScanned: selectionStats.totalScanned,
      totalSelected: selectionStats.totalSelected,
      totalSkipped: selectionStats.totalSkipped,
      duplicatesRemoved: selectionStats.duplicatesRemoved,
      byPriority: selectionStats.byPriority,
    },

    // Analysis summary
    analysis: summary,

    // Strategy insights (derived)
    strategy: deriveStrategy(analyzed, summary, brand),

    // Top ads (sorted by priority, then impressions)
    topAds: analyzed.slice(0, 10).map(formatAdForReport),
  };

  return report;
}

/**
 * Derive strategy insights from analyzed ads.
 */
function deriveStrategy(analyzed, summary, brand) {
  const strategy = {
    primaryHook: getTopKey(summary.hookDistribution),
    primaryAngle: getTopKey(summary.angleDistribution),
    primaryFormat: getTopKey(summary.formatDistribution),
    primaryEmotion: getTopKey(summary.emotionDistribution),
    primaryCta: getTopKey(summary.ctaDistribution),

    // Activity level assessment
    activityLevel: assessActivity(brand),

    // Messaging diversity (how many different angles/hooks they use)
    hookDiversity: Object.keys(summary.hookDistribution).length,
    angleDiversity: Object.keys(summary.angleDistribution).length,

    // Offer strategy
    usesOffers: Object.keys(summary.offerTypes).length > 0,
    offerTypes: Object.keys(summary.offerTypes),

    // Content depth
    avgWordCount: summary.avgWordCount,
    contentDepth: summary.avgWordCount > 150 ? 'long_form' :
      summary.avgWordCount > 75 ? 'medium' : 'short',

    // Media strategy
    usesVideo: summary.withVideo > 0,
    videoRatio: summary.totalAnalyzed > 0
      ? Math.round((summary.withVideo / summary.totalAnalyzed) * 100) : 0,

    // Key patterns (top 3 hooks + angles for gap analysis later)
    topHooks: getTopN(summary.hookDistribution, 3),
    topAngles: getTopN(summary.angleDistribution, 3),
    topEmotions: getTopN(summary.emotionDistribution, 3),
  };

  return strategy;
}

/**
 * Assess brand activity level.
 */
function assessActivity(brand) {
  if (brand.recentAdCount >= 10 && brand.activeAdCount >= 5) return 'aggressive';
  if (brand.recentAdCount >= 5) return 'active';
  if (brand.recentAdCount >= 2) return 'moderate';
  if (brand.activeAdCount >= 1) return 'minimal';
  return 'dormant';
}

/**
 * Format a single ad record for the report output.
 */
function formatAdForReport(ad) {
  return {
    id: ad.id,
    priority: ad.priority,
    label: ad.label,
    launchDate: ad.launchDate,
    impressions: ad.impressions,
    headline: ad.headlines?.[0] || null,
    primaryTextPreview: ad.primaryTexts?.[0]?.slice(0, 300) || null,
    analysis: {
      hook: ad.analysis.hook.type,
      dominantAngle: ad.analysis.dominantAngle,
      format: ad.analysis.format,
      emotion: ad.analysis.dominantEmotion,
      cta: ad.analysis.cta,
      offers: ad.analysis.offers.map((o) => o.type),
      wordCount: ad.analysis.wordCount,
    },
    snapshotUrl: ad.snapshotUrl,
    landingPage: ad.analysis.landingPage,
  };
}

/**
 * Save a brand report to disk as JSON.
 *
 * @param {object} report - Output of generateBrandReport()
 * @param {string} keyword - Search keyword slug
 * @returns {string} Path to saved report file
 */
export function saveBrandReport(report, keyword) {
  ensureDataDirs();

  const slug = report.brand.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
  const kwSlug = (keyword || 'unknown').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 30);
  const ts = new Date().toISOString().slice(0, 10);
  const filename = `${kwSlug}_${slug}_${ts}.json`;
  const filepath = join(config.paths.reports, filename);

  writeFileSync(filepath, JSON.stringify(report, null, 2), 'utf-8');
  return filepath;
}

/**
 * Format a brand report as human-readable text for terminal output.
 */
export function formatBrandReportText(report) {
  const lines = [];
  const b = report.brand;
  const s = report.strategy;

  // Header
  lines.push(`${'═'.repeat(60)}`);
  lines.push(`  BRAND REPORT: ${b.name}`);
  lines.push(`${'═'.repeat(60)}`);
  lines.push('');

  // Brand overview
  lines.push(`  Total Ads: ${b.totalAds}  |  Active: ${b.activeAds}  |  Recent (30d): ${b.recentAds}`);
  lines.push(`  Impressions: ${formatNumber(b.impressionsLower)}+  |  Score: ${b.relevanceScore}`);
  lines.push(`  Activity Level: ${s.activityLevel.toUpperCase()}`);
  lines.push('');

  // Selection breakdown
  const sel = report.selection;
  lines.push(`  Selected ${sel.totalSelected} of ${sel.totalScanned} ads (${sel.totalSkipped} skipped, ${sel.duplicatesRemoved} dupes)`);
  const bp = sel.byPriority;
  lines.push(`  P1 Winners: ${bp.activeWinners}  |  P2 Proven: ${bp.provenRecent}  |  P3 Strategic: ${bp.strategicDirection}  |  P4 Recent: ${bp.recentModerate}`);
  lines.push('');

  // Strategy summary
  lines.push(`${'─'.repeat(60)}`);
  lines.push('  STRATEGY PROFILE');
  lines.push(`${'─'.repeat(60)}`);
  lines.push(`  Primary Hook:    ${s.primaryHook}`);
  lines.push(`  Primary Angle:   ${s.primaryAngle}`);
  lines.push(`  Primary Format:  ${s.primaryFormat}`);
  lines.push(`  Primary Emotion: ${s.primaryEmotion}`);
  lines.push(`  Primary CTA:     ${s.primaryCta}`);
  lines.push(`  Content Depth:   ${s.contentDepth} (avg ${s.avgWordCount} words)`);
  lines.push(`  Hook Diversity:  ${s.hookDiversity} types  |  Angle Diversity: ${s.angleDiversity} types`);

  if (s.usesOffers) {
    lines.push(`  Offer Types:     ${s.offerTypes.join(', ')}`);
  }
  if (s.usesVideo) {
    lines.push(`  Video Usage:     ${s.videoRatio}% of ads`);
  }
  lines.push('');

  // Top ads
  lines.push(`${'─'.repeat(60)}`);
  lines.push('  TOP ADS');
  lines.push(`${'─'.repeat(60)}`);

  for (let i = 0; i < Math.min(report.topAds.length, 5); i++) {
    const ad = report.topAds[i];
    const date = ad.launchDate ? new Date(ad.launchDate).toISOString().slice(0, 10) : '—';
    lines.push('');
    lines.push(`  ${i + 1}. [P${ad.priority}] ${ad.headline || '(no headline)'}`);
    lines.push(`     ${date}  |  ${ad.impressions.label}  |  Hook: ${ad.analysis.hook}  |  Angle: ${ad.analysis.dominantAngle}`);
    if (ad.primaryTextPreview) {
      const preview = ad.primaryTextPreview.slice(0, 120).replace(/\n/g, ' ');
      lines.push(`     "${preview}..."`);
    }
  }

  lines.push('');
  lines.push(`${'═'.repeat(60)}`);

  return lines.join('\n');
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

/**
 * Get top N keys from a distribution.
 */
function getTopN(distribution, n) {
  return Object.entries(distribution)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([key, count]) => ({ key, count }));
}

function formatNumber(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
