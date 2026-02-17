'use strict';

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
 * - Video ads with a non-empty transcript use the transcript as copy.
 * - Video ads with an empty transcript are skipped.
 */
function resolveAdCopy(ad) {
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
    if (wordCount > 0) {
      return { source: 'transcript', text: ad.transcript.trim() };
    }
    // Empty transcript — skip for now
    return null;
  }

  return null;
}

/**
 * Filter a list of ads, returning only those with valid resolved copy.
 * Each returned ad is augmented with a `resolvedCopy` field.
 */
function filterAds(ads) {
  if (!Array.isArray(ads)) {
    return [];
  }

  return ads.reduce((kept, ad) => {
    const resolved = resolveAdCopy(ad);
    if (resolved) {
      kept.push({ ...ad, resolvedCopy: resolved });
    }
    return kept;
  }, []);
}

module.exports = {
  AdType,
  MIN_TRANSCRIPT_WORDS_STATIC,
  countWords,
  resolveAdCopy,
  filterAds,
};
