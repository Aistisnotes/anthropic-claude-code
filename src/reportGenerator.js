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

function wrapText(text, indent, maxWidth) {
  const words = text.split(/\s+/);
  const lines = [];
  let current = indent;
  for (const word of words) {
    if (current.length + word.length + 1 > maxWidth && current.length > indent.length) {
      lines.push(current);
      current = indent + word;
    } else {
      current += (current.length === indent.length ? '' : ' ') + word;
    }
  }
  if (current.length > indent.length) lines.push(current);
  return lines.join('\n');
}

function generateReport(brandName, filterSummary, patterns, extractions) {
  const lines = [];
  const hr = '='.repeat(78);
  const hr2 = '-'.repeat(78);

  lines.push(hr);
  lines.push(`  DR FRAMEWORK ANALYSIS: ${brandName.toUpperCase()}`);
  lines.push(hr);
  lines.push('');

  // ===== 1. FILTER RESULTS =====
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

  // ===== 2. TARGET CUSTOMER (Synthesized Avatars) =====
  lines.push('2. TARGET CUSTOMER (Synthesized Avatars)');
  lines.push(hr2);
  lines.push('');
  lines.push('  Per-ad avatar:');
  for (const a of patterns.avatars) {
    lines.push(`    ${a.id}: ${a.avatar}`);
  }
  lines.push('');
  lines.push('  Cross-ad demographic patterns:');
  if (patterns.demographicFreq.length > 0) {
    for (const [demo, count] of patterns.demographicFreq) {
      const pct = Math.round((count / patterns.totalAds) * 100);
      lines.push(`    ${demo.padEnd(28)} ${count}/${patterns.totalAds} ads (${pct}%)`);
    }
  } else {
    lines.push('    No demographic signals detected.');
  }
  lines.push('');
  lines.push('  Cross-ad psychographic patterns:');
  if (patterns.psychographicFreq.length > 0) {
    for (const [psych, count] of patterns.psychographicFreq) {
      const pct = Math.round((count / patterns.totalAds) * 100);
      lines.push(`    ${count}/${patterns.totalAds} (${pct}%): ${psych}`);
    }
  } else {
    lines.push('    No psychographic signals detected.');
  }
  lines.push('');

  // ===== 3. MASS DESIRE =====
  lines.push('3. MASS DESIRE');
  lines.push(hr2);
  if (patterns.primaryDesire) {
    lines.push(`  PRIMARY: "${patterns.primaryDesire.desire}"`);
    lines.push(`           ${patterns.primaryDesire.count}/${patterns.totalAds} ads (${patterns.primaryDesire.pct}%)`);
    lines.push('');
    if (patterns.allDesires.length > 1) {
      lines.push('  Secondary desires:');
      for (const d of patterns.allDesires.slice(1)) {
        lines.push(`    ${d.desire.padEnd(42)} ${d.count}/${patterns.totalAds} (${d.pct}%)`);
      }
    }
  } else {
    lines.push('  No mass desire signals detected.');
  }
  lines.push('');

  // ===== 4. PAIN POINTS & SYMPTOMS (by category) =====
  lines.push('4. PAIN POINTS & SYMPTOMS (by category)');
  lines.push(hr2);
  if (patterns.painCategories.length === 0) {
    lines.push('  No pain point signals detected.');
  } else {
    for (const cat of patterns.painCategories) {
      const bar = '#'.repeat(Math.round(cat.pct / 5));
      lines.push(`  ${cat.label.padEnd(40)} ${cat.adsWithCategory}/${patterns.totalAds} ads (${cat.pct}%)  ${bar}`);
      if (cat.topMatches.length > 0) {
        const matchStr = cat.topMatches.map(([m, c]) => `${m} (${c}x)`).join(', ');
        lines.push(`    Signals: ${matchStr}`);
      }
    }
  }
  lines.push('');

  // ===== 5. ROOT CAUSE (Villain Narrative) =====
  lines.push('5. ROOT CAUSE (Villain Narrative)');
  lines.push(hr2);
  lines.push(`  Ads with root cause narrative: ${patterns.rootCause.adsWithRootCause}/${patterns.totalAds} (${patterns.rootCause.pct}%)`);
  lines.push('');

  if (patterns.rootCause.villainTypes.length > 0) {
    lines.push('  Villain types:');
    for (const v of patterns.rootCause.villainTypes) {
      lines.push(`    ${v.label.padEnd(36)} ${v.count} ads`);
    }
    lines.push('');
  }

  if (patterns.rootCause.sentences.length > 0) {
    lines.push('  Actual villain sentences from ad copy:');
    const shown = new Set();
    for (const s of patterns.rootCause.sentences.slice(0, 10)) {
      const truncated = s.sentence.length > 120 ? s.sentence.slice(0, 117) + '...' : s.sentence;
      if (!shown.has(truncated)) {
        lines.push(`    [${s.adId}] "${truncated}"`);
        shown.add(truncated);
      }
    }
  }
  lines.push('');

  // ===== 6. MECHANISM (Causal Chain Analysis) =====
  lines.push('6. MECHANISM (Causal Chain Analysis)');
  lines.push(hr2);
  lines.push(`  Ads with mechanism: ${patterns.mechanism.adsWithMechanism}/${patterns.totalAds} (${patterns.mechanism.pct}%)`);
  lines.push(`  Ads with COMPLETE chain (all 5 steps): ${patterns.mechanism.fullChainCount}/${patterns.totalAds}`);
  lines.push('');

  if (patterns.mechanism.commonMissingSteps.length > 0) {
    lines.push('  Most commonly missing chain steps:');
    for (const s of patterns.mechanism.commonMissingSteps) {
      lines.push(`    "${s.step}" — missing in ${s.count}/${patterns.totalAds} ads`);
    }
    lines.push('');
  }

  // Show best chain example
  if (patterns.mechanism.bestChainAd) {
    const bestAd = extractions.find(e => e.id === patterns.mechanism.bestChainAd);
    if (bestAd && bestAd.mechanism.chain.length > 0) {
      lines.push(`  Best chain example (${bestAd.id} - "${bestAd.name}"):`);
      for (const step of bestAd.mechanism.chain) {
        lines.push(`    Step ${step.step} — ${step.label}:`);
        for (const sent of step.sentences.slice(0, 2)) {
          const truncated = sent.length > 140 ? sent.slice(0, 137) + '...' : sent;
          lines.push(wrapText(`"${truncated}"`, '      ', 78));
        }
      }
    }
  }
  lines.push('');

  // ===== 7. PRODUCT DELIVERY MECHANISM =====
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

  // ===== 8. MARKET SOPHISTICATION =====
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

  // ===== 9. CUSTOMER AWARENESS STAGE =====
  lines.push('9. CUSTOMER AWARENESS STAGE');
  lines.push(hr2);
  const aw = patterns.awareness;
  if (aw.dominant) {
    if (aw.isSplit) {
      lines.push('  WARNING: No dominant awareness stage (60%+ threshold not met)');
      lines.push('');
      lines.push('  Stage distribution:');
      for (const a of aw.breakdown) {
        const label = STAGE_LABELS[a.stage] || a.stage;
        const bar = '#'.repeat(Math.round(a.pct / 5));
        lines.push(`    ${label.padEnd(20)} ${a.count}/${patterns.totalAds} (${a.pct}%)  ${bar}`);
      }
      lines.push('');
      lines.push('  This brand splits awareness targeting across multiple stages.');
      lines.push('  Recommend consolidating around 1-2 primary stages for stronger');
      lines.push('  creative consistency.');
    } else {
      const label = STAGE_LABELS[aw.dominant.stage] || aw.dominant.stage;
      lines.push(`  DOMINANT: ${label} (${aw.dominant.count}/${patterns.totalAds} ads, ${aw.dominant.pct}%)`);
      lines.push('');
      if (aw.breakdown.length > 1) {
        lines.push('  Full breakdown:');
        for (const a of aw.breakdown) {
          const stageLabel = STAGE_LABELS[a.stage] || a.stage;
          lines.push(`    ${stageLabel.padEnd(20)} ${a.count}/${patterns.totalAds} (${a.pct}%)`);
        }
      }
    }
  } else {
    lines.push('  No awareness signals detected.');
  }
  lines.push('');

  // ===== 10. BIG IDEA / CREATIVE STYLES =====
  lines.push('10. BIG IDEA');
  lines.push(hr2);
  lines.push('  Per-ad concept synthesis:');
  for (const e of extractions) {
    lines.push(`    ${e.id}: ${e.bigIdea.concept}`);
    lines.push(`           Style: ${e.bigIdea.primaryStyle}`);
  }
  lines.push('');
  if (patterns.topCreativeStyles.length > 0) {
    lines.push('  Creative style distribution:');
    for (const s of patterns.topCreativeStyles) {
      const bar = '#'.repeat(Math.round(s.pct / 5));
      lines.push(`    ${s.style.padEnd(36)} ${s.count}/${patterns.totalAds} (${s.pct}%)  ${bar}`);
    }
  }
  lines.push('');

  // ===== 11. STRATEGIC GAPS / LOOPHOLES =====
  lines.push('11. STRATEGIC GAPS / LOOPHOLES');
  lines.push(hr2);
  const gapKeys = Object.keys(patterns.strategicGaps);
  if (gapKeys.length === 0) {
    lines.push('  No systematic gaps detected by ad type.');
  } else {
    for (const [adType, data] of Object.entries(patterns.strategicGaps)) {
      lines.push(`  ${adType.toUpperCase()} ADS (${data.totalAds} total) are systematically missing:`);
      for (const g of data.gaps) {
        lines.push(`    - ${g.element}: only ${g.present}/${g.total} ${adType} ads (${g.pct}%) include it`);
      }
      lines.push('');
    }
    lines.push('  This brand is sleeping on DR fundamentals in these formats.');
    lines.push('  Adding root cause + mechanism to underperforming ad types');
    lines.push('  would likely improve conversion by strengthening the');
    lines.push('  persuasion architecture (pain -> villain -> mechanism -> product).');
  }
  lines.push('');

  // ===== 12. FRAMEWORK COMPLETENESS (QA) =====
  lines.push('12. FRAMEWORK COMPLETENESS (QA)');
  lines.push(hr2);
  lines.push('  Elements: Target Customer | Mass Desire | Pain Points | Root Cause | Mechanism | Product Delivery');
  lines.push('');
  for (const c of patterns.completeness) {
    const bar = '#'.repeat(c.score) + '.'.repeat(c.outOf - c.score);
    lines.push(`  ${c.id.padEnd(12)} ${bar} ${c.score}/${c.outOf} (${c.pct}%)  "${c.name}"`);
    if (c.missing.length > 0) {
      lines.push(`               MISSING: ${c.missing.join(', ')}`);
    }
  }
  lines.push('');

  // ===== 13. PER-AD MECHANISM CHAINS =====
  lines.push('13. PER-AD MECHANISM CHAINS');
  lines.push(hr2);
  for (const e of extractions) {
    lines.push(`  ${e.id} - "${e.name}" (${e.type}, ${e.wordCount} words)`);
    if (e.mechanism.chain.length === 0) {
      lines.push('    NO MECHANISM CHAIN — ad skips persuasion architecture entirely');
    } else {
      for (const step of e.mechanism.chain) {
        lines.push(`    Step ${step.step} — ${step.label}:`);
        for (const sent of step.sentences.slice(0, 2)) {
          const truncated = sent.length > 120 ? sent.slice(0, 117) + '...' : sent;
          lines.push(wrapText(`"${truncated}"`, '      ', 78));
        }
      }
      if (e.mechanism.missingSteps.length > 0) {
        lines.push(`    MISSING: ${e.mechanism.missingSteps.join(', ')}`);
      }
    }
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
