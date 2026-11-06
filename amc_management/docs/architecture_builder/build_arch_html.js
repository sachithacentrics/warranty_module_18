// AMC Technical Architecture as a self-contained HTML page (shown in Odoo under
// Configuration > Documents > Technical Architecture).
// Usage: node build_arch_html.js <diagram_dir> <out.html>
const fs = require('fs');
const path = require('path');
const { render, esc } = require('../html_shell.js');

const [diagDir, outFile] = process.argv.slice(2);
const slug = (s) => s.toLowerCase().replace(/^[\d.]+\s*/, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const items = [];
const toc = [];
let figure = 0;
const usedIds = new Set();
const uid = (base) => { let id = base || 'section'; let n = 2; while (usedIds.has(id)) id = `${base}-${n++}`; usedIds.add(id); return id; };

const fmtRun = (r) => {
  let h = esc(r.text);
  if (r.mono) h = `<code>${h}</code>`;
  if (r.bold) h = `<strong>${h}</strong>`;
  if (r.italics) h = `<em>${h}</em>`;
  return h;
};
const runs = (x) => (typeof x === 'string' ? esc(x) : x.map(fmtRun).join(''));
const pngSize = (buf) => [buf.readUInt32BE(16), buf.readUInt32BE(20)];

const api = {
  run: (text, o = {}) => ({ text, bold: o.bold, mono: o.mono, italics: o.italics }),
  b: (text) => ({ text, bold: true }),
  code: (text) => ({ text, mono: true }),
  p: (x) => (typeof x === 'string' && !x.trim() ? [] : { kind: 'p', html: `<p>${runs(x)}</p>` }),
  h1: (text) => { const id = uid(slug(text)); toc.push({ level: 1, text, id }); return { kind: 'h1', text, id }; },
  h2: (text) => { const id = uid(slug(text)); toc.push({ level: 2, text, id }); return { kind: 'h2', html: `<h2 id="${id}">${esc(text)}<a class="anchor" href="#${id}" aria-label="Link">#</a></h2>` }; },
  h3: (text) => ({ kind: 'h3', html: `<h3>${esc(text)}</h3>` }),
  bullet: (x) => ({ kind: 'ul', html: `<li>${runs(x)}</li>` }),
  note: (text) => ({ kind: 'note', html: `<aside class="note"><span class="note-icon">i</span><div><strong>Design note</strong><p>${esc(text)}</p></div></aside>` }),
  codeBlock: (lines) => [{ kind: 'pre', html: `<pre class="code">${lines.map(esc).join('\n')}</pre>` }],
  diagram: (name, caption) => {
    const file = path.join(diagDir, name + '.png');
    const buf = fs.readFileSync(file);
    const [w, h] = pngSize(buf); // rendered at 2x
    figure += 1;
    return [{ kind: 'fig', html: `<figure class="diagram"><button class="zoom" type="button" aria-label="Enlarge: ${esc(caption)}"><img width="${Math.round(w / 2)}" height="${Math.round(h / 2)}" decoding="async" alt="${esc(caption)}" src="data:image/png;base64,${buf.toString('base64')}"></button><figcaption><span>Figure ${figure}</span>${esc(caption)}</figcaption></figure>` }];
  },
  table: (headers, rows) => [{ kind: 'table', html: `<div class="table-wrap"><table><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c, i) => (i === 0 ? `<th scope="row">${esc(c)}</th>` : `<td>${esc(c)}</td>`)).join('')}</tr>`).join('')}</tbody></table></div>` }],
  add: (...xs) => xs.forEach((x) => (Array.isArray(x) ? items.push(...x) : items.push(x))),
  flush: () => {}, // Word sections (landscape pages) only
};
require('./arch_content.js')(api);

const extraCss = `
code{font-family:Consolas,"Cascadia Mono",Menlo,monospace;font-size:.88em;background:var(--soft);color:var(--accent);padding:1px 6px;border-radius:5px}
pre.code{font:13px/1.55 Consolas,"Cascadia Mono",Menlo,monospace;background:#1e1b24;color:#e9e3ee;padding:16px 18px;border-radius:12px;overflow:auto;margin:14px 0 20px;white-space:pre}
figure.diagram .zoom{background:#fff;padding:14px}
figure.diagram img{width:auto;max-width:100%;margin:0 auto}
tbody th{white-space:normal}
`;
const page = render({
  title: 'AMC Management – Technical Architecture',
  meta: 'Odoo 18 · amc_management 18.0.1.1.0 · 06 November 2026',
  heroTitle: 'Technical Architecture of the AMC Process',
  heroText: 'Module layers, data model, state machines, process flows, pricing / billing / scheduling engines, integration with the warranty service chain, security, reliability, configuration, migration, testing and extension points.',
  chips: ['amc_management', 'amc_management_warranty', 'amc_management_service', `${figure} diagrams`],
  items, toc, extraCss,
});
fs.writeFileSync(outFile, page);
console.log('WROTE', outFile, 'chapters', toc.filter((e) => e.level === 1).length, 'sections', toc.length, 'figures', figure, 'bytes', page.length);
