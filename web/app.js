// On-call Brain UI. Three views:
//   Incidents  an inbox (list left, the open incident right). An incident leads with the answer: likely cause with a
//              confidence label, what broke, who is paged, the fix, Confirm / Wrong cause; "Show me why" is the
//              incident subgraph, the three agents' steps and the Cypher behind every call.
//   Ask        company questions answered from the graph, as a chat with source chips.
//   Connect    how to plug it in: the alert webhook, MCP (Claude Code), Slack, your own data.
// No build step. Every piece of data reaches the DOM as text (see h()), never as HTML.

import * as G from './graph.js';

const { kindOf, short, names } = G;
const params = new URLSearchParams(location.search);
const OFFLINE = params.has('offline'); // ?offline=1 replays web/fixtures (recorded from the real code)
const STEP_MS = Number(params.get('step_ms')) || 700; // fastest pace at which steps appear (a model is slower anyway)
const ROLES = ['triage', 'investigator', 'comms'];
const ROLE_N = { triage: 1, investigator: 2, comms: 3 };
const ROLE_JOB = { triage: 'Finds who is hurt and pages on-call', investigator: 'Tests every recent change against the graph',
  comms: 'Writes the update, with sources' };
const SCENARIO_NOTE = {
  1: 'A bad config change hides among four other recent changes.',
  2: 'The same failure again. Confirm the first fix and memory solves this one in a few steps.',
  3: 'Three services alert within four minutes. One shared cause, or three?',
};
const EXAMPLES = ['Who owns kafka?', 'Why was legacy-billing retired?', 'Why was the payments gateway pool lowered?',
  'How do I roll back a bad deploy on cart?', 'What happened to auth?', 'Who knows payments-gw?'];
const MODELS = { 'claude-opus-5-5': 'Claude Opus 5.5', 'claude-sonnet-5-5': 'Claude Sonnet 5.5',
  'claude-haiku-5-5': 'Claude Haiku 5.5', 'claude-fable-5-1': 'Claude Fable 5.1', rules: 'Rules' };
const SYMPTOM_WORD = { latency: 'slowdown', errors: 'errors', saturation: 'saturation' };
const KIND_WORD = { Doc: 'Doc', Ticket: 'Ticket', Message: 'Chat', Change: 'Change', Person: 'Person', Runbook: 'Runbook',
  design: 'Design', decision: 'Decision', postmortem: 'Postmortem', runbook: 'Runbook', chat: 'Chat', ticket: 'Ticket',
  status_update: 'Status update', service: 'Service', team: 'Team', person: 'Person', change: 'Change', incident: 'Incident',
  message: 'Chat', doc: 'Doc' };

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const enc = encodeURIComponent;
const plural = (n, word) => `${n} ${n === 1 ? word : word === 'query' ? 'queries' : `${word}s`}`;
const ist = (at) => new Date(at * 1000).toLocaleString('en-GB', {
  timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).replace(',', '');
// Human text never shows graph id prefixes, ASCII arrows or the word "hypothesis".
const plain = (text) => String(text ?? '').replace(/\b(svc|chg|inc|hyp|rb|alert|person|team|doc|ticket|msg|ev):/g, '')
  .replace(/ -> /g, ' → ').replace(/\bhypotheses\b/g, 'suspects').replace(/\bhypothesis\b/g, 'suspect');
const companyLabel = () => (state.tenant === (state.health?.default_tenant || 'acme') ? 'Acme (demo company)' : state.tenant);
const idIn = (text, kind) => (String(text || '').match(new RegExp(`\\b${kind}:[A-Za-z0-9_.:-]+`)) || [null])[0];
const modelName = (by) => MODELS[by] || by || 'Rules';
const kindWord = (k) => KIND_WORD[k] || String(k || '').replace(/_/g, ' ');
const minutesBetween = (a, b) => Math.round(Math.abs(a - b) / 60);
const mobile = () => matchMedia('(max-width: 900px)').matches;

// running: an agent run is streaming; graphOwner: whose picture the graph shows (a run, 'ask', or null)
const state = { tenant: '', health: null, graph: null, alerts: [], runs: [], current: null, view: 'incidents',
  tab: 'answer', running: false, skip: false, chat: [], graphOwner: null, asking: false };

// ---------- DOM: strings become text nodes, so API data is never parsed as HTML ----------
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat(Infinity)) if (k != null && k !== false) el.append(k instanceof Node ? k : String(k));
  return el;
}
const set = (id, ...kids) => $(id).replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
const chip = (text, cls = '') => h('span', { class: `chip-static ${cls}` }, text);
const pathChips = (ids) => h('span', { class: 'path' }, ids.map((id, i) => [i ? h('span', { class: 'arrow' }, '→') : null,
  h('span', { class: 'hop' }, short(id))]));
const skel = (w = '70%') => h('span', { class: 'skel', style: `width:${w}` });

let toastTimer;
function toast(text, isError = false) {
  const el = $('toast');
  el.textContent = text;
  el.classList.toggle('error', isError);
  el.setAttribute('role', isError ? 'alert' : 'status');
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 10000 : 5000);
}
const announce = (text) => { $('sr-status').textContent = text; };

// ---------- API ----------
const T = () => `/api/tenants/${enc(state.tenant)}`;

async function api(method, path, body) {
  if (OFFLINE) return fixture(path);
  const r = await fetch(path, { method, headers: body ? { 'content-type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `${r.status} ${r.statusText}`);
  return data;
}

const FIXTURES = [[/\/health$/, 'health'], [/\/alerts$/, 'alerts'], [/\/graph/, 'graph'], [/\/resolve$/, 'resolve'],
  [/checkout-latency\/respond/, 'act1'], [/refunds-latency\/respond/, 'act2'], [/subscriptions-latency\/respond/, 'act3']];

async function fixture(path) {
  const p = decodeURIComponent(path).split('?')[0];
  if (p.endsWith('/reset')) return { tenant: state.tenant, status: 'restored' };
  const hit = FIXTURES.find(([re]) => re.test(p));
  if (!hit) throw new Error(`this needs the live server (no recording of ${p})`);
  await sleep(200);
  return (await fetch(new URL(`fixtures/${hit[1]}.json`, import.meta.url))).json(); // works on any static host
}

// An agent run as events: live, the NDJSON lines of /respond/stream as the agents record each step; offline, the
// recorded run replayed as the same events.
async function* runEvents(path) {
  if (OFFLINE) {
    const { ablation, ...result } = await fixture(path);
    for (const step of result.steps) yield { step };
    yield { result };
    if (ablation) yield { ablation };
    return;
  }
  const r = await fetch(path, { method: 'POST' });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(typeof d.detail === 'string' ? d.detail : `${r.status} ${r.statusText}`);
  }
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += value;
    for (let i; (i = buf.indexOf('\n')) >= 0; buf = buf.slice(i + 1)) {
      if (buf.slice(0, i).trim()) yield JSON.parse(buf.slice(0, i));
    }
  }
}

// ---------- runs and incidents ----------
// A run is one agent response to an alert, kept for this page's lifetime. An incident handled before the page was
// opened is loaded from the graph instead (GET /incidents/{id}): its outcome and steps, without the live trace.
function newRun(alert, alerts, act) {
  return { alert, alerts, act, home: alert.service, incident: null, steps: [], res: null, ablation: null,
    resolved: null, done: false, error: null, folded: alerts.length < 2, showAlt: false,
    touched: G.empty(), cause: G.empty() };
}

const outcomeOf = (cur) => cur?.res?.outcome || null;

// cur: a run or stored incident (may be null); row: the inbox row from GET /alerts (status, has_cause, has_update).
function statusOf(cur, row) {
  if (cur?.error) return ['error', 'Failed'];
  if (cur && !cur.done) return ['working', 'Investigating'];
  if (cur?.resolved || row?.status === 'resolved' || cur?.status === 'resolved') return ['confirmed', 'Confirmed'];
  const o = outcomeOf(cur);
  if (o) return o.root_cause ? ['found', 'Cause found'] : ['human', 'Needs a human'];
  if (row?.status) return row.has_cause ? ['found', 'Cause found'] : row.has_update ? ['human', 'Needs a human'] : ['working', 'Investigating'];
  return ['new', 'New'];
}

function scenarios() { // the demo company's scripted alerts, grouped by act; the act's last alert is the one answered
  const by = new Map();
  for (const a of state.alerts) if (a.act != null) (by.get(a.act) || by.set(a.act, []).get(a.act)).push(a);
  return [...by].sort((x, y) => x[0] - y[0]).map(([act, alerts]) => {
    alerts.sort((x, y) => x.at - y.at);
    return { act, alerts, trigger: alerts.at(-1) };
  });
}
const fired = (sc) => !!sc.trigger.incident || state.runs.some((r) => r.act === sc.act);
const nextScenario = () => scenarios().find((s) => !fired(s));
const scenarioTitle = (sc) => (sc.alerts.length > 1 ? 'Three alerts at once'
  : `${short(sc.trigger.service)} is ${sc.trigger.symptom === 'latency' ? 'slow' : `throwing ${sc.trigger.symptom}`}`);

function inboxItems() {
  const items = new Map();
  for (const a of state.alerts) {
    if (!a.incident) continue;
    if (!items.has(a.incident)) items.set(a.incident, { incident: a.incident, status: a.status, has_cause: a.has_cause, has_update: a.has_update, alerts: [] });
    items.get(a.incident).alerts.push(a);
  }
  const rows = [...items.values()];
  for (const run of state.runs) {
    const it = run.incident && items.get(run.incident);
    if (it) it.run = run;
    else if (run.folded) rows.push({ incident: run.incident, alerts: run.alerts, run });
    else for (const a of run.alerts) rows.push({ incident: null, alerts: [a], run }); // a storm before correlation
  }
  // Alerts raised through the webhook that nobody has run the agents on yet.
  for (const a of state.alerts) {
    if (!a.incident && a.act == null && !state.runs.some((r) => r.alert.id === a.id)) rows.push({ fresh: a, alerts: [a] });
  }
  const latest = (it) => Math.max(...it.alerts.map((a) => a.at));
  return rows.sort((x, y) => latest(y) - latest(x));
}

// ---------- header: simulate menu ----------
function closeMenus() {
  for (const id of ['simulate-menu']) {
    $(id).hidden = true;
    $('btn-simulate').setAttribute('aria-expanded', 'false');
  }
}

function renderSimulateMenu() {
  const list = scenarios(), next = nextScenario();
  const items = list.map((sc) => {
    const done = fired(sc), isNext = sc.act === next?.act;
    return h('div', { class: `menu-item${isNext ? ' next' : ''}`, role: 'none' },
      h('div', { class: 'mi-text' }, h('b', {}, scenarioTitle(sc)), h('span', { class: 'muted small' }, SCENARIO_NOTE[sc.act] || '')),
      h('button', { class: isNext ? 'primary-btn' : 'ghost', role: 'menuitem', disabled: done || state.running,
        onclick: () => { closeMenus(); fire(sc.act); } }, done ? (OFFLINE ? 'Replayed ✓' : 'Simulated ✓') : OFFLINE ? 'Replay' : 'Simulate'));
  });
  const svcs = [...(state.graph?.nodes || [])].sort((a, b) => a.name.localeCompare(b.name));
  const custom = OFFLINE ? null : h('details', { class: 'custom' },
    h('summary', {}, 'Raise a custom alert'),
    h('form', { class: 'custom-form', onsubmit: (e) => { e.preventDefault(); closeMenus(); raiseCustom(e.target); } },
      h('label', {}, 'Service', h('select', { name: 'service', required: true }, svcs.map((n) => h('option', { value: n.id }, n.name)))),
      h('label', {}, 'Symptom', h('select', { name: 'symptom' }, ['latency', 'errors', 'saturation'].map((s) => h('option', { value: s }, s)))),
      h('label', {}, 'Alert name', h('input', { name: 'name', maxlength: 200, placeholder: 'cart 5xx above 1%', required: true })),
      h('button', { class: 'primary-btn', disabled: state.running }, 'Raise and investigate')));
  set('simulate-menu', h('p', { class: 'menu-head' }, 'Simulate an incident', h('span', { class: 'muted small' }, 'Synthetic company, real agents')),
    items, custom,
    h('div', { class: 'menu-foot' },
      h('span', {}, `Steps chosen by ${plannerLabel()} · ${companyLabel()}`),
      h('button', { class: 'ghost', disabled: state.running, onclick: () => { closeMenus(); doReset(); } }, 'Reset demo company')));
}

function plannerLabel() {
  const p = state.health?.planner || '';
  return /deterministic|mock/i.test(p) ? 'the rule planner' : modelName(p.split(' ')[0]);
}
const modelDecides = () => !/deterministic|mock/i.test(state.health?.planner || 'mock');

// ---------- rendering: inbox and landing ----------
function renderInbox() {
  const rows = inboxItems();
  const open = rows.filter((it) => statusOf(it.run, it)[0] !== 'confirmed').length;
  set('inbox-counts', rows.length ? `${open} open · ${rows.length - open} confirmed` : '');
  set('inbox', rows.length ? rows.map((it) => {
    const [cls, label] = statusOf(it.run, it);
    const trigger = it.run?.alert || it.fresh || it.alerts.find((a) => `inc:${short(a.id)}` === it.incident) || it.alerts.at(-1);
    const many = it.alerts.length > 1;
    const selected = state.current && (state.current === it.run || (it.incident && state.current.incident === it.incident));
    const open = () => (it.run ? openRun(it.run) : it.fresh ? runAlert(it.fresh, [it.fresh], null) : openStored(it.incident));
    return h('li', {},
      h('button', { class: `inbox-item${selected ? ' selected' : ''}`, title: trigger.name, onclick: open, 'aria-current': selected ? 'true' : null },
        h('span', { class: `dot ${cls}` }),
        h('span', { class: 'ii-main' },
          h('span', { class: 'ii-title' }, many ? `${it.alerts.length} alerts, 1 incident` : trigger.name),
          h('span', { class: 'ii-sub' }, many ? it.alerts.map((a) => short(a.service)).join(', ') : short(trigger.service),
            ` · ${ist(trigger.at)}`)),
        h('span', { class: `status-pill ${cls}` }, label)));
  }) : [h('li', { class: 'inbox-empty' }, h('p', {}, h('b', {}, 'No open incidents.')),
    h('p', { class: 'muted small' }, 'Alerts from your monitoring land here. ',
      h('button', { class: 'link-btn', onclick: () => fireNext() }, 'Simulate one'), ', or ',
      h('button', { class: 'link-btn', onclick: () => showView('connect') }, 'connect your alerts'), '.'))]);
  set('panel-foot', OFFLINE ? 'Recorded replay of real runs (steps chosen by Claude Opus 5.5); no database behind this page.'
    : state.health ? [h('span', { class: `dot ${state.health.falkordb ? 'confirmed' : 'error'}` }),
      ` FalkorDB ${state.health.falkordb ? 'connected' : 'down'} · steps chosen by ${plannerLabel()} · ${companyLabel()}`] : '');
}

function renderLanding() {
  const next = nextScenario(), g = state.graph;
  const step = (n, title, text) => h('li', {}, h('span', { class: 'how-n' }, n), h('div', {}, h('b', {}, title), h('p', {}, text)));
  set('landing', h('div', { class: 'hero' },
    h('h2', {}, 'What broke, why, who’s paged, and the fix.'),
    h('p', { class: 'lede' }, 'When an alert fires, three agents read your company graph: what depends on what, who owns it, '
      + 'what changed, what fixed it last time. Confirm the cause and it remembers.'),
    h('div', { class: 'cta-row' },
      h('button', { class: 'cta', disabled: state.running || !state.alerts.length, onclick: () => fireNext() },
        next ? `${OFFLINE ? 'Replay a recorded incident' : 'Simulate an incident'}: ${scenarioTitle(next).toLowerCase()}`
          : 'All demo incidents handled. Reset demo company'),
      h('button', { class: 'ghost tall', onclick: () => showView('connect') }, 'Connect your alerts')),
    h('ol', { class: 'how' },
      step('1', 'An alert fires', 'From your monitoring through a webhook, or simulated here.'),
      step('2', 'Three agents investigate on the graph', 'Triage finds who is hurt and pages on-call. The investigator tests every '
        + 'recent change on the dependency paths. Comms writes the update, with sources.'),
      step('3', 'You confirm, it remembers', 'Your call becomes memory in the graph, so the next similar incident is solved in a few steps.')),
    g ? h('p', { class: 'muted small facts' }, `Demo company: ${g.nodes.length} services, ${new Set(g.nodes.map((n) => n.team)).size} teams, `
      + `${g.edges.length} dependencies, all synthetic · one FalkorDB graph per company`) : null));
}

// ---------- rendering: one incident ----------
function titleOf(cur) {
  return cur.alerts.length > 1 ? `${cur.alerts.length} alerts, 1 incident` : cur.alert.name;
}

function stormLine(cur) {
  const o = outcomeOf(cur), st = o?.storm;
  if (!st && cur.alerts.length < 2) return null;
  const svcs = [...new Set([...(st?.alerts || []).map((a) => a.service), ...cur.alerts.map((a) => a.service), cur.home])].map(short);
  const list = svcs.length > 1 ? `${svcs.slice(0, -1).join(', ')} and ${svcs.at(-1)}` : svcs[0];
  const shared = (st?.shared || []).slice(0, 2).map((s) => short(s.service));
  return h('p', { class: 'storm-line' }, h('b', {}, `${svcs.length} alerts, 1 incident: `), `${list} fired within minutes`,
    shared.length ? ` and share ${shared.join(' and ')}.` : '.');
}

function renderHead(cur) {
  const [cls, label] = statusOf(cur, cur.status);
  $('inc-status').className = `status-pill ${cls}`;
  $('inc-status').textContent = label;
  $('inc-title').textContent = titleOf(cur);
  set('inc-sub', `${short(cur.home)} · ${ist(cur.alert.at)}`, stormLine(cur));
  $('btn-back').hidden = !mobile();
  document.querySelector('.incidents').classList.toggle('has-current', true);
}

// What the run knows so far (live) or knew at the end (final): one shape for both, so the answer card can render
// while the agents work and fill in as steps land.
function facts(cur) {
  const o = outcomeOf(cur), steps = cur.steps || [];
  const data = (tool) => steps.filter((s) => s.tool === tool && s.data).map((s) => s.data);
  const checks = data('check_hypothesis');
  const suspects = new Map();
  for (const d of data('hypothesize_from_memory')) for (const s of Array.isArray(d) ? d : []) suspects.set(s.change, { ...s, source: 'memory' });
  for (const d of data('propose_hypotheses')) for (const s of d.suspects || []) suspects.set(s.change, s);
  for (const c of checks) suspects.set(c.change, { ...suspects.get(c.change), ...c });
  const conclude = data('conclude')[0];
  const broke = o ? o.blast_radius.map(short) : [...new Set(data('blast_radius').flat().map((r) => short(r.service)))];
  const paged = o ? o.paged : data('page_on_call').filter((d) => d.person).map((d) => ({ ...d }));
  const rc = o ? o.root_cause : (conclude?.leading ? suspects.get(conclude.leading) : checks.find((c) => c.verdict === 'supports')) || null;
  const posted = data('post_update')[0];
  return {
    o, rc, suspects: [...suspects.values()], checks, broke, paged,
    atRisk: o ? o.at_risk.map(short) : [],
    runbook: o?.runbook || posted?.runbook || null,
    expert: o?.expert || posted?.expert || data('who_knows')[0]?.[0] || null,
    refuted: o ? o.refuted : [...suspects.values()].filter((s) => s.verdict === 'refutes'),
    recalled: o ? o.memory.recalled[0] : data('recall_similar')[0]?.find((r) => r.score >= 3) || null,
    solvedByMemory: !!o?.memory.solved_by_memory,
    sources: o?.sources || [],
    update: cur.resolved?.update_text || o?.update_text || posted?.text || null,
  };
}

function renderProgress(cur) {
  if (cur.done || cur.stored) return set('progress');
  const steps = cur.steps || [];
  const handed = new Set(steps.filter((s) => s.tool === 'handoff').map((s) => s.role));
  const working = ROLES.find((r) => !handed.has(r));
  const cells = ROLES.map((role) => {
    const mine = steps.filter((s) => s.role === role && s.tool !== 'handoff');
    const st = handed.has(role) ? 'done' : role === working ? 'working' : 'waiting';
    const last = mine.at(-1);
    const text = st === 'waiting' ? ROLE_JOB[role] : last ? stepResult(last) : 'Reading the incident board…';
    return h('div', { class: `cell ${st} ${role}` },
      h('div', { class: 'cell-head' }, h('span', { class: `role ${role}` }, `${ROLE_N[role]} ${role}`),
        h('span', { class: 'cell-state' }, st === 'done' ? '✓ done' : st === 'working' ? '● working' : '○ waiting')),
      h('p', {}, text));
  });
  const last = steps.at(-1);
  set('progress', h('div', { class: 'strip' }, cells),
    h('p', { class: 'live-line' }, h('span', { class: 'spinner' }),
      last ? [h('b', {}, `${last.role[0].toUpperCase()}${last.role.slice(1)}: `), plain(last.reason)] : 'Opening the incident…',
      h('button', { class: 'ghost', onclick: () => { state.skip = true; } }, 'Skip to answer')));
}

// The answer, in reading order: memory banner, verdict + confidence, actions, what broke / who's paged / fix,
// ruled out, the path, the Slack preview. Right rail: live suspects (while working), the change-log comparison,
// sources. Skeleton slots stand in for what the agents have not found yet.
function renderAnswer(cur) {
  const f = facts(cur), o = f.o, rc = f.rc, live = !cur.done && !cur.stored, conf = o?.confidence;
  const alertAt = cur.alert.at;
  const resolved = !!cur.resolved || cur.status === 'resolved';

  // Memory banner / line.
  const wo = cur.ablation?.without_memory;
  const memory = f.recalled && f.solvedByMemory
    ? h('div', { class: 'banner memory' },
      h('div', { class: 'banner-text' },
        h('b', {}, 'Seen this before. '), `“${f.recalled.title}” was fixed with `,
        h('b', {}, `“${f.recalled.runbook_title}”`), ', so the same fix was tried first.'),
      wo ? h('div', { class: 'bignums' },
        h('div', {}, h('span', { class: 'big' }, o.investigator_calls), h('span', { class: 'lbl' }, `steps instead of ${wo.investigator_calls}`)),
        h('div', {}, h('span', { class: 'big' }, o.hypotheses_checked), h('span', { class: 'lbl' }, `suspect${o.hypotheses_checked === 1 ? '' : 's'} tested instead of ${wo.hypotheses_checked}`)))
        : cur.act === 2 && !cur.ablation && !cur.stored ? h('span', { class: 'muted small' }, 'Replaying it without memory for comparison…') : null)
    : f.recalled && (o || cur.steps.some((s) => s.tool === 'propose_hypotheses'))
      ? h('p', { class: 'memory-line' }, h('b', {}, 'Seen something like this: '), `“${f.recalled.title}”. Its fix didn’t apply here, so the search widened.`)
      : null;

  // Verdict block.
  const kindOfChange = (k) => (k === 'deploy' ? 'Deploy' : k ? 'Config change' : 'Change');
  const label = resolved ? 'Cause confirmed' : live ? 'Leading suspect' : rc ? 'Likely cause' : 'No single cause yet';
  const chipText = resolved ? 'Confirmed by you'
    : conf && rc ? `${conf.label}${conf.level === 'high' && f.checks.length > 1 ? ` · ${f.refuted.length} of ${f.checks.length} suspects ruled out` : conf.level === 'confirmed' ? '' : ` · ${conf.why}`}`
    : null;
  const verdict = h('div', { class: `verdict ${resolved ? 'confirmed' : ''}` },
    h('p', { class: 'k' }, label),
    rc ? [h('h3', { class: 'cause-line' }, h('span', { class: 'cause-svc' }, short(rc.service)),
      plain(rc.summary?.toLowerCase().startsWith(short(rc.service).toLowerCase()) ? rc.summary.slice(short(rc.service).length) : ` · ${rc.summary}`)),
      h('p', { class: 'byline' }, `${kindOfChange(rc.kind)}${rc.author ? ` by ${rc.author}` : ''}`,
        rc.at ? ` · ${ist(rc.at)} · ${minutesBetween(rc.at, alertAt)} min before the alert` : ''),
      chipText ? h('span', { class: `conf ${resolved ? 'confirmed' : conf?.level || ''}` }, chipText) : null]
      : live ? [h('h3', { class: 'cause-line' }, skel('60%')), h('p', { class: 'byline' }, skel('40%'))]
        : [h('h3', { class: 'cause-line muted' }, 'No recent change explains this alert.'),
          h('p', { class: 'byline' }, 'A human should look. The suspects the agents tested are listed below.')]);

  // Actions.
  // Other changes a human might name instead: the suspects that lost, plus what the change log alone would blame.
  const seen = new Set([rc?.change]);
  const alts = o ? [...o.refuted, ...(o.co_causes || []), o.baseline_pick, o.anomaly_baseline_pick]
    .filter((r) => r && !seen.has(r.change) && seen.add(r.change))
    .map((r) => ({ ...r, tag: r.tag || 'not on a dependency path the agents tested' })) : [];
  const actions = o && cur.incident && !resolved ? h('div', { class: 'actions' },
    rc ? h('button', { class: 'confirm', disabled: state.running && !cur.done, onclick: () => resolve(cur, rc.change) }, '✓ Confirm cause') : null,
    alts.length ? h('button', { class: 'ghost tall', onclick: () => { cur.showAlt = !cur.showAlt; renderAnswer(cur); } }, rc ? 'Wrong cause' : 'Pick the cause') : null,
    cur.showAlt ? h('div', { class: 'alts' },
      h('p', { class: 'muted small' }, 'Pick the change that really caused it. Your call is written to the graph and becomes memory.'),
      h('ul', {}, alts.map((r) => h('li', {}, h('span', {}, h('b', {}, short(r.change)), ` on ${short(r.service)}: ${r.summary || ''} `,
        h('span', { class: 'pill out' }, r.tag || 'suspect')),
        h('button', { class: 'ghost', onclick: () => resolve(cur, r.change) }, 'This one'))))) : null) : null;
  const learned = cur.resolved?.data ? h('div', { class: 'learned' },
    h('p', {}, h('span', { class: 'pill rb' }, 'saved to memory'), ' ', `Next time a change on ${short(rc?.service)} hurts ${short(cur.home)}, `,
      h('b', {}, `“${cur.resolved.data.title}”`), ' is tried first.'),
    cur.resolved.data.steps ? h('details', {}, h('summary', {}, `Show ${plural(cur.resolved.data.steps.length, 'step')}`),
      h('ol', {}, cur.resolved.data.steps.map((s) => h('li', {}, s)))) : null) : null;

  // Three columns.
  const col = (title, ...kids) => h('div', { class: 'col' }, h('h4', {}, title), ...kids);
  const broke = col('What broke', cur.alerts.length > 1 ? h('ul', { class: 'plain-list' }, cur.alerts.map((a) => h('li', {}, a.name))) : h('p', {}, cur.alert.name),
    f.broke.length ? h('div', { class: 'chips' }, f.broke.map((s) => chip(s, s === short(cur.home) ? 'alerting' : ''))) : live ? skel('80%') : h('p', { class: 'muted' }, 'Impact not mapped.'),
    f.atRisk.length ? h('p', { class: 'muted small' }, `Also at risk: ${f.atRisk.join(', ')}`) : null);
  const paged = col('Who’s paged', f.paged.length ? h('ul', { class: 'people' }, f.paged.map((p) => h('li', {},
    h('span', { class: 'avatar' }, (p.name || '?').split(' ').map((w) => w[0]).join('').slice(0, 2)),
    h('span', {}, h('b', {}, p.name), h('span', { class: 'muted'}, ` · ${p.team_name || p.team} · on-call${p.service ? ` for ${short(p.service)}` : ''}`)))))
    : live ? skel('70%') : h('p', { class: 'muted' }, 'Nobody paged.'),
    o?.warned?.length ? h('p', { class: 'small' }, h('span', { class: 'k' }, 'Heads-up'),
      o.warned.map((w, i) => [i ? ', ' : ' ', h('b', {}, w.name), ` (${w.team}) for ${short(w.service)}`])) : null,
    f.expert ? h('p', { class: 'small' }, `Knows ${short(f.expert.service || rc?.service || cur.home)} best: `, h('b', {}, f.expert.name), ` (${f.expert.handle})`) : null);
  const rb = f.runbook;
  const fix = col('Fix', learned || (rb ? [h('p', {}, h('b', {}, rb.title)),
    h('p', { class: 'muted small' }, rb.uses > 1 ? `worked ${rb.successes ?? 0} of ${rb.uses} times` : rb.uses === 1 ? 'confirmed once' : 'from memory'),
    rb.steps?.length ? h('details', {}, h('summary', {}, `Show ${plural(rb.steps.length, 'step')}`), h('ol', {}, rb.steps.map((s) => h('li', {}, s)))) : null]
    : live ? skel('60%') : h('p', { class: 'muted' }, 'No runbook for this yet. Confirm the cause and the fix is saved for next time.')));

  // Ruled out.
  const outranked = (o?.refuted || []).filter((r) => r.verdict === 'outranked');
  const ruledRows = f.refuted.filter((r) => r.verdict !== 'outranked');
  const ruled = ruledRows.length || outranked.length || (o?.co_causes || []).length ? h('div', { class: 'ruled' },
    h('h4', {}, `Ruled out (${ruledRows.length})`),
    h('ul', {}, ruledRows.map((r) => h('li', {}, h('b', {}, short(r.change)), ` on ${short(r.service)}`, h('span', { class: 'pill out' }, r.tag || 'ruled out'),
      h('span', { class: 'muted small' }, ` ${plain(r.reason)}`))),
    outranked.map((r) => h('li', { class: 'also' }, h('b', {}, 'Also possible: '), `${short(r.change)} on ${short(r.service)}`,
      h('span', { class: 'muted small' }, ` · ${alsoWhy(r, rc)}`))),
    (o?.co_causes || []).map((c) => h('li', { class: 'also' }, h('b', {}, 'Also contributing: '), `${short(c.change)} on ${short(c.service)}`,
      h('span', { class: 'muted small' }, ` · ${plain(c.reason || '')}`))))) : null;

  // Why this change (the path).
  const sym = SYMPTOM_WORD[cur.alert.symptom] || 'problem';
  const path = rc?.live_path?.length > 1 ? h('div', { class: 'why-path' }, h('h4', {}, 'Why this change'),
    pathChips([...rc.live_path].reverse()),
    h('p', {}, `The ${sym} travels ${[...rc.live_path].reverse().map(short).join(' → ')}, the same path the alert came up.`,
      rc.gaps?.length ? ` Nothing was recorded on ${rc.gaps.map(short).join(', ')} along the way (monitoring gap).` : '',
      rc.explained?.length > 1 ? ` It explains all ${rc.explained.length} alerting services.` : '')) : null;

  // Slack preview (collapsed).
  const slack = cur.resolved?.slack || cur.res?.slack;
  const preview = f.update ? h('details', { class: 'slack-wrap', open: mobile() ? null : null },
    h('summary', {}, h('span', { class: 'logo sm' }), h('b', {}, 'Status update drafted for #incidents'),
      h('span', { class: 'muted small' }, slack === 'posted' ? ' · posted to your Slack' : ' · preview'),
      cur.res && slack !== 'posted' ? h('span', { class: 'muted small' }, ' · ', h('button', { class: 'link-btn', onclick: (e) => { e.preventDefault(); showView('connect'); } }, 'Connect Slack to post it')) : null),
    slackCard(f.update, cur.alert.at)) : live ? h('div', { class: 'slack-wrap pending' }, h('p', { class: 'muted small' }, 'Comms drafts the #incidents update once the cause is clear…')) : null;

  // Right rail.
  const rail = [];
  if (live || (!o && f.suspects.length)) rail.push(suspectsCard(f, live));
  const bp = o?.baseline_pick, ab = o?.anomaly_baseline_pick;
  if (bp || ab) {
    const row = (label, pick, ok) => pick && h('li', { class: ok ? 'ok' : 'bad' }, h('span', {}, label), h('b', {}, short(pick.change)), h('span', { class: 'pill' }, ok ? 'same answer' : 'wrong'));
    rail.push(h('div', { class: 'card nograph' }, h('h4', {}, 'What a change log alone would blame'),
      h('ul', {}, row('Newest change', bp, o.baseline_correct), row('Change log + anomalies', ab, o.anomaly_baseline_correct)),
      h('p', { class: 'muted small' }, 'The same facts without walking the dependency graph.')));
  }
  if (f.sources.length) rail.push(h('div', { class: 'card' }, h('h4', {}, 'Sources'),
    h('div', { class: 'chips' }, f.sources.map((s) => h('span', { class: 'chip-static src', title: s.id }, h('span', { class: 'pill kind' }, kindWord(s.kind)), ' ', plain(s.title || short(s.id)))))));
  if (o?.storm) rail.push(h('div', { class: 'card storm' }, h('h4', {}, 'Alert storm'),
    h('p', {}, h('b', {}, `${o.storm.alerts.length + 1} alerts → 1 incident`)),
    h('p', { class: 'small' }, 'Nearest shared upstream: ', h('b', {}, o.storm.shared.slice(0, 2).map((s) => short(s.service)).join(', ') || 'none')),
    h('p', { class: 'muted small' }, 'Without correlating them first, the same agents blame a change that explains only one alert.')));
  if (cur.res?.planner) rail.push(h('p', { class: 'muted small foot' },
    `Steps chosen by ${modelDecides() ? modelName((cur.res.planner || '').split(' ')[0]) : 'the rule planner'}`));

  set('answer', h('div', { class: 'answer-grid' },
    h('div', { class: 'answer-main' }, memory, verdict, actions, h('div', { class: 'cols' }, broke, paged, fix), ruled, path, preview),
    h('div', { class: 'answer-rail' }, rail)));
}

// "outranked: chg:x explains every alerting service this change does (1) and 2 more" -> plain words.
function alsoWhy(r, rc) {
  const m = String(r.reason || '').match(/explains every alerting service this change does \((\d+)\) and (\d+) more/);
  if (m) {
    const n = Number(m[1]), all = n + Number(m[2]);
    return `it only explains ${n} of ${all} alerting services; the ${short(rc?.service || '')} change explains all ${all}`;
  }
  return plain(r.reason).replace(/^outranked:\s*/, '');
}

function suspectsCard(f, live) {
  const rows = f.suspects.length ? f.suspects.map((s) => {
    const st = s.verdict === 'refutes' ? 'out' : s.verdict === 'supports' ? 'yes' : 'open';
    return h('li', { class: st }, h('span', { class: 'sus-ic' }, st === 'out' ? '✗' : st === 'yes' ? '✓' : '?'),
      h('span', {}, h('b', {}, short(s.change)), ` on ${short(s.service)}`,
        h('span', { class: 'muted small' }, st === 'out' ? ` · ruled out: ${s.tag}` : st === 'yes' ? ' · supported' : s.source === 'memory' ? ' · from memory' : ' · open')));
  }) : [h('li', { class: 'muted' }, live ? 'Listing recent changes on the dependency paths…' : 'No suspects.')];
  return h('div', { class: 'card suspects' }, h('h4', {}, `Suspects${f.suspects.length ? ` (${f.suspects.length})` : ''}`), h('ul', {}, rows));
}

// The status update the way it lands in Slack: the comms agent's text, line by line ("Key: value").
function slackCard(text, at) {
  const [first, ...rest] = text.split('\n');
  const m = first.match(/^\[(.*)\]\s*status:\s*(.*)$/);
  return h('div', { class: 'slack' },
    h('div', { class: 'slack-head' }, h('span', { class: 'logo sm' }), h('b', {}, 'On-call Brain'), h('span', { class: 'app' }, 'APP'), h('span', { class: 'muted' }, ist(at))),
    m ? h('p', { class: 'slack-title' }, h('span', { class: 'siren' }, '●'), h('b', {}, m[1]), ' — ', m[2]) : h('p', {}, first),
    rest.map((line) => {
      const k = line.match(/^([A-Z][\w ()]{1,30}):\s(.*)$/);
      if (!k) return h('p', {}, line);
      return h('p', { class: /cause/i.test(k[1]) ? 'cause-line-slack' : null }, h('b', {}, `${k[1]}: `), k[2]);
    }));
}

// ---------- rendering: show me why (timeline) ----------
const TOOL_TITLE = {
  open_incident: () => 'Open a shared incident record',
  blast_radius: (s) => `Who depends on ${short(idIn(s.summary, 'svc') || '')}?`,
  page_on_call: (s) => `Who is on call for ${short(idIn(s.summary, 'svc') || '')}?`,
  correlate_alerts: () => 'Do these alerts share a cause?',
  recall_similar: () => 'Have we seen this before?',
  hypothesize_from_memory: () => 'Does the remembered fix apply?',
  propose_hypotheses: () => 'Which recent changes could be the cause?',
  check_hypothesis: (s) => `Test suspect: ${short(s.data?.change || '')}`,
  conclude: () => 'Which suspect explains the most?',
  who_knows: (s) => `Who knows ${short(idIn(s.summary, 'svc') || '')} best?`,
  warn_owners: () => 'Who should get a heads-up?',
  post_update: () => 'Draft the status update',
};
const stepTitle = (s) => (TOOL_TITLE[s.tool] ? TOOL_TITLE[s.tool](s) : s.tool.replace(/_/g, ' '));
function stepResult(s) {
  const d = s.data;
  if (s.tool === 'check_hypothesis' && d) return `${d.verdict === 'supports' ? 'Supported' : 'Ruled out'}: ${short(d.change)} on ${short(d.service)} · ${plain(d.reason)}`;
  return plain(s.summary);
}

function learnNames(step) {
  const d = step.data;
  if (step.tool === 'page_on_call' && d?.person) {
    names.set(d.person, d.name);
    names.set(d.team, `${d.team_name} team`);
  }
  if (step.tool === 'who_knows') for (const p of d || []) names.set(p.person, p.name);
  if (step.tool === 'ask') for (const r of d?.related || []) if (['person', 'team'].includes(kindOf(r.id))) names.set(r.id, r.name);
}

function copyBtn(text) {
  return h('button', { class: 'ghost copy', onclick: (e) => { e.preventDefault(); navigator.clipboard?.writeText(text).then(() => toast('Copied.')); } }, 'Copy');
}

function queryBlock(q) {
  return h('div', { class: 'q' },
    h('div', { class: 'qhead' }, h('b', {}, q.name),
      h('span', { class: `rw ${q.readonly ? 'ro' : 'w'}`, title: q.readonly ? 'GRAPH.RO_QUERY' : 'GRAPH.QUERY (writes)' }, q.readonly ? 'read' : 'write'),
      h('span', { class: 'muted' }, `${plural(q.rows.length, 'row')} · ${q.ms} ms`),
      q.name === 'incident_board' ? h('span', { class: 'tag' }, 'the agent reads the shared board') : null, copyBtn(q.cypher)),
    h('pre', { class: 'cypher' }, q.cypher),
    h('pre', { class: 'params' }, `params ${JSON.stringify(q.params)}`),
    q.rows.length ? h('details', { class: 'rows' }, h('summary', {}, `rows (${q.rows.length})`), h('pre', {}, JSON.stringify(q.rows, null, 1))) : null);
}

function cypherList(queries) {
  if (!queries?.length) return null;
  const ms = queries.reduce((a, q) => a + q.ms, 0), rows = queries.reduce((a, q) => a + q.rows.length, 0);
  return h('details', { class: 'cypher-list' },
    h('summary', {}, `Cypher · ${plural(queries.length, 'query')} · ${plural(rows, 'row')} · ${ms.toFixed(1)} ms`),
    queries.map(queryBlock));
}

function stepRow(step, i) {
  const d = step.data, verdict = step.tool === 'check_hypothesis' && d ? d.verdict : null;
  // Runs recorded before reasons and deciders were stored say "LLM chose X" with no decider: show that honestly.
  const old = /^LLM chose /.test(step.reason || '');
  const by = old && step.by === 'rules' ? 'model' : step.by;
  const why = old ? 'chosen by the model (older run; its reason was not recorded)' : plain(step.reason);
  return h('li', { class: `step ${step.role}${verdict ? ` v-${verdict}` : ''}`, 'data-i': i, tabindex: 0, role: 'button' },
    h('div', { class: 'step-head' }, h('span', { class: 'seq' }, step.seq), h('b', { class: 'step-title' }, stepTitle(step)),
      h('code', { class: 'tool' }, step.tool), h('span', { class: `by ${by === 'rules' ? 'rules' : 'model'}` }, by === 'model' ? 'Model' : modelName(by))),
    verdict ? h('p', { class: 'summary' }, h('span', { class: `verdict ${verdict}` }, verdict === 'supports' ? '✓ supports' : '✗ ruled out'), ' ',
      h('b', {}, short(d.change)), ` on ${short(d.service)}: `, h('span', { class: 'reason' }, plain(d.reason)),
      verdict === 'supports' && d.live_path?.length > 1 ? pathChips([...d.live_path].reverse()) : null)
      : h('p', { class: 'summary' }, plain(step.summary)),
    h('p', { class: 'why' }, h('span', { class: 'why-label' }, 'why '), why),
    cypherList(step.queries));
}

function renderWhy(cur) {
  const steps = cur.steps || [];
  const ms = steps.reduce((a, s) => a + (s.queries || []).reduce((b, q) => b + q.ms, 0), 0);
  const byModel = steps.filter((s) => s.by && s.by !== 'rules').length;
  const groups = ROLES.map((role) => {
    const mine = steps.map((s, i) => [s, i]).filter(([s]) => s.role === role);
    if (!mine.length) return null;
    const hand = mine.find(([s]) => s.tool === 'handoff')?.[0];
    return h('details', { class: `group ${role}`, open: true },
      h('summary', {}, h('span', { class: `role ${role}` }, `${ROLE_N[role]} ${role}`),
        h('span', { class: 'muted small' }, plural(mine.filter(([s]) => s.tool !== 'handoff').length, 'step')),
        hand ? h('span', { class: 'hand' }, `→ ${hand.summary.includes('human') ? 'Handed to you' : `Handed to ${hand.summary.split('to ')[1] || ''}`}: ${plain(hand.reason)}`) : null),
      h('ol', { class: 'steps' }, mine.filter(([s]) => s.tool !== 'handoff').map(([s, i]) => stepRow(s, i))));
  });
  set('why-side', h('div', { class: 'why-head' }, h('h3', {}, `Agent steps · ${steps.length}`),
    h('span', { class: 'muted small' }, [ms ? `${(ms / 1000).toFixed(1)} s on the graph` : '',
      cur.res?.llm_tokens ? `${(cur.res.llm_tokens / 1000).toFixed(0)}k model tokens` : ''].filter(Boolean).join(' · '))),
    h('div', { class: 'why-groups' }, groups),
    h('p', { class: 'muted small foot' }, steps.length ? `Steps chosen by ${byModel ? `${modelName(steps.find((s) => s.by !== 'rules')?.by)} (${byModel})` : ''}`
      + `${byModel && steps.length - byModel ? ' and ' : ''}${steps.length - byModel ? `the rule planner (${steps.length - byModel})` : ''}` : ''));
}

function onStepClick(ev) {
  if (ev.target.closest('summary, pre, details[open] *, button')) return; // let people read and expand the Cypher
  const li = ev.target.closest('li[data-i]'), cur = state.current;
  if (!li || !cur?.steps) return;
  $('why-side').querySelectorAll('.selected').forEach((x) => x.classList.remove('selected'));
  li.classList.add('selected');
  const eles = cur.steps[Number(li.dataset.i)]?.eles;
  if (eles && state.graphOwner === cur) G.paint(cur, eles, G.near(eles));
}

// ---------- the graph's picture of a run ----------
function renderGraphTools() {
  const owner = state.graphOwner, scoped = G.isScoped();
  const g = state.graph;
  let caption = g ? `${g.nodes.length} services · ${g.edges.length} dependencies` : '';
  if (owner && owner !== 'ask' && g) {
    const shown = scoped ? (G.select('.svc:visible')?.length ?? g.nodes.length) : g.nodes.length;
    caption = scoped ? `Showing ${shown} of ${g.nodes.length} services: what this incident touched, plus one hop` : `Whole company: ${g.nodes.length} services`;
  } else if (owner === 'ask' && g) caption = scoped ? 'Showing what this answer is linked to' : `Whole company: ${g.nodes.length} services`;
  set('hud', h('span', { class: 'muted' }, caption));
  set('graph-tools', owner && G.ready() ? h('button', { class: 'ghost', onclick: () => { scoped ? G.scopeAll() : rescope(); renderGraphTools(); } },
    scoped ? 'Show whole company' : 'Incident only') : null);
}

function rescope() {
  const cur = state.current;
  if (state.graphOwner === 'ask') return state.askEles?.nonempty() && G.scopeTo(state.askEles);
  if (cur?.touched?.nonempty()) G.scopeTo(cur.touched);
}

function applyStep(run, step, live) {
  if (!G.ready()) return;
  let eles = G.elementsFor(step.highlight, run);
  if (!eles) return;
  if (step.tool === 'correlate_alerts' && step.data?.alerts?.length) eles = eles.union(G.markStorm(step.data, run));
  step.eles = eles;
  run.touched = run.touched.union(eles);
  if (step.tool === 'check_hypothesis' && step.data) {
    if (step.data.verdict === 'supports') run.cause = run.cause.union(eles);
    else G.mark(step.data.change, 'refuted');
  }
  if (live) G.paint(run, eles, step.tool === 'correlate_alerts' ? eles : G.near(eles));
}

// End on the answer: the incident subgraph, with the cause path (and the memory chain, if memory solved it) lit.
function finalPaint(run) {
  const o = outcomeOf(run);
  if (!o || !G.ready()) return;
  const memo = o.memory?.solved_by_memory ? G.elementsFor({ nodes: [], edges: o.memory.recalled.flatMap((r) =>
    [[run.incident, r.incident, 'RECALLS'], [r.incident, r.runbook, 'FIXED_WITH']]) }, run) : null;
  if (memo) run.touched = run.touched.union(memo);
  const learned = run.resolved && G.elementsFor(run.resolved.highlight, run);
  if (learned) run.touched = run.touched.union(learned);
  const storm = o.storm ? G.select('.storm, .shared') : null;
  G.scopeTo(run.touched, storm ? run.cause.union(storm) : run.cause); // one hop around the cause path (and the storm)
  const focus = storm ? run.cause.union(storm) : run.cause.nonempty() ? run.cause.union(memo || G.empty()) : null;
  G.paint(run, learned || memo, focus);
  renderGraphTools();
}

// Rebuild the graph's picture of a run from its steps (switching incidents, or back from Ask).
function replayGraph(cur) {
  state.graphOwner = cur;
  if (!G.ready()) return renderGraphTools();
  G.clear(false);
  if (!cur) { G.paint(null); return renderGraphTools(); }
  cur.touched = G.empty();
  cur.cause = G.empty();
  G.mark(cur.home, 'alerting');
  for (const s of cur.steps || []) applyStep(cur, s, false);
  if (cur.stored) { // no live trace: light the cause path and the storm the graph remembers
    const o = outcomeOf(cur), rc = o?.root_cause, p = rc?.live_path || [];
    const eles = G.elementsFor({ nodes: p, edges: p.slice(1).map((n, i) => [p[i], n, 'DEPENDS_ON']) }, cur);
    if (eles) { cur.touched = cur.touched.union(eles); cur.cause = eles; }
    if (o?.storm) {
      const alerting = [...new Set([cur.home, ...o.storm.alerts.map((a) => a.service)])];
      for (const s of alerting) G.mark(s, 'alerting storm');
      for (const s of o.storm.shared) G.mark(s.service, 'shared');
      if (o.storm.shared[0]) G.mark(o.storm.shared[0].service, 'choke');
      const marked = G.select([...alerting, ...o.storm.shared.map((s) => s.service)].map((id) => `[id = "${id}"]`).join(', '));
      if (marked) cur.touched = cur.touched.union(marked);
    }
  }
  if (outcomeOf(cur)) finalPaint(cur);
  else G.paint(cur, null, cur.touched.nonempty() ? cur.touched : G.select(`[id = "${cur.home}"]`));
  renderGraphTools();
}

// ---------- views ----------
function showView(view) {
  state.view = view;
  closeMenus();
  for (const b of document.querySelectorAll('.view-tab')) b.setAttribute('aria-current', b.dataset.view === view ? 'page' : 'false');
  for (const v of ['incidents', 'ask', 'connect']) $(`view-${v}`).hidden = v !== view;
  if (view === 'connect') renderConnect();
  if (view === 'ask') renderChat();
  placeGraph();
}

function showTab(tab) {
  state.tab = tab;
  $('tab-answer').setAttribute('aria-selected', String(tab === 'answer'));
  $('tab-why').setAttribute('aria-selected', String(tab === 'why'));
  $('tab-answer').tabIndex = tab === 'answer' ? 0 : -1;
  $('tab-why').tabIndex = tab === 'why' ? 0 : -1;
  $('answer-view').hidden = tab !== 'answer';
  $('why-view').hidden = tab !== 'why';
  if (tab === 'why' && state.current) renderWhy(state.current);
  placeGraph();
}

// One Cytoscape canvas, moved to wherever it is shown; its picture is rebuilt when its owner changes.
function placeGraph() {
  const ask = state.view === 'ask';
  const slot = ask ? $('ask-graph-slot') : $('why-graph-slot');
  if ($('graph-wrap').parentElement !== slot) slot.append($('graph-wrap'));
  if (ask && state.graphOwner !== 'ask') {
    state.graphOwner = 'ask';
    G.clear(false);
    renderGraphTools();
  } else if (!ask && state.tab === 'why' && state.graphOwner !== state.current) replayGraph(state.current);
  requestAnimationFrame(() => { G.refit(); });
}

function showIncident(cur) {
  state.current = cur;
  $('landing').hidden = !!cur;
  $('incident').hidden = !cur;
  document.querySelector('.incidents').classList.toggle('has-current', !!cur);
  renderAll();
  if (state.view !== 'incidents') showView('incidents');
  else placeGraph();
  if (cur && mobile()) $('incident-main').scrollTo({ top: 0 });
}

function renderAll() {
  renderInbox();
  renderSimulateMenu();
  const cur = state.current;
  if (!cur) return renderLanding();
  renderHead(cur);
  renderProgress(cur);
  renderAnswer(cur);
  if (state.tab === 'why') renderWhy(cur);
}

function openRun(run) {
  if (state.current === run) return;
  showTab('answer');
  showIncident(run);
}

async function openStored(incident) {
  try {
    const d = await api('GET', `${T()}/incidents/${enc(incident)}`);
    const alerts = state.alerts.filter((a) => a.incident === incident);
    const alert = { id: d.alert, name: d.alert_name, service: d.service, at: d.at, symptom: d.symptom };
    const cur = { stored: true, done: true, incident, alert, alerts: alerts.length ? alerts : [alert], home: d.service,
      status: d.status, res: { outcome: d.outcome, steps: d.steps, planner: null, llm_tokens: 0 }, steps: d.steps,
      resolved: null, touched: G.empty(), cause: G.empty() };
    showTab('answer');
    showIncident(cur);
  } catch (e) {
    toast(e.message, true);
  }
}

// ---------- actions ----------
async function refreshAlerts() {
  if (OFFLINE) return; // the recording does not change; runs carry their own status
  try {
    state.alerts = await api('GET', `${T()}/alerts`);
  } catch { /* keep the old list; the next action reports a real outage */ }
  renderAll();
}

function setRunning(on) {
  state.running = on;
  $('btn-simulate').disabled = on;
  renderSimulateMenu();
  if (!state.current) renderLanding();
}

function fireNext() {
  const next = nextScenario();
  if (next) fire(next.act);
  else doReset();
}

function fire(act) {
  const sc = scenarios().find((s) => s.act === act);
  if (sc) runAlert(sc.trigger, sc.alerts, act);
}

async function raiseCustom(form) {
  const body = Object.fromEntries(new FormData(form));
  try {
    const r = await api('POST', `${T()}/alerts`, body);
    await refreshAlerts();
    const alert = state.alerts.find((a) => a.id === r.alert) || { id: r.alert, name: body.name, service: body.service, at: r.at, symptom: body.symptom };
    runAlert(alert, [alert], null);
  } catch (e) {
    toast(e.message, true);
  }
}

async function runAlert(alert, alerts, act) {
  if (state.running) return;
  const run = newRun(alert, alerts, act);
  state.runs.push(run);
  state.skip = false;
  setRunning(true);
  showTab('answer');
  showIncident(run);
  replayGraph(run);
  let last = 0;
  try {
    for await (const ev of runEvents(`${T()}/alerts/${enc(alert.id)}/respond/stream${act === 2 ? '?compare=memory' : ''}`)) {
      if (ev.step) {
        if (!state.skip) await sleep(Math.max(0, last + STEP_MS - performance.now()));
        last = performance.now();
        onStep(run, ev.step);
      } else if (ev.result) onResult(run, ev.result);
      else if (ev.ablation) {
        run.ablation = ev.ablation;
        if (state.current === run) renderAnswer(run);
      } else if (ev.error) throw new Error(ev.error);
    }
    if (!run.done) throw new Error('the agent run ended without a result');
  } catch (e) {
    run.error = e.message;
    run.done = true;
    toast(`The agents could not finish: ${e.message}`, true);
    if (state.current === run) renderAll();
  } finally {
    setRunning(false);
    await refreshAlerts();
  }
}

function onStep(run, step) {
  run.steps.push(step);
  learnNames(step);
  if (step.tool === 'open_incident' && step.data?.incident) run.incident = step.data.incident;
  if (step.tool === 'correlate_alerts') run.folded = true;
  if (state.graphOwner === run) applyStep(run, step, true);
  announce(`${step.role}: ${plain(step.reason)}`);
  renderInbox();
  if (state.current !== run) return;
  renderHead(run);
  renderProgress(run);
  renderAnswer(run);
  if (state.tab === 'why') renderWhy(run);
}

function onResult(run, res) {
  run.res = res;
  run.incident = res.incident_id;
  run.done = true;
  run.folded = true;
  if (state.graphOwner === run) finalPaint(run);
  if (state.current === run) renderAll();
  const rc = res.outcome.root_cause;
  announce(rc ? `Cause found: ${short(rc.change)} on ${short(rc.service)}` : 'No cause found; a human should look.');
  if (state.current !== run) toast(rc ? `Cause found for ${titleOf(run)}.` : `${titleOf(run)}: no cause found.`);
}

async function resolve(cur, change) {
  try {
    const r = await api('POST', `${T()}/incidents/${enc(cur.incident)}/resolve`, { change_id: change });
    cur.resolved = r;
    cur.showAlt = false;
    if (r.data) names.set(r.data.runbook, 'runbook');
    if (state.graphOwner === cur) finalPaint(cur);
    toast('Cause confirmed and the fix saved to memory.');
    announce('Cause confirmed and the fix saved to memory.');
  } catch (e) {
    toast(e.message, true);
  }
  await refreshAlerts();
}

async function doReset() {
  if (state.running) return;
  try {
    const r = await api('POST', `${T()}/reset`);
    names.clear();
    Object.assign(state, { runs: [], chat: [], graphOwner: null, askEles: null });
    await loadTenant();
    showIncident(null);
    toast(r.status === 'seeded' ? 'Loaded the demo company into FalkorDB.' : 'Demo company reset: the graph was restored from its pristine copy.');
  } catch (e) {
    toast(e.message, true);
  }
}

// ---------- ask the brain ----------
// The answer first (one or two sentences), then at most five source chips, then the rest behind disclosures.
function splitAnswer(text) {
  const full = String(text || '');
  // Sentences end at punctuation followed by whitespace, so "@hana.costa" and "inc:0911" never split a sentence.
  const sentences = full.split(/(?<=[.!?])\s+/);
  let lead = '';
  for (const s of sentences) {
    if (lead && lead.length + s.length > 260) break;
    lead += (lead ? ' ' : '') + s;
  }
  return [lead.trim(), full.slice(lead.length).trim()];
}

function brainMessage(m) {
  if (m.pending) return h('div', { class: 'msg brain' }, h('p', { class: 'muted' }, h('span', { class: 'spinner' }), 'Searching the graph…'));
  if (m.error) return h('div', { class: 'msg brain' }, h('p', { class: 'error' }, m.error));
  const d = m.data, [lead, rest] = splitAnswer(d.answer);
  const hits = (d.hits || []).slice(0, 5), more = (d.related || []);
  return h('div', { class: 'msg brain' },
    h('p', { class: 'answer' }, lead),
    rest ? h('details', { class: 'more' }, h('summary', {}, 'More detail'), h('p', { class: 'small' }, rest)) : null,
    hits.length ? h('div', { class: 'sources' }, h('span', { class: 'k' }, 'Sources'),
      h('div', { class: 'chips' }, hits.map((x) => [
        h('button', { class: 'chip-btn src', title: x.title, onclick: (e) => {
          const q = e.currentTarget.nextElementSibling; if (q) q.hidden = !q.hidden; } },
        h('span', { class: 'pill kind' }, kindWord(x.kind)), ' ', x.title,
        x.superseded_by ? h('span', { class: 'pill out' }, 'superseded') : null),
        h('blockquote', { class: 'quote small', hidden: true }, x.snippet)]))) : null,
    more.length ? h('details', { class: 'more' }, h('summary', {}, `More linked (${more.length})`),
      h('div', { class: 'chips' }, more.map((r) => h('span', { class: 'chip-static' }, h('span', { class: 'pill kind' }, kindWord(r.kind)), ' ', r.name)))) : null,
    mobile() ? h('button', { class: 'ghost small-btn', onclick: () => toggleAskGraph() }, 'Show on graph') : null,
    cypherList(m.queries));
}

function toggleAskGraph() {
  const on = document.body.classList.toggle('ask-graph-open');
  requestAnimationFrame(() => G.refit());
  return on;
}

function renderChat() {
  const log = $('chat-log');
  if (!state.chat.length) {
    set('chat-log', h('div', { class: 'chat-empty' },
      h('h2', {}, 'Ask the company brain'),
      h('p', { class: 'muted' }, 'Who owns what, why something was decided, what fixed it last time: answered from the same graph the agents use, with sources.'),
      OFFLINE ? h('p', { class: 'note' }, 'This page is a recorded replay, so questions need the live server (make dev). Questions it answers, for example:') : null,
      h('div', { class: 'chips' }, EXAMPLES.map((q) => h('button', { class: 'chip-btn', disabled: OFFLINE, onclick: () => askQ(q) }, q)))));
    return;
  }
  set('chat-log', state.chat.map((m) => (m.who === 'you' ? h('div', { class: 'msg you' }, m.text) : brainMessage(m))));
  // Scroll so the latest answer starts in view (its first line is the answer), not so its tail is in view.
  const last = log.lastElementChild, question = last?.previousElementSibling;
  log.scrollTop = Math.max(0, (question || last)?.offsetTop - log.offsetTop - 8 || 0);
}

async function askQ(q) {
  if (!q || state.asking || OFFLINE) return;
  state.asking = true;
  $('ask-go').disabled = true;
  const m = { who: 'brain', pending: true };
  state.chat.push({ who: 'you', text: q }, m);
  renderChat();
  try {
    const r = await api('POST', `${T()}/tools/ask`, { question: q });
    Object.assign(m, { pending: false, data: r.data, queries: r.queries });
    learnNames({ tool: 'ask', data: r.data });
    announce(splitAnswer(r.data.answer)[0]);
    if (state.view === 'ask' && G.ready()) {
      state.graphOwner = 'ask';
      G.clear(false);
      const eles = G.elementsFor(r.highlight, null);
      state.askEles = eles;
      if (eles?.nonempty()) { G.scopeTo(eles); G.paint(null, eles, eles); }
      renderGraphTools();
    }
  } catch (e) {
    Object.assign(m, { pending: false, error: e.message });
  } finally {
    state.asking = false;
    $('ask-go').disabled = false;
    renderChat();
  }
}

// ---------- connect ----------
function renderConnect() {
  const origin = OFFLINE ? 'http://localhost:8000' : location.origin;
  // On a deployment (not localhost) the plugin card also shows remote mode: nothing local but the plugin.
  const deployed = !OFFLINE && !/^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
  const code = (text) => h('div', { class: 'code-wrap' }, h('pre', { class: 'code' }, text), copyBtn(text));
  const card = (title, ...kids) => h('div', { class: 'card connect-card' }, h('h3', {}, title), ...kids);
  const hl = state.health;
  const pill = (label, value, ok) => h('span', { class: `status-pill ${ok ? 'confirmed' : 'open'}` }, `${label} · ${value}`);
  // "at" pins the sample to the demo company's act-1 time (datagen.T1), where its changes sit; without it the alert is
  // stamped now and the demo graph has nothing recent to blame. A real alerting tool leaves it out.
  const curl = `curl -X POST '${origin}${T()}/alerts?respond=true' \\\n  -H 'content-type: application/json' \\\n  -d '{"service": "svc:checkout", "symptom": "latency", "name": "checkout p99 latency above 2s", "at": 1792036800}'`;
  set('connect',
    h('div', { class: 'connect-intro' }, h('h2', {}, 'Plug it into your stack'),
      h('p', { class: 'muted' }, 'Every agent tool is defined once and exposed three ways: to the agents, over MCP, and over HTTP.'),
      h('div', { class: 'status-row' },
        pill('FalkorDB', hl?.falkordb ? 'connected' : 'down', !!hl?.falkordb),
        pill('Alert webhook', 'ready', true),
        pill('Slack', hl?.slack ? 'connected' : 'not connected', !!hl?.slack),
        pill('Steps chosen by', plannerLabel(), modelDecides()))),
    h('div', { class: 'connect-grid' },
      card('Send alerts in (webhook)',
        h('p', {}, 'Point your alerting tool at this endpoint and map its payload to service, symptom (latency, errors or saturation) and name. With respond=true the agents start right away; new alerts show up in the inbox. The sample pins "at" to the demo story\'s time; leave it out and the alert is stamped now.'),
        code(curl)),
      card('Use it from Claude Code (plugin)',
        h('p', {}, 'The plugin ships the MCP server (the same graph tools the agents use, plus “respond to alert”) and three skills. From the repo:'),
        code('claude --plugin-dir ./plugin\n/oncall-brain:incident alert:checkout-latency\n/oncall-brain:who-owns kafka'),
        deployed ? h('p', { class: 'small' }, 'Against this deployment, with nothing local but the plugin (the token is the MCP_TOKEN set on the host):') : null,
        deployed ? code(`ONCALL_BRAIN_URL=${origin} ONCALL_BRAIN_TOKEN=<MCP_TOKEN> claude --plugin-dir ./plugin`) : null,
        h('p', { class: 'muted small' }, 'Or install it: /plugin install oncall-brain --marketplace <owner>/<repo>. Any other MCP client: ', h('code', {}, 'python -m oncall_brain.mcp_server'), ' (stdio) or ', h('code', {}, '--http --port 8001'), '.')),
      card('Post updates to Slack',
        hl?.slack ? h('p', { class: 'ok-line' }, 'Connected: every status update is also posted to your channel.')
          : [h('p', {}, h('b', {}, 'Not connected. '), 'Create an incoming webhook in Slack (Apps → Incoming Webhooks), add it to .env and restart:'),
            code('SLACK_WEBHOOK_URL=https://hooks.slack.com/services/…')]),
      card('Bring your own data',
        h('p', {}, `This demo runs on a synthetic company (${state.graph ? `${state.graph.nodes.length} services` : 'services'}, teams, people, changes). Real systems feed the same graph as things happen, through write tools on MCP and HTTP:`),
        h('ul', { class: 'small' },
          h('li', {}, h('code', {}, 'record_change'), ' from CI/CD (deploys, config changes)'),
          h('li', {}, h('code', {}, 'record_anomaly'), ' and ', h('code', {}, 'raise_alert'), ' from monitoring'),
          h('li', {}, h('code', {}, 'add_dependency'), ' / ', h('code', {}, 'retire_dependency'), ' from the service catalog')),
        h('p', { class: 'muted small' }, 'Every write is an idempotent MERGE, so replays and retries are safe.')),
      card('Each company is its own graph',
        h('p', {}, 'One FalkorDB graph per company (tenant): memory, incidents and knowledge never mix. ', h('b', {}, `This company: ${companyLabel()}.`),
          ' Add ?tenant=<name> to the URL to open another.'),
        h('button', { class: 'ghost tall', disabled: state.running, onclick: () => doReset() }, 'Reset demo company')),
      card('Who decides each step',
        h('p', {}, 'Now: ', h('b', {}, plannerLabel()), '. Set LLM_PROVIDER (anthropic, openai, gemini, groq, ollama) and a key in .env to let a model choose the tools; '
          + 'without one, rules choose each step from what the graph returns. Either way, every fact comes from a graph query, and each run is capped in tokens.'))));
}

// ---------- startup ----------
async function loadTenant() {
  state.alerts = await api('GET', `${T()}/alerts`);
  const g = state.graph = await api('GET', `${T()}/graph`);
  G.build($('graph'), g);
  state.graphOwner = null;
  renderGraphTools();
}

async function init() {
  for (const b of document.querySelectorAll('.view-tab')) b.onclick = () => showView(b.dataset.view);
  $('tab-answer').onclick = () => showTab('answer');
  $('tab-why').onclick = () => showTab('why');
  document.querySelector('.seg').addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { showTab(state.tab === 'answer' ? 'why' : 'answer'); $(state.tab === 'answer' ? 'tab-answer' : 'tab-why').focus(); }
  });
  $('btn-back').onclick = () => showIncident(null);
  $('btn-simulate').onclick = (e) => {
    e.stopPropagation();
    const open = $('simulate-menu').hidden;
    closeMenus();
    if (open) { renderSimulateMenu(); $('simulate-menu').hidden = false; $('btn-simulate').setAttribute('aria-expanded', 'true'); }
  };
  $('simulate-menu').addEventListener('click', (e) => e.stopPropagation());
  document.addEventListener('click', closeMenus);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenus(); });
  $('why-side').addEventListener('click', onStepClick);
  $('why-side').addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { if (e.target.closest('li[data-i]')) { e.preventDefault(); onStepClick(e); } } });
  $('ask-form').onsubmit = (e) => {
    e.preventDefault(); // the native form gives Enter-to-ask; never navigate
    const q = $('ask-q').value.trim();
    $('ask-q').value = '';
    askQ(q);
  };
  if (OFFLINE) $('ask-q').disabled = $('ask-go').disabled = true;
  matchMedia('(max-width: 900px)').addEventListener('change', () => { renderAll(); placeGraph(); });
  placeGraph();
  showIncident(null);
  try {
    const hl = state.health = await api('GET', '/api/health');
    const tenant = params.get('tenant');
    state.tenant = tenant && /^[a-z0-9_]{1,40}$/.test(tenant) ? tenant : hl.default_tenant;
    if (OFFLINE) hl.falkordb = true; // a recording of real runs; the live dot is not shown offline anyway
  } catch (e) {
    if (!OFFLINE) { // no backend (e.g. a static host): replay the recorded runs instead
      params.set('offline', '1');
      location.search = params.toString();
      return;
    }
    toast(`Could not load the recordings (${e.message}).`, true);
    return;
  }
  try {
    await loadTenant();
  } catch (e) {
    toast(`${e.message}. Use “Reset demo company” in the Simulate menu to load the demo company.`, true);
  }
  renderAll();
}

init();
