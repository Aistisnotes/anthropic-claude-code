'use strict';

const { countWords } = require('./adFilter');

// ============================================================================
// DR FRAMEWORK EXTRACTION v2
//
// Sentence-level analysis for direct response marketing framework:
// 1. Target Customer (synthesized avatar)
// 2. Mass Desire (primary identification)
// 3. Pain Points (grouped by symptom category)
// 4. Root Cause (villain narrative sentences)
// 5. Mechanism (causal chain from ad copy)
// 6. Product Delivery Mechanism
// 7. Market Sophistication Stage
// 8. Customer Awareness Stage
// 9. Big Idea (concept + creative style)
// ============================================================================

// --- Sentence utilities ---

function splitSentences(text) {
  // Protect abbreviations from being split on their periods
  let safe = text
    .replace(/\b(Dr|Mr|Mrs|Ms|Prof)\./gi, (m) => m.replace('.', '\u2024'))
    .replace(/\b(vs|etc|Inc|Ltd)\./gi, (m) => m.replace('.', '\u2024'))
    .replace(/\b([ap])\.m\./gi, (m) => m.replace(/\./g, '\u2024'))
    .replace(/(\d)\./g, '$1\u2024');

  const parts = safe.split(/(?<=[.!?])\s+/);
  return parts
    .map(s => s.replace(/\u2024/g, '.').trim())
    .filter(s => s.length > 15);
}

// --- Sentence role classification ---

const ROLE_PATTERNS = {
  pain_agitation: [
    /\b(?:tired|exhausted|fatigued|burned out|no energy|crash(?:ing|es)?|brain fog|can'?t (?:sleep|focus|concentrate)|muscle cramp|joint (?:pain|stiff)|sore(?:ness)?|bloat|stressed|anxious|overwhelmed|irritable|inflammation|chronic fatigue)\b/i,
    /\b(?:struggling|suffering|dealing with|frustrated|nothing work|tried everything|given up|was just done|could not function|collapsing|half-used bottles|medicine cabinet)\b/i,
    /\b(?:afternoon (?:crash|slump)|2\s*PM|3\s*PM|midday)\b/i,
  ],
  root_cause: [
    /\b(?:the (?:real|true|actual|hidden|root) (?:reason|cause|problem|issue))\b/i,
    /\b(?:industry (?:is|has|was)|companies? (?:optimize|sell)|empty promises|flashy marketing)\b/i,
    /\b(?:deficien(?:cy|t)|depleted|not (?:getting|absorbing) enough|(?:\d+)%? (?:of (?:Americans?|adults?|people)|do not get))\b/i,
    /\b(?:modern (?:agriculture|diet|lifestyle)|soil (?:depletion|minerals)|indoor lifestyle)\b/i,
    /\b(?:cheap|underdosed|poorly (?:sourced|formulated)|unnecessary filler|generic)\b/i,
    /\b(?:bioavailability (?:rate|of)|(?:your )?body (?:cannot|can'?t) (?:absorb|use)|does not dissolve|essentially worthless)\b/i,
    /\b(?:burns? through|chronic stress (?:burns?|depletes?))\b/i,
    /\b(?:what (?:no one|nobody|they) (?:told|tells|mentioned|won'?t tell))\b/i,
  ],
  failed_solutions: [
    /\b(?:tried (?:countless|dozens?|everything|over (?:a )?dozen|multiple)|half-used (?:bottles?)|nothing (?:delivered|worked|else came close))\b/i,
    /\b(?:graveyard of|medicine cabinet was|previous (?:supplement|vitamin|brand|multivitamin))\b/i,
    /\b(?:another supplement|sure,? another|whatever)\b/i,
    /\b(?:none delivered|each promising|wasting money on supplements? that (?:don'?t|do not) work)\b/i,
    /\b(?:if you(?:'ve| have) been taking .{1,40} and not (?:noticing|seeing))\b/i,
  ],
  mechanism_how: [
    /\b(?:that'?s (?:why|how|exactly)|here'?s (?:how|what|the (?:key|thing|secret)))\b/i,
    /\b(?:we (?:chose|selected|paired|integrated)|our .{1,20} (?:approach|method|formula))\b/i,
    /\b(?:synergistic|cofactors?|chelated|methylated|full[- ]spectrum)\b/i,
    /\b(?:works? by|designed to|formulated to|engineered to|built (?:to|into))\b/i,
    /\b(?:separates? .{1,30} from|what sets .{1,30} apart|unlike (?:other|most|typical))\b/i,
    /\b(?:superior (?:bioavailability|absorption)|properly (?:formulated|dosed))\b/i,
    /\b(?:enhance(?:s|d)? absorption|fill(?:s|ing)? (?:critical )?gaps?|well[- ]designed supplement)\b/i,
  ],
  product_detail: [
    /\b(?:\d+\s*(?:mg|IU|mcg|billion CFU))\b/i,
    /\b(?:third[- ]party test|independent lab|certificate of analysis|GMP|certified)\b/i,
    /\b(?:capsule|tablet|powder|gummies|softgel)\b/i,
    /\b(?:purity|potency|heavy metals|dissolution rate|every (?:batch|shipment))\b/i,
    /\b(?:sourced? from|facility in|manufactured|encapsulation|low[- ]temperature)\b/i,
    /\b(?:magnesium (?:glycinate|oxide|citrate)|vitamin [A-Z]\d?|CoQ10|mushroom|lion'?s mane|B-?complex|methylfolate|methylcobalamin)\b/i,
  ],
  outcome_promise: [
    /\b(?:\d+\s*(?:percent|%) (?:report|show|improv))\b/i,
    /\b(?:notice(?:d|able)? (?:something|the|a )?(?:change|difference|improvement))\b/i,
    /\b(?:energy (?:to (?:play|spare)|levels?))\b/i,
    /\b(?:sleep(?:ing)? (?:through|better|faster|quality)|wake up (?:actually )?feeling rested|fall asleep faster)\b/i,
    /\b(?:focus (?:during|had|has) (?:sharpened|improved))\b/i,
    /\b(?:changed my life|never going back|reclaim|feel the difference|transformation)\b/i,
    /\b(?:within (?:the first|two) (?:week|day|month)|by (?:day|week) (?:\d+|ten|two|three))\b/i,
  ],
  social_proof: [
    /\b(?:\d[\d,]*\+?\s*(?:customers?|people|participants?|members?))\b/i,
    /\b(?:customer (?:survey|report|told|wrote|stories?))\b/i,
    /\b(?:personal (?:referral|recommendation)|(?:can'?t|cannot) help but share)\b/i,
  ],
  cta: [
    /\b(?:use code|% off|free shipping|money[- ]back|guarantee|shop now|order (?:now|today)|try .{1,20} today|visit \S+\.com|subscribe and save|get (?:yours|started))\b/i,
  ],
};

function classifySentences(sentences) {
  return sentences.map(sentence => {
    const roles = {};
    for (const [role, patterns] of Object.entries(ROLE_PATTERNS)) {
      let hits = 0;
      for (const pat of patterns) {
        pat.lastIndex = 0;
        if (pat.test(sentence)) hits++;
      }
      if (hits > 0) roles[role] = hits;
    }
    const sorted = Object.entries(roles).sort((a, b) => b[1] - a[1]);
    const primaryRole = sorted.length > 0 ? sorted[0][0] : 'other';
    return { text: sentence, primaryRole, roles };
  });
}

// --- Pain Points by Category ---

const PAIN_CATEGORIES = {
  energy_fatigue: {
    label: 'Energy & Fatigue',
    patterns: [
      /\b(?:tired|exhausted|fatigued|burned out|no energy|low energy|energy crash(?:es)?|chronic fatigue|always tired|constantly exhausted|crash(?:ing)?|not crashing|afternoon (?:crash|slump)|2\s*PM|3\s*PM|midday|was just done|could not function|collapsing)\b/gi,
    ],
  },
  sleep: {
    label: 'Sleep',
    patterns: [
      /\b(?:can'?t sleep|poor sleep|insomnia|wake up at \d|waking at \d|trouble sleeping|not sleeping|sleep quality|fall asleep|sleeping through)\b/gi,
    ],
  },
  cognitive: {
    label: 'Cognitive & Focus',
    patterns: [
      /\b(?:brain fog|can'?t focus|can'?t concentrate|mental clarity|foggy|unfocused|cognitive)\b/gi,
    ],
  },
  stress_mood: {
    label: 'Stress & Mood',
    patterns: [
      /\b(?:stressed|anxiety|anxious|overwhelmed|irritable|mood stability)\b/gi,
    ],
  },
  physical: {
    label: 'Physical (Muscle, Joint, Inflammation)',
    patterns: [
      /\b(?:muscle (?:cramps?|tension)|soreness|joint (?:pain|stiffness)|inflammation|joints? feel)\b/gi,
    ],
  },
  digestive: {
    label: 'Digestive',
    patterns: [
      /\b(?:bloating|digestive|gut (?:issues|problems)|GI discomfort|stomach)\b/gi,
    ],
  },
  appearance: {
    label: 'Appearance (Skin, Hair, Aging)',
    patterns: [
      /\b(?:hair (?:loss|growth|nails)|skin (?:issues|problems|health)|brittle nails|aging)\b/gi,
    ],
  },
  meta_frustration: {
    label: 'Tried everything / past failures',
    patterns: [
      /\b(?:tried (?:everything|countless|dozens?|over (?:a )?dozen|multiple)|nothing (?:works|worked|else came close)|frustrated|skeptical|given up|graveyard of|wasting money|half-used bottles|medicine cabinet)\b/gi,
    ],
  },
};

function extractPainPoints(text) {
  const byCategory = {};
  const all = [];

  for (const [catKey, cat] of Object.entries(PAIN_CATEGORIES)) {
    const matches = [];
    for (const pat of cat.patterns) {
      pat.lastIndex = 0;
      let m;
      while ((m = pat.exec(text)) !== null) {
        const cleaned = m[0].trim().toLowerCase();
        if (!matches.includes(cleaned)) matches.push(cleaned);
      }
    }
    if (matches.length > 0) {
      byCategory[catKey] = { label: cat.label, matches };
      all.push(...matches);
    }
  }

  return { byCategory, all };
}

// --- Root Cause (villain narrative) ---

const VILLAIN_TYPES = {
  industry_blame: {
    label: 'Industry / system blame',
    patterns: [
      /\b(?:(?:supplement|food|health|pharma|wellness) industry|empty promises|flashy marketing|companies? (?:optimize|sell|market) for (?:cost|profit))\b/i,
    ],
  },
  hidden_deficiency: {
    label: 'Hidden nutritional deficiency',
    patterns: [
      /\b(?:deficien(?:cy|t)|depleted|not (?:getting|absorbing) enough|(?:\d+)%? (?:of (?:Americans?|adults?)|do not get))\b/i,
    ],
  },
  environmental: {
    label: 'Modern environment / lifestyle',
    patterns: [
      /\b(?:modern (?:agriculture|diet|lifestyle)|soil (?:depletion|minerals)|indoor lifestyle|chronic stress (?:burns?|depletes?))\b/i,
    ],
  },
  product_failure: {
    label: 'Existing products are broken',
    patterns: [
      /\b(?:cheap|underdosed|poorly (?:sourced|formulated)|filler|magnesium oxide|bioavailability (?:rate )?(?:of )?(?:roughly )?(?:\d)%|synthetic (?:folic|B )|does not dissolve|essentially worthless)\b/i,
    ],
  },
};

function extractRootCause(text, classifiedSentences) {
  const rootCauseSentences = classifiedSentences
    .filter(s => s.primaryRole === 'root_cause' || (s.roles.root_cause && s.roles.root_cause >= 2))
    .map(s => s.text);

  const failedSolutionSentences = classifiedSentences
    .filter(s => s.primaryRole === 'failed_solutions')
    .map(s => s.text);

  // Detect villain types
  const villainScores = {};
  for (const [type, config] of Object.entries(VILLAIN_TYPES)) {
    for (const pat of config.patterns) {
      pat.lastIndex = 0;
      if (pat.test(text)) {
        villainScores[type] = (villainScores[type] || 0) + 1;
      }
    }
  }

  const villainRanked = Object.entries(villainScores).sort((a, b) => b[1] - a[1]);
  const primaryVillain = villainRanked.length > 0 ? villainRanked[0][0] : null;
  const allVillainTypes = villainRanked.map(([type]) => ({
    type,
    label: VILLAIN_TYPES[type].label,
  }));

  return {
    present: rootCauseSentences.length > 0,
    sentences: rootCauseSentences,
    failedSolutionSentences,
    primaryVillain,
    villainLabel: primaryVillain ? VILLAIN_TYPES[primaryVillain].label : null,
    allVillainTypes,
  };
}

// --- Mechanism (causal chain) ---

function extractMechanismChain(classifiedSentences) {
  const chain = [];

  // Step 1: Pain state
  const painSentences = classifiedSentences
    .filter(s => s.primaryRole === 'pain_agitation')
    .slice(0, 2);
  if (painSentences.length > 0) {
    chain.push({ step: 1, role: 'problem_state', label: 'The problem', sentences: painSentences.map(s => s.text) });
  }

  // Step 2: Root cause
  const rootSentences = classifiedSentences
    .filter(s => s.primaryRole === 'root_cause')
    .slice(0, 3);
  if (rootSentences.length > 0) {
    chain.push({ step: 2, role: 'root_cause', label: 'Why it happens (the villain)', sentences: rootSentences.map(s => s.text) });
  }

  // Step 3: Failed solutions
  const failedSentences = classifiedSentences
    .filter(s => s.primaryRole === 'failed_solutions')
    .slice(0, 2);
  if (failedSentences.length > 0) {
    chain.push({ step: 3, role: 'why_others_fail', label: 'Why other solutions fail', sentences: failedSentences.map(s => s.text) });
  }

  // Step 4: How this mechanism works
  const mechSentences = classifiedSentences
    .filter(s => s.primaryRole === 'mechanism_how')
    .slice(0, 3);
  if (mechSentences.length > 0) {
    chain.push({ step: 4, role: 'how_this_works', label: 'How this mechanism works', sentences: mechSentences.map(s => s.text) });
  }

  // Step 5: Outcome
  const outcomeSentences = classifiedSentences
    .filter(s => s.primaryRole === 'outcome_promise')
    .slice(0, 2);
  if (outcomeSentences.length > 0) {
    chain.push({ step: 5, role: 'outcome', label: 'The outcome', sentences: outcomeSentences.map(s => s.text) });
  }

  // Assess completeness
  const allRoles = ['problem_state', 'root_cause', 'why_others_fail', 'how_this_works', 'outcome'];
  const allLabels = ['Problem state', 'Root cause (villain)', 'Why others fail', 'How this works', 'Outcome'];
  const missingSteps = [];
  for (let i = 0; i < allRoles.length; i++) {
    if (!chain.some(c => c.role === allRoles[i])) {
      missingSteps.push(allLabels[i]);
    }
  }

  return {
    present: chain.some(c => c.role === 'how_this_works'),
    chain,
    complete: missingSteps.length === 0,
    missingSteps,
    stepsFound: chain.length,
  };
}

// --- Target Customer (synthesized avatar) ---

function detectTargetCustomer(text, painCategories) {
  const demographics = [];
  const demoPatterns = [
    [/\b(?:mom|mother)\b/gi, 'mother'],
    [/\b(?:dad|father)\b/gi, 'father'],
    [/\b(?:parent|parents)\b/gi, 'parent'],
    [/\b(\d{2})[- ]year[- ]old\b/gi, 'age_match'],
    [/\bover (\d{2})\b/gi, 'over_age'],
    [/\b(?:professional|project manager|executive|entrepreneur)\b/gi, 'professional'],
    [/\b(?:athlete|lifter|gym|fitness|training|workout)\b/gi, 'fitness-oriented'],
    [/\b(?:aging|older adult|senior)\b/gi, 'aging adult'],
    [/\b(?:woman|women|female)\b/gi, 'women'],
    [/\b(?:man|men|male)\b/gi, 'men'],
    [/\b(?:busy|work(?:s|ing)? full[- ]time)\b/gi, 'busy / time-pressed'],
    [/\b(?:physician|doctor|naturopath)\b/gi, 'healthcare professional'],
  ];

  for (const [pat, label] of demoPatterns) {
    pat.lastIndex = 0;
    if (label === 'age_match') {
      let m;
      while ((m = pat.exec(text)) !== null) {
        const tag = `${m[1]}-year-old`;
        if (!demographics.includes(tag)) demographics.push(tag);
      }
    } else if (label === 'over_age') {
      let m;
      while ((m = pat.exec(text)) !== null) {
        const tag = `over ${m[1]}`;
        if (!demographics.includes(tag)) demographics.push(tag);
      }
    } else {
      if (pat.test(text) && !demographics.includes(label)) demographics.push(label);
    }
  }

  const psychographics = [];
  const psychoPatterns = [
    [/\b(?:skeptic(?:al)?|didn'?t believe|hard to impress|sure,? another)\b/gi, 'skeptical of supplements after past disappointments'],
    [/\b(?:tried (?:everything|countless|dozens?|over (?:a )?dozen|multiple)|nothing (?:works|worked)|graveyard of)\b/gi, 'has tried multiple products without lasting results'],
    [/\b(?:health[- ]conscious|optimize|biohack)\b/gi, 'health-conscious / actively optimizing'],
    [/\b(?:research|ingredients?|label|transparency|third[- ]party|clinical|dosage|potency)\b/gi, 'evaluates ingredients, dosage, and testing'],
    [/\b(?:friend (?:told|recommended)|coworker|buddy introduced|personal (?:referral|recommendation)|(?:told|recommended) (?:to|by))\b/gi, 'influenced by trusted personal referral'],
  ];

  for (const [pat, label] of psychoPatterns) {
    pat.lastIndex = 0;
    if (pat.test(text) && !psychographics.includes(label)) psychographics.push(label);
  }

  const avatar = synthesizeAvatar(demographics, psychographics, painCategories);
  return { demographics, psychographics, avatar };
}

function synthesizeAvatar(demographics, psychographics, painCategories) {
  const parts = [];

  // WHO: compose demographic identity
  if (demographics.length > 0) {
    const ageGender = demographics.filter(d => d.includes('year-old') || d.startsWith('over ') || d === 'women' || d === 'men');
    const roles = demographics.filter(d => ['mother', 'father', 'parent', 'professional', 'fitness-oriented', 'aging adult', 'healthcare professional'].includes(d));
    const situation = demographics.filter(d => d === 'busy / time-pressed');

    const whoChunks = [];
    if (ageGender.length > 0) whoChunks.push(ageGender.join(', '));
    if (situation.length > 0 && roles.length > 0) {
      whoChunks.push(`${situation.join(', ')} ${roles.join(' and ')}`);
    } else if (roles.length > 0) {
      whoChunks.push(roles.join(' and '));
    }
    if (whoChunks.length > 0) parts.push(whoChunks.join(', '));
  }

  // SITUATION: what pain categories they're experiencing
  const painLabels = Object.values(painCategories).map(c => c.label.toLowerCase());
  if (painLabels.length > 0) {
    parts.push(`experiencing ${painLabels.slice(0, 3).join(', ')}`);
  }

  // MINDSET: their buying behavior and past experience
  if (psychographics.length > 0) {
    parts.push(`who ${psychographics.slice(0, 2).join(' and ')}`);
  }

  if (parts.length === 0) return 'Avatar not clearly defined in this ad';
  return parts.join(', ');
}

// --- Mass Desire (primary identification) ---

const DESIRE_MAP = [
  { key: 'energy', pattern: /\b(?:energy|energized|vitality|alive|vibrant)\b/gi, label: 'Having consistent energy and vitality' },
  { key: 'sleep', pattern: /\b(?:sleep|rested|rest(?:ful)?|insomnia|fall asleep)\b/gi, label: 'Sleeping well and waking rested' },
  { key: 'focus', pattern: /\b(?:focus|clarity|cognitive|mental|brain|sharp)\b/gi, label: 'Mental clarity and sharp focus' },
  { key: 'health', pattern: /\b(?:health|healthy|wellness|well[- ]being|longevity)\b/gi, label: 'Overall health and wellness' },
  { key: 'performance', pattern: /\b(?:performance|recover|recovery|strength|endurance)\b/gi, label: 'Peak physical performance and recovery' },
  { key: 'trust', pattern: /\b(?:confidence|trust|transparent|transparency|truth)\b/gi, label: 'Trusting what you put in your body' },
  { key: 'family', pattern: /\b(?:family|kids|children|keep up)\b/gi, label: 'Being present and active for family' },
];

function detectMassDesire(text) {
  const detected = [];
  for (const d of DESIRE_MAP) {
    d.pattern.lastIndex = 0;
    const matches = text.match(d.pattern);
    if (matches) {
      detected.push({ key: d.key, label: d.label, hits: matches.length });
    }
  }
  detected.sort((a, b) => b.hits - a.hits);
  const primary = detected.length > 0 ? detected[0] : null;
  return {
    all: detected,
    primary: primary ? primary.label : null,
    primaryKey: primary ? primary.key : null,
  };
}

// --- Awareness Stage ---

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

function detectAwarenessStage(text) {
  const leadText = text.slice(0, Math.floor(text.length * 0.25));
  const leadScores = scoreSignalGroup(leadText, AWARENESS_SIGNALS);
  const fullScores = scoreSignalGroup(text, AWARENESS_SIGNALS);
  const leadRanked = Object.entries(leadScores).sort((a, b) => b[1] - a[1]);
  const fullRanked = Object.entries(fullScores).sort((a, b) => b[1] - a[1]);

  const primary = leadRanked.length > 0
    ? leadRanked[0][0]
    : (fullRanked.length > 0 ? fullRanked[0][0] : 'unknown');

  return { primary };
}

// --- Sophistication Stage ---

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

function detectSophisticationStage(text) {
  const strategyScores = scoreSignalGroup(text, SOPHISTICATION_SIGNALS);
  const strategies = Object.entries(strategyScores).sort((a, b) => b[1] - a[1]);
  const primaryStrategy = strategies.length > 0 ? strategies[0][0] : 'none';

  let likelyStage = 3;
  if (primaryStrategy === 'new_identity') likelyStage = 5;
  else if (primaryStrategy === 'new_information' && strategyScores.new_mechanism) likelyStage = 4;

  return { likelyStage, primaryStrategy, strategyScores };
}

// --- Product Delivery ---

const PRODUCT_DELIVERY_SIGNALS = [
  /(?:magnesium (?:glycinate|oxide|citrate)?|vitamin [A-Z]\d?|CoQ10|zinc|selenium|B-?complex|mushroom|lion'?s mane|reishi|adaptogen|methylfolate|methylcobalamin|boron|manganese|creatine|protein)/gi,
  /(?:\d+\s*(?:mg|IU|mcg|billion CFU))/gi,
  /(?:capsule|tablet|powder|liquid|gummies|softgel|patch|spray|tincture|sachet)/gi,
  /(?:third[- ]party test|independent lab|certificate of analysis|GMP|certified)/gi,
  /(?:every batch|dissolution rate|purity|potency|heavy metals)/gi,
  /(?:sourced? from|facility in|manufactured|encapsulation|low[- ]temperature)/gi,
];

function extractProductDelivery(text) {
  const signals = [];
  for (const pat of PRODUCT_DELIVERY_SIGNALS) {
    pat.lastIndex = 0;
    let m;
    while ((m = pat.exec(text)) !== null) {
      const cleaned = m[0].trim();
      if (!signals.some(x => x.toLowerCase() === cleaned.toLowerCase())) {
        signals.push(cleaned);
      }
    }
  }
  return { signals, present: signals.length > 0 };
}

// --- Big Idea (concept + creative style) ---

function extractBigIdea(text, painCategories, rootCause, mechanismChain, massDesire) {
  // Detect creative style
  const stylePatterns = [
    [/\b(?:(?:my|his|her) (?:story|experience|journey)|wrote to us|told us|customer,?\s+\w+\s+from)\b/gi, 'Customer story / testimonial'],
    [/\b(?:I'?m (?:Dr|a physician|a doctor|founder)|as a (?:physician|doctor)|I (?:built|created|founded|started))\b/gi, 'Founder / authority narrative'],
    [/\b(?:clinical (?:trial|studies?|data)|(?:\d+%?) (?:report|show|improv)|peer[- ]reviewed|participants?|survey)\b/gi, 'Science / data-driven education'],
    [/\b(?:versus|vs\.?|compared|comparison|leading (?:brand|multi|suppl))\b/gi, 'Head-to-head comparison'],
    [/\b(?:honestly|literally|real talk|let me tell you|have to tell you|changed my life|I was like)\b/gi, 'UGC / authentic voice'],
    [/\b(?:do I (?:really )?need|a lot of people ask|the (?:honest|real) answer|common question)\b/gi, 'Expert Q&A / objection handling'],
  ];

  const creativeStyles = [];
  for (const [pat, style] of stylePatterns) {
    pat.lastIndex = 0;
    if (pat.test(text) && !creativeStyles.includes(style)) creativeStyles.push(style);
  }
  const primaryStyle = creativeStyles.length > 0 ? creativeStyles[0] : 'Unclear';

  // Synthesize the big idea concept
  const painLabel = Object.values(painCategories).length > 0
    ? Object.values(painCategories)[0].label
    : null;
  const villainLabel = rootCause.villainLabel;
  const hasChain = mechanismChain.present;
  const desireLabel = massDesire.primary;

  let concept;
  if (painLabel && villainLabel && hasChain) {
    concept = `People suffering from ${painLabel.toLowerCase()} because of ${villainLabel.toLowerCase()} can finally achieve ${(desireLabel || 'results').toLowerCase()} through a properly designed mechanism`;
  } else if (painLabel && villainLabel) {
    concept = `People suffering from ${painLabel.toLowerCase()} because of ${villainLabel.toLowerCase()} need a real solution (but mechanism not articulated in this ad)`;
  } else if (painLabel && hasChain) {
    concept = `People dealing with ${painLabel.toLowerCase()} can achieve ${(desireLabel || 'results').toLowerCase()} through a solution that works differently (but root cause / villain not named)`;
  } else if (painLabel) {
    concept = `People experiencing ${painLabel.toLowerCase()} find relief (root cause and mechanism not articulated — weak narrative arc)`;
  } else {
    concept = 'Big idea not clearly articulated — ad lacks a strong pain-to-outcome narrative arc';
  }

  return { concept, primaryStyle, allStyles: creativeStyles };
}

// ============================================================================
// MAIN EXTRACTION
// ============================================================================

function extractFramework(ad) {
  const text = ad.resolvedCopy.text;
  const words = countWords(text);

  // Sentence-level analysis
  const sentences = splitSentences(text);
  const classified = classifySentences(sentences);

  // Extract each framework element
  const painPoints = extractPainPoints(text);
  const rootCause = extractRootCause(text, classified);
  const mechanism = extractMechanismChain(classified);
  const productDelivery = extractProductDelivery(text);
  const massDesire = detectMassDesire(text);
  const targetCustomer = detectTargetCustomer(text, painPoints.byCategory);
  const awarenessStage = detectAwarenessStage(text);
  const sophistication = detectSophisticationStage(text);
  const bigIdea = extractBigIdea(text, painPoints.byCategory, rootCause, mechanism, massDesire);

  return {
    id: ad.id,
    name: ad.name,
    type: ad.type,
    wordCount: words,
    targetCustomer,
    massDesire,
    painPoints,
    rootCause,
    mechanism,
    productDelivery,
    sophistication,
    awarenessStage,
    bigIdea,
  };
}

module.exports = {
  extractFramework,
  splitSentences,
  classifySentences,
  extractPainPoints,
  extractRootCause,
  extractMechanismChain,
  detectTargetCustomer,
  detectMassDesire,
  detectAwarenessStage,
  detectSophisticationStage,
  extractProductDelivery,
  extractBigIdea,
  PAIN_CATEGORIES,
  ROLE_PATTERNS,
};
