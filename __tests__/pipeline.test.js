'use strict';

const { AdType, filterAds } = require('../src/adFilter');
const { extractFramework, matchSignals, detectTargetCustomer, detectMassDesire, PAIN_POINT_SIGNALS } = require('../src/adExtractor');
const { analyzePatterns } = require('../src/patternAnalyzer');
const { generateReport } = require('../src/reportGenerator');

function makeWords(n) {
  return Array.from({ length: n }, (_, i) => `word${i}`).join(' ');
}

// A rich static ad that hits many framework elements
const richStaticAd = {
  id: 's1', type: AdType.STATIC, name: 'Rich static',
  transcript: 'If you have been struggling with chronic fatigue and brain fog, you are not alone. ' +
    'The real reason you are still tired is not lack of sleep. It is a magnesium deficiency that affects nearly ' +
    '50 percent of adults. The supplement industry has been selling you cheap magnesium oxide that your body ' +
    'cannot absorb. That is why nothing has worked. Our synergistic approach pairs chelated magnesium glycinate ' +
    'with cofactors like vitamin D3 at 5000 IU and a full-spectrum B-complex. This unique formula was designed to ' +
    'restore cellular energy and cognitive clarity. Unlike other brands, every batch is third-party tested by an ' +
    'independent lab. Clinical studies show 82 percent of participants report better sleep within 30 days. ' +
    'Join over 200,000 customers who trust Glow Daily. Use code SHINE25 for 25% off your first order. ' +
    'Whether you are a busy parent trying to keep up with your kids or a professional looking to optimize ' +
    'performance, this was built for you. Free shipping on orders over $50. ' + makeWords(400),
};

// A short video ad with UGC style
const ugcVideoAd = {
  id: 'v1', type: AdType.VIDEO, name: 'UGC video',
  transcript: 'Okay so I have to tell you about these vitamins because they literally changed my life. ' +
    'I am a mom of three and by 2 PM every day I was just done. Within two weeks I noticed I was not crashing anymore. ' +
    'I actually have energy to play with my kids after work now.',
};

// Empty video (should be filtered out)
const emptyVideo = { id: 'v2', type: AdType.VIDEO, name: 'Silent', transcript: '' };

const sampleAds = [richStaticAd, ugcVideoAd, emptyVideo];

describe('extractFramework', () => {
  const kept = filterAds(sampleAds);

  test('extracts target customer segments', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.targetCustomer).toContain('parent');
    expect(e.targetCustomer).toContain('professional');
    expect(e.targetCustomer).toContain('ingredient-aware researcher');
  });

  test('extracts mass desires', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.massDesire.length).toBeGreaterThan(0);
    expect(e.massDesire).toContain('Sleeping well and waking rested');
  });

  test('extracts pain points', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.painPoints.length).toBeGreaterThan(0);
    const joined = e.painPoints.join(' ').toLowerCase();
    expect(joined).toContain('chronic fatigue');
  });

  test('detects root cause signals', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.rootCause.present).toBe(true);
    const joined = e.rootCause.signals.join(' ').toLowerCase();
    expect(joined).toContain('deficiency');
  });

  test('detects mechanism signals', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.mechanism.present).toBe(true);
    const joined = e.mechanism.signals.join(' ').toLowerCase();
    expect(joined).toContain('synergistic');
  });

  test('detects product delivery signals', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.productDelivery.present).toBe(true);
    const joined = e.productDelivery.signals.join(' ').toLowerCase();
    expect(joined).toContain('magnesium');
  });

  test('detects sophistication strategy', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.sophistication.primaryStrategy).toBeDefined();
    expect(e.sophistication.likelyStage).toBeGreaterThanOrEqual(3);
  });

  test('detects awareness stage', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.awarenessStage.primary).toBeDefined();
  });

  test('detects creative angles in big idea', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.bigIdea.creativeAngles.length).toBeGreaterThan(0);
  });

  test('UGC video has parent segment and pain points', () => {
    const e = extractFramework(kept.find(a => a.id === 'v1'));
    expect(e.targetCustomer).toContain('parent');
    expect(e.painPoints.length).toBeGreaterThan(0);
  });
});

describe('matchSignals', () => {
  test('returns unique matches', () => {
    const text = 'I am tired and exhausted, so tired all the time';
    const matches = matchSignals(text, PAIN_POINT_SIGNALS);
    expect(matches.length).toBeGreaterThan(0);
  });

  test('returns empty array for no matches', () => {
    const matches = matchSignals('hello world nothing here', PAIN_POINT_SIGNALS);
    expect(matches).toEqual([]);
  });
});

describe('analyzePatterns', () => {
  const kept = filterAds(sampleAds);
  const extractions = kept.map(a => extractFramework(a));
  const patterns = analyzePatterns(extractions);

  test('counts total ads', () => {
    expect(patterns.totalAds).toBe(2);
  });

  test('aggregates customer segments', () => {
    expect(patterns.topCustomerSegments.length).toBeGreaterThan(0);
  });

  test('aggregates pain points', () => {
    expect(patterns.topPainPoints.length).toBeGreaterThan(0);
  });

  test('tracks root cause presence', () => {
    expect(patterns.rootCause.adsWithRootCause).toBeGreaterThanOrEqual(1);
  });

  test('computes framework completeness', () => {
    expect(patterns.completeness.length).toBe(2);
    expect(patterns.completeness[0].score).toBeGreaterThan(0);
  });

  test('returns empty result for no ads', () => {
    expect(analyzePatterns([])).toEqual({ totalAds: 0 });
  });
});

describe('generateReport', () => {
  const kept = filterAds(sampleAds);
  const extractions = kept.map(a => extractFramework(a));
  const patterns = analyzePatterns(extractions);
  const filterSummary = { total: 3, kept: 2, skipped: 1, skippedReasons: [{ id: 'v2', type: 'video', reason: 'empty transcript' }] };
  const report = generateReport('Test Brand', filterSummary, patterns, extractions);

  test('produces a string', () => {
    expect(typeof report).toBe('string');
  });

  test('contains brand name', () => {
    expect(report).toContain('TEST BRAND');
  });

  test('contains all DR framework sections', () => {
    expect(report).toContain('TARGET CUSTOMER');
    expect(report).toContain('MASS DESIRE');
    expect(report).toContain('PAIN POINTS');
    expect(report).toContain('ROOT CAUSE');
    expect(report).toContain('MECHANISM');
    expect(report).toContain('PRODUCT DELIVERY');
    expect(report).toContain('MARKET SOPHISTICATION');
    expect(report).toContain('CUSTOMER AWARENESS');
    expect(report).toContain('BIG IDEA');
    expect(report).toContain('FRAMEWORK COMPLETENESS');
    expect(report).toContain('PER-AD FRAMEWORK DETAIL');
  });

  test('contains filter summary', () => {
    expect(report).toContain('FILTER RESULTS');
    expect(report).toContain('empty transcript');
  });
});
