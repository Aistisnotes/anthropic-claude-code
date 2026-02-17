import Anthropic from '@anthropic-ai/sdk';
import { config } from '../utils/config.js';

let _client = null;

/**
 * Check if Claude API is available (API key is set).
 */
export function isClaudeAvailable() {
  return Boolean(config.claude.apiKey);
}

/**
 * Get or create the Anthropic client singleton.
 */
function getClient() {
  if (!_client) {
    if (!config.claude.apiKey) {
      throw new Error('ANTHROPIC_API_KEY not set');
    }
    _client = new Anthropic({ apiKey: config.claude.apiKey });
  }
  return _client;
}

/**
 * Call Claude with retry logic.
 */
async function callClaude(systemPrompt, userPrompt, { maxTokens } = {}) {
  const client = getClient();
  const tokens = maxTokens || config.claude.maxTokens;

  for (let attempt = 0; attempt <= config.claude.retryAttempts; attempt++) {
    try {
      const response = await client.messages.create({
        model: config.claude.model,
        max_tokens: tokens,
        system: systemPrompt,
        messages: [{ role: 'user', content: userPrompt }],
      });

      const text = response.content
        .filter((block) => block.type === 'text')
        .map((block) => block.text)
        .join('');

      return text;
    } catch (err) {
      if (attempt < config.claude.retryAttempts && isRetryable(err)) {
        const delay = config.claude.retryDelayMs * Math.pow(2, attempt);
        await sleep(delay);
        continue;
      }
      throw err;
    }
  }
}

function isRetryable(err) {
  if (err.status === 429) return true;
  if (err.status >= 500) return true;
  if (err.code === 'ECONNRESET' || err.code === 'ETIMEDOUT') return true;
  return false;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Parse JSON from Claude's response, handling markdown code blocks.
 */
function parseJsonResponse(text) {
  // Strip markdown code fences if present
  const cleaned = text.replace(/^```(?:json)?\n?/m, '').replace(/\n?```\s*$/m, '').trim();
  return JSON.parse(cleaned);
}

// ─── Per-Ad Deep Analysis ────────────────────────────────────

const AD_ANALYSIS_SYSTEM = `You are a senior competitive intelligence analyst specializing in direct-response advertising and performance marketing. You have 15+ years analyzing Meta/Facebook ads across DTC, SaaS, health, finance, and e-commerce verticals.

Your analysis must be surgical and actionable — no filler, no generic observations. Every insight should be specific enough that a media buyer could act on it immediately.

IMPORTANT: Return ONLY valid JSON. No markdown, no explanations outside the JSON.`;

/**
 * Deep analysis of a single ad using Claude.
 *
 * @param {object} ad - Enriched ad record
 * @returns {object} Deep analysis result
 */
export async function analyzeAdWithClaude(ad) {
  const primaryText = ad.primaryTexts?.[0] || '';
  const headline = ad.headlines?.[0] || '';
  const ctaText = ad.creative?.ctaText || '';
  const landingPage = ad.creative?.landingPageUrl || '';
  const imageCount = ad.creative?.imageUrls?.length || 0;
  const videoCount = ad.creative?.videoUrls?.length || 0;

  const userPrompt = `Analyze this Meta ad with surgical precision.

BRAND: ${ad.pageName || 'Unknown'}
HEADLINE: ${headline || '(none)'}
CTA BUTTON: ${ctaText || '(none)'}
LAUNCH DATE: ${ad.launchDate || 'unknown'}
ESTIMATED IMPRESSIONS: ${ad.impressions?.label || 'unknown'} (lower: ${ad.impressions?.lower || 0})
MEDIA: ${imageCount} images, ${videoCount} videos
LANDING PAGE: ${landingPage || '(not captured)'}
PRIORITY: P${ad.priority} (${ad.label})

PRIMARY AD TEXT:
"""
${primaryText}
"""

Return this exact JSON structure:
{
  "hook": {
    "type": "<question|statistic|bold_claim|fear_urgency|story|social_proof|curiosity|direct_address|other>",
    "reasoning": "<why this hook type, what makes it work or fail>",
    "effectivenessScore": <1-10>,
    "scrollStopPower": "<what specifically would make someone stop scrolling>"
  },
  "angles": [
    {
      "angle": "<mechanism|social_proof|transformation|problem_agitate|scarcity|authority|educational>",
      "evidence": "<specific text that demonstrates this angle>",
      "strength": <1-10>
    }
  ],
  "dominantAngle": "<the single strongest angle>",
  "emotionalTriggers": [
    {
      "emotion": "<security|achievement|hedonism|stimulation|self_direction|benevolence|conformity|tradition|power|universalism>",
      "mechanism": "<how the ad triggers this emotion>",
      "intensity": <1-10>
    }
  ],
  "dominantEmotion": "<the single strongest Schwartz value>",
  "targetAudience": {
    "primary": "<specific demographic/psychographic>",
    "painPoints": ["<specific pain points being addressed>"],
    "desires": ["<specific desires being promised>"],
    "awarenessLevel": "<unaware|problem_aware|solution_aware|product_aware|most_aware>"
  },
  "uniqueMechanism": {
    "present": <true|false>,
    "description": "<what proprietary mechanism/ingredient/process is claimed>",
    "credibilityScore": <1-10>
  },
  "persuasionTechniques": [
    {
      "technique": "<specific technique name>",
      "example": "<where in the ad it's used>",
      "effectiveness": <1-10>
    }
  ],
  "copyQuality": {
    "score": <1-10>,
    "strengths": ["<specific copy strengths>"],
    "weaknesses": ["<specific copy weaknesses>"],
    "missingElements": ["<what a top-performing ad would include that this doesn't>"]
  },
  "format": "<listicle|testimonial|how_to|long_form|minimal|emoji_heavy|direct_response>",
  "cta": "<shop_now|learn_more|sign_up|claim_offer|watch|download|contact|unknown>",
  "offers": [{"type": "<discount|free_trial|guarantee|bonus|free_shipping|bundle|subscription|limited_time>", "detail": "<specifics>"}],
  "strategicIntent": {
    "funnelPosition": "<top|middle|bottom>",
    "objective": "<awareness|consideration|conversion|retention>",
    "testingHypothesis": "<what this ad is likely testing>"
  },
  "overallAssessment": {
    "score": <1-10>,
    "summary": "<2-3 sentence assessment>",
    "topStrength": "<single biggest strength>",
    "topWeakness": "<single biggest weakness>",
    "actionableInsight": "<one thing a competitor could learn from this ad>"
  }
}`;

  const raw = await callClaude(AD_ANALYSIS_SYSTEM, userPrompt);
  return parseJsonResponse(raw);
}

// ─── Brand Strategy Synthesis ────────────────────────────────

const BRAND_SYNTHESIS_SYSTEM = `You are a senior competitive strategist who builds intelligence profiles on DTC and digital-first brands. You synthesize ad-level data into actionable competitive intelligence.

Your output must read like a briefing document for a CMO preparing to compete against this brand. Be specific, evidence-based, and ruthlessly honest about strengths and weaknesses.

IMPORTANT: Return ONLY valid JSON. No markdown, no explanations outside the JSON.`;

/**
 * Synthesize a brand's overall strategy from analyzed ads.
 *
 * @param {object} brand - Advertiser info
 * @param {Array} analyzed - Array of analyzed ads (with .analysis or .claudeAnalysis)
 * @param {object} summary - Batch summary stats
 * @returns {object} Strategic synthesis
 */
export async function synthesizeBrandStrategy(brand, analyzed, summary) {
  // Build concise ad summaries for the prompt
  const adSummaries = analyzed.slice(0, 15).map((ad, i) => {
    const ca = ad.claudeAnalysis || ad.analysis;
    const hook = ca?.hook?.type || ca?.hook || 'unknown';
    const angle = ca?.dominantAngle || 'unknown';
    const emotion = ca?.dominantEmotion || 'unknown';
    const score = ca?.overallAssessment?.score || ca?.copyQuality?.score || 'N/A';
    const preview = (ad.primaryTexts?.[0] || '').slice(0, 200);

    return `Ad ${i + 1} [P${ad.priority}]: hook=${hook}, angle=${angle}, emotion=${emotion}, score=${score}
  "${preview}${preview.length >= 200 ? '...' : ''}"`;
  }).join('\n\n');

  const userPrompt = `Synthesize the competitive strategy for this brand based on their ad portfolio.

BRAND: ${brand.pageName}
TOTAL ADS: ${brand.adCount} | ACTIVE: ${brand.activeAdCount} | RECENT (30d): ${brand.recentAdCount}
TOTAL IMPRESSIONS: ${brand.totalImpressionLower}+
ADS ANALYZED: ${summary.totalAnalyzed}

DISTRIBUTION SUMMARY:
- Hooks: ${JSON.stringify(summary.hookDistribution)}
- Angles: ${JSON.stringify(summary.angleDistribution)}
- Emotions: ${JSON.stringify(summary.emotionDistribution)}
- Formats: ${JSON.stringify(summary.formatDistribution)}
- CTAs: ${JSON.stringify(summary.ctaDistribution)}
- Offers: ${JSON.stringify(summary.offerTypes)}
- Avg word count: ${summary.avgWordCount}
- With video: ${summary.withVideo}/${summary.totalAnalyzed}

AD PORTFOLIO:
${adSummaries}

Return this exact JSON structure:
{
  "positioningNarrative": "<2-3 paragraphs: how this brand positions itself, what market space they own, how they differentiate>",
  "messagingStrategy": {
    "primaryMessage": "<the core message repeated across ads>",
    "supportingMessages": ["<secondary messages that reinforce the primary>"],
    "toneProfile": "<formal/casual/urgent/aspirational/clinical/etc — be specific>",
    "copywritingStyle": "<what school of copywriting they follow, notable patterns>"
  },
  "offerPsychology": {
    "strategy": "<how they structure offers and why>",
    "riskReversalApproach": "<how they reduce purchase friction>",
    "urgencyTactics": ["<specific urgency/scarcity tactics used>"]
  },
  "audienceProfile": {
    "primarySegment": "<specific audience they target>",
    "secondarySegments": ["<other segments>"],
    "psychographicProfile": "<values, lifestyle, beliefs of their target>",
    "awarenessSpectrum": "<where on the awareness spectrum they focus>"
  },
  "strengths": ["<specific competitive strengths backed by evidence>"],
  "vulnerabilities": ["<exploitable weaknesses>"],
  "blindSpots": ["<angles/emotions/formats they completely ignore>"],
  "strategicDirection": {
    "currentPhase": "<launch|growth|scale|defend|pivot>",
    "testingPatterns": "<what they appear to be A/B testing>",
    "likelyNextMoves": ["<predicted strategic moves based on current trajectory>"]
  },
  "threatLevel": {
    "score": <1-10>,
    "reasoning": "<why this score — how dangerous are they as a competitor>"
  }
}`;

  const raw = await callClaude(BRAND_SYNTHESIS_SYSTEM, userPrompt);
  return parseJsonResponse(raw);
}

// ─── Market Loophole Analysis ────────────────────────────────

const LOOPHOLE_SYSTEM = `You are a market strategist who identifies exploitable gaps in competitive landscapes. You analyze advertising patterns across brands to find opportunities that others miss.

Your recommendations must be specific, prioritized, and immediately actionable. Every opportunity should include a clear exploitation strategy, not just the observation that a gap exists.

IMPORTANT: Return ONLY valid JSON. No markdown, no explanations outside the JSON.`;

/**
 * Generate strategic recommendations from market map data.
 *
 * @param {object} marketMap - Market Map report
 * @param {Array<object>} brandReports - Brand reports
 * @param {string|null} focusBrand - Optional focus brand
 * @returns {object} Strategic recommendations
 */
export async function generateStrategicRecommendations(marketMap, brandReports, focusBrand) {
  const profiles = marketMap.profiles.map((p) => {
    return `${p.name}: hook=${p.primaryHook}, angle=${p.primaryAngle}, emotion=${p.primaryEmotion}, format=${p.primaryFormat}, CTA=${p.primaryCta}, depth=${p.contentDepth}, hookDiv=${p.hookDiversity}, angleDiv=${p.angleDiversity}`;
  }).join('\n');

  const satSummary = Object.entries(marketMap.saturation)
    .filter(([k]) => k !== 'overall')
    .map(([dim, data]) => {
      const sat = (data.saturated || []).map((s) => s.dimension);
      const ws = (data.whitespace || []).map((s) => s.dimension);
      return `${dim}: saturated=[${sat.join(', ')}] whitespace=[${ws.join(', ')}]`;
    }).join('\n');

  const overall = marketMap.saturation.overall;

  // Build brand synthesis summaries if available
  const brandInsights = brandReports.map((r) => {
    const cs = r.strategy.claudeSynthesis;
    if (cs) {
      return `${r.brand.name}: ${cs.positioningNarrative?.slice(0, 300) || 'N/A'}
  Strengths: ${(cs.strengths || []).slice(0, 3).join('; ')}
  Vulnerabilities: ${(cs.vulnerabilities || []).slice(0, 3).join('; ')}
  Threat: ${cs.threatLevel?.score || 'N/A'}/10`;
    }
    return `${r.brand.name}: hook=${r.strategy.primaryHook}, angle=${r.strategy.primaryAngle}, activity=${r.strategy.activityLevel}`;
  }).join('\n\n');

  const focusContext = focusBrand
    ? `\nFOCUS BRAND: "${focusBrand}" — generate specific action items for this brand to exploit gaps.\n`
    : '';

  const userPrompt = `Analyze this competitive landscape and identify exploitable gaps.

MARKET: "${marketMap.meta.keyword}"
BRANDS COMPARED: ${marketMap.meta.brandsCompared}
${focusContext}
BRAND PROFILES:
${profiles}

SATURATION ANALYSIS:
${satSummary}

MARKET STATS:
- Avg Hook Diversity: ${overall.avgHookDiversity}
- Avg Angle Diversity: ${overall.avgAngleDiversity}
- Offer Usage: ${overall.offerUsage}%
- Video Usage: ${overall.videoUsage}%

BRAND INTELLIGENCE:
${brandInsights}

Return this exact JSON structure:
{
  "marketNarrative": "<3-4 paragraph executive summary of the competitive landscape — who's winning, why, and where the cracks are>",
  "topOpportunities": [
    {
      "gap": "<specific gap identified>",
      "exploitationStrategy": "<exactly how to exploit this gap>",
      "expectedImpact": "<high|medium|low>",
      "implementationDifficulty": "<easy|moderate|hard>",
      "reasoning": "<why this gap exists and why it's exploitable>"
    }
  ],
  "contrarianPlays": [
    {
      "conventionalWisdom": "<what everyone in the market is doing>",
      "contrarianApproach": "<the opposite or unexpected approach>",
      "upside": "<why going against the grain could work here>"
    }
  ],
  "immediateActions": [
    {
      "action": "<specific action to take>",
      "timeline": "<this week|this month|this quarter>",
      "expectedOutcome": "<what this should produce>"
    }
  ]${focusBrand ? `,
  "brandSpecificActions": [
    {
      "action": "<specific action for ${focusBrand}>",
      "rationale": "<why this matters for ${focusBrand}>",
      "priority": "<P1|P2|P3>",
      "expectedOutcome": "<measurable expected outcome>"
    }
  ]` : ''}
}`;

  const raw = await callClaude(LOOPHOLE_SYSTEM, userPrompt, { maxTokens: 6000 });
  return parseJsonResponse(raw);
}

// ─── Concurrency Helper ──────────────────────────────────────

/**
 * Process items through an async function with concurrency limit.
 *
 * @param {Array} items - Items to process
 * @param {Function} fn - Async function to call on each item
 * @param {number} concurrency - Max concurrent calls
 * @returns {Array} Results in same order as items
 */
export async function mapWithConcurrency(items, fn, concurrency) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function worker() {
    while (nextIndex < items.length) {
      const i = nextIndex++;
      results[i] = await fn(items[i], i);
    }
  }

  const workers = Array.from(
    { length: Math.min(concurrency, items.length) },
    () => worker()
  );
  await Promise.all(workers);
  return results;
}
