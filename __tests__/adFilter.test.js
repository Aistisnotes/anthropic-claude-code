'use strict';

const {
  AdType,
  MIN_TRANSCRIPT_WORDS_STATIC,
  countWords,
  resolveAdCopy,
  filterAds,
} = require('../src/adFilter');
const videoAnalyzer = require('../src/videoAnalyzer');

// Helper: generate a string with exactly N words
function makeWords(n) {
  return Array.from({ length: n }, (_, i) => `word${i}`).join(' ');
}

// Mock extractVisualContent so tests don't hit a real pipeline
jest.mock('../src/videoAnalyzer', () => {
  const actual = jest.requireActual('../src/videoAnalyzer');
  return {
    ...actual,
    extractVisualContent: jest.fn(),
  };
});

beforeEach(() => {
  videoAnalyzer.extractVisualContent.mockReset();
  // Default: extraction returns null (nothing found)
  videoAnalyzer.extractVisualContent.mockResolvedValue(null);
});

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
  test('rejects static ad with no transcript', async () => {
    const ad = { type: AdType.STATIC, transcript: null };
    expect(await resolveAdCopy(ad)).toBeNull();
  });

  test('rejects static ad with empty transcript', async () => {
    const ad = { type: AdType.STATIC, transcript: '' };
    expect(await resolveAdCopy(ad)).toBeNull();
  });

  test('rejects static ad with transcript below 500 words', async () => {
    const ad = { type: AdType.STATIC, transcript: makeWords(499) };
    expect(await resolveAdCopy(ad)).toBeNull();
  });

  test('accepts static ad with exactly 500 words', async () => {
    const transcript = makeWords(500);
    const ad = { type: AdType.STATIC, transcript };
    const result = await resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('transcript');
    expect(countWords(result.text)).toBe(500);
  });

  test('accepts static ad with more than 500 words', async () => {
    const transcript = makeWords(750);
    const ad = { type: AdType.STATIC, transcript };
    const result = await resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('transcript');
  });

  test('static ads never trigger visual extraction', async () => {
    const ad = { type: AdType.STATIC, transcript: makeWords(10) };
    await resolveAdCopy(ad);
    expect(videoAnalyzer.extractVisualContent).not.toHaveBeenCalled();
  });
});

// ─── resolveAdCopy: video ads with transcript ───────────────

describe('resolveAdCopy – video ads with transcript', () => {
  test('uses transcript when video ad has words', async () => {
    const transcript = 'This is a video transcript';
    const ad = { type: AdType.VIDEO, transcript };
    const result = await resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('transcript');
    expect(result.text).toBe(transcript);
  });

  test('does not trigger visual extraction when transcript exists', async () => {
    const ad = { type: AdType.VIDEO, transcript: 'has words' };
    await resolveAdCopy(ad);
    expect(videoAnalyzer.extractVisualContent).not.toHaveBeenCalled();
  });

  test('video ads do NOT enforce 500-word minimum on transcript', async () => {
    const ad = { type: AdType.VIDEO, transcript: 'short' };
    const result = await resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('transcript');
    expect(result.text).toBe('short');
  });
});

// ─── resolveAdCopy: video ads with empty transcript (visual extraction) ──

describe('resolveAdCopy – video ads with empty transcript', () => {
  test('attempts visual extraction when transcript is empty', async () => {
    const ad = { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v1.mp4' };
    await resolveAdCopy(ad);
    expect(videoAnalyzer.extractVisualContent).toHaveBeenCalledWith(ad, undefined);
  });

  test('attempts visual extraction when transcript is null', async () => {
    const ad = { type: AdType.VIDEO, transcript: null, videoUrl: 'https://cdn.example.com/v2.mp4' };
    await resolveAdCopy(ad);
    expect(videoAnalyzer.extractVisualContent).toHaveBeenCalledWith(ad, undefined);
  });

  test('attempts visual extraction when transcript is whitespace', async () => {
    const ad = { type: AdType.VIDEO, transcript: '  \t\n ', videoUrl: 'https://cdn.example.com/v3.mp4' };
    await resolveAdCopy(ad);
    expect(videoAnalyzer.extractVisualContent).toHaveBeenCalled();
  });

  test('uses extracted overlay text when available', async () => {
    videoAnalyzer.extractVisualContent.mockResolvedValue({
      overlayText: ['SALE 50% OFF', 'Shop Now'],
      headlines: [],
      sceneDescription: '',
      costCents: 5,
      elapsedMs: 800,
    });
    const ad = { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v.mp4' };
    const result = await resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('visual_extraction');
    expect(result.text).toContain('SALE 50% OFF');
    expect(result.text).toContain('Shop Now');
    expect(result.extraction).toBeDefined();
  });

  test('uses extracted headlines when available', async () => {
    videoAnalyzer.extractVisualContent.mockResolvedValue({
      overlayText: [],
      headlines: ['Summer Collection 2026'],
      sceneDescription: '',
      costCents: 3,
      elapsedMs: 600,
    });
    const ad = { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v.mp4' };
    const result = await resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('visual_extraction');
    expect(result.text).toContain('Summer Collection 2026');
  });

  test('uses scene description when available', async () => {
    videoAnalyzer.extractVisualContent.mockResolvedValue({
      overlayText: [],
      headlines: [],
      sceneDescription: 'A person unboxing a new laptop in a bright room',
      costCents: 10,
      elapsedMs: 1200,
    });
    const ad = { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v.mp4' };
    const result = await resolveAdCopy(ad);
    expect(result).not.toBeNull();
    expect(result.source).toBe('visual_extraction');
    expect(result.text).toContain('A person unboxing a new laptop');
  });

  test('skips ad when extraction returns null (failed)', async () => {
    videoAnalyzer.extractVisualContent.mockResolvedValue(null);
    const ad = { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v.mp4' };
    expect(await resolveAdCopy(ad)).toBeNull();
  });

  test('skips ad when extraction returns empty content', async () => {
    videoAnalyzer.extractVisualContent.mockResolvedValue({
      overlayText: [],
      headlines: [],
      sceneDescription: '',
      costCents: 2,
      elapsedMs: 400,
    });
    const ad = { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v.mp4' };
    expect(await resolveAdCopy(ad)).toBeNull();
  });

  test('passes analyzer options through', async () => {
    const ad = { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v.mp4' };
    const opts = { timeoutMs: 2000, maxCostCents: 10 };
    await resolveAdCopy(ad, opts);
    expect(videoAnalyzer.extractVisualContent).toHaveBeenCalledWith(ad, opts);
  });

  test('no longer falls back to primaryCopy', async () => {
    videoAnalyzer.extractVisualContent.mockResolvedValue(null);
    const ad = {
      type: AdType.VIDEO,
      transcript: '',
      primaryCopy: 'This should NOT be used anymore',
      videoUrl: 'https://cdn.example.com/v.mp4',
    };
    const result = await resolveAdCopy(ad);
    expect(result).toBeNull();
  });
});

// ─── resolveAdCopy: edge cases ──────────────────────────────

describe('resolveAdCopy – edge cases', () => {
  test('returns null for null ad', async () => {
    expect(await resolveAdCopy(null)).toBeNull();
  });

  test('returns null for ad with no type', async () => {
    expect(await resolveAdCopy({ transcript: 'some text' })).toBeNull();
  });

  test('returns null for unknown ad type', async () => {
    const ad = { type: 'banner', transcript: makeWords(600) };
    expect(await resolveAdCopy(ad)).toBeNull();
  });
});

// ─── filterAds ──────────────────────────────────────────────

describe('filterAds', () => {
  test('returns empty array for non-array input', async () => {
    expect(await filterAds(null)).toEqual([]);
    expect(await filterAds(undefined)).toEqual([]);
    expect(await filterAds('not an array')).toEqual([]);
  });

  test('returns empty array when no ads pass', async () => {
    const ads = [
      { type: AdType.STATIC, transcript: 'too short' },
      { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v.mp4' },
    ];
    expect(await filterAds(ads)).toEqual([]);
  });

  test('keeps static ads that meet 500-word minimum', async () => {
    const ads = [
      { type: AdType.STATIC, transcript: makeWords(500), id: 'a1' },
      { type: AdType.STATIC, transcript: makeWords(100), id: 'a2' },
    ];
    const result = await filterAds(ads);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('a1');
    expect(result[0].resolvedCopy.source).toBe('transcript');
  });

  test('keeps video ads where visual extraction succeeds', async () => {
    videoAnalyzer.extractVisualContent.mockResolvedValue({
      overlayText: ['BUY NOW'],
      headlines: ['Big Deal'],
      sceneDescription: 'Product showcase',
      costCents: 5,
      elapsedMs: 500,
    });
    const ads = [
      { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v1.mp4', id: 'v1' },
    ];
    const result = await filterAds(ads);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('v1');
    expect(result[0].resolvedCopy.source).toBe('visual_extraction');
  });

  test('mixed ads: keeps valid static and video ads', async () => {
    // Make extraction succeed for empty-transcript videos
    videoAnalyzer.extractVisualContent.mockResolvedValue({
      overlayText: ['Limited Time'],
      headlines: [],
      sceneDescription: 'Person using product',
      costCents: 8,
      elapsedMs: 900,
    });

    const ads = [
      { type: AdType.STATIC, transcript: makeWords(600), id: 's1' },
      { type: AdType.STATIC, transcript: makeWords(50), id: 's2' },
      { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v1.mp4', id: 'v1' },
      { type: AdType.VIDEO, transcript: 'Has words', id: 'v2' },
    ];
    const result = await filterAds(ads);
    expect(result).toHaveLength(3);
    const ids = result.map((a) => a.id);
    expect(ids).toEqual(['s1', 'v1', 'v2']);
  });

  test('processes video ads concurrently', async () => {
    let concurrentCalls = 0;
    let maxConcurrent = 0;
    videoAnalyzer.extractVisualContent.mockImplementation(async () => {
      concurrentCalls++;
      maxConcurrent = Math.max(maxConcurrent, concurrentCalls);
      await new Promise(r => setTimeout(r, 50));
      concurrentCalls--;
      return { overlayText: ['Text'], headlines: [], sceneDescription: '', costCents: 1, elapsedMs: 50 };
    });

    const ads = [
      { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v1.mp4', id: 'v1' },
      { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v2.mp4', id: 'v2' },
      { type: AdType.VIDEO, transcript: '', videoUrl: 'https://cdn.example.com/v3.mp4', id: 'v3' },
    ];
    await filterAds(ads);
    expect(maxConcurrent).toBeGreaterThan(1);
  });
});

// ─── constants ──────────────────────────────────────────────

describe('MIN_TRANSCRIPT_WORDS_STATIC constant', () => {
  test('is set to 500', () => {
    expect(MIN_TRANSCRIPT_WORDS_STATIC).toBe(500);
  });
});
