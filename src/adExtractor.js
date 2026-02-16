'use strict';

const { countWords } = require('./adFilter');

/**
 * Common CTA phrases to detect in ad copy.
 */
const CTA_PATTERNS = [
  /\b(?:shop|buy|order|get|try|grab|claim|start|join|sign up|subscribe)\b.*?\b(?:now|today|here|yours)\b/gi,
  /\buse code\s+\w+/gi,
  /\bvisit\s+\S+\.com/gi,
  /\bfree shipping\b/gi,
  /\bmoney[- ]back guarantee\b/gi,
  /\b\d+%\s*off\b/gi,
];

/**
 * Offer/promo patterns.
 */
const OFFER_PATTERNS = [
  /\b(\d+%)\s*off\b/gi,
  /\bcode\s+(\w+)\b/gi,
  /\bfree shipping\b/gi,
  /\bsubscribe and save\b/gi,
  /\bmoney[- ]back guarantee\b/gi,
  /\b(\d+)[- ]day\s+(?:money[- ]back\s+)?guarantee\b/gi,
];

/**
 * Tone/style indicators.
 */
const TONE_MARKERS = {
  clinical: [/\bclinical\b/i, /\bstud(?:y|ies)\b/i, /\bresearch\b/i, /\bpeer[- ]reviewed\b/i, /\bdata\b/i, /\btrial/i, /\bparticipants?\b/i],
  personal: [/\bI\b/, /\bmy\b/i, /\bme\b/, /\bhonestly\b/i, /\bliterally\b/i, /\bmy life\b/i],
  authoritative: [/\bDr\.\b/i, /\bphysician\b/i, /\bcertified\b/i, /\bexpert\b/i, /\bscience\b/i],
  urgency: [/\blimited\b/i, /\btoday\b/i, /\bnow\b/i, /\bdon'?t miss\b/i, /\bhurry\b/i],
  social_proof: [/\b\d[\d,]*\+?\s*(?:customers?|people|users?|members?)\b/i, /\breviews?\b/i, /\btestimonial/i, /\brecommend/i],
  comparative: [/\bvs\.?\b/i, /\bversus\b/i, /\bcompared?\b/i, /\bunlike\b/i, /\bother brands?\b/i, /\bswitch\b/i],
};

/**
 * Extract structural components from a resolved ad's copy text.
 */
function extractComponents(ad) {
  const text = ad.resolvedCopy.text;
  const words = countWords(text);

  // --- CTAs ---
  const ctas = [];
  for (const pat of CTA_PATTERNS) {
    pat.lastIndex = 0;
    let m;
    while ((m = pat.exec(text)) !== null) {
      const cleaned = m[0].trim();
      if (!ctas.includes(cleaned)) ctas.push(cleaned);
    }
  }

  // --- Offers ---
  const offers = [];
  for (const pat of OFFER_PATTERNS) {
    pat.lastIndex = 0;
    let m;
    while ((m = pat.exec(text)) !== null) {
      const cleaned = m[0].trim();
      if (!offers.includes(cleaned)) offers.push(cleaned);
    }
  }

  // --- Tone ---
  const toneScores = {};
  for (const [tone, patterns] of Object.entries(TONE_MARKERS)) {
    let hits = 0;
    for (const pat of patterns) {
      pat.lastIndex = 0;
      if (pat.test(text)) hits++;
    }
    if (hits > 0) toneScores[tone] = hits;
  }
  const dominantTone = Object.entries(toneScores)
    .sort((a, b) => b[1] - a[1])
    .map(([tone]) => tone);

  // --- Key claims / stats ---
  const stats = [];
  const statPat = /\b(\d[\d,.]*%?\s*(?:improvement|increase|reduction|better|report|percent|customers?|participants?|people|mg|IU))\b/gi;
  let sm;
  while ((sm = statPat.exec(text)) !== null) {
    stats.push(sm[0].trim());
  }

  // --- Keywords (top nouns/terms, simple frequency) ---
  const stopWords = new Set(['the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'can', 'shall', 'that', 'this', 'these', 'those', 'it', 'its', 'we', 'our', 'you', 'your', 'they', 'their', 'he', 'she', 'his', 'her', 'not', 'no', 'than', 'more', 'most', 'just', 'also', 'about', 'up', 'out', 'so', 'if', 'as', 'what', 'who', 'how', 'all', 'each', 'every', 'both', 'few', 'some', 'any', 'other', 'into', 'over', 'after', 'before', 'between', 'under', 'again', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'because', 'through', 'during', 'above', 'below', 'own', 'same', 'too', 'very', 'us']);
  const freq = {};
  const wordTokens = text.toLowerCase().replace(/[^a-z0-9\s'-]/g, '').split(/\s+/);
  for (const w of wordTokens) {
    if (w.length < 3 || stopWords.has(w)) continue;
    freq[w] = (freq[w] || 0) + 1;
  }
  const keywords = Object.entries(freq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15)
    .map(([word, count]) => ({ word, count }));

  // --- Opening hook (first sentence) ---
  const firstSentence = text.match(/^[^.!?]+[.!?]/);
  const hook = firstSentence ? firstSentence[0].trim() : text.slice(0, 100).trim();

  return {
    id: ad.id,
    name: ad.name,
    type: ad.type,
    wordCount: words,
    hook,
    ctas,
    offers,
    toneScores,
    dominantTone,
    stats,
    keywords,
  };
}

module.exports = {
  extractComponents,
  CTA_PATTERNS,
  OFFER_PATTERNS,
  TONE_MARKERS,
};
