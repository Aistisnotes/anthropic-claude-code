'use strict';

const videoAnalyzer = require('./videoAnalyzer');

const MIN_TRANSCRIPT_WORDS_STATIC = 500;

const AdType = {
  STATIC: 'static',
  VIDEO: 'video',
};

/**
 * Count words in a transcript string.
 * Returns 0 for empty/null/undefined input.
 */
function countWords(transcript) {
  if (!transcript || typeof transcript !== 'string') {
    return 0;
  }
  const trimmed = transcript.trim();
  if (trimmed.length === 0) {
    return 0;
  }
  return trimmed.split(/\s+/).length;
}

/**
 * Resolve the copy text for an ad based on its type and transcript.
 *
 * Rules:
 * - Static ads require a transcript with at least 500 words.
 *   If the transcript is below the minimum, the ad is rejected (returns null).
 * - Video ads with a non-empty transcript use the transcript as copy.
 * - Video ads with a zero-word transcript attempt visual extraction
 *   (overlay text, headlines, scene content). If extraction fails,
 *   times out, or exceeds cost budget, the ad is skipped.
 *
 * @param {Object} ad
 * @param {Object} [analyzerOptions] - Options passed to extractVisualContent
 * @returns {Promise<Object|null>}
 */
async function resolveAdCopy(ad, analyzerOptions) {
  if (!ad || !ad.type) {
    return null;
  }

  const wordCount = countWords(ad.transcript);

  if (ad.type === AdType.STATIC) {
    if (wordCount < MIN_TRANSCRIPT_WORDS_STATIC) {
      return null;
    }
    return { source: 'transcript', text: ad.transcript.trim() };
  }

  if (ad.type === AdType.VIDEO) {
    // Videos with transcript: use it directly (no word minimum)
    if (wordCount > 0) {
      return { source: 'transcript', text: ad.transcript.trim() };
    }

    // Empty transcript: try to extract visual content from the video itself
    const extraction = await videoAnalyzer.extractVisualContent(ad, analyzerOptions);
    if (videoAnalyzer.hasUsableContent(extraction)) {
      return {
        source: 'visual_extraction',
        text: videoAnalyzer.extractionToText(extraction),
        extraction,
      };
    }

    // Nothing usable — skip this ad
    return null;
  }

  return null;
}

/**
 * Filter a list of ads, returning only those with valid resolved copy.
 * Each returned ad is augmented with a `resolvedCopy` field.
 *
 * @param {Object[]} ads
 * @param {Object} [analyzerOptions] - Options passed to extractVisualContent
 * @returns {Promise<Object[]>}
 */
async function filterAds(ads, analyzerOptions) {
  if (!Array.isArray(ads)) {
    return [];
  }

  const results = await Promise.all(
    ads.map(async (ad) => {
      const resolved = await resolveAdCopy(ad, analyzerOptions);
      return resolved ? { ...ad, resolvedCopy: resolved } : null;
    })
  );

  return results.filter(Boolean);
}

module.exports = {
  AdType,
  MIN_TRANSCRIPT_WORDS_STATIC,
  countWords,
  resolveAdCopy,
  filterAds,
};
