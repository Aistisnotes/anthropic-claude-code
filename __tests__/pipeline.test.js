'use strict';

const { AdType, filterAds } = require('../src/adFilter');
const {
  extractFramework, splitSentences, classifySentences,
  extractPainPoints, extractRootCause, extractMechanismChain,
  detectTargetCustomer, detectMassDesire, PAIN_CATEGORIES, ROLE_PATTERNS,
} = require('../src/adExtractor');
const { analyzePatterns } = require('../src/patternAnalyzer');
const { generateReport } = require('../src/reportGenerator');

function makeWords(n) {
  return Array.from({ length: n }, (_, i) => `word${i}`).join(' ');
}

// A rich static ad with full DR narrative arc
const richStaticAd = {
  id: 's1', type: AdType.STATIC, name: 'Rich static',
  transcript: 'If you have been struggling with chronic fatigue and brain fog, you are not alone. ' +
    'The real reason you are still tired is not lack of sleep. It is a magnesium deficiency that affects nearly ' +
    '50 percent of adults. The supplement industry has been selling you cheap magnesium oxide that your body ' +
    'cannot absorb. That is why nothing has worked. He had tried countless supplements over the years and none delivered ' +
    'lasting results. Our synergistic approach pairs chelated magnesium glycinate ' +
    'with cofactors like vitamin D3 at 5000 IU and a full-spectrum B-complex. This unique formula was designed to ' +
    'restore cellular energy and cognitive clarity. Unlike other brands, every batch is third-party tested by an ' +
    'independent lab. Clinical studies show 82 percent of participants report better sleep within 30 days. ' +
    'Join over 200,000 customers who trust Glow Daily. Use code SHINE25 for 25% off your first order. ' +
    'Whether you are a busy parent trying to keep up with your kids or a professional looking to optimize ' +
    'performance, this was built for you. Free shipping on orders over $50. ' + makeWords(350),
};

// A short video ad with UGC style (no root cause, no mechanism)
const ugcVideoAd = {
  id: 'v1', type: AdType.VIDEO, name: 'UGC video',
  transcript: 'Okay so I have to tell you about these vitamins because they literally changed my life. ' +
    'I am a mom of three and by 2 PM every day I was just done. My friend told me about Glow Daily and I was like, sure, another supplement. ' +
    'Within two weeks I noticed I was not crashing anymore. ' +
    'I actually have energy to play with my kids after work now. The sleep thing is real too.',
};

// Empty video (filtered out)
const emptyVideo = { id: 'v2', type: AdType.VIDEO, name: 'Silent', transcript: '' };

const sampleAds = [richStaticAd, ugcVideoAd, emptyVideo];

// === Sentence utilities ===
describe('splitSentences', () => {
  test('splits on sentence boundaries', () => {
    const sentences = splitSentences('This is the first sentence here. This is a test sentence. And this is another one!');
    expect(sentences.length).toBe(3);
  });

  test('protects abbreviations', () => {
    const sentences = splitSentences('Dr. Emily Chen explained this. It makes sense.');
    // Should not split on "Dr."
    expect(sentences[0]).toContain('Dr.');
  });

  test('filters out short fragments', () => {
    const sentences = splitSentences('Short. This is a longer sentence that should be kept.');
    expect(sentences.length).toBe(1);
    expect(sentences[0]).toContain('longer');
  });
});

describe('classifySentences', () => {
  test('classifies pain agitation sentences', () => {
    const result = classifySentences(['I was exhausted and burned out every single day.']);
    expect(result[0].primaryRole).toBe('pain_agitation');
  });

  test('classifies root cause sentences', () => {
    const result = classifySentences(['The supplement industry is full of empty promises and cheap fillers.']);
    expect(result[0].primaryRole).toBe('root_cause');
  });

  test('classifies mechanism sentences', () => {
    const result = classifySentences(['We paired chelated magnesium with cofactors that enhance absorption.']);
    expect(result[0].primaryRole).toBe('mechanism_how');
  });

  test('classifies outcome sentences', () => {
    const result = classifySentences(['Within the first two weeks I noticed a dramatic improvement in sleep quality.']);
    expect(result[0].primaryRole).toBe('outcome_promise');
  });
});

// === Pain Points ===
describe('extractPainPoints', () => {
  test('groups pain points by category', () => {
    const result = extractPainPoints('I have chronic fatigue, brain fog, and muscle cramps.');
    expect(result.byCategory.energy_fatigue).toBeDefined();
    expect(result.byCategory.cognitive).toBeDefined();
    expect(result.byCategory.physical).toBeDefined();
  });

  test('returns empty for no matches', () => {
    const result = extractPainPoints('The weather is nice today.');
    expect(Object.keys(result.byCategory)).toHaveLength(0);
  });
});

// === Target Customer ===
describe('detectTargetCustomer', () => {
  test('synthesizes avatar from demographics + psychographics + pain', () => {
    const painCats = { energy_fatigue: { label: 'Energy & Fatigue', matches: ['tired'] } };
    const result = detectTargetCustomer(
      'I am a busy mom of three who tried everything and reads every label.',
      painCats,
    );
    expect(result.avatar).toContain('mother');
    expect(result.avatar).toContain('energy & fatigue');
    expect(result.demographics).toContain('mother');
    expect(result.psychographics.length).toBeGreaterThan(0);
  });

  test('returns fallback for empty text', () => {
    const result = detectTargetCustomer('word word word', {});
    expect(result.avatar).toBe('Avatar not clearly defined in this ad');
  });
});

// === Mass Desire ===
describe('detectMassDesire', () => {
  test('identifies primary desire by frequency', () => {
    const result = detectMassDesire('Sleep is essential. Better sleep quality. Fall asleep faster. Also energy.');
    expect(result.primary).toBe('Sleeping well and waking rested');
    expect(result.all.length).toBeGreaterThan(1);
  });
});

// === extractFramework (full pipeline per ad) ===
describe('extractFramework', () => {
  const kept = filterAds(sampleAds);

  test('extracts synthesized avatar', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.targetCustomer.avatar).toContain('parent');
    expect(e.targetCustomer.avatar).toContain('professional');
  });

  test('extracts pain points by category', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(Object.keys(e.painPoints.byCategory).length).toBeGreaterThan(0);
    expect(e.painPoints.byCategory.energy_fatigue).toBeDefined();
  });

  test('extracts root cause with villain narrative', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.rootCause.present).toBe(true);
    expect(e.rootCause.sentences.length).toBeGreaterThan(0);
    expect(e.rootCause.primaryVillain).toBeDefined();
  });

  test('extracts mechanism causal chain', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.mechanism.present).toBe(true);
    expect(e.mechanism.chain.length).toBeGreaterThan(0);
    const roles = e.mechanism.chain.map(c => c.role);
    expect(roles).toContain('how_this_works');
  });

  test('reports missing chain steps', () => {
    const e = extractFramework(kept.find(a => a.id === 'v1'));
    expect(e.mechanism.missingSteps.length).toBeGreaterThan(0);
  });

  test('identifies mass desire with primary', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.massDesire.primary).toBeDefined();
  });

  test('detects sophistication strategy', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.sophistication.primaryStrategy).toBeDefined();
  });

  test('detects awareness stage', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.awarenessStage.primary).toBeDefined();
  });

  test('synthesizes big idea concept', () => {
    const e = extractFramework(kept.find(a => a.id === 's1'));
    expect(e.bigIdea.concept).toContain('energy & fatigue');
    expect(e.bigIdea.primaryStyle).toBeDefined();
  });

  test('UGC video flags missing root cause and mechanism', () => {
    const e = extractFramework(kept.find(a => a.id === 'v1'));
    expect(e.bigIdea.concept).toContain('not articulated');
  });
});

// === Pattern Analyzer ===
describe('analyzePatterns', () => {
  const kept = filterAds(sampleAds);
  const extractions = kept.map(a => extractFramework(a));
  const patterns = analyzePatterns(extractions);

  test('counts total ads', () => {
    expect(patterns.totalAds).toBe(2);
  });

  test('provides per-ad avatars', () => {
    expect(patterns.avatars.length).toBe(2);
    expect(patterns.avatars[0].avatar).toBeDefined();
  });

  test('identifies primary mass desire', () => {
    expect(patterns.primaryDesire).toBeDefined();
    expect(patterns.primaryDesire.desire).toBeDefined();
    expect(patterns.primaryDesire.pct).toBeDefined();
  });

  test('aggregates pain categories', () => {
    expect(patterns.painCategories.length).toBeGreaterThan(0);
    expect(patterns.painCategories[0].label).toBeDefined();
  });

  test('tracks root cause with villain types', () => {
    expect(patterns.rootCause.adsWithRootCause).toBeGreaterThanOrEqual(1);
    expect(patterns.rootCause.sentences.length).toBeGreaterThan(0);
  });

  test('tracks mechanism chain completeness', () => {
    expect(patterns.mechanism.adsWithMechanism).toBeGreaterThanOrEqual(1);
    expect(patterns.mechanism.commonMissingSteps.length).toBeGreaterThan(0);
  });

  test('computes awareness with split detection', () => {
    expect(patterns.awareness.dominant).toBeDefined();
    expect(typeof patterns.awareness.isSplit).toBe('boolean');
  });

  test('computes completeness with missing element names', () => {
    expect(patterns.completeness.length).toBe(2);
    expect(patterns.completeness[0].present).toBeDefined();
    expect(patterns.completeness[0].missing).toBeDefined();
  });

  test('returns empty result for no ads', () => {
    expect(analyzePatterns([])).toEqual({ totalAds: 0 });
  });
});

// === Report Generator ===
describe('generateReport', () => {
  const kept = filterAds(sampleAds);
  const extractions = kept.map(a => extractFramework(a));
  const patterns = analyzePatterns(extractions);
  const filterSummary = { total: 3, kept: 2, skipped: 1, skippedReasons: [{ id: 'v2', type: 'video', reason: 'empty transcript' }] };
  const report = generateReport('Test Brand', filterSummary, patterns, extractions);

  test('contains brand name', () => {
    expect(report).toContain('TEST BRAND');
  });

  test('contains synthesized avatar section', () => {
    expect(report).toContain('Synthesized Avatars');
    expect(report).toContain('Per-ad avatar:');
  });

  test('contains mass desire with PRIMARY label', () => {
    expect(report).toContain('PRIMARY:');
  });

  test('contains pain points by category', () => {
    expect(report).toContain('by category');
  });

  test('contains villain narrative section', () => {
    expect(report).toContain('Villain Narrative');
    expect(report).toContain('Villain types:');
  });

  test('contains causal chain analysis', () => {
    expect(report).toContain('Causal Chain Analysis');
    expect(report).toContain('COMPLETE chain');
  });

  test('contains awareness with threshold warning or dominant label', () => {
    // Either WARNING for split or DOMINANT for clear stage
    expect(report.includes('WARNING:') || report.includes('DOMINANT:')).toBe(true);
  });

  test('contains strategic gaps section', () => {
    expect(report).toContain('STRATEGIC GAPS');
  });

  test('contains framework completeness with MISSING labels', () => {
    expect(report).toContain('FRAMEWORK COMPLETENESS');
  });

  test('contains per-ad mechanism chains', () => {
    expect(report).toContain('PER-AD MECHANISM CHAINS');
  });

  test('contains filter summary', () => {
    expect(report).toContain('FILTER RESULTS');
    expect(report).toContain('empty transcript');
  });
});
