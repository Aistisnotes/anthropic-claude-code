# Meta Ads Market Research Pipeline

## Project Overview
CLI tool (`meta-ads`) for surgical market research via Meta Ad Library. Scans metadata first, selects ads by strategic priority, then runs deep analysis only on high-signal ads.

## Architecture
```
bin/meta-ads.js                → CLI entry point (Commander.js)
src/commands/scan.js           → `meta-ads scan` command
src/commands/market.js         → `meta-ads market` command (full pipeline)
src/scraper/meta-ad-library.js → Meta Ad Library API client (metadata-only)
src/scraper/ad-downloader.js   → Selective ad creative downloader
src/selection/ad-selector.js   → Priority-based ad selection engine (P1-P4)
src/analysis/pipeline.js       → Heuristic ad analysis pipeline
src/reports/brand-report.js    → Per-brand mini-report generator
src/utils/config.js            → Configuration (thresholds, paths, API settings)
src/utils/logger.js            → Colored terminal logging
src/utils/formatters.js        → Table/JSON/summary output formatters
```

## Commands
- `meta-ads scan "keyword"` — Scan Meta Ad Library metadata, rank advertisers, show selection breakdown
  - Flags: `--country`, `--pages`, `--status`, `--top`, `--headlines`, `--select`, `--json`, `--output`
- `meta-ads market "keyword"` — Full pipeline: scan → select → download → analyze → report
  - Flags: `--country`, `--pages`, `--status`, `--top-brands`, `--ads-per-brand`, `--no-download`, `--from-scan`, `--json`, `--output`

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

## Setup
```bash
npm install
export META_ACCESS_TOKEN=your_facebook_token  # Required: ads_read permission
node bin/meta-ads.js scan "keyword"
node bin/meta-ads.js market "keyword" --top-brands 5 --ads-per-brand 15
```

## Testing
```bash
node --test src/**/*.test.js                    # All tests (56 tests)
node --test src/selection/ad-selector.test.js   # Ad selector (18 tests)
node --test src/analysis/pipeline.test.js       # Analysis pipeline (38 tests)
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

### Session 3 (NEXT)
Build `meta-ads compare` command:
- [ ] Market Map report (brand-by-brand comparison, saturation, gaps, Schwartz scale)
- [ ] Master Loophole Document (market-wide gaps, brand-specific gaps, priority matrix)
- [ ] `meta-ads compare --brand "X" --market-keyword "Y"` command
- [ ] End-to-end pipeline test

Key files to create:
- `src/commands/compare.js`
- `src/reports/market-map.js`
- `src/reports/loophole-doc.js`

The compare command should:
1. Load market reports for multiple brands (from Session 2 output)
2. Build cross-brand comparison matrix (hooks, angles, emotions, offers)
3. Identify market saturation zones (where everyone competes)
4. Identify gaps/loopholes (underused angles, emotions, formats)
5. Generate Market Map report + Master Loophole Document

## Configuration
All thresholds are in `src/utils/config.js`:
- Impression thresholds: high=50K, moderate=10K, low=1K
- Time windows: P1=14d, P2=30d, P3=7d, P4=60d, skip=180d
- Min primary text: 50 words
- API: 500ms delay between pages, 100 results/page, 20 max pages
