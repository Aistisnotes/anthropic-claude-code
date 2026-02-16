'use strict';

const STAGE_LABELS = {
  unaware: 'Unaware',
  problem_aware: 'Problem-Aware',
  solution_aware: 'Solution-Aware',
  product_aware: 'Product-Aware',
  most_aware: 'Most Aware',
  unknown: 'Unknown',
};

const STRATEGY_LABELS = {
  new_mechanism: 'New Mechanism',
  new_information: 'New Information',
  new_identity: 'New Identity',
  none: 'None detected',
};

function generateReport(brandName, filterSummary, patterns, extractions) {
  const lines = [];
  const hr = '='.repeat(74);
  const hr2 = '-'.repeat(74);

  lines.push(hr);
  lines.push(`  DR FRAMEWORK ANALYSIS: ${brandName.toUpperCase()}`);
  lines.push(hr);
  lines.push('');

  // ---- 1. FILTER RESULTS ----
  lines.push('1. FILTER RESULTS');
  lines.push(hr2);
  lines.push(`  Total ads ingested:  ${filterSummary.total}`);
  lines.push(`  Ads kept:            ${filterSummary.kept} (${Math.round((filterSummary.kept / filterSummary.total) * 100)}%)`);
  lines.push(`  Ads skipped:         ${filterSummary.skipped}`);
  if (filterSummary.skippedReasons.length > 0) {
    for (const r of filterSummary.skippedReasons) {
      lines.push(`    - ${r.id} (${r.type}): ${r.reason}`);
    }
  }
  lines.push('');

  // ---- 2. TARGET CUSTOMER ----
  lines.push('2. TARGET CUSTOMER');
  lines.push(hr2);
  if (patterns.topCustomerSegments.length === 0) {
    lines.push('  No target customer signals detected.');
  } else {
    for (const s of patterns.topCustomerSegments) {
      const bar = '#'.repeat(Math.round(s.pct / 5));
      lines.push(`  ${s.segment.padEnd(30)} ${String(s.count).padStart(2)}/${patterns.totalAds} ads (${String(s.pct).padStart(3)}%)  ${bar}`);
    }
  }
  lines.push('');

  // ---- 3. MASS DESIRE ----
  lines.push('3. MASS DESIRE');
  lines.push(hr2);
  if (patterns.topDesires.length === 0) {
    lines.push('  No mass desire signals detected.');
  } else {
    for (const d of patterns.topDesires) {
      const bar = '#'.repeat(Math.round(d.pct / 5));
      lines.push(`  ${d.desire.padEnd(42)} ${String(d.count).padStart(2)}/${patterns.totalAds} (${String(d.pct).padStart(3)}%)  ${bar}`);
    }
  }
  lines.push('');

  // ---- 4. PAIN POINTS & SYMPTOMS ----
  lines.push('4. PAIN POINTS & SYMPTOMS');
  lines.push(hr2);
  if (patterns.topPainPoints.length === 0) {
    lines.push('  No pain point signals detected.');
  } else {
    for (const p of patterns.topPainPoints) {
      lines.push(`  [${p.count}x] ${p.pain}`);
    }
  }
  lines.push('');

  // ---- 5. ROOT CAUSE ----
  lines.push('5. ROOT CAUSE');
  lines.push(hr2);
  lines.push(`  Ads with root cause signals: ${patterns.rootCause.adsWithRootCause}/${patterns.totalAds} (${patterns.rootCause.pct}%)`);
  if (patterns.rootCause.topSignals.length > 0) {
    lines.push('  Top villain / root cause signals:');
    for (const s of patterns.rootCause.topSignals) {
      lines.push(`    [${s.count}x] ${s.signal}`);
    }
  }
  lines.push('');

  // ---- 6. MECHANISM (The "New Mechanism") ----
  lines.push('6. MECHANISM (The "New Mechanism")');
  lines.push(hr2);
  lines.push(`  Ads with mechanism signals: ${patterns.mechanism.adsWithMechanism}/${patterns.totalAds} (${patterns.mechanism.pct}%)`);
  if (patterns.mechanism.topSignals.length > 0) {
    lines.push('  Top mechanism signals:');
    for (const s of patterns.mechanism.topSignals) {
      lines.push(`    [${s.count}x] ${s.signal}`);
    }
  }
  lines.push('');

  // ---- 7. PRODUCT DELIVERY MECHANISM ----
  lines.push('7. PRODUCT DELIVERY MECHANISM');
  lines.push(hr2);
  if (patterns.topDeliverySignals.length === 0) {
    lines.push('  No product delivery signals detected.');
  } else {
    for (const s of patterns.topDeliverySignals) {
      lines.push(`  [${s.count}x] ${s.signal}`);
    }
  }
  lines.push('');

  // ---- 8. MARKET SOPHISTICATION ----
  lines.push('8. MARKET SOPHISTICATION STRATEGY');
  lines.push(hr2);
  if (patterns.sophisticationBreakdown.length === 0) {
    lines.push('  No sophistication signals detected.');
  } else {
    for (const s of patterns.sophisticationBreakdown) {
      const label = STRATEGY_LABELS[s.strategy] || s.strategy;
      const bar = '#'.repeat(Math.round(s.pct / 5));
      lines.push(`  ${label.padEnd(20)} ${String(s.count).padStart(2)}/${patterns.totalAds} ads (${String(s.pct).padStart(3)}%)  ${bar}`);
    }
  }
  lines.push('');

  // ---- 9. CUSTOMER AWARENESS STAGE ----
  lines.push('9. CUSTOMER AWARENESS STAGE');
  lines.push(hr2);
  if (patterns.awarenessBreakdown.length === 0) {
    lines.push('  No awareness signals detected.');
  } else {
    for (const a of patterns.awarenessBreakdown) {
      const label = STAGE_LABELS[a.stage] || a.stage;
      const bar = '#'.repeat(Math.round(a.pct / 5));
      lines.push(`  ${label.padEnd(20)} ${String(a.count).padStart(2)}/${patterns.totalAds} ads (${String(a.pct).padStart(3)}%)  ${bar}`);
    }
  }
  lines.push('');

  // ---- 10. BIG IDEA / CREATIVE ANGLES ----
  lines.push('10. BIG IDEA / CREATIVE ANGLES');
  lines.push(hr2);
  if (patterns.topCreativeAngles.length === 0) {
    lines.push('  No creative angle signals detected.');
  } else {
    for (const a of patterns.topCreativeAngles) {
      const bar = '#'.repeat(Math.round(a.pct / 5));
      lines.push(`  ${a.angle.padEnd(36)} ${String(a.count).padStart(2)}/${patterns.totalAds} (${String(a.pct).padStart(3)}%)  ${bar}`);
    }
  }
  lines.push('');

  // ---- 11. FRAMEWORK COMPLETENESS (QA) ----
  lines.push('11. FRAMEWORK COMPLETENESS (QA)');
  lines.push(hr2);
  lines.push('  Elements: Target Customer | Mass Desire | Pain Points | Root Cause | Mechanism | Product Delivery');
  lines.push('');
  for (const c of patterns.completeness) {
    const bar = '#'.repeat(c.score) + '.'.repeat(c.outOf - c.score);
    lines.push(`  ${c.id.padEnd(12)} ${bar} ${c.score}/${c.outOf} (${c.pct}%)  "${c.name}"`);
  }
  lines.push('');

  // ---- 12. PER-AD FRAMEWORK DETAIL ----
  lines.push('12. PER-AD FRAMEWORK DETAIL');
  lines.push(hr2);
  for (const e of extractions) {
    lines.push(`  ${e.id} - "${e.name}" (${e.type}, ${e.wordCount} words)`);
    lines.push('');
    lines.push(`    Target Customer:    ${e.targetCustomer.join(', ') || 'none detected'}`);
    lines.push(`    Mass Desire:        ${e.massDesire.join(', ') || 'none detected'}`);
    lines.push(`    Pain Points:        ${e.painPoints.join(' | ') || 'none detected'}`);
    lines.push('');
    lines.push(`    Root Cause:         ${e.rootCause.present ? 'YES' : 'NO'}`);
    if (e.rootCause.signals.length > 0) {
      lines.push(`      Signals:          ${e.rootCause.signals.join(' | ')}`);
    }
    lines.push('');
    lines.push(`    Mechanism:          ${e.mechanism.present ? 'YES' : 'NO'}`);
    if (e.mechanism.signals.length > 0) {
      lines.push(`      Signals:          ${e.mechanism.signals.join(' | ')}`);
    }
    lines.push('');
    lines.push(`    Product Delivery:   ${e.productDelivery.present ? 'YES' : 'NO'}`);
    if (e.productDelivery.signals.length > 0) {
      lines.push(`      Signals:          ${e.productDelivery.signals.join(' | ')}`);
    }
    lines.push('');
    const sophLabel = STRATEGY_LABELS[e.sophistication.primaryStrategy] || e.sophistication.primaryStrategy;
    lines.push(`    Sophistication:     Stage ${e.sophistication.likelyStage} / ${sophLabel}`);
    const awLabel = STAGE_LABELS[e.awarenessStage.primary] || e.awarenessStage.primary;
    lines.push(`    Awareness Stage:    ${awLabel}`);
    lines.push(`    Creative Angles:    ${e.bigIdea.creativeAngles.join(', ') || 'none detected'}`);
    lines.push('');
    lines.push(hr2);
  }

  lines.push('');
  lines.push(hr);
  lines.push('  END OF REPORT');
  lines.push(hr);

  return lines.join('\n');
}

module.exports = { generateReport };
