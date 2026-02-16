'use strict';

const fs = require('fs');
const path = require('path');
const { AdType, filterAds, resolveAdCopy, countWords, MIN_TRANSCRIPT_WORDS_STATIC } = require('./src/adFilter');
const { extractComponents } = require('./src/adExtractor');
const { analyzePatterns } = require('./src/patternAnalyzer');
const { generateReport } = require('./src/reportGenerator');

// --- Load brand data ---
const dataFile = process.argv[2] || path.join(__dirname, 'data', 'brand-glow-vitamins.json');
if (!fs.existsSync(dataFile)) {
  console.error(`File not found: ${dataFile}`);
  console.error('Usage: node demo.js [path/to/brand-data.json]');
  process.exit(1);
}

const brandData = JSON.parse(fs.readFileSync(dataFile, 'utf8'));
const { brand, ads } = brandData;

console.log(`Loading ${ads.length} ads for "${brand}"...\n`);

// --- Step 1: Filter ---
const kept = filterAds(ads);
const keptIds = new Set(kept.map(a => a.id));

const skippedReasons = ads
  .filter(a => !keptIds.has(a.id))
  .map(a => {
    const wc = countWords(a.transcript);
    let reason;
    if (a.type === AdType.STATIC) {
      reason = `transcript ${wc} words (need ${MIN_TRANSCRIPT_WORDS_STATIC})`;
    } else if (a.type === AdType.VIDEO && wc === 0) {
      reason = 'empty transcript';
    } else {
      reason = 'did not pass filter';
    }
    return { id: a.id, type: a.type, name: a.name, reason };
  });

const filterSummary = {
  total: ads.length,
  kept: kept.length,
  skipped: ads.length - kept.length,
  skippedReasons,
};

console.log(`Filter: kept ${kept.length}/${ads.length} ads\n`);

// --- Step 2: Extract components ---
const extractions = kept.map(ad => extractComponents(ad));

// --- Step 3: Analyze patterns ---
const patterns = analyzePatterns(extractions);

// --- Step 4: Generate report ---
const report = generateReport(brand, filterSummary, patterns, extractions);

console.log(report);

// --- Save report to file ---
const reportPath = path.join(__dirname, 'data', `report-${brand.toLowerCase().replace(/\s+/g, '-')}.txt`);
fs.writeFileSync(reportPath, report, 'utf8');
console.log(`\nReport saved to: ${reportPath}`);
