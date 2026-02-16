# Meta Ads Market Research Pipeline

## Project Overview
CLI tool (`meta-ads`) for surgical market research via Meta Ad Library. Scans metadata first, selects ads by strategic priority, then runs deep analysis only on high-signal ads.

## Architecture
```
bin/meta-ads.js              → CLI entry point (Commander.js)
src/commands/scan.js         → `meta-ads scan` command
src/scraper/meta-ad-library.js → Meta Ad Library API client (metadata-only)
src/selection/ad-selector.js → Priority-based ad selection engine (P1-P4)
src/utils/config.js          → Configuration (thresholds, paths, API settings)
src/utils/logger.js          → Colored terminal logging
src/utils/formatters.js      → Table/JSON/summary output formatters
```

## Commands
- `meta-ads scan "keyword"` — Scan Meta Ad Library metadata, rank advertisers, show selection breakdown
  - Flags: `--country`, `--pages`, `--status`, `--top`, `--headlines`, `--select`, `--json`, `--output`

## Ad Selection Priority System
- **P1 ACTIVE_WINNER**: <14 days + high impressions (50K+) — brand is scaling this NOW
- **P2 PROVEN_RECENT**: <30 days + moderate impressions (10K+) — survived testing
- **P3 STRATEGIC_DIRECTION**: <7 days, any impressions — where brand is heading
- **P4 RECENT_MODERATE**: <60 days + high impressions (50K+) — still relevant
- **SKIP**: Legacy (6+ months), failed tests (low impressions + >30 days), thin text (<50 words), duplicates

## Setup
```bash
npm install
export META_ACCESS_TOKEN=your_facebook_token  # Required: ads_read permission
node bin/meta-ads.js scan "keyword"
```

## Testing
```bash
node --test src/selection/ad-selector.test.js
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

### Session 2 (NEXT)
Build `meta-ads market` command:
- [ ] Ad creative downloader (selective, based on selection results)
- [ ] Full analysis pipeline runner on selected ads
- [ ] Per-brand mini-report generation
- [ ] `meta-ads market "keyword" --top-brands 5 --ads-per-brand 15` command
- [ ] Integration test with real keyword

Key files to create:
- `src/commands/market.js` — market command
- `src/scraper/ad-downloader.js` — selective ad downloader
- `src/analysis/pipeline.js` — analysis pipeline runner
- `src/reports/brand-report.js` — per-brand mini-report generator

The market command should:
1. Run scan internally (or load from saved scan JSON)
2. Pick top N brands by `rankAdvertisers()` score
3. Run `selectAdsForBrand()` for each brand (already built)
4. Download selected ad creatives only
5. Run analysis pipeline on downloaded ads
6. Generate per-brand mini-reports

### Session 3 (LATER)
Build `meta-ads compare` command:
- [ ] Market Map report (brand-by-brand comparison, saturation, gaps, Schwartz scale)
- [ ] Master Loophole Document (market-wide gaps, brand-specific gaps, priority matrix)
- [ ] `meta-ads compare --brand "X" --market-keyword "Y"` command
- [ ] End-to-end pipeline test

Key files to create:
- `src/commands/compare.js`
- `src/reports/market-map.js`
- `src/reports/loophole-doc.js`

## Configuration
All thresholds are in `src/utils/config.js`:
- Impression thresholds: high=50K, moderate=10K, low=1K
- Time windows: P1=14d, P2=30d, P3=7d, P4=60d, skip=180d
- Min primary text: 50 words
- API: 500ms delay between pages, 100 results/page, 20 max pages
