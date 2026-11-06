// AMC Technical Architecture (Word) - usage: node build_arch.js <diagram_dir> <out.docx>
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, ImageRun, Table, TableRow, TableCell,
  WidthType, ShadingType, AlignmentType, PageBreak, TableOfContents, Footer, Header, PageNumber,
  LevelFormat, BorderStyle, PageOrientation,
} = require('docx');

const [diagDir, outFile] = process.argv.slice(2);
const FONT = 'Calibri';
const MONO = 'Consolas';
const ACCENT = '1F4E79';
let figure = 0;

const run = (text, o = {}) => new TextRun({ text, font: o.mono ? MONO : FONT, size: o.size || 22, bold: o.bold, italics: o.italics, color: o.color });
const p = (parts, o = {}) => new Paragraph({ spacing: { after: 120 }, ...o,
  children: (typeof parts === 'string' ? [run(parts)] : parts) });
const code = (text) => run(text, { mono: true, size: 19, color: '7A1F3D' });
const b = (text) => run(text, { bold: true });
const h1 = (text, first) => new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: !first, children: [new TextRun(text)] });
const h2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] });
const h3 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(text)] });
const bullet = (parts) => new Paragraph({ numbering: { reference: 'bullets', level: 0 }, spacing: { after: 60 },
  children: (typeof parts === 'string' ? [run(parts)] : parts) });
const note = (text) => new Paragraph({ spacing: { before: 60, after: 160 },
  shading: { type: ShadingType.CLEAR, fill: 'EAF1FB', color: 'auto' },
  border: { left: { style: BorderStyle.SINGLE, size: 18, color: ACCENT, space: 6 } },
  children: [run('Design note: ', { bold: true, color: ACCENT, size: 21 }), run(text, { size: 21 })] });
const codeBlock = (lines) => lines.map((line, i) => new Paragraph({ spacing: { after: 0, before: i ? 0 : 60 },
  shading: { type: ShadingType.CLEAR, fill: 'F4F4F4', color: 'auto' },
  children: [run(line || ' ', { mono: true, size: 17 })] })).concat([p('')]);

function diagram(name, caption, maxWidth = 600, maxHeight = 820) {
  const file = path.join(diagDir, name + '.png');
  const buf = fs.readFileSync(file);
  const w = buf.readUInt32BE(16); const h = buf.readUInt32BE(20);
  let width = maxWidth; let height = Math.round(h * width / w);
  if (height > maxHeight) { height = maxHeight; width = Math.round(w * height / h); }
  figure += 1;
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true,
      children: [new ImageRun({ type: 'png', data: buf, transformation: { width, height },
        altText: { title: caption, description: caption, name } })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
      children: [run(`Figure ${figure} – ${caption}`, { italics: true, size: 18, color: '595959' })] }),
  ];
}

function table(headers, rows, widths) {
  const total = widths.reduce((a, c) => a + c, 0);
  const mk = (cells, header) => new TableRow({ tableHeader: header, cantSplit: true,
    children: cells.map((c, i) => new TableCell({
      width: { size: widths[i], type: WidthType.DXA },
      shading: header ? { type: ShadingType.CLEAR, fill: ACCENT, color: 'auto' } : undefined,
      margins: { top: 50, bottom: 50, left: 90, right: 90 },
      children: [new Paragraph({ children: [new TextRun({ text: c, bold: header, font: (!header && i === 0 && /[._(]/.test(c)) ? MONO : FONT,
        size: (!header && i === 0 && /[._(]/.test(c)) ? 17 : 18, color: header ? 'FFFFFF' : '000000' })] })] })) });
  return [new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: [mk(headers, true), ...rows.map((r) => mk(r, false))] }), p('')];
}

const P = 9026; // portrait content width (A4, 1" margins)
const L = 13958; // landscape content width
const sections = [];
let cur = [];
const add = (...items) => items.forEach((i) => (Array.isArray(i) ? cur.push(...i) : cur.push(i)));
const flush = (landscape) => { sections.push({ landscape, children: cur }); cur = []; };

// =============================================================== cover + TOC
add(
  new Paragraph({ spacing: { before: 2200, after: 200 }, children: [run('AMC Management', { bold: true, size: 64, color: ACCENT })] }),
  new Paragraph({ spacing: { after: 500 }, children: [run('Technical Architecture of the AMC Process', { size: 36, color: '404040' })] }),
  ...table(['Item', 'Details'], [
    ['Platform', 'Odoo 18.0 (Community + Enterprise: helpdesk, industry_fsm, worksheet)'],
    ['Modules', 'amc_management 18.0.1.1.0 · amc_management_warranty 18.0.1.0.0 · amc_management_service 18.0.1.0.0'],
    ['Repository', 'warranty_module_18 (custom addons root)'],
    ['Requirement sources', 'Warranty Module SRS V1 (81 p.), AMC Consolidated Requirements (AMC-A01 … H06)'],
    ['Audience', 'Developers, solution architects, technical consultants, support engineers'],
    ['Version / date', '1.0 – 06 November 2026'],
  ], [2400, 6626]),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun('Contents')] }),
  new TableOfContents('Contents', { hyperlink: true, headingStyleRange: '1-2' }),
);

require('./arch_content.js')({ run, p, code, b, h1, h2, h3, bullet, note, codeBlock, diagram, table, add, flush });

const docSections = sections.map((s, i) => ({
  properties: { page: { size: s.landscape
    ? { width: 11906, height: 16838, orientation: PageOrientation.LANDSCAPE }
    : { width: 11906, height: 16838 }, margin: { top: 1300, bottom: 1300, left: 1440, right: 1440 } } },
  headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [run('AMC Management – Technical Architecture', { size: 16, color: '808080' })] })] }) },
  footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: ['Page ', PageNumber.CURRENT, ' of ', PageNumber.TOTAL_PAGES], size: 16, color: '808080', font: FONT })] })] }) },
  children: s.children,
}));

const doc = new Document({
  creator: 'AMC Management', title: 'AMC Management – Technical Architecture',
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 32, bold: true, color: ACCENT }, paragraph: { spacing: { before: 240, after: 160 }, keepNext: true, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 26, bold: true, color: '2E75B6' }, paragraph: { spacing: { before: 220, after: 110 }, keepNext: true, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: FONT, size: 23, bold: true, color: '404040' }, paragraph: { spacing: { before: 160, after: 80 }, keepNext: true, outlineLevel: 2 } },
    ],
  },
  numbering: { config: [
    { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
  ] },
  sections: docSections,
});
Packer.toBuffer(doc).then((buffer) => { fs.writeFileSync(outFile, buffer); console.log('WROTE', outFile, 'figures', figure, 'sections', sections.length); });
