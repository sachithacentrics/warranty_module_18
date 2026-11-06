# AMC user manual – builders

One text source, two outputs:

| Output | Built by |
|---|---|
| `amc_management/docs/AMC_User_Manual.docx` (Word, with table of contents) | `build_manual.js` |
| `amc_management/manual/amc_user_manual.html` (shown in Odoo under *Configuration > Documents > User Manual*) | `build_manual_html.js` |

## Files

| File | Purpose |
|---|---|
| `manual_content.js` | **the manual text**: chapters, sections, steps, notes, tables and which screenshot goes where. Edit only this file for text changes. |
| `build_manual.js` | Word renderer (npm `docx`) |
| `build_manual_html.js` | HTML renderer (shared page `../html_shell.js`, also used by the technical architecture): self-contained page, screenshots embedded, sidebar contents with active section, topic search, chapter pager, image zoom, responsive / print layout |
| `screenshots/*.png` | the 37 screenshots (1440×900) referenced by name in `manual_content.js` |
| `shots.py` | captures the screenshots from the demo server with headless Chrome |
| `convert_webp.py` | PNG → WebP for the HTML page |
| `check_manual.py` | browser check of the menu and the HTML page on the demo server (screenshots m1…m6, console errors) |
| `../update_word_fields.ps1` | fills the Word table of contents / page numbers (needs Microsoft Word) |
| `../package.json` | npm dependency `docx` 9.5.1 (`npm install` once in `amc_management/docs`; `node_modules` is not committed) |

## Rebuild after a text change (no server needed)

```bash
cd "amc_management/docs"
npm install                                   # once
node manual_builder/build_manual.js manual_builder/screenshots AMC_User_Manual.docx
python manual_builder/convert_webp.py manual_builder/screenshots manual_builder/screenshots_web
node manual_builder/build_manual_html.js manual_builder/screenshots_web ../manual/amc_user_manual.html
powershell -File update_word_fields.ps1 -Path AMC_User_Manual.docx    # table of contents
```

`build_*` print `missing …` for a screenshot name that has no file; `python` = any Python with Pillow
(e.g. the Odoo Python).

## Retake the screenshots (after UI changes)

1. Build and start the demo database as described in `../recording/README.md` (steps 1–3: install,
   `demo_data_1.py`, `demo_data_2.py`, snapshot, server on port 8199).
2. `python manual_builder/shots.py http://localhost:8199 amc_demo admin admin manual_builder/screenshots`
   (Odoo Python: needs `websocket-client`). Each `SHOT name` line is one screenshot; `FAILED name`
   means a selector or record lookup must be adapted in `shots.py`.
3. Look at the new PNGs, then rebuild as above.
4. Optional: `python manual_builder/check_manual.py http://localhost:8199 <out_dir>` after upgrading
   `amc_management` on the demo database, to check the in-app page (expects no JS errors).

Environment overrides: `CHROME` (Chrome path), `AMC_DEMO_DB` (`check_manual.py`).
