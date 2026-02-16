'use strict';

const { AdType, filterAds, countWords } = require('./src/adFilter');
const videoAnalyzer = require('./src/videoAnalyzer');

// Helper: generate filler transcript of N words
function makeTranscript(n) {
  const words = [];
  const pool = ['the', 'quick', 'brown', 'fox', 'jumps', 'over', 'a', 'lazy', 'dog', 'and', 'runs', 'through', 'fields', 'of', 'green', 'grass', 'under', 'blue', 'sky', 'with', 'bright', 'sun'];
  for (let i = 0; i < n; i++) words.push(pool[i % pool.length]);
  return words.join(' ');
}

// Simulate the visual extraction pipeline for the demo
const originalExtract = videoAnalyzer.extractVisualContent;
videoAnalyzer.extractVisualContent = async function simulatedExtract(ad, opts) {
  // Simulate: some videos have extractable visuals, some don't
  if (ad.id === 'video-2') {
    return {
      overlayText: ['SUMMER SALE', '50% OFF EVERYTHING'],
      headlines: ['Shop the Collection'],
      sceneDescription: 'Model walking on beach wearing sunglasses and summer outfit',
      costCents: 12,
      elapsedMs: 1800,
    };
  }
  if (ad.id === 'video-3') {
    return {
      overlayText: [],
      headlines: ['Feel the Beat'],
      sceneDescription: 'Close-up of premium headphones with pulsing bass visualization',
      costCents: 8,
      elapsedMs: 1200,
    };
  }
  // video-4: nothing extractable (dark/abstract)
  if (ad.id === 'video-4') {
    return null; // extraction failed
  }
  // video-5: whitespace transcript, but has visual text
  if (ad.id === 'video-5') {
    return {
      overlayText: ['NEW ARRIVALS'],
      headlines: [],
      sceneDescription: 'Clothing rack with new items being revealed',
      costCents: 6,
      elapsedMs: 900,
    };
  }
  return originalExtract(ad, opts);
};

const sampleAds = [
  // --- Static ads ---
  { id: 'static-1', type: AdType.STATIC, name: 'Long article ad',       transcript: makeTranscript(620) },
  { id: 'static-2', type: AdType.STATIC, name: 'Short blurb ad',        transcript: makeTranscript(80) },
  { id: 'static-3', type: AdType.STATIC, name: 'Borderline ad',         transcript: makeTranscript(500) },
  { id: 'static-4', type: AdType.STATIC, name: 'Empty static ad',       transcript: '' },

  // --- Video ads ---
  { id: 'video-1',  type: AdType.VIDEO,  name: 'Narrated video',        transcript: 'Buy our product now, limited time offer for all customers', videoUrl: 'https://cdn.example.com/v1.mp4' },
  { id: 'video-2',  type: AdType.VIDEO,  name: 'Silent promo video',    transcript: '',   videoUrl: 'https://cdn.example.com/v2.mp4' },
  { id: 'video-3',  type: AdType.VIDEO,  name: 'Music-only video',      transcript: null, videoUrl: 'https://cdn.example.com/v3.mp4' },
  { id: 'video-4',  type: AdType.VIDEO,  name: 'Dark abstract video',   transcript: '',   videoUrl: 'https://cdn.example.com/v4.mp4' },
  { id: 'video-5',  type: AdType.VIDEO,  name: 'Whitespace transcript', transcript: '   \t\n  ', videoUrl: 'https://cdn.example.com/v5.mp4' },
];

async function main() {
  console.log('=== Ad Filter Demo (Visual Extraction) ===\n');
  console.log(`Input: ${sampleAds.length} ads\n`);

  for (const ad of sampleAds) {
    const wc = countWords(ad.transcript);
    console.log(`  [${ad.type.padEnd(6)}] ${ad.id.padEnd(12)} "${ad.name}" — transcript: ${wc} words`);
  }

  console.log('\n--- Running filter ---\n');

  const start = performance.now();
  const kept = await filterAds(sampleAds);
  const elapsed = (performance.now() - start).toFixed(3);

  console.log(`Kept ${kept.length} of ${sampleAds.length} ads (${elapsed}ms)\n`);

  for (const ad of kept) {
    const preview = ad.resolvedCopy.text.length > 60
      ? ad.resolvedCopy.text.slice(0, 57) + '...'
      : ad.resolvedCopy.text;
    console.log(`  + ${ad.id.padEnd(12)} source=${ad.resolvedCopy.source.padEnd(18)} "${preview}"`);
  }

  const keptIds = new Set(kept.map(a => a.id));
  const rejected = sampleAds.filter(a => !keptIds.has(a.id));
  if (rejected.length) {
    console.log('');
    for (const ad of rejected) {
      console.log(`  x ${ad.id.padEnd(12)} SKIPPED  "${ad.name}"`);
    }
  }

  console.log('\n=== Done ===');
}

main().catch(console.error);
