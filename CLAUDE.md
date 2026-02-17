# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Map

- Branch: `claude/meta-ads-scraper-transcribe-KupjO` (Python brand analysis)
- Branch: `claude/add-market-research-layer-34lhA` (Node.js market research)

## Current Status

- Python pipeline: production-ready for single brand analysis
- Node.js pipeline: working but needs unification into Python
- Next priority: port Node.js market research into Python pipeline

---

## Python Pipeline — Meta Ads Analyzer (`meta_ads_analyzer/`)

A Python CLI tool that scrapes Meta Ads Library, downloads media, transcribes video ads with Whisper, and analyzes ad strategies using Claude. Built for Mac Studio M3 Max with 96GB RAM.

### Python Commands

```bash
# Install
pip install -e ".[apple-silicon]"    # Apple Silicon (MLX Whisper)
pip install -e ".[generic]"          # Other platforms (OpenAI Whisper)
pip install -e ".[dev]"              # Dev dependencies (pytest, ruff)

# First-time setup
meta-ads install-browser             # Install Playwright Chromium

# Run
meta-ads run "Athletic Greens" --brand "AG1"
meta-ads run "Eight Sleep" --max-ads 50 --format html --no-headless
meta-ads batch brands_example.json   # Process multiple brands

# Tests
python -m pytest tests/test_smoke.py -v

# Lint
ruff check .
ruff format .
```

### Python Architecture

8-stage async pipeline (`pipeline.py` orchestrates everything):

```
Scraper (Playwright) → Downloader (yt-dlp/aiohttp) → Transcriber (MLX Whisper)
  → Filter → Ad Analyzer (Claude API) → Quality Gates → Pattern Analyzer (Claude API) → Reporter
```

All intermediate results persist to SQLite (`output/meta_ads.db`).

### Python Module Layout

- **`cli.py`** — Typer CLI with `run`, `batch`, `install-browser` commands
- **`pipeline.py`** — `Pipeline` (single brand) and `BatchPipeline` (multi-brand) orchestrators
- **`models.py`** — Pydantic v2 models: `ScrapedAd`, `DownloadedMedia`, `Transcript`, `AdContent`, `AdAnalysis`, `PatternReport`, `QualityReport`
- **`scraper/meta_library.py`** — Playwright automation of Meta Ads Library with smart scrolling and JS DOM extraction
- **`downloader/media.py`** — Async media downloads: yt-dlp for videos (handles Facebook CDN), aiohttp for images, 5 concurrent
- **`transcriber/whisper.py`** — MLX Whisper (Apple Silicon) with fallback to OpenAI Whisper, lazy model loading, confidence scoring
- **`analyzer/filter.py`** — Keeps video ads with good transcripts + static ads with 500+ word copy; deduplicates via SHA256
- **`analyzer/ad_analyzer.py`** — Sends individual ads to Claude (3 concurrent) extracting: pain points, root cause, mechanism, avatar, hooks, awareness level
- **`analyzer/pattern_analyzer.py`** — Aggregates all ad analyses into cross-ad patterns and strategic insights via Claude
- **`quality/gates.py`** — Pre-pattern-analysis checks: minimum ad count, confidence thresholds, filter ratio warnings. Also includes `CopyQualityChecker` for transcript quality (gibberish, repetition, truncation detection)
- **`reporter/output.py`** — Generates markdown/JSON/HTML reports
- **`db/store.py`** — Async SQLite via aiosqlite. Tables: `runs`, `scraped_ads`, `ad_content`, `ad_analyses`
- **`utils/config.py`** — TOML config loader with env var overrides (`META_ADS_` prefix)
- **`prompts/`** — Claude prompt templates for ad analysis and pattern analysis

### Python Configuration

`config/default.toml` has all defaults. Override via:
1. Custom TOML file (`--config path.toml`)
2. CLI flags (`--max-ads 50`)
3. Environment variables (`META_ADS_SCRAPER_MAX_ADS=200`)

Key settings: `scraper.max_ads` (100), `transcriber.model_size` (large-v3), `transcriber.use_mlx` (true), `analyzer.model` (claude-sonnet-4-20250514), `filter.min_static_copy_words` (500), `quality.min_ads_for_pattern` (10).

### Python Key Design Decisions

- **Fully async** — asyncio throughout for concurrent downloads, transcriptions, and API calls
- **Quality gates block pattern analysis** — if <10 ads pass filters or confidence is too low, pipeline stops early with a report of why
- **Static ads need 500+ words** — short copy ads are filtered because they don't contain enough strategic depth for analysis
- **Video transcripts get quality-checked** — gibberish, repetition, and truncation detection before accepting
- **SQLite as audit trail** — every pipeline stage persists results for debugging and reanalysis
- **Ruff** for linting, line length 100, target Python 3.11+

### Python Output

- Reports: `output/reports/`
- Database: `output/meta_ads.db`

---

## Node.js Pipeline — Market Research (`src/`)

CLI tool (`meta-ads`) for surgical market research via Meta Ad Library. Scans metadata first, selects ads by strategic priority, then runs deep Claude-powered analysis on high-signal ads (with heuristic fallback when no API key).

### Node.js Architecture

```
bin/meta-ads.js                → CLI entry point (Commander.js)
src/commands/scan.js           → `meta-ads scan` command
src/commands/market.js         → `meta-ads market` command (full pipeline)
src/commands/compare.js        → `meta-ads compare` command (cross-brand)
src/scraper/meta-ad-library.js → Meta Ad Library web scraper (no API token)
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

### Node.js Commands

- `meta-ads scan "keyword"` — Scan Meta Ad Library metadata, rank advertisers, show selection breakdown
  - Flags: `--country`, `--pages`, `--status`, `--top`, `--headlines`, `--select`, `--json`, `--output`
- `meta-ads market "keyword"` — Full pipeline: scan → select → download → analyze → report
  - Flags: `--country`, `--pages`, `--status`, `--top-brands`, `--ads-per-brand`, `--no-download`, `--from-scan`, `--json`, `--output`
- `meta-ads compare "keyword"` — Cross-brand comparison: Market Map + Loophole Document
  - Flags: `--brand`, `--from-reports`, `--from-scan`, `--top-brands`, `--ads-per-brand`, `--no-download`, `--json`, `--output`

### Node.js Setup

```bash
npm install
export ANTHROPIC_API_KEY=your_anthropic_key   # Optional: enables deep Claude analysis
node bin/meta-ads.js scan "keyword"
node bin/meta-ads.js market "keyword" --top-brands 5 --ads-per-brand 15
node bin/meta-ads.js compare "keyword" --brand "BrandName"
```

No Meta API token required — the scraper fetches data directly from the public Ad Library page.

### Node.js Testing

```bash
node --test src/**/*.test.js                    # All tests (77 tests)
node --test src/selection/ad-selector.test.js   # Ad selector (18 tests)
node --test src/analysis/pipeline.test.js       # Analysis pipeline (38 tests)
node --test src/reports/compare.test.js         # Market Map + Loophole Doc (21 tests)
```

### Ad Selection Priority System

- **P1 ACTIVE_WINNER**: <14 days + high impressions (50K+) — brand is scaling this NOW
- **P2 PROVEN_RECENT**: <30 days + moderate impressions (10K+) — survived testing
- **P3 STRATEGIC_DIRECTION**: <7 days, any impressions — where brand is heading
- **P4 RECENT_MODERATE**: <60 days + high impressions (50K+) — still relevant
- **SKIP**: Legacy (6+ months), failed tests (low impressions + >30 days), thin text (<50 words), duplicates

### Analysis Pipeline (Dual Mode)

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

### Compare Pipeline

Cross-brand analysis outputs:
- **Market Map**: Brand-by-brand comparison matrices (hooks × brands, angles × brands, emotions × brands), saturation analysis (saturated/moderate/whitespace), brand strategy profiles
- **Loophole Document**: Market-wide gaps (nobody uses), saturation zones (everyone uses), underexploited opportunities (1-2 brands use), priority matrix (ranked by gap score × relevance), brand-specific blind spots, Claude strategic recommendations

### Node.js Configuration

All thresholds are in `src/utils/config.js`:
- Impression thresholds: high=50K, moderate=10K, low=1K
- Time windows: P1=14d, P2=30d, P3=7d, P4=60d, skip=180d
- Min primary text: 50 words
- Scraper: 800ms delay between pages, 30 results/page, 20 max pages
- Claude API: model=claude-sonnet-4-5-20250929, maxTokens=4096, maxConcurrent=3, retryAttempts=2

### Node.js Output

- Reports: `data/reports/`
- Scans: `data/scans/`
- Downloads: `data/downloads/`

---

## Build Progress (Node.js)

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

---

## Hard Rules

- Never commit API keys or secrets; use environment variables
- Always run linting/tests before pushing
- Keep branch naming convention: `claude/<description>-<id>`
- Do not force-push to shared branches
- Read existing code before modifying it
