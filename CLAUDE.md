# CLAUDE.md

## Project Map

- Branch: `claude/meta-ads-scraper-transcribe-KupjO` (Python brand analysis)
- Branch: `claude/add-market-research-layer-34lhA` (Node.js market research)

## Python Pipeline (meta_ads_analyzer/)

- Scraper: `meta_ads_analyzer/scraper/meta_library.py`
- Downloader: `meta_ads_analyzer/downloader/media.py`
- Transcriber: `meta_ads_analyzer/transcriber/whisper.py`
- Analyzer: `meta_ads_analyzer/analyzer/ad_analyzer.py`
- Pattern analyzer: `meta_ads_analyzer/analyzer/pattern_analyzer.py`
- Analysis prompts: `prompts/ad_analysis.txt`, `prompts/pattern_analysis.txt`
- Reports output: `output/reports/`
- Database: `output/meta_ads.db`

## Node.js Pipeline (src/)

- Scanner: `src/scraper/meta-ad-library.js`
- Selector: `src/selection/ad-selector.js`
- Downloader: `src/scraper/ad-downloader.js`
- Analysis: `src/analysis/pipeline.js` + `claude-client.js`
- Reports: `src/reports/brand-report.js` + `loophole-doc.js`
- Market command: `src/commands/market.js`
- Compare command: `src/commands/compare.js`
- Reports output: `data/reports/`

## Current Status

- Python pipeline: production-ready for single brand analysis
- Node.js pipeline: working but needs unification into Python
- Next priority: port Node.js market research into Python pipeline

## Hard Rules

- Never commit API keys or secrets; use environment variables
- Always run linting/tests before pushing
- Keep branch naming convention: `claude/<description>-<id>`
- Do not force-push to shared branches
- Read existing code before modifying it
