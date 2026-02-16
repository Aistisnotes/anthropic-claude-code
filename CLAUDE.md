# Meta Ads Market Research Pipeline

## Project Overview
CLI tool (`meta-ads`) for surgical market research via Meta Ad Library. Scans metadata first, selects ads by strategic priority, then runs deep Claude-powered analysis on high-signal ads (with heuristic fallback when no API key).

## Architecture
```
bin/meta-ads.js                → CLI entry point (Commander.js)
src/commands/scan.js           → `meta-ads scan` command
src/commands/market.js         → `meta-ads market` command (full pipeline)
src/commands/compare.js        → `meta-ads compare` command (cross-brand)
src/scraper/meta-ad-library.js → Meta Ad Library Playwright scraper (headless Chromium)
src/scraper/ad-downloader.js   → Selective ad creative downloader
src/selection/ad-selector.js   → Priority-based ad selection engine (P1-P4)
src/analysis/claude-client.js  → Anthropic Claude API client (deep analysis)
src/analysis/pipeline.js       → Analysis pipeline (Claude + heuristic fallback)
src/reports/brand-report.js    → Per-brand report with Claude strategy synthesis
src/reports/market-map.js      → Cross-brand Market Map report
src/reports/loophole-doc.js    → Master Loophole Doc with Claude strategic recommendations
src/utils/config.js            → Configuration (thresholds, paths, API settings)
src/utils/logger.js            → Colored terminal logging
src/utils/formatters.js        → Table/JSON/summary output formatters
```

## Commands
- `meta-ads scan "keyword"` — Scan Meta Ad Library metadata, rank advertisers, show selection breakdown
  - Flags: `--country`, `--pages`, `--status`, `--top`, `--headlines`, `--select`, `--json`, `--output`
- `meta-ads market "keyword"` — Full pipeline: scan → select → download → analyze → report
  - Flags: `--country`, `--pages`, `--status`, `--top-brands`, `--ads-per-brand`, `--no-download`, `--from-scan`, `--json`, `--output`
- `meta-ads compare "keyword"` — Cross-brand comparison: Market Map + Loophole Document
  - Flags: `--brand`, `--from-reports`, `--from-scan`, `--top-brands`, `--ads-per-brand`, `--no-download`, `--json`, `--output`

## Ad Selection Priority System
- **P1 ACTIVE_WINNER**: <14 days + high impressions (50K+) — brand is scaling this NOW
- **P2 PROVEN_RECENT**: <30 days + moderate impressions (10K+) — survived testing
- **P3 STRATEGIC_DIRECTION**: <7 days, any impressions — where brand is heading
- **P4 RECENT_MODERATE**: <60 days + high impressions (50K+) — still relevant
- **SKIP**: Legacy (6+ months), failed tests (low impressions + >30 days), thin text (<50 words), duplicates

## Analysis Pipeline (Dual Mode)
When `ANTHROPIC_API_KEY` is set, Claude provides deep competitive intelligence per ad:
- **Hook analysis**: type classification + reasoning + effectiveness score + scroll-stop power
- **Messaging angles**: evidence-based angle detection with strength scoring (1-10)
- **Emotional triggers**: Schwartz value classification with mechanism description + intensity
- **Target audience**: primary segment, psychographic profile, pain points, awareness level
- **Unique mechanism**: detection + credibility scoring
- **Persuasion techniques**: identification + per-technique effectiveness scoring
- **Copy quality**: score + specific strengths/weaknesses/missing elements
- **Strategic intent**: funnel position, objective, testing hypothesis
- **Overall assessment**: score, summary, top strength/weakness, actionable insight

When no API key is set, heuristic fallback (regex/keyword matching) provides:
- Hook detection, messaging angles, offer types, CTA classification, format, Schwartz values

### Brand Strategy Synthesis (Claude)
Per-brand deep synthesis includes:
- Positioning narrative (2-3 paragraphs)
- Messaging strategy (primary message, tone, copywriting style)
- Offer psychology (strategy, risk reversal, urgency tactics)
- Audience profiling (segments, psychographic, awareness spectrum)
- Strengths, vulnerabilities, blind spots
- Strategic direction (phase, testing patterns, likely next moves)
- Threat level (1-10 score with reasoning)

### Market Loophole Analysis (Claude)
Strategic recommendations include:
- Executive market narrative (3-4 paragraph competitive landscape summary)
- Top exploitable opportunities (with exploitation strategy + impact + difficulty)
- Contrarian plays (conventional wisdom vs. contrarian approach + upside)
- Immediate action items (with timeline + expected outcome)
- Brand-specific action plans (when focus brand specified)

## Compare Pipeline
Cross-brand analysis outputs:
- **Market Map**: Brand-by-brand comparison matrices (hooks × brands, angles × brands, emotions × brands), saturation analysis (saturated/moderate/whitespace), brand strategy profiles
- **Loophole Document**: Market-wide gaps (nobody uses), saturation zones (everyone uses), underexploited opportunities (1-2 brands use), priority matrix (ranked by gap score × relevance), brand-specific blind spots, Claude strategic recommendations

## Setup
```bash
npm install
npx playwright install chromium                # Required: installs headless Chromium
export ANTHROPIC_API_KEY=your_anthropic_key   # Optional: enables deep Claude analysis
node bin/meta-ads.js scan "keyword"
node bin/meta-ads.js market "keyword" --top-brands 5 --ads-per-brand 15
node bin/meta-ads.js compare "keyword" --brand "BrandName"
```
Requires Playwright Chromium (`npx playwright install chromium`). No Meta API token needed.

## Testing
```bash
node --test src/**/*.test.js                    # All tests (77 tests)
node --test src/selection/ad-selector.test.js   # Ad selector (18 tests)
node --test src/analysis/pipeline.test.js       # Analysis pipeline (38 tests)
node --test src/reports/compare.test.js         # Market Map + Loophole Doc (21 tests)
```

---

## Build Progress

### Session 1 (COMPLETED)
- [x] Project scaffolding (package.json, Commander.js CLI, directory structure)
- [x] Meta Ad Library web scraper — direct page scraping, no API token required
- [x] Advertiser aggregation + ranking (recent activity + impressions composite score)
- [x] Priority-based ad selection engine (P1-P4 classification + skip rules)
- [x] Deduplication logic (same text prefix per advertiser, keep highest impressions)
- [x] `meta-ads scan` command with full CLI wiring and output formatting
- [x] Unit tests for ad-selector (18 tests, all passing)
- [x] Auto-save scan results to data/scans/

### Session 2 (COMPLETED)
- [x] Ad creative downloader — snapshot HTML fetching, image/video/CTA/landing page extraction
- [x] Analysis pipeline — hook detection, angle classification, offer extraction, CTA, format, Schwartz values
- [x] Per-brand mini-report generator — strategy profile, top ads, cross-brand summary
- [x] `meta-ads market "keyword" --top-brands 5 --ads-per-brand 15` command
- [x] Full pipeline: scan → rank → select per brand → download → analyze → report
- [x] Load from saved scan (--from-scan) or run fresh scan
- [x] Unit tests for analysis pipeline (38 tests, all passing)
- [x] Human-readable terminal report output + JSON export

### Session 3 (COMPLETED)
- [x] Market Map report — brand-by-brand comparison matrices, saturation analysis, coverage heat maps
- [x] Master Loophole Document — market gaps, saturation zones, underexploited opportunities, priority matrix
- [x] Brand-specific gap analysis — blind spots vs competitors, ranked by severity
- [x] `meta-ads compare "keyword" --brand "X"` command with --from-reports and --from-scan modes
- [x] End-to-end pipeline test (market map → loophole doc → brand gaps)
- [x] Unit tests for compare pipeline (21 tests, all passing)
- [x] All 77 tests passing across the full project

### Claude API Integration (COMPLETED)
- [x] Added @anthropic-ai/sdk dependency + config (ANTHROPIC_API_KEY, model, concurrency, retry)
- [x] Claude client module — Anthropic SDK wrapper with retry logic, structured JSON prompts
- [x] Per-ad deep analysis — hook reasoning, angles with evidence, emotional triggers, target audience, unique mechanism, persuasion techniques, copy quality, strategic intent, overall assessment
- [x] Brand strategy synthesis — positioning narrative, messaging strategy, offer psychology, audience profiling, strengths/vulnerabilities/blind spots, strategic direction, threat level
- [x] Market loophole analysis — executive narrative, top opportunities, contrarian plays, immediate actions, brand-specific action plans
- [x] Dual-mode pipeline: Claude primary with heuristic fallback (no API key = pure heuristic)
- [x] Async pipeline: analyzeAd/analyzeAdBatch, generateBrandReport, generateLoopholeDoc all async
- [x] Concurrency control (3 concurrent Claude calls) with progress callbacks
- [x] Updated market.js + compare.js for async pipeline
- [x] All 77 tests passing (heuristic fallback mode in tests)

### Web Scraper Rewrite (COMPLETED)
- [x] Replaced Meta Graph API client with direct web scraper — no META_ACCESS_TOKEN required
- [x] Session management (cookies, fb_dtsg CSRF, lsd tokens)
- [x] Multi-strategy HTML parsing (data-sjs, application/json, ServerJS, regex fallback)
- [x] GraphQL-based pagination via facebook.com/api/graphql/
- [x] Ad downloader updated to use browser-style headers (no token)
- [x] Config updated: removed API token, added scraper settings (timeouts, delays)
- [x] Same public interface preserved: scanAdLibrary, rankAdvertisers exports

### Playwright Scraper Rewrite (COMPLETED)
- [x] Replaced raw HTTP/axios scraper with Playwright headless Chromium — bypasses Meta anti-bot
- [x] Network interception captures structured GraphQL API responses (primary extraction)
- [x] DOM extraction fallback scrapes rendered ad cards when network capture misses data
- [x] Scroll-based pagination (infinite scroll) replaces cursor-based GraphQL pagination
- [x] Stealth browser config: automation detection masking, realistic viewport/UA/locale
- [x] Cookie consent + login wall dismissal
- [x] Same public interface preserved: scanAdLibrary, rankAdvertisers, normalizeAdRecord exports
- [x] All 77 tests passing (tests don't hit network, test selector/pipeline/reports)

## Configuration
All thresholds are in `src/utils/config.js`:
- Impression thresholds: high=50K, moderate=10K, low=1K
- Time windows: P1=14d, P2=30d, P3=7d, P4=60d, skip=180d
- Min primary text: 50 words
- Scraper: 800ms delay between pages, 30 results/page, 20 max pages
- Claude API: model=claude-sonnet-4-5-20250929, maxTokens=4096, maxConcurrent=3, retryAttempts=2
