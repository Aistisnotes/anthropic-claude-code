'use strict';

const { AdType, filterAds, countWords } = require('../src/adFilter');
const { extractComponents } = require('../src/adExtractor');
const { analyzePatterns } = require('../src/patternAnalyzer');
const { generateReport } = require('../src/reportGenerator');

function makeWords(n) {
  return Array.from({ length: n }, (_, i) => `word${i}`).join(' ');
}

const sampleAds = [
  { id: 's1', type: AdType.STATIC, name: 'Long static',
    transcript: 'The science of health has evolved. ' + makeWords(510) + ' Use code SAVE20 for 20% off. Visit example.com. Free shipping. 90-day money-back guarantee. Over 100,000 customers trust us.' },
  { id: 'v1', type: AdType.VIDEO, name: 'Narrated video',
    transcript: 'Hi I am the founder. We built this product because nothing else worked. Try it today. Use code SAVE20 for 20% off your first order.' },
  { id: 'v2', type: AdType.VIDEO, name: 'Silent video', transcript: '' },
];

describe('extractComponents', () => {
  const kept = filterAds(sampleAds);

  test('extracts from static ad', () => {
    const e = extractComponents(kept.find(a => a.id === 's1'));
    expect(e.wordCount).toBeGreaterThanOrEqual(500);
    expect(e.hook).toBeTruthy();
    expect(e.keywords.length).toBeGreaterThan(0);
  });

  test('extracts CTAs', () => {
    const e = extractComponents(kept.find(a => a.id === 's1'));
    const ctaText = e.ctas.join(' ').toLowerCase();
    expect(ctaText).toContain('20% off');
  });

  test('extracts offers', () => {
    const e = extractComponents(kept.find(a => a.id === 's1'));
    const offerText = e.offers.join(' ').toLowerCase();
    expect(offerText).toContain('code save20');
  });

  test('detects tone markers', () => {
    const e = extractComponents(kept.find(a => a.id === 's1'));
    expect(e.dominantTone.length).toBeGreaterThan(0);
  });

  test('extracts from video ad', () => {
    const e = extractComponents(kept.find(a => a.id === 'v1'));
    expect(e.type).toBe('video');
    expect(e.wordCount).toBeGreaterThan(0);
  });
});

describe('analyzePatterns', () => {
  const kept = filterAds(sampleAds);
  const extractions = kept.map(a => extractComponents(a));
  const patterns = analyzePatterns(extractions);

  test('counts total ads', () => {
    expect(patterns.totalAds).toBe(2);
  });

  test('provides word stats', () => {
    expect(patterns.wordStats.avg).toBeGreaterThan(0);
    expect(patterns.wordStats.min).toBeLessThanOrEqual(patterns.wordStats.max);
  });

  test('collects keywords', () => {
    expect(patterns.topKeywords.length).toBeGreaterThan(0);
  });

  test('returns empty result for no ads', () => {
    expect(analyzePatterns([])).toEqual({ totalAds: 0 });
  });
});

describe('generateReport', () => {
  const kept = filterAds(sampleAds);
  const extractions = kept.map(a => extractComponents(a));
  const patterns = analyzePatterns(extractions);
  const filterSummary = { total: 3, kept: 2, skipped: 1, skippedReasons: [{ id: 'v2', type: 'video', reason: 'empty transcript' }] };
  const report = generateReport('Test Brand', filterSummary, patterns, extractions);

  test('produces a string', () => {
    expect(typeof report).toBe('string');
  });

  test('contains brand name', () => {
    expect(report).toContain('TEST BRAND');
  });

  test('contains filter results', () => {
    expect(report).toContain('FILTER RESULTS');
    expect(report).toContain('Ads kept');
  });

  test('contains all report sections', () => {
    expect(report).toContain('AD TYPE BREAKDOWN');
    expect(report).toContain('COPY LENGTH');
    expect(report).toContain('OPENING HOOKS');
    expect(report).toContain('TONE & STYLE');
    expect(report).toContain('CALLS TO ACTION');
    expect(report).toContain('OFFERS & PROMOTIONS');
    expect(report).toContain('TOP KEYWORDS');
    expect(report).toContain('PER-AD DETAIL');
  });

  test('contains skip reasons', () => {
    expect(report).toContain('empty transcript');
  });
});
