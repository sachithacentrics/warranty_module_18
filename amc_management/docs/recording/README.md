# AMC process recording – scripts

These scripts produce the screen recording shown in Odoo under
**AMC Management > Configuration > Documents > Process Recording (Video)**:

| Output (served by `controllers/amc_management.py`) | Produced by |
|---|---|
| `amc_management/manual/amc_process.mp4` | `record.py` → `encode.py` |
| `amc_management/manual/amc_process_poster.jpg` | `encode.py` |
| `amc_management/manual/amc_process_video.html` (player page with chapters) | `build_player.py` |

The recording drives the real Odoo UI of a demonstration database in headless Chrome (real typing,
clicks, wizards, menus) and records it with the Chrome DevTools screencast. Captions, an animated
cursor and click highlights are injected into the page, so they are part of the video. Steps that
need other users (case approval by the Service Manager, the technician's timer / signature /
Complete Visit) are executed server-side by `server_steps.py`; the video shows their result.

## Files

| File | Purpose |
|---|---|
| `record.py` | the recording itself: all steps, captions and chapter titles |
| `server_steps.py` | server-side steps run as other users (`approve`, `plan_job`, `complete_job`) |
| `encode.py` | frames → MP4 (H.264, 1440×900, 25 fps), still gaps capped at 3 s, chapter times remapped |
| `build_player.py` | player page (chapter list, chapter progress bar, speed, keyboard shortcuts) |
| `run_with_conf.py` | runs a script against a database with only the given `odoo.conf` |
| `warm_assets.py` | builds the web asset bundles of a restored database before the take (otherwise the first page load is recorded as a blank screen and the first clicks miss) |
| `demo_data_1.py`, `demo_data_2.py` | demonstration data (plans, formulas, contracts in every state, service request → confirmed job, warranty card) |
| `restore_demo.sh` | restores the demo database and filestore from the snapshot before a new take |

## Requirements

* The project's Odoo 18 (Enterprise) with all warranty addons and the three AMC modules.
* Google Chrome (`CHROME` overrides the path).
* The Odoo Python (has `websocket-client`) for `record.py`, `build_player.py`, `run_with_conf.py`.
* For `encode.py` only: a separate virtual environment with `imageio-ffmpeg==0.5.1` (bundles an
  ffmpeg binary with libx264):
  `python -m venv venv_video && venv_video\Scripts\python -m pip install imageio-ffmpeg==0.5.1`.
  Pass Windows-style paths (`C:\...`) to `encode.py`: ffmpeg's concat list does not accept
  `C:/...` paths from Git Bash.

Environment overrides: `ODOO_ROOT` (default `E:\odoo-env\odoo-v18-03022026`), `ODOO_PY`,
`ODOO_CONF`, `CHROME`, `AMC_DEMO_DB` (default `amc_demo`); `restore_demo.sh`: `PGBIN`, `FILESTORE`,
`PGUSER`, `PGPASSWORD`, `DB`, `BASE`.

## Procedure (Git Bash, from `E:\odoo-env\odoo-v18-03022026\server`)

```bash
REC="../project/Warranty Module/warranty_module_18/amc_management/docs/recording"
MANUAL="../project/Warranty Module/warranty_module_18/amc_management/manual"
WORK=/tmp/amc_recording            # any empty working folder (frames, chapters)

# 1. Demo database (once): all addons with Odoo demo data, then the AMC demo data
MSYS_NO_PATHCONV=1 ../python/python.exe odoo-bin -c odoo.conf -d amc_demo -i warranty_meta_dependencies --stop-after-init --no-http
../python/python.exe "$REC/run_with_conf.py" odoo.conf amc_demo "$REC/demo_data_1.py"
../python/python.exe "$REC/run_with_conf.py" odoo.conf amc_demo "$REC/demo_data_2.py"

# 2. Snapshot (once) - the recording changes data; restore_demo.sh returns to this state
PGPASSWORD=odoo18 /e/other-installations/PostgreSQL/bin/createdb -h localhost -U odoo18 -T amc_demo amc_demo_base
cp -r ../sessions/filestore/amc_demo ../sessions/filestore/amc_demo_base

# 3. Demo server (separate terminal; no cron so nothing changes during the take)
MSYS_NO_PATHCONV=1 ../python/python.exe odoo-bin -c odoo.conf -d amc_demo --db-filter=^amc_demo$ \
  --http-port=8199 --gevent-port=8299 --max-cron-threads=0

# 4. Warm the asset bundles (once per restore), then record (about 7 minutes; prints
#    CONTRACT / CASE / JOB ids and FRAMES / DURATION; no NOT FOUND / JS EXCEPTION lines expected)
../python/python.exe "$REC/warm_assets.py" http://localhost:8199 amc_demo admin admin
../python/python.exe "$REC/record.py" http://localhost:8199 "$WORK"

# 5. Encode and build the player page (writes directly into amc_management/manual/)
venv_video/Scripts/python.exe "$REC/encode.py" "$WORK" "$MANUAL/amc_process.mp4" "$WORK/amc_process_chapters.json" "$MANUAL/amc_process_poster.jpg"
../python/python.exe "$REC/build_player.py" "$WORK/amc_process_chapters.json" "$MANUAL/amc_process_video.html"

# 6. Before another take: stop the demo server, then
bash "$REC/restore_demo.sh"
```

Check the result before committing: open a few frames in `$WORK/frames/`, extract frames at the
chapter times printed by `encode.py`, and play the page `/amc_management/process_video` (AMC user).

## Chapters

Introduction, Sign in, **1. Configuration – AMC settings** (every setting of *Configuration >
Settings*, one caption each: `SETTINGS` in `record.py`; a setting that is not visible, such as
Default Pricelist without Sales pricelists, is explained via `HIDDEN`; then AMC Enabled is switched
off and saved – the AMC app disappears from the home screen – and switched on again), 1. AMC plans and pricing,
2. Create and price a contract, 3. Quotation and activation, 4. Billing, 5. AMC visits and service
request, 6. Helpdesk case and Service Job, 7. Field Service completion, 8. Hold, expiry and renewal,
9. Warranty to AMC, 10. Reports and documentation.

## Changing the recording

* Each step in `record.py` is a short block: `caption(step, text, chapter=…)` shows the banner (a
  `chapter=` starts a new chapter of the player), `point(selector, text)` moves the cursor,
  highlights and clicks, `type_into(selector, text, enter=True)` types into a field (Enter selects
  the first Many2one suggestion), `goto(path)` opens a URL, `idle(seconds)` holds the screen.
* `point()` retries for up to 10 seconds until the element is visible, so slow screens do not break
  the take; `NOT FOUND <selector>` in the output means a selector must be adapted to a changed view.
* Records created during the take are looked up by RPC (`rpc(...)`), never by URL.
* The settings are saved during the take: the demo company needs a Default Warranty Duration
  and Unit (`demo_data_1.py`), otherwise the warranty settings block every Settings save.
* Keep a take below about 7 minutes; still screens longer than 3 s are shortened by `encode.py`.
