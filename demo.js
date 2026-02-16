'use strict';

const { AdType, resolveAdCopy, filterAds, countWords, MIN_TRANSCRIPT_WORDS_STATIC } = require('./src/adFilter');

const verbose = process.argv.includes('--verbose') || process.argv.includes('-v');

// Helper: generate filler transcript of N words
function makeTranscript(n) {
  const words = [];
  const pool = ['the', 'quick', 'brown', 'fox', 'jumps', 'over', 'a', 'lazy', 'dog', 'and', 'runs', 'through', 'fields', 'of', 'green', 'grass', 'under', 'blue', 'sky', 'with', 'bright', 'sun'];
  for (let i = 0; i < n; i++) words.push(pool[i % pool.length]);
  return words.join(' ');
}

const sampleAds = [
  // --- Static ads ---
  { id: 'static-1', type: AdType.STATIC, name: 'Long article ad',       transcript: makeTranscript(620) },
  { id: 'static-2', type: AdType.STATIC, name: 'Short blurb ad',        transcript: makeTranscript(80) },
  { id: 'static-3', type: AdType.STATIC, name: 'Borderline ad',         transcript: makeTranscript(500) },
  { id: 'static-4', type: AdType.STATIC, name: 'Empty static ad',       transcript: '' },

  // --- Video ads ---
  { id: 'video-1',  type: AdType.VIDEO,  name: 'Narrated video',        transcript: 'Buy our product now, limited time offer for all customers' },
  { id: 'video-2',  type: AdType.VIDEO,  name: 'Silent promo video',    transcript: '' },
  { id: 'video-3',  type: AdType.VIDEO,  name: 'Music-only video',      transcript: null },
  { id: 'video-4',  type: AdType.VIDEO,  name: 'Whitespace transcript', transcript: '   \t\n  ' },
];

console.log('=== Ad Filter Demo ===');
console.log(`Tip: run with --verbose or -v to see full transcripts\n`);
console.log(`Input: ${sampleAds.length} ads\n`);

const kept = filterAds(sampleAds);
const keptIds = new Set(kept.map(a => a.id));

for (const ad of sampleAds) {
  const wc = countWords(ad.transcript);
  const resolved = resolveAdCopy(ad);
  const status = resolved ? '+' : 'x';
  let reason;

  if (resolved) {
    reason = `KEPT (source: ${resolved.source})`;
  } else if (ad.type === AdType.STATIC) {
    reason = `SKIPPED — transcript ${wc} words (need ${MIN_TRANSCRIPT_WORDS_STATIC})`;
  } else if (ad.type === AdType.VIDEO && wc === 0) {
    reason = `SKIPPED — empty transcript, no fallback`;
  } else {
    reason = `SKIPPED`;
  }

  console.log(`  ${status} [${ad.type.padEnd(6)}] ${ad.id.padEnd(12)} "${ad.name}"`);
  console.log(`    words: ${wc} | ${reason}`);

  if (verbose) {
    const raw = ad.transcript;
    if (raw === null || raw === undefined) {
      console.log(`    transcript: (null)`);
    } else if (raw.trim().length === 0) {
      console.log(`    transcript: (empty)`);
    } else {
      console.log(`    transcript:`);
      // Wrap long transcripts at ~80 chars per line, indented
      const lines = raw.trim().match(/.{1,76}/g) || [];
      for (const line of lines) {
        console.log(`      ${line}`);
      }
    }
    if (resolved) {
      console.log(`    resolved copy:`);
      const copyLines = resolved.text.match(/.{1,76}/g) || [];
      for (const line of copyLines) {
        console.log(`      ${line}`);
      }
    }
    console.log('');
  }
}

console.log(`\nResult: kept ${kept.length} of ${sampleAds.length} ads`);
console.log('\n=== Done ===');
