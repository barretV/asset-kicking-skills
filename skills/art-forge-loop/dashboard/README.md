# Art Forge dashboard

A live web page for watching the forge: what is generating now, what is queued, the newest candidates with their scores, and a contact sheet per job against its bar. Hover any candidate and click **✓ good enough** to make it final: the loop stops working on that target, whatever the judge scored.

```bash
node <skill>/dashboard/server.mjs                 # run from the project root -> http://127.0.0.1:5390
node <skill>/dashboard/server.mjs --root ../my-game --port 5390 --comfy http://127.0.0.1:8188 --lock ../.gpu-lock
node <skill>/dashboard/server.mjs --read-only     # watch only, no good-enough button
```

Needs Node 18+ and nothing else (no npm install). Stop it with Ctrl+C.

## What it reads
- **Jobs:** `<root>/work/forge/<job>/` and every git worktree's `<root>/.claude/worktrees/<lane>/work/forge/<job>/` (also `.worktrees/`). Add more with `--forge <dir>` (repeatable). A job is a folder with `job.json` or `out/`.
  - `job.json` for `bar`, `max_rounds`, `mode`, targets, `init`/`ref`.
  - `picks.json` for the pick, its score, round, note and `final`.
  - `scores.json` (optional) for per-candidate scores: `{"<target>": {"r1-s1007": 8.9, ...}}`. Write it while judging if you want every candidate scored on the page, not only the pick.
  - `out/<target>/r<N>-s<seed>.png` candidates, `r<N>.done` markers, `_tmp*` while a gen is running (ignored after 8 minutes without changes, which means a killed gen).
  - The newest `*.log` in the job folder, for the last lines of output.
- **GPU lock:** the nearest `.gpu-lock` folder walking up from the root (or `--lock`, `$FORGE_GPU_LOCK`), owner file `<owner>|<time>|<job>`.
- **ComfyUI:** `/queue`, `/history` and `/view` on `--comfy` (default `http://127.0.0.1:8188`). Step progress is estimated from recent run times, because ComfyUI only streams progress to the client that queued the prompt. If websocket progress or preview frames do arrive (ComfyUI started with `--preview-method auto` and prompts queued without a `client_id`), they are shown live.

## Good enough
Hover a candidate and click **✓ good enough** (click **✓ undo** on an approved one to take it back). The dashboard writes one file, `<job>/approvals.json`:

```json
{"vespera|front": {"path": "work/forge/vespera/out/vespera__front/r2-s2007.png", "at": "2026-11-26T03:55:30Z", "by": "dashboard"}}
```

`forge_loop.py` reads it on every command: an approved target counts as final with that image as its pick, `gen` gives it no more rounds (even when you approve mid-round: it is checked before each target), `sheets` stops showing it to the judge, and `report` lists it as approved. The judge's own scores and notes in `picks.json` are left alone.

That file is the only thing it writes. It never touches the lock or ComfyUI, and only serves images inside a lane's forge folder. The write endpoint (`POST /api/approve`) only accepts requests from the page itself: it needs a custom header and a matching origin, so another website open in your browser cannot click it for you. It listens on 127.0.0.1 only unless you pass `--host`.

## The page
- **Now forging:** the job and target mid-generation (or the one the lock names), its round and progress, seed and denoise of the running ComfyUI prompt, the GPU lock holder, the latest output, and the tail of the gen log.
- **Queue:** ComfyUI's pending prompts, then each job with pieces left: to generate, to judge, final, target-rounds left.
- **Recent candidates:** the newest 48 across all jobs with target, round, seed, score (green at the bar, amber within 0.5, red below) and a PICK badge.
- **Jobs:** pick one for its contact sheet: one row per target with the ref, every candidate (newest first), status and the judge's note.

Click any image for full size (the `-hi` cutout when there is one). Updates arrive over server-sent events every 3 s.

Endpoints: `/api/state` (everything), `/api/job?id=<lane>/<job>` (one job with all candidates), `/api/stream` (SSE), `POST /api/approve` with `{"job": "<lane>/<job>", "target": "<key>", "file": "r2-s2007.png"}` (`"file": null` to undo).
