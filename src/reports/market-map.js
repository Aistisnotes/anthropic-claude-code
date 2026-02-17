import { writeFileSync } from 'fs';
import { join } from 'path';
import { config, ensureDataDirs } from '../utils/config.js';

/**
 * Market Map report generator.
 *
 * Takes brand reports from Session 2 and builds a cross-brand comparison matrix
 * showing where each brand competes, market saturation zones, and whitespace.
 *
 * Output:
 *   - Brand comparison matrix (hooks × brands, angles × brands, emotions × brands)
 *   - Saturation analysis (what dimensions are overcrowded)
 *   - Coverage heat map data (which dimensions are used by how many brands)
 */

// All possible dimension values for completeness
const ALL_HOOKS = ['question', 'statistic', 'bold_claim', 'fear_urgency', 'story', 'social_proof', 'curiosity', 'direct_address', 'other'];
const ALL_ANGLES = ['mechanism', 'social_proof', 'transformation', 'problem_agitate', 'scarcity', 'authority', 'educational'];
const ALL_EMOTIONS = ['security', 'achievement', 'hedonism', 'stimulation', 'self_direction', 'benevolence', 'conformity', 'tradition', 'power', 'universalism'];
const ALL_FORMATS = ['listicle', 'testimonial', 'how_to', 'long_form', 'minimal', 'emoji_heavy', 'direct_response'];
const ALL_OFFERS = ['discount', 'free_trial', 'guarantee', 'bonus', 'free_shipping', 'bundle', 'subscription', 'limited_time'];
const ALL_CTAS = ['shop_now', 'learn_more', 'sign_up', 'claim_offer', 'watch', 'download', 'contact'];

/**
 * Generate a Market Map from multiple brand reports.
 *
 * @param {Array<object>} brandReports - Array of brand report objects (from generateBrandReport)
 * @param {object} meta - { keyword, scanDate }
 * @returns {object} Market Map report
 */
export function generateMarketMap(brandReports, meta = {}) {
  const brandNames = brandReports.map((r) => r.brand.name);

  const map = {
    meta: {
      keyword: meta.keyword || 'unknown',
      scanDate: meta.scanDate || new Date().toISOString(),
      reportDate: new Date().toISOString(),
      brandsCompared: brandNames.length,
      brandNames,
    },

    // Brand-by-brand comparison matrices
    matrices: {
      hooks: buildMatrix(brandReports, ALL_HOOKS, (r) => r.analysis?.hookDistribution || {}),
      angles: buildMatrix(brandReports, ALL_ANGLES, (r) => r.analysis?.angleDistribution || {}),
      emotions: buildMatrix(brandReports, ALL_EMOTIONS, (r) => r.analysis?.emotionDistribution || {}),
      formats: buildMatrix(brandReports, ALL_FORMATS, (r) => r.analysis?.formatDistribution || {}),
      offers: buildMatrix(brandReports, ALL_OFFERS, (r) => r.analysis?.offerTypes || {}),
      ctas: buildMatrix(brandReports, ALL_CTAS, (r) => r.analysis?.ctaDistribution || {}),
    },

    // Market saturation analysis
    saturation: buildSaturationAnalysis(brandReports),

    // Brand strategy profiles (compact)
    profiles: brandReports.map((r) => ({
      name: r.brand.name,
      activity: r.strategy?.activityLevel || 'unknown',
      primaryHook: r.strategy?.primaryHook || 'unknown',
      primaryAngle: r.strategy?.primaryAngle || 'unknown',
      primaryEmotion: r.strategy?.primaryEmotion || 'unknown',
      primaryFormat: r.strategy?.primaryFormat || 'unknown',
      primaryCta: r.strategy?.primaryCta || 'unknown',
      contentDepth: r.strategy?.contentDepth || 'unknown',
      hookDiversity: r.strategy?.hookDiversity || 0,
      angleDiversity: r.strategy?.angleDiversity || 0,
      adsAnalyzed: r.analysis?.totalAnalyzed || 0,
      usesOffers: r.strategy?.usesOffers || false,
      usesVideo: r.strategy?.usesVideo || false,
    })),
  };

  return map;
}

/**
 * Build a comparison matrix for one dimension.
 *
 * Returns { dimension: string, brands: { [brandName]: count }, coverage: number, total: number }
 * for each possible value in that dimension.
 */
function buildMatrix(brandReports, allValues, getDistribution) {
  return allValues.map((value) => {
    const brands = {};
    let total = 0;
    let brandsUsing = 0;

    for (const report of brandReports) {
      const dist = getDistribution(report);
      const count = dist[value] || 0;
      brands[report.brand.name] = count;
      total += count;
      if (count > 0) brandsUsing++;
    }

    return {
      dimension: value,
      brands,
      coverage: brandsUsing,                                    // How many brands use this
      coveragePercent: Math.round((brandsUsing / (brandReports.length || 1)) * 100),
      total,                                                     // Total ads using this across all brands
    };
  });
}

/**
 * Analyze market saturation across all dimensions.
 */
function buildSaturationAnalysis(brandReports) {
  const n = brandReports.length || 1;

  const hookCoverage = computeCoverage(brandReports, ALL_HOOKS, (r) => r.analysis?.hookDistribution || {});
  const angleCoverage = computeCoverage(brandReports, ALL_ANGLES, (r) => r.analysis?.angleDistribution || {});
  const emotionCoverage = computeCoverage(brandReports, ALL_EMOTIONS, (r) => r.analysis?.emotionDistribution || {});
  const formatCoverage = computeCoverage(brandReports, ALL_FORMATS, (r) => r.analysis?.formatDistribution || {});

  // Classify saturation levels
  const classify = (coverage, total) => {
    const saturated = coverage.filter((c) => c.coveragePercent >= 60);
    const moderate = coverage.filter((c) => c.coveragePercent >= 30 && c.coveragePercent < 60);
    const whitespace = coverage.filter((c) => c.coveragePercent < 30);
    return { saturated, moderate, whitespace };
  };

  return {
    hooks: classify(hookCoverage),
    angles: classify(angleCoverage),
    emotions: classify(emotionCoverage),
    formats: classify(formatCoverage),

    // Overall market stats
    overall: {
      totalBrands: n,
      avgHookDiversity: Math.round(brandReports.reduce((s, r) => s + (r.strategy?.hookDiversity || 0), 0) / n * 10) / 10,
      avgAngleDiversity: Math.round(brandReports.reduce((s, r) => s + (r.strategy?.angleDiversity || 0), 0) / n * 10) / 10,
      offerUsage: Math.round(brandReports.filter((r) => r.strategy?.usesOffers).length / n * 100),
      videoUsage: Math.round(brandReports.filter((r) => r.strategy?.usesVideo).length / n * 100),
    },
  };
}

/**
 * Compute coverage for each value in a dimension.
 */
function computeCoverage(brandReports, allValues, getDistribution) {
  return allValues.map((value) => {
    let brandsUsing = 0;
    for (const report of brandReports) {
      const dist = getDistribution(report);
      if ((dist[value] || 0) > 0) brandsUsing++;
    }
    return {
      dimension: value,
      coverage: brandsUsing,
      coveragePercent: Math.round((brandsUsing / (brandReports.length || 1)) * 100),
    };
  });
}

/**
 * Save a Market Map report to disk.
 */
export function saveMarketMap(marketMap, keyword) {
  ensureDataDirs();
  const kwSlug = (keyword || 'unknown').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 30);
  const ts = new Date().toISOString().slice(0, 10);
  const filename = `market-map_${kwSlug}_${ts}.json`;
  const filepath = join(config.paths.reports, filename);
  writeFileSync(filepath, JSON.stringify(marketMap, null, 2), 'utf-8');
  return filepath;
}

/**
 * Format Market Map as human-readable terminal output.
 */
export function formatMarketMapText(marketMap) {
  const lines = [];
  const m = marketMap.meta;

  lines.push(`${'═'.repeat(70)}`);
  lines.push(`  MARKET MAP: "${m.keyword}"`);
  lines.push(`  ${m.brandsCompared} brands compared | ${m.scanDate.slice(0, 10)}`);
  lines.push(`${'═'.repeat(70)}`);
  lines.push('');

  // Brand profiles overview
  lines.push(`${'─'.repeat(70)}`);
  lines.push('  BRAND STRATEGY PROFILES');
  lines.push(`${'─'.repeat(70)}`);

  for (const p of marketMap.profiles) {
    lines.push(`  ${p.name} (${p.activity.toUpperCase()}, ${p.adsAnalyzed} ads)`);
    lines.push(`    Hook: ${p.primaryHook}  |  Angle: ${p.primaryAngle}  |  Emotion: ${p.primaryEmotion}`);
    lines.push(`    Format: ${p.primaryFormat}  |  CTA: ${p.primaryCta}  |  Depth: ${p.contentDepth}`);
    lines.push(`    Diversity — hooks: ${p.hookDiversity}  angles: ${p.angleDiversity}  offers: ${p.usesOffers ? 'yes' : 'no'}  video: ${p.usesVideo ? 'yes' : 'no'}`);
    lines.push('');
  }

  // Saturation heat map
  lines.push(`${'─'.repeat(70)}`);
  lines.push('  SATURATION ANALYSIS');
  lines.push(`${'─'.repeat(70)}`);

  const satDimensions = [
    { label: 'Hooks', data: marketMap.saturation.hooks },
    { label: 'Angles', data: marketMap.saturation.angles },
    { label: 'Emotions', data: marketMap.saturation.emotions },
    { label: 'Formats', data: marketMap.saturation.formats },
  ];

  for (const { label, data } of satDimensions) {
    lines.push(`\n  ${label}:`);
    if (data.saturated.length > 0) {
      lines.push(`    SATURATED (60%+ brands): ${data.saturated.map((s) => s.dimension).join(', ')}`);
    }
    if (data.moderate.length > 0) {
      lines.push(`    MODERATE  (30-59%):       ${data.moderate.map((s) => s.dimension).join(', ')}`);
    }
    if (data.whitespace.length > 0) {
      lines.push(`    WHITESPACE (<30%):        ${data.whitespace.map((s) => s.dimension).join(', ')}`);
    }
  }

  lines.push('');

  // Market-level stats
  const o = marketMap.saturation.overall;
  lines.push(`${'─'.repeat(70)}`);
  lines.push('  MARKET OVERVIEW');
  lines.push(`${'─'.repeat(70)}`);
  lines.push(`  Avg Hook Diversity:  ${o.avgHookDiversity} types per brand`);
  lines.push(`  Avg Angle Diversity: ${o.avgAngleDiversity} types per brand`);
  lines.push(`  Offer Usage:         ${o.offerUsage}% of brands`);
  lines.push(`  Video Usage:         ${o.videoUsage}% of brands`);
  lines.push('');

  // Comparison matrix for hooks (compact table)
  lines.push(`${'─'.repeat(70)}`);
  lines.push('  HOOK COMPARISON MATRIX');
  lines.push(`${'─'.repeat(70)}`);
  lines.push(formatMatrixCompact(marketMap.matrices.hooks, marketMap.meta.brandNames));

  lines.push(`${'─'.repeat(70)}`);
  lines.push('  ANGLE COMPARISON MATRIX');
  lines.push(`${'─'.repeat(70)}`);
  lines.push(formatMatrixCompact(marketMap.matrices.angles, marketMap.meta.brandNames));

  lines.push(`${'─'.repeat(70)}`);
  lines.push('  EMOTION COMPARISON MATRIX (SCHWARTZ)');
  lines.push(`${'─'.repeat(70)}`);
  lines.push(formatMatrixCompact(marketMap.matrices.emotions, marketMap.meta.brandNames));

  lines.push('');
  lines.push(`${'═'.repeat(70)}`);

  return lines.join('\n');
}

/**
 * Format a matrix as a compact comparison view.
 */
function formatMatrixCompact(matrixRows, brandNames) {
  const lines = [];
  const shortNames = brandNames.map((n) => n.slice(0, 12).padEnd(12));

  // Header
  lines.push(`  ${''.padEnd(18)} ${shortNames.join(' ')}  CVG`);
  lines.push(`  ${'─'.repeat(18 + shortNames.length * 13 + 4)}`);

  for (const row of matrixRows) {
    const dimLabel = row.dimension.padEnd(18);
    const values = brandNames.map((name) => {
      const count = row.brands[name] || 0;
      return String(count).padStart(5).padEnd(12);
    });
    const cvg = `${row.coveragePercent}%`;
    lines.push(`  ${dimLabel} ${values.join(' ')}  ${cvg}`);
  }

  return lines.join('\n');
}

export { ALL_HOOKS, ALL_ANGLES, ALL_EMOTIONS, ALL_FORMATS, ALL_OFFERS, ALL_CTAS };
