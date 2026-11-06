// AMC User Manual (Word) - usage: node build_manual.js <shots_dir> <out.docx>
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, ImageRun, Table, TableRow, TableCell,
  WidthType, ShadingType, AlignmentType, PageBreak, TableOfContents, Footer, Header, PageNumber,
  LevelFormat, BorderStyle,
} = require('docx');

const [shotsDir, outFile] = process.argv.slice(2);
const FONT = 'Calibri';
const CONTENT = 9026; // A4 width 11906 - 2 x 1440 margins (DXA)
const ACCENT = '1F4E79';
let figure = 0;
const missing = [];

const p = (text, opts = {}) => new Paragraph({
  spacing: { after: 120 }, ...opts,
  children: Array.isArray(text) ? text : [new TextRun({ text, font: FONT, size: 22 })],
});
const b = (text) => new TextRun({ text, bold: true, font: FONT, size: 22 });
const t = (text) => new TextRun({ text, font: FONT, size: 22 });
const h1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun(text)] });
const h2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] });
const h3 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(text)] });
const bullet = (parts) => new Paragraph({ numbering: { reference: 'bullets', level: 0 }, spacing: { after: 60 },
  children: (Array.isArray(parts) ? parts : [t(parts)]) });
const step = (parts) => new Paragraph({ numbering: { reference: 'steps', level: 0 }, spacing: { after: 60 },
  children: (Array.isArray(parts) ? parts : [t(parts)]) });
const note = (text) => new Paragraph({
  spacing: { before: 60, after: 160 }, shading: { type: ShadingType.CLEAR, fill: 'EAF1FB', color: 'auto' },
  border: { left: { style: BorderStyle.SINGLE, size: 18, color: ACCENT, space: 6 } },
  children: [new TextRun({ text: 'Note: ', bold: true, font: FONT, size: 21, color: ACCENT }),
    new TextRun({ text, font: FONT, size: 21 })],
});

function shot(name, caption) {
  const file = path.join(shotsDir, name + '.png');
  if (!fs.existsSync(file)) { missing.push(name); return []; }
  figure += 1;
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true,
      children: [new ImageRun({ type: 'png', data: fs.readFileSync(file),
        transformation: { width: 600, height: 375 },
        altText: { title: caption, description: caption, name } })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
      children: [new TextRun({ text: `Figure ${figure} – ${caption}`, italics: true, font: FONT, size: 18, color: '595959' })] }),
  ];
}

function table(headers, rows, widths) {
  const total = widths.reduce((a, c) => a + c, 0);
  const mk = (cells, header) => new TableRow({ tableHeader: header,
    children: cells.map((c, i) => new TableCell({
      width: { size: widths[i], type: WidthType.DXA },
      shading: header ? { type: ShadingType.CLEAR, fill: ACCENT, color: 'auto' } : undefined,
      margins: { top: 60, bottom: 60, left: 100, right: 100 },
      children: [new Paragraph({ children: [new TextRun({ text: c, bold: header, font: FONT, size: 19,
        color: header ? 'FFFFFF' : '000000' })] })] })) });
  return [new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: [mk(headers, true), ...rows.map((r) => mk(r, false))] }), p('')];
}

const body = [];
const add = (...items) => items.forEach((i) => (Array.isArray(i) ? body.push(...i) : body.push(i)));

// ------------------------------------------------------------------ cover
add(
  new Paragraph({ spacing: { before: 2400, after: 200 }, children: [new TextRun({ text: 'AMC Management', bold: true, size: 64, font: FONT, color: ACCENT })] }),
  new Paragraph({ spacing: { after: 600 }, children: [new TextRun({ text: 'Annual Maintenance Contracts – User Manual', size: 36, font: FONT, color: '404040' })] }),
  ...table(['Item', 'Details'], [
    ['System', 'Odoo 18 – Warranty Management solution'],
    ['Modules', 'amc_management 18.0.1.1.0, amc_management_warranty 18.0.1.0.0, amc_management_service 18.0.1.0.0'],
    ['Audience', 'AMC users, coordinators, managers, approvers, Helpdesk users, technicians, accountants'],
    ['Version / date', '1.0 – 06 November 2026'],
    ['Screens', 'Captured from a demonstration database (sample customers and amounts)'],
  ], [2600, 6426]),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun('Contents')] }),
  new TableOfContents('Contents', { hyperlink: true, headingStyleRange: '1-2' }),
  p('Right-click the table and choose Update Field to refresh the page numbers.', { children: [new TextRun({ text: 'Right-click the table and choose Update Field to refresh the page numbers.', italics: true, size: 18, font: FONT, color: '808080' })] }),
);

require('./manual_content.js')({ p, b, t, h1, h2, h3, bullet, step, note, shot, table, add });

const doc = new Document({
  creator: 'AMC Management', title: 'AMC Management – User Manual',
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 32, bold: true, color: ACCENT }, paragraph: { spacing: { before: 240, after: 160 }, keepNext: true, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 27, bold: true, color: '2E75B6' }, paragraph: { spacing: { before: 240, after: 120 }, keepNext: true, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 23, bold: true, color: '404040' }, paragraph: { spacing: { before: 180, after: 80 }, keepNext: true, outlineLevel: 2 } },
    ],
  },
  numbering: { config: [
    { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    { reference: 'steps', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
  ] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: 'AMC Management – User Manual', size: 16, color: '808080', font: FONT })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: ['Page ', PageNumber.CURRENT, ' of ', PageNumber.TOTAL_PAGES], size: 16, color: '808080', font: FONT })] })] }) },
    children: body,
  }],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(outFile, buffer);
  console.log('WROTE', outFile, 'figures', figure, 'missing', missing.join(',') || 'none');
});
