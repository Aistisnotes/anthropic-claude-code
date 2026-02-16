'use strict';

const { AdType, filterAds, countWords } = require('./src/adFilter');

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
  { id: 'video-2',  type: AdType.VIDEO,  name: 'Silent promo video',    transcript: '',   primaryCopy: 'Shop the summer sale — 50% off everything' },
  { id: 'video-3',  type: AdType.VIDEO,  name: 'Music-only video',      transcript: null, primaryCopy: 'Feel the beat. New headphones, available now.' },
  { id: 'video-4',  type: AdType.VIDEO,  name: 'Broken video ad',       transcript: '',   primaryCopy: '' },
  { id: 'video-5',  type: AdType.VIDEO,  name: 'Whitespace transcript', transcript: '   \t\n  ', primaryCopy: 'Fallback copy for whitespace transcript' },
];

console.log('=== Ad Filter Demo ===\n');
console.log(`Input: ${sampleAds.length} ads\n`);

// Show each ad's status
for (const ad of sampleAds) {
  const wc = countWords(ad.transcript);
  console.log(`  [${ad.type.padEnd(6)}] ${ad.id.padEnd(12)} "${ad.name}" — transcript: ${wc} words`);
}

console.log('\n--- Running filter ---\n');

const start = performance.now();
const kept = filterAds(sampleAds);
const elapsed = (performance.now() - start).toFixed(3);

console.log(`Kept ${kept.length} of ${sampleAds.length} ads (${elapsed}ms)\n`);

for (const ad of kept) {
  const preview = ad.resolvedCopy.text.length > 60
    ? ad.resolvedCopy.text.slice(0, 57) + '...'
    : ad.resolvedCopy.text;
  console.log(`  ✓ ${ad.id.padEnd(12)} source=${ad.resolvedCopy.source.padEnd(12)} "${preview}"`);
}

// Show rejected
const keptIds = new Set(kept.map(a => a.id));
const rejected = sampleAds.filter(a => !keptIds.has(a.id));
if (rejected.length) {
  console.log('');
  for (const ad of rejected) {
    console.log(`  ✗ ${ad.id.padEnd(12)} REJECTED  "${ad.name}"`);
  }
}

console.log('\n=== Done ===');
