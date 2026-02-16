const fs = require('fs');
const path = require('path');

const reportFile = process.argv[2] || fs.readdirSync('/Users/am/anthropic-claude-code/data/reports')
  .filter(f => f.endsWith('.json') && !f.startsWith('market') && !f.startsWith('loopholes'))[0];

const reportPath = reportFile.startsWith('/') 
  ? reportFile 
  : path.join('/Users/am/anthropic-claude-code/data/reports', reportFile);

const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));

console.log('='.repeat(80));
console.log(`  BRAND REPORT: ${report.brand.name}`);
console.log('='.repeat(80));
console.log();

console.log('OVERVIEW');
console.log('-'.repeat(80));
console.log(`Total Ads: ${report.brand.totalAds} | Active: ${report.brand.activeAds} | Recent (30d): ${report.brand.recentAds}`);
console.log(`Relevance Score: ${report.brand.relevanceScore} | Activity: ${report.strategy.activityLevel}`);
console.log();

console.log('STRATEGY PROFILE');
console.log('-'.repeat(80));
console.log(`Hook: ${report.strategy.primaryHook} | Angle: ${report.strategy.primaryAngle}`);
console.log(`Format: ${report.strategy.primaryFormat} | Emotion: ${report.strategy.primaryEmotion}`);
console.log(`CTA: ${report.strategy.primaryCta} | Depth: ${report.strategy.contentDepth} (${report.strategy.avgWordCount} words)`);
console.log(`Diversity: ${report.strategy.hookDiversity} hooks, ${report.strategy.angleDiversity} angles`);
if (report.strategy.usesVideo) {
  console.log(`Video Usage: ${report.strategy.videoRatio}%`);
}
console.log();

if (report.strategy.claudeSynthesis) {
  const cs = report.strategy.claudeSynthesis;
  
  console.log('COMPETITIVE INTELLIGENCE (Claude Analysis)');
  console.log('-'.repeat(80));
  console.log();
  
  console.log('POSITIONING:');
  console.log(cs.positioning);
  console.log();
  
  if (cs.messaging) {
    console.log('MESSAGING:');
    console.log(`Core: ${cs.messaging.coreMessage}`);
    console.log(`Tone: ${cs.messaging.tone}`);
    console.log(`Style: ${cs.messaging.copywritingStyle}`);
    console.log();
  }
  
  if (cs.targetAudience) {
    console.log('TARGET AUDIENCE:');
    console.log(`Segment: ${cs.targetAudience.primarySegment}`);
    console.log(`Psychographic: ${cs.targetAudience.psychographic}`);
    console.log(`Awareness: ${cs.targetAudience.awarenessLevel}`);
    console.log();
  }
  
  console.log('STRENGTHS:');
  cs.strengths.forEach(s => console.log(`  + ${s}`));
  console.log();
  
  console.log('VULNERABILITIES:');
  cs.vulnerabilities.forEach(v => console.log(`  - ${v}`));
  console.log();
  
  console.log('BLIND SPOTS:');
  cs.blindSpots.forEach(b => console.log(`  * ${b}`));
  console.log();
  
  console.log(`THREAT LEVEL: ${cs.threatLevel.score}/10`);
  console.log(`${cs.threatLevel.reasoning}`);
  console.log();
  
  console.log('STRATEGIC DIRECTION:');
  console.log(`Phase: ${cs.strategicDirection.phase}`);
  console.log('Likely Next Moves:');
  cs.strategicDirection.likelyNextMoves.forEach(m => console.log(`  > ${m}`));
  console.log();
}

if (report.topAds && report.topAds.length > 0) {
  console.log('TOP ADS');
  console.log('-'.repeat(80));
  report.topAds.forEach((ad, i) => {
    console.log();
    console.log(`${i + 1}. [${ad.priority}] ${ad.headlines?.[0] || 'No headline'}`);
    console.log(`   ${new Date(ad.launchDate).toLocaleDateString()} | ${ad.impressions?.label || '0+'}`);
    console.log(`   Hook: ${ad.analysis?.hook?.type || ad.analysis?.hook} | Angle: ${ad.analysis?.dominantAngle}`);
    if (ad.primaryTextPreview) {
      console.log(`   "${ad.primaryTextPreview}"`);
    }
    if (ad.claudeAnalysis?.overallAssessment) {
      console.log(`   Score: ${ad.claudeAnalysis.overallAssessment.score}/10`);
      console.log(`   ${ad.claudeAnalysis.overallAssessment.summary}`);
    }
  });
}

console.log();
console.log('='.repeat(80));
