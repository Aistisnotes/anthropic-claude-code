'use strict';

const {
  hasUsableContent,
  extractionToText,
  extractVisualContent,
  DEFAULT_OPTIONS,
} = require('../src/videoAnalyzer');

// ─── hasUsableContent ───────────────────────────────────────

describe('hasUsableContent', () => {
  test('returns false for null', () => {
    expect(hasUsableContent(null)).toBe(false);
  });

  test('returns false for undefined', () => {
    expect(hasUsableContent(undefined)).toBe(false);
  });

  test('returns false when all fields are empty', () => {
    expect(hasUsableContent({
      overlayText: [],
      headlines: [],
      sceneDescription: '',
    })).toBeFalsy();
  });

  test('returns false when text arrays contain only whitespace', () => {
    expect(hasUsableContent({
      overlayText: ['  ', '\t'],
      headlines: [''],
      sceneDescription: '  ',
    })).toBe(false);
  });

  test('returns true when overlayText has content', () => {
    expect(hasUsableContent({
      overlayText: ['SALE 50% OFF'],
      headlines: [],
      sceneDescription: '',
    })).toBe(true);
  });

  test('returns true when headlines has content', () => {
    expect(hasUsableContent({
      overlayText: [],
      headlines: ['Summer Collection'],
      sceneDescription: '',
    })).toBe(true);
  });

  test('returns true when sceneDescription has content', () => {
    expect(hasUsableContent({
      overlayText: [],
      headlines: [],
      sceneDescription: 'A person holding a product',
    })).toBe(true);
  });
});

// ─── extractionToText ───────────────────────────────────────

describe('extractionToText', () => {
  test('returns empty string for null', () => {
    expect(extractionToText(null)).toBe('');
  });

  test('returns headlines joined by pipe', () => {
    const result = extractionToText({
      headlines: ['Big Sale', 'Today Only'],
      overlayText: [],
      sceneDescription: '',
    });
    expect(result).toBe('Big Sale | Today Only');
  });

  test('returns overlay text joined by space', () => {
    const result = extractionToText({
      headlines: [],
      overlayText: ['Shop Now', 'Free Shipping'],
      sceneDescription: '',
    });
    expect(result).toBe('Shop Now Free Shipping');
  });

  test('returns scene description', () => {
    const result = extractionToText({
      headlines: [],
      overlayText: [],
      sceneDescription: 'Person opens box',
    });
    expect(result).toBe('Person opens box');
  });

  test('combines all fields with double newlines', () => {
    const result = extractionToText({
      headlines: ['Headline'],
      overlayText: ['Overlay'],
      sceneDescription: 'Scene',
    });
    expect(result).toBe('Headline\n\nOverlay\n\nScene');
  });

  test('skips empty fields', () => {
    const result = extractionToText({
      headlines: [],
      overlayText: ['Only this'],
      sceneDescription: '',
    });
    expect(result).toBe('Only this');
  });
});

// ─── extractVisualContent ───────────────────────────────────

describe('extractVisualContent', () => {
  test('returns null when ad has no videoUrl or videoAsset', async () => {
    const ad = { type: 'video', transcript: '' };
    const result = await extractVisualContent(ad);
    expect(result).toBeNull();
  });

  test('returns extraction result for ad with videoUrl', async () => {
    const ad = { type: 'video', transcript: '', videoUrl: 'https://cdn.example.com/v.mp4' };
    const result = await extractVisualContent(ad);
    // Stub returns empty extraction
    expect(result).not.toBeNull();
    expect(result).toHaveProperty('overlayText');
    expect(result).toHaveProperty('headlines');
    expect(result).toHaveProperty('sceneDescription');
  });

  test('returns extraction result for ad with videoAsset', async () => {
    const ad = { type: 'video', transcript: '', videoAsset: { id: 'abc' } };
    const result = await extractVisualContent(ad);
    expect(result).not.toBeNull();
  });

  test('uses default options', () => {
    expect(DEFAULT_OPTIONS.timeoutMs).toBe(5000);
    expect(DEFAULT_OPTIONS.maxCostCents).toBe(50);
  });
});
