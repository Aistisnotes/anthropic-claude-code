# Meta Ads Market Research Pipeline

## Project Overview
CLI tool (`meta-ads`) for surgical market research via Meta Ad Library. Scans metadata first, selects ads by strategic priority, then runs deep analysis only on high-signal ads.

## Architecture
```
bin/meta-ads.js                → CLI entry point (Commander.js)
src/commands/scan.js           → `meta-ads scan` command
src/commands/market.js         → `meta-ads market` command (full pipeline)
src/commands/compare.js        → `meta-ads compare` command (cross-brand)
src/scraper/meta-ad-library.js → Meta Ad Library API client (metadata-only)
src/scraper/ad-downloader.js   → Selective ad creative downloader
src/selection/ad-selector.js   → Priority-based ad selection engine (P1-P4)
src/analysis/pipeline.js       → Heuristic ad analysis pipeline
src/reports/brand-report.js    → Per-brand mini-report generator
src/reports/market-map.js      → Cross-brand Market Map report
src/reports/loophole-doc.js    → Master Loophole Document (gaps + priority matrix)
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

## Analysis Pipeline
Heuristic-based ad text analysis (no LLM required):
- **Hook detection**: question, statistic, bold claim, fear/urgency, story, social proof, curiosity, direct address
- **Messaging angles**: mechanism, social proof, transformation, problem-agitate, scarcity, authority, educational
- **Offer detection**: discount, free trial, guarantee, bonus, free shipping, bundle, subscription, limited time
- **CTA classification**: shop now, learn more, sign up, claim offer, watch, download, contact
- **Format classification**: listicle, testimonial, how-to, long form, minimal, emoji heavy, direct response
- **Emotional register** (Schwartz values): security, achievement, hedonism, stimulation, self-direction, benevolence, conformity, tradition, power, universalism

## Compare Pipeline
Cross-brand analysis outputs:
- **Market Map**: Brand-by-brand comparison matrices (hooks × brands, angles × brands, emotions × brands), saturation analysis (saturated/moderate/whitespace), brand strategy profiles
- **Loophole Document**: Market-wide gaps (nobody uses), saturation zones (everyone uses), underexploited opportunities (1-2 brands use), priority matrix (ranked by gap score × relevance), brand-specific blind spots

## Setup
```bash
npm install
export META_ACCESS_TOKEN=your_facebook_token  # Required: ads_read permission
node bin/meta-ads.js scan "keyword"
node bin/meta-ads.js market "keyword" --top-brands 5 --ads-per-brand 15
node bin/meta-ads.js compare "keyword" --brand "BrandName"
```

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
- [x] Meta Ad Library API client — metadata-only scanning, pagination, rate limiting
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

## Configuration
All thresholds are in `src/utils/config.js`:
- Impression thresholds: high=50K, moderate=10K, low=1K
- Time windows: P1=14d, P2=30d, P3=7d, P4=60d, skip=180d
- Min primary text: 50 words
- API: 500ms delay between pages, 100 results/page, 20 max pages
