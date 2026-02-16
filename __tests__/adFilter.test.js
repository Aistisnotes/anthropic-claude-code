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

describe('resolveAdCopy – static ads', () => {
  test('rejects static ad with no transcript', () => {
    const ad = { type: AdType.STATIC, transcript: null };
    expect(resolveAdCopy(ad)).toBeNull();
  });

  test('rejects static ad with empty transcript', () => {
    const ad = { type: AdType.STATIC, transcript: '' };
    expect(resolveAdCopy(ad)).toBeNull();
  });

  test('rejects static ad with transcript below 500 words', () => {
    const ad = { type: AdType.STATIC, transcript: makeWords(499) };
    expect(resolveAdCopy(ad)).toBeNull();
  });

  test('accepts static ad with exactly 500 words', () => {
    const transcript = makeWords(500);
    const ad = { type: AdType.STATIC, transcript };
    const result = resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('transcript');
    expect(countWords(result.text)).toBe(500);
  });

  test('accepts static ad with more than 500 words', () => {
    const transcript = makeWords(750);
    const ad = { type: AdType.STATIC, transcript };
    const result = resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('transcript');
  });

  test('static ad ignores primaryCopy – transcript is required', () => {
    const ad = {
      type: AdType.STATIC,
      transcript: makeWords(10),
      primaryCopy: 'Fallback copy here',
    };
    expect(resolveAdCopy(ad)).toBeNull();
  });
});

describe('resolveAdCopy – video ads', () => {
  test('uses transcript when video ad has words', () => {
    const transcript = 'This is a video transcript';
    const ad = {
      type: AdType.VIDEO,
      transcript,
      primaryCopy: 'Primary copy text',
    };
    const result = resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('transcript');
    expect(result.text).toBe(transcript);
  });

  test('falls back to primaryCopy when video transcript is empty', () => {
    const ad = {
      type: AdType.VIDEO,
      transcript: '',
      primaryCopy: 'Use this primary copy instead',
    };
    const result = resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('primary_copy');
    expect(result.text).toBe('Use this primary copy instead');
  });

  test('falls back to primaryCopy when video transcript is null', () => {
    const ad = {
      type: AdType.VIDEO,
      transcript: null,
      primaryCopy: 'Fallback copy',
    };
    const result = resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('primary_copy');
    expect(result.text).toBe('Fallback copy');
  });

  test('falls back to primaryCopy when video transcript is whitespace-only', () => {
    const ad = {
      type: AdType.VIDEO,
      transcript: '   \n\t  ',
      primaryCopy: 'Fallback',
    };
    const result = resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('primary_copy');
    expect(result.text).toBe('Fallback');
  });

  test('rejects video ad when both transcript and primaryCopy are empty', () => {
    const ad = { type: AdType.VIDEO, transcript: '', primaryCopy: '' };
    expect(resolveAdCopy(ad)).toBeNull();
  });

  test('rejects video ad when both transcript and primaryCopy are null', () => {
    const ad = { type: AdType.VIDEO, transcript: null, primaryCopy: null };
    expect(resolveAdCopy(ad)).toBeNull();
  });

  test('video ads do NOT enforce 500-word minimum on transcript', () => {
    const ad = { type: AdType.VIDEO, transcript: 'short' };
    const result = resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('transcript');
    expect(result.text).toBe('short');
  });
});

describe('resolveAdCopy – edge cases', () => {
  test('returns null for null ad', () => {
    expect(resolveAdCopy(null)).toBeNull();
  });

  test('returns null for ad with no type', () => {
    expect(resolveAdCopy({ transcript: 'some text' })).toBeNull();
  });

  test('returns null for unknown ad type', () => {
    const ad = { type: 'banner', transcript: makeWords(600) };
    expect(resolveAdCopy(ad)).toBeNull();
  });
});

describe('filterAds', () => {
  test('returns empty array for non-array input', () => {
    expect(filterAds(null)).toEqual([]);
    expect(filterAds(undefined)).toEqual([]);
    expect(filterAds('not an array')).toEqual([]);
  });

  test('returns empty array when no ads pass', () => {
    const ads = [
      { type: AdType.STATIC, transcript: 'too short' },
      { type: AdType.VIDEO, transcript: '', primaryCopy: '' },
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
    expect(result[0].resolvedCopy.source).toBe('transcript');
  });

  test('keeps video ads that fall back to primary copy', () => {
    const ads = [
      {
        type: AdType.VIDEO,
        transcript: '',
        primaryCopy: 'Primary ad copy',
        id: 'v1',
      },
      {
        type: AdType.VIDEO,
        transcript: '',
        primaryCopy: '',
        id: 'v2',
      },
    ];
    const result = filterAds(ads);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('v1');
    expect(result[0].resolvedCopy.source).toBe('primary_copy');
  });

  test('mixed ads: keeps valid static and video ads', () => {
    const ads = [
      { type: AdType.STATIC, transcript: makeWords(600), id: 's1' },
      { type: AdType.STATIC, transcript: makeWords(50), id: 's2' },
      {
        type: AdType.VIDEO,
        transcript: '',
        primaryCopy: 'Fallback',
        id: 'v1',
      },
      {
        type: AdType.VIDEO,
        transcript: 'Has words',
        primaryCopy: 'Also has copy',
        id: 'v2',
      },
      {
        type: AdType.VIDEO,
        transcript: '',
        primaryCopy: '',
        id: 'v3',
      },
    ];
    const result = filterAds(ads);
    expect(result).toHaveLength(3);
    const ids = result.map((a) => a.id);
    expect(ids).toEqual(['s1', 'v1', 'v2']);
  });
});

describe('MIN_TRANSCRIPT_WORDS_STATIC constant', () => {
  test('is set to 500', () => {
    expect(MIN_TRANSCRIPT_WORDS_STATIC).toBe(500);
  });
});
