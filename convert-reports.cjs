#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

const reportsDir = '/Users/am/anthropic-claude-code/data/reports';
const outputDir = path.join(reportsDir, 'markdown');

// Create markdown output directory
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

// Function to convert brand report to markdown
function brandReportToMarkdown(report) {
  const brand = report.brand;
  const strategy = report.strategy;

  let md = `# Brand Report: ${brand.name}\n\n`;
  md += `**Generated:** ${new Date(report.meta.reportDate).toLocaleDateString()}\n\n`;
  md += `---\n\n`;

  // Overview
  md += `## Overview\n\n`;
  md += `- **Total Ads:** ${brand.totalAds}\n`;
  md += `- **Active Ads:** ${brand.activeAds}\n`;
  md += `- **Recent Ads (30d):** ${brand.recentAds}\n`;
  md += `- **Relevance Score:** ${brand.relevanceScore}\n`;
  md += `- **Activity Level:** ${strategy.activityLevel}\n\n`;

  // Strategy Profile
  md += `## Strategy Profile\n\n`;
  md += `- **Primary Hook:** ${strategy.primaryHook}\n`;
  md += `- **Primary Angle:** ${strategy.primaryAngle}\n`;
  md += `- **Primary Format:** ${strategy.primaryFormat}\n`;
  md += `- **Primary Emotion:** ${strategy.primaryEmotion}\n`;
  md += `- **Primary CTA:** ${strategy.primaryCta}\n`;
  md += `- **Content Depth:** ${strategy.contentDepth} (avg ${strategy.avgWordCount} words)\n`;
  md += `- **Hook Diversity:** ${strategy.hookDiversity} types\n`;
  md += `- **Angle Diversity:** ${strategy.angleDiversity} types\n`;
  if (strategy.usesVideo) {
    md += `- **Video Usage:** ${strategy.videoRatio}% of ads\n`;
  }
  md += `\n`;

  // Claude Synthesis
  if (strategy.claudeSynthesis) {
    const cs = strategy.claudeSynthesis;

    md += `## Competitive Intelligence (Claude Analysis)\n\n`;

    md += `### Positioning\n\n${cs.positioning}\n\n`;

    md += `### Messaging\n\n`;
    md += `**Core Message:** ${cs.messaging.coreMessage}\n\n`;
    md += `**Tone:** ${cs.messaging.tone}\n\n`;
    md += `**Style:** ${cs.messaging.copywritingStyle}\n\n`;

    md += `### Target Audience\n\n`;
    md += `**Primary Segment:** ${cs.targetAudience.primarySegment}\n\n`;
    md += `**Psychographic:** ${cs.targetAudience.psychographic}\n\n`;
    md += `**Awareness Level:** ${cs.targetAudience.awarenessLevel}\n\n`;

    md += `### Strengths\n\n`;
    cs.strengths.forEach(s => md += `- ${s}\n`);
    md += `\n`;

    md += `### Vulnerabilities\n\n`;
    cs.vulnerabilities.forEach(v => md += `- ${v}\n`);
    md += `\n`;

    md += `### Blind Spots\n\n`;
    cs.blindSpots.forEach(b => md += `- ${b}\n`);
    md += `\n`;

    md += `### Threat Assessment\n\n`;
    md += `**Threat Level:** ${cs.threatLevel.score}/10\n\n`;
    md += `**Reasoning:** ${cs.threatLevel.reasoning}\n\n`;

    md += `### Strategic Direction\n\n`;
    md += `**Phase:** ${cs.strategicDirection.phase}\n\n`;
    md += `**Likely Next Moves:**\n\n`;
    cs.strategicDirection.likelyNextMoves.forEach(m => md += `- ${m}\n`);
    md += `\n`;
  }

  // Top Ads
  if (report.topAds && report.topAds.length > 0) {
    md += `## Top Ads\n\n`;
    report.topAds.forEach((ad, i) => {
      md += `### ${i + 1}. [${ad.priority}] ${ad.headlines?.[0] || 'No headline'}\n\n`;
      md += `- **Launch Date:** ${new Date(ad.launchDate).toLocaleDateString()}\n`;
      md += `- **Hook:** ${ad.analysis?.hook?.type || ad.analysis?.hook || 'unknown'}\n`;
      md += `- **Angle:** ${ad.analysis?.dominantAngle || 'unknown'}\n`;
      if (ad.primaryTextPreview) {
        md += `- **Preview:** ${ad.primaryTextPreview}\n`;
      }
      if (ad.claudeAnalysis?.overallAssessment) {
        md += `\n**Score:** ${ad.claudeAnalysis.overallAssessment.score}/10\n\n`;
        md += `**Assessment:** ${ad.claudeAnalysis.overallAssessment.summary}\n\n`;
      }
      md += `\n`;
    });
  }

  return md;
}

// Process all brand report JSON files
const files = fs.readdirSync(reportsDir).filter(f =>
  f.endsWith('.json') &&
  !f.startsWith('market-map') &&
  !f.startsWith('loopholes')
);

console.log(`Converting ${files.length} reports to markdown...\n`);

files.forEach(file => {
  const jsonPath = path.join(reportsDir, file);
  const report = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
  const markdown = brandReportToMarkdown(report);
  const mdPath = path.join(outputDir, file.replace('.json', '.md'));
  fs.writeFileSync(mdPath, markdown, 'utf8');
  console.log(`✓ ${path.basename(mdPath)}`);
});

console.log(`\nMarkdown reports saved to: ${outputDir}`);
console.log('Opening directory...');

// Open the markdown directory
require('child_process').exec(`open "${outputDir}"`);
