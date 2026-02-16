'use strict';

/**
 * Generate a formatted text report from pattern analysis results.
 */
function generateReport(brandName, filterSummary, patterns, extractions) {
  const lines = [];
  const hr = '='.repeat(70);
  const hr2 = '-'.repeat(70);

  lines.push(hr);
  lines.push(`  AD ANALYSIS REPORT: ${brandName.toUpperCase()}`);
  lines.push(hr);
  lines.push('');

  // --- Filter summary ---
  lines.push('1. FILTER RESULTS');
  lines.push(hr2);
  lines.push(`  Total ads ingested:   ${filterSummary.total}`);
  lines.push(`  Ads kept:             ${filterSummary.kept} (${Math.round((filterSummary.kept / filterSummary.total) * 100)}%)`);
  lines.push(`  Ads skipped:          ${filterSummary.skipped}`);
  if (filterSummary.skippedReasons.length > 0) {
    lines.push('  Skip reasons:');
    for (const r of filterSummary.skippedReasons) {
      lines.push(`    - ${r.id} (${r.type}): ${r.reason}`);
    }
  }
  lines.push('');

  // --- Ad type breakdown ---
  lines.push('2. AD TYPE BREAKDOWN');
  lines.push(hr2);
  for (const [type, count] of Object.entries(patterns.byType)) {
    lines.push(`  ${type.padEnd(8)} ${count} ads (${Math.round((count / patterns.totalAds) * 100)}%)`);
  }
  lines.push('');

  // --- Word count stats ---
  lines.push('3. COPY LENGTH');
  lines.push(hr2);
  lines.push(`  Average:  ${patterns.wordStats.avg} words`);
  lines.push(`  Range:    ${patterns.wordStats.min} – ${patterns.wordStats.max} words`);
  lines.push('');
  lines.push('  Per ad:');
  for (const e of extractions) {
    lines.push(`    ${e.id.padEnd(12)} ${String(e.wordCount).padStart(5)} words  "${e.name}"`);
  }
  lines.push('');

  // --- Opening hooks ---
  lines.push('4. OPENING HOOKS');
  lines.push(hr2);
  for (const h of patterns.hooks) {
    const preview = h.hook.length > 80 ? h.hook.slice(0, 77) + '...' : h.hook;
    lines.push(`  ${h.id.padEnd(12)} "${preview}"`);
  }
  lines.push('');

  // --- Tone analysis ---
  lines.push('5. TONE & STYLE');
  lines.push(hr2);
  if (patterns.toneBreakdown.length === 0) {
    lines.push('  No tone markers detected.');
  } else {
    for (const t of patterns.toneBreakdown) {
      const bar = '#'.repeat(Math.round(t.pct / 5));
      lines.push(`  ${t.tone.padEnd(16)} ${String(t.adsWithTone).padStart(2)}/${patterns.totalAds} ads (${String(t.pct).padStart(3)}%)  ${bar}`);
    }
  }
  lines.push('');

  // --- CTAs ---
  lines.push('6. CALLS TO ACTION');
  lines.push(hr2);
  if (patterns.topCTAs.length === 0) {
    lines.push('  No CTAs detected.');
  } else {
    for (const c of patterns.topCTAs) {
      lines.push(`  [${c.count}x] "${c.cta}"`);
    }
  }
  lines.push('');

  // --- Offers ---
  lines.push('7. OFFERS & PROMOTIONS');
  lines.push(hr2);
  if (patterns.topOffers.length === 0) {
    lines.push('  No offers detected.');
  } else {
    for (const o of patterns.topOffers) {
      lines.push(`  [${o.count}x] ${o.offer}`);
    }
  }
  lines.push('');

  // --- Keywords ---
  lines.push('8. TOP KEYWORDS');
  lines.push(hr2);
  const kwCols = [];
  for (let i = 0; i < patterns.topKeywords.length; i += 2) {
    const left = `${patterns.topKeywords[i].word} (${patterns.topKeywords[i].count})`;
    const right = patterns.topKeywords[i + 1]
      ? `${patterns.topKeywords[i + 1].word} (${patterns.topKeywords[i + 1].count})`
      : '';
    kwCols.push(`  ${left.padEnd(30)} ${right}`);
  }
  lines.push(...kwCols);
  lines.push('');

  // --- Per-ad detail ---
  lines.push('9. PER-AD DETAIL');
  lines.push(hr2);
  for (const e of extractions) {
    lines.push(`  ${e.id} — "${e.name}" (${e.type}, ${e.wordCount} words)`);
    lines.push(`    Tone:    ${e.dominantTone.join(', ') || 'none detected'}`);
    lines.push(`    CTAs:    ${e.ctas.length > 0 ? e.ctas.join(' | ') : 'none'}`);
    lines.push(`    Offers:  ${e.offers.length > 0 ? e.offers.join(' | ') : 'none'}`);
    lines.push(`    Stats:   ${e.stats.length > 0 ? e.stats.join(' | ') : 'none'}`);
    const topKw = e.keywords.slice(0, 8).map(k => k.word).join(', ');
    lines.push(`    Keywords: ${topKw || 'none'}`);
    lines.push('');
  }

  lines.push(hr);
  lines.push('  END OF REPORT');
  lines.push(hr);

  return lines.join('\n');
}

module.exports = { generateReport };
