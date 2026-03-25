import PDFDocument from 'pdfkit';

// Colors
const NAVY = '#1a1f36';
const CHARCOAL = '#2d3142';
const WHITE = '#ffffff';
const LIGHT_GRAY = '#f4f5f7';
const MID_GRAY = '#e1e4e8';
const DARK_TEXT = '#24292e';
const DIM_TEXT = '#6a737d';
const AMBER = '#d97706';
const AMBER_BG = '#fffbeb';
const AMBER_BORDER = '#f59e0b';
const BLUE = '#2563eb';
const BLUE_BG = '#eff6ff';
const BLUE_BORDER = '#3b82f6';
const GREEN = '#059669';
const RED = '#dc2626';
const ACCENT = '#e8ff47';

const PAGE_W = 595.28; // A4
const PAGE_H = 841.89;
const MARGIN = 40;
const CONTENT_W = PAGE_W - MARGIN * 2;

export function generateReport(data, res) {
  const doc = new PDFDocument({ size: 'A4', margin: MARGIN, bufferPages: true });
  doc.pipe(res);

  const { results, patternSummary, brandName, searchQuery, sessionId } = data;
  const dateStr = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  const summary = patternSummary?.pattern_summary || patternSummary || {};
  const adResults = Object.entries(results || {}).filter(([, v]) => !v.error && !v.parse_error);

  // Collect all loopholes across ads
  const allLoopholes = [];
  for (const [, analysis] of adResults) {
    if (analysis.layer_2?.loopholes) {
      for (const l of analysis.layer_2.loopholes) {
        allLoopholes.push(l);
      }
    }
  }
  allLoopholes.sort((a, b) => (b.score || 0) - (a.score || 0));

  // ==========================================
  // COVER PAGE
  // ==========================================
  doc.rect(0, 0, PAGE_W, PAGE_H).fill(NAVY);

  // Title block
  doc.fontSize(11).fillColor('#8b95a5').text('ADS LIBRARY PATTERNS', MARGIN, 80, { width: CONTENT_W, characterSpacing: 3 });
  doc.fontSize(10).fillColor('#8b95a5').text('STRATEGIC INTELLIGENCE REPORT', MARGIN, 96, { width: CONTENT_W, characterSpacing: 2 });

  doc.moveTo(MARGIN, 125).lineTo(MARGIN + 60, 125).lineWidth(3).strokeColor(ACCENT).stroke();

  const displayName = brandName || searchQuery || 'Market Analysis';
  doc.fontSize(36).fillColor(WHITE).text(displayName, MARGIN, 150, { width: CONTENT_W });

  doc.fontSize(13).fillColor('#8b95a5').text(dateStr, MARGIN, doc.y + 12, { width: CONTENT_W });
  doc.text(`${adResults.length} ads analyzed`, MARGIN, doc.y + 4, { width: CONTENT_W });

  // Key Finding callout
  if (summary.biggest_market_loophole) {
    const callY = 320;
    doc.rect(MARGIN, callY, CONTENT_W, 90).fill('#2a2f42');
    doc.rect(MARGIN, callY, 4, 90).fill(AMBER_BORDER);
    doc.fontSize(9).fillColor(AMBER).text('KEY FINDING', MARGIN + 20, callY + 14, { characterSpacing: 1.5 });
    doc.fontSize(11).fillColor(WHITE).text(summary.biggest_market_loophole, MARGIN + 20, callY + 32, {
      width: CONTENT_W - 40,
      lineGap: 3,
    });
  }

  // Key Insight callout
  if (summary.brand_strengths?.length) {
    const callY = 430;
    doc.rect(MARGIN, callY, CONTENT_W, 80).fill('#2a2f42');
    doc.rect(MARGIN, callY, 4, 80).fill(BLUE_BORDER);
    doc.fontSize(9).fillColor(BLUE_BORDER).text('KEY INSIGHT', MARGIN + 20, callY + 14, { characterSpacing: 1.5 });
    doc.fontSize(11).fillColor(WHITE).text(
      `Consistent strength: ${summary.brand_strengths[0]}`,
      MARGIN + 20, callY + 32,
      { width: CONTENT_W - 40, lineGap: 3 }
    );
  }

  // Contents
  const tocY = 560;
  doc.fontSize(12).fillColor(ACCENT).text('CONTENTS', MARGIN, tocY, { characterSpacing: 2 });
  doc.moveTo(MARGIN, tocY + 18).lineTo(MARGIN + 40, tocY + 18).lineWidth(1).strokeColor(ACCENT).stroke();

  const tocItems = ['Pattern Summary', 'Validated Loopholes', 'Priority Matrix', 'What NOT To Do'];
  if (adResults.length > 0) tocItems.push(`Ad Analyses (${adResults.length})`);

  let tocItemY = tocY + 30;
  doc.fontSize(10).fillColor('#8b95a5');
  tocItems.forEach((item, i) => {
    doc.text(`${String(i + 1).padStart(2, '0')}  ${item}`, MARGIN + 8, tocItemY);
    tocItemY += 18;
  });

  // ==========================================
  // HELPER FUNCTIONS
  // ==========================================
  function addFooter() {
    const pages = doc.bufferedPageRange();
    for (let i = 0; i < pages.count; i++) {
      doc.switchToPage(i);
      doc.fontSize(7).fillColor(DIM_TEXT)
        .text(`Ads Library Patterns \u00B7 Strategic Intelligence \u00B7 ${dateStr}`, MARGIN, PAGE_H - 30, { width: CONTENT_W - 40, align: 'left' })
        .text(`${i + 1}`, PAGE_W - MARGIN - 30, PAGE_H - 30, { width: 30, align: 'right' });
    }
  }

  function checkPage(needed = 100) {
    if (doc.y + needed > PAGE_H - 60) doc.addPage();
  }

  function sectionHeader(title) {
    doc.addPage();
    doc.rect(0, 0, PAGE_W, 70).fill(CHARCOAL);
    doc.fontSize(16).fillColor(WHITE).text(title, MARGIN, 25, { width: CONTENT_W });
    doc.y = 90;
  }

  function subHeader(title) {
    checkPage(60);
    doc.moveDown(0.5);
    doc.fontSize(12).fillColor(DARK_TEXT).text(title, MARGIN, doc.y, { width: CONTENT_W, underline: true });
    doc.moveDown(0.4);
  }

  function calloutBox(label, text, color, bgColor, borderColor) {
    checkPage(80);
    const boxY = doc.y;
    const textOpts = { width: CONTENT_W - 40, lineGap: 2 };
    const textH = doc.fontSize(10).heightOfString(text, textOpts);
    const boxH = Math.max(textH + 40, 50);
    doc.rect(MARGIN, boxY, CONTENT_W, boxH).fill(bgColor);
    doc.rect(MARGIN, boxY, 4, boxH).fill(borderColor);
    doc.fontSize(8).fillColor(color).text(label, MARGIN + 16, boxY + 10, { characterSpacing: 1.2 });
    doc.fontSize(10).fillColor(DARK_TEXT).text(text, MARGIN + 16, boxY + 26, textOpts);
    doc.y = boxY + boxH + 10;
  }

  function bulletList(items, indent = MARGIN + 8) {
    if (!items?.length) return;
    doc.fontSize(10).fillColor(DARK_TEXT);
    for (const item of items) {
      checkPage(20);
      doc.text(`\u2022  ${item}`, indent, doc.y, { width: CONTENT_W - (indent - MARGIN) - 8, lineGap: 2 });
      doc.moveDown(0.2);
    }
  }

  function scorePill(score, maxScore = 50) {
    const ratio = score / maxScore;
    if (ratio >= 0.7) return { color: GREEN, label: `${score}/${maxScore}` };
    if (ratio >= 0.4) return { color: AMBER, label: `${score}/${maxScore}` };
    return { color: RED, label: `${score}/${maxScore}` };
  }

  // ==========================================
  // PATTERN SUMMARY
  // ==========================================
  sectionHeader('Pattern Summary');

  if (summary.most_common_hook_types?.length) {
    subHeader('Dominant Hook Types');
    bulletList(summary.most_common_hook_types);
  }

  if (summary.dominant_rc_mechanism_combos?.length) {
    subHeader('Root Cause + Mechanism Combos');
    bulletList(summary.dominant_rc_mechanism_combos);
  }

  if (summary.biggest_market_loophole) {
    calloutBox('BIGGEST MARKET LOOPHOLE', summary.biggest_market_loophole, AMBER, AMBER_BG, AMBER_BORDER);
  }

  if (summary.brand_strengths?.length) {
    subHeader('Brand Strengths');
    bulletList(summary.brand_strengths);
  }

  if (summary.brand_weaknesses?.length) {
    subHeader('Brand Weaknesses');
    bulletList(summary.brand_weaknesses);
  }

  if (summary.recurring_proof_gaps?.length) {
    subHeader('Recurring Proof Gaps');
    bulletList(summary.recurring_proof_gaps);
  }

  if (summary.recurring_objection_gaps?.length) {
    subHeader('Recurring Objection Gaps');
    bulletList(summary.recurring_objection_gaps);
  }

  // Awareness distribution
  if (summary.awareness_level_distribution) {
    subHeader('Awareness Level Distribution');
    const dist = summary.awareness_level_distribution;
    for (const [level, count] of Object.entries(dist)) {
      checkPage(18);
      doc.fontSize(10).fillColor(DARK_TEXT).text(`${level}: ${count}`, MARGIN + 8, doc.y, { width: CONTENT_W });
    }
    doc.moveDown(0.5);
  }

  // Stats callout
  if (summary.average_copy_quality !== undefined || summary.average_analysis_confidence !== undefined) {
    const statsText = [
      summary.total_ads_analyzed ? `${summary.total_ads_analyzed} ads analyzed` : null,
      summary.average_copy_quality ? `Avg copy quality: ${(summary.average_copy_quality * 100).toFixed(0)}%` : null,
      summary.average_analysis_confidence ? `Avg confidence: ${(summary.average_analysis_confidence * 100).toFixed(0)}%` : null,
    ].filter(Boolean).join('  \u00B7  ');
    if (statsText) {
      calloutBox('ANALYSIS STATS', statsText, BLUE, BLUE_BG, BLUE_BORDER);
    }
  }

  // ==========================================
  // VALIDATED LOOPHOLES
  // ==========================================
  if (allLoopholes.length > 0) {
    sectionHeader('Validated Loopholes');

    const topLoopholes = allLoopholes.slice(0, 8);
    topLoopholes.forEach((l, i) => {
      checkPage(160);

      const medal = i === 0 ? '\uD83E\uDD47' : i === 1 ? '\uD83E\uDD48' : i === 2 ? '\uD83E\uDD49' : `#${i + 1}`;
      const pill = scorePill(l.score || 0);

      // Card header
      const cardY = doc.y;
      doc.rect(MARGIN, cardY, CONTENT_W, 30).fill(CHARCOAL);
      doc.fontSize(11).fillColor(WHITE).text(`${medal}  ${l.gap || 'Loophole'}`, MARGIN + 12, cardY + 8, { width: CONTENT_W - 80 });
      doc.fontSize(10).fillColor(pill.color).text(pill.label, PAGE_W - MARGIN - 60, cardY + 9, { width: 50, align: 'right' });

      doc.y = cardY + 30;

      // Card body
      const bodyY = doc.y;
      doc.rect(MARGIN, bodyY, CONTENT_W, 1).fill(MID_GRAY);
      doc.y = bodyY + 8;

      if (l.gap) {
        doc.fontSize(8).fillColor(DIM_TEXT).text('THE GAP', MARGIN + 12, doc.y, { characterSpacing: 1 });
        doc.moveDown(0.2);
        doc.fontSize(10).fillColor(DARK_TEXT).text(l.gap, MARGIN + 12, doc.y, { width: CONTENT_W - 24, lineGap: 2 });
        doc.moveDown(0.5);
      }

      if (l.science) {
        doc.fontSize(8).fillColor(DIM_TEXT).text('WHY IT\'S MASSIVE', MARGIN + 12, doc.y, { characterSpacing: 1 });
        doc.moveDown(0.2);
        doc.fontSize(10).fillColor(DARK_TEXT).text(l.science, MARGIN + 12, doc.y, { width: CONTENT_W - 24, lineGap: 2 });
        doc.moveDown(0.5);
      }

      if (l.execution_hooks?.length) {
        doc.fontSize(8).fillColor(DIM_TEXT).text('EXECUTION', MARGIN + 12, doc.y, { characterSpacing: 1 });
        doc.moveDown(0.2);
        for (const hook of l.execution_hooks) {
          doc.fontSize(10).fillColor(DARK_TEXT).text(`\u2022  ${hook}`, MARGIN + 16, doc.y, { width: CONTENT_W - 32, lineGap: 2 });
          doc.moveDown(0.15);
        }
        doc.moveDown(0.3);
      }

      // Effort + Timeline
      const metaLine = [
        l.effort ? `Effort: ${l.effort}` : null,
        l.timeline ? `Timeline: ${l.timeline}` : null,
      ].filter(Boolean).join('  \u00B7  ');
      if (metaLine) {
        doc.fontSize(9).fillColor(DIM_TEXT).text(metaLine, MARGIN + 12, doc.y, { width: CONTENT_W - 24 });
      }

      doc.moveDown(1);
    });
  }

  // ==========================================
  // PRIORITY MATRIX TABLE
  // ==========================================
  if (allLoopholes.length > 0) {
    sectionHeader('Priority Matrix');

    const tableTop = doc.y;
    const colWidths = [35, 200, 55, 70, 100];
    const headers = ['Rank', 'Loophole', 'Score', 'Effort', 'Timeline'];

    // Header row
    let colX = MARGIN;
    doc.rect(MARGIN, tableTop, CONTENT_W, 24).fill(CHARCOAL);
    doc.fontSize(9).fillColor(WHITE);
    headers.forEach((h, i) => {
      doc.text(h, colX + 6, tableTop + 7, { width: colWidths[i] - 12 });
      colX += colWidths[i];
    });
    doc.y = tableTop + 24;

    // Data rows
    allLoopholes.slice(0, 15).forEach((l, i) => {
      checkPage(24);
      const rowY = doc.y;
      const bgColor = i % 2 === 0 ? LIGHT_GRAY : WHITE;
      doc.rect(MARGIN, rowY, CONTENT_W, 22).fill(bgColor);

      colX = MARGIN;
      const pill = scorePill(l.score || 0);
      const rowData = [
        `${i + 1}`,
        (l.gap || '').slice(0, 55) + ((l.gap || '').length > 55 ? '...' : ''),
        pill.label,
        l.effort || '-',
        l.timeline || '-',
      ];
      const rowColors = [DARK_TEXT, DARK_TEXT, pill.color, DARK_TEXT, DIM_TEXT];

      rowData.forEach((val, j) => {
        doc.fontSize(9).fillColor(rowColors[j]).text(val, colX + 6, rowY + 6, { width: colWidths[j] - 12 });
        colX += colWidths[j];
      });

      doc.y = rowY + 22;
    });
  }

  // ==========================================
  // WHAT NOT TO DO
  // ==========================================
  const whatNotToDo = [];
  for (const [, analysis] of adResults) {
    if (analysis.layer_2?.what_not_to_do) {
      for (const item of analysis.layer_2.what_not_to_do) {
        if (!whatNotToDo.includes(item)) whatNotToDo.push(item);
      }
    }
  }

  if (whatNotToDo.length > 0) {
    sectionHeader('What NOT To Do');
    calloutBox('WARNING', 'These approaches may seem tempting but are strategically wrong for this market.', RED, '#fef2f2', RED);
    doc.moveDown(0.5);
    bulletList(whatNotToDo);
  }

  // ==========================================
  // INDIVIDUAL AD ANALYSES (APPENDIX)
  // ==========================================
  if (adResults.length > 0) {
    sectionHeader('Ad Analyses — Appendix');

    for (const [adId, analysis] of adResults) {
      checkPage(120);

      // Ad header
      const adHeaderY = doc.y;
      doc.rect(MARGIN, adHeaderY, CONTENT_W, 28).fill(CHARCOAL);
      const adName = analysis.page_name || adId;
      const adFormat = analysis.format || 'unknown';
      doc.fontSize(10).fillColor(WHITE).text(`${adName}  \u00B7  ${adFormat.toUpperCase()}  \u00B7  ${adId}`, MARGIN + 12, adHeaderY + 8, { width: CONTENT_W - 24 });
      doc.y = adHeaderY + 36;

      // Layer 1
      if (analysis.layer_1) {
        const l1 = analysis.layer_1;

        if (l1.persuasion_architecture) {
          const pa = l1.persuasion_architecture;
          if (pa.big_idea) {
            calloutBox('BIG IDEA', pa.big_idea, BLUE, BLUE_BG, BLUE_BORDER);
          }

          const archItems = [
            pa.mass_desire ? `Mass desire: ${pa.mass_desire}` : null,
            pa.ad_angle ? `Angle: ${pa.ad_angle}` : null,
            pa.hook_type ? `Hook: ${pa.hook_type}` : null,
            pa.awareness_level ? `Awareness: ${pa.awareness_level}` : null,
            pa.sophistication_level ? `Sophistication: ${pa.sophistication_level}/5` : null,
            pa.cta_strategy ? `CTA: ${pa.cta_strategy}` : null,
          ].filter(Boolean);
          if (archItems.length) bulletList(archItems);
        }

        if (l1.target?.avatar) {
          checkPage(40);
          doc.fontSize(9).fillColor(DIM_TEXT).text('TARGET AVATAR', MARGIN + 8, doc.y, { characterSpacing: 1 });
          doc.moveDown(0.2);
          doc.fontSize(10).fillColor(DARK_TEXT).text(l1.target.avatar, MARGIN + 8, doc.y, { width: CONTENT_W - 16, lineGap: 2 });
          doc.moveDown(0.5);
        }

        if (l1.concept) {
          calloutBox('CONCEPT (RC + MECHANISM)', l1.concept, AMBER, AMBER_BG, AMBER_BORDER);
        }

        if (l1.pain?.pain_points?.length) {
          checkPage(30);
          doc.fontSize(9).fillColor(DIM_TEXT).text('PAIN POINTS', MARGIN + 8, doc.y, { characterSpacing: 1 });
          doc.moveDown(0.2);
          bulletList(l1.pain.pain_points);
        }

        if (l1.proof?.proof_gaps?.length) {
          checkPage(30);
          doc.fontSize(9).fillColor(DIM_TEXT).text('PROOF GAPS', MARGIN + 8, doc.y, { characterSpacing: 1 });
          doc.moveDown(0.2);
          bulletList(l1.proof.proof_gaps);
        }

        if (l1.scores) {
          checkPage(25);
          const scoreText = [
            l1.scores.copy_quality_score !== undefined ? `Copy quality: ${(l1.scores.copy_quality_score * 100).toFixed(0)}%` : null,
            l1.scores.analysis_confidence !== undefined ? `Confidence: ${(l1.scores.analysis_confidence * 100).toFixed(0)}%` : null,
          ].filter(Boolean).join('  \u00B7  ');
          doc.fontSize(9).fillColor(DIM_TEXT).text(scoreText, MARGIN + 8, doc.y);
          doc.moveDown(0.5);
        }
      }

      // Layer 2 competitive verdict
      if (analysis.layer_2?.competitive_verdict) {
        calloutBox('COMPETITIVE VERDICT', analysis.layer_2.competitive_verdict, RED, '#fef2f2', RED);
      }

      doc.moveDown(1);
      doc.moveTo(MARGIN, doc.y).lineTo(PAGE_W - MARGIN, doc.y).lineWidth(0.5).strokeColor(MID_GRAY).stroke();
      doc.moveDown(0.5);
    }
  }

  // ==========================================
  // FINALIZE
  // ==========================================
  addFooter();
  doc.end();
}
