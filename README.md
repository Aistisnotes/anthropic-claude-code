# Meta Ads Analyzer

Extract, transcribe, and analyze Meta Ads Library ads at scale. Built for Mac Studio M3 Max with 96GB RAM.

## What it does

1. **Scrapes** Meta Ads Library (100 ads per brand, configurable)
2. **Downloads** video and static ad media
3. **Transcribes** video ads locally using Whisper (MLX-optimized for Apple Silicon)
4. **Filters** ads: video ads kept if transcript quality passes, static ads only if primary copy >= 500 words
5. **Analyzes** each ad with Claude: target customer, pain points, symptoms, root cause, mechanism, delivery mechanism, mass desire, big idea
6. **Quality gates** before pattern analysis: minimum ad count, transcript confidence, analysis confidence, copy quality scoring
7. **Pattern analysis** across all ads: identifies recurring strategies, commonalities, and insights
8. **Reports** in markdown, JSON, or HTML

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

```bash
# Single brand
meta-ads run "Athletic Greens" --brand "AG1"

# With options
meta-ads run "Eight Sleep" --max-ads 50 --format html --no-headless

# Batch mode (10-15 brands)
meta-ads batch brands_example.json

# Custom config
meta-ads run "Organifi" --config my_config.toml
```

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

Designed for 10-15 brands/day, 100 ads each. On Mac Studio M3 Max:
- Whisper large-v3 via MLX: processes ~1min video in ~10-15 seconds
- Claude API: 3 concurrent analysis calls
- Sequential brand processing with configurable pauses
