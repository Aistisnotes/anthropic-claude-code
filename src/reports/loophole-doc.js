import { writeFileSync } from 'fs';
import { join } from 'path';
import { config, ensureDataDirs } from '../utils/config.js';
import { isClaudeAvailable, generateStrategicRecommendations } from '../analysis/claude-client.js';
import { ALL_HOOKS, ALL_ANGLES, ALL_EMOTIONS, ALL_FORMATS, ALL_OFFERS, ALL_CTAS } from './market-map.js';

/**
 * Master Loophole Document generator.
 *
 * Two modes:
 *   1. Claude API — strategic narrative, exploitation guides, contrarian plays,
 *      brand-specific action plans with priority reasoning
 *   2. Heuristic fallback — matrix-based gap/saturation/priority computation
 *
 * The heuristic layer always runs (produces the data foundation).
 * Claude adds strategic interpretation on top when available.
 */

/**
 * Generate the Master Loophole Document.
 *
 * @param {object} marketMap - Output of generateMarketMap()
 * @param {Array<object>} brandReports - Original brand report objects
 * @param {string} focusBrand - Optional: generate brand-specific gaps for this brand
 * @returns {Promise<object>} Loophole document
 */
export async function generateLoopholeDoc(marketMap, brandReports, focusBrand = null) {
  const doc = {
    meta: {
      keyword: marketMap.meta.keyword,
      reportDate: new Date().toISOString(),
      brandsCompared: marketMap.meta.brandsCompared,
      focusBrand: focusBrand || null,
    },

    // Market-wide gaps: things NO ONE is doing
    marketGaps: findMarketGaps(marketMap),

    // Saturation zones: things EVERYONE is doing (avoid or differentiate)
    saturationZones: findSaturationZones(marketMap),

    // Underexploited opportunities: some brands use, most don't
    underexploited: findUnderexploited(marketMap),

    // Priority matrix: ranked opportunities combining gap size + potential
    priorityMatrix: buildPriorityMatrix(marketMap, brandReports),
  };

  // Brand-specific gaps (if a focus brand is specified)
  if (focusBrand) {
    const focusReport = brandReports.find(
      (r) => r.brand.name.toLowerCase() === focusBrand.toLowerCase()
    );
    if (focusReport) {
      doc.brandGaps = findBrandSpecificGaps(focusReport, marketMap, brandReports);
    }
  }

  // Enrich with Claude strategic recommendations if available
  if (isClaudeAvailable()) {
    try {
      const recommendations = await generateStrategicRecommendations(marketMap, brandReports, focusBrand);
      doc.strategicRecommendations = recommendations;
    } catch {
      // Claude failed — heuristic analysis already in place
    }
  }

  return doc;
}

/**
 * Find dimensions where NO brand has any presence.
 */
function findMarketGaps(marketMap) {
  const gaps = { hooks: [], angles: [], emotions: [], formats: [], offers: [], ctas: [] };

  for (const [dimension, matrix] of Object.entries(marketMap.matrices)) {
    for (const row of matrix) {
      if (row.coverage === 0) {
        gaps[dimension].push({
          dimension: row.dimension,
          opportunity: 'wide_open',
          description: `No brand in the market is using "${row.dimension}" — first-mover advantage available`,
        });
      }
    }
  }

  return gaps;
}

/**
 * Find dimensions where 60%+ of brands compete.
 */
function findSaturationZones(marketMap) {
  const zones = { hooks: [], angles: [], emotions: [], formats: [] };

  for (const [dimension, classification] of Object.entries(marketMap.saturation)) {
    if (dimension === 'overall') continue;
    if (!classification.saturated) continue;
    for (const item of classification.saturated) {
      zones[dimension]?.push({
        dimension: item.dimension,
        coveragePercent: item.coveragePercent,
        risk: 'high_competition',
        recommendation: `${item.coveragePercent}% of brands use "${item.dimension}" — differentiate or avoid`,
      });
    }
  }

  return zones;
}

/**
 * Find dimensions used by 1-2 brands (proof of concept, but underexploited).
 */
function findUnderexploited(marketMap) {
  const opportunities = [];

  for (const [dimension, matrix] of Object.entries(marketMap.matrices)) {
    for (const row of matrix) {
      // Used by at least 1 brand but less than 30% of market
      if (row.coverage > 0 && row.coveragePercent < 30) {
        const users = Object.entries(row.brands)
          .filter(([, count]) => count > 0)
          .map(([name]) => name);

        opportunities.push({
          category: dimension,
          dimension: row.dimension,
          usedBy: users,
          coveragePercent: row.coveragePercent,
          totalAds: row.total,
          opportunity: 'underexploited',
          description: `Only ${users.length} brand(s) using "${row.dimension}" — proven but uncrowded`,
        });
      }
    }
  }

  // Sort by fewest users (biggest gaps first)
  opportunities.sort((a, b) => a.coveragePercent - b.coveragePercent);
  return opportunities;
}

/**
 * Build a priority matrix combining gap analysis with potential impact.
 *
 * Score = gap_size (inverse of coverage) x relevance_signal
 * Relevance signal: if ANY brand is successfully using it, it's validated.
 */
function buildPriorityMatrix(marketMap, brandReports) {
  const entries = [];

  const dimensionSets = [
    { name: 'hooks', matrix: marketMap.matrices.hooks, weight: 3 },
    { name: 'angles', matrix: marketMap.matrices.angles, weight: 4 },
    { name: 'emotions', matrix: marketMap.matrices.emotions, weight: 3 },
    { name: 'formats', matrix: marketMap.matrices.formats, weight: 2 },
    { name: 'offers', matrix: marketMap.matrices.offers, weight: 2 },
    { name: 'ctas', matrix: marketMap.matrices.ctas, weight: 1 },
  ];

  for (const { name, matrix, weight } of dimensionSets) {
    for (const row of matrix) {
      // Gap score: 100 = nobody uses it, 0 = everyone uses it
      const gapScore = 100 - row.coveragePercent;

      // Validation score: higher if someone IS using it successfully (total > 0)
      const validationBonus = row.total > 0 ? 20 : 0;

      // Low-competition bonus: 1 user means validated but uncrowded
      const lowCompBonus = (row.coverage === 1 && row.total >= 2) ? 15 : 0;

      const score = Math.round((gapScore + validationBonus + lowCompBonus) * (weight / 3));

      // Skip fully saturated dimensions (everyone uses them)
      if (row.coveragePercent >= 80) continue;

      entries.push({
        category: name,
        dimension: row.dimension,
        gapScore,
        coveragePercent: row.coveragePercent,
        brandsUsing: row.coverage,
        totalAds: row.total,
        priorityScore: score,
        tier: score >= 80 ? 'P1_HIGH' :
          score >= 50 ? 'P2_MEDIUM' :
            score >= 25 ? 'P3_LOW' : 'P4_MONITOR',
      });
    }
  }

  // Sort by priority score descending
  entries.sort((a, b) => b.priorityScore - a.priorityScore);
  return entries;
}

/**
 * Find gaps specific to a focus brand — dimensions competitors use but this brand doesn't.
 */
function findBrandSpecificGaps(focusReport, marketMap, allReports) {
  const gaps = [];
  const brandName = focusReport.brand.name;

  const dimensionChecks = [
    { name: 'hooks', getDist: (r) => r.analysis?.hookDistribution || {} },
    { name: 'angles', getDist: (r) => r.analysis?.angleDistribution || {} },
    { name: 'emotions', getDist: (r) => r.analysis?.emotionDistribution || {} },
    { name: 'formats', getDist: (r) => r.analysis?.formatDistribution || {} },
    { name: 'offers', getDist: (r) => r.analysis?.offerTypes || {} },
  ];

  for (const { name, getDist } of dimensionChecks) {
    const focusDist = getDist(focusReport);

    for (const row of marketMap.matrices[name]) {
      const focusCount = focusDist[row.dimension] || 0;
      const competitorCount = row.coverage - (focusCount > 0 ? 1 : 0);

      // Gap: focus brand doesn't use it, but competitors do
      if (focusCount === 0 && competitorCount > 0) {
        const competitorNames = Object.entries(row.brands)
          .filter(([n, c]) => c > 0 && n !== brandName)
          .map(([n]) => n);

        gaps.push({
          category: name,
          dimension: row.dimension,
          competitorsUsing: competitorNames,
          competitorCount,
          totalCompetitorAds: row.total,
          recommendation: competitorCount >= 2
            ? `Multiple competitors use "${row.dimension}" — consider testing`
            : `Competitor ${competitorNames[0]} uses "${row.dimension}" — monitor or test`,
        });
      }
    }
  }

  // Sort: most competitors using it = biggest blind spot
  gaps.sort((a, b) => b.competitorCount - a.competitorCount);
  return gaps;
}

/**
 * Save a Loophole Document to disk.
 */
export function saveLoopholeDoc(doc, keyword) {
  ensureDataDirs();
  const kwSlug = (keyword || 'unknown').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 30);
  const ts = new Date().toISOString().slice(0, 10);
  const brandSuffix = doc.meta.focusBrand
    ? `_${doc.meta.focusBrand.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 20)}`
    : '';
  const filename = `loopholes_${kwSlug}${brandSuffix}_${ts}.json`;
  const filepath = join(config.paths.reports, filename);
  writeFileSync(filepath, JSON.stringify(doc, null, 2), 'utf-8');
  return filepath;
}

/**
 * Format Loophole Document as human-readable terminal output.
 */
export function formatLoopholeDocText(doc) {
  const lines = [];

  lines.push(`${'═'.repeat(70)}`);
  lines.push(`  MASTER LOOPHOLE DOCUMENT: "${doc.meta.keyword}"`);
  lines.push(`  ${doc.meta.brandsCompared} brands analyzed${doc.meta.focusBrand ? ` | Focus: ${doc.meta.focusBrand}` : ''}`);
  lines.push(`${'═'.repeat(70)}`);
  lines.push('');

  // Claude strategic narrative (if available)
  if (doc.strategicRecommendations?.marketNarrative) {
    lines.push(`${'─'.repeat(70)}`);
    lines.push('  EXECUTIVE SUMMARY (Claude Analysis)');
    lines.push(`${'─'.repeat(70)}`);
    wrapText(doc.strategicRecommendations.marketNarrative, 66).forEach((l) => lines.push(`  ${l}`));
    lines.push('');
  }

  // Market-wide gaps
  lines.push(`${'─'.repeat(70)}`);
  lines.push('  MARKET GAPS — Nobody Is Doing This');
  lines.push(`${'─'.repeat(70)}`);

  const allGaps = Object.entries(doc.marketGaps);
  const hasGaps = allGaps.some(([, items]) => items.length > 0);

  if (hasGaps) {
    for (const [category, items] of allGaps) {
      if (items.length === 0) continue;
      lines.push(`\n  ${category.toUpperCase()}:`);
      for (const item of items) {
        lines.push(`    [OPEN] ${item.dimension}`);
      }
    }
  } else {
    lines.push('  No completely empty dimensions found — market has broad coverage.');
  }
  lines.push('');

  // Saturation zones
  lines.push(`${'─'.repeat(70)}`);
  lines.push('  SATURATION ZONES — Avoid or Differentiate');
  lines.push(`${'─'.repeat(70)}`);

  const allZones = Object.entries(doc.saturationZones);
  const hasZones = allZones.some(([, items]) => items.length > 0);

  if (hasZones) {
    for (const [category, items] of allZones) {
      if (items.length === 0) continue;
      lines.push(`\n  ${category.toUpperCase()}:`);
      for (const item of items) {
        lines.push(`    [${item.coveragePercent}%] ${item.dimension} — ${item.recommendation}`);
      }
    }
  } else {
    lines.push('  No heavily saturated zones detected — market is fragmented.');
  }
  lines.push('');

  // Claude top opportunities (if available)
  if (doc.strategicRecommendations?.topOpportunities?.length) {
    lines.push(`${'─'.repeat(70)}`);
    lines.push('  TOP OPPORTUNITIES (Claude Analysis)');
    lines.push(`${'─'.repeat(70)}`);
    for (const opp of doc.strategicRecommendations.topOpportunities.slice(0, 5)) {
      lines.push(`\n  [${(opp.expectedImpact || 'N/A').toUpperCase()}] ${opp.gap}`);
      lines.push(`    Strategy: ${opp.exploitationStrategy || ''}`);
      lines.push(`    Difficulty: ${opp.implementationDifficulty || 'N/A'}`);
    }
    lines.push('');
  }

  // Underexploited opportunities
  lines.push(`${'─'.repeat(70)}`);
  lines.push('  UNDEREXPLOITED — Proven but Uncrowded');
  lines.push(`${'─'.repeat(70)}`);

  if (doc.underexploited.length > 0) {
    for (const item of doc.underexploited.slice(0, 15)) {
      lines.push(`  [${item.category}] ${item.dimension} — used by ${item.usedBy.join(', ')} (${item.totalAds} ads)`);
    }
    if (doc.underexploited.length > 15) {
      lines.push(`  ... +${doc.underexploited.length - 15} more`);
    }
  } else {
    lines.push('  No underexploited opportunities detected.');
  }
  lines.push('');

  // Claude contrarian plays (if available)
  if (doc.strategicRecommendations?.contrarianPlays?.length) {
    lines.push(`${'─'.repeat(70)}`);
    lines.push('  CONTRARIAN PLAYS (Claude Analysis)');
    lines.push(`${'─'.repeat(70)}`);
    for (const play of doc.strategicRecommendations.contrarianPlays.slice(0, 3)) {
      lines.push(`\n  CONVENTIONAL: ${play.conventionalWisdom || ''}`);
      lines.push(`  CONTRARIAN:   ${play.contrarianApproach || ''}`);
      lines.push(`  UPSIDE:       ${play.upside || ''}`);
    }
    lines.push('');
  }

  // Priority matrix (top 15)
  lines.push(`${'─'.repeat(70)}`);
  lines.push('  PRIORITY MATRIX — Ranked Opportunities');
  lines.push(`${'─'.repeat(70)}`);
  lines.push('  #   TIER        CATEGORY   DIMENSION          GAP   USED  SCORE');
  lines.push(`  ${'─'.repeat(65)}`);

  const topPriorities = doc.priorityMatrix.slice(0, 20);
  for (let i = 0; i < topPriorities.length; i++) {
    const p = topPriorities[i];
    const num = String(i + 1).padStart(2);
    const tier = p.tier.padEnd(10);
    const cat = p.category.padEnd(10);
    const dim = p.dimension.padEnd(18);
    const gap = `${p.gapScore}%`.padStart(5);
    const used = `${p.brandsUsing}/${doc.meta.brandsCompared}`.padStart(5);
    const score = String(p.priorityScore).padStart(5);
    lines.push(`  ${num}. ${tier} ${cat} ${dim} ${gap} ${used} ${score}`);
  }
  lines.push('');

  // Claude immediate actions (if available)
  if (doc.strategicRecommendations?.immediateActions?.length) {
    lines.push(`${'─'.repeat(70)}`);
    lines.push('  IMMEDIATE ACTIONS (Claude Analysis)');
    lines.push(`${'─'.repeat(70)}`);
    for (const action of doc.strategicRecommendations.immediateActions.slice(0, 5)) {
      lines.push(`  [${(action.timeline || 'N/A').toUpperCase()}] ${action.action}`);
      lines.push(`    Expected: ${action.expectedOutcome || ''}`);
    }
    lines.push('');
  }

  // Brand-specific gaps (if focus brand)
  if (doc.brandGaps) {
    lines.push(`${'─'.repeat(70)}`);
    lines.push(`  BRAND GAPS — What "${doc.meta.focusBrand}" Is Missing`);
    lines.push(`${'─'.repeat(70)}`);

    if (doc.brandGaps.length > 0) {
      for (const gap of doc.brandGaps.slice(0, 15)) {
        lines.push(`  [${gap.category}] ${gap.dimension} — ${gap.recommendation}`);
      }
      if (doc.brandGaps.length > 15) {
        lines.push(`  ... +${doc.brandGaps.length - 15} more`);
      }
    } else {
      lines.push(`  No blind spots found — ${doc.meta.focusBrand} covers all dimensions competitors use.`);
    }
    lines.push('');
  }

  // Claude brand-specific actions (if available)
  if (doc.strategicRecommendations?.brandSpecificActions?.length) {
    lines.push(`${'─'.repeat(70)}`);
    lines.push(`  ACTION PLAN FOR "${doc.meta.focusBrand}" (Claude Analysis)`);
    lines.push(`${'─'.repeat(70)}`);
    for (const action of doc.strategicRecommendations.brandSpecificActions.slice(0, 5)) {
      lines.push(`  [${action.priority || 'N/A'}] ${action.action}`);
      lines.push(`    Rationale: ${action.rationale || ''}`);
      lines.push(`    Expected: ${action.expectedOutcome || ''}`);
    }
    lines.push('');
  }

  lines.push(`${'═'.repeat(70)}`);

  return lines.join('\n');
}

/**
 * Wrap text to a given line width.
 */
function wrapText(text, width) {
  const words = text.split(/\s+/);
  const lines = [];
  let current = '';

  for (const word of words) {
    if (current.length + word.length + 1 > width) {
      lines.push(current);
      current = word;
    } else {
      current = current ? `${current} ${word}` : word;
    }
  }
  if (current) lines.push(current);
  return lines;
}
