'use strict';

const {
  AdType,
  MIN_TRANSCRIPT_WORDS_STATIC,
  countWords,
  resolveAdCopy,
  filterAds,
} = require('../src/adFilter');

// Helper: generate a string with exactly N words
function makeWords(n) {
  return Array.from({ length: n }, (_, i) => `word${i}`).join(' ');
}

// ─── countWords ──────────────────────────────────────────────

describe('countWords', () => {
  test('returns 0 for null/undefined/empty', () => {
    expect(countWords(null)).toBe(0);
    expect(countWords(undefined)).toBe(0);
    expect(countWords('')).toBe(0);
    expect(countWords('   ')).toBe(0);
  });

  test('returns 0 for non-string input', () => {
    expect(countWords(42)).toBe(0);
    expect(countWords({})).toBe(0);
  });

  test('counts single word', () => {
    expect(countWords('hello')).toBe(1);
  });

  test('counts multiple words separated by spaces', () => {
    expect(countWords('one two three')).toBe(3);
  });

  test('handles extra whitespace', () => {
    expect(countWords('  one   two   three  ')).toBe(3);
  });

  test('handles tabs and newlines', () => {
    expect(countWords('one\ttwo\nthree')).toBe(3);
  });
});

// ─── resolveAdCopy: static ads ──────────────────────────────

describe('resolveAdCopy – static ads', () => {
  test('rejects static ad with no transcript', () => {
    expect(resolveAdCopy({ type: AdType.STATIC, transcript: null })).toBeNull();
  });

  test('rejects static ad with empty transcript', () => {
    expect(resolveAdCopy({ type: AdType.STATIC, transcript: '' })).toBeNull();
  });

  test('rejects static ad with transcript below 500 words', () => {
    expect(resolveAdCopy({ type: AdType.STATIC, transcript: makeWords(499) })).toBeNull();
  });

  test('accepts static ad with exactly 500 words', () => {
    const result = resolveAdCopy({ type: AdType.STATIC, transcript: makeWords(500) });
    expect(result).not.toBeNull();
    expect(result.source).toBe('transcript');
    expect(countWords(result.text)).toBe(500);
  });

  test('accepts static ad with more than 500 words', () => {
    const result = resolveAdCopy({ type: AdType.STATIC, transcript: makeWords(750) });
    expect(result).not.toBeNull();
    expect(result.source).toBe('transcript');
  });
});

// ─── resolveAdCopy: video ads ───────────────────────────────

describe('resolveAdCopy – video ads', () => {
  test('uses transcript when video ad has words', () => {
    const result = resolveAdCopy({ type: AdType.VIDEO, transcript: 'Buy our product now' });
    expect(result).not.toBeNull();
    expect(result.source).toBe('transcript');
    expect(result.text).toBe('Buy our product now');
  });

  test('video ads do NOT enforce 500-word minimum', () => {
    const result = resolveAdCopy({ type: AdType.VIDEO, transcript: 'short' });
    expect(result).not.toBeNull();
    expect(result.source).toBe('transcript');
  });

  test('skips video ad with empty transcript', () => {
    expect(resolveAdCopy({ type: AdType.VIDEO, transcript: '' })).toBeNull();
  });

  test('skips video ad with null transcript', () => {
    expect(resolveAdCopy({ type: AdType.VIDEO, transcript: null })).toBeNull();
  });

  test('skips video ad with whitespace-only transcript', () => {
    expect(resolveAdCopy({ type: AdType.VIDEO, transcript: '  \t\n ' })).toBeNull();
  });

  test('ignores primaryCopy — not used as fallback', () => {
    const ad = { type: AdType.VIDEO, transcript: '', primaryCopy: 'Should be ignored' };
    expect(resolveAdCopy(ad)).toBeNull();
  });
});

// ─── resolveAdCopy: edge cases ──────────────────────────────

describe('resolveAdCopy – edge cases', () => {
  test('returns null for null ad', () => {
    expect(resolveAdCopy(null)).toBeNull();
  });

  test('returns null for ad with no type', () => {
    expect(resolveAdCopy({ transcript: 'text' })).toBeNull();
  });

  test('returns null for unknown ad type', () => {
    expect(resolveAdCopy({ type: 'banner', transcript: makeWords(600) })).toBeNull();
  });
});

// ─── filterAds ──────────────────────────────────────────────

describe('filterAds', () => {
  test('returns empty array for non-array input', () => {
    expect(filterAds(null)).toEqual([]);
    expect(filterAds(undefined)).toEqual([]);
    expect(filterAds('not an array')).toEqual([]);
  });

  test('returns empty array when no ads pass', () => {
    const ads = [
      { type: AdType.STATIC, transcript: 'too short' },
      { type: AdType.VIDEO, transcript: '' },
    ];
    expect(filterAds(ads)).toEqual([]);
  });

  test('keeps static ads that meet 500-word minimum', () => {
    const ads = [
      { type: AdType.STATIC, transcript: makeWords(500), id: 'a1' },
      { type: AdType.STATIC, transcript: makeWords(100), id: 'a2' },
    ];
    const result = filterAds(ads);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('a1');
  });

  test('keeps video ads with transcripts, skips empty ones', () => {
    const ads = [
      { type: AdType.VIDEO, transcript: 'Has words', id: 'v1' },
      { type: AdType.VIDEO, transcript: '', id: 'v2' },
      { type: AdType.VIDEO, transcript: null, id: 'v3' },
    ];
    const result = filterAds(ads);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('v1');
  });

  test('mixed ads: filters correctly', () => {
    const ads = [
      { type: AdType.STATIC, transcript: makeWords(600), id: 's1' },
      { type: AdType.STATIC, transcript: makeWords(50), id: 's2' },
      { type: AdType.VIDEO, transcript: 'Has words', id: 'v1' },
      { type: AdType.VIDEO, transcript: '', id: 'v2' },
    ];
    const result = filterAds(ads);
    expect(result).toHaveLength(2);
    expect(result.map(a => a.id)).toEqual(['s1', 'v1']);
  });
});

// ─── constants ──────────────────────────────────────────────

describe('MIN_TRANSCRIPT_WORDS_STATIC constant', () => {
  test('is set to 500', () => {
    expect(MIN_TRANSCRIPT_WORDS_STATIC).toBe(500);
  });
});
