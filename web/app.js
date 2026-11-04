/* Camp Legio — the front end.
 *
 * Fetches /api/camp every 2.5s, renders either the camp or one tent.
 * No framework, no build step. Hash routes:
 *   #/                       the camp
 *   #/legion/<name>          one centuria's tent
 *   #/legion/<name>/cast     the eight roles
 */

'use strict';

const ROLE_FILES = ['tesserarius', 'signifer', 'fabri', 'probator', 'medicus',
  'mensor', 'librator', 'primus-pilus'];

const ROLE_VERB = {
  tesserarius: 'shutting the gate',
  signifer: 'raising the standard',
  fabri: 'hammering, do not disturb',
  probator: 'inspecting the work',
  medicus: 'tending to the work',
  mensor: 'measuring the ground',
  librator: 'levelling the ground',
  'primus-pilus': 'judging the work',
};

const ROLE_FALLBACK = {
  tesserarius: 'Doorkeeper', signifer: 'Standard-bearer', fabri: 'Engineer',
  probator: 'Inspector', medicus: 'Surgeon', mensor: 'Surveyor',
  librator: 'Level-keeper', 'primus-pilus': 'Arbiter',
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const app = $('#app');
const modal = $('#modal');

const state = { data: null, fingerprint: '', route: { view: 'camp' } };

/* ------------------------------------------------------------------ utils */

function asset(name) { return `assets/${name}.webp`; }

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function enc(name) { return encodeURIComponent(name); }

function hash01(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

function roman(number) {
  const table = [[1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'],
    [90, 'XC'], [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'],
    [4, 'IV'], [1, 'I']];
  let n = number;
  let out = '';
  for (const [value, glyph] of table) {
    while (n >= value) { out += glyph; n -= value; }
  }
  return out;
}

function ago(seconds) {
  const s = Number(seconds) || 0;
  if (s < 90) return `${Math.max(1, Math.round(s))}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  return `${Math.round(s / 3600)}h`;
}

function roleTitle(role, cast) {
  const found = (cast || []).find((entry) => entry.role === role);
  if (found) return found.title.split('·')[0].trim();
  return ROLE_FALLBACK[role] || role;
}

function counts(project) {
  const out = { active: 0, waiting: 0, done: 0 };
  for (const job of project.jobs || []) {
    if (job.terminal) out.done += 1;
    else if (job.waiting) out.waiting += 1;
    else if (job.active) out.active += 1;
  }
  return out;
}

function allWaiting() {
  const out = [];
  for (const project of state.data?.projects || []) {
    for (const job of project.jobs || []) {
      if (job.waiting) out.push({ project, job });
    }
  }
  return out;
}

/* ---------------------------------------------------------------- chrome */

function chrome({ active, project }) {
  const projects = state.data?.projects || [];
  const healthy = projects.filter((p) => p.ok).length;
  const cost = projects.reduce((sum, p) => sum
    + (p.jobs || []).reduce((inner, job) => inner + (Number(job.cost_usd) || 0), 0), 0);
  const waiting = allWaiting().length;
  const milites = project
    ? `#/legion/${enc(project.name)}/cast`
    : '#/';

  return `<header class="chrome">
    <a class="brand" href="#/" aria-label="Camp Legio — back to the camp">
      <img class="brand-logo" src="${asset('logo')}" alt="">
      <span class="brand-word">LEGIO</span>
    </a>
    <nav class="pills" aria-label="camp navigation">
      <a class="pill ${active === 'castra' ? 'active' : ''}" href="#/">
        <img class="ico" src="${asset('icon-castra')}" alt="">CASTRA</a>
      <a class="pill ${active === 'milites' ? 'active' : ''} ${project ? '' : 'disabled'}"
         href="${milites}" ${project ? '' : 'aria-disabled="true" tabindex="-1"'}>
        <img class="ico" src="${asset('icon-milites')}" alt="">MILITES</a>
      <button class="pill" type="button" data-modal="legions">
        <img class="ico" src="${asset('icon-legiones')}" alt="">LEGIONES</button>
      <button class="pill" type="button" data-modal="notifications">
        <img class="ico" src="${asset('icon-nuntii')}" alt="">NUNTII${
  waiting ? `<span class="badge">${waiting}</span>` : ''}</button>
    </nav>
    <div class="wallet">
      <img class="avatar" src="${asset('avatar')}" alt="the operator">
      <span class="denarii" title="recorded job cost (USD)">
        <img class="ico" src="${asset('icon-coin')}" alt="">${cost.toFixed(2)}</span>
      <span class="status" title="${healthy}/${projects.length} projects read cleanly">
        <span class="status-label">STATUS</span>
        <span class="meter"><i style="width:${projects.length
    ? Math.round(100 * healthy / projects.length) : 0}%"></i></span>
      </span>
    </div>
  </header>`;
}

function notificationsPill() {
  const waiting = allWaiting().length;
  return `<button class="notif-pill" type="button" data-modal="notifications">
    <img class="ico" src="${asset('icon-bell')}" alt="">NOTIFICATIONS${
  waiting ? `<span class="badge">${waiting}</span>` : ''}</button>`;
}

function helpButton() {
  return `<button class="help-btn" type="button" data-modal="help">
    <img src="${asset('mascot-eagle')}" alt="">HELP</button>`;
}

/* ------------------------------------------------------------------ camp */

function renderCamp() {
  const projects = state.data.projects || [];
  app.innerHTML = `<div class="camp ${projects.length > 8 ? 'crowded' : ''}">
    <div class="camp-bg" role="presentation"></div>
    ${chrome({ active: 'castra' })}
    <div class="camp-stage" id="camp-stage" aria-label="the camp"></div>
    ${projects.length ? '' : emptyCamp()}
    ${notificationsPill()}
    ${helpButton()}
    ${state.data.demo ? '<span class="demo-badge">DEMO · fake data</span>' : ''}
  </div>`;
  const stage = $('#camp-stage');
  stage.innerHTML = projects.map((project, index) => tentNode(project, index)).join('');
  requestAnimationFrame(() => layoutTents(projects));
}

function emptyCamp() {
  return `<div class="empty-camp">
    <img src="${asset('tent')}" alt="">
    <h2>No legions yet. Plant the first standard.</h2>
    <p>Station a centuria with <code>legio add &lt;path&gt;</code>, then come back.</p>
  </div>`;
}

function tentNode(project, index) {
  const c = counts(project);
  const broken = !project.ok;
  const art = broken ? 'tent-warped'
    : (hash01(project.name) > 0.62 ? (hash01(project.name) > 0.81 ? 'tent-alt-1' : 'tent-alt-2') : 'tent');
  return `<button class="tent ${broken ? 'broken' : ''}" type="button"
      data-open="${esc(project.name)}"
      aria-label="Open the tent of ${esc(project.name)}"
      title="${broken ? esc(project.error || 'cannot read this project') : ''}">
    <img class="tent-art" src="${asset(art)}" alt="">
    <span class="tent-banner">
      <span class="legion-line">
        <span class="legion-no">LEGIO ${roman(index + 1)}</span>
        <span class="legion-name">${esc(project.name)}</span>
      </span>
      <span class="tent-counts ${broken ? 'broken-tag' : ''}">${broken
    ? 'cannot read'
    : `<b>${c.active}</b> active · <b>${c.waiting}</b> waiting · <b>${c.done}</b> done`}</span>
    </span>
  </button>`;
}

function layoutTents(projects) {
  const stage = $('#camp-stage');
  if (!stage || !projects) return;
  const width = stage.clientWidth;
  const height = stage.clientHeight;
  if (!width || !height) return;
  const n = projects.length;
  if (!n) return;
  const narrow = window.matchMedia('(max-width: 940px)').matches;
  const oneColumn = narrow && width < 480;
  const cols = narrow
    ? (n <= 1 || oneColumn ? 1 : 2)
    : (n <= 4 ? n : n <= 8 ? 4 : n <= 15 ? 5 : 6);
  const rows = Math.ceil(n / cols);
  const x0 = width * (narrow ? 0.04 : 0.07);
  const x1 = width * (narrow ? 0.96 : 0.93);
  const y0 = height * (narrow ? 0.05 : 0.36);
  const y1 = height * (narrow ? 0.95 : 0.90);
  const cellW = (x1 - x0) / cols;
  const cellH = (y1 - y0) / rows;
  let tentH = Math.min(cellH * (narrow ? 0.84 : 0.80),
    cellW / (narrow ? 1.06 : 1.12), height * 0.38);
  tentH = Math.max(narrow ? 96 : 112, tentH);
  $$('.tent', stage).forEach((node, index) => {
    const project = projects[index];
    const col = index % cols;
    const row = Math.floor(index / cols);
    const jx = (hash01(project.name) - 0.5) * cellW * 0.16;
    const jy = (hash01(`${project.name}·y`) - 0.5) * cellH * 0.10;
    const cx = x0 + (col + 0.5) * cellW + jx;
    const bottom = y0 + (row + 0.9) * cellH + jy;
    const w = tentH * 1.06;
    node.style.height = `${tentH}px`;
    node.style.left = `${cx - w / 2}px`;
    node.style.top = `${bottom - tentH}px`;
    node.style.setProperty('--tent-h', `${tentH}px`);
  });
}

/* ------------------------------------------------------------------ tent */

function renderTentError(project) {
  app.innerHTML = `<div class="tent-view">
    <div class="tent-bg" role="presentation"></div>
    ${chrome({ active: 'castra', project })}
    <div class="tent-error">
      <div class="error-card">
        <img src="${asset('tent-warped')}" alt="">
        <h1>The messenger lost the way.</h1>
        <p>This tent could not be read:
          <code>${esc(project.error || 'unknown error')}</code></p>
        <a class="back" href="#/">← back to the camp</a>
      </div>
    </div>
    ${helpButton()}
    ${state.data.demo ? '<span class="demo-badge">DEMO · fake data</span>' : ''}
  </div>`;
}

function renderTent(project) {
  if (!project.ok) { renderTentError(project); return; }
  const live = project.live;
  const onDuty = live && !live.stale && live.roles && live.roles.length
    ? live.roles[0] : null;
  const workingJob = live && live.job
    ? (project.jobs || []).find((job) => job.id === live.job) : null;
  const lanes = { todo: [], doing: [], done: [] };
  for (const job of project.jobs || []) {
    if (job.terminal) lanes.done.push(job);
    else if (job.waiting) lanes.todo.push(job);
    else lanes.doing.push(job);
  }

  app.innerHTML = `<div class="tent-view">
    <div class="tent-bg" role="presentation"></div>
    ${chrome({ active: 'castra', project })}
    <div class="tent-name"><span>LEGIO ${
  roman(state.data.projects.findIndex((entry) => entry.name === project.name) + 1)
}</span> · ${esc(project.name)}</div>
    <main class="tent-layout">
      <section class="board-wrap" aria-label="Tabula Operum">
        <img class="board-art" src="${asset('board')}" alt="">
        <div class="board-title" aria-hidden="true">TABULA OPERUM</div>
        <div class="board-labels" aria-hidden="true">
          <span>AD FACIENDUM</span><span>IN CURSU</span><span>FACTUM</span>
        </div>
        <div class="board-lanes">
          ${lane('todo', lanes.todo)}
          ${lane('doing', lanes.doing)}
          ${lane('done', lanes.done)}
        </div>
      </section>
      <section class="role-stage" aria-label="the working role">
        ${roleStage(project, onDuty, workingJob)}
      </section>
    </main>
    ${castStrip(project, onDuty)}
    ${helpButton()}
    ${state.data.demo ? '<span class="demo-badge">DEMO · fake data</span>' : ''}
  </div>`;
}

function lane(kind, jobs) {
  return `<div class="lane lane-${kind}">
    <div class="notes">${jobs.length
    ? jobs.map(note).join('')
    : '<span class="lane-empty">nothing here</span>'}</div>
  </div>`;
}

function note(job) {
  const marks = Object.entries(job.reviews || {}).map(([role, verdict]) => {
    const short = role.slice(0, 3).toUpperCase();
    return `<i class="mark ${verdict === 'PASS' ? 'pass' : 'changes'}"
      title="${esc(role)}: ${esc(verdict)}">${short}</i>`;
  }).join('');
  return `<button class="note" type="button" data-job="${esc(job.id)}">
    <span class="note-title">${esc(job.title)}</span>
    <span class="note-meta">r${esc(job.round ?? 0)}/${esc(job.round_limit ?? 3)}${
  job.gate ? ` · gate ${job.gate === 'PASS' ? '✓' : '✗'}` : ''}</span>
    ${marks ? `<span class="note-marks">${marks}</span>` : ''}
    ${job.cost_usd ? `<span class="note-cost">${Number(job.cost_usd).toFixed(2)}</span>` : ''}
  </button>`;
}

function roleStage(project, onDuty, job) {
  if (onDuty && ROLE_FILES.includes(onDuty)) {
    const title = roleTitle(onDuty, project.cast);
    const verb = ROLE_VERB[onDuty] || 'working';
    return `<div class="worker-wrap">
      <div class="glow" aria-hidden="true"></div>
      <img class="hearts" src="${asset('hearts-sparkles')}" alt="" aria-hidden="true">
      <img class="worker" src="${asset(`role-${onDuty}-working`)}" alt="${esc(title)} at work">
      <div class="bubble"><b>${esc(title)}</b> is ${esc(verb)}${
  job ? `<span class="bubble-job">${esc(job.title)}</span>` : ''}</div>
    </div>`;
  }
  const lastSeen = project.live && project.live.stale && project.live.roles?.length
    ? `Last seen <b>${esc(roleTitle(project.live.roles[0], project.cast))}</b> ${
      ago(project.live.age_seconds)} ago.`
    : 'The tent is quiet. Nobody is sweating yet.';
  return `<div class="worker-wrap quiet">
    <img class="desk" src="${asset('desk')}" alt="">
    <p class="quiet-copy">${lastSeen}</p>
  </div>`;
}

function castStrip(project, onDuty) {
  const cast = project.cast && project.cast.length
    ? project.cast
    : ROLE_FILES.map((role) => ({ role, title: ROLE_FALLBACK[role], function: '' }));
  return `<div class="cast-strip" aria-label="the cast">
    ${cast.map((entry) => {
    const role = entry.role;
    const file = ROLE_FILES.includes(role) ? role : 'fabri';
    const on = role === onDuty;
    return `<button class="chip ${on ? 'on-duty' : ''}" type="button"
        data-role-detail="${esc(role)}" title="${esc(entry.duty || entry.function || '')}">
      <img src="${asset(`role-${file}`)}" alt="">
      <span class="chip-name">${esc(roleTitle(role, project.cast))}</span>
      <span class="chip-state">${on ? 'on duty' : 'resting'}</span>
    </button>`;
  }).join('')}
  </div>`;
}

/* ------------------------------------------------------------------ cast */

function renderCast(project) {
  const on = project.live && !project.live.stale ? project.live.roles || [] : [];
  const cast = project.cast && project.cast.length
    ? project.cast
    : ROLE_FILES.map((role) => ({ role, title: ROLE_FALLBACK[role], function: '', duty: '' }));
  app.innerHTML = `<div class="cast-page">
    <div class="tent-bg" role="presentation"></div>
    ${chrome({ active: 'milites', project })}
    <main class="cast-wrap">
      <a class="back" href="#/legion/${enc(project.name)}">← back to the tent</a>
      <h1 class="cast-title">MILITES <span>· the cast of ${esc(project.name)}</span></h1>
      <div class="cast-grid">
        ${cast.map((entry) => `
        <article class="cast-card ${on.includes(entry.role) ? 'on-duty' : ''}">
          <img class="cast-art" src="${asset(`role-${ROLE_FILES.includes(entry.role) ? entry.role : 'fabri'}`)}"
               alt="${esc(roleTitle(entry.role, project.cast))}">
          <h2>${esc(roleTitle(entry.role, project.cast))}</h2>
          <p class="cast-function">${esc(entry.function || 'role')}${
  entry.tier ? ` · ${esc(entry.tier)}` : ''}</p>
          <p class="cast-duty">${esc(entry.duty || '')}</p>
          <span class="cast-state">${on.includes(entry.role) ? 'on duty' : 'resting'}</span>
        </article>`).join('')}
      </div>
    </main>
    ${helpButton()}
    ${state.data.demo ? '<span class="demo-badge">DEMO · fake data</span>' : ''}
  </div>`;
}

/* ---------------------------------------------------------------- modals */

function openModal(html) {
  modal.hidden = false;
  $('.modal-body').innerHTML = html;
}

function closeModal() {
  modal.hidden = true;
  $('.modal-body').innerHTML = '';
}

function showLegions() {
  const projects = state.data?.projects || [];
  openModal(`<h2 class="modal-title">LEGIONES · every centuria</h2>
    <ul class="modal-list">${projects.map((project) => {
    const c = counts(project);
    return `<li><a href="#/legion/${enc(project.name)}"><b>${esc(project.name)}</b>
      <span>${project.ok ? `${c.active} active · ${c.waiting} waiting · ${c.done} done`
    : `cannot read: ${esc(project.error)}`}</span></a></li>`;
  }).join('')}</ul>
    ${projects.length ? '' : '<p>No legions yet.</p>'}`);
}

function showNotifications() {
  const waiting = allWaiting();
  openModal(`<h2 class="modal-title">NUNTII · what waits on you</h2>
    ${waiting.length
    ? `<ul class="modal-list">${waiting.map(({ project, job }) => `
        <li><a href="#/legion/${enc(project.name)}"><b>${esc(project.name)} · ${esc(job.title)}</b>
        <span>${esc(job.human_reason || job.stage)}</span></a></li>`).join('')}</ul>`
    : '<p class="modal-empty">Nothing needs you right now. Enjoy the quiet.</p>'}`);
}

function showHelp() {
  openModal(`<h2 class="modal-title">HELP · how the camp works</h2>
    <div class="modal-prose">
      <p>Each <b>tent</b> is one centuria (one project). The banner over a tent names
      the legion; the line under it counts its jobs.</p>
      <p>Inside a tent, the big board is the <b>TABULA OPERUM</b>:
      <b>AD FACIENDUM</b> (waiting on a human), <b>IN CURSU</b> (being worked),
      <b>FACTUM</b> (finished). A note is one job.</p>
      <p>The role at the desk is <b>on duty</b>: whichever role is running right now,
      with its job named in the bubble. If nobody is running, the desk is empty.</p>
      <p>Press <kbd>M</kbd> for the cast, <kbd>L</kbd> for the legions,
      <kbd>N</kbd> for what waits on you, <kbd>Esc</kbd> to close a panel.</p>
    </div>`);
}

function showJob(jobId) {
  let found = null;
  for (const project of state.data?.projects || []) {
    const job = (project.jobs || []).find((entry) => entry.id === jobId);
    if (job) { found = { project, job }; break; }
  }
  if (!found) return;
  const { project, job } = found;
  const reviews = Object.entries(job.reviews || {});
  openModal(`<h2 class="modal-title">${esc(job.title)}</h2>
    <p class="modal-sub">${esc(project.name)} · ${esc(job.id)} · #${esc(job.issue)}</p>
    <dl class="modal-facts">
      <div><dt>stage</dt><dd>${esc(job.stage)}</dd></div>
      <div><dt>round</dt><dd>${esc(job.round)}/${esc(job.round_limit)}</dd></div>
      <div><dt>gate</dt><dd>${esc(job.gate || '—')}</dd></div>
      <div><dt>PR</dt><dd>${job.pr ? `#${esc(job.pr)}` : '—'}</dd></div>
      <div><dt>cost</dt><dd>${Number(job.cost_usd || 0).toFixed(2)}</dd></div>
      <div><dt>waiting on</dt><dd>${esc(job.human_reason || '—')}</dd></div>
    </dl>
    ${reviews.length ? `<h3 class="modal-h3">reviews</h3><ul class="modal-list">${
  reviews.map(([role, verdict]) => `<li><b>${esc(role)}</b><span>${esc(verdict)}</span></li>`).join('')}</ul>` : ''}
    <p><a class="modal-link" href="#/legion/${enc(project.name)}">open the tent →</a></p>`);
}

function showRole(role) {
  const project = state.data?.projects?.find((p) => p.name === state.route.name);
  const cast = project?.cast || [];
  const entry = cast.find((item) => item.role === role);
  if (!entry) return;
  openModal(`<h2 class="modal-title">${esc(roleTitle(role, cast))}</h2>
    <p class="modal-sub">${esc(entry.function)}${entry.tier ? ` · ${esc(entry.tier)}` : ''}</p>
    <p class="modal-prose">${esc(entry.duty || '')}</p>`);
}

/* --------------------------------------------------------------- renderer */

function parseRoute() {
  const raw = decodeURIComponent(location.hash.replace(/^#/, ''));
  if (!raw || raw === '/') return { view: 'camp' };
  let match = raw.match(/^\/legion\/([^/]+)\/cast$/);
  if (match) return { view: 'cast', name: match[1] };
  match = raw.match(/^\/legion\/([^/]+)$/);
  if (match) return { view: 'tent', name: match[1] };
  return { view: 'camp' };
}

function render() {
  if (!state.data) return;
  state.route = parseRoute();
  if (state.route.view === 'camp') {
    renderCamp();
    return;
  }
  const project = state.data.projects.find((p) => p.name === state.route.name);
  if (!project) { location.hash = '#/'; return; }
  if (!project.ok) { renderTentError(project); return; }
  if (state.route.view === 'cast') renderCast(project);
  else renderTent(project);
}

function fingerprint(data) {
  return JSON.stringify({
    demo: data.demo,
    projects: (data.projects || []).map((project) => ({
      name: project.name,
      ok: project.ok,
      error: project.error,
      jobs: (project.jobs || []).map((job) => [job.id, job.stage, job.round,
        job.waiting, job.active, job.terminal, job.gate, job.reviews,
        job.cost_usd, job.human_reason]),
      live: project.live ? [project.live.roles, project.live.job, project.live.stale] : null,
      cast: (project.cast || []).map((entry) => [entry.role, entry.title, entry.duty]),
    })),
  });
}

async function pollOnce() {
  try {
    const response = await fetch('/api/camp', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const next = fingerprint(data);
    state.data = data;
    if (next !== state.fingerprint) {
      state.fingerprint = next;
      render();
    }
  } catch (error) {
    document.body.classList.add('offline');
    return;
  }
  document.body.classList.remove('offline');
}

/* --------------------------------------------------------------- events */

document.addEventListener('click', (event) => {
  const tent = event.target.closest('[data-open]');
  if (tent) {
    location.hash = `#/legion/${enc(tent.dataset.open)}`;
    return;
  }
  const modalButton = event.target.closest('[data-modal]');
  if (modalButton) {
    const which = modalButton.dataset.modal;
    if (which === 'legions') showLegions();
    else if (which === 'notifications') showNotifications();
    else showHelp();
    return;
  }
  if (event.target.closest('.modal-close') || event.target === modal) {
    closeModal();
    return;
  }
  const noteButton = event.target.closest('[data-job]');
  if (noteButton) { showJob(noteButton.dataset.job); return; }
  const roleButton = event.target.closest('[data-role-detail]');
  if (roleButton) showRole(roleButton.dataset.roleDetail);
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') { closeModal(); return; }
  if (event.target.closest('input, textarea')) return;
  const project = state.data?.projects?.find((p) => p.name === state.route.name);
  if (event.key === 'm' || event.key === 'M') {
    if (project) location.hash = `#/legion/${enc(project.name)}/cast`;
  } else if (event.key === 'l' || event.key === 'L') showLegions();
  else if (event.key === 'n' || event.key === 'N') showNotifications();
});

window.addEventListener('hashchange', () => { closeModal(); render(); });
window.addEventListener('resize', () => {
  if (state.route.view === 'camp') layoutTents(state.data?.projects);
});

/* ------------------------------------------------------------------- boot */

render();
pollOnce();
setInterval(pollOnce, 2500);
