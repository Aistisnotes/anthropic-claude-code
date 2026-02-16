'use strict';

/**
 * Analyze patterns across a set of extracted ad components.
 */
function analyzePatterns(extractions) {
  if (!extractions || extractions.length === 0) {
    return { totalAds: 0 };
  }

  const total = extractions.length;

  // --- Word count distribution ---
  const wordCounts = extractions.map(e => e.wordCount);
  const avgWords = Math.round(wordCounts.reduce((a, b) => a + b, 0) / total);
  const minWords = Math.min(...wordCounts);
  const maxWords = Math.max(...wordCounts);

  // --- CTA frequency ---
  const ctaFreq = {};
  for (const e of extractions) {
    for (const cta of e.ctas) {
      const normalized = cta.toLowerCase();
      ctaFreq[normalized] = (ctaFreq[normalized] || 0) + 1;
    }
  }
  const topCTAs = Object.entries(ctaFreq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([cta, count]) => ({ cta, count, pct: Math.round((count / total) * 100) }));

  // --- Offer frequency ---
  const offerFreq = {};
  for (const e of extractions) {
    for (const offer of e.offers) {
      const normalized = offer.toLowerCase();
      offerFreq[normalized] = (offerFreq[normalized] || 0) + 1;
    }
  }
  const topOffers = Object.entries(offerFreq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([offer, count]) => ({ offer, count, pct: Math.round((count / total) * 100) }));

  // --- Tone distribution ---
  const toneTotals = {};
  for (const e of extractions) {
    for (const [tone, score] of Object.entries(e.toneScores)) {
      toneTotals[tone] = (toneTotals[tone] || 0) + score;
    }
  }
  // Count how many ads feature each tone
  const tonePresence = {};
  for (const e of extractions) {
    for (const tone of Object.keys(e.toneScores)) {
      tonePresence[tone] = (tonePresence[tone] || 0) + 1;
    }
  }
  const toneBreakdown = Object.entries(tonePresence)
    .sort((a, b) => b[1] - a[1])
    .map(([tone, count]) => ({
      tone,
      adsWithTone: count,
      pct: Math.round((count / total) * 100),
      totalHits: toneTotals[tone],
    }));

  // --- Global keyword frequency ---
  const globalKeywords = {};
  for (const e of extractions) {
    for (const { word, count } of e.keywords) {
      globalKeywords[word] = (globalKeywords[word] || 0) + count;
    }
  }
  const topKeywords = Object.entries(globalKeywords)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 20)
    .map(([word, count]) => ({ word, count }));

  // --- Hook analysis (opening patterns) ---
  const hooks = extractions.map(e => ({
    id: e.id,
    name: e.name,
    hook: e.hook,
  }));

  // --- Type breakdown ---
  const byType = {};
  for (const e of extractions) {
    byType[e.type] = (byType[e.type] || 0) + 1;
  }

  return {
    totalAds: total,
    byType,
    wordStats: { avg: avgWords, min: minWords, max: maxWords },
    topCTAs,
    topOffers,
    toneBreakdown,
    topKeywords,
    hooks,
  };
}

module.exports = { analyzePatterns };
