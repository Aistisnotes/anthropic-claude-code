'use strict';

const { countWords } = require('./adFilter');

// ============================================================================
// DR FRAMEWORK EXTRACTION
//
// Extracts direct response marketing framework elements from ad copy:
// 1. Target Customer          5. Mechanism (the "new mechanism")
// 2. Mass Desire              6. Product Delivery Mechanism
// 3. Pain Points & Symptoms   7. Market Sophistication Stage
// 4. Root Cause               8. Customer Awareness Stage
//                             9. Big Idea
// ============================================================================

// --- Signal patterns for each framework element ---

const PAIN_POINT_SIGNALS = [
  /(?:tired|exhausted|fatigued|burned out|no energy|low energy|energy crash)/gi,
  /(?:can'?t sleep|poor sleep|insomnia|wake up at \d|trouble sleeping|not sleeping)/gi,
  /(?:brain fog|can'?t focus|can'?t concentrate|mental clarity|foggy|unfocused)/gi,
  /(?:stressed|anxiety|anxious|overwhelmed|irritable)/gi,
  /(?:muscle cramps?|soreness|joint (?:pain|stiffness)|inflammation)/gi,
  /(?:weight gain|bloating|digestive|gut (?:issues|problems)|GI discomfort)/gi,
  /(?:hair loss|skin (?:issues|problems)|brittle nails|aging)/gi,
  /(?:tried everything|nothing (?:works|worked)|frustrated|skeptical|given up)/gi,
  /(?:afternoon (?:crash|slump)|2\s*PM|3\s*PM|midday)/gi,
  /(?:chronic fatigue|always tired|constantly exhausted)/gi,
];

const ROOT_CAUSE_SIGNALS = [
  // Villain patterns - externalizing blame
  /(?:the (?:real|true|actual|hidden|root) (?:reason|cause|problem|issue))/gi,
  /(?:what (?:they|no one|nobody) (?:told|tells|mentioned|explained))/gi,
  /(?:the (?:supplement|food|health|wellness|pharma) industry)/gi,
  /(?:misinformation|misleading|bad advice|wrong information)/gi,
  // Hidden biological mechanisms
  /(?:deficien(?:cy|t)|depleted|lacking|not (?:getting|absorbing) enough)/gi,
  /(?:cortisol|inflammation|hormonal? (?:imbalance|balance)|insulin)/gi,
  /(?:gut (?:microbiome|health|flora)|mitochondrial?|cellular)/gi,
  /(?:bioavailab(?:ility|le)|absorb(?:ed|tion)|dissolve|break(?:s|ing)? down)/gi,
  // System blame
  /(?:modern (?:agriculture|diet|lifestyle)|soil (?:depletion|minerals))/gi,
  /(?:generic|cheap|underdosed|poorly (?:sourced|formulated)|fillers)/gi,
  /(?:proprietary blends? that hide|artificial|synthetic)/gi,
];

const MECHANISM_SIGNALS = [
  // "How it works" / method language
  /(?:that'?s (?:why|how|exactly)|here'?s (?:how|what|the (?:thing|key|secret)))/gi,
  /(?:the (?:key|secret|trick|answer|solution|method|approach|system) (?:is|was))/gi,
  /(?:works? by|designed to|formulated to|engineered to|built to)/gi,
  /(?:targets?|addresses?|solves?|fixes?|corrects?|reverses?|restores?) (?:the )/gi,
  // Unique process / approach
  /(?:synergistic|proprietary|unique (?:blend|formula|approach|method))/gi,
  /(?:paired (?:it |them )?with|combined with|stacked with)/gi,
  /(?:cofactors?|chelated|methylated|full[- ]spectrum)/gi,
  /(?:unlike (?:other|most|typical)|what (?:sets|makes) .{1,60}? (?:different|apart|unique))/gi,
];

const PRODUCT_DELIVERY_SIGNALS = [
  // Ingredients
  /(?:magnesium|vitamin [A-Z]\d?|CoQ10|zinc|selenium|B-?complex|mushroom|lion'?s mane|reishi|adaptogen)/gi,
  /(?:\d+\s*(?:mg|IU|mcg|billion CFU))/gi,
  // Form factor
  /(?:capsule|tablet|powder|liquid|gummies|softgel|patch|spray|tincture|sachet)/gi,
  // Testing / quality
  /(?:third[- ]party test|independent lab|certificate of analysis|GMP|certified)/gi,
  /(?:every batch|dissolution rate|purity|potency|heavy metals)/gi,
  // Sourcing
  /(?:sourced? from|facility in|manufactured|encapsulation|low[- ]temperature)/gi,
];

const AWARENESS_SIGNALS = {
  unaware: [
    /(?:did you know|you might not (?:know|realize)|most people (?:don'?t|never))/gi,
    /(?:a lot of people ask|do I really need)/gi,
  ],
  problem_aware: [
    /(?:if you(?:'ve| have) been (?:struggling|dealing|suffering|experiencing))/gi,
    /(?:tired of|sick of|frustrated with|fed up)/gi,
    /(?:you(?:'ve| have) tried (?:everything|countless|dozens?))/gi,
  ],
  solution_aware: [
    /(?:you(?:'ve| have) probably (?:heard|seen|tried)|other (?:brands?|products?|supplements?))/gi,
    /(?:unlike (?:other|most)|compared to|versus|vs\.?)/gi,
    /(?:switch(?:ed|ing)? (?:to|from))/gi,
  ],
  product_aware: [
    /(?:you(?:'ve| have) (?:been|already) (?:heard|know) about)/gi,
    /(?:still on the fence|haven'?t tried|waiting to)/gi,
  ],
  most_aware: [
    /(?:use code|% off|free shipping|limited time|subscribe and save|money[- ]back)/gi,
    /(?:shop now|order (?:now|today)|get (?:yours|started))/gi,
  ],
};

const SOPHISTICATION_SIGNALS = {
  new_mechanism: [
    /(?:new (?:way|method|approach|system|technology|process|formula))/gi,
    /(?:proprietary|patented|breakthrough|first (?:ever|of its kind|to))/gi,
    /(?:not (?:just )?another|unlike anything|never been done)/gi,
    /(?:how (?:it|this) works|the science behind)/gi,
  ],
  new_information: [
    /(?:studies? show|research (?:shows?|proves?|found)|clinical (?:trial|data|study))/gi,
    /(?:what (?:they|no one|the industry) (?:won'?t|doesn'?t) tell)/gi,
    /(?:the (?:truth|real story|hidden fact) about)/gi,
    /(?:peer[- ]reviewed|published|data from|compiled data)/gi,
    /(?:education|educate|learn (?:more|why|how))/gi,
  ],
  new_identity: [
    /(?:join (?:the|our|a) (?:community|movement|tribe|family))/gi,
    /(?:people (?:like|who) (?:you|us)|for (?:those|people) who)/gi,
    /(?:lifestyle|way of life|who you (?:are|become))/gi,
    /(?:not (?:just|only) a (?:product|supplement|brand))/gi,
  ],
};

// --- Extraction logic ---

function matchSignals(text, patterns) {
  const matches = [];
  for (const pat of patterns) {
    pat.lastIndex = 0;
    let m;
    while ((m = pat.exec(text)) !== null) {
      const cleaned = m[0].trim();
      if (!matches.some(x => x.toLowerCase() === cleaned.toLowerCase())) {
        matches.push(cleaned);
      }
    }
  }
  return matches;
}

function scoreSignalGroup(text, signalMap) {
  const scores = {};
  for (const [key, patterns] of Object.entries(signalMap)) {
    let hits = 0;
    for (const pat of patterns) {
      pat.lastIndex = 0;
      if (pat.test(text)) hits++;
    }
    if (hits > 0) scores[key] = hits;
  }
  return scores;
}

function detectTargetCustomer(text) {
  const segments = [];

  // Demographic signals
  const demoPatterns = [
    [/\b(?:mom|mother|parent|dad|father)\b/gi, 'parent'],
    [/\b(?:\d{2})[- ]year[- ]old\b/gi, 'age-specific'],
    [/\b(?:professional|project manager|executive|entrepreneur)\b/gi, 'professional'],
    [/\b(?:athlete|lifter|gym|fitness|training|workout)\b/gi, 'fitness-oriented'],
    [/\b(?:aging|older adult|senior|over \d{2})\b/gi, 'aging adult'],
    [/\b(?:woman|women|female|her )\b/gi, 'women'],
    [/\b(?:man|men|male|his )\b/gi, 'men'],
  ];

  for (const [pat, label] of demoPatterns) {
    pat.lastIndex = 0;
    if (pat.test(text)) segments.push(label);
  }

  // Psychographic signals
  const psychoPatterns = [
    [/\b(?:skeptic|skeptical|didn'?t believe|hard to impress)\b/gi, 'skeptic / tried-everything'],
    [/\b(?:tried (?:everything|countless|dozens?)|nothing (?:works|worked))\b/gi, 'skeptic / tried-everything'],
    [/\b(?:health[- ]conscious|wellness|optimize|biohack)\b/gi, 'health-conscious optimizer'],
    [/\b(?:research|ingredients?|label|transparency|third[- ]party)\b/gi, 'ingredient-aware researcher'],
  ];

  for (const [pat, label] of psychoPatterns) {
    pat.lastIndex = 0;
    if (pat.test(text) && !segments.includes(label)) segments.push(label);
  }

  return segments;
}

function detectMassDesire(text) {
  const desires = [];
  const desireMap = [
    [/\b(?:energy|energized|vitality|alive|vibrant)\b/gi, 'Having consistent energy and vitality'],
    [/\b(?:sleep|rested|rest|insomnia)\b/gi, 'Sleeping well and waking rested'],
    [/\b(?:focus|clarity|cognitive|mental|brain|sharp)\b/gi, 'Mental clarity and sharp focus'],
    [/\b(?:health|healthy|wellness|well[- ]being)\b/gi, 'Overall health and wellness'],
    [/\b(?:performance|recover|recovery|strength|endurance)\b/gi, 'Peak physical performance and recovery'],
    [/\b(?:confidence|trust|transparent|truth)\b/gi, 'Trusting what you put in your body'],
    [/\b(?:family|kids|children|keep up)\b/gi, 'Being present and active for family'],
  ];

  for (const [pat, desire] of desireMap) {
    pat.lastIndex = 0;
    if (pat.test(text) && !desires.includes(desire)) desires.push(desire);
  }

  return desires;
}

function detectAwarenessStage(text) {
  const scores = scoreSignalGroup(text, AWARENESS_SIGNALS);
  const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]);

  // Most aware signals (offers/CTAs) exist in almost every ad.
  // The PRIMARY awareness stage is the one the ad LEADS with.
  // Check the first ~25% of text for the dominant stage.
  const leadText = text.slice(0, Math.floor(text.length * 0.25));
  const leadScores = scoreSignalGroup(leadText, AWARENESS_SIGNALS);
  const leadRanked = Object.entries(leadScores).sort((a, b) => b[1] - a[1]);

  const primary = leadRanked.length > 0 ? leadRanked[0][0] : (ranked.length > 0 ? ranked[0][0] : 'unknown');

  return {
    primary,
    allSignals: scores,
  };
}

function detectSophisticationStage(text) {
  const strategyScores = scoreSignalGroup(text, SOPHISTICATION_SIGNALS);

  // Determine likely stage based on strategy signals
  let likelyStage = 3; // Default for most ecom
  const strategies = Object.entries(strategyScores).sort((a, b) => b[1] - a[1]);
  const primaryStrategy = strategies.length > 0 ? strategies[0][0] : 'none';

  if (primaryStrategy === 'new_identity') likelyStage = 5;
  else if (primaryStrategy === 'new_information' && strategyScores.new_mechanism) likelyStage = 4;
  else if (primaryStrategy === 'new_mechanism') likelyStage = 3;
  else if (primaryStrategy === 'new_information') likelyStage = 3;

  return {
    likelyStage,
    primaryStrategy,
    strategyScores,
  };
}

function extractBigIdea(text, painPoints, rootCauseSignals, mechanismSignals) {
  // The big idea = how the avatar gets from problem to outcome.
  // We synthesize it from: what pain points are addressed + what mechanism is introduced.
  // Also detect the creative angle (how they sell the idea).

  const creativeAngles = [];
  const anglePatterns = [
    [/\b(?:story|stories|told us|wrote to us|testimonial)\b/gi, 'Customer story / social proof'],
    [/\b(?:I'?m|my name|founder|I (?:built|created|started))\b/gi, 'Founder / authority narrative'],
    [/\b(?:study|studies|clinical|research|data|survey|percent)\b/gi, 'Science / data-driven education'],
    [/\b(?:versus|vs\.?|compared|comparison|leading|other)\b/gi, 'Competitive comparison'],
    [/\b(?:honestly|literally|real talk|let me tell you|have to tell you)\b/gi, 'UGC / authentic voice'],
    [/\b(?:do I (?:really )?need|a lot of people ask|the (?:honest|real) answer)\b/gi, 'Expert Q&A / objection handling'],
  ];

  for (const [pat, angle] of anglePatterns) {
    pat.lastIndex = 0;
    if (pat.test(text) && !creativeAngles.includes(angle)) creativeAngles.push(angle);
  }

  return {
    painPointCount: painPoints.length,
    rootCausePresent: rootCauseSignals.length > 0,
    mechanismPresent: mechanismSignals.length > 0,
    creativeAngles,
  };
}

// ============================================================================
// MAIN EXTRACTION
// ============================================================================

function extractFramework(ad) {
  const text = ad.resolvedCopy.text;
  const words = countWords(text);

  const painPoints = matchSignals(text, PAIN_POINT_SIGNALS);
  const rootCauseSignals = matchSignals(text, ROOT_CAUSE_SIGNALS);
  const mechanismSignals = matchSignals(text, MECHANISM_SIGNALS);
  const productDelivery = matchSignals(text, PRODUCT_DELIVERY_SIGNALS);
  const targetCustomer = detectTargetCustomer(text);
  const massDesire = detectMassDesire(text);
  const awarenessStage = detectAwarenessStage(text);
  const sophistication = detectSophisticationStage(text);
  const bigIdea = extractBigIdea(text, painPoints, rootCauseSignals, mechanismSignals);

  return {
    id: ad.id,
    name: ad.name,
    type: ad.type,
    wordCount: words,

    // Framework elements
    targetCustomer,
    massDesire,
    painPoints,
    rootCause: {
      signals: rootCauseSignals,
      present: rootCauseSignals.length > 0,
    },
    mechanism: {
      signals: mechanismSignals,
      present: mechanismSignals.length > 0,
    },
    productDelivery: {
      signals: productDelivery,
      present: productDelivery.length > 0,
    },
    sophistication,
    awarenessStage,
    bigIdea,
  };
}

module.exports = {
  extractFramework,
  // Expose for testing
  matchSignals,
  detectTargetCustomer,
  detectMassDesire,
  detectAwarenessStage,
  detectSophisticationStage,
  PAIN_POINT_SIGNALS,
  ROOT_CAUSE_SIGNALS,
  MECHANISM_SIGNALS,
  PRODUCT_DELIVERY_SIGNALS,
};
