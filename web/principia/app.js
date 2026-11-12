// Legio Principia — the second skin of the camp dashboard.
// Read-only: it polls GET /api/camp and reads job scrolls through
// GET /api/job and /api/job/file. It never writes, never runs an agent,
// and every action it offers is a command copied for you to run yourself.
'use strict';

const POLL_MS = 2500;
const STAGES = ['intake', 'spec', 'build', 'gate', 'review', 'approve', 'merged'];
const NUM = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII'];
const ROLE_NAMES = {
  tesserarius: 'Tesserarius', signifer: 'Signifer', fabri: 'Fabri', probator: 'Probator',
  medicus: 'Medicus', mensor: 'Mensor', librator: 'Librator', 'primus-pilus': 'Primus Pilus',
};
const STAGE_ROLE = { intake: 'tesserarius', spec: 'signifer', build: 'fabri', approve: 'primus-pilus' };
const VERB = {
  tesserarius: 'reading the issue', signifer: 'writing the spec', fabri: 'building',
  probator: 'reviewing', medicus: 'reviewing security', mensor: 'reviewing the UI',
  librator: 'checking the layout', 'primus-pilus': 'deciding',
};
const TENTS = ['tent', 'tent-alt-1', 'tent-alt-2'];

const asset = (name) => `../assets/${name}.webp`;
const $ = (sel) => document.querySelector(sel);
const enc = encodeURIComponent;
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}
function roman(n) {
  const table = [[10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']];
  let out = '';
  let left = n;
  for (const [v, s] of table) while (left >= v) { out += s; left -= v; }
  return out || String(n);
}
function mmss(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  if (m >= 60) return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}
const clock = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

// ---------------------------------------------------------------- settings

const prefs = {
  line: 'aqueduct', density: 'comfortable', lang: 'latin',
  motion: true, desk: true, cost: true, done: true, detailH: null, storyW: null, lfold: false, rfold: false,
};
try { Object.assign(prefs, JSON.parse(localStorage.getItem('principia-prefs') || '{}')); } catch (_) { /* private mode */ }
function savePrefs() { try { localStorage.setItem('principia-prefs', JSON.stringify(prefs)); } catch (_) { /* ignore */ } }
function applyPrefs() {
  const b = document.body.classList;
  b.toggle('compact', prefs.density === 'compact');
  b.toggle('english', prefs.lang === 'english');
  b.toggle('nomotion', !prefs.motion);
  b.toggle('nodesk', !prefs.desk);
  b.toggle('nocost', !prefs.cost);
  b.toggle('lfold', !!prefs.lfold);
  b.toggle('rfold', !!prefs.rfold);
  document.querySelectorAll('[data-fold="left"]').forEach((el) => {
    el.setAttribute('aria-expanded', String(!prefs.lfold));
    el.title = prefs.lfold ? 'Show projects ( [ )' : 'Hide projects ( [ )';
    el.setAttribute('aria-label', prefs.lfold ? 'Show projects' : 'Hide projects');
  });
  document.querySelectorAll('[data-fold="right"]').forEach((el) => el.setAttribute('aria-expanded', String(!prefs.rfold)));
}
function useSkin(skin) {
  try { localStorage.setItem('legio-skin', skin); } catch (_) { /* ignore */ }
  location.href = skin === 'camp' ? '../?skin=camp' : './';
}

// ---------------------------------------------------------------- state

const state = {
  data: null, fetchedAt: 0, error: null, fingerprint: '',
  project: null, job: null, view: 'via', file: null, q: '', big: false,
  history: new Map(), files: new Map(), queue: Promise.resolve(),
  seen: null, msgs: [], unread: 0,
};

const projects = () => state.data?.projects || [];
const project = (name) => projects().find((p) => p.name === name);
const isTerminal = (j) => !!j.terminal || j.stage === 'merged' || j.stage === 'rejected';
const isWaiting = (j) => !!j.waiting || j.stage === 'needs-info' || j.stage === 'needs-human';
const shortId = (j) => (String(j.id).match(/^\d+/) || [j.id])[0];
const keyOf = (p, j) => `${p.name}/${j.id}`;
const livesOf = (p, j) => (p.lives || []).filter((l) => l.job === j.id);
const liveOf = (p, j) => livesOf(p, j).find((l) => !l.stale) || null;
const roleName = (role) => ROLE_NAMES[role] || String(role).replace(/(^|-)(\w)/g, (_, a, b) => (a ? ' ' : '') + b.toUpperCase());
const approved = (j) => /^approved/i.test(j.human_reason || '');
const sigOf = (j) => `${j.stage}|${j.round}|${j.gate}|${JSON.stringify(j.reviews || {})}`;

function mg(role, cls = '') {
  const title = esc(roleName(role));
  if (ROLE_NAMES[role]) return `<span class="mg ${cls}" title="${title}"><img src="${asset(`head-${role}`)}" alt="${title}"></span>`;
  return `<span class="mg ${cls}" title="${title}">${esc(roleName(role).slice(0, 2))}</span>`;
}

// where on the road a job stands (index into STAGES)
function pos(p, j) {
  const i = STAGES.indexOf(j.stage);
  if (i >= 0) return i;
  if (j.stage === 'merging') return 5;
  if (j.stage === 'needs-info') return 0;
  if (j.stage === 'needs-human') {
    const h = state.history.get(keyOf(p, j));
    if (approved(j) || h?.decision) return 5;
    if (Object.keys(j.reviews || {}).length && j.gate === 'PASS') return 4;
    if (j.gate) return 3;
    return j.round > 0 ? 2 : 0;
  }
  if (j.stage === 'rejected') return j.round > 0 ? 2 : 0;
  return 0;
}

function gateFailed(p, j) {
  const h = state.history.get(keyOf(p, j));
  if (j.gate === 'FAIL') return true;
  return !!h && Object.entries(h.rounds).some(([n, r]) => Number(n) < j.round && r.gate === 'FAIL');
}

// ---------------------------------------------------------------- job history (read from the job's own files)

function header(text) {
  const out = {};
  for (const line of String(text).split('\n')) {
    if (!line.trim()) break;
    const m = line.match(/^([A-Za-z-]+):\s*(.*)$/);
    if (m) out[m[1].toUpperCase()] = m[2].trim();
  }
  return out;
}
const firstLine = (text) => String(text).split('\n', 1)[0].trim();

async function getJSON(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

async function readFile(p, j, path) {
  const key = `${keyOf(p, j)}|${sigOf(j)}|${path}`;
  if (state.files.has(key)) return state.files.get(key);
  const data = await getJSON(`/api/job/file?project=${enc(p.name)}&job=${enc(j.id)}&path=${enc(path)}`);
  state.files.set(key, data);
  return data;
}

function enqueueHistory(p, j) {
  const key = keyOf(p, j);
  const sig = sigOf(j);
  const have = state.history.get(key);
  if (have && (have.sig === sig || have.pending === sig)) return;
  state.history.set(key, { ...(have || { files: [], rounds: {} }), pending: sig });
  state.queue = state.queue.then(() => loadHistory(p, j, sig)).catch(() => {});
}

async function loadHistory(p, j, sig) {
  const key = keyOf(p, j);
  const h = { sig, files: [], rounds: {}, intake: null, decision: null, feedback: [], rejected: false };
  try {
    const listing = await getJSON(`/api/job?project=${enc(p.name)}&job=${enc(j.id)}`);
    h.files = (listing.files || []).map((f) => f.path);
    const wanted = h.files.filter((f) => f === 'intake.md' || f === 'decision.md'
      || /^round-\d+\/(checks|review-[\w-]+)\.md$/.test(f));
    const texts = await Promise.all(wanted.map((f) => readFile(p, j, f).then((d) => [f, d.text]).catch(() => [f, ''])));
    for (const [f, text] of texts) {
      if (f === 'intake.md') {
        const hd = header(text);
        h.intake = { decision: hd.DECISION || '', risk: hd.RISK || '', surfaces: hd.SURFACES || '' };
      } else if (f === 'decision.md') {
        h.decision = firstLine(text);
      } else {
        const m = f.match(/^round-(\d+)\/(checks|review-([\w-]+))\.md$/);
        const r = (h.rounds[m[1]] ||= { gate: null, reviews: {} });
        if (m[2] === 'checks') r.gate = header(text).GATE || null;
        else {
          const v = firstLine(text).match(/^VERDICT:\s*(PASS|CHANGES)$/);
          r.reviews[m[3]] = v ? v[1] : 'invalid';
        }
      }
    }
    h.feedback = h.files.filter((f) => /^feedback-\d+\.md$/.test(f));
    h.rejected = h.files.includes('rejection.md');
  } catch (_) {
    // no scrolls yet (or the demo has none for this job): the story falls back to the job fields
  }
  state.history.set(key, h);
  if (state.project === p.name) {
    renderBoard();
    if (state.job === j.id) renderDetail();
  }
}

// ---------------------------------------------------------------- polling + Legatus dispatches

function fingerprint(data) {
  return JSON.stringify(data, (k, v) => (k === 'generated_at' || k === 'age_seconds' ? undefined : v));
}

function say(html) {
  state.msgs.push({ at: clock(), html });
  if (state.msgs.length > 40) state.msgs.shift();
  if (prefs.rfold && $('#lgwin').hidden) state.unread += 1;
  renderMsgs();
}

function digest() {
  const waiting = [];
  let working = 0;
  for (const p of projects()) {
    for (const j of p.jobs || []) if (isWaiting(j)) waiting.push(`<li><b>${esc(p.name)} ${esc(shortId(j))}</b> ${esc(j.title)}: ${esc(j.human_reason || j.stage)}</li>`);
    working += (p.lives || []).filter((l) => !l.stale).length;
  }
  const broken = projects().filter((p) => !p.ok).map((p) => `<b>${esc(p.name)}</b>`);
  const hour = new Date().getHours();
  const hello = hour < 12 ? 'Good morning.' : hour < 18 ? 'Good afternoon.' : 'Good evening.';
  let html = `${hello} `;
  html += waiting.length ? `${waiting.length === 1 ? 'One thing needs' : `${waiting.length} things need`} you:<ul>${waiting.join('')}</ul>` : 'Nothing needs you right now. ';
  html += working ? `${working === 1 ? 'One agent is' : `${working} agents are`} at work.` : 'No agent is working.';
  if (broken.length) html += ` I can't read ${broken.join(', ')}.`;
  say(html);
}

function noticeChanges() {
  const now = new Map();
  for (const p of projects()) {
    for (const j of p.jobs || []) now.set(keyOf(p, j), { p, j });
    for (const l of p.lives || []) now.set(`live:${p.name}/${l.job}/${(l.roles || []).join(',')}`, { p, l });
  }
  if (!state.seen) { state.seen = now; digest(); return; }
  for (const [key, cur] of now) {
    const before = state.seen.get(key);
    if (cur.j) {
      const name = `<b>${esc(cur.p.name)} ${esc(shortId(cur.j))}</b> ${esc(cur.j.title)}`;
      if (!before) say(`New job ${name}.`);
      else if (before.j.stage !== cur.j.stage) {
        const verb = cur.j.stage === 'merged' ? 'is merged.'
          : cur.j.stage === 'needs-human' ? `needs you: ${esc(cur.j.human_reason || 'a human')}.`
            : cur.j.stage === 'needs-info' ? 'needs more information from the author.'
              : `moved from ${esc(before.j.stage)} to ${esc(cur.j.stage)}.`;
        say(`${name} ${verb}`);
      }
    } else if (!before && cur.l) {
      const j = (cur.p.jobs || []).find((x) => x.id === cur.l.job);
      const who = (cur.l.roles || []).map(roleName).join(' and ') || 'An agent';
      say(`${esc(who)} started on <b>${esc(cur.p.name)} ${esc(j ? shortId(j) : cur.l.job)}</b>${j ? ` ${esc(j.title)}` : ''}.`);
    }
  }
  state.seen = now;
}

async function poll() {
  try {
    const data = await getJSON('/api/camp');
    state.error = null;
    state.fetchedAt = Date.now();
    const fp = fingerprint(data);
    state.data = data;
    if (fp !== state.fingerprint) {
      state.fingerprint = fp;
      noticeChanges();
      route();
      renderAll();
    } else {
      renderTimersOnly();
    }
  } catch (err) {
    if (!state.error) {
      state.error = String(err.message || err);
      if (!state.data) $('#board').innerHTML = `<div class="broken"><b>Can't reach the camp server.</b> Is <span class="mono">python3 web/serve.py</span> still running?</div>`;
      say('I lost the connection to the camp server. I keep trying.');
    }
  } finally {
    setTimeout(poll, POLL_MS);
  }
}

// ---------------------------------------------------------------- routing

function route() {
  const m = location.hash.match(/^#\/legion\/([^/]+)(?:\/job\/([^/]+))?/);
  const all = projects();
  let name = m ? decodeURIComponent(m[1]) : state.project;
  if (!all.some((p) => p.name === name)) {
    const pick = all.find((p) => (p.jobs || []).some(isWaiting)) || all.find((p) => p.ok) || all[0];
    name = pick ? pick.name : null;
  }
  if (name !== state.project) { state.file = null; state.job = null; }
  state.project = name;
  const p = project(name);
  let job = m && m[2] ? decodeURIComponent(m[2]) : state.job;
  if (p && !(p.jobs || []).some((j) => j.id === job)) {
    const open = orderedOpen(p);
    job = (open[0] || (p.jobs || [])[0] || {}).id || null;
  }
  if (job !== state.job) state.file = null;
  state.job = p ? job : null;
}

function go(name, job) {
  const target = `#/legion/${enc(name)}${job ? `/job/${enc(job)}` : ''}`;
  if (location.hash === target) { route(); renderAll(); } else location.hash = target;
}

// ---------------------------------------------------------------- rendering: chrome + left

function renderStats() {
  const all = projects();
  const waiting = all.reduce((n, p) => n + (p.jobs || []).filter(isWaiting).length, 0);
  const working = all.reduce((n, p) => n + (p.lives || []).filter((l) => !l.stale).length, 0);
  const cost = all.reduce((n, p) => n + (p.jobs || []).reduce((m, j) => m + (Number(j.cost_usd) || 0), 0), 0);
  $('#stats').innerHTML = `${state.data?.demo ? '<span class="demo">demo data</span>' : ''}
    <span><i class="dot" style="background:var(--blue)"></i><b>${working}</b> at work</span>
    <span><img src="${asset('icon-bell')}" alt=""><b>${waiting}</b> need you</span>
    <span class="cost" title="recorded job cost (USD)"><img src="${asset('icon-coin')}" alt=""><b>$${cost.toFixed(2)}</b> spent</span>`;
  document.title = waiting ? `(${waiting}) Legio Principia` : 'Legio Principia';
}

function counts(p) {
  const jobs = p.jobs || [];
  return {
    active: jobs.filter((j) => !isTerminal(j) && !isWaiting(j)).length,
    waiting: jobs.filter(isWaiting).length,
    done: jobs.filter(isTerminal).length,
    live: (p.lives || []).filter((l) => !l.stale).length,
  };
}

function renderLeft() {
  const all = projects();
  $('#ncastra').textContent = `${all.length} stationed`;
  $('#projects').innerHTML = all.map((p, i) => {
    const c = counts(p);
    const on = p.name === state.project;
    const tent = !p.ok ? 'tent-warped' : on ? 'tent-open' : TENTS[i % TENTS.length];
    const badge = !p.ok ? '<span class="badge b-red" title="cannot read">!</span>'
      : c.waiting ? `<span class="badge b-ochre" title="needs you">${c.waiting}</span>`
        : c.live ? `<span class="badge b-blue" title="at work">${c.live}</span>`
          : '<span class="badge b-mute">0</span>';
    const total = Math.max(1, c.active + c.waiting + c.done);
    const bar = !p.ok ? '<div class="pbar"><i style="flex:1;background:var(--red)"></i></div>'
      : `<div class="pbar"><i style="flex:${c.waiting / total};background:var(--ochre)"></i><i style="flex:${c.active / total};background:var(--blue)"></i><i style="flex:${c.done / total};background:var(--ink-3)"></i></div>`;
    return `<a class="proj ${on ? 'on' : ''}" href="#/legion/${enc(p.name)}" title="${esc(p.name)}" ${on ? 'aria-current="page"' : ''}>
      <span class="tentic"><img src="${asset(tent)}" alt=""><b>${roman(i + 1)}</b></span>
      <span style="min-width:0"><div class="pname">${esc(p.name)}</div>
        <div class="psub ${p.ok ? '' : 'err'}">${p.ok ? `${c.active} active · ${c.waiting} waiting · ${c.done} done` : 'cannot read'}</div>${bar}</span>
      ${badge}</a>`;
  }).join('') || '<div class="note" style="padding:0 6px">No centuria found. Station one with <span class="mono">legio add &lt;path&gt;</span>.</div>';
  const unch = state.data?.uncharted || [];
  $('#unch-wrap').hidden = !unch.length;
  $('#uncharted').innerHTML = unch.map((u) => `<button class="unch" type="button" data-copy="${esc(`legio add ${u.path}`)}" title="Copy the command that stations a centuria here"><span>${esc(u.name)}</span><span>station +</span></button>`).join('');
  $('#foot').innerHTML = `read-only · refreshes every ${POLL_MS / 1000} s${state.data?.demo ? ' · demo data' : ''}`;
}

// ---------------------------------------------------------------- rendering: middle

function orderedOpen(p) {
  const rank = (j) => (isWaiting(j) ? 0 : liveOf(p, j) ? 1 : 2);
  return (p.jobs || []).filter((j) => !isTerminal(j))
    .sort((a, b) => rank(a) - rank(b) || String(a.id).localeCompare(String(b.id)));
}
function filtered(p, jobs) {
  const q = state.q.trim().toLowerCase();
  return q ? jobs.filter((j) => `${j.id} ${j.title} #${j.issue}`.toLowerCase().includes(q)) : jobs;
}

function renderHead() {
  const p = project(state.project);
  if (!p) { $('#mhead').innerHTML = ''; return; }
  const idx = projects().indexOf(p) + 1;
  const c = counts(p);
  const cost = (p.jobs || []).reduce((m, j) => m + (Number(j.cost_usd) || 0), 0);
  $('#mhead').innerHTML = `<h1><small>${roman(idx)}</small>${esc(p.name)}</h1>
    <div class="facts">${p.path ? `<span class="mono">${esc(p.path)}</span>` : ''}
      ${p.ok ? `<span><b>${c.active}</b> active</span><span><b>${c.waiting}</b> waiting</span><span><b>${c.done}</b> done</span><span class="cost"><b>$${cost.toFixed(2)}</b></span>` : ''}</div>
    ${p.ok ? `<div class="seg" role="group" aria-label="View"><button class="${state.view === 'via' ? 'on' : ''}" data-view="via" type="button">Via</button><button class="${state.view === 'table' ? 'on' : ''}" data-view="table" type="button">Table</button></div>` : ''}`;
}

function node(p, j, i) {
  const ps = pos(p, j);
  if (i !== ps) return i < ps ? '<span class="node pt"></span>' : '<span class="node pt fut"></span>';
  if (j.stage === 'merged') return '<span class="node"><span class="mg ok" title="merged">✓</span></span>';
  if (j.stage === 'rejected') return '<span class="node"><span class="mg no" title="rejected">×</span></span>';
  if (isWaiting(j)) return `<span class="node"><span class="mg you" title="${esc(j.human_reason || 'needs you')}">!</span></span>`;
  const live = liveOf(p, j);
  const liveRoles = new Set(live ? live.roles : []);
  if (j.stage === 'review') {
    const roster = Object.keys(j.roster?.reviewers || {});
    const roles = [...new Set([...roster, ...Object.keys(j.reviews || {})])];
    if (roles.length) {
      return `<span class="node cluster">${roles.map((r) => {
        const v = (j.reviews || {})[r];
        return mg(r, liveRoles.has(r) ? 'live' : v === 'PASS' ? 'pass' : v === 'CHANGES' ? 'chg' : 'pend');
      }).join('')}</span>`;
    }
  }
  if (j.stage === 'gate') return `<span class="node"><span class="mg seal ${live ? 'live' : ''}" title="running the checks"><img src="${asset('seal')}" alt="checks"></span></span>`;
  const role = live?.roles?.[0] || STAGE_ROLE[j.stage] || 'probator';
  return `<span class="node">${mg(role, live ? 'live' : '')}</span>`;
}

const NS = 'vector-effect="non-scaling-stroke"';
const svg = (inner) => `<svg class="trk" viewBox="0 0 100 56" preserveAspectRatio="none" aria-hidden="true">${inner}</svg>`;

function aqueductCell(p, j, i, ps) {
  const fut = i > ps;
  const arch = 'M0 25 H100 V54 H93 V41 A43 15 0 0 0 7 41 V54 H0 Z';
  const tank = 'M14 54 V22 L50 9 L86 22 V54 Z M40 54 V40 A10 10 0 0 1 60 40 V54 Z';
  let s = '';
  if (fut) {
    s += i === 6
      ? `<path d="${tank}" fill="none" stroke="var(--line-2)" stroke-dasharray="3 3" fill-rule="evenodd" ${NS}/><path d="M0 18 H14" stroke="var(--line-2)" stroke-dasharray="3 3" ${NS}/>`
      : `<path d="${arch}" fill="none" stroke="var(--line-2)" stroke-dasharray="3 3" ${NS}/><path d="M0 15 H100" stroke="var(--line-2)" stroke-dasharray="3 3" ${NS}/>`;
    return svg(s);
  }
  if (i === 6) {
    s += `<path d="${tank}" fill="var(--stone)" stroke="var(--stone-d)" fill-rule="evenodd" ${NS}/><rect x="0" y="15" width="14" height="10" fill="var(--stone)" stroke="var(--stone-d)" ${NS}/><rect x="0" y="17.5" width="40" height="5" fill="var(--water)"/>`;
    return svg(s);
  }
  s += `<path d="${arch}" fill="var(--stone)" stroke="var(--stone-d)" ${NS}/>`;
  s += `<rect x="0" y="15" width="100" height="10" fill="var(--stone)" stroke="var(--stone-d)" ${NS}/><rect x="0" y="12.5" width="100" height="2.8" fill="var(--stone-d)"/>`;
  s += `<rect x="46.5" y="25" width="7" height="4.5" fill="var(--stone-d)"/><path d="M28 31 L25 28 M72 31 L75 28 M14 37 L10 35 M86 37 L90 35" stroke="var(--stone-d)" ${NS}/>`;
  const end = i < ps ? 100 : isWaiting(j) ? 59 : 52;
  s += `<rect x="0" y="17.5" width="${end}" height="5" fill="var(--water)"/>`;
  if (i === ps && !isWaiting(j)) s += `<path d="M${end} 17.5 q3 2.5 0 5" fill="var(--water)"/>`;
  if (liveOf(p, j)) s += `<path class="whl" d="M0 19.3 H${end}" stroke="#fff" stroke-opacity=".8" stroke-width="1.2" ${NS}/>`;
  if (i === 3 && gateFailed(p, j)) s += `<path d="M38 15 L43 19 L39 21.5 L45 25" fill="none" stroke="var(--ink-3)" stroke-width="1.2" ${NS}/><ellipse cx="46" cy="30" rx="1.3" ry="1.8" fill="var(--water)"/><ellipse cx="48" cy="36" rx="1.1" ry="1.5" fill="var(--water)"/>`;
  if (isWaiting(j) && i === ps) s += `<rect x="60" y="10" width="5" height="17" rx="1" fill="var(--wood)"/><path d="M62.5 10 V6 M59 6 H66" stroke="var(--wood)" stroke-width="1.5" ${NS}/>`;
  return svg(s);
}

function roadCell(i, ps) {
  const left = 'M14 37.5 L12 46 M31 37.5 L33 41.5 L30 46 M47 37.5 L45 46 M0 41.8 H9 M20 41.6 H40';
  const right = 'M64 37.5 L67 42 L64 46 M82 37.5 L80 46 M54 41.7 H74 M88 41.8 H100';
  const end = i < ps ? 100 : i === ps ? 50 : 0;
  let s = `<rect x="0" y="38.5" width="100" height="6.5" fill="var(--dirt)"/><path d="M0 38.5 H100 M0 45 H100" stroke="var(--line-2)" stroke-dasharray="2 4" ${NS}/>`;
  if (end) {
    s += `<rect x="0" y="37" width="${end}" height="9.5" fill="var(--basalt)"/><path d="${left}${end === 100 ? ` ${right}` : ''}" stroke="var(--basalt-d)" fill="none" ${NS}/>`;
    s += `<path d="M0 36.6 H${end} M0 46.8 H${end}" stroke="var(--stone-d)" stroke-width="2" ${NS}/>`;
  }
  return svg(s);
}

function trackCell(p, j, i) {
  const ps = pos(p, j);
  if (prefs.line === 'aqueduct') return `<div class="cell aq">${aqueductCell(p, j, i, ps)}${i === ps ? node(p, j, i) : ''}</div>`;
  if (prefs.line === 'road') {
    const stone = i === ps ? node(p, j, i)
      : `<span class="ms ${i > ps ? 'fut' : ''} ${i === 6 ? 'gold' : ''}" title="${i === 6 ? 'the golden milestone' : `milestone ${NUM[i]}`}">${NUM[i]}</span>`;
    return `<div class="cell rd">${roadCell(i, ps)}${stone}</div>`;
  }
  const l = i === 0 ? 'gone' : i <= ps ? '' : 'todo';
  const r = i === 6 ? 'gone' : i < ps ? '' : 'todo';
  return `<div class="cell"><i class="l ${l}"></i><i class="r ${r}"></i>${node(p, j, i)}</div>`;
}

function pips(j) {
  const out = [];
  const limit = Math.max(j.round_limit || 3, j.round || 0);
  for (let i = 0; i < limit; i++) {
    let cls = '';
    if (i < (j.round || 0) - 1) cls = 'fail';
    else if (i === (j.round || 0) - 1) cls = j.stage === 'merged' || approved(j) ? 'okr' : 'cur';
    out.push(`<i class="${cls}" title="${cls === 'fail' ? `round ${i + 1}: sent back` : `round ${i + 1}`}"></i>`);
  }
  return `<div class="pips">${out.join('')}<span>r${j.round || 0}/${j.round_limit || '?'}<span class="cost"> · $${(Number(j.cost_usd) || 0).toFixed(2)}</span></span></div>`;
}

function caption(p, j) {
  const live = liveOf(p, j);
  if (j.stage === 'needs-human') return `<div class="cap you">${esc(approved(j) && j.pr ? `Approved. Merge PR #${j.pr}` : (j.human_reason || 'needs you'))}</div>`;
  if (j.stage === 'needs-info') return `<div class="cap you">Waiting for the author, issue #${esc(j.issue)}</div>`;
  if (live) {
    const who = live.roles.map(roleName).join(', ');
    return `<div class="cap live">${esc(who)} ${esc(VERB[live.roles[0]] || 'working')} · <span class="mono" data-age="${live.age_seconds}">${mmss(live.age_seconds)}</span></div>`;
  }
  if (j.stage === 'gate') return '<div class="cap">checks queued</div>';
  return `<div class="cap">${esc(j.stage)}, nobody on it</div>`;
}

function subline(p, j) {
  const h = state.history.get(keyOf(p, j));
  const bits = [`#${j.issue}`];
  if (h?.intake?.risk) bits.push(`${h.intake.risk.toLowerCase()} risk`);
  if (h?.intake?.surfaces && h.intake.surfaces.toLowerCase() !== 'none') bits.push(h.intake.surfaces.toLowerCase());
  if (j.pr) bits.push(`PR #${j.pr}`);
  return bits.join(' · ');
}

function renderBoard() {
  const p = project(state.project);
  const board = $('#board');
  if (!state.data) return;
  if (!p) {
    board.innerHTML = '<div class="empty"><img src="../assets/role-probator.webp" alt=""><div><b>No centuria found.</b><br>Station one with <span class="mono">legio add &lt;path&gt;</span>, then refresh.</div></div>';
    return;
  }
  if (!p.ok) {
    board.innerHTML = `<div class="broken"><img src="${asset('tent-warped')}" alt=""><b>This centuria can't be read.</b> Nothing is hidden; legio just can't read it right now.<pre>${esc(p.error || 'unknown error')}</pre><p class="note" style="color:var(--red)">Try <span class="mono">legio doctor ${esc(p.name)}</span> in a terminal.</p></div>`;
    return;
  }
  const open = filtered(p, orderedOpen(p));
  const done = filtered(p, (p.jobs || []).filter(isTerminal)).sort((a, b) => String(b.id).localeCompare(String(a.id)));
  for (const j of open) enqueueHistory(p, j);

  if (state.view === 'table') {
    const rows = [...open, ...(prefs.done ? done : [])];
    board.innerHTML = `<table class="tbl"><thead><tr><th>JOB</th><th>TITLE</th><th>STAGE</th><th>ROUND</th><th>GATE</th><th>REVIEWS</th><th>PR</th><th class="cost">COST</th></tr></thead><tbody>${rows.map((j) => {
      const st = isWaiting(j) ? `<span class="badge b-ochre">${j.stage === 'needs-info' ? 'needs info' : 'needs you'}</span>`
        : j.stage === 'merged' ? '<span class="badge b-verd">merged</span>'
          : j.stage === 'rejected' ? '<span class="badge b-red">rejected</span>'
            : `<span class="badge b-blue">${esc(j.stage)}</span>`;
      const rv = Object.entries(j.reviews || {}).map(([r, v]) => `<span title="${esc(roleName(r))}: ${esc(v)}" style="color:${v === 'PASS' ? 'var(--verd)' : v === 'CHANGES' ? 'var(--red)' : 'var(--ink-3)'}">${esc(roleName(r))}</span>`).join(', ') || '–';
      return `<tr class="${state.job === j.id ? 'sel' : ''}" data-job="${esc(j.id)}" tabindex="0"><td class="mono">${esc(shortId(j))}</td><td>${esc(j.title)}</td><td>${st}</td><td class="mono">${j.round || 0}/${j.round_limit || '?'}</td><td>${esc(j.gate || '–')}</td><td>${rv}</td><td>${j.pr ? `#${esc(j.pr)}` : '–'}</td><td class="mono cost">$${(Number(j.cost_usd) || 0).toFixed(2)}</td></tr>`;
    }).join('')}</tbody></table>${rows.length ? '' : '<p class="note">No jobs match.</p>'}`;
    return;
  }

  const per = STAGES.map((_, i) => open.filter((j) => pos(p, j) === i).length);
  let html = `<div class="vgrid vhead"><div>JOB</div>${STAGES.map((s, i) => `<div>${s}<b>${i === 6 ? '' : per[i] || '·'}</b></div>`).join('')}<div>NOW</div></div>`;
  html += open.map((j) => `<div class="vgrid vrow ${state.job === j.id ? 'sel' : ''}" data-job="${esc(j.id)}" tabindex="0">
      <div class="vjob"><span class="id">${esc(shortId(j))}</span><div style="min-width:0"><div class="vt" title="${esc(j.title)}">${esc(j.title)}</div><div class="vs">${esc(subline(p, j))}</div></div></div>
      ${STAGES.map((_, i) => trackCell(p, j, i)).join('')}
      <div class="vmeta">${pips(j)}${caption(p, j)}</div></div>`).join('');
  if (!open.length) {
    html += state.q
      ? '<p class="note" style="padding:16px 0">No open jobs match the filter.</p>'
      : '<div class="empty"><img src="../assets/role-probator.webp" alt=""><div><b>All quiet in this camp.</b><br>Label an issue <span class="mono">centuria</span> and run <span class="mono">legio sync</span> to start a job.</div></div>';
  }
  if (done.length && prefs.done) {
    html += `<div class="done-h"><span class="la">FACTUM · </span>FINISHED ${done.length}</div>${done.map((j) => `<div class="drow ${state.job === j.id ? 'sel' : ''}" data-job="${esc(j.id)}" tabindex="0">
      <span class="mono">${esc(shortId(j))}</span><span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(j.title)}</span>
      <span><span class="badge ${j.stage === 'merged' ? 'b-verd' : 'b-red'}">${esc(j.stage)}</span></span>
      <span class="mono cost" style="text-align:right">$${(Number(j.cost_usd) || 0).toFixed(2)}</span></div>`).join('')}`;
  }
  board.innerHTML = html;
}

// ---------------------------------------------------------------- rendering: the job's scroll

function storyOf(p, j) {
  const h = state.history.get(keyOf(p, j)) || { files: [], rounds: {} };
  const has = (f) => h.files.includes(f);
  const items = [{ label: `Issue #${j.issue}`, text: 'the request', file: has('issue.md') ? 'issue.md' : null }];
  if (h.intake) {
    const d = h.intake.decision.toUpperCase();
    const bits = [d.toLowerCase(), h.intake.risk && `${h.intake.risk.toLowerCase()} risk`,
      h.intake.surfaces && h.intake.surfaces.toLowerCase() !== 'none' && h.intake.surfaces.toLowerCase()].filter(Boolean);
    items.push({ label: 'Intake', role: 'tesserarius', text: bits.join(' · '), state: d === 'ACCEPT' ? 'ok' : d === 'REJECT' ? 'fail' : 'you', file: 'intake.md' });
  }
  if (has('spec.md')) items.push({ label: 'Spec', role: 'signifer', text: 'ready', state: 'ok', file: 'spec.md' });
  const fileRounds = Object.keys(h.rounds).map(Number);
  const last = Math.max(j.round || 0, ...fileRounds, 0);
  for (let r = 1; r <= last; r++) {
    const rr = h.rounds[r] || { gate: null, reviews: {} };
    const current = r === (j.round || 0);
    items.push({ label: `Round ${r}`, role: 'fabri', text: r < (j.round || 0) ? 'sent back' : 'build', file: current && has('build.md') ? 'build.md' : null });
    const gate = rr.gate || (current ? j.gate : null);
    if (gate) items.push({ label: 'Gate', text: gate.toLowerCase(), state: gate === 'PASS' ? 'ok' : 'fail', file: has(`round-${r}/checks.md`) ? `round-${r}/checks.md` : null });
    const reviews = { ...rr.reviews, ...(current ? Object.fromEntries(Object.entries(j.reviews || {}).filter(([, v]) => v === 'PASS' || v === 'CHANGES')) : {}) };
    for (const [role, v] of Object.entries(reviews)) {
      const f = `round-${r}/review-${role}.md`;
      items.push({ label: roleName(role), role, text: v === 'PASS' ? 'pass' : v === 'CHANGES' ? 'changes' : v, state: v === 'PASS' ? 'ok' : 'fail', file: has(f) ? f : null });
    }
  }
  for (const f of h.feedback || []) items.push({ label: 'Your feedback', text: f.replace(/\.md$/, ''), file: f });
  if (h.decision) items.push({ label: 'Primus Pilus', role: 'primus-pilus', text: h.decision.toLowerCase(), state: h.decision === 'APPROVE' ? 'ok' : 'you', file: 'decision.md' });
  for (const live of livesOf(p, j)) {
    for (const role of live.roles) items.push({ label: roleName(role), role, text: live.stale ? 'started a while ago' : `${VERB[role] || 'working'} now`, state: 'live' });
  }
  if (j.stage === 'needs-human') items.push({ label: 'You', text: j.human_reason || 'needs a human', state: 'you' });
  if (j.stage === 'needs-info') items.push({ label: 'The author', text: `answers on issue #${j.issue}; the job resumes on its own`, state: 'you' });
  if (j.stage === 'merged') items.push({ label: 'Merged', text: j.pr ? `PR #${j.pr}` : '', state: 'ok' });
  if (j.stage === 'rejected') items.push({ label: 'Rejected', text: '', state: 'fail', file: has('rejection.md') ? 'rejection.md' : null });
  const shown = new Set(items.map((s) => s.file).filter(Boolean));
  for (const f of h.files) {
    if (shown.has(f)) continue;
    const log = f.match(/^agent-(\d+)-([\w-]+)\.log$/);
    if (log) items.push({ label: `${roleName(log[2])} log`, role: log[2], text: `round ${log[1]}`, file: f, kind: 'log' });
    else items.push({ label: f.replace(/\.md$/, ''), text: '', file: f });
  }
  return { items, files: h.files };
}

function actionsOf(p, j) {
  const ref = `${p.name}:${shortId(j)}`;
  const acts = [];
  if (j.stage === 'needs-human') {
    if (approved(j) && j.pr) acts.push(['Copy merge command', `gh pr merge ${j.pr}`, true]);
    acts.push(['Copy feedback command', `legio say ${ref} "your feedback"`, !approved(j)]);
    acts.push(['Copy reject command', `legio reject ${ref} "reason"`]);
  } else if (j.stage === 'needs-info') {
    acts.push(['Copy issue command', `gh issue view ${j.issue} --web`, true]);
    acts.push(['Copy reject command', `legio reject ${ref} "reason"`]);
  } else if (!isTerminal(j)) {
    acts.push(['Copy run command', `legio run ${ref}`]);
  }
  acts.push(['Copy job id', j.id]);
  return acts;
}

// one quiet line under the title: only the facts this job actually has
function factsOf(p, j) {
  const live = liveOf(p, j);
  const stage = j.stage === 'needs-human' ? 'needs you' : j.stage === 'needs-info' ? 'needs info' : j.stage;
  const tone = isWaiting(j) ? 'b-ochre' : j.stage === 'merged' ? 'b-verd' : j.stage === 'rejected' ? 'b-red' : live ? 'b-blue' : 'b-mute';
  const bits = [`<span class="badge ${tone}">${esc(stage)}</span>`];
  if (j.round) bits.push(`<span class="dm">round ${esc(j.round)} of ${esc(j.round_limit || '?')}</span>`);
  if (j.gate) bits.push(`<span class="dm">gate <b class="${j.gate === 'PASS' ? 'okt' : 'badt'}">${esc(j.gate.toLowerCase())}</b></span>`);
  if (j.pr) bits.push(`<span class="dm">PR #${esc(j.pr)}</span>`);
  const reviewers = [...new Set([...Object.keys(j.roster?.reviewers || {}), ...Object.keys(j.reviews || {})])];
  if (reviewers.length) {
    bits.push(`<span class="dm faces" title="reviewers: ${esc(reviewers.map(roleName).join(', '))}">${reviewers.map((r) => {
      const v = (j.reviews || {})[r];
      return mg(r, v === 'PASS' ? 'pass' : v === 'CHANGES' ? 'chg' : 'pend');
    }).join('')}</span>`);
  }
  bits.push(`<span class="dm cost">$${(Number(j.cost_usd) || 0).toFixed(2)}</span>`);
  bits.push(`<span class="dm mono id" title="job id">${esc(p.name)}:${esc(j.id)}</span>`);
  return bits.join('');
}

function renderMd(text) {
  const lines = String(text).split('\n');
  let i = 0;
  const hdr = [];
  while (i < lines.length && /^([A-Z-]+:\s|(APPROVE|ESCALATE|REJECTED)\s*$)/.test(lines[i])) hdr.push(lines[i++]);
  let out = hdr.length ? `<div class="hdr">${hdr.map(esc).join('<br>')}</div>` : '';
  let list = false;
  let code = false;
  for (; i < lines.length; i++) {
    const l = lines[i];
    if (/^```/.test(l)) { out += code ? '</pre>' : '<pre>'; code = !code; continue; }
    if (code) { out += `${esc(l)}\n`; continue; }
    if (/^\s*[-*] /.test(l)) { if (!list) { out += '<ul>'; list = true; } out += `<li>${esc(l.replace(/^\s*[-*] /, ''))}</li>`; continue; }
    if (list) { out += '</ul>'; list = false; }
    if (/^#{1,4} /.test(l)) out += `<h4>${esc(l.replace(/^#+ /, ''))}</h4>`;
    else if (l.trim()) out += `<p>${esc(l)}</p>`;
  }
  if (code) out += '</pre>';
  return out + (list ? '</ul>' : '');
}

function renderDetail() {
  const p = project(state.project);
  const j = p && (p.jobs || []).find((x) => x.id === state.job);
  const box = $('#detail');
  $('#mid').classList.toggle('nodetail', !j);
  box.hidden = !j;
  if (!j) { box.innerHTML = ''; if (state.big) setBig(false); return; }
  enqueueHistory(p, j);
  const { items, files } = storyOf(p, j);
  if (!files.includes(state.file)) {
    const withFile = items.filter((s) => s.file);
    state.file = (withFile[withFile.length - 1] || {}).file || files[0] || null;
  }
  const acts = actionsOf(p, j);
  const primary = acts.find((a) => a[2]);
  const rest = acts.filter((a) => a !== primary);
  const head = (s) => (s.role && ROLE_NAMES[s.role] ? mg(s.role, 'tiny') : '');
  box.innerHTML = `<div class="dhead">
      <div class="dtitle"><h2 title="${esc(j.title)}">${esc(j.title)}</h2><div class="dmeta">${factsOf(p, j)}</div></div>
      <div class="acts">${primary ? `<button class="btn pri" type="button" data-copy="${esc(primary[1])}" title="${esc(primary[1])}">${esc(primary[0])}</button>` : ''}
        <details class="menu"><summary class="btn" title="Copy a command">Copy<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg></summary>
          <div class="menu-list">${rest.map(([label, cmd]) => `<button type="button" data-copy="${esc(cmd)}"><b>${esc(label.replace(/^Copy /, ''))}</b><span class="mono">${esc(cmd)}</span></button>`).join('')}</div></details>
        ${expandButton()}</div></div>
    <div class="dbody"><div class="story" aria-label="Timeline and files">${items.map((s) => `<div class="st ${s.state || ''}"><div class="h">${esc(s.label)}${head(s)}</div>${s.text ? `<div class="t">${esc(s.text)}</div>` : ''}${s.file ? `<button class="f ${state.file === s.file ? 'on' : ''}" type="button" data-file="${esc(s.file)}">${esc(s.file)}</button>` : ''}</div>`).join('')}</div>
      <div class="vsplit" role="separator" aria-orientation="vertical" aria-label="Resize the timeline (drag, or use the arrow keys; double-click to reset)" tabindex="0"></div>
      <div class="reader"><div class="docbar"><span class="mono">${esc(state.file || '')}</span>${state.file ? `<span class="note">${files.indexOf(state.file) + 1} of ${files.length}</span>` : ''}</div>
        <div class="doc" id="doc">${files.length ? '<p class="note">Loading…</p>' : '<p class="note">No files yet. They appear as the roles write them.</p>'}</div></div></div>`;
  const on = box.querySelector('.story .f.on');
  if (on) on.scrollIntoView({ block: 'nearest' });
  loadDoc(p, j);
}

// ---------------------------------------------------------------- the job's scroll: resize and pop out

const EXPAND_ICON = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.5 2.5h4v4M13.5 2.5 9 7M6.5 13.5h-4v-4M2.5 13.5 7 9"/></svg>';
const SHRINK_ICON = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.5 6.5h-4v-4M9.5 6.5 14 2M2.5 9.5h4v4M6.5 9.5 2 14"/></svg>';
function expandButton() {
  const label = state.big ? 'Shrink back (Esc)' : 'Expand';
  return `<button class="btn ico-btn" type="button" data-expand title="${label}" aria-label="${label}" aria-pressed="${state.big}">${state.big ? SHRINK_ICON : EXPAND_ICON}</button>`;
}
function setBig(big) {
  state.big = big;
  document.body.classList.toggle('bigdetail', big);
  $('#scrim').hidden = !big;
  const b = document.querySelector('[data-expand]');
  if (b) b.outerHTML = expandButton();
  if (big) document.querySelector('[data-expand]')?.focus();
}

// drag the bar beside the timeline to share the width between it and the file
const STORY_MIN = 160;
function setStoryWidth(px, save) {
  const detail = $('#detail');
  if (px == null) {
    detail.style.removeProperty('--sw');
    prefs.storyW = null;
  } else {
    const body = detail.querySelector('.dbody');
    const max = (body ? body.clientWidth : 900) - 320;
    const w = Math.round(Math.max(STORY_MIN, Math.min(max, px)));
    detail.style.setProperty('--sw', `${w}px`);
    prefs.storyW = w;
  }
  if (save) savePrefs();
}
document.addEventListener('pointerdown', (e) => {
  const bar = e.target.closest && e.target.closest('.vsplit');
  if (!bar || e.button !== 0) return;
  e.preventDefault();
  try { bar.setPointerCapture(e.pointerId); } catch (_) { /* pointer already gone */ }
  bar.classList.add('drag');
  document.body.classList.add('resizing-x');
  const left = bar.parentElement.getBoundingClientRect().left;
  const move = (ev) => setStoryWidth(ev.clientX - left - 4, false);
  const up = () => {
    bar.removeEventListener('pointermove', move);
    bar.removeEventListener('pointerup', up);
    bar.removeEventListener('pointercancel', up);
    bar.classList.remove('drag');
    document.body.classList.remove('resizing-x');
    savePrefs();
  };
  bar.addEventListener('pointermove', move);
  bar.addEventListener('pointerup', up);
  bar.addEventListener('pointercancel', up);
});
document.addEventListener('dblclick', (e) => { if (e.target.closest && e.target.closest('.vsplit')) setStoryWidth(null, true); });
document.addEventListener('keydown', (e) => {
  if (!e.target.classList || !e.target.classList.contains('vsplit')) return;
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  e.preventDefault();
  const now = document.querySelector('#detail .story').offsetWidth;
  setStoryWidth(now + (e.key === 'ArrowRight' ? 24 : -24), true);
});

// drag the bar between the board and the scroll to give either more room
const DETAIL_MIN = 140;
function clampDetail(px) {
  const mid = $('#mid');
  const head = $('#mhead').offsetHeight;
  const max = mid.clientHeight - head - 9 - 120;
  return Math.round(Math.max(DETAIL_MIN, Math.min(max, px)));
}
function setDetailHeight(px, save) {
  if (px == null) {
    $('#mid').style.removeProperty('--dh');
    prefs.detailH = null;
  } else {
    const h = clampDetail(px);
    $('#mid').style.setProperty('--dh', `${h}px`);
    prefs.detailH = h;
  }
  if (save) savePrefs();
}
(() => {
  const split = $('#split');
  split.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    try { split.setPointerCapture(e.pointerId); } catch (_) { /* pointer already gone */ }
    split.classList.add('drag');
    document.body.classList.add('resizing');
    const bottom = $('#mid').getBoundingClientRect().bottom;
    const move = (ev) => setDetailHeight(bottom - ev.clientY - 4, false);
    const up = () => {
      split.removeEventListener('pointermove', move);
      split.removeEventListener('pointerup', up);
      split.removeEventListener('pointercancel', up);
      split.classList.remove('drag');
      document.body.classList.remove('resizing');
      savePrefs();
    };
    split.addEventListener('pointermove', move);
    split.addEventListener('pointerup', up);
    split.addEventListener('pointercancel', up);
  });
  split.addEventListener('dblclick', () => setDetailHeight(null, true));
  split.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    e.preventDefault();
    const now = $('#detail').offsetHeight;
    setDetailHeight(now + (e.key === 'ArrowUp' ? 32 : -32), true);
  });
})();

async function loadDoc(p, j) {
  const path = state.file;
  const doc = $('#doc');
  if (!path || !doc) return;
  try {
    const data = await readFile(p, j, path);
    if (state.file !== path || state.job !== j.id) return;
    const body = path.endsWith('.log') ? `<pre>${esc(data.text)}</pre>` : renderMd(data.text);
    $('#doc').innerHTML = `${data.truncated ? '<p class="note">Showing part of a large file.</p>' : ''}${body}`;
  } catch (_) {
    if (state.file === path) $('#doc').innerHTML = `<p class="note">Couldn't read ${esc(path)}.</p>`;
  }
}

// ---------------------------------------------------------------- rendering: right rail

function renderNeeds() {
  const rows = [];
  for (const p of projects()) {
    for (const j of p.jobs || []) {
      if (!isWaiting(j)) continue;
      const ref = `${p.name}:${shortId(j)}`;
      const info = j.stage === 'needs-info';
      const cmd = info ? `gh issue view ${j.issue} --web` : approved(j) && j.pr ? `gh pr merge ${j.pr}` : `legio say ${ref} "your feedback"`;
      const why = info ? `Waiting for the author to answer on issue #${j.issue}.` : approved(j) && j.pr ? `Approved. Merge PR #${j.pr} when you're ready.` : (j.human_reason || 'Needs a human.');
      rows.push(`<a class="need" href="#/legion/${enc(p.name)}/job/${enc(j.id)}"><img class="seal" src="${asset('seal')}" alt="">
        <div class="top1"><span class="who">${esc(p.name)} · ${esc(shortId(j))} ${esc(j.title)}</span><span class="badge b-ochre">${info ? 'info' : approved(j) ? 'merge' : 'decide'}</span></div>
        <div class="why">${esc(why)}</div>
        <div class="cmd"><span>${esc(cmd)}</span><button type="button" data-copy="${esc(cmd)}">Copy</button></div></a>`);
    }
  }
  $('#nneed').textContent = rows.length || '';
  $('#rneed').textContent = rows.length;
  $('#rneed').hidden = !rows.length;
  $('.eaglebtn').title = `${rows.length ? `${rows.length} need${rows.length === 1 ? 's' : ''} you. ` : ''}Show needs you, at work and Legatus ( ] )`;
  $('#needs').innerHTML = rows.join('') || '<div class="note" style="padding:0 6px">The eagle has no messages for you.</div>';
}

function allLives() {
  const out = [];
  for (const p of projects()) {
    for (const l of p.lives || []) {
      const j = (p.jobs || []).find((x) => x.id === l.job);
      out.push({ p, l, j });
    }
  }
  return out.sort((a, b) => a.l.age_seconds - b.l.age_seconds);
}

function deskPick(lives) {
  const p = project(state.project);
  const j = p && (p.jobs || []).find((x) => x.id === state.job);
  return lives.find((x) => x.p === p && x.j === j && !x.l.stale) || lives.find((x) => !x.l.stale) || null;
}

function renderWork() {
  const lives = allLives();
  const pick = deskPick(lives);
  $('#nwork').textContent = lives.length ? `${lives.length} ${lives.length === 1 ? 'agent' : 'agents'}` : '';
  if (pick && pick.l.roles.length) {
    const role = pick.l.roles[0];
    const others = pick.l.roles.length > 1 ? ` (with ${pick.l.roles.slice(1).map(roleName).join(', ')})` : '';
    const img = ROLE_NAMES[role] ? asset(`role-${role}-working`) : asset('desk');
    $('#desk').innerHTML = `<a class="desk" href="#/legion/${enc(pick.p.name)}/job/${enc(pick.l.job)}"><img src="${img}" alt="${esc(roleName(role))} at the desk"><img class="hs" src="${asset('hearts-sparkles')}" alt="">
      <div class="bubble"><b>${esc(roleName(role))}</b>${esc(others)} is ${esc(VERB[role] || 'working')}<br>${esc(pick.j ? pick.j.title : pick.l.job)}<br>
      <span class="mono">${esc(pick.p.name)}:${esc(pick.j ? shortId(pick.j) : pick.l.job)} · r${esc(pick.l.round ?? '?')} · <span data-age="${pick.l.age_seconds}">${mmss(pick.l.age_seconds)}</span></span></div></a>`;
  } else {
    $('#desk').innerHTML = '';
  }
  const rest = lives.filter((x) => x !== pick);
  $('#work').innerHTML = rest.map(({ p, l, j }) => {
    const role = l.roles[0] || 'fabri';
    return `<a class="work ${l.stale ? 'stale' : ''}" href="#/legion/${enc(p.name)}/job/${enc(l.job)}" style="color:inherit;text-decoration:none">${mg(role, l.stale ? 'you' : 'live')}
      <div style="min-width:0"><div class="w1"><b>${esc(l.roles.map(roleName).join(', ') || 'agent')}</b> · ${esc(p.name)} ${esc(j ? `${shortId(j)} ${j.title}` : l.job)}</div>
      <div class="w2">${l.stale ? 'running for more than 10 minutes' : `round ${esc(l.round ?? '?')}`}</div></div>
      <span class="tm" data-age="${l.age_seconds}">${mmss(l.age_seconds)}</span></a>`;
  }).join('') || (pick ? '' : '<div class="note" style="padding:0 6px">Nobody is working right now.</div>');
}

function renderMsgs() {
  const html = state.msgs.map((m) => `<div class="lgrow"><span class="lgface" role="img" aria-label="Legatus"></span><div class="msg"><time>${esc(m.at)}</time>${m.html}</div></div>`).join('');
  for (const box of [$('#msgs'), $('#lgmsgs')]) {
    const near = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.innerHTML = html;
    if (near) box.scrollTop = box.scrollHeight;
  }
  $('#lgdot').hidden = !state.unread;
  $('.lgbtn').title = state.unread ? `Legatus has ${state.unread} new ${state.unread === 1 ? 'message' : 'messages'}` : 'Talk to Legatus';
}

// Legatus's own window, opened from his face on the folded right rail
function openLegatus(open) {
  $('#lgwin').hidden = !open;
  $('.lgbtn').setAttribute('aria-expanded', String(open));
  if (open) {
    state.unread = 0;
    renderMsgs();
    const box = $('#lgmsgs');
    box.scrollTop = box.scrollHeight;
    $('[data-legatus-close]').focus();
  }
}

// ---------------------------------------------------------------- settings panel

const MINI = {
  aqueduct: '<svg viewBox="0 0 46 14" aria-hidden="true"><rect x="0" y="2" width="46" height="3" fill="var(--stone)" stroke="var(--stone-d)" stroke-width=".8"/><rect x="0" y="2.8" width="26" height="1.6" fill="var(--water)"/><path d="M0 5H46V14H43V10A8 4 0 0 0 31 10V14H27V10A8 4 0 0 0 19 10V14H15V10A8 4 0 0 0 3 10V14H0Z" fill="var(--stone)" stroke="var(--stone-d)" stroke-width=".8"/></svg>',
  road: '<svg viewBox="0 0 46 14" aria-hidden="true"><rect x="0" y="9" width="26" height="4" fill="var(--basalt)"/><rect x="26" y="9.5" width="20" height="3" fill="var(--dirt)" stroke="var(--line-2)" stroke-width=".6" stroke-dasharray="1.5 1.5"/><rect x="6" y="2" width="5" height="7" rx="2" fill="var(--stone)" stroke="var(--stone-d)" stroke-width=".8"/><rect x="20" y="2" width="5" height="7" rx="2" fill="var(--stone)" stroke="var(--stone-d)" stroke-width=".8"/><rect x="35" y="2" width="5" height="7" rx="2" fill="var(--gold)" stroke="var(--gold-d)" stroke-width=".8"/></svg>',
  plain: '<svg viewBox="0 0 46 14" aria-hidden="true"><path d="M3 7H25" stroke="var(--ink-3)" stroke-width="1.5"/><path d="M25 7H43" stroke="var(--line-2)" stroke-width="1.5" stroke-dasharray="2 2"/><circle cx="3" cy="7" r="2" fill="var(--ink-3)"/><circle cx="14" cy="7" r="2" fill="var(--ink-3)"/><circle cx="25" cy="7" r="4" fill="var(--blue-bg)" stroke="var(--blue)" stroke-width="1.2"/><circle cx="36" cy="7" r="2" fill="var(--raised)" stroke="var(--line-2)"/></svg>',
};
const TRACK_NOTE = {
  aqueduct: 'Water flows as far as the job has got. A crack marks a failed gate; a sluice gate means it waits on you.',
  road: 'Milestones I to VI, paved as the job passes them. The last one is the golden milestone.',
  plain: 'Dots and a line. The quietest option.',
};
function pick(key, opts, mini) {
  return `<div class="pick" role="group">${opts.map(([v, t]) => `<button type="button" class="${prefs[key] === v ? 'on' : ''}" data-pref="${key}" data-val="${v}" aria-pressed="${prefs[key] === v}">${mini ? MINI[v] : ''}${t}</button>`).join('')}</div>`;
}
const PANEL_TOGGLES = { lopen: 'lfold', ropen: 'rfold' };   // "open" switches stored as "folded"
function tog(key, label) {
  const on = PANEL_TOGGLES[key] ? !prefs[PANEL_TOGGLES[key]] : prefs[key];
  return `<label class="tog" for="pref-${key}">${label}<input type="checkbox" id="pref-${key}" data-toggle="${key}" ${on ? 'checked' : ''}></label>`;
}
function fold(side) {
  const key = side === 'left' ? 'lfold' : 'rfold';
  prefs[key] = !prefs[key];
  savePrefs(); applyPrefs(); afterFold();
}
function afterFold() {
  if (!prefs.rfold) { openLegatus(false); state.unread = 0; renderMsgs(); }
  if (!$('#sets').hidden) renderSettings();
  if (prefs.detailH) $('#mid').style.setProperty('--dh', `${clampDetail(prefs.detailH)}px`);
}
function renderSettings() {
  $('#sets').innerHTML = `<h3>SETTINGS<button type="button" data-close aria-label="Close settings">×</button></h3>
    <div class="srow"><span>Interface</span><div class="pick" role="group"><button type="button" class="on" aria-pressed="true">Principia</button><button type="button" data-skin="camp" aria-pressed="false">Camp (classic)</button></div><small>The classic camp is the illustrated view. You can switch back from its HELP panel.</small></div>
    <div class="srow"><span>Progress track</span>${pick('line', [['aqueduct', 'Aqueduct'], ['road', 'Road'], ['plain', 'Plain']], true)}<small>${TRACK_NOTE[prefs.line]}</small></div>
    <div class="srow"><span>Density</span>${pick('density', [['comfortable', 'Comfortable'], ['compact', 'Compact']])}</div>
    <div class="srow"><span>Labels</span>${pick('lang', [['latin', 'Latin and English'], ['english', 'English only']])}</div>
    <div class="srow">${tog('motion', 'Animations')}${tog('desk', 'Desk scene in At work')}${tog('cost', 'Show costs')}${tog('done', 'Show finished jobs')}</div>
    <div class="srow"><span>Panels</span>${tog('lopen', 'Projects on the left')}${tog('ropen', 'Needs you, at work and Legatus')}<small>Keys: [ and ] fold each side, \\ folds both for focus.</small></div>
    <div class="note">Saved in this browser only.</div>`;
}
function openSettings(open) {
  if (open) renderSettings();
  $('#sets').hidden = !open;
  $('#gear').setAttribute('aria-expanded', String(open));
}

// ---------------------------------------------------------------- glue

function renderAll() {
  renderStats();
  renderLeft();
  renderHead();
  renderBoard();
  renderDetail();
  renderNeeds();
  renderWork();
}

function renderTimersOnly() {
  const elapsed = (Date.now() - state.fetchedAt) / 1000;
  document.querySelectorAll('[data-age]').forEach((n) => { n.textContent = mmss(Number(n.dataset.age) + elapsed); });
}

let toastTimer = 0;
function toast(text) {
  const t = $('#toast');
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2200);
}
async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast(`Copied: ${text}`);
  } catch (_) {
    const area = document.createElement('textarea');
    area.value = text;
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (__) { ok = false; }
    area.remove();
    toast(ok ? `Copied: ${text}` : `Copy this: ${text}`);
  }
}

document.addEventListener('click', (e) => {
  const c = e.target.closest('[data-copy]');
  if (c) { e.preventDefault(); e.stopPropagation(); copy(c.dataset.copy); closeMenus(); return; }
  if (e.target.closest('[data-expand]')) { setBig(!state.big); return; }
  if (e.target.closest('#scrim')) { setBig(false); return; }
  if (e.target.closest('[data-legatus]')) { openLegatus($('#lgwin').hidden); return; }
  if (e.target.closest('[data-legatus-close]')) { openLegatus(false); $('.lgbtn').focus(); return; }
  const fd = e.target.closest('[data-fold]');
  if (fd) { fold(fd.dataset.fold); return; }
  const row = e.target.closest('[data-job]');
  if (row && state.project) { go(state.project, row.dataset.job); return; }
  const f = e.target.closest('[data-file]');
  if (f) {
    state.file = f.dataset.file;
    renderDetail();
    return;
  }
  const v = e.target.closest('[data-view]');
  if (v) { state.view = v.dataset.view; renderHead(); renderBoard(); }
});
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('#q').focus(); return; }
  if (e.key === 'Escape' && !$('#sets').hidden) { openSettings(false); $('#gear').focus(); return; }
  if (e.key === 'Escape' && state.big) { setBig(false); return; }
  if (e.key === 'Escape' && !$('#lgwin').hidden) { openLegatus(false); $('.lgbtn').focus(); return; }
  if (e.key === 'f' && !e.target.matches('input, textarea') && !e.metaKey && !e.ctrlKey && state.job) { setBig(!state.big); return; }
  if (e.target.matches('input, textarea') || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === 'Enter' && e.target.dataset && e.target.dataset.job) { go(state.project, e.target.dataset.job); return; }
  const p = project(state.project);
  if (!p) return;
  const order = [...filtered(p, orderedOpen(p)), ...(prefs.done ? filtered(p, (p.jobs || []).filter(isTerminal)).sort((a, b) => String(b.id).localeCompare(String(a.id))) : [])];
  const i = order.findIndex((j) => j.id === state.job);
  if ((e.key === 'j' || e.key === 'ArrowDown') && order.length) { e.preventDefault(); go(p.name, order[Math.min(order.length - 1, i + 1)].id); }
  if ((e.key === 'k' || e.key === 'ArrowUp') && order.length) { e.preventDefault(); go(p.name, order[Math.max(0, i - 1)].id); }
  if (e.key === 'v') { state.view = state.view === 'via' ? 'table' : 'via'; renderHead(); renderBoard(); }
  if (e.key === '[') fold('left');
  if (e.key === ']') fold('right');
  if (e.key === '\\') { const both = !(prefs.lfold && prefs.rfold); prefs.lfold = both; prefs.rfold = both; savePrefs(); applyPrefs(); afterFold(); }
});
$('#q').addEventListener('input', (e) => { state.q = e.target.value; renderBoard(); });
$('#gear').addEventListener('click', (e) => { e.stopPropagation(); openSettings($('#sets').hidden); });
$('#sets').addEventListener('click', (e) => {
  e.stopPropagation();
  if (e.target.closest('[data-close]')) { openSettings(false); $('#gear').focus(); return; }
  const skin = e.target.closest('[data-skin]');
  if (skin) { useSkin(skin.dataset.skin); return; }
  const b = e.target.closest('[data-pref]');
  if (!b) return;
  prefs[b.dataset.pref] = b.dataset.val;
  savePrefs(); applyPrefs(); renderSettings(); renderBoard();
});
$('#sets').addEventListener('change', (e) => {
  const key = e.target.dataset.toggle;
  if (!key) return;
  if (PANEL_TOGGLES[key]) { prefs[PANEL_TOGGLES[key]] = !e.target.checked; savePrefs(); applyPrefs(); afterFold(); return; }
  prefs[key] = e.target.checked;
  savePrefs(); applyPrefs(); renderBoard(); renderWork();
});
document.addEventListener('click', (e) => {
  if (!$('#sets').hidden && !e.target.closest('#sets, #gear')) openSettings(false);
}, true);
// the copy menu closes after a copy, on an outside click and on Escape
function closeMenus(except) {
  document.querySelectorAll('details.menu[open]').forEach((m) => { if (m !== except) m.open = false; });
}
document.addEventListener('click', (e) => closeMenus(e.target.closest && e.target.closest('details.menu')), true);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenus(); }, true);
window.addEventListener('hashchange', () => { if (state.data) { route(); renderAll(); } });
setInterval(renderTimersOnly, 1000);

try { localStorage.setItem('legio-skin', 'principia'); } catch (_) { /* ignore */ }
applyPrefs();
if (prefs.detailH) $('#mid').style.setProperty('--dh', `${prefs.detailH}px`);
if (prefs.storyW) $('#detail').style.setProperty('--sw', `${prefs.storyW}px`);
window.addEventListener('resize', () => { if (prefs.detailH) $('#mid').style.setProperty('--dh', `${clampDetail(prefs.detailH)}px`); });
poll();
