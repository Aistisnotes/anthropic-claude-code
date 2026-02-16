'use strict';

const DEFAULT_OPTIONS = {
  timeoutMs: 5000,
  maxCostCents: 50,
};

/**
 * Result of analyzing a video's visual content.
 * @typedef {Object} VisualExtraction
 * @property {string[]} overlayText  - Text overlays found on screen (titles, captions, CTAs)
 * @property {string[]} headlines    - Prominent headline text rendered on top of video
 * @property {string}   sceneDescription - Brief description of what's happening visually
 * @property {number}   costCents    - Cost incurred for this extraction
 * @property {number}   elapsedMs    - Time taken for extraction
 */

/**
 * Extract visual content from a video ad (overlay text, headlines, scene content).
 *
 * This is the integration point for frame extraction + OCR/vision analysis.
 * The default implementation is a stub — wire in your actual vision pipeline
 * (e.g. frame sampling → OCR, or a vision-language model API call).
 *
 * @param {Object} ad - The video ad object. Expected fields: ad.videoUrl or ad.videoAsset
 * @param {Object} [options]
 * @param {number} [options.timeoutMs=5000]   - Max time allowed for extraction
 * @param {number} [options.maxCostCents=50]  - Max cost budget in cents
 * @returns {Promise<VisualExtraction|null>}  - Extracted content, or null if extraction failed
 */
async function extractVisualContent(ad, options = {}) {
  const opts = { ...DEFAULT_OPTIONS, ...options };

  const start = Date.now();

  try {
    const result = await _analyzeFrames(ad, opts);
    const elapsed = Date.now() - start;

    if (elapsed > opts.timeoutMs) {
      return null;
    }
    if (result && result.costCents > opts.maxCostCents) {
      return null;
    }

    return result;
  } catch {
    return null;
  }
}

/**
 * Internal: run frame analysis pipeline.
 * Replace this stub with your actual implementation.
 *
 * @param {Object} ad
 * @param {Object} opts
 * @returns {Promise<VisualExtraction|null>}
 */
async function _analyzeFrames(ad, opts) {
  // --- STUB: replace with real vision pipeline ---
  // In production this would:
  //   1. Sample key frames from ad.videoUrl / ad.videoAsset
  //   2. Run OCR on each frame to extract overlay text & headlines
  //   3. Run a vision model to describe the scene
  //   4. Track cost and abort if budget exceeded

  if (!ad.videoUrl && !ad.videoAsset) {
    return null;
  }

  // Simulate extraction — in tests this gets mocked
  return {
    overlayText: [],
    headlines: [],
    sceneDescription: '',
    costCents: 0,
    elapsedMs: 0,
  };
}

/**
 * Check whether a visual extraction produced usable learnings.
 * At minimum we need some text or a scene description.
 */
function hasUsableContent(extraction) {
  if (!extraction) return false;

  const hasText =
    (extraction.overlayText && extraction.overlayText.some(t => t.trim().length > 0)) ||
    (extraction.headlines && extraction.headlines.some(t => t.trim().length > 0));
  const hasScene =
    extraction.sceneDescription && extraction.sceneDescription.trim().length > 0;

  return hasText || hasScene;
}

/**
 * Build a combined text string from a visual extraction for use as ad copy/learnings.
 */
function extractionToText(extraction) {
  if (!extraction) return '';

  const parts = [];

  if (extraction.headlines && extraction.headlines.length > 0) {
    parts.push(extraction.headlines.filter(h => h.trim()).join(' | '));
  }
  if (extraction.overlayText && extraction.overlayText.length > 0) {
    parts.push(extraction.overlayText.filter(t => t.trim()).join(' '));
  }
  if (extraction.sceneDescription && extraction.sceneDescription.trim()) {
    parts.push(extraction.sceneDescription.trim());
  }

  return parts.join('\n\n');
}

module.exports = {
  DEFAULT_OPTIONS,
  extractVisualContent,
  hasUsableContent,
  extractionToText,
  // Exposed for test mocking
  _analyzeFrames,
};
