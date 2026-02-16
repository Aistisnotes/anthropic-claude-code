import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { generateMarketMap, formatMarketMapText } from './market-map.js';
import { generateLoopholeDoc, formatLoopholeDocText } from './loophole-doc.js';

/**
 * End-to-end tests for the compare pipeline.
 *
 * Uses mock brand reports that mirror the real structure produced by
 * generateBrandReport() in brand-report.js.
 */

function makeBrandReport(name, overrides = {}) {
  return {
    brand: {
      name,
      pageId: '12345',
      totalAds: overrides.totalAds || 20,
      activeAds: overrides.activeAds || 10,
      recentAds: overrides.recentAds || 8,
      relevanceScore: overrides.relevanceScore || 100,
      earliestLaunch: '2026-01-01T00:00:00Z',
      latestLaunch: '2026-02-10T00:00:00Z',
      impressionsLower: 500000,
    },
    meta: {
      keyword: 'test keyword',
      scanDate: '2026-02-15T00:00:00Z',
      reportDate: '2026-02-15T00:00:00Z',
    },
    selection: {
      totalScanned: 20,
      totalSelected: 10,
      totalSkipped: 8,
      duplicatesRemoved: 2,
      byPriority: { activeWinners: 3, provenRecent: 4, strategicDirection: 2, recentModerate: 1 },
    },
    analysis: {
      totalAnalyzed: 10,
      hookDistribution: overrides.hooks || { question: 3, story: 2, direct_address: 2 },
      angleDistribution: overrides.angles || { mechanism: 4, social_proof: 3 },
      emotionDistribution: overrides.emotions || { security: 3, achievement: 2 },
      formatDistribution: overrides.formats || { direct_response: 5, listicle: 3 },
      ctaDistribution: overrides.ctas || { shop_now: 6, learn_more: 3 },
      offerTypes: overrides.offers || { discount: 3, guarantee: 2 },
      avgWordCount: 120,
      withCreative: 5,
      withVideo: 2,
      withImages: 8,
    },
    strategy: {
      primaryHook: overrides.primaryHook || 'question',
      primaryAngle: overrides.primaryAngle || 'mechanism',
      primaryFormat: overrides.primaryFormat || 'direct_response',
      primaryEmotion: overrides.primaryEmotion || 'security',
      primaryCta: overrides.primaryCta || 'shop_now',
      activityLevel: 'active',
      hookDiversity: Object.keys(overrides.hooks || { question: 3, story: 2, direct_address: 2 }).length,
      angleDiversity: Object.keys(overrides.angles || { mechanism: 4, social_proof: 3 }).length,
      usesOffers: true,
      offerTypes: Object.keys(overrides.offers || { discount: 3, guarantee: 2 }),
      avgWordCount: 120,
      contentDepth: 'medium',
      usesVideo: true,
      videoRatio: 20,
      topHooks: [{ key: 'question', count: 3 }],
      topAngles: [{ key: 'mechanism', count: 4 }],
      topEmotions: [{ key: 'security', count: 3 }],
    },
    topAds: [],
  };
}

// Three brands with different strategies for meaningful comparison
const BRAND_A = makeBrandReport('BrandAlpha', {
  hooks: { question: 5, story: 3, bold_claim: 2 },
  angles: { mechanism: 6, authority: 3 },
  emotions: { security: 4, achievement: 3 },
  formats: { direct_response: 5, long_form: 3 },
  offers: { discount: 4, guarantee: 2 },
  ctas: { shop_now: 7, learn_more: 2 },
  primaryHook: 'question',
  primaryAngle: 'mechanism',
  primaryEmotion: 'security',
});

const BRAND_B = makeBrandReport('BrandBeta', {
  hooks: { direct_address: 4, fear_urgency: 3, statistic: 2 },
  angles: { problem_agitate: 5, scarcity: 3 },
  emotions: { stimulation: 4, hedonism: 2 },
  formats: { listicle: 4, emoji_heavy: 3, testimonial: 2 },
  offers: { limited_time: 3, free_shipping: 2 },
  ctas: { claim_offer: 5, shop_now: 3 },
  primaryHook: 'direct_address',
  primaryAngle: 'problem_agitate',
  primaryEmotion: 'stimulation',
});

const BRAND_C = makeBrandReport('BrandGamma', {
  hooks: { question: 3, curiosity: 4, social_proof: 2 },
  angles: { social_proof: 5, educational: 3 },
  emotions: { benevolence: 3, universalism: 2, security: 1 },
  formats: { how_to: 4, testimonial: 3 },
  offers: { free_trial: 4, guarantee: 1 },
  ctas: { learn_more: 5, sign_up: 3 },
  primaryHook: 'curiosity',
  primaryAngle: 'social_proof',
  primaryEmotion: 'benevolence',
});

const ALL_REPORTS = [BRAND_A, BRAND_B, BRAND_C];

// ─── Market Map ─────────────────────────────────────────────

describe('generateMarketMap', () => {
  it('generates a market map with correct metadata', () => {
    const map = generateMarketMap(ALL_REPORTS, { keyword: 'test', scanDate: '2026-02-15' });

    assert.equal(map.meta.brandsCompared, 3);
    assert.deepEqual(map.meta.brandNames, ['BrandAlpha', 'BrandBeta', 'BrandGamma']);
    assert.equal(map.meta.keyword, 'test');
  });

  it('builds hook comparison matrix with all standard hooks', () => {
    const map = generateMarketMap(ALL_REPORTS);

    assert.ok(map.matrices.hooks.length >= 9); // All standard hooks
    const questionRow = map.matrices.hooks.find((r) => r.dimension === 'question');
    assert.ok(questionRow);
    assert.equal(questionRow.brands['BrandAlpha'], 5);
    assert.equal(questionRow.brands['BrandBeta'], 0);
    assert.equal(questionRow.brands['BrandGamma'], 3);
    assert.equal(questionRow.coverage, 2); // 2 of 3 brands use questions
  });

  it('builds angle comparison matrix', () => {
    const map = generateMarketMap(ALL_REPORTS);

    const mechRow = map.matrices.angles.find((r) => r.dimension === 'mechanism');
    assert.equal(mechRow.brands['BrandAlpha'], 6);
    assert.equal(mechRow.brands['BrandBeta'], 0);
    assert.equal(mechRow.coverage, 1); // Only BrandAlpha
  });

  it('builds emotion comparison matrix with Schwartz values', () => {
    const map = generateMarketMap(ALL_REPORTS);

    const secRow = map.matrices.emotions.find((r) => r.dimension === 'security');
    assert.equal(secRow.coverage, 2); // BrandAlpha + BrandGamma
    assert.equal(secRow.brands['BrandAlpha'], 4);
    assert.equal(secRow.brands['BrandGamma'], 1);
  });

  it('computes saturation analysis', () => {
    const map = generateMarketMap(ALL_REPORTS);

    assert.ok(map.saturation.hooks);
    assert.ok(map.saturation.hooks.saturated);
    assert.ok(map.saturation.hooks.moderate);
    assert.ok(map.saturation.hooks.whitespace);
  });

  it('identifies saturated dimensions (60%+ coverage)', () => {
    const map = generateMarketMap(ALL_REPORTS);

    // "question" hook is used by 2/3 brands = 67% → saturated
    const saturatedHooks = map.saturation.hooks.saturated.map((s) => s.dimension);
    assert.ok(saturatedHooks.includes('question'));
  });

  it('identifies whitespace dimensions (<30% coverage)', () => {
    const map = generateMarketMap(ALL_REPORTS);

    // "story" hook is used by only 1/3 = 33% → moderate, not whitespace
    // "bold_claim" is used by 1/3 = 33% → moderate
    // hooks nobody uses → whitespace
    const whitespaceHooks = map.saturation.hooks.whitespace.map((s) => s.dimension);
    // "other" hook is not used by any brand → 0% → whitespace
    assert.ok(whitespaceHooks.includes('other'));
  });

  it('generates brand strategy profiles', () => {
    const map = generateMarketMap(ALL_REPORTS);

    assert.equal(map.profiles.length, 3);
    assert.equal(map.profiles[0].name, 'BrandAlpha');
    assert.equal(map.profiles[0].primaryHook, 'question');
    assert.equal(map.profiles[1].primaryAngle, 'problem_agitate');
  });

  it('computes overall market stats', () => {
    const map = generateMarketMap(ALL_REPORTS);

    assert.equal(map.saturation.overall.totalBrands, 3);
    assert.equal(map.saturation.overall.videoUsage, 100); // All 3 use video
    assert.equal(map.saturation.overall.offerUsage, 100); // All 3 use offers
  });
});

describe('formatMarketMapText', () => {
  it('produces non-empty formatted output', () => {
    const map = generateMarketMap(ALL_REPORTS, { keyword: 'test supplements', scanDate: '2026-02-15' });
    const text = formatMarketMapText(map);

    assert.ok(text.length > 100);
    assert.ok(text.includes('MARKET MAP'));
    assert.ok(text.includes('BRAND STRATEGY PROFILES'));
    assert.ok(text.includes('SATURATION ANALYSIS'));
    assert.ok(text.includes('BrandAlpha'));
    assert.ok(text.includes('BrandBeta'));
    assert.ok(text.includes('HOOK COMPARISON MATRIX'));
  });
});

// ─── Loophole Document ──────────────────────────────────────

describe('generateLoopholeDoc', () => {
  const map = generateMarketMap(ALL_REPORTS, { keyword: 'test' });

  it('generates loophole doc with correct metadata', () => {
    const doc = generateLoopholeDoc(map, ALL_REPORTS);

    assert.equal(doc.meta.keyword, 'test');
    assert.equal(doc.meta.brandsCompared, 3);
    assert.equal(doc.meta.focusBrand, null);
  });

  it('finds market-wide gaps (dimensions nobody uses)', () => {
    const doc = generateLoopholeDoc(map, ALL_REPORTS);

    // "transformation" angle: none of our 3 brands use it
    const angleGaps = doc.marketGaps.angles.map((g) => g.dimension);
    assert.ok(angleGaps.includes('transformation'));
  });

  it('finds saturation zones', () => {
    const doc = generateLoopholeDoc(map, ALL_REPORTS);

    // Check that saturation zones exist and have structure
    assert.ok(doc.saturationZones);
    const allZones = Object.values(doc.saturationZones).flat();
    // Every zone should have coveragePercent >= 60
    for (const zone of allZones) {
      assert.ok(zone.coveragePercent >= 60, `Zone ${zone.dimension} has ${zone.coveragePercent}%`);
    }
  });

  it('finds underexploited opportunities (coverage threshold aware)', () => {
    const doc = generateLoopholeDoc(map, ALL_REPORTS);

    // With 3 brands: 1/3 = 33% which is >= 30%, so no underexploited items
    // This is correct — underexploited requires <30% coverage with at least 1 user
    assert.ok(Array.isArray(doc.underexploited));
    for (const item of doc.underexploited) {
      assert.ok(item.coveragePercent < 30, `${item.dimension} has ${item.coveragePercent}%`);
    }

    // With 4+ brands, 1 brand = 25% < 30% → underexploited items appear
    const brand4 = makeBrandReport('BrandDelta', {
      hooks: { statistic: 4 },
      angles: { educational: 5 },
      emotions: { self_direction: 3 },
      formats: { minimal: 5 },
      offers: { subscription: 3 },
      ctas: { download: 4 },
    });
    const map4 = generateMarketMap([...ALL_REPORTS, brand4], { keyword: 'test' });
    const doc4 = generateLoopholeDoc(map4, [...ALL_REPORTS, brand4]);

    assert.ok(doc4.underexploited.length > 0, 'With 4 brands, 1/4 = 25% should produce underexploited items');
    for (const item of doc4.underexploited) {
      assert.ok(item.coveragePercent < 30);
    }
  });

  it('builds a priority matrix sorted by score', () => {
    const doc = generateLoopholeDoc(map, ALL_REPORTS);

    assert.ok(doc.priorityMatrix.length > 0);
    // Verify sorted descending by priorityScore
    for (let i = 1; i < doc.priorityMatrix.length; i++) {
      assert.ok(
        doc.priorityMatrix[i].priorityScore <= doc.priorityMatrix[i - 1].priorityScore,
        `Entry ${i} score ${doc.priorityMatrix[i].priorityScore} > entry ${i-1} score ${doc.priorityMatrix[i-1].priorityScore}`
      );
    }
  });

  it('assigns priority tiers correctly', () => {
    const doc = generateLoopholeDoc(map, ALL_REPORTS);

    for (const entry of doc.priorityMatrix) {
      if (entry.priorityScore >= 80) assert.equal(entry.tier, 'P1_HIGH');
      else if (entry.priorityScore >= 50) assert.equal(entry.tier, 'P2_MEDIUM');
      else if (entry.priorityScore >= 25) assert.equal(entry.tier, 'P3_LOW');
      else assert.equal(entry.tier, 'P4_MONITOR');
    }
  });

  it('generates brand-specific gaps when focus brand specified', () => {
    const doc = generateLoopholeDoc(map, ALL_REPORTS, 'BrandAlpha');

    assert.equal(doc.meta.focusBrand, 'BrandAlpha');
    assert.ok(doc.brandGaps);
    assert.ok(doc.brandGaps.length > 0);

    // BrandAlpha doesn't use "problem_agitate" but BrandBeta does
    const angleBrandGaps = doc.brandGaps.filter((g) => g.category === 'angles');
    const paGap = angleBrandGaps.find((g) => g.dimension === 'problem_agitate');
    assert.ok(paGap, 'Should find problem_agitate as a gap for BrandAlpha');
    assert.ok(paGap.competitorsUsing.includes('BrandBeta'));
  });

  it('is case-insensitive on focus brand', () => {
    const doc = generateLoopholeDoc(map, ALL_REPORTS, 'brandalpha');

    assert.ok(doc.brandGaps);
    assert.ok(doc.brandGaps.length > 0);
  });

  it('handles unknown focus brand gracefully', () => {
    const doc = generateLoopholeDoc(map, ALL_REPORTS, 'NonexistentBrand');

    // No brandGaps property since the brand wasn't found
    assert.equal(doc.brandGaps, undefined);
  });
});

describe('formatLoopholeDocText', () => {
  it('produces non-empty formatted output', () => {
    const map = generateMarketMap(ALL_REPORTS, { keyword: 'test supplements' });
    const doc = generateLoopholeDoc(map, ALL_REPORTS, 'BrandAlpha');
    const text = formatLoopholeDocText(doc);

    assert.ok(text.length > 100);
    assert.ok(text.includes('MASTER LOOPHOLE DOCUMENT'));
    assert.ok(text.includes('MARKET GAPS'));
    assert.ok(text.includes('PRIORITY MATRIX'));
    assert.ok(text.includes('BrandAlpha'));
  });
});

// ─── End-to-End Pipeline ─────────────────────────────────────

describe('End-to-end: Market Map → Loophole Doc', () => {
  it('full pipeline produces actionable output', () => {
    // 1. Generate Market Map
    const map = generateMarketMap(ALL_REPORTS, { keyword: 'supplements', scanDate: '2026-02-15' });

    // 2. Generate Loophole Doc with brand focus
    const doc = generateLoopholeDoc(map, ALL_REPORTS, 'BrandBeta');

    // 3. Verify key outputs exist
    assert.ok(map.matrices.hooks.length > 0, 'Market map has hook matrix');
    assert.ok(map.saturation.overall.totalBrands === 3, 'Market map has 3 brands');
    assert.ok(doc.priorityMatrix.length > 0, 'Loophole doc has priority matrix');
    assert.ok(doc.brandGaps.length > 0, 'BrandBeta has gaps to exploit');

    // 4. BrandBeta doesn't use mechanism angle — should appear as brand gap
    const mechGap = doc.brandGaps.find(
      (g) => g.category === 'angles' && g.dimension === 'mechanism'
    );
    assert.ok(mechGap, 'BrandBeta should have mechanism as a gap');
    assert.ok(mechGap.competitorsUsing.includes('BrandAlpha'));

    // 5. Market-wide gaps should include unused dimensions
    const unusedEmotions = doc.marketGaps.emotions.map((g) => g.dimension);
    // "tradition" and "conformity" not used by any of our 3 brands
    assert.ok(unusedEmotions.includes('tradition'));
    assert.ok(unusedEmotions.includes('conformity'));

    // 6. Format outputs should work
    assert.ok(formatMarketMapText(map).length > 200);
    assert.ok(formatLoopholeDocText(doc).length > 200);
  });
});
