// AMC User Manual as a self-contained HTML page - usage: node build_manual_html.js <shots_dir> <out.html>
const fs = require('fs');
const path = require('path');

const [shotsDir, outFile] = process.argv.slice(2);
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const slug = (s) => s.toLowerCase().replace(/^[\d.]+\s*/, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const items = [];
const toc = [];
let figure = 0;
const usedIds = new Set();
const uid = (base) => { let id = base || 'section'; let n = 2; while (usedIds.has(id)) id = `${base}-${n++}`; usedIds.add(id); return id; };

const runs = (x) => (Array.isArray(x) ? x : [{ text: x }]).map((r) => (r.bold ? `<strong>${esc(r.text)}</strong>` : esc(r.text))).join('');
const api = {
  b: (text) => ({ text, bold: true }),
  t: (text) => ({ text }),
  p: (x) => ({ kind: 'p', html: `<p>${runs(x)}</p>` }),
  h1: (text) => { const id = uid(slug(text)); toc.push({ level: 1, text, id }); return { kind: 'h1', text, id }; },
  h2: (text) => { const id = uid(slug(text)); toc.push({ level: 2, text, id }); return { kind: 'h2', html: `<h2 id="${id}">${esc(text)}<a class="anchor" href="#${id}" aria-label="Link">#</a></h2>` }; },
  h3: (text) => ({ kind: 'h3', html: `<h3>${esc(text)}</h3>` }),
  bullet: (x) => ({ kind: 'ul', html: `<li>${runs(x)}</li>` }),
  step: (x) => ({ kind: 'ol', html: `<li>${runs(x)}</li>` }),
  note: (text) => ({ kind: 'note', html: `<aside class="note"><span class="note-icon">i</span><div><strong>Note</strong><p>${esc(text)}</p></div></aside>` }),
  shot: (name, caption) => {
    const ext = fs.existsSync(path.join(shotsDir, name + '.webp')) ? 'webp' : 'png';
    const file = path.join(shotsDir, name + '.' + ext);
    if (!fs.existsSync(file)) return [];
    figure += 1;
    const data = fs.readFileSync(file).toString('base64');
    return [{ kind: 'fig', html: `<figure><button class="zoom" type="button" aria-label="Enlarge: ${esc(caption)}"><img width="1440" height="900" decoding="async" alt="${esc(caption)}" src="data:image/${ext};base64,${data}"></button><figcaption><span>Figure ${figure}</span>${esc(caption)}</figcaption></figure>` }];
  },
  table: (headers, rows) => [{ kind: 'table', html: `<div class="table-wrap"><table><thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c, i) => (i === 0 ? `<th scope="row">${esc(c)}</th>` : `<td>${esc(c)}</td>`)).join('')}</tr>`).join('')}</tbody></table></div>` }],
  add: (...xs) => xs.forEach((x) => (Array.isArray(x) ? items.push(...x) : items.push(x))),
};
require('./manual_content.js')(api);

const { render } = require('../html_shell.js');
const page = render({
  title: 'AMC Management – User Manual',
  meta: 'Odoo 18 · Version 1.0 · 06 November 2026',
  heroTitle: 'Annual Maintenance Contracts',
  heroText: 'Plans and prices, quotations and activation, preventive visits and free services, billing, renewals – and service execution through Helpdesk, Service Job and Field Service.',
  chips: ['amc_management 18.0.1.1.0', 'Warranty Link', 'Service Execution', `${figure} screenshots`],
  items, toc,
});
fs.writeFileSync(outFile, page);
console.log('WROTE', outFile, 'chapters', toc.filter((e) => e.level === 1).length, 'sections', toc.length, 'figures', figure, 'bytes', page.length);
