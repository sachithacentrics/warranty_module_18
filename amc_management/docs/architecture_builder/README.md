# AMC technical architecture – builder

Builds `amc_management/docs/AMC_Technical_Architecture.docx` (12 chapters, 10 diagrams, portrait
and landscape sections).

| File | Purpose |
|---|---|
| `diagrams.js` | Mermaid sources of the 10 diagrams (layers, components, ERD, state machines, sequences, scheduler, pricing, security) |
| `render.py` | renders them to `diagrams/<name>.png` (2× resolution) with headless Chrome and Mermaid 10.9.1 from cdn.jsdelivr.net (internet access needed) |
| `diagrams/*.png` | the rendered diagrams (committed, so a text-only rebuild needs no rendering) |
| `build_arch.js` | Word document (npm `docx`): text, tables, code blocks and the diagrams; the ERD and the two sequence diagrams are placed on landscape pages |

## Rebuild after a text change

```bash
cd "amc_management/docs"
npm install                                   # once
node architecture_builder/build_arch.js architecture_builder/diagrams AMC_Technical_Architecture.docx
powershell -File update_word_fields.ps1 -Path AMC_Technical_Architecture.docx   # table of contents
```

## After changing a diagram

```bash
cd "amc_management/docs/architecture_builder"
node -e "require('fs').writeFileSync('diagrams/diagrams.json', JSON.stringify(require('./diagrams.js'), null, 1))"
python render.py diagrams          # Odoo Python (websocket-client); prints PNG <name> <width> <height>
```

Then rebuild as above. Keep wide diagrams (sequence diagrams, ERD) in the landscape sections of
`build_arch.js`; prefer `flowchart TB` for long pipelines so they stay readable at page width.
`diagrams.json` and `diagrams.html` are build artefacts (ignored by Git).

Environment override: `CHROME` (Chrome path).
