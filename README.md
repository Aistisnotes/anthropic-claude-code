# Meta Ads Analyzer

Extract, transcribe, and analyze Meta Ads Library ads at scale. Built for Mac Studio M3 Max with 96GB RAM.

## What it does

### Single Brand Analysis
1. **Scrapes** Meta Ads Library (100 ads per brand, configurable)
2. **Downloads** video and static ad media
3. **Transcribes** video ads locally using Whisper (MLX-optimized for Apple Silicon)
4. **Filters** ads: video ads kept if transcript quality passes, static ads only if primary copy >= 500 words
5. **Analyzes** each ad with Claude: target customer, pain points, symptoms, root cause, mechanism, delivery mechanism, mass desire, big idea
6. **Quality gates** before pattern analysis: minimum ad count, transcript confidence, analysis confidence, copy quality scoring
7. **Pattern analysis** across all ads: identifies recurring strategies, commonalities, and insights
8. **Reports** in markdown, JSON, or HTML

### Market Research (NEW)
1. **Scans** keyword for all ads, extracts metadata (impressions, launch dates, copy)
2. **Ranks** advertisers by relevance (recent activity + impression volume + active ad count)
3. **Selects** top N brands, picks best ads per brand using P1-P4 priority classification
4. **Analyzes** each brand using full pipeline (download, transcribe, Claude analysis)
5. **Reports** per-brand insights with cross-brand comparison table

## Setup

```bash
# Install dependencies
pip install -e ".[apple-silicon]"

# Install Playwright browser (first time only)
meta-ads install-browser

# Set your Anthropic API key
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Usage

### Single Brand Analysis

```bash
# Analyze a single brand
meta-ads run "Athletic Greens" --brand "AG1"

# With options
meta-ads run "Eight Sleep" --max-ads 50 --format html --no-headless

# Custom config
meta-ads run "Organifi" --config my_config.toml
```

### Batch Mode

```bash
# Analyze multiple brands from JSON file (10-15 brands)
meta-ads batch brands_example.json
```

### Market Research (NEW)

Scan Meta Ads Library for a keyword, rank advertisers, and analyze top brands:

```bash
# Scan only - extract metadata and rank advertisers
meta-ads scan "weight loss supplement" --select --top 25

# Full market research - analyze top brands
meta-ads market "weight loss supplement" --top-brands 5 --ads-per-brand 10

# Load from saved scan (skip scraping step)
meta-ads market "keyword" --from-scan output/scans/scan_keyword_20240601_120000.json

# Save scan results for later
meta-ads scan "keyword" --output my_scan.json
```

**Market research workflow:**
1. **Scan** - Scrape all ads for a keyword, extract metadata, rank advertisers by relevance
2. **Select** - For each top brand, select up to N best ads using P1-P4 priority
3. **Analyze** - Run full pipeline (download, transcribe, analyze) on selected ads
4. **Report** - Generate per-brand reports in subdirectory: `output/reports/market_{keyword}_{timestamp}/`

**Ad Selection Priority:**
- **P1 (Active Winner)**: ≤14 days old + ≥50K impressions (scaling NOW)
- **P2 (Proven Recent)**: ≤30 days old + ≥10K impressions (survived testing)
- **P3 (Strategic Direction)**: ≤7 days old (brand new tests)
- **P4 (Recent Moderate)**: ≤60 days old + ≥50K impressions (still relevant)

Ads are automatically filtered to skip:
- Legacy ads (≥180 days old)
- Thin text (<50 words primary copy)
- Failed tests (low impressions + old)
- Duplicates (same advertiser + text prefix)

## Configuration

Edit `config/default.toml` or pass `--config`. Environment variables override with `META_ADS_` prefix:

```bash
META_ADS_SCRAPER_MAX_ADS=200 meta-ads run "brand"
```

## Project structure

```
meta_ads_analyzer/
├── cli.py                  # CLI entry point
├── pipeline.py             # Pipeline orchestrator
├── models.py               # Pydantic data models
├── scraper/
│   └── meta_library.py     # Playwright-based Meta Ads Library scraper
├── downloader/
│   └── media.py            # Video/image downloader (yt-dlp + aiohttp)
├── transcriber/
│   └── whisper.py          # Whisper transcription (MLX or OpenAI)
├── analyzer/
│   ├── filter.py           # Ad filtering and classification
│   ├── ad_analyzer.py      # Single-ad Claude analysis
│   └── pattern_analyzer.py # Cross-ad pattern analysis
├── quality/
│   └── gates.py            # Quality gates and copy quality checks
├── reporter/
│   └── output.py           # Report generation (MD/JSON/HTML)
├── db/
│   └── store.py            # SQLite storage for pipeline state
└── utils/
    ├── config.py           # TOML config loader
    └── logging.py          # Rich logging setup
config/
    └── default.toml        # Default configuration
prompts/
    ├── ad_analysis.txt     # Single-ad analysis prompt
    └── pattern_analysis.txt # Pattern analysis prompt
```

## Quality gates

Before running pattern analysis, the pipeline checks:
- Minimum analyzed ad count (default: 10)
- Average transcript confidence threshold
- Average analysis confidence threshold
- Copy quality score threshold
- Filter ratio warning (too many ads filtered = bad scrape/targeting)

## Scale

**Single brand mode:** 10-15 brands/day, 100 ads each.

**Market research mode:** Scan 1 keyword → analyze top 5 brands, 10 ads each = 50 total ads.

On Mac Studio M3 Max:
- Whisper large-v3 via MLX: processes ~1min video in ~10-15 seconds
- Claude API: 3 concurrent analysis calls
- Sequential brand processing with configurable pauses

Market research is faster than analyzing 5 brands individually because:
- Single scan covers all brands (no repeated scraping)
- Smart ad selection (P1-P4 priority) focuses on most relevant ads
- Shared pipeline infrastructure
