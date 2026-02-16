/**
 * Ad analysis pipeline.
 *
 * Runs heuristic-based analysis on enriched ad records to extract:
 *   - Hook type (question, statistic, story, bold claim, fear/urgency)
 *   - Messaging angle (mechanism, social proof, scarcity, transformation, problem-agitate)
 *   - Offer structure (discount, free trial, guarantee, bonus, shipping)
 *   - CTA classification
 *   - Ad format (listicle, testimonial, story, direct response, educational)
 *   - Emotional register (Schwartz values: security, achievement, hedonism, etc.)
 *
 * This is text-based pattern matching — no LLM required. Good enough for
 * market-level pattern detection and gap analysis.
 */

// ─── Hook Detection ──────────────────────────────────────────

const HOOK_PATTERNS = [
  { type: 'question', test: (t) => /^[^.!]{5,}\?/.test(t) },
  { type: 'statistic', test: (t) => /^\d|^["\u201c]?\d/.test(t) || /\d+%/.test(t.slice(0, 80)) },
  { type: 'bold_claim', test: (t) => /^(?:the|this|finally|introducing|discover|meet|say goodbye)/i.test(t) },
  { type: 'fear_urgency', test: (t) => /^(?:warning|don't|stop|before it's|last chance|hurry|urgent)/i.test(t) },
  { type: 'story', test: (t) => /^(?:i was|when i|my (?:doctor|wife|husband|friend)|after years|i never)/i.test(t) },
  { type: 'social_proof', test: (t) => /^(?:over \d|join \d|\d+ (?:million|thousand|people|customers))/i.test(t) },
  { type: 'curiosity', test: (t) => /^(?:what if|imagine|here's (?:the|why)|the secret|you won't believe|nobody talks)/i.test(t) },
  { type: 'direct_address', test: (t) => /^(?:you |your |if you|tired of|struggling with|ready to)/i.test(t) },
];

/**
 * Detect the hook type from the first line of primary text.
 */
function detectHook(primaryText) {
  if (!primaryText) return { type: 'unknown', firstLine: '' };

  // Extract first sentence (up to the first sentence-ending punctuation)
  const sentenceMatch = primaryText.match(/^(.+?[.!?\n])/s);
  const firstSentence = sentenceMatch ? sentenceMatch[1].trim() : primaryText.split('\n')[0].trim();
  const firstLine = firstSentence.replace(/[.!?]+$/, '').trim();

  // Check if first sentence is a question
  if (firstSentence.endsWith('?')) {
    return { type: 'question', firstLine: firstSentence };
  }

  for (const pattern of HOOK_PATTERNS) {
    if (pattern.test(firstLine)) {
      return { type: pattern.type, firstLine };
    }
  }
  return { type: 'other', firstLine };
}

// ─── Messaging Angle Detection ───────────────────────────────

const ANGLE_KEYWORDS = {
  mechanism: [
    'how it works', 'the secret', 'the reason', 'scientifically',
    'clinically proven', 'patented', 'breakthrough', 'technology',
    'formula', 'ingredient', 'compound', 'enzyme', 'peptide',
  ],
  social_proof: [
    'reviews', 'rated', 'customers', 'trusted by', 'as seen',
    'featured in', 'recommended by', 'million', 'best seller',
    'award', '#1', 'doctor recommended', 'expert',
  ],
  transformation: [
    'before and after', 'in just', 'within days', 'results',
    'transform', 'changed my life', 'never looked back', 'finally',
    'journey', 'amazing results', 'incredible',
  ],
  problem_agitate: [
    'tired of', 'struggling', 'frustrated', 'pain', 'suffer',
    'embarrassing', 'no matter what', 'nothing works', 'sick of',
    'fed up', 'desperate', 'nightmare',
  ],
  scarcity: [
    'limited', 'only', 'last chance', 'selling fast', 'almost gone',
    'while supplies', 'exclusive', 'ends today', 'hurry', 'final',
  ],
  authority: [
    'doctor', 'scientist', 'research', 'study', 'university',
    'harvard', 'fda', 'clinical', 'medical', 'expert', 'phd',
  ],
  educational: [
    'did you know', 'most people', 'the truth', 'myth', 'fact',
    'research shows', 'according to', 'studies show', 'learn',
  ],
};

/**
 * Detect messaging angles present in the ad text.
 * Returns all detected angles with confidence (keyword match count).
 */
function detectAngles(primaryText) {
  if (!primaryText) return [];

  const lower = primaryText.toLowerCase();
  const angles = [];

  for (const [angle, keywords] of Object.entries(ANGLE_KEYWORDS)) {
    const matches = keywords.filter((kw) => lower.includes(kw));
    if (matches.length > 0) {
      angles.push({ angle, confidence: matches.length, matchedKeywords: matches });
    }
  }

  // Sort by confidence
  angles.sort((a, b) => b.confidence - a.confidence);
  return angles;
}

// ─── Offer Detection ─────────────────────────────────────────

const OFFER_PATTERNS = [
  { type: 'discount', pattern: /(\d+%?\s*off|\$\d+\s*off|save\s*\$?\d+|half\s*price)/i },
  { type: 'free_trial', pattern: /(free trial|try (?:it )?free|risk.?free|sample free)/i },
  { type: 'guarantee', pattern: /(money.?back|guarantee|full refund|\d+.?day.?(?:return|refund))/i },
  { type: 'bonus', pattern: /(free (?:gift|bonus|shipping)|buy (?:one|1).+get|bogo|bonus)/i },
  { type: 'free_shipping', pattern: /(free shipping|free delivery|ships free)/i },
  { type: 'bundle', pattern: /(bundle|pack of|set of|(?:buy|get) \d+)/i },
  { type: 'subscription', pattern: /(subscribe|monthly|auto.?ship|membership)/i },
  { type: 'limited_time', pattern: /(today only|limited time|flash sale|ends (?:soon|today|tonight))/i },
];

/**
 * Detect offer types present in ad text + headlines.
 */
function detectOffers(primaryText, headlines) {
  const combined = [primaryText || '', ...(headlines || [])].join(' ');
  const offers = [];

  for (const { type, pattern } of OFFER_PATTERNS) {
    const match = combined.match(pattern);
    if (match) {
      offers.push({ type, matched: match[1] });
    }
  }

  return offers;
}

// ─── CTA Classification ─────────────────────────────────────

const CTA_MAP = {
  shop_now: /shop now|buy now|order now|get yours/i,
  learn_more: /learn more|find out|discover|see how/i,
  sign_up: /sign up|join|register|get started|start now/i,
  claim_offer: /claim|redeem|grab|unlock|get deal/i,
  watch: /watch|see|view|play/i,
  download: /download|get app|install/i,
  contact: /contact|call|message|book|schedule/i,
};

/**
 * Classify the CTA from button text, headline, or ad text.
 */
function classifyCta(ctaText, headlines, primaryText) {
  const sources = [ctaText, ...(headlines || []), primaryText || ''].filter(Boolean);
  const combined = sources.join(' ');

  for (const [classification, pattern] of Object.entries(CTA_MAP)) {
    if (pattern.test(combined)) {
      return classification;
    }
  }
  return 'unknown';
}

// ─── Ad Format Classification ────────────────────────────────

/**
 * Classify the ad copy format.
 */
function classifyFormat(primaryText) {
  if (!primaryText) return 'minimal';

  const lines = primaryText.split('\n').filter((l) => l.trim());
  const bulletCount = (primaryText.match(/^[\s]*[•✓✔☑→►▸\-★⭐]/gm) || []).length;
  const emojiDensity = (primaryText.match(/[\u{1F300}-\u{1FAFF}]/gu) || []).length;
  const words = primaryText.split(/\s+/).length;

  if (bulletCount >= 3) return 'listicle';
  if (/\b(?:i was|my (?:story|journey)|when i|i never thought)\b/i.test(primaryText)) return 'testimonial';
  if (/\b(?:step \d|first|then|next|finally)\b/i.test(primaryText) && lines.length >= 4) return 'how_to';
  if (words > 200) return 'long_form';
  if (words < 30) return 'minimal';
  if (emojiDensity > 3) return 'emoji_heavy';
  return 'direct_response';
}

// ─── Emotional Register (Schwartz Values) ────────────────────

const SCHWARTZ_KEYWORDS = {
  security: ['safe', 'protect', 'secure', 'worry', 'risk', 'peace of mind', 'trusted', 'reliable'],
  achievement: ['success', 'achieve', 'goal', 'perform', 'best', 'winning', 'elite', 'top', 'results'],
  hedonism: ['enjoy', 'pleasure', 'delicious', 'love', 'indulge', 'treat', 'luxury', 'bliss'],
  stimulation: ['new', 'exciting', 'revolutionary', 'cutting-edge', 'game-changer', 'breakthrough'],
  self_direction: ['choose', 'freedom', 'your way', 'control', 'independent', 'custom', 'personalize'],
  benevolence: ['family', 'loved ones', 'care', 'give', 'help', 'support', 'community', 'together'],
  conformity: ['everyone', 'normal', 'all', 'join', 'popular', 'trending', 'viral', 'millions'],
  tradition: ['natural', 'ancient', 'traditional', 'heritage', 'original', 'time-tested', 'classic'],
  power: ['exclusive', 'premium', 'vip', 'status', 'elite', 'first', 'priority', 'dominant'],
  universalism: ['sustainable', 'organic', 'planet', 'eco', 'ethical', 'fair', 'clean', 'pure'],
};

/**
 * Detect dominant Schwartz value orientations in ad text.
 */
function detectEmotionalRegister(primaryText) {
  if (!primaryText) return [];

  const lower = primaryText.toLowerCase();
  const values = [];

  for (const [value, keywords] of Object.entries(SCHWARTZ_KEYWORDS)) {
    const matches = keywords.filter((kw) => lower.includes(kw));
    if (matches.length > 0) {
      values.push({ value, strength: matches.length, keywords: matches });
    }
  }

  values.sort((a, b) => b.strength - a.strength);
  return values;
}

// ─── Main Pipeline ───────────────────────────────────────────

/**
 * Run the full analysis pipeline on a single ad.
 *
 * @param {object} ad - Enriched ad record (with creative data if available)
 * @returns {object} Ad record with `.analysis` attached
 */
export function analyzeAd(ad) {
  const primaryText = ad.primaryTexts?.[0] || '';
  const ctaText = ad.creative?.ctaText || null;

  const analysis = {
    hook: detectHook(primaryText),
    angles: detectAngles(primaryText),
    offers: detectOffers(primaryText, ad.headlines),
    cta: classifyCta(ctaText, ad.headlines, primaryText),
    format: classifyFormat(primaryText),
    emotionalRegister: detectEmotionalRegister(primaryText),
    hasCreative: ad.creative?.fetchStatus === 'success',
    imageCount: ad.creative?.imageUrls?.length || 0,
    videoCount: ad.creative?.videoUrls?.length || 0,
    landingPage: ad.creative?.landingPageUrl || null,
    wordCount: primaryText.split(/\s+/).filter(Boolean).length,
  };

  // Derive dominant angle (highest confidence)
  analysis.dominantAngle = analysis.angles[0]?.angle || 'unknown';
  // Derive dominant emotion
  analysis.dominantEmotion = analysis.emotionalRegister[0]?.value || 'unknown';

  return { ...ad, analysis };
}

/**
 * Run the analysis pipeline on a batch of ads.
 *
 * @param {Array} ads - Enriched ad records
 * @returns {{ analyzed: Array, summary: object }}
 */
export function analyzeAdBatch(ads) {
  const analyzed = ads.map(analyzeAd);

  // Build batch summary stats
  const summary = {
    totalAnalyzed: analyzed.length,
    hookDistribution: countBy(analyzed, (a) => a.analysis.hook.type),
    angleDistribution: countBy(analyzed, (a) => a.analysis.dominantAngle),
    formatDistribution: countBy(analyzed, (a) => a.analysis.format),
    emotionDistribution: countBy(analyzed, (a) => a.analysis.dominantEmotion),
    ctaDistribution: countBy(analyzed, (a) => a.analysis.cta),
    offerTypes: countByFlat(analyzed, (a) => a.analysis.offers.map((o) => o.type)),
    avgWordCount: Math.round(analyzed.reduce((s, a) => s + a.analysis.wordCount, 0) / (analyzed.length || 1)),
    withCreative: analyzed.filter((a) => a.analysis.hasCreative).length,
    withVideo: analyzed.filter((a) => a.analysis.videoCount > 0).length,
    withImages: analyzed.filter((a) => a.analysis.imageCount > 0).length,
  };

  return { analyzed, summary };
}

/**
 * Count occurrences of a derived key across an array.
 */
function countBy(arr, keyFn) {
  const counts = {};
  for (const item of arr) {
    const key = keyFn(item);
    counts[key] = (counts[key] || 0) + 1;
  }
  return counts;
}

/**
 * Count occurrences from an array-valued key function.
 */
function countByFlat(arr, keyFn) {
  const counts = {};
  for (const item of arr) {
    for (const key of keyFn(item)) {
      counts[key] = (counts[key] || 0) + 1;
    }
  }
  return counts;
}

export { detectHook, detectAngles, detectOffers, classifyCta, classifyFormat, detectEmotionalRegister };
