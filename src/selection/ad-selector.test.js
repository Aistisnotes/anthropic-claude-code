import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { classifyAd, deduplicateAds, selectAds, selectAdsForBrand } from './ad-selector.js';

// Fixed "now" for deterministic tests: 2026-02-16
const NOW = new Date('2026-02-16T12:00:00Z');

/** Helper to make a mock ad record */
function makeAd(overrides = {}) {
  return {
    id: overrides.id || 'ad_001',
    pageName: overrides.pageName || 'TestBrand',
    pageId: overrides.pageId || '12345',
    launchDate: overrides.launchDate || '2026-02-10T00:00:00Z',
    stopDate: overrides.stopDate || null,
    isActive: overrides.isActive ?? true,
    impressions: overrides.impressions || { lower: 60000, upper: 100000, label: '60K-100K' },
    spend: overrides.spend || { lower: 500, upper: 1000, currency: 'USD' },
    primaryTexts: overrides.primaryTexts || ['This is a long primary text that has enough words to pass the minimum threshold. We need at least fifty words to be considered substantial enough for analysis. So here are more words to pad it out and make sure we clear the bar easily.'],
    headlines: overrides.headlines || ['Test Headline'],
    descriptions: overrides.descriptions || ['Test description'],
    maxPrimaryTextWords: overrides.maxPrimaryTextWords ?? 55,
    platforms: overrides.platforms || ['facebook'],
    snapshotUrl: overrides.snapshotUrl || null,
    ...overrides,
  };
}

// ─── classifyAd ─────────────────────────────────────────────

describe('classifyAd', () => {
  it('P1: Active Winner — <14 days + high impressions', () => {
    const ad = makeAd({
      launchDate: '2026-02-05T00:00:00Z', // 11 days ago
      impressions: { lower: 60000, upper: 100000 },
    });
    const result = classifyAd(ad, NOW);
    assert.equal(result.priority, 1);
    assert.equal(result.label, 'ACTIVE_WINNER');
  });

  it('P2: Proven Recent — <30 days + moderate impressions', () => {
    const ad = makeAd({
      launchDate: '2026-01-25T00:00:00Z', // 22 days ago
      impressions: { lower: 15000, upper: 30000 },
    });
    const result = classifyAd(ad, NOW);
    assert.equal(result.priority, 2);
    assert.equal(result.label, 'PROVEN_RECENT');
  });

  it('P3: Strategic Direction — <7 days, any impressions', () => {
    const ad = makeAd({
      launchDate: '2026-02-12T00:00:00Z', // 4 days ago
      impressions: { lower: 200, upper: 500 },
    });
    const result = classifyAd(ad, NOW);
    assert.equal(result.priority, 3);
    assert.equal(result.label, 'STRATEGIC_DIRECTION');
  });

  it('P3 takes precedence over P1 for very new high-impression ads (P1 matches first by code order)', () => {
    // <7 days AND high impressions — P1 matches first since <14 days + high impressions
    const ad = makeAd({
      launchDate: '2026-02-12T00:00:00Z', // 4 days ago
      impressions: { lower: 80000, upper: 150000 },
    });
    const result = classifyAd(ad, NOW);
    // P1 check runs first: <14 days + high impressions → P1
    assert.equal(result.priority, 1);
  });

  it('P4: Recent Moderate — <60 days + high impressions', () => {
    const ad = makeAd({
      launchDate: '2026-01-01T00:00:00Z', // 46 days ago
      impressions: { lower: 55000, upper: 80000 },
    });
    const result = classifyAd(ad, NOW);
    assert.equal(result.priority, 4);
    assert.equal(result.label, 'RECENT_MODERATE');
  });

  it('SKIP: Legacy ads (6+ months old)', () => {
    const ad = makeAd({
      launchDate: '2025-06-01T00:00:00Z', // ~8.5 months ago
    });
    const result = classifyAd(ad, NOW);
    assert.equal(result.priority, null);
    assert.equal(result.skipReason, 'legacy_autopilot');
  });

  it('SKIP: Failed tests (low impressions + >30 days old)', () => {
    const ad = makeAd({
      launchDate: '2026-01-10T00:00:00Z', // 37 days ago
      impressions: { lower: 500, upper: 800 },
    });
    const result = classifyAd(ad, NOW);
    assert.equal(result.priority, null);
    assert.equal(result.skipReason, 'failed_test');
  });

  it('SKIP: Thin text (<50 words)', () => {
    const ad = makeAd({
      launchDate: '2026-02-10T00:00:00Z',
      maxPrimaryTextWords: 30,
    });
    const result = classifyAd(ad, NOW);
    assert.equal(result.priority, null);
    assert.equal(result.skipReason, 'thin_text');
  });

  it('SKIP: No launch date', () => {
    const ad = makeAd({ launchDate: null });
    const result = classifyAd(ad, NOW);
    assert.equal(result.priority, null);
    assert.equal(result.skipReason, 'no_launch_date');
  });

  it('SKIP: Below threshold — moderate age, moderate impressions (no priority match)', () => {
    const ad = makeAd({
      launchDate: '2026-01-05T00:00:00Z', // 42 days ago
      impressions: { lower: 15000, upper: 25000 }, // moderate, not high
    });
    const result = classifyAd(ad, NOW);
    assert.equal(result.priority, null);
    assert.equal(result.skipReason, 'below_threshold');
  });
});

// ─── deduplicateAds ─────────────────────────────────────────

describe('deduplicateAds', () => {
  it('keeps unique ads', () => {
    const ads = [
      makeAd({ id: 'a1', primaryTexts: ['Unique text about product one that is different'] }),
      makeAd({ id: 'a2', primaryTexts: ['Completely different text about another product here'] }),
    ];
    const { kept, duplicatesRemoved } = deduplicateAds(ads);
    assert.equal(kept.length, 2);
    assert.equal(duplicatesRemoved, 0);
  });

  it('removes duplicates, keeps highest impression version', () => {
    const sharedText = 'This is the exact same primary text that appears in multiple ad variations for testing';
    const ads = [
      makeAd({ id: 'a1', primaryTexts: [sharedText], impressions: { lower: 5000 } }),
      makeAd({ id: 'a2', primaryTexts: [sharedText], impressions: { lower: 50000 } }),
      makeAd({ id: 'a3', primaryTexts: [sharedText], impressions: { lower: 20000 } }),
    ];
    const { kept, duplicatesRemoved } = deduplicateAds(ads);
    assert.equal(kept.length, 1);
    assert.equal(duplicatesRemoved, 2);
    assert.equal(kept[0].id, 'a2'); // Highest impressions
  });

  it('deduplicates per advertiser (different brands can have same text)', () => {
    const sharedText = 'Same text used by different brands for similar products in the market';
    const ads = [
      makeAd({ id: 'a1', pageName: 'BrandA', primaryTexts: [sharedText] }),
      makeAd({ id: 'a2', pageName: 'BrandB', primaryTexts: [sharedText] }),
    ];
    const { kept, duplicatesRemoved } = deduplicateAds(ads);
    assert.equal(kept.length, 2); // Different brands, not duplicates
    assert.equal(duplicatesRemoved, 0);
  });
});

// ─── selectAds ──────────────────────────────────────────────

describe('selectAds', () => {
  it('selects and sorts ads by priority then impressions', () => {
    const ads = [
      makeAd({ id: 'p4', launchDate: '2026-01-01T00:00:00Z', impressions: { lower: 70000 }, maxPrimaryTextWords: 55, primaryTexts: ['Ad text about recent moderate performance metrics and results four'] }),
      makeAd({ id: 'p1', launchDate: '2026-02-05T00:00:00Z', impressions: { lower: 60000 }, maxPrimaryTextWords: 55, primaryTexts: ['Ad text about active winner scaling with high impressions one'] }),
      makeAd({ id: 'p3', launchDate: '2026-02-13T00:00:00Z', impressions: { lower: 300 }, maxPrimaryTextWords: 55, primaryTexts: ['Ad text about strategic direction brand new test launch three'] }),
      makeAd({ id: 'skip', launchDate: '2025-01-01T00:00:00Z', impressions: { lower: 100000 }, maxPrimaryTextWords: 55, primaryTexts: ['Ad text about legacy autopilot running for many months skip'] }),
    ];
    const { selected, skipped, stats } = selectAds(ads, { now: NOW });

    assert.equal(selected.length, 3);
    assert.equal(skipped.length, 1);
    assert.equal(selected[0].id, 'p1'); // P1 first
    assert.equal(selected[1].id, 'p3'); // P3 second
    assert.equal(selected[2].id, 'p4'); // P4 third
    assert.equal(stats.byPriority.activeWinners, 1);
    assert.equal(stats.byPriority.strategicDirection, 1);
    assert.equal(stats.byPriority.recentModerate, 1);
  });

  it('respects limit parameter', () => {
    const ads = [
      makeAd({ id: 'a1', launchDate: '2026-02-05T00:00:00Z', impressions: { lower: 60000 }, maxPrimaryTextWords: 55, primaryTexts: ['First ad about product benefits and unique selling points here'] }),
      makeAd({ id: 'a2', launchDate: '2026-02-06T00:00:00Z', impressions: { lower: 70000 }, maxPrimaryTextWords: 55, primaryTexts: ['Second ad about different angle with alternative messaging copy'] }),
      makeAd({ id: 'a3', launchDate: '2026-02-07T00:00:00Z', impressions: { lower: 80000 }, maxPrimaryTextWords: 55, primaryTexts: ['Third ad about another unique approach to customer acquisition'] }),
    ];
    const { selected } = selectAds(ads, { limit: 2, now: NOW });
    assert.equal(selected.length, 2);
  });
});

// ─── selectAdsForBrand ──────────────────────────────────────

describe('selectAdsForBrand', () => {
  it('filters to a single brand and selects', () => {
    const ads = [
      makeAd({ id: 'a1', pageName: 'TargetBrand', launchDate: '2026-02-05T00:00:00Z', impressions: { lower: 60000 }, maxPrimaryTextWords: 55, primaryTexts: ['Target brand first ad about lymphatic drainage supplement benefits'] }),
      makeAd({ id: 'a2', pageName: 'OtherBrand', launchDate: '2026-02-05T00:00:00Z', impressions: { lower: 90000 }, maxPrimaryTextWords: 55, primaryTexts: ['Other brand ad about competing product with different angle'] }),
      makeAd({ id: 'a3', pageName: 'TargetBrand', launchDate: '2026-02-13T00:00:00Z', impressions: { lower: 500 }, maxPrimaryTextWords: 55, primaryTexts: ['Target brand second ad new test about mechanism of action'] }),
    ];
    const { selected } = selectAdsForBrand(ads, 'TargetBrand', 15, NOW);

    assert.equal(selected.length, 2);
    assert.ok(selected.every((a) => a.pageName === 'TargetBrand'));
  });

  it('is case-insensitive on brand name', () => {
    const ads = [
      makeAd({ id: 'a1', pageName: 'MyBrand', launchDate: '2026-02-05T00:00:00Z', impressions: { lower: 60000 }, maxPrimaryTextWords: 55 }),
    ];
    const { selected } = selectAdsForBrand(ads, 'mybrand', 15, NOW);
    assert.equal(selected.length, 1);
  });

  it('returns empty for unknown brand', () => {
    const ads = [
      makeAd({ id: 'a1', pageName: 'BrandA' }),
    ];
    const { selected } = selectAdsForBrand(ads, 'NonexistentBrand', 15, NOW);
    assert.equal(selected.length, 0);
  });
});
