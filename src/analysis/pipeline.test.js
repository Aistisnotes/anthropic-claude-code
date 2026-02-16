import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  analyzeAd,
  analyzeAdBatch,
  detectHook,
  detectAngles,
  detectOffers,
  classifyCta,
  classifyFormat,
  detectEmotionalRegister,
} from './pipeline.js';

/** Helper to make a mock ad for pipeline tests */
function makeAd(overrides = {}) {
  return {
    id: overrides.id || 'ad_001',
    pageName: overrides.pageName || 'TestBrand',
    primaryTexts: overrides.primaryTexts || ['Default ad text for testing purposes.'],
    headlines: overrides.headlines || ['Test Headline'],
    descriptions: overrides.descriptions || [],
    impressions: overrides.impressions || { lower: 50000, upper: 100000, label: '50K-100K' },
    launchDate: overrides.launchDate || '2026-02-10T00:00:00Z',
    snapshotUrl: overrides.snapshotUrl || null,
    creative: overrides.creative || { fetchStatus: 'skipped', imageUrls: [], videoUrls: [], ctaText: null },
    priority: overrides.priority || 1,
    label: overrides.label || 'ACTIVE_WINNER',
    ...overrides,
  };
}

// ─── detectHook ─────────────────────────────────────────────

describe('detectHook', () => {
  it('detects question hooks', () => {
    const result = detectHook('Do you ever wonder why diets never seem to work for you? This new method changes everything.');
    assert.equal(result.type, 'question');
  });

  it('detects statistic hooks', () => {
    const result = detectHook('97% of users reported visible results within 30 days');
    assert.equal(result.type, 'statistic');
  });

  it('detects bold claim hooks', () => {
    const result = detectHook('Discover the ancient secret that dermatologists hate');
    assert.equal(result.type, 'bold_claim');
  });

  it('detects fear/urgency hooks', () => {
    const result = detectHook("Warning: this ingredient in your kitchen is silently destroying your gut");
    assert.equal(result.type, 'fear_urgency');
  });

  it('detects story hooks', () => {
    const result = detectHook('I was 50 pounds overweight and my doctor told me I had 6 months');
    assert.equal(result.type, 'story');
  });

  it('detects social proof hooks', () => {
    const result = detectHook('Over 2 million customers have already switched to this');
    assert.equal(result.type, 'social_proof');
  });

  it('detects curiosity hooks', () => {
    const result = detectHook("Here's why nobody talks about this simple weight loss trick");
    assert.equal(result.type, 'curiosity');
  });

  it('detects direct address hooks', () => {
    const result = detectHook('Tired of spending hundreds on skincare that does nothing. Try our proven solution today.');
    assert.equal(result.type, 'direct_address');
  });

  it('returns "other" for unclassified hooks', () => {
    const result = detectHook('Amazing product on sale now for limited time.');
    assert.equal(result.type, 'other');
  });

  it('handles empty text', () => {
    const result = detectHook('');
    assert.equal(result.type, 'unknown');
  });
});

// ─── detectAngles ───────────────────────────────────────────

describe('detectAngles', () => {
  it('detects mechanism angle', () => {
    const text = 'Our patented formula uses a breakthrough compound that targets stubborn fat cells. Clinically proven to work in 14 days.';
    const angles = detectAngles(text);
    assert.ok(angles.some((a) => a.angle === 'mechanism'));
  });

  it('detects social proof angle', () => {
    const text = 'Trusted by over 2 million customers. Best seller on Amazon with 50,000 five-star reviews.';
    const angles = detectAngles(text);
    assert.ok(angles.some((a) => a.angle === 'social_proof'));
  });

  it('detects multiple angles', () => {
    const text = 'Doctor recommended and clinically proven. Over a million customers trust our formula. Results in just 7 days or your money back.';
    const angles = detectAngles(text);
    assert.ok(angles.length >= 2);
  });

  it('returns empty for generic text', () => {
    const angles = detectAngles('Hello world this is a test.');
    assert.equal(angles.length, 0);
  });

  it('sorts by confidence (keyword match count)', () => {
    const text = 'Clinically proven patented breakthrough formula with a new compound. Trusted by millions.';
    const angles = detectAngles(text);
    assert.ok(angles[0].confidence >= angles[angles.length - 1].confidence);
  });
});

// ─── detectOffers ───────────────────────────────────────────

describe('detectOffers', () => {
  it('detects discount offers', () => {
    const offers = detectOffers('Get 50% off your first order today!', []);
    assert.ok(offers.some((o) => o.type === 'discount'));
  });

  it('detects free shipping', () => {
    const offers = detectOffers('Order now and get free shipping on all orders.', []);
    assert.ok(offers.some((o) => o.type === 'free_shipping'));
  });

  it('detects guarantee', () => {
    const offers = detectOffers('Try it risk-free with our 60-day money-back guarantee.', []);
    assert.ok(offers.some((o) => o.type === 'guarantee'));
  });

  it('detects limited time offers', () => {
    const offers = detectOffers('Flash sale — today only! Grab yours before midnight.', []);
    assert.ok(offers.some((o) => o.type === 'limited_time'));
  });

  it('checks headlines too', () => {
    const offers = detectOffers('Great product description here.', ['50% OFF — Limited Time']);
    assert.ok(offers.some((o) => o.type === 'discount'));
  });

  it('returns empty when no offers detected', () => {
    const offers = detectOffers('Learn about our product and how it works.', ['Learn More']);
    assert.equal(offers.length, 0);
  });
});

// ─── classifyCta ────────────────────────────────────────────

describe('classifyCta', () => {
  it('classifies shop_now', () => {
    assert.equal(classifyCta('Shop Now', [], ''), 'shop_now');
  });

  it('classifies learn_more', () => {
    assert.equal(classifyCta('Learn More', [], ''), 'learn_more');
  });

  it('classifies sign_up', () => {
    assert.equal(classifyCta('Get Started', [], ''), 'sign_up');
  });

  it('falls back to headline when no CTA text', () => {
    assert.equal(classifyCta(null, ['Shop Now — 50% Off'], ''), 'shop_now');
  });

  it('returns unknown for unclassified CTAs', () => {
    assert.equal(classifyCta(null, ['Wow'], 'Great stuff'), 'unknown');
  });
});

// ─── classifyFormat ─────────────────────────────────────────

describe('classifyFormat', () => {
  it('detects listicle format', () => {
    const text = '• Benefit one\n• Benefit two\n• Benefit three\n• Benefit four';
    assert.equal(classifyFormat(text), 'listicle');
  });

  it('detects testimonial format', () => {
    const text = 'I was skeptical at first. My story begins when I tried this product and my life changed completely. I never thought something so simple could work this well.';
    assert.equal(classifyFormat(text), 'testimonial');
  });

  it('detects long form', () => {
    const text = Array(250).fill('word').join(' ');
    assert.equal(classifyFormat(text), 'long_form');
  });

  it('detects minimal', () => {
    const text = 'Buy now. Limited offer.';
    assert.equal(classifyFormat(text), 'minimal');
  });

  it('returns direct_response for medium text', () => {
    const text = 'This is a standard ad copy that describes the product benefits clearly and directly. It has enough words to be meaningful and substantial but not too many words to be considered a long form piece of content. The messaging is focused and persuasive with a clear call to action.';
    assert.equal(classifyFormat(text), 'direct_response');
  });
});

// ─── detectEmotionalRegister ─────────────────────────────────

describe('detectEmotionalRegister', () => {
  it('detects security values', () => {
    const values = detectEmotionalRegister('Keep your family safe and protected with our trusted, reliable solution for peace of mind.');
    assert.ok(values.some((v) => v.value === 'security'));
  });

  it('detects achievement values', () => {
    const values = detectEmotionalRegister('Achieve your goals and get the best results. Top performance for elite athletes.');
    assert.ok(values.some((v) => v.value === 'achievement'));
  });

  it('detects multiple values', () => {
    const values = detectEmotionalRegister('Safe and reliable for your family. Achieve the best results naturally.');
    assert.ok(values.length >= 2);
  });

  it('returns empty for neutral text', () => {
    const values = detectEmotionalRegister('Click here to view the product page.');
    assert.equal(values.length, 0);
  });
});

// ─── analyzeAd (full pipeline) ──────────────────────────────

describe('analyzeAd', () => {
  it('attaches full analysis to ad record', async () => {
    const ad = makeAd({
      primaryTexts: ['Are you tired of struggling with acne? Our clinically proven formula uses a patented ingredient to clear your skin in 14 days. Over 500,000 happy customers. Order now with free shipping and a 60-day money-back guarantee.'],
      headlines: ['Shop Now — Clear Skin Guaranteed'],
    });

    const result = await analyzeAd(ad);

    assert.ok(result.analysis);
    assert.ok(result.analysis.hook);
    assert.ok(result.analysis.angles.length > 0);
    assert.ok(result.analysis.offers.length > 0);
    assert.equal(typeof result.analysis.format, 'string');
    assert.equal(typeof result.analysis.dominantAngle, 'string');
    assert.equal(typeof result.analysis.dominantEmotion, 'string');
    assert.equal(typeof result.analysis.wordCount, 'number');
  });

  it('handles minimal ad text gracefully', async () => {
    const ad = makeAd({ primaryTexts: ['Buy now.'], headlines: [] });
    const result = await analyzeAd(ad);
    assert.ok(result.analysis);
    assert.equal(result.analysis.format, 'minimal');
  });
});

// ─── analyzeAdBatch ─────────────────────────────────────────

describe('analyzeAdBatch', () => {
  it('analyzes a batch and produces summary stats', async () => {
    const ads = [
      makeAd({ id: 'a1', primaryTexts: ['Are you struggling? Our clinically proven breakthrough formula works in 14 days.'], headlines: ['Shop Now'] }),
      makeAd({ id: 'a2', primaryTexts: ['I was skeptical but this product changed my story. My journey to clear skin started here.'], headlines: ['Learn More'] }),
      makeAd({ id: 'a3', primaryTexts: ['97% of users saw results. Trusted by millions of customers worldwide. Best seller rated.'], headlines: ['Get Started'] }),
    ];

    const { analyzed, summary } = await analyzeAdBatch(ads);

    assert.equal(analyzed.length, 3);
    assert.equal(summary.totalAnalyzed, 3);
    assert.ok(typeof summary.hookDistribution === 'object');
    assert.ok(typeof summary.angleDistribution === 'object');
    assert.ok(typeof summary.formatDistribution === 'object');
    assert.ok(typeof summary.avgWordCount === 'number');
  });
});
