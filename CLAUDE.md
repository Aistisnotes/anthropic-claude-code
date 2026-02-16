# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Meta Ads Analyzer — a Python CLI tool that scrapes Meta Ads Library, downloads media, transcribes video ads with Whisper, and analyzes ad strategies using Claude. Built for Mac Studio M3 Max with 96GB RAM.

## Commands

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

## Architecture

8-stage async pipeline (`pipeline.py` orchestrates everything):

```
Scraper (Playwright) → Downloader (yt-dlp/aiohttp) → Transcriber (MLX Whisper)
  → Filter → Ad Analyzer (Claude API) → Quality Gates → Pattern Analyzer (Claude API) → Reporter
```

All intermediate results persist to SQLite (`output/meta_ads.db`).

### Module Layout

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

## Configuration

`config/default.toml` has all defaults. Override via:
1. Custom TOML file (`--config path.toml`)
2. CLI flags (`--max-ads 50`)
3. Environment variables (`META_ADS_SCRAPER_MAX_ADS=200`)

Key settings: `scraper.max_ads` (100), `transcriber.model_size` (large-v3), `transcriber.use_mlx` (true), `analyzer.model` (claude-sonnet-4-20250514), `filter.min_static_copy_words` (500), `quality.min_ads_for_pattern` (10).

## Key Design Decisions

- **Fully async** — asyncio throughout for concurrent downloads, transcriptions, and API calls
- **Quality gates block pattern analysis** — if <10 ads pass filters or confidence is too low, pipeline stops early with a report of why
- **Static ads need 500+ words** — short copy ads are filtered because they don't contain enough strategic depth for analysis
- **Video transcripts get quality-checked** — gibberish, repetition, and truncation detection before accepting
- **SQLite as audit trail** — every pipeline stage persists results for debugging and reanalysis
- **Ruff** for linting, line length 100, target Python 3.11+
