'use strict';

/**
 * Analyze patterns across DR framework extractions.
 * Aggregates framework-level trends, detects dominant stages,
 * and identifies strategic gaps by ad type.
 */
function analyzePatterns(extractions) {
  if (!extractions || extractions.length === 0) {
    return { totalAds: 0 };
  }

  const total = extractions.length;

  // --- Ad type breakdown ---
  const byType = {};
  for (const e of extractions) {
    byType[e.type] = (byType[e.type] || 0) + 1;
  }

  // --- Word count ---
  const wordCounts = extractions.map(e => e.wordCount);
  const avgWords = Math.round(wordCounts.reduce((a, b) => a + b, 0) / total);

  // --- Target Customer: per-ad avatars + cross-ad patterns ---
  const avatars = extractions.map(e => ({
    id: e.id, name: e.name, avatar: e.targetCustomer.avatar,
  }));
  const demoFreq = {};
  const psychoFreq = {};
  for (const e of extractions) {
    for (const d of e.targetCustomer.demographics) {
      demoFreq[d] = (demoFreq[d] || 0) + 1;
    }
    for (const p of e.targetCustomer.psychographics) {
      psychoFreq[p] = (psychoFreq[p] || 0) + 1;
    }
  }

  // --- Mass Desire: find ONE primary across all ads ---
  const desireCount = {};
  for (const e of extractions) {
    for (const d of e.massDesire.all) {
      desireCount[d.label] = (desireCount[d.label] || 0) + 1;
    }
  }
  const desireRanked = Object.entries(desireCount).sort((a, b) => b[1] - a[1]);
  const primaryDesire = desireRanked.length > 0 ? {
    desire: desireRanked[0][0],
    count: desireRanked[0][1],
    pct: Math.round((desireRanked[0][1] / total) * 100),
  } : null;
  const allDesires = desireRanked.map(([desire, count]) => ({
    desire, count, pct: Math.round((count / total) * 100),
  }));

  // --- Pain Points: by category across all ads ---
  const categoryCount = {};
  for (const e of extractions) {
    for (const [catKey, cat] of Object.entries(e.painPoints.byCategory)) {
      if (!categoryCount[catKey]) categoryCount[catKey] = { label: cat.label, count: 0, matches: {} };
      categoryCount[catKey].count++;
      for (const m of cat.matches) {
        categoryCount[catKey].matches[m] = (categoryCount[catKey].matches[m] || 0) + 1;
      }
    }
  }
  const painCategories = Object.entries(categoryCount)
    .sort((a, b) => b[1].count - a[1].count)
    .map(([key, val]) => ({
      category: key,
      label: val.label,
      adsWithCategory: val.count,
      pct: Math.round((val.count / total) * 100),
      topMatches: Object.entries(val.matches).sort((a, b) => b[1] - a[1]).slice(0, 5),
    }));

  // --- Root Cause: presence + villain type distribution ---
  const rootCauseCount = extractions.filter(e => e.rootCause.present).length;
  const villainTypeCount = {};
  for (const e of extractions) {
    if (e.rootCause.primaryVillain) {
      const key = e.rootCause.primaryVillain;
      const label = e.rootCause.villainLabel;
      if (!villainTypeCount[key]) villainTypeCount[key] = { label, count: 0 };
      villainTypeCount[key].count++;
    }
  }
  const villainTypes = Object.entries(villainTypeCount)
    .sort((a, b) => b[1].count - a[1].count)
    .map(([key, val]) => ({ type: key, label: val.label, count: val.count }));

  // Collect root cause sentences for the report
  const rootCauseSentences = [];
  for (const e of extractions) {
    for (const s of e.rootCause.sentences) {
      rootCauseSentences.push({ adId: e.id, sentence: s });
    }
  }

  // --- Mechanism: chain completeness analysis ---
  const mechanismCount = extractions.filter(e => e.mechanism.present).length;
  const fullChainCount = extractions.filter(e => e.mechanism.complete).length;
  const missingStepFreq = {};
  for (const e of extractions) {
    for (const step of e.mechanism.missingSteps) {
      missingStepFreq[step] = (missingStepFreq[step] || 0) + 1;
    }
  }
  const commonMissingSteps = Object.entries(missingStepFreq)
    .sort((a, b) => b[1] - a[1])
    .map(([step, count]) => ({ step, count }));

  // Find best chain example (most complete)
  const bestChainAd = extractions
    .filter(e => e.mechanism.present)
    .sort((a, b) => b.mechanism.stepsFound - a.mechanism.stepsFound)[0] || null;

  // --- Awareness: enforce 60% dominant threshold ---
  const awarenessCount = {};
  for (const e of extractions) {
    const stage = e.awarenessStage.primary;
    awarenessCount[stage] = (awarenessCount[stage] || 0) + 1;
  }
  const awarenessRanked = Object.entries(awarenessCount).sort((a, b) => b[1] - a[1]);
  const dominantAwareness = awarenessRanked.length > 0 ? {
    stage: awarenessRanked[0][0],
    count: awarenessRanked[0][1],
    pct: Math.round((awarenessRanked[0][1] / total) * 100),
  } : null;
  const awarenessSplit = !dominantAwareness || dominantAwareness.pct < 60;
  const awarenessBreakdown = awarenessRanked.map(([stage, count]) => ({
    stage, count, pct: Math.round((count / total) * 100),
  }));

  // --- Sophistication ---
  const strategyFreq = {};
  for (const e of extractions) {
    const strat = e.sophistication.primaryStrategy;
    strategyFreq[strat] = (strategyFreq[strat] || 0) + 1;
  }
  const sophisticationBreakdown = Object.entries(strategyFreq)
    .sort((a, b) => b[1] - a[1])
    .map(([strategy, count]) => ({ strategy, count, pct: Math.round((count / total) * 100) }));

  // --- Product Delivery ---
  const deliveryFreq = {};
  for (const e of extractions) {
    for (const s of e.productDelivery.signals) {
      const normalized = s.toLowerCase();
      deliveryFreq[normalized] = (deliveryFreq[normalized] || 0) + 1;
    }
  }
  const topDeliverySignals = Object.entries(deliveryFreq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15)
    .map(([signal, count]) => ({ signal, count }));

  // --- Creative Styles ---
  const styleFreq = {};
  for (const e of extractions) {
    for (const style of e.bigIdea.allStyles) {
      styleFreq[style] = (styleFreq[style] || 0) + 1;
    }
  }
  const topCreativeStyles = Object.entries(styleFreq)
    .sort((a, b) => b[1] - a[1])
    .map(([style, count]) => ({ style, count, pct: Math.round((count / total) * 100) }));

  // --- Framework completeness per ad (with missing element names) ---
  const completeness = extractions.map(e => {
    const elements = {
      'Target Customer': e.targetCustomer.demographics.length > 0 || e.targetCustomer.psychographics.length > 0,
      'Mass Desire': e.massDesire.primary !== null,
      'Pain Points': Object.keys(e.painPoints.byCategory).length > 0,
      'Root Cause': e.rootCause.present,
      'Mechanism': e.mechanism.present,
      'Product Delivery': e.productDelivery.present,
    };
    const present = Object.entries(elements).filter(([, v]) => v).map(([k]) => k);
    const missing = Object.entries(elements).filter(([, v]) => !v).map(([k]) => k);
    const score = present.length;
    return {
      id: e.id, name: e.name, type: e.type,
      score, outOf: Object.keys(elements).length,
      pct: Math.round((score / Object.keys(elements).length) * 100),
      present, missing,
    };
  });

  // --- Strategic Gaps by ad type ---
  const strategicGaps = {};
  for (const [adType, count] of Object.entries(byType)) {
    const typeAds = extractions.filter(e => e.type === adType);
    const elementCounts = {
      'Root Cause': typeAds.filter(e => e.rootCause.present).length,
      'Mechanism': typeAds.filter(e => e.mechanism.present).length,
      'Product Delivery': typeAds.filter(e => e.productDelivery.present).length,
      'Pain Points': typeAds.filter(e => Object.keys(e.painPoints.byCategory).length > 0).length,
    };
    const gaps = [];
    for (const [element, presCount] of Object.entries(elementCounts)) {
      const pct = Math.round((presCount / count) * 100);
      if (pct < 50) {
        gaps.push({ element, present: presCount, total: count, pct });
      }
    }
    if (gaps.length > 0) {
      strategicGaps[adType] = { totalAds: count, gaps };
    }
  }

  return {
    totalAds: total,
    byType,
    avgWords,
    avatars,
    demographicFreq: Object.entries(demoFreq).sort((a, b) => b[1] - a[1]),
    psychographicFreq: Object.entries(psychoFreq).sort((a, b) => b[1] - a[1]),
    primaryDesire,
    allDesires,
    painCategories,
    rootCause: {
      adsWithRootCause: rootCauseCount,
      pct: Math.round((rootCauseCount / total) * 100),
      villainTypes,
      sentences: rootCauseSentences,
    },
    mechanism: {
      adsWithMechanism: mechanismCount,
      pct: Math.round((mechanismCount / total) * 100),
      fullChainCount,
      commonMissingSteps,
      bestChainAd: bestChainAd ? bestChainAd.id : null,
    },
    topDeliverySignals,
    sophisticationBreakdown,
    awareness: {
      dominant: dominantAwareness,
      isSplit: awarenessSplit,
      breakdown: awarenessBreakdown,
    },
    topCreativeStyles,
    completeness,
    strategicGaps,
  };
}

module.exports = { analyzePatterns };
