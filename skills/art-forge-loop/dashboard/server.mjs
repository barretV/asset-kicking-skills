#!/usr/bin/env node
// Art Forge dashboard: a live view of art-forge-loop jobs, the GPU lock and ComfyUI, with a "good enough" button.
//
//   node <skill>/dashboard/server.mjs                  # project root = current folder, http://127.0.0.1:5390
//   node <skill>/dashboard/server.mjs --root ../my-game --port 5390 --comfy http://127.0.0.1:8188
//
// Scans <root>/work/forge/<job>/ and every git worktree <root>/.claude/worktrees/<lane>/work/forge/<job>/
// (plus any --forge <dir>). Finds the GPU lock by walking up from the root for a `.gpu-lock` folder
// (or --lock <dir>). Zero dependencies. Its one write is <job>/approvals.json when the owner marks a candidate
// good enough (POST /api/approve, same-origin only); --read-only turns that off. Never touches the lock or ComfyUI.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf('--' + name); return i >= 0 && args[i + 1] ? args[i + 1] : dflt; };
const optAll = (name) => args.flatMap((a, i) => (a === '--' + name && args[i + 1] ? [args[i + 1]] : []));
const ROOT = path.resolve(opt('root', process.env.FORGE_ROOT || process.cwd()));
const PORT = Number(opt('port', process.env.FORGE_DASH_PORT || 5390));
const HOST = opt('host', '127.0.0.1');
const COMFY = opt('comfy', process.env.COMFY_URL || 'http://127.0.0.1:8188').replace(/\/$/, '');
const EXTRA = optAll('forge').map((d) => path.resolve(d));
const READ_ONLY = args.includes('--read-only');
const TICK_MS = 3000;
const DEFAULTS = { bar: 9.5, max_rounds: 10, seeds: 2, mode: 'pixel' };
const IMG = /\.(png|jpe?g|webp|gif)$/i;

function findLock() {
  const given = opt('lock', process.env.FORGE_GPU_LOCK);
  if (given) return path.resolve(given);
  for (let d = ROOT, i = 0; i < 6; i++) {
    const p = path.join(d, '.gpu-lock');
    if (fs.existsSync(p) || i === 5) return p;
    const up = path.dirname(d);
    if (up === d) break;
    d = up;
  }
  return path.join(path.dirname(ROOT), '.gpu-lock');
}
const LOCK = findLock();

// ---------- small fs helpers (all read-only, all failure-tolerant) ----------
const readJSON = (p) => { try { return JSON.parse(fs.readFileSync(p, 'utf8').replace(/^﻿/, '')); } catch { return null; } };
const ls = (d) => { try { return fs.readdirSync(d, { withFileTypes: true }); } catch { return []; } };
const mtime = (p) => { try { return fs.statSync(p).mtimeMs; } catch { return 0; } };
const exists = (p) => { try { fs.accessSync(p); return true; } catch { return false; } };
const slug = (k) => k.replace(/[^A-Za-z0-9_.-]+/g, '__');
const rel = (from, p) => path.relative(from, p).split(path.sep).join('/');
function tail(p, bytes = 2048) {
  try {
    const fd = fs.openSync(p, 'r');
    const size = fs.fstatSync(fd).size;
    const n = Math.min(bytes, size);
    const buf = Buffer.alloc(n);
    fs.readSync(fd, buf, 0, n, size - n);
    fs.closeSync(fd);
    return buf.toString('utf8').split(/\r?\n/).map((l) => l.trim()).filter(Boolean).slice(-6);
  } catch { return []; }
}

// ---------- lanes: the project root plus each git worktree ----------
function lanes() {
  const out = [{ lane: 'main', root: ROOT, forge: path.join(ROOT, 'work', 'forge') }];
  for (const wt of ['.claude/worktrees', '.worktrees']) {
    for (const e of ls(path.join(ROOT, wt))) {
      if (!e.isDirectory()) continue;
      const root = path.join(ROOT, wt, e.name);
      const forge = path.join(root, 'work', 'forge');
      if (exists(forge)) out.push({ lane: e.name, root, forge });
    }
  }
  for (const f of EXTRA) out.push({ lane: path.basename(path.dirname(path.dirname(f))) || f, root: path.dirname(path.dirname(f)), forge: f });
  return out.filter((l) => exists(l.forge));
}

// ---------- one job, read like forge_loop.py reads it ----------
const CAND = /^r(\d+)-s(\d+)\.png$/;
function readJob(L, name) {
  const dir = path.join(L.forge, name);
  const job = readJSON(path.join(dir, 'job.json'));
  const outDir = path.join(dir, 'out');
  if (!job && !exists(outDir)) return null;
  const cfg = { ...DEFAULTS, ...(job?.mode === 'illustration' ? { seeds: 2 } : {}), ...(job || {}) };
  const picks = readJSON(path.join(dir, 'picks.json')) || {};
  const scores = readJSON(path.join(dir, 'scores.json')) || {};
  const approvals = readJSON(path.join(dir, 'approvals.json')) || {};
  const keys = Object.keys(cfg.targets || {});
  for (const e of ls(outDir)) if (e.isDirectory() && !keys.some((k) => slug(k) === e.name)) keys.push(e.name);
  const id = `${L.lane}/${name}`;
  const toUrl = (p) => (p ? `/img?lane=${encodeURIComponent(L.lane)}&p=${encodeURIComponent(p)}` : null);
  // paths in job.json / picks.json are relative to the lane's project root
  const laneRel = (p) => (p ? (path.isAbsolute(p) ? rel(L.root, p) : p.replace(/\\/g, '/')) : null);
  let newest = Math.max(mtime(path.join(dir, 'job.json')), mtime(path.join(dir, 'approvals.json')));
  const targets = [];
  for (const key of keys) {
    const t = (cfg.targets || {})[key] || {};
    const td = path.join(outDir, slug(key));
    const files = ls(td).map((e) => e.name);
    // forge_loop.py works in out/<target>/_tmp<i>/ during a gen; one left behind by a killed gen goes stale
    const tmpAge = (f) => Math.max(mtime(path.join(td, f)), ...['', 'raw', 'native', 'fixed'].map((s) => mtime(path.join(td, f, s))));
    const generating = files.some((f) => f.startsWith('_tmp') && Date.now() - tmpAge(f) < 8 * 60e3);
    const doneRounds = new Set(files.map((f) => /^r(\d+)\.done$/.exec(f)).filter(Boolean).map((m) => +m[1]));
    const ap = approvals[key]?.path ? approvals[key] : null;
    const pk = ap ? { ...(picks[key] || {}), path: ap.path, final: true, approved: true } : (picks[key] || null);
    const pickBase = pk ? [pk.path, pk.best].filter(Boolean).map((p) => path.basename(p).replace(/\.png$/, '')) : [];
    const sc = scores[key] || scores[slug(key)] || {};
    const cands = [];
    for (const f of files) {
      const m = CAND.exec(f);
      if (!m) continue;
      const p = path.join(td, f);
      const mt = mtime(p);
      newest = Math.max(newest, mt);
      const stem = f.slice(0, -4);
      let score = sc[stem] ?? sc[f] ?? null;
      const picked = pickBase.includes(stem);
      if (score == null && picked && pk && typeof pk.score === 'number' && path.basename(pk.path || '') === f) score = pk.score;
      cands.push({
        file: f, round: +m[1], seed: +m[2], score, picked, mtime: mt, approved: !!ap && path.basename(ap.path) === f,
        url: toUrl(rel(L.root, p)), hi: files.includes(stem + '-hi.png') ? toUrl(rel(L.root, path.join(td, stem + '-hi.png'))) : null,
      });
    }
    cands.sort((a, b) => a.round - b.round || a.seed - b.seed);
    const judged = pk ? Number(pk.round || 1) : 0;
    const maxR = Number(cfg.max_rounds);
    const lastRound = cands.length ? cands[cands.length - 1].round : 0;
    let status, needsRound = null;
    if (pk?.final) status = 'final';
    else if (generating) { status = 'generating'; needsRound = pk ? judged + 1 : 1; }
    else if (!pk) { if (doneRounds.has(1) || cands.length) status = 'judge'; else { status = 'queued'; needsRound = 1; } }
    else if (lastRound > judged) status = 'judge';
    else if (judged + 1 > maxR) status = 'capped';
    else if (doneRounds.has(judged + 1)) status = 'judge';
    else { status = 'queued'; needsRound = judged + 1; }
    targets.push({
      key, status, needsRound, generating, judged, lastRound, approved: ap ? { file: path.basename(ap.path), at: ap.at || null } : null,
      roundsLeft: status === 'final' || status === 'capped' ? 0 : Math.max(0, maxR - judged),
      pick: pk ? { score: pk.score ?? null, round: pk.round ?? null, note: pk.note || '', final: !!pk.final, file: pk.path ? path.basename(pk.path) : null } : null,
      ref: toUrl(laneRel(t.ref || t.init)), prompt: t.prompt || '', cands,
    });
  }
  // newest log line (gen-r1.log, gen.log, ...) for a human-readable "what's it doing"
  const logs = ls(dir).filter((e) => e.isFile() && /\.log$/i.test(e.name)).map((e) => ({ p: path.join(dir, e.name), m: mtime(path.join(dir, e.name)) })).sort((a, b) => b.m - a.m);
  if (logs[0]) newest = Math.max(newest, logs[0].m);
  const count = (s) => targets.filter((t) => t.status === s).length;
  const curRound = Math.max(0, ...targets.map((t) => t.needsRound || t.lastRound));
  const inRound = targets.filter((t) => (t.needsRound || 0) === curRound || (t.lastRound === curRound && t.status === 'judge'));
  return {
    id, lane: L.lane, name, dir, bar: Number(cfg.bar), maxRounds: Number(cfg.max_rounds), mode: cfg.mode, seeds: cfg.seeds,
    barText: cfg.bar_text || '', hasJob: !!job, newest,
    counts: { total: targets.length, final: count('final'), judge: count('judge'), queued: count('queued'), generating: count('generating'), capped: count('capped') },
    passing: targets.filter((t) => t.pick && t.pick.score >= cfg.bar).length,
    roundsLeft: targets.reduce((s, t) => s + t.roundsLeft, 0),
    round: { n: curRound, made: inRound.filter((t) => t.status === 'judge' && t.lastRound === curRound).length, of: inRound.length },
    log: logs[0] ? { file: path.basename(logs[0].p), mtime: logs[0].m, lines: tail(logs[0].p) } : null,
    targets,
  };
}

// ---------- the one write: <job>/approvals.json ----------
function approve(body) {
  const [lane, ...n] = String(body.job || '').split('/');
  const L = lanes().find((l) => l.lane === lane);
  if (!L || n.length !== 1 || !n[0] || n[0].startsWith('.')) throw new Error('no such job');
  const dir = path.join(L.forge, n[0]);
  const job = readJob(L, n[0]);
  const t = job && job.targets.find((x) => x.key === body.target);
  if (!t) throw new Error('no such target');
  const fp = path.join(dir, 'approvals.json');
  const all = readJSON(fp) || {};
  if (body.file == null) delete all[t.key];
  else {
    const f = String(body.file);
    if (!CAND.test(f) || !t.cands.some((c) => c.file === f)) throw new Error('no such candidate');
    all[t.key] = { path: rel(L.root, path.join(dir, 'out', slug(t.key), f)), at: new Date().toISOString(), by: 'dashboard' };
  }
  const tmp = fp + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(all, null, 1));
  fs.renameSync(tmp, fp);
  return all[t.key] || null;
}
function sameOrigin(req) {
  // a cross-site page cannot send a custom header without a CORS preflight, which this server never answers
  if (req.headers['x-forge'] !== '1') return false;
  const o = req.headers.origin;
  return !o || o === `http://${req.headers.host}`;
}
function readBody(req, max = 4096) {
  return new Promise((ok, bad) => {
    let b = '';
    req.on('data', (c) => { b += c; if (b.length > max) { bad(new Error('too big')); req.destroy(); } });
    req.on('end', () => { try { ok(JSON.parse(b || '{}')); } catch (e) { bad(e); } });
  });
}

function scanJobs() {
  const jobs = [];
  for (const L of lanes()) for (const e of ls(L.forge)) if (e.isDirectory()) { const j = readJob(L, e.name); if (j) jobs.push(j); }
  return jobs.sort((a, b) => b.newest - a.newest);
}

// ---------- GPU lock ----------
function readLock() {
  if (!exists(LOCK)) return { path: LOCK, held: false };
  let raw = '';
  const ownerFile = fs.statSync(LOCK).isDirectory() ? path.join(LOCK, 'owner') : LOCK;
  try { raw = fs.readFileSync(ownerFile, 'utf8').trim(); } catch {}
  const [owner = '?', time = '', ...rest] = raw.split('|');
  return { path: LOCK, held: true, raw, owner: owner.trim(), time: time.trim(), job: rest.join('|').trim(), since: mtime(ownerFile) || mtime(LOCK) };
}

// ---------- ComfyUI ----------
const comfy = { online: false, running: [], pending: [], recent: [], avgMs: null, firstSeen: new Map(), progress: null, preview: null, ws: false, error: null };
async function getJSON(url, ms = 2500) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), ms);
  try { const r = await fetch(url, { signal: ac.signal }); return r.ok ? await r.json() : null; } finally { clearTimeout(t); }
}
function describePrompt(item) {
  // queue item: [number, prompt_id, graph, extra, outputs]
  const [num, id, graph] = item;
  const d = { num, id, text: '', seed: null, denoise: null, prefix: '', steps: null, w: null, h: null };
  for (const n of Object.values(graph || {})) {
    const i = n.inputs || {};
    if (n.class_type === 'CLIPTextEncode' && typeof i.text === 'string' && i.text.length > d.text.length) d.text = i.text;
    if (/KSampler/.test(n.class_type || '')) { d.seed = i.seed ?? i.noise_seed ?? d.seed; d.denoise = i.denoise ?? d.denoise; d.steps = i.steps ?? d.steps; }
    if (/SaveImage/.test(n.class_type || '') && i.filename_prefix) d.prefix = i.filename_prefix;
    if (i.width && i.height) { d.w = i.width; d.h = i.height; }
  }
  // forge_loop.py: prefix forge/<target-slug>, seed = 1000*round + 17*i + 7
  const m = /^forge\/(.+)$/.exec(d.prefix);
  d.target = m ? m[1] : null;
  d.round = d.seed != null && d.seed >= 1000 ? Math.floor(d.seed / 1000) : null;
  return d;
}
async function pollComfy() {
  try {
    const q = await getJSON(COMFY + '/queue');
    if (!q) throw new Error('no /queue');
    comfy.online = true; comfy.error = null;
    comfy.running = (q.queue_running || []).map(describePrompt);
    comfy.pending = (q.queue_pending || []).map(describePrompt).sort((a, b) => a.num - b.num);
    const now = Date.now();
    for (const r of comfy.running) if (!comfy.firstSeen.has(r.id)) comfy.firstSeen.set(r.id, now);
    for (const id of [...comfy.firstSeen.keys()]) if (!comfy.running.some((r) => r.id === id) && now - comfy.firstSeen.get(id) > 600000) comfy.firstSeen.delete(id);
    const h = (await getJSON(COMFY + '/history?max_items=12')) || {};
    const items = Object.entries(h).map(([id, v]) => {
      const msgs = v.status?.messages || [];
      const ts = (k) => msgs.find((m) => m[0] === k)?.[1]?.timestamp;
      const start = ts('execution_start'), end = ts('execution_success') || ts('execution_error');
      const imgs = Object.values(v.outputs || {}).flatMap((o) => o.images || []);
      const d = describePrompt(v.prompt || []);
      return { ...d, id, start, end, ok: !!ts('execution_success'), images: imgs.map((im) => `/comfy/view?filename=${encodeURIComponent(im.filename)}&subfolder=${encodeURIComponent(im.subfolder || '')}&type=${encodeURIComponent(im.type || 'output')}`) };
    }).filter((x) => x.end).sort((a, b) => b.end - a.end);
    comfy.recent = items.slice(0, 8);
    const durs = items.filter((x) => x.ok && x.start).map((x) => x.end - x.start).slice(0, 8);
    comfy.avgMs = durs.length ? durs.reduce((a, b) => a + b, 0) / durs.length : null;
  } catch (e) {
    comfy.online = false; comfy.running = []; comfy.pending = []; comfy.error = String(e.message || e);
  }
}
// Websocket: ComfyUI only sends step progress / previews to the client that queued the prompt (or to all when
// it was queued without a client_id), so this is a bonus, not the source of truth.
function connectWS() {
  if (typeof WebSocket === 'undefined') return;
  let ws;
  try { ws = new WebSocket(COMFY.replace(/^http/, 'ws') + '/ws?clientId=forge-dash-' + process.pid); } catch { return setTimeout(connectWS, 10000); }
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => { comfy.ws = true; };
  ws.onclose = ws.onerror = () => { comfy.ws = false; try { ws.close(); } catch {} setTimeout(connectWS, 10000); };
  ws.onmessage = (ev) => {
    if (typeof ev.data === 'string') {
      try {
        const m = JSON.parse(ev.data);
        if (m.type === 'progress') { comfy.progress = { value: m.data.value, max: m.data.max, id: m.data.prompt_id, at: Date.now() }; broadcast('progress', comfy.progress); }
      } catch {}
    } else {
      const b = Buffer.from(ev.data);
      if (b.length > 8 && b.readUInt32BE(0) === 1) { // PREVIEW_IMAGE: [type u32][format u32][image bytes]
        comfy.preview = { mime: b.readUInt32BE(4) === 2 ? 'image/png' : 'image/jpeg', buf: b.subarray(8), at: Date.now() };
        broadcast('preview', { at: comfy.preview.at });
      }
    }
  };
}

// ---------- state ----------
function snapshot() {
  const jobs = scanJobs();
  const lock = readLock();
  const lockWords = (lock.job || '').toLowerCase().split(/[^a-z0-9_.-]+/);
  const running = comfy.running[0] || null;
  // active = a target is mid-generation, the lock names the job, or its gen log moved in the last 2 minutes
  const isActive = (j) => j.counts.generating > 0 || (lock.held && lockWords.includes(j.name.toLowerCase())) || (j.log && Date.now() - j.log.mtime < 120000);
  const owner = (lock.owner || '').toLowerCase();
  const rank = (j) => (j.counts.generating ? 8 : 0) + (lock.held && lockWords.includes(j.name.toLowerCase()) ? 4 : 0)
    + (owner && j.lane.toLowerCase().includes(owner) ? 2 : 0) + (j.log && Date.now() - j.log.mtime < 120000 ? 1 : 0);
  let active = jobs.filter(isActive).sort((a, b) => rank(b) - rank(a) || b.newest - a.newest);
  if (running?.target) {
    const byTarget = jobs.filter((j) => j.targets.some((t) => slug(t.key) === running.target && (t.generating || t.status === 'queued')));
    if (byTarget.length) active = [...new Set([...byTarget, ...active])];
  }
  const nowJob = active[0] || null;
  const nowTarget = nowJob ? (nowJob.targets.find((t) => running?.target && slug(t.key) === running.target) || nowJob.targets.find((t) => t.generating)) : null;
  let progress = null;
  if (running) {
    const ws = comfy.progress && comfy.progress.id === running.id && Date.now() - comfy.progress.at < 30000 ? comfy.progress : null;
    if (ws) progress = { frac: ws.value / ws.max, label: `step ${ws.value}/${ws.max}`, exact: true };
    else if (comfy.avgMs && comfy.firstSeen.has(running.id)) {
      const el = Date.now() - comfy.firstSeen.get(running.id);
      progress = { frac: Math.min(0.97, el / comfy.avgMs), label: `${Math.round(el / 1000)}s of ~${Math.round(comfy.avgMs / 1000)}s`, exact: false };
    }
  }
  const recent = jobs.flatMap((j) => j.targets.flatMap((t) => t.cands.map((c) => ({ ...c, job: j.id, jobName: j.name, lane: j.lane, target: t.key, bar: j.bar, final: t.status === 'final' }))))
    .sort((a, b) => b.mtime - a.mtime).slice(0, 48);
  const strip = (j) => { const { targets, dir, ...rest } = j; return rest; };
  return {
    at: Date.now(), root: ROOT, lanes: lanes().map((l) => l.lane), readOnly: READ_ONLY,
    lock,
    now: nowJob ? { job: strip(nowJob), target: nowTarget ? { key: nowTarget.key, round: nowTarget.needsRound || running?.round, status: nowTarget.status, ref: nowTarget.ref, done: nowTarget.cands.filter((c) => c.round === (nowTarget.needsRound || running?.round)).length } : null } : null,
    comfy: { url: COMFY, online: comfy.online, error: comfy.error, ws: comfy.ws, running, pending: comfy.pending, progress, recent: comfy.recent.slice(0, 4), preview: comfy.preview && Date.now() - comfy.preview.at < 60000 ? `/comfy/preview?t=${comfy.preview.at}` : null },
    queue: active.concat(jobs.filter((j) => !active.includes(j) && (j.counts.queued || j.counts.judge) && Date.now() - j.newest < 6 * 3600e3)).map(strip),
    activeIds: active.map((j) => j.id),
    jobs: jobs.map(strip),
    recent,
  };
}

// ---------- http ----------
const clients = new Set();
function broadcast(event, data) { const s = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`; for (const c of clients) c.write(s); }
let last = '';
async function tick() {
  await pollComfy();
  if (!clients.size) return;
  const s = snapshot();
  const sig = JSON.stringify({ ...s, at: 0, comfy: { ...s.comfy, progress: null } }); // progress ticks ride on 'ping'
  if (sig !== last) { last = sig; broadcast('state', s); }
  else broadcast('ping', { at: s.at, progress: s.comfy.progress });
}

const MIME = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif', '.html': 'text/html; charset=utf-8' };
function send(res, code, body, type = 'text/plain; charset=utf-8', extra = {}) { res.writeHead(code, { 'content-type': type, 'cache-control': 'no-store', ...extra }); res.end(body); }

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x');
  if (req.method === 'POST' && u.pathname === '/api/approve') {
    if (READ_ONLY) return send(res, 403, 'started with --read-only');
    if (!sameOrigin(req)) return send(res, 403, 'same-origin requests only');
    try {
      const r = approve(await readBody(req));
      tick();
      return send(res, 200, JSON.stringify({ ok: true, approved: r }), 'application/json');
    } catch (e) { return send(res, 400, String(e.message || e)); }
  }
  if (req.method !== 'GET') return send(res, 405, 'GET only (and POST /api/approve)');
  try {
    if (u.pathname === '/' || u.pathname === '/index.html') return send(res, 200, fs.readFileSync(path.join(HERE, 'index.html')), MIME['.html']);
    if (u.pathname === '/api/state') return send(res, 200, JSON.stringify(snapshot()), 'application/json');
    if (u.pathname === '/api/job') {
      const id = u.searchParams.get('id') || '';
      const [lane, ...n] = id.split('/');
      const L = lanes().find((l) => l.lane === lane);
      const j = L && readJob(L, n.join('/'));
      if (!j || n.length !== 1) return send(res, 404, 'no such job');
      delete j.dir;
      return send(res, 200, JSON.stringify(j), 'application/json');
    }
    if (u.pathname === '/api/stream') {
      res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store', connection: 'keep-alive' });
      clients.add(res);
      req.on('close', () => clients.delete(res));
      const s = snapshot();
      res.write(`event: state\ndata: ${JSON.stringify(s)}\n\n`);
      return;
    }
    if (u.pathname === '/img') {
      const L = lanes().find((l) => l.lane === u.searchParams.get('lane'));
      const p = L && path.resolve(L.root, u.searchParams.get('p') || '');
      // only images inside that lane's forge folder
      if (!L || !IMG.test(p) || !(p + path.sep).startsWith(path.resolve(L.forge) + path.sep) || !exists(p)) return send(res, 404, 'not found');
      return send(res, 200, fs.readFileSync(p), MIME[path.extname(p).toLowerCase()] || 'application/octet-stream', { 'cache-control': 'max-age=5' });
    }
    if (u.pathname === '/comfy/view') {
      const qs = new URLSearchParams({ filename: u.searchParams.get('filename') || '', subfolder: u.searchParams.get('subfolder') || '', type: u.searchParams.get('type') || 'output' });
      const r = await fetch(`${COMFY}/view?${qs}`);
      if (!r.ok) return send(res, r.status, 'comfy view failed');
      return send(res, 200, Buffer.from(await r.arrayBuffer()), r.headers.get('content-type') || 'image/png', { 'cache-control': 'max-age=300' });
    }
    if (u.pathname === '/comfy/preview') {
      if (!comfy.preview) return send(res, 404, 'no preview');
      return send(res, 200, comfy.preview.buf, comfy.preview.mime);
    }
    send(res, 404, 'not found');
  } catch (e) { send(res, 500, String(e.stack || e)); }
});

server.on('error', (e) => { console.error(e.code === 'EADDRINUSE' ? `port ${PORT} is busy: pass --port <n>` : e); process.exit(1); });
server.listen(PORT, HOST, () => {
  console.log(`Art Forge dashboard  http://${HOST}:${PORT}`);
  console.log(`  root  ${ROOT}\n  lanes ${lanes().map((l) => l.lane).join(', ')}\n  lock  ${LOCK}\n  comfy ${COMFY}`);
});
connectWS();
setInterval(tick, TICK_MS);
pollComfy();
