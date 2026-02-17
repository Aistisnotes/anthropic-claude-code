# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Map

Everything is on main branch. All feature branches have been merged.

## Python Pipeline (meta_ads_analyzer/) - PRODUCTION

- CLI: `meta_ads_analyzer/cli.py`
- Pipeline: `meta_ads_analyzer/pipeline.py`
- Scraper: `meta_ads_analyzer/scraper/meta_library.py`
- Downloader: `meta_ads_analyzer/downloader/media.py`
- Transcriber: `meta_ads_analyzer/transcriber/whisper.py`
- Ad Analyzer: `meta_ads_analyzer/analyzer/ad_analyzer.py`
- Pattern Analyzer: `meta_ads_analyzer/analyzer/pattern_analyzer.py`
- Filter: `meta_ads_analyzer/analyzer/filter.py`
- Quality Gates: `meta_ads_analyzer/quality/gates.py`
- Reporter: `meta_ads_analyzer/reporter/output.py`
- Analysis prompts: `prompts/ad_analysis.txt`, `prompts/pattern_analysis.txt`
- Reports output: `output/reports/`
- Database: `output/meta_ads.db`
- Run command: `meta-ads run "brand.com" --brand "Brand" --max-ads 100`

## Node.js Pipeline (src/) - NEEDS PORTING TO PYTHON

- Scanner: `src/scraper/meta-ad-library.js`
- Selector: `src/selection/ad-selector.js`
- Downloader: `src/scraper/ad-downloader.js`
- Analysis: `src/analysis/pipeline.js` + `claude-client.js`
- Brand Reports: `src/reports/brand-report.js`
- Loophole Doc: `src/reports/loophole-doc.js`
- Market command: `src/commands/market.js`
- Compare command: `src/commands/compare.js`
- Reports output: `data/reports/`
- Run commands:
  - `node bin/meta-ads.js scan "keyword" --pages 3 --select --headlines`
  - `node bin/meta-ads.js market "keyword" --top-brands 5 --ads-per-brand 10`
  - `node bin/meta-ads.js compare "keyword"`

## Current Status

- Python pipeline: production-ready for single brand analysis (full downloads, video transcription, deep Claude analysis)
- Node.js pipeline: working for market research (scan, select, analyze) but data quality is lower (no video transcription, flaky downloads)
- CRITICAL GAP: Node.js market research needs to be ported into Python pipeline so market research gets the same data quality as brand analysis

## Next Priority

Port Node.js market research into Python pipeline:
1. Scan command (keyword search, metadata extraction, advertiser ranking)
2. Ad selection engine (P1-P4 priority, skip rules, dedup)
3. Compare command (market map, loophole document generation)
4. Delete Node.js pipeline once ported

## Hard Rules

1. NEVER make partial fixes. If a fix fails once, rewrite the entire file from scratch on the second attempt.
2. If an HTTP request gets 403 from Meta/Facebook, the ONLY fix is Playwright browser automation. Never use axios, fetch, or got for Meta URLs.
3. Before saying something is "fixed," actually run it and verify the output.
4. If you hit the same error twice, stop and rethink the approach entirely.
5. No secrets in commits.
6. Lint/test before push.
7. Read CLAUDE.md before starting any work.
8. All analysis MUST use Claude API, not heuristic keyword matching.
