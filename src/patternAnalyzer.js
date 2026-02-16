'use strict';

/**
 * Analyze patterns across a set of DR framework extractions.
 * Identifies trends, commonalities, and gaps across all kept ads.
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

  // --- Word count stats ---
  const wordCounts = extractions.map(e => e.wordCount);
  const avgWords = Math.round(wordCounts.reduce((a, b) => a + b, 0) / total);

  // --- Target customer segments across all ads ---
  const customerFreq = {};
  for (const e of extractions) {
    for (const seg of e.targetCustomer) {
      customerFreq[seg] = (customerFreq[seg] || 0) + 1;
    }
  }
  const topCustomerSegments = Object.entries(customerFreq)
    .sort((a, b) => b[1] - a[1])
    .map(([segment, count]) => ({ segment, count, pct: Math.round((count / total) * 100) }));

  // --- Mass desires across all ads ---
  const desireFreq = {};
  for (const e of extractions) {
    for (const d of e.massDesire) {
      desireFreq[d] = (desireFreq[d] || 0) + 1;
    }
  }
  const topDesires = Object.entries(desireFreq)
    .sort((a, b) => b[1] - a[1])
    .map(([desire, count]) => ({ desire, count, pct: Math.round((count / total) * 100) }));

  // --- Pain points across all ads ---
  const painFreq = {};
  for (const e of extractions) {
    for (const p of e.painPoints) {
      const normalized = p.toLowerCase();
      painFreq[normalized] = (painFreq[normalized] || 0) + 1;
    }
  }
  const topPainPoints = Object.entries(painFreq)
    .sort((a, b) => b[1] - a[1])
    .map(([pain, count]) => ({ pain, count }));

  // --- Root cause presence ---
  const rootCauseCount = extractions.filter(e => e.rootCause.present).length;
  const rootCauseSignalFreq = {};
  for (const e of extractions) {
    for (const s of e.rootCause.signals) {
      const normalized = s.toLowerCase();
      rootCauseSignalFreq[normalized] = (rootCauseSignalFreq[normalized] || 0) + 1;
    }
  }
  const topRootCauseSignals = Object.entries(rootCauseSignalFreq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15)
    .map(([signal, count]) => ({ signal, count }));

  // --- Mechanism presence ---
  const mechanismCount = extractions.filter(e => e.mechanism.present).length;
  const mechSignalFreq = {};
  for (const e of extractions) {
    for (const s of e.mechanism.signals) {
      const normalized = s.toLowerCase();
      mechSignalFreq[normalized] = (mechSignalFreq[normalized] || 0) + 1;
    }
  }
  const topMechanismSignals = Object.entries(mechSignalFreq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15)
    .map(([signal, count]) => ({ signal, count }));

  // --- Product delivery ---
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

  // --- Sophistication strategy distribution ---
  const strategyFreq = {};
  for (const e of extractions) {
    const strat = e.sophistication.primaryStrategy;
    strategyFreq[strat] = (strategyFreq[strat] || 0) + 1;
  }
  const sophisticationBreakdown = Object.entries(strategyFreq)
    .sort((a, b) => b[1] - a[1])
    .map(([strategy, count]) => ({ strategy, count, pct: Math.round((count / total) * 100) }));

  // --- Awareness stage distribution ---
  const awarenessFreq = {};
  for (const e of extractions) {
    const stage = e.awarenessStage.primary;
    awarenessFreq[stage] = (awarenessFreq[stage] || 0) + 1;
  }
  const awarenessBreakdown = Object.entries(awarenessFreq)
    .sort((a, b) => b[1] - a[1])
    .map(([stage, count]) => ({ stage, count, pct: Math.round((count / total) * 100) }));

  // --- Creative angle distribution ---
  const angleFreq = {};
  for (const e of extractions) {
    for (const angle of e.bigIdea.creativeAngles) {
      angleFreq[angle] = (angleFreq[angle] || 0) + 1;
    }
  }
  const topCreativeAngles = Object.entries(angleFreq)
    .sort((a, b) => b[1] - a[1])
    .map(([angle, count]) => ({ angle, count, pct: Math.round((count / total) * 100) }));

  // --- Framework completeness per ad ---
  const completeness = extractions.map(e => {
    const elements = [
      e.targetCustomer.length > 0,
      e.massDesire.length > 0,
      e.painPoints.length > 0,
      e.rootCause.present,
      e.mechanism.present,
      e.productDelivery.present,
    ];
    const score = elements.filter(Boolean).length;
    return { id: e.id, name: e.name, score, outOf: elements.length, pct: Math.round((score / elements.length) * 100) };
  });

  return {
    totalAds: total,
    byType,
    avgWords,
    topCustomerSegments,
    topDesires,
    topPainPoints,
    rootCause: {
      adsWithRootCause: rootCauseCount,
      pct: Math.round((rootCauseCount / total) * 100),
      topSignals: topRootCauseSignals,
    },
    mechanism: {
      adsWithMechanism: mechanismCount,
      pct: Math.round((mechanismCount / total) * 100),
      topSignals: topMechanismSignals,
    },
    topDeliverySignals,
    sophisticationBreakdown,
    awarenessBreakdown,
    topCreativeAngles,
    completeness,
  };
}

module.exports = { analyzePatterns };
