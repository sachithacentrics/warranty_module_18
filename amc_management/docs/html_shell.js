// Shared HTML page of the AMC documentation (user manual, technical architecture): sticky header,
// sidebar contents with active section, topic search, chapter pager, image zoom, responsive /
// print layout. render(o) -> html; o: title, meta, heroTitle, heroText, chips, items, toc, extraCss.
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function render(o) {
  const { items, toc } = o;
// Group consecutive list items; wrap each chapter (h1) in a section.
let html = '';
let open = null;
let inSection = false;
for (const it of items) {
  if (open && it.kind !== open) { html += `</${open}>`; open = null; }
  if (it.kind === 'h1') {
    if (inSection) html += '</section>';
    html += `<section class="chapter" id="${it.id}"><h1>${esc(it.text)}<a class="anchor" href="#${it.id}" aria-label="Link">#</a></h1>`;
    inSection = true;
  } else if (it.kind === 'ul' || it.kind === 'ol') {
    if (!open) { html += `<${it.kind}${it.kind === 'ol' ? ' class="steps"' : ''}>`; open = it.kind; }
    html += it.html;
  } else {
    html += it.html;
  }
}
if (open) html += `</${open}>`;
if (inSection) html += '</section>';

let nav = '';
let chapterOpen = false;
for (const e of toc) {
  if (e.level === 1) {
    if (chapterOpen) nav += '</ul></li>';
    nav += `<li class="lvl1"><a href="#${e.id}" data-target="${e.id}">${esc(e.text)}</a><ul>`;
    chapterOpen = true;
  } else {
    nav += `<li class="lvl2"><a href="#${e.id}" data-target="${e.id}">${esc(e.text)}</a></li>`;
  }
}
if (chapterOpen) nav += '</ul></li>';

const page = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(o.title)}</title>
<style>
:root{--bg:#f5f7fb;--panel:#ffffff;--ink:#1d2433;--muted:#5b6475;--line:#e3e7ef;--accent:#714b67;--accent-2:#017e84;--soft:#f3eef2;--note:#e8f4f5;--shadow:0 10px 30px rgba(20,30,60,.08)}
@media (prefers-color-scheme:dark){:root{--bg:#12151c;--panel:#1a1f29;--ink:#e6e9ef;--muted:#a3abba;--line:#2b3342;--accent:#c79bbb;--accent-2:#4fc3c8;--soft:#2a2130;--note:#15302f;--shadow:0 10px 30px rgba(0,0,0,.35)}}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:84px}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 "Segoe UI",Roboto,Helvetica,Arial,sans-serif}
header.top{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:14px;padding:12px 24px;background:linear-gradient(90deg,#714b67,#8a5e80);color:#fff;box-shadow:0 2px 10px rgba(0,0,0,.15)}
header.top .logo{width:36px;height:36px;border-radius:9px;background:rgba(255,255,255,.18);display:grid;place-items:center;font-weight:700;letter-spacing:.5px}
header.top h1{font-size:18px;margin:0;font-weight:600}header.top small{opacity:.8;margin-left:auto;font-size:13px}
#menu-toggle{display:none;background:transparent;border:1px solid rgba(255,255,255,.5);color:#fff;border-radius:8px;padding:6px 10px;font-size:15px;cursor:pointer}
.layout{display:grid;grid-template-columns:300px minmax(0,1fr);max-width:1400px;margin:0 auto}
nav.toc{position:sticky;top:61px;height:calc(100vh - 61px);overflow:auto;padding:22px 14px 40px 22px;border-right:1px solid var(--line);background:var(--panel)}
nav.toc .search{width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink);font:inherit;font-size:14px;margin-bottom:14px}
nav.toc ul{list-style:none;margin:0;padding:0}nav.toc li.lvl1{margin:4px 0}
nav.toc li.lvl1>a{display:block;padding:7px 10px;border-radius:8px;font-weight:600;font-size:14.5px;color:var(--ink);text-decoration:none}
nav.toc li.lvl1>ul{margin:2px 0 8px 10px;border-left:2px solid var(--line)}
nav.toc li.lvl2>a{display:block;padding:4px 10px 4px 14px;font-size:13.5px;color:var(--muted);text-decoration:none;border-left:2px solid transparent;margin-left:-2px}
nav.toc a:hover{color:var(--accent)}nav.toc a.active{color:var(--accent);background:var(--soft)}nav.toc li.lvl2>a.active{background:none;border-left-color:var(--accent);font-weight:600}
main{padding:28px 40px 80px;min-width:0}
.hero{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:30px 34px;box-shadow:var(--shadow);margin-bottom:28px}
.hero h2{margin:0 0 6px;font-size:30px}.hero p{margin:0;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}.chips span{background:var(--soft);color:var(--accent);border-radius:999px;padding:4px 12px;font-size:13px;font-weight:600}
section.chapter{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:30px 38px;margin-bottom:28px;box-shadow:var(--shadow)}
section.chapter h1{font-size:27px;margin:0 0 14px;color:var(--accent);padding-bottom:10px;border-bottom:2px solid var(--soft)}
h2{font-size:21px;margin:30px 0 10px;color:var(--accent-2)}h3{font-size:17px;margin:22px 0 6px}
.anchor{opacity:0;margin-left:8px;font-size:.7em;color:var(--muted);text-decoration:none}h1:hover .anchor,h2:hover .anchor{opacity:1}
p{margin:8px 0 12px}strong{color:var(--ink)}
ul,ol{margin:8px 0 16px;padding-left:24px}li{margin:5px 0}
ol.steps{list-style:none;counter-reset:s;padding-left:0}ol.steps li{counter-increment:s;position:relative;padding:8px 12px 8px 50px;background:var(--bg);border-radius:10px;margin:8px 0}
ol.steps li::before{content:counter(s);position:absolute;left:12px;top:8px;width:26px;height:26px;border-radius:50%;background:var(--accent);color:#fff;display:grid;place-items:center;font-size:13px;font-weight:700}
.note{display:flex;gap:14px;background:var(--note);border-left:4px solid var(--accent-2);border-radius:10px;padding:14px 18px;margin:16px 0}
.note p{margin:2px 0 0}.note-icon{flex:none;width:26px;height:26px;border-radius:50%;background:var(--accent-2);color:#fff;display:grid;place-items:center;font-weight:700;font-style:italic;font-family:Georgia,serif}
.table-wrap{overflow-x:auto;margin:14px 0 20px;border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;font-size:14.5px}th,td{text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top}
thead th{background:var(--accent);color:#fff;font-weight:600}tbody th{font-weight:600;white-space:nowrap}tbody tr:nth-child(even){background:var(--bg)}tbody tr:last-child>*{border-bottom:0}
figure{margin:20px 0 26px}figure .zoom{display:block;width:100%;padding:0;border:1px solid var(--line);border-radius:12px;overflow:hidden;cursor:zoom-in;background:#fff;box-shadow:var(--shadow)}
figure img{display:block;width:100%;height:auto}figcaption{margin-top:8px;font-size:13.5px;color:var(--muted);text-align:center}
figcaption span{display:inline-block;background:var(--soft);color:var(--accent);font-weight:700;border-radius:6px;padding:1px 8px;margin-right:8px}
#lightbox{position:fixed;inset:0;background:rgba(10,12,18,.88);display:none;align-items:center;justify-content:center;z-index:50;padding:30px;cursor:zoom-out}
#lightbox.open{display:flex}#lightbox img{max-width:100%;max-height:100%;border-radius:10px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
#lightbox .cap{position:absolute;bottom:14px;left:0;right:0;text-align:center;color:#e8e8e8;font-size:14px}
#top{position:fixed;right:22px;bottom:22px;width:44px;height:44px;border-radius:50%;border:0;background:var(--accent);color:#fff;font-size:20px;cursor:pointer;box-shadow:var(--shadow);opacity:0;pointer-events:none;transition:opacity .2s}
#top.show{opacity:1;pointer-events:auto}
.pager{display:flex;justify-content:space-between;gap:12px;margin-top:26px;padding-top:16px;border-top:1px solid var(--line)}
.pager a{flex:1;max-width:48%;text-decoration:none;border:1px solid var(--line);border-radius:12px;padding:10px 14px;color:var(--ink);background:var(--bg)}
.pager a small{display:block;color:var(--muted);font-size:12px}.pager a.next{text-align:right;margin-left:auto}.pager a:hover{border-color:var(--accent)}
@media (max-width:960px){header.top small{display:none}header.top h1{font-size:16px}.layout{grid-template-columns:1fr}#menu-toggle{display:inline-block}
nav.toc{position:fixed;left:0;top:61px;width:300px;z-index:30;transform:translateX(-105%);transition:transform .25s;box-shadow:var(--shadow)}
nav.toc.open{transform:none}main{padding:18px 16px 70px}section.chapter{padding:22px 18px}}
@media print{header.top,nav.toc,#top,.pager,#lightbox{display:none!important}.layout{display:block}section.chapter{box-shadow:none;border:0;page-break-before:always}body{background:#fff}}
${o.extraCss || ''}</style></head>
<body>
<header class="top"><button id="menu-toggle" aria-label="Contents">☰</button><div class="logo">AMC</div><h1>${esc(o.title)}</h1><small>${esc(o.meta)}</small></header>
<div class="layout">
<nav class="toc" id="toc" aria-label="Contents"><input class="search" id="toc-search" type="search" placeholder="Search topics…" aria-label="Search topics"><ul>${nav}</ul></nav>
<main id="content">
<div class="hero"><h2>${esc(o.heroTitle)}</h2><p>${esc(o.heroText)}</p>
<div class="chips">${o.chips.map((c) => `<span>${esc(c)}</span>`).join('')}</div></div>
${html}
</main></div>
<div id="lightbox" role="dialog" aria-modal="true"><img alt=""><div class="cap"></div></div>
<button id="top" aria-label="Back to top">↑</button>
<script>
(function(){
  const links=[...document.querySelectorAll('nav.toc a')];
  const byId=Object.fromEntries(links.map(a=>[a.dataset.target,a]));
  const targets=links.map(a=>document.getElementById(a.dataset.target)).filter(Boolean);
  function setActive(id){links.forEach(a=>a.classList.remove('active'));const a=byId[id];if(!a)return;a.classList.add('active');
    const chapter=a.closest('li.lvl1');if(chapter)chapter.querySelector(':scope>a').classList.add('active');
    const box=document.getElementById('toc');const r=a.getBoundingClientRect(),b=box.getBoundingClientRect();if(r.top<b.top||r.bottom>b.bottom)a.scrollIntoView({block:'nearest'});}
  function onScroll(){let current=targets[0]&&targets[0].id;for(const t of targets){if(t.getBoundingClientRect().top<120)current=t.id;else break;}setActive(current);
    document.getElementById('top').classList.toggle('show',window.scrollY>600);}
  window.addEventListener('scroll',onScroll,{passive:true});onScroll();
  // Chapter pager (previous / next).
  const chapters=[...document.querySelectorAll('section.chapter')];
  chapters.forEach((c,i)=>{const pg=document.createElement('div');pg.className='pager';
    const prev=chapters[i-1],next=chapters[i+1];
    const title=s=>s.querySelector('h1').firstChild.textContent;
    if(prev)pg.insertAdjacentHTML('beforeend','<a href="#'+prev.id+'"><small>Previous</small>'+title(prev)+'</a>');
    if(next)pg.insertAdjacentHTML('beforeend','<a class="next" href="#'+next.id+'"><small>Next</small>'+title(next)+'</a>');
    c.appendChild(pg);});
  // Search the table of contents.
  document.getElementById('toc-search').addEventListener('input',e=>{const q=e.target.value.trim().toLowerCase();
    document.querySelectorAll('nav.toc li.lvl1').forEach(li=>{let any=li.querySelector(':scope>a').textContent.toLowerCase().includes(q);
      li.querySelectorAll('li.lvl2').forEach(s=>{const hit=!q||s.textContent.toLowerCase().includes(q);s.style.display=hit?'':'none';any=any||(q&&hit);});
      li.style.display=(!q||any)?'':'none';});});
  // Mobile menu.
  const toc=document.getElementById('toc');document.getElementById('menu-toggle').onclick=()=>toc.classList.toggle('open');
  links.forEach(a=>a.addEventListener('click',()=>toc.classList.remove('open')));
  // Lightbox.
  const lb=document.getElementById('lightbox');
  document.querySelectorAll('figure .zoom').forEach(btn=>btn.addEventListener('click',()=>{const img=btn.querySelector('img');
    lb.querySelector('img').src=img.src;lb.querySelector('.cap').textContent=img.alt;lb.classList.add('open');}));
  lb.addEventListener('click',()=>lb.classList.remove('open'));
  document.addEventListener('keydown',e=>{if(e.key==='Escape')lb.classList.remove('open');});
  document.getElementById('top').onclick=()=>window.scrollTo({top:0});
})();
</script>
</body></html>`;
  return page;
}

module.exports = { render, esc };
