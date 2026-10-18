// On-call Brain UI (docs/design/RULEBOOK.md, direction "Pager"). Three views:
//   Incidents  the inbox on the left; the open incident on the right as an ink slab (the page you were woken by),
//              then dispatch rows that answer it in order: Cause, Where (the evidence wire), Since, Who, Do this,
//              Ruled out, Sources, and the status update. "Show me why" is the incident subgraph and every agent step
//              with the Cypher behind it. Confirm cause / Wrong cause write the human's call back to the graph.
//   Ask        company questions answered from the graph, with sources.
//   Connect    how to plug it in: the alert webhook, the Claude Code plugin (MCP), Slack, your own data.
// No build step. Every piece of API data reaches the DOM as text (see h()), never as HTML.

import * as G from './graph.js';

const { kindOf, short, names } = G;
const params = new URLSearchParams(location.search);
const OFFLINE = params.has('offline'); // ?offline=1 replays web/fixtures (recorded from the real code)
const STEP_MS = Number(params.get('step_ms')) || 700; // fastest pace at which steps appear (a model is slower anyway)
const ROLES = ['triage', 'investigator', 'comms'];
const ROLE_NAME = { triage: 'Triage', investigator: 'Investigator', comms: 'Comms' };
const ROLE_JOB = { triage: 'Finds who is hurt and pages on-call.', investigator: 'Tests every recent change against the graph.',
  comms: 'Writes the status update, with sources.' };
const SCENARIO_NOTE = {
  1: 'A bad config change hides among four other recent changes.',
  2: 'The same failure again. Confirm the first cause and memory solves this one in a few steps.',
  3: 'Three services alert within minutes. One shared cause, or three?',
};
const EXAMPLES = ['Who owns kafka?', 'Why was legacy-billing retired?', 'Why was the payments gateway pool lowered?',
  'How do I roll back a bad deploy on cart?', 'What happened to auth?', 'Who knows payments-gw?'];
const MODELS = { 'claude-opus-5-5': 'Claude Opus 5.5', 'claude-sonnet-5-5': 'Claude Sonnet 5.5',
  'claude-haiku-5-5': 'Claude Haiku 5.5', 'claude-fable-5-1': 'Claude Fable 5.1', rules: 'the rules' };
const SYMPTOM_WORD = { latency: 'slowdown', errors: 'error spike', saturation: 'saturation' };
const KIND_WORD = { Doc: 'Doc', Ticket: 'Ticket', Message: 'Chat', Change: 'Change', Person: 'Person', Runbook: 'Runbook',
  Initiative: 'Initiative', design: 'Design', decision: 'Decision', postmortem: 'Postmortem', runbook: 'Runbook', chat: 'Chat',
  ticket: 'Ticket', status_update: 'Status update', service: 'Service', team: 'Team', person: 'Person', change: 'Change',
  incident: 'Incident', message: 'Chat', doc: 'Doc' };
// Tool names in words, so prose never shows snake_case; the names appear only next to their Cypher. Only the snake_case
// names are replaced in prose ("conclude" is also an ordinary English word).
const TOOL_WORD = { open_incident: 'opening the incident', correlate_alerts: 'the alert correlation', blast_radius: 'blast radius',
  page_on_call: 'paging', recall_similar: 'the memory search', hypothesize_from_memory: 'the memory check',
  propose_hypotheses: 'the change search', check_hypothesis: 'the suspect test', conclude: 'the final ranking',
  who_knows: 'who knows', warn_owners: 'heads-ups', post_update: 'the status update', incident_board: 'the incident board' };
const TOOL_RE = new RegExp(`\\b(${Object.keys(TOOL_WORD).filter((k) => k.includes('_')).join('|')})\\b`, 'g');
const PLURAL = { query: 'queries', dependency: 'dependencies', person: 'people', company: 'companies' };

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const enc = encodeURIComponent;
const plural = (n, word) => `${n} ${n === 1 ? word : PLURAL[word] || `${word}s`}`;
const nb = (n, word) => plural(n, word).replace(' ', ' '); // "2 alerts" never breaks across lines
const and = (xs) => (xs.length > 1 ? `${xs.slice(0, -1).join(', ')} and ${xs.at(-1)}` : xs[0] || '');
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
// Times are the viewer's local time; the zone is named once per view.
const fmt = (o) => new Intl.DateTimeFormat('en-GB', o);
const HM = fmt({ hour: '2-digit', minute: '2-digit' }), DM = fmt({ day: 'numeric', month: 'short' });
const DMY = fmt({ day: 'numeric', month: 'short', year: 'numeric' });
const hhmm = (at) => HM.format(new Date(at * 1000));
const dmon = (at) => DM.format(new Date(at * 1000));
const ZONE = (() => {
  const name = (s) => fmt({ timeZoneName: s }).formatToParts(new Date()).find((p) => p.type === 'timeZoneName')?.value || '';
  const s = name('short');
  return /^[A-Z]{2,5}$/.test(s) ? s : name('long') || s;
})();
// Server prose stamps times in UTC ("2026-10-20 04:00 UTC") and dates as ISO; show them in the viewer's zone.
const localTimes = (text) => String(text ?? '')
  .replace(/\b(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}) UTC\b/g, (_, y, mo, d, hh, mi) => {
    const at = Date.UTC(+y, mo - 1, +d, +hh, +mi) / 1000;
    return `${dmon(at)}, ${hhmm(at)} ${ZONE}`;
  })
  .replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, (_, y, mo, d) => DMY.format(new Date(Date.UTC(+y, mo - 1, +d, 12))));
const minutesBetween = (a, b) => Math.round(Math.abs(a - b) / 60);
const gap = (min) => (min < 120 ? `${min} min` : `${Math.round(min / 60)} hours`);
// Human text never shows graph id prefixes, arrows (the body font has no arrow glyph), tool names or the word
// "hypothesis"; a past incident it has learned the title of is named by it. A tool word that starts a sentence gets a
// capital letter.
const plain = (text) => String(text ?? '')
  .replace(/\binc:[A-Za-z0-9_-]+/g, (id) => (names.has(id) ? `“${names.get(id)}”` : id))
  .replace(/\b(svc|chg|inc|hyp|rb|alert|person|team|doc|ticket|msg|ev|init):/g, '')
  .replace(/ (?:->|→) /g, ' to ').replace(/\bhypotheses\b/g, 'suspects').replace(/\bhypothesis\b/g, 'suspect')
  .replace(/(\d+) more from the flat change log \(newest anywhere: ([^)]+)\)/g, '$1 more changed recently anywhere in the company (the newest: $2)')
  .replace(/\blive dependency path\b/g, 'current dependency path')
  .replace(TOOL_RE, (m, _w, at, s) => (at === 0 || /[.!?]\s+$/.test(s.slice(0, at)) ? cap(TOOL_WORD[m]) : TOOL_WORD[m]));
// An id of one kind in some text; an id never ends in the sentence's own punctuation ("svc:payments-gw." is payments-gw).
const idIn = (text, kind) => (String(text || '').match(new RegExp(`\\b${kind}:[A-Za-z0-9_-]+(?:[.:][A-Za-z0-9_-]+)*`)) || [null])[0];
const modelName = (by) => MODELS[by] || by || 'the rules';
const kindWord = (k) => KIND_WORD[k] || String(k || '').replace(/_/g, ' ');
const mobile = () => matchMedia('(max-width: 899px)').matches;
const nodeOf = (id) => state.graph?.nodes.find((n) => n.id === id) || null;
// The same alert stored twice (the webhook sample posted into the demo company) is one alert.
const distinct = (alerts) => [...new Map(alerts.map((a) => [`${a.service}|${a.name}|${a.at}`, a])).values()];
const recordedLink = (text, cls = null) => h('a', { class: cls, href: `${location.pathname}?offline=1` }, text);
const teamOf = (id) => nodeOf(id)?.team || null;

// running: an agent run is streaming; graphOwner: whose picture the graph shows (a run, 'ask', or null);
// wide: the reader asked for the whole company; askHl: the last answer's highlight (rebuilt whenever Ask is shown).
const state = { tenant: '', health: null, graph: null, alerts: [], runs: [], current: null, view: 'incidents',
  tab: 'answer', running: false, skip: false, chat: [], graphOwner: null, asking: false, loaded: false, loadError: null,
  confirmReset: null, askGraphOpen: false, askHl: null, askEles: null, wide: false, stale: false, zoneShown: false, frame: null,
  selectedStep: null };

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

// Re-rendering a block keeps what the reader was doing in it: the focused control (matched by data-key) and every
// open <details data-key>. A control that is gone hands focus to the incident title (or the selected inbox row).
const keyOf = (el) => el?.dataset?.key || (el?.tagName === 'SUMMARY' && el.parentElement?.dataset.key ? `>${el.parentElement.dataset.key}` : null);
const byKey = (box, key) => (!key ? null : key[0] === '>'
  ? box.querySelector(`details[data-key="${CSS.escape(key.slice(1))}"] > summary`) : box.querySelector(`[data-key="${CSS.escape(key)}"]`));
const focusKey = (key) => byKey(document, key)?.focus();
let pressed = null; // the keyed control under a press that is not released yet
addEventListener('pointerdown', (e) => { pressed = e.target.closest?.('[data-key]') || null; }, true);
addEventListener('pointerup', () => setTimeout(() => { pressed = null; }), true); // after the click it makes
addEventListener('pointercancel', () => { pressed = null; }, true);
function set(id, ...kids) {
  const box = $(id), a = document.activeElement, inside = box.contains(a) && a !== box, key = inside ? keyOf(a) : null;
  const open = new Set([...box.querySelectorAll('details[open][data-key]')].map((d) => d.dataset.key));
  const next = document.createDocumentFragment();
  next.append(...kids.flat(Infinity).filter((k) => k != null && k !== false));
  if (!keepPressed(box, next)) box.replaceChildren(next);
  for (const d of box.querySelectorAll('details[data-key]')) if (open.has(d.dataset.key)) d.open = true;
  if (inside && !box.contains(document.activeElement)) {
    const home = id === 'inbox' ? box.querySelector('[aria-current="true"]') : box.closest('#incident') ? $('inc-title') : null;
    (byKey(box, key) || home)?.focus({ preventScroll: true });
  }
}
// A run re-renders every step. A press that started before a re-render must still end in a click, and Chrome drops the
// click of a pressed node that leaves the document, even if it is put back. So when the pressed control renders the
// same, it and its ancestors stay where they are: each ancestor takes its new version's attributes, and everything
// around them is swapped for the new render. Returns false (render normally) when the control changed or moved.
function keepPressed(box, next) {
  const p = pressed;
  if (!p || p === box || !box.contains(p)) return false;
  const n = next.querySelector(`[data-key="${CSS.escape(p.dataset.key)}"]`);
  if (!n || n.outerHTML !== p.outerHTML) return false;
  const chain = (el, top) => { const xs = []; for (; el && el !== top; el = el.parentNode) xs.push(el); return xs; };
  const olds = chain(p, box), news = chain(n, next);
  if (olds.length !== news.length || olds.some((o, i) => o.tagName !== news[i].tagName)) return false;
  if (n._it) p._it = n._it;
  for (let i = olds.length - 1; i >= 0; i--) {
    const top = i === olds.length - 1, el = top ? box : olds[i + 1], fresh = top ? next : news[i + 1];
    if (!top) {
      for (const at of [...el.attributes]) if (!fresh.hasAttribute(at.name)) el.removeAttribute(at.name);
      for (const at of fresh.attributes) el.setAttribute(at.name, at.value);
    }
    const kids = [...fresh.childNodes], at = kids.indexOf(news[i]);
    for (const c of [...el.childNodes]) if (c !== olds[i]) c.remove();
    olds[i].before(...kids.slice(0, at));
    olds[i].after(...kids.slice(at + 1));
  }
  return true;
}
const skel = (...ws) => ws.map((w) => h('span', { class: `skel ${w}`, 'aria-hidden': 'true' }));
const linkBtn = (text, onclick, cls = '', key = null) => h('button', { class: `link ${cls}`, type: 'button', 'data-key': key, onclick }, text);

let toastTimer;
function toast(text, isError = false) {
  $('toast-text').textContent = text;
  $('toast').classList.toggle('error', isError);
  $('toast').hidden = false;
  announce(text);
  clearTimeout(toastTimer);
  if (!isError) toastTimer = setTimeout(() => { $('toast').hidden = true; }, 6000); // failures stay until closed
}
const announce = (text) => { $('sr-status').textContent = text; };

// ---------- API ----------
const T = () => `/api/tenants/${enc(state.tenant)}`;

async function api(method, path, body) {
  if (OFFLINE) return fixture(path);
  const r = await fetch(path, { method, headers: body ? { 'content-type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : {}; } catch { /* not JSON: a static host's page or a proxy's error page */ }
  if (!r.ok) {
    throw Object.assign(new Error(typeof data?.detail === 'string' ? data.detail : `${r.status} ${r.statusText}`),
      { body: data || {}, status: r.status });
  }
  if (data === null) throw Object.assign(new Error(`the server sent something that is not JSON (${r.status})`), { status: r.status, notJson: true });
  return data;
}

// Offline only act 1 has a recorded Confirm (resolve.json); the other acts say Confirm needs the live server.
const FIXTURES = [[/\/health$/, 'health'], [/\/alerts$/, 'alerts'], [/\/graph/, 'graph'], [/checkout-latency\/resolve$/, 'resolve'],
  [/checkout-latency\/respond/, 'act1'], [/refunds-latency\/respond/, 'act2'], [/subscriptions-latency\/respond/, 'act3']];

async function fixture(path) {
  const p = decodeURIComponent(path).split('?')[0];
  if (p.endsWith('/reset')) return { tenant: state.tenant, status: 'restored' };
  const hit = FIXTURES.find(([re]) => re.test(p));
  if (!hit) throw new Error(`this needs the live server (no recording of ${p})`);
  await sleep(200);
  const r = await fetch(new URL(`fixtures/${hit[1]}.json`, import.meta.url)); // relative: works on any static host
  if (!r.ok) throw new Error(`the recording ${hit[1]}.json did not load (${r.status})`);
  return r.json();
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
  // A run takes one to three minutes; a server that stalls past five frees the page (runAlert marks the run failed).
  const r = await fetch(path, { method: 'POST', signal: AbortSignal.timeout(300_000) });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(typeof d.detail === 'string' ? d.detail : `${r.status} ${r.statusText}`);
  }
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = '';
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buf += value;
      for (let i; (i = buf.indexOf('\n')) >= 0; buf = buf.slice(i + 1)) {
        if (buf.slice(0, i).trim()) yield JSON.parse(buf.slice(0, i));
      }
    }
  } finally {
    reader.cancel().catch(() => {}); // the consumer stopped early (an error event, a bad line): close the stream
  }
}

// ---------- runs and incidents ----------
// A run is one agent response to an alert, kept for this page's lifetime. An incident handled before the page was
// opened is loaded from the graph instead (GET /incidents/{id}): its outcome and steps with the queries each ran,
// without the live trace's rows and step data.
function newRun(alert, alerts, act) {
  return { alert, alerts, act, home: alert.service, incident: null, steps: [], res: null, ablation: null,
    resolved: null, picked: null, done: false, error: null, folded: alerts.length < 2, showAlt: false, saving: null,
    touched: G.empty(), cause: G.empty() };
}

const outcomeOf = (cur) => cur?.res?.outcome || null;
const isLive = (cur) => !!cur && typeof cur === 'object' && !cur.done && !cur.stored;
const isResolved = (cur) => !!cur?.resolved || cur?.status === 'resolved';

// One set of status words for the inbox, the landing and the slab: [class, the slab block, the detail].
const FOUND = ['found', 'Firing', 'cause found, fix pending'], HUMAN = ['human', 'Needs a human', 'no recent change explains it'];
// cur: a run or stored incident (may be null); row: the inbox row from GET /alerts (status, has_cause, has_update).
function statusOf(cur, row) {
  if (cur?.error) return ['error', 'Run failed', 'the agents could not finish'];
  if (cur && !cur.done) return ['working', 'Investigating', ''];
  if (isResolved(cur) || row?.status === 'resolved') return ['confirmed', 'Confirmed', ''];
  const o = outcomeOf(cur);
  if (o) return o.root_cause ? FOUND : HUMAN;
  if (row?.status) return row.has_cause ? FOUND : row.has_update ? HUMAN : ['working', 'Investigating', ''];
  return ['new', 'Not run yet', ''];
}
const statusWords = ([, block, detail]) => (detail ? `${block}: ${detail}` : block);
const BLOCK = { working: 'working', confirmed: 'confirmed', human: 'human', error: 'error' };

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
// A scenario's incident is confirmed: its alert's row says so, or a person confirmed it on this page.
const confirmedSc = (sc) => sc.trigger.status === 'resolved' || state.runs.some((r) => r.act === sc.act && isResolved(r));
// Act 2 is the same failure as act 1, and memory solves it only once act 1's cause is confirmed: the act 1 still waiting
// for that, if any (live only; the replay's act 2 was recorded after a confirm).
const waitingOn = (sc) => (!OFFLINE && sc?.act === 2 ? scenarios().find((s) => s.act === 1 && fired(s) && !confirmedSc(s)) || null : null);
const scenarioTitle = (sc) => (sc.alerts.length > 1 ? `${plural(sc.alerts.length, 'alert')} at once`
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
const triggerOf = (it) => it.run?.alert || it.fresh || it.alerts.find((a) => `inc:${short(a.id)}` === it.incident) || it.alerts.at(-1);
const rowKey = (it) => `row-${it.run ? `${it.run.alert.id}|${it.alerts[0]?.id}` : it.fresh ? it.fresh.id : it.incident}`;
const openItem = (it) => (it.run ? openRun(it.run) : it.fresh ? runAlert(it.fresh, [it.fresh], null) : openStored(it.incident));
const openRows = (rows = inboxItems()) => (state.loaded && !state.loadError ? rows.filter((it) => statusOf(it.run, it)[0] !== 'confirmed') : []);

// An alert storm is alerts on two or more services; two alerts on one service are one service, not a storm.
const realStorm = (o, home) => (o?.storm && new Set([home, ...o.storm.alerts.map((a) => a.service)]).size > 1 ? o.storm : null);
// The alerting services of an incident, distinct.
function alertingServices(cur) {
  const st = outcomeOf(cur)?.storm;
  return [...new Set([cur.home, ...(st?.alerts || []).map((a) => a.service), ...cur.alerts.map((a) => a.service)])];
}

// ---------- header: simulate menu ----------
// Under 900px the menu is a full-screen sheet, so while it is open it is modal: the page behind it is inert.
const sheetModal = (on) => {
  if (on) $('simulate-menu').setAttribute('aria-modal', 'true');
  else $('simulate-menu').removeAttribute('aria-modal');
  for (const el of [$('main'), document.querySelector('.views')]) el.inert = on;
};
function closeMenus(refocus = false) {
  if ($('simulate-menu').hidden) return;
  $('simulate-menu').hidden = true;
  sheetModal(false);
  $('btn-simulate').setAttribute('aria-expanded', 'false');
  if (state.confirmReset === 'menu') state.confirmReset = null;
  if (refocus) $('btn-simulate').focus();
}

function plannerLabel() {
  const p = state.health?.planner || '';
  return /deterministic|mock/i.test(p) || !p ? 'the rules' : modelName(p.split(' ')[0]);
}
const modelDecides = () => !/deterministic|mock/i.test(state.health?.planner || 'mock');
const plannerSentence = () => (modelDecides() ? `${plannerLabel()} chooses each step.` : 'Rules choose each step (no model key is set).');
const isDemo = () => state.tenant === (state.health?.default_tenant || 'acme');
const companyLabel = () => (isDemo() ? 'the demo company' : state.tenant);
const dbDown = () => !OFFLINE && ((state.health && !state.health.falkordb) || !!state.loadError?.db);

// Reset deletes a company's incidents and memory, so it asks in place first, with keeping it as the default (filled,
// and focused). where: 'menu' | 'connect'. Nothing loaded (an unknown company): no reset, which would create it.
function resetControl(where) {
  if (state.loadError) return null;
  const what = `Reset ${isDemo() ? 'demo company' : state.tenant}`;
  if (state.confirmReset !== where) {
    return linkBtn(what, () => { state.confirmReset = where; rerenderReset(where); focusKey(`reset-no-${where}`); }, 'quiet', `reset-${where}`);
  }
  return h('div', { class: 'confirm-inline', role: 'group', 'aria-label': 'Confirm reset' },
    h('p', {}, `Reset ${companyLabel()}? Every incident, confirmed cause and learned fix on it is deleted and the demo data is loaded again.`),
    h('div', { class: 'row-btns' },
      h('button', { class: 'btn fill small', type: 'button', 'data-key': `reset-no-${where}`, onclick: () => cancelReset() }, 'Keep it'),
      h('button', { class: 'btn small', type: 'button', disabled: state.running, 'data-key': `reset-yes-${where}`,
        onclick: () => { state.confirmReset = null; closeMenus(); doReset(); } }, what)));
}
const rerenderReset = (where) => (where === 'menu' ? renderSimulateMenu() : renderConnect());
function cancelReset() {
  const where = state.confirmReset;
  if (!where) return false;
  state.confirmReset = null;
  rerenderReset(where);
  focusKey(`reset-${where}`);
  return true;
}

function renderSimulateMenu() {
  const list = scenarios(), next = nextScenario();
  const svcs = [...(state.graph?.nodes || [])].sort((a, b) => a.name.localeCompare(b.name));
  const custom = OFFLINE || !state.graph ? null : h('details', { class: 'custom', 'data-key': 'custom' },
    h('summary', {}, 'Raise a custom alert'),
    h('form', { class: 'custom-form', onsubmit: (e) => { e.preventDefault(); closeMenus(); raiseCustom(e.target); } },
      h('label', {}, 'Service', h('select', { name: 'service', required: true }, svcs.map((n) => h('option', { value: n.id }, n.name)))),
      h('label', {}, 'Symptom', h('select', { name: 'symptom' }, ['latency', 'errors', 'saturation'].map((s) => h('option', { value: s }, s)))),
      h('label', {}, 'Alert name', h('input', { type: 'text', name: 'name', maxlength: 200, placeholder: 'cart 5xx above 1%', required: true })),
      h('button', { class: 'btn fill', type: 'submit', disabled: state.running }, 'Raise it and run the agents')));
  set('simulate-menu',
    h('div', { class: 'menu-head' },
      h('div', { class: 'menu-title' }, h('h2', {}, OFFLINE ? 'Replay an incident' : 'Simulate an incident'),
        h('button', { class: 'link menu-close', type: 'button', 'data-key': 'menu-close', onclick: () => closeMenus(true) }, 'Close')),
      h('p', {}, OFFLINE ? 'Replays a recorded run of the real agents on the demo company. There is no database behind this page.'
        : 'Fires a scripted alert on the demo company. The three agents then work it live on the graph, step by step; a run takes a minute or two.')),
    list.length ? h('ol', { class: 'scenarios' }, list.map((sc, i) => {
      const done = fired(sc), isNext = sc.act === next?.act, wait = isNext && waitingOn(sc);
      return h('li', { class: done ? 'done' : null }, h('span', { class: 'num' }, i + 1),
        h('div', {}, h('b', {}, scenarioTitle(sc)), h('p', {}, SCENARIO_NOTE[sc.act] || ''),
          wait ? h('p', { class: 'wait' }, 'Confirm the cause of scenario 1 first, or memory has nothing to recall.') : null),
        done ? h('span', { class: 'done-word' }, OFFLINE ? 'Replayed' : confirmedSc(sc) ? 'Confirmed' : 'Ran, not confirmed')
          : h('button', { class: `btn small${isNext && !wait ? ' fill' : ''}`, type: 'button', disabled: state.running, 'data-key': `sc-${sc.act}`,
            onclick: () => { closeMenus(); fire(sc.act); } }, OFFLINE ? 'Replay' : 'Simulate'));
    })) : h('p', { class: 'menu-head muted' }, 'This company has no scripted scenarios.'),
    custom,
    h('div', { class: 'menu-foot' }, h('p', { class: 'muted' }, `${plannerSentence()} Company: ${companyLabel()}.`),
      OFFLINE ? null : resetControl('menu')));
}

// Why the header button is disabled, in words (title and aria-describedby), or '' when it works.
function simButtonState() {
  const why = state.running ? 'A run is in progress; it takes a minute or two.' : dbDown() ? 'FalkorDB is not reachable, so nothing can be simulated.'
    : state.loadError ? 'This company could not load, so nothing can be simulated here.' : '';
  $('btn-simulate').disabled = !!why;
  $('btn-simulate').title = why;
  $('sim-why').textContent = why;
}

// ---------- inbox, health line, landing ----------
function inboxRow(it) {
  const st = statusOf(it.run, it), trigger = triggerOf(it);
  const svcs = [...new Set(it.alerts.map((a) => short(a.service)))];
  const team = teamOf(trigger.service), n = distinct(it.alerts).length;
  const inTitle = svcs.length === 1 && trigger.name.toLowerCase().startsWith(svcs[0]); // the title already names it
  const where = svcs.length > 1 ? `${nb(n, 'alert')} on ${and(svcs)}, folded into one incident`
    : [inTitle ? null : svcs[0], team ? `${team} team` : null, n > 1 ? nb(n, 'alert') : null].filter(Boolean).join(', ');
  const cur = state.current;
  const selected = !!cur && (cur === it.run || (!!it.incident && cur.incident === it.incident));
  const btn = h('button', { class: 'row-btn', type: 'button', title: trigger.name, 'aria-current': selected ? 'true' : null,
    'data-key': rowKey(it), onclick: () => openItem(it) },
  h('span', {}, h('span', { class: 'num' }, hhmm(trigger.at)), h('span', { class: 'date' }, dmon(trigger.at))),
  h('span', {}, h('span', { class: 'title' }, st[0] !== 'confirmed' ? h('span', { class: 'mark', 'aria-hidden': 'true' }) : null, trigger.name),
    where ? h('span', { class: 'where' }, where) : null,
    h('span', { class: 'state' }, it.fresh ? 'Not run yet. Open it to run the agents.' : statusWords(st))));
  btn._it = it;
  return h('li', {}, btn);
}
const rowFor = (cur) => (cur ? [...$('inbox').querySelectorAll('.row-btn')]
  .find((b) => b._it.run === cur || (!!cur.incident && b._it.incident === cur.incident)) : null);

function renderInbox(rows = state.loaded && !state.loadError ? inboxItems() : []) {
  const box = $('view-incidents');
  if (!state.loaded) {
    box.classList.remove('inbox-first');
    return set('inbox', h('div', { class: 'rail-group' }, h('h2', {}, 'Open'),
      [1, 2, 3].map(() => h('div', { class: 'rail-skel' }, skel('w40 tall', 'w80', 'w60')))));
  }
  if (state.loadError) {
    box.classList.remove('inbox-first');
    return set('inbox', h('div', { class: 'rail-empty' }, h('b', {}, 'No incidents to show.'),
      h('p', {}, state.loadError.db ? 'The list needs FalkorDB; the notice says how to start it.' : 'The list could not load; the error message says why.')));
  }
  const open = openRows(rows), done = rows.filter((it) => !open.includes(it));
  box.classList.toggle('inbox-first', rows.length > 0);
  const group = (title, items, emptyText) => h('section', { class: 'rail-group', 'aria-label': title },
    h('h2', {}, title, h('span', { class: 'num' }, items.length)),
    items.length ? h('ul', {}, items.map(inboxRow)) : h('p', { class: 'rail-empty' }, h('span', { class: 'muted small' }, emptyText)));
  set('inbox', rows.length ? [group('Open', open, 'Nothing open right now.'), done.length ? group('Confirmed', done) : null]
    : h('div', { class: 'rail-group' }, h('h2', {}, 'Open', h('span', { class: 'num' }, 0)),
      h('div', { class: 'rail-empty' }, h('b', {}, 'No incidents yet.'),
        h('p', {}, `Alerts from your monitoring land here, and the agents start on them. ${OFFLINE ? 'Replay' : 'Simulate'} one to see how it works.`))));
}

function renderHealth(rows = state.loaded && !state.loadError ? inboxItems() : []) {
  const hl = state.health;
  const times = rows.length > 0; // the list shows times
  const zone = !times || state.current || state.zoneShown ? '' : ` Times are in ${ZONE}.`;
  set('health', OFFLINE ? [`A recorded replay of real runs; ${plannerLabel()} chose the steps. There is no database behind this page.`, zone]
    : !hl ? '' : [hl.falkordb ? 'FalkorDB is connected. ' : h('span', { class: 'down' }, 'FalkorDB is not reachable. '),
      `${plannerSentence()} Company: ${state.loadError ? 'none loaded' : companyLabel()}.`, zone, state.stale ? ' The list could not refresh, so it may be out of date.' : '']);
}

function renderNotice() {
  const hl = state.health, down = !OFFLINE && !!hl && !hl.falkordb;
  const msg = down ? hl.falkordb_error || 'down' : '';
  $('notice').hidden = !down;
  if ($('notice').dataset.msg === msg) return; // same notice: do not rebuild or announce it again
  $('notice').dataset.msg = msg;
  if (!down) return set('notice');
  set('notice', h('p', {}, h('b', {}, 'FalkorDB is not reachable, so incidents cannot load and Simulate is off. '), 'Start FalkorDB with ',
    h('code', {}, 'make db'), ', then reload this page.'),
  h('p', {}, 'Or watch the agents work a recorded run, with no database: ', recordedLink('Open the replay'), '.'),
  hl.falkordb_error ? h('details', { 'data-key': 'raw' }, h('summary', {}, 'What the server said'), h('pre', {}, hl.falkordb_error)) : null);
  announce('FalkorDB is not reachable, so incidents cannot load.');
}

const demoLink = () => {
  const p = new URLSearchParams(location.search);
  p.delete('tenant');
  return h('p', {}, h('a', { class: 'btn fill', href: `${location.pathname}${p.size ? `?${p}` : ''}` }, 'Open the demo company'));
};

function errorBlock(err) {
  return h('div', { class: 'error-block' }, h('h2', {}, err.title), h('p', {}, err.hint), err.action || null,
    err.raw ? h('details', { 'data-key': 'raw' }, h('summary', {}, 'What the server said'), h('pre', {}, err.raw)) : null);
}

function describeLoadError(e) {
  if (!OFFLINE && state.health && !state.health.falkordb) return { db: true };
  if (e.status === 404 && /unknown tenant/.test(e.message)) {
    return { title: `There is no company called “${state.tenant}” here.`,
      hint: 'This link names a company the brain has no graph for. Open the demo company instead.', action: demoLink(), raw: e.message };
  }
  return { title: 'The incidents could not load.', hint: 'Reload the page in a moment. If it keeps failing, the server log has the reason.', raw: e.message };
}

// The newest open incident as a compact slab that opens it, so a paged engineer's first click is obvious. One control:
// the slab is the button. wait: the next scenario waits on this incident's confirm.
function readout(it, count, wait) {
  const st = statusOf(it.run, it), t = triggerOf(it), node = nodeOf(t.service);
  return h('div', { class: 'readout-wrap' },
    h('button', { class: 'slab readout', type: 'button', 'data-key': 'open-newest', onclick: () => openItem(it) },
      h('span', { class: 'slab-top' }, h('span', { class: `state-block ${BLOCK[st[0]] || 'firing'}` }, st[1]),
        st[2] ? h('span', {}, st[2]) : null, h('span', { class: 'num' }, hhmm(t.at)), h('span', {}, `${dmon(t.at)}, ${ZONE}`)),
      h('span', { class: 'readout-title' }, t.name),
      h('span', { class: 'where-line' }, node ? `${short(t.service)}, owned by the ${node.team} team.` : short(t.service),
        count > 1 ? ` ${plural(count - 1, 'more open incident')} in the list.` : ''),
      h('span', { class: 'readout-go' }, wait ? 'Open it and confirm the cause' : count > 1 ? 'Open the newest incident' : 'Open incident')));
}

function renderLanding(rows = state.loaded && !state.loadError ? inboxItems() : []) {
  const next = nextScenario(), g = state.graph, list = scenarios(), open = openRows(rows), wait = waitingOn(next);
  state.zoneShown = open.length > 0 && !mobile(); // the readout names the zone; on phone it gives way to the inbox row above
  let action;
  if (!state.loaded) action = h('div', { class: 'cta-row' }, skel('w40 tall'));
  else if (state.loadError?.db) action = null; // the notice at the top says what to do
  else if (state.loadError) action = errorBlock(state.loadError);
  else if (next) {
    // While act 1 waits for its confirm, simulating act 2 is still offered, but as the secondary action, with the reason.
    action = [wait ? h('p', { class: 'cta-wait' }, h('b', {}, `Confirm the cause of “${wait.trigger.name}” first.`), ' The next scenario is the same '
      + 'failure, and memory solves it only once a person has confirmed the cause.') : null,
    h('div', { class: 'cta-row' },
      h('button', { class: `btn${open.length ? '' : ' fill'}`, type: 'button', disabled: state.running, 'data-key': 'sim-next', onclick: () => fire(next.act) },
        h('span', {}, h('span', { class: 'wide-only' }, OFFLINE ? 'Replay an incident' : 'Simulate an incident'),
          h('span', { class: 'narrow-only' }, OFFLINE ? 'Replay' : 'Simulate'), `: ${scenarioTitle(next).toLowerCase()}`)),
      linkBtn('Connect your alerts', () => showView('connect', true), '', 'connect-link'))];
  } else {
    action = h('p', { class: 'cta-note' }, list.length ? `All ${plural(list.length, 'demo scenario')} have run on this company. Open one from the list`
      : 'Open an incident from the list', OFFLINE ? '.' : [', or raise a custom alert from Simulate an incident. ',
      linkBtn('Connect your alerts', () => showView('connect', true), 'quiet', 'connect-link'), ' to work real ones.']);
  }
  const step = (n, title, text) => h('li', {}, h('span', { class: 'num' }, n), h('div', {}, h('b', {}, title), h('p', {}, text)));
  const teams = g ? new Set(g.nodes.map((n) => n.team).filter(Boolean)).size : 0;
  const demo = isDemo();
  set('landing',
    open.length ? readout(open[0], open.length, !!wait && open[0].alerts.some((a) => a.id === wait.trigger.id)) : null,
    h('h1', { id: 'landing-title', tabindex: '-1' }, 'What broke, why, who is paged and the fix, with the proof from your company graph.'),
    h('p', { class: 'lede' }, 'When an alert fires, three agents read your company graph: what depends on what, who owns it, what changed '
      + 'and what fixed it last time. They answer here, with the evidence. Confirm the cause and the graph remembers it for the next incident.'),
    action,
    h('ol', { class: 'how', 'aria-label': 'How it works' },
      step(1, 'An alert fires', 'From your monitoring through the webhook, or simulated here.'),
      step(2, 'Three agents work it on the graph', 'Triage finds who is hurt and pages on-call. The investigator tests every recent '
        + 'change against the dependency paths. Comms writes the status update, with sources.'),
      step(3, 'You confirm, the graph remembers', 'Your call is written to the graph, so the next incident like it starts from the fix that worked.')),
    g && !state.loadError ? h('p', { class: 'facts' }, `${demo ? 'The demo company' : 'This company'} has ${plural(g.nodes.length, 'service')}, `
      + `${plural(teams, 'team')} and ${plural(g.edges.length, 'dependency')}${demo ? ', all synthetic' : ''}. Each company has its own graph in FalkorDB.`) : null);
}

// ---------- one incident: what the run knows ----------
// The change a person picked under Wrong cause, when it is not the agents' pick (from the outcome's other suspects).
function pickedAlt(cur, o) {
  if (!cur?.picked || !o || cur.picked === o.root_cause?.change) return null;
  return [...(o.refuted || []), ...(o.co_causes || []), o.baseline_pick, o.anomaly_baseline_pick].find((r) => r?.change === cur.picked)
    || { change: cur.picked, service: null, summary: '' };
}

// What the run knows so far (live) or knew at the end (final): one shape for both, so the answer can render while
// the agents work and fill in as steps land. Computed once per render and passed to every block.
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
  const paged = o ? o.paged : data('page_on_call').filter((d) => d.person);
  const agentsRc = o ? o.root_cause : (conclude?.leading ? suspects.get(conclude.leading) : checks.find((c) => c.verdict === 'supports')) || null;
  const alt = pickedAlt(cur, o), rc = alt || agentsRc;
  const posted = data('post_update')[0];
  // The minute each service on the cause path went red: the anomalies_between rows of the check that supported it.
  const support = rc && steps.find((s) => s.tool === 'check_hypothesis' && s.data?.change === rc.change);
  const anomalies = (support?.queries || []).find((q) => q.name === 'anomalies_between')?.rows || [];
  const knows = data('who_knows')[0] || [];
  const expert0 = o?.expert || posted?.expert || knows[0] || expertFromSummary(steps);
  const expert = expert0 && { ...knows.find((k) => k.person === (expert0.person || expert0.id)), ...expert0 };
  const refuted = o ? o.refuted : [...suspects.values()].filter((s) => s.verdict === 'refutes');
  return {
    o, rc, overruled: alt ? agentsRc : null, suspects: [...suspects.values()], broke, paged, anomalies, expert, refuted,
    tested: o ? (o.hypotheses_checked || refuted.length + (o.co_causes?.length || 0) + (agentsRc ? 1 : 0)) : checks.length,
    atRisk: o ? o.at_risk.map(short) : [],
    warned: o ? o.warned : data('warn_owners').flat(),
    runbook: o?.runbook || posted?.runbook || null,
    recalled: o ? o.memory.recalled[0] : data('recall_similar')[0]?.find((r) => r.score >= 3) || null,
    solvedByMemory: !!o?.memory.solved_by_memory,
    sources: o?.sources || [],
    update: cur.resolved?.update_text || o?.update_text || posted?.text || null,
  };
}

// A stored run keeps no step data, but its who_knows summary still names the expert ("Sana Brandt (Payments): 3 changes, …").
function expertFromSummary(steps) {
  const s = steps.find((x) => x.tool === 'who_knows'), m = String(s?.summary || '').match(/^(.+?) \(([^)]+)\): (\d+) changes?\b/);
  return m ? { name: m[1], team: m[2], changes: Number(m[3]), service: svcOf(s) } : null;
}
// The service a step is about: its target, else the first service id in its highlight, summary or reason.
const svcOf = (s) => (s?.target?.startsWith('svc:') && s.target) || s?.highlight?.nodes?.find((id) => kindOf(id) === 'svc')
  || idIn(s?.summary, 'svc') || idIn(s?.reason, 'svc') || null;
// ponytail: an id for a person the API named without one, from the demo data's person:first-last convention.
const personId = (name) => `person:${String(name).toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;

// ---------- one incident: the slab ----------
const firstAlertAt = (cur) => Math.min(cur.alert.at, ...cur.alerts.map((a) => a.at)); // a storm counts from its first alert
function renderSlab(cur, f) {
  const st = statusOf(cur, null), rc = f.rc, at = cur.alert.at, node = nodeOf(cur.home);
  const first = firstAlertAt(cur), storm = alertingServices(cur).length > 1;
  const counts = [];
  // One stable headline number: minutes from the change to the (first) alert (the anomaly minute when no change is known).
  if (rc?.at) counts.push([minutesBetween(rc.at, first), storm ? 'min from change to first alert' : 'min from change to alert']);
  else if (f.anomalies.length) counts.push([minutesBetween(Math.min(...f.anomalies.map((a) => a.first_at)), first), 'min from first anomaly to alert']);
  counts.push([f.broke.length, f.broke.length === 1 ? 'service hurt' : 'services hurt']);
  counts.push([f.tested, f.tested === 1 ? 'suspect tested' : 'suspects tested']);
  counts.push([f.paged.length, f.paged.length === 1 ? 'person paged' : 'people paged']);
  const last = cur.steps.at(-1);
  set('slab',
    h('div', { class: 'slab-top' },
      h('span', { class: `state-block ${BLOCK[st[0]] || 'firing'}` }, st[0] === 'working' ? h('span', { class: 'indicator', 'aria-hidden': 'true' }) : null, st[1]),
      st[2] && st[0] !== 'error' ? h('span', {}, st[2]) : null,
      h('span', { class: 'num' }, hhmm(at)), h('span', {}, `${dmon(at)}, ${ZONE}`)),
    h('h1', { id: 'inc-title', tabindex: '-1', 'data-key': 'inc-title' }, cur.alert.name),
    h('p', { class: 'where-line' }, node ? `${short(cur.home)}, tier ${node.tier}, owned by the ${node.team} team.` : short(cur.home)),
    stormLine(cur),
    isLive(cur) ? h('div', { class: 'slab-live' },
      h('p', {}, last ? [h('b', {}, `${ROLE_NAME[last.role]}: `), plain(last.reason)] : 'Opening the incident on the shared board.'),
      h('button', { class: 'btn on-ink small', type: 'button', 'aria-disabled': state.skip ? 'true' : null, 'data-key': 'skip',
        onclick: () => { if (!state.skip) { state.skip = true; renderSlab(cur, facts(cur)); } } },
      state.skip ? 'Skipping ahead' : OFFLINE ? 'Skip the replay' : 'Skip to answer')) : null,
    cur.error ? h('div', { class: 'slab-live' }, h('p', {}, h('b', {}, 'The agents could not finish. '), plain(cur.error))) : null,
    h('div', { class: 'counts' }, counts.map(([n, label]) => h('div', {}, h('span', { class: 'num' }, n), h('span', {}, label)))));
}

function stormLine(cur) {
  const svcs = alertingServices(cur).map(short);
  if (svcs.length > 1) {
    const ats = cur.alerts.map((a) => a.at), span = minutesBetween(Math.min(...ats), Math.max(...ats));
    const shared = (realStorm(outcomeOf(cur), cur.home)?.shared || []).slice(0, 2).map((s) => short(s.service));
    return h('p', { class: 'storm-line' }, `${plural(svcs.length, 'alert')}, 1 incident: ${and(svcs)} fired within ${plural(span || 1, 'minute')}`,
      shared.length ? ` and share ${and(shared)} upstream.` : '.');
  }
  const n = distinct(cur.alerts).length;
  return n > 1 ? h('p', { class: 'storm-line' }, `${plural(n, 'alert')} on ${svcs[0]}, folded into this incident.`) : null;
}

// ---------- one incident: the two decisions ----------
function alternatives(o, rc) {
  const seen = new Set([rc?.change]);
  return o ? [...o.refuted, ...(o.co_causes || []), o.baseline_pick, o.anomaly_baseline_pick]
    .filter((r) => r && !seen.has(r.change) && seen.add(r.change))
    .map((r) => ({ ...r, tag: r.tag && r.tag !== 'outranked' ? r.tag : r.tag === 'outranked' ? 'explains fewer alerts' : 'not on a tested dependency path' })) : [];
}

function closeAlts(cur) {
  cur.showAlt = false;
  renderActs(cur, facts(cur));
  focusKey('wrong');
}

function renderActs(cur, f) {
  const rc = f.rc, busy = !!cur.saving || (state.running && !cur.done);
  const alts = alternatives(f.o, rc), kids = [];
  const needsLive = OFFLINE && cur.act !== 1; // only act 1's Confirm is recorded
  const dis = busy ? 'true' : null;
  if (f.o && cur.incident && !isResolved(cur)) {
    if (needsLive) kids.push(h('p', { class: 'acts-note' }, 'Confirming this one needs the live server.'));
    else {
      if (rc) {
        kids.push(h('button', { class: 'btn fill', type: 'button', 'aria-disabled': dis, 'data-key': 'confirm',
          onclick: () => { if (!busy) resolve(cur, rc.change); } }, cur.saving === rc.change ? 'Saving…' : 'Confirm cause'));
      }
      if (alts.length) {
        kids.push(h('button', { class: 'btn', type: 'button', 'aria-disabled': dis, 'aria-expanded': String(!!cur.showAlt), 'aria-controls': 'alts',
          'data-key': 'wrong', onclick: () => {
            if (busy) return;
            cur.showAlt = !cur.showAlt;
            renderActs(cur, facts(cur));
            if (cur.showAlt && mobile()) $('alts').scrollIntoView({ block: 'start' });
          } }, rc ? 'Wrong cause' : 'Pick the cause'));
      }
    }
  }
  set('acts', kids);
  $('incident').classList.toggle('has-acts', kids.length > 0);
  syncBody();
  set('alts', cur.showAlt && alts.length && kids.length && !needsLive ? h('div', { class: 'alts-box', role: 'group', 'aria-label': 'Pick the cause' },
    h('p', {}, h('b', {}, 'Which change really caused it? '), 'Your choice is written to the graph and becomes memory for the next incident.'),
    h('ul', {}, alts.map((r) => h('li', {},
      h('span', {}, h('b', {}, short(r.change)), ` on ${short(r.service)}: ${plain(r.summary || '')}`, h('span', { class: 'tag' }, r.tag)),
      h('button', { class: 'btn small', type: 'button', 'aria-disabled': dis, 'data-key': `pick-${r.change}`,
        onclick: () => { if (!busy) resolve(cur, r.change); } }, cur.saving === r.change ? 'Saving…' : 'This one')))),
    h('div', { class: 'alts-foot' },
      h('p', { class: 'small muted' }, 'None of these? Close this and nothing is saved: the incident stays open for a person to work.'),
      h('button', { class: 'btn small', type: 'button', 'data-key': 'alts-cancel', onclick: () => closeAlts(cur) }, 'Cancel'))) : null);
}

// ---------- one incident: the three agents while they work ----------
function renderProgress(cur) {
  if (!isLive(cur)) return set('progress');
  const steps = cur.steps || [];
  const handed = new Set(steps.filter((s) => s.tool === 'handoff').map((s) => s.role));
  const working = ROLES.find((r) => !handed.has(r));
  set('progress', h('div', { class: 'strip', role: 'group', 'aria-label': 'The three agents' }, ROLES.map((role, i) => {
    const mine = steps.filter((s) => s.role === role && s.tool !== 'handoff');
    const st = handed.has(role) ? 'done' : role === working ? 'working' : 'waiting';
    const text = st === 'waiting' ? ROLE_JOB[role] : mine.length ? stepResult(mine.at(-1)) : 'Reading the incident board.';
    return h('div', { class: `cell ${st}` }, h('div', { class: 'cell-head' }, h('span', { class: 'num' }, i + 1), h('b', {}, ROLE_NAME[role]),
      h('span', { class: 'state-word' }, st)), h('p', {}, text));
  })));
}

// ---------- one incident: the dispatch rows ----------
const kindOfChange = (k) => (k === 'deploy' ? 'Deploy' : k ? 'Config change' : 'Change');
const pathOf = (rc) => (rc?.live_path?.length > 1 ? [...rc.live_path].reverse() : null); // change side first

function causeRow(cur, f) {
  const rc = f.rc, o = f.o, conf = o?.confidence, live = isLive(cur), resolved = isResolved(cur);
  // The comparison is with the same alert run again with memory switched off, both numbers set as numerals.
  const vs = (n, one, many, was) => h('div', {}, h('span', { class: 'num' }, n), h('span', {}, n === 1 ? one : many),
    h('span', {}, 'instead of'), h('span', { class: 'num was' }, was));
  const without = cur.ablation?.without_memory;
  const memory = f.recalled && f.solvedByMemory ? h('div', { class: 'memory' },
    h('p', {}, h('b', {}, 'Solved from memory. '), `“${f.recalled.title}” was fixed with “${f.recalled.runbook_title}”, so that fix was tested first.`),
    without ? [h('div', { class: 'pair' }, vs(o.investigator_calls, 'investigator step', 'investigator steps', without.investigator_calls),
      vs(o.hypotheses_checked, 'suspect tested', 'suspects tested', without.hypotheses_checked)),
    h('p', { class: 'small muted' }, 'Compared with the same alert, run again with memory switched off.')]
      : cur.act === 2 && !cur.stored ? h('p', { class: 'small muted' }, 'Running the same alert again with memory switched off, for comparison.') : null)
    : f.recalled && (o || cur.steps.some((s) => s.tool === 'propose_hypotheses'))
      ? h('p', { class: 'small muted' }, `Seen something like this before: “${f.recalled.title}”. Its fix did not apply here, so the search widened.`) : null;
  if (!rc) {
    return live ? [skel('w80 tall', 'w60'), h('p', { class: 'small muted' }, 'The investigator is testing the suspects. The leading one appears here.')]
      : [h('p', { class: 'lead' }, 'No recent change explains this alert.'),
        h('p', {}, 'A human should look. The suspects the agents tested are listed under Ruled out.'), memory];
  }
  const first = firstAlertAt(cur), which = alertingServices(cur).length > 1 ? 'the first alert' : 'the alert'; // same minutes as the slab
  const before = rc.at ? ` at ${hhmm(rc.at)}${dmon(rc.at) !== dmon(first) ? ` on ${dmon(rc.at)}` : ''}, ${gap(minutesBetween(rc.at, first))} before ${which}` : '';
  const ov = f.overruled;
  return [
    h('p', { class: 'lead' }, h('b', {}, short(rc.service || rc.change)), rc.summary ? `: ${plain(rc.summary)}` : ''),
    rc.kind || rc.author || rc.at ? h('p', {}, `${kindOfChange(rc.kind)}${rc.author ? ` by ${rc.author}` : ''}${before}.`) : null,
    resolved ? h('p', { class: 'conf-line' }, h('span', { class: 'conf confirmed' }, 'Confirmed'),
      ov ? `You picked this cause; the agents had blamed ${short(ov.change)} on ${short(ov.service)}.`
        : cur.resolved ? 'You confirmed this cause.' : 'A person confirmed this cause.')
      : live ? h('p', { class: 'conf-line' }, h('span', { class: 'conf' }, 'Leading suspect'), 'Supported so far; the agents are still testing the others.')
        : conf ? h('p', { class: 'conf-line' }, h('span', { class: 'conf' }, conf.label),
          conf.level === 'high' && f.tested > 1 ? `${f.refuted.length} of ${f.tested} suspects ruled out; ${plain(conf.why)}.` : `${cap(plain(conf.why))}.`) : null,
    memory];
}

function whereRow(cur, f) {
  const rc = f.rc, live = isLive(cur), alerting = new Set(alertingServices(cur)), path = pathOf(rc);
  const now = !isResolved(cur); // red means broken right now; a confirmed incident's boxes and times go back to ink
  const red = new Map(f.anomalies.map((a) => [a.service, a]));
  const others = f.broke.filter((s) => !alerting.has(`svc:${s}`));
  const sym = SYMPTOM_WORD[cur.alert.symptom] || 'problem';
  const tcls = now ? 't sig' : 't';
  const out = [];
  if (path) {
    const items = [h('li', {}, h('span', { class: 'box change' }, kindOfChange(rc.kind), h('span', { class: 'id' }, short(rc.change))),
      rc.at ? h('span', { class: 't' }, hhmm(rc.at)) : null, rc.author ? h('span', { class: 'm' }, `by ${rc.author}`) : null)];
    for (const s of path) {
      const an = red.get(s), al = alerting.has(s) && cur.alerts.find((a) => a.service === s);
      items.push(h('li', {}, h('span', { class: `box${alerting.has(s) ? (now ? ' alerting' : ' was-alerting') : ''}` }, short(s)),
        an ? [h('span', { class: tcls }, hhmm(an.first_at)), h('span', { class: 'm' }, plain(an.summary))] : null,
        al ? [h('span', { class: tcls }, hhmm(al.at)), h('span', { class: 'm' }, 'alert fired')] : null));
    }
    out.push(h('ol', { class: `wire${items.length > 5 ? ' vertical' : ''}`, 'aria-label': 'Evidence path, from the change to the alert' }, items));
    out.push(h('p', {}, `The ${sym} travels from ${path.map(short).join(' to ')}, the same path the alert came up.`,
      rc.gaps?.length ? ` Nothing was recorded on ${and(rc.gaps.map(short))} along the way, a monitoring gap.` : '',
      rc.explained?.length > 1 ? ` It explains all ${plural(rc.explained.length, 'alerting service')}.` : ''));
  } else if (live) out.push(...skel('w60 tall', 'w40'));
  if (alerting.size > 1) out.push(h('p', {}, `${now ? 'Alerting' : 'Alerted'}: ${and([...alerting].map(short))}.`));
  if (others.length || f.atRisk.length) {
    out.push(h('p', {}, others.length ? `Also hurt: ${and(others)}.` : '', others.length && f.atRisk.length ? ' ' : '',
      f.atRisk.length ? `At risk: ${and(f.atRisk)}.` : ''));
  }
  if (!out.length) out.push(h('p', { class: 'muted' }, 'No other service is affected in the graph.'));
  return out;
}

function sinceRow(cur, f) {
  const rc = f.rc, now = !isResolved(cur);
  if (!rc && !f.anomalies.length) return null;
  const events = [];
  if (rc?.at) events.push([rc.at, `${kindOfChange(rc.kind).toLowerCase()} lands on ${short(rc.service)}`, false]);
  for (const a of f.anomalies) events.push([a.first_at, `${short(a.service)}: ${plain(a.summary)}`, now]);
  const seen = new Set();
  for (const a of cur.alerts) if (!seen.has(a.service) && seen.add(a.service)) events.push([a.at, `alert fires on ${short(a.service)}`, now]);
  if (events.length < 2) return null;
  events.sort((x, y) => x[0] - y[0]);
  return h('div', { class: 'timeline' }, events.map(([at, text, sig]) => [h('span', { class: `t${sig ? ' sig' : ''}` }, hhmm(at)), h('span', {}, text)]));
}

function whoRow(cur, f) {
  const live = isLive(cur), rows = [];
  const of = (handle, team) => ` ${[handle, team && short(team)].filter(Boolean).join(', ')}`;
  for (const p of f.paged) rows.push(['Paged', p.name, `${of(p.handle, p.team_name || p.team)}${p.service ? `, on call for ${short(p.service)}` : ''}`]);
  for (const w of f.warned) rows.push(['Heads-up', w.name, `${of(w.handle, w.team_name || w.team)}, which owns ${short(w.service)}`]);
  const e = f.expert, svc = short(e?.service || f.rc?.service || cur.home);
  if (e) {
    rows.push(['Knows it best', e.name, `${of(e.handle, e.team)}${e.changes != null
      ? `: ${plural(e.changes, 'change')}${e.docs != null ? ` and ${plural(e.docs, 'doc')}` : ''} on ${svc}` : `, knows ${svc} best`}`]);
  }
  if (!rows.length) return live ? skel('w60', 'w40') : h('p', { class: 'muted' }, 'Nobody was paged.');
  return h('ul', { class: 'people' }, rows.map(([k, name, rest]) => h('li', {}, h('span', {}, k), h('span', {}, h('b', {}, name), rest))));
}

// The fix Confirm saves as the runbook (the same rule as learned_runbook in src/oncall_brain/domain/update.py).
const suggestedFix = (rc) => (rc?.kind && rc.service ? `${rc.kind === 'config' ? 'Revert the config change' : 'Roll back the deploy'} on ${short(rc.service)}` : null);

function doRow(cur, f) {
  const rc = f.rc, learned = cur.resolved?.data, rb = f.runbook;
  // A runbook's steps are actions; its "Last time the culprit was" line is a note, set above them.
  const steps = (xs) => {
    const notes = (xs || []).filter((s) => /^Last time\b/.test(s)), acts = (xs || []).filter((s) => !notes.includes(s));
    return [notes.map((s) => h('p', { class: 'small muted' }, plain(s).replace(/^Last time the culprit was: (.*)$/, 'Last time the culprit was “$1”.'))),
      acts.length ? h('ol', { class: 'steps-list' }, acts.map((s) => h('li', {}, plain(s)))) : null];
  };
  if (learned) {
    return h('div', { class: 'learned' }, h('p', { class: 'learned-head' }, h('b', {}, 'Saved to memory')),
      h('p', {}, `Next time a change on ${short(rc?.service || '')} hurts ${short(cur.home)}, “${learned.title}” is tried first.`), steps(learned.steps));
  }
  if (rb) {
    return [h('p', {}, h('b', {}, rb.title)),
      h('p', { class: 'small muted' }, rb.uses > 1 ? `This fix worked ${rb.successes ?? 0} of ${rb.uses} times.` : rb.uses === 1 ? 'This fix was confirmed once before.' : 'From memory.'),
      steps(rb.steps)];
  }
  if (isLive(cur)) return skel('w60', 'w40');
  if (isResolved(cur)) {
    const saved = f.sources.find((s) => s.kind === 'Runbook');
    return h('p', {}, saved ? `The cause is confirmed and the fix is saved to memory as “${plain(saved.title)}”. The next incident like this starts from it.`
      : 'The cause is confirmed. The fix you applied is saved to memory for the next incident like this.');
  }
  if (suggestedFix(rc)) { // shown before the human decides
    return [h('p', {}, h('b', {}, `Suggested: ${suggestedFix(rc)}`),
      ` (${short(rc.change)}${rc.author ? ` by ${rc.author}` : ''}${rc.at ? `, ${hhmm(rc.at)}` : ''}).`),
    h('p', { class: 'small muted' }, 'There is no runbook for this yet. Confirm the cause and this is saved as one, so the next incident like it starts here.')];
  }
  return h('p', {}, 'No runbook for this yet.', f.expert ? ` Ask ${f.expert.name}, who knows ${short(f.expert.service || rc?.service || cur.home)} best.` : '',
    ' Pick the cause above once you know it, and the fix is saved to memory for next time.');
}

function ruledRow(cur, f) {
  if (isLive(cur)) {
    if (!f.suspects.length) return h('p', { class: 'muted' }, 'Listing the recent changes on the dependency paths.');
    return h('ul', { class: 'ruled' }, f.suspects.map((s) => {
      const st = s.verdict === 'refutes' ? `ruled out: ${s.tag}` : s.verdict === 'supports' ? 'supported' : s.source === 'memory' ? 'from memory, not tested yet' : 'not tested yet';
      return h('li', {}, h('b', {}, short(s.change)), ` on ${short(s.service)} `, h('span', { class: `state-word${s.verdict === 'supports' ? ' sig' : ''}` }, st));
    }));
  }
  const picked = f.rc?.change, rows = f.refuted.filter((r) => r.verdict !== 'outranked' && r.change !== picked), ov = f.overruled;
  if (!rows.length && !ov) return null;
  return h('ul', { class: 'ruled' },
    ov ? h('li', {}, h('b', {}, short(ov.change)), ` on ${short(ov.service)}`, h('span', { class: 'tag' }, 'you ruled it out'),
      h('span', { class: 'why-not' }, 'The agents\' pick; you chose another change.')) : null,
    rows.map((r) => {
      // the tag only when the reason does not already say it ("rolled back" over "change was rolled back before …")
      const tag = r.tag || 'ruled out', text = plain(r.reason);
      const said = tag.split(' ').filter((w) => w.length > 2).every((w) => text.toLowerCase().includes(w));
      return h('li', {}, h('b', {}, short(r.change)), ` on ${short(r.service)}`, said ? null : h('span', { class: 'tag' }, tag),
        h('span', { class: 'why-not' }, text));
    }));
}

// What a flat change log (no graph) would have blamed for the same alert; "wrong" means not the cause the agents found.
function nographRow(cur, f) {
  const o = f.o, bp = o?.baseline_pick, ab = o?.anomaly_baseline_pick;
  if (isLive(cur) || (!bp && !ab)) return null;
  const pick = (p, ok, how) => p && h('li', {}, h('b', {}, short(p.change)), ` on ${short(p.service)}`,
    h('span', { class: 'tag' }, ok ? 'same answer' : 'wrong change'), h('span', { class: 'why-not' }, how));
  return h('ul', { class: 'ruled' }, pick(bp, o.baseline_correct, 'The newest change in the change log.'),
    pick(ab, o.anomaly_baseline_correct, 'The change log plus anomalies: the change whose own service went red first.'));
}

// Other changes that also fit: outranked (they explain fewer of the alerts) or co-causes (they also contributed).
function alsoRow(cur, f, kind) {
  if (isLive(cur) || !f.o) return null;
  const picked = f.rc?.change;
  const xs = kind === 'outranked' ? (f.o.refuted || []).filter((r) => r.verdict === 'outranked' && r.change !== picked)
    : (f.o.co_causes || []).filter((c) => c.change !== picked);
  if (!xs.length) return null;
  return h('ul', { class: 'ruled' }, xs.map((r) => h('li', {}, h('b', {}, short(r.change)), ` on ${short(r.service)}`,
    h('span', { class: 'why-not' }, kind === 'outranked' ? alsoWhy(r, f.rc) : plain(r.reason || '')))));
}

// "chg:x explains every alerting service this change does (1) and 2 more" -> { n: 1, all: 3, by: 'x' }.
const outranked = (text) => {
  const m = String(text || '').match(/(?:(?:chg:)?([\w.-]+) )?explains every alerting service this change does \((\d+)\) and (\d+) more/);
  return m && { by: m[1], n: Number(m[2]), all: Number(m[2]) + Number(m[3]) };
};
function alsoWhy(r, rc) {
  const m = outranked(r.reason);
  if (m) return `It explains only ${m.n} of ${m.all} alerting services; the ${short(rc?.service || '')} change explains all ${m.all}.`;
  return plain(r.reason).replace(/^outranked:\s*/, '');
}

function sourcesRow(cur, f) {
  if (!f.sources.length) return isLive(cur) ? skel('w60') : null;
  return h('ul', { class: 'sources' }, f.sources.map((s) => h('li', {}, h('span', {}, kindWord(s.kind)),
    h('span', {}, plain(s.title || short(s.id))), h('span', {}, s.at ? dmon(s.at) : ''))));
}

function renderDispatch(cur, f) {
  const live = isLive(cur);
  const rows = [['Cause', causeRow(cur, f)], ['Where', whereRow(cur, f)], ['Since', sinceRow(cur, f)], ['Who', whoRow(cur, f)],
    ['Do this', doRow(cur, f)], ['Also possible', alsoRow(cur, f, 'outranked')], ['Also contributing', alsoRow(cur, f, 'co')],
    [live ? 'Suspects' : 'Ruled out', ruledRow(cur, f)], ['Without the graph', nographRow(cur, f)], ['Sources', sourcesRow(cur, f)]]
    .filter(([, v]) => v != null && !(Array.isArray(v) && !v.flat(Infinity).filter(Boolean).length));
  set('dispatch', rows.map(([k, v], i) => h('div', { style: `--i:${i + 1}` }, h('dt', {}, k), h('dd', {}, v))));
  return rows.length;
}

// The status update the comms agent drafted, line by line ("Key: value"), as a ruled block. What is shown is what
// Copy update copies: sources by their titles (tickets by key), "1 of 1 time" in the singular, the outranked suspect in
// plain words, and, on an open draft with no next action, the suggested fix as one (suggested, not yet confirmed).
function updateLines(text, f, next = null) {
  const src = new Map(f.sources.map((s) => [s.id, s]));
  const [first, ...rest] = text.split('\n');
  const m = first.match(/^\[(.*)\]\s*status:\s*(.*)$/);
  const lines = rest.map((line) => {
    const k = line.match(/^([A-Z][\w ()-]{1,40}):\s(.*)$/);
    if (!k) return [null, plain(localTimes(line))];
    let v = localTimes(k[2]).replace(/worked (\d+) of 1 times/, 'worked $1 of 1 time');
    if (k[1] === 'Sources') v = v.split(/,\s*/).map((id) => (kindOf(id) === 'ticket' || !src.get(id)?.title ? short(id) : src.get(id).title)).join(', ');
    const out = k[1] === 'Supported but outranked' && outranked(v), who = v.match(/^(\S+) \(/)?.[1];
    if (out && who) return ['Also possible', `${short(who)}, but it explains only ${out.n} of the ${out.all} alerts; ${short(out.by || '')} explains all ${out.all}.`];
    return [k[1], plain(v)];
  });
  if (next && !lines.some(([k]) => k === 'Next action')) {
    const at = lines.findIndex(([k]) => k === 'Sources');
    lines.splice(at < 0 ? lines.length : at, 0, ['Next action', next]);
  }
  return { head: m ? `${m[1]}: ${m[2]}` : first, lines };
}

function renderUpdate(cur, n, f) {
  const slack = cur.resolved?.slack || cur.res?.slack;
  $('update').style.setProperty('--i', n + 1);
  if (!f.update) {
    return set('update', isLive(cur) ? [h('div', { class: 'update-head' }, h('h2', {}, 'Status update for #incidents')),
      h('p', { class: 'update-pending' }, 'Comms drafts the update for #incidents once the cause is clear.')] : null);
  }
  const fix = !isResolved(cur) && !f.runbook && suggestedFix(f.rc);
  const u = updateLines(f.update, f, fix ? `${fix} (suggested, not yet confirmed)` : null);
  const shown = [u.head, ...u.lines.map(([k, v]) => (k ? `${k}: ${v}` : v))].join('\n');
  const posted = slack === 'posted', failed = String(slack || '').startsWith('failed');
  set('update',
    h('div', { class: 'update-head' }, h('h2', {}, 'Status update drafted for #incidents'),
      h('span', { class: 'small muted' }, posted ? 'Posted to your Slack.' : failed ? `The Slack post failed (${slack.replace(/^failed:?\s*/, '')}).` : 'Preview, not posted.'),
      !posted && !failed && !OFFLINE ? linkBtn('Connect Slack to post it', () => showView('connect', true), 'quiet small', 'slack-link') : null,
      copyBtn(shown, 'Copy update', null, 'copy-update')),
    h('div', { class: 'update-lines' }, h('p', { class: 'head' }, u.head),
      u.lines.map(([k, v]) => (k ? h('p', {}, h('b', {}, `${k}: `), v) : h('p', {}, v)))));
}

// ---------- show me why ----------
const TOOL_TITLE = {
  open_incident: () => 'Open a shared incident record',
  blast_radius: (s) => `Who depends on ${short(svcOf(s)) || 'the alerting service'}?`,
  page_on_call: (s) => `Who is on call for ${short(svcOf(s)) || 'the alerting service'}?`,
  correlate_alerts: () => 'Do these alerts share a cause?',
  recall_similar: () => 'Have we seen this before?',
  hypothesize_from_memory: () => 'Does the remembered fix apply?',
  propose_hypotheses: () => 'Which recent changes could be the cause?',
  check_hypothesis: (s) => `Test suspect ${short(s.data?.change || idIn(s.summary, 'chg') || '')}`,
  conclude: () => 'Which suspect explains the most?',
  who_knows: (s) => `Who knows ${short(svcOf(s)) || 'the culprit'} best?`,
  warn_owners: () => 'Who should get a heads-up?',
  post_update: () => 'Draft the status update',
};
const stepTitle = (s) => (TOOL_TITLE[s.tool] ? TOOL_TITLE[s.tool](s) : cap(plain(s.tool.replace(/_/g, ' '))));
function stepResult(s) {
  const d = s.data;
  if (s.tool === 'open_incident') { // "Opened inc:<id> for '<alert>' on svc:x": the id is an epoch stamp, not words
    const m = String(s.summary || '').match(/for '(.*)' on (\S+)/);
    return m ? `Opened the shared incident record for “${m[1]}” on ${short(m[2])}.` : 'Opened the shared incident record.';
  }
  if (s.tool === 'check_hypothesis' && d) return `${d.verdict === 'supports' ? 'Supported' : 'Ruled out'}: ${short(d.change)} on ${short(d.service)}, ${plain(d.reason)}`;
  return cap(plain(String(s.summary || '').replace(/^REFUTES /, 'Ruled out: ').replace(/^SUPPORTS /, 'Supported: ')
    .replace(/\binc:\S+ '([^']*)' \(cause on (\S+)\)/g, '“$1” (its cause was on $2)')));
}

function learnNames(step) {
  const d = step.data;
  if (step.tool === 'page_on_call' && d?.person) {
    names.set(d.person, d.name);
    names.set(d.team, `${d.team_name} team`);
  }
  if (step.tool === 'who_knows') for (const p of d || []) names.set(p.person, p.name);
  if (step.tool === 'warn_owners') {
    for (const w of Array.isArray(d) ? d : []) {
      names.set(w.person, w.name);
      if (w.team_name && kindOf(w.team) === 'team') names.set(w.team, `${w.team_name} team`);
    }
  }
  if (step.tool === 'recall_similar') for (const r of Array.isArray(d) ? d : []) names.set(r.incident, r.title);
  if (step.tool === 'ask') for (const r of d?.related || []) if (['person', 'team'].includes(kindOf(r.id))) names.set(r.id, r.name);
}

// A stored run has no step data, so the graph learns names from its outcome: people, teams, recalled incidents.
function learnOutcome(o) {
  for (const x of [...(o?.paged || []), ...(o?.warned || [])]) names.set(x.person, x.name);
  for (const x of o?.paged || []) if (x.team_name) names.set(x.team, `${x.team_name} team`);
  if (o?.expert?.id) names.set(o.expert.id, o.expert.name);
  for (const r of o?.memory?.recalled || []) names.set(r.incident, r.title);
}

function copyBtn(text, label = 'Copy', name = null, key = null) { // text: a string, or a function giving it at click time
  return h('button', { class: 'btn small', type: 'button', 'aria-label': name, 'data-key': key || `copy-${label}`, onclick: (e) => {
    e.preventDefault();
    if (!navigator.clipboard) return toast('This page cannot reach the clipboard here; select the text and copy it.', true);
    const t = typeof text === 'function' ? text() : text;
    if (!t) return toast('The Cypher has not loaded yet. Open the list and try again.', true);
    navigator.clipboard.writeText(t).then(() => toast('Copied to the clipboard.'), () => toast('The browser blocked the clipboard; select the text and copy it.', true));
  } }, label);
}

// A live query carries its Cypher and rows. A stored step's query keeps its name, row count, ms, params (null when
// they were too long to keep) and the sha of its Cypher; the Cypher is code, fetched once per name from
// GET /api/queries/{name} when its list opens, and a different sha there means the query was edited since the step ran.
const cypherFor = new Map(); // query name -> {cypher, sha, ...}, or the fetch in flight (a 404 stays: the query is gone)
const knownCypher = (q) => q.cypher ?? cypherFor.get(q.name)?.cypher ?? null;
const rowCount = (q) => q.rows?.length ?? q.row_count ?? 0;
const DRIFTED = 'This query has changed since the step ran; this is its current Cypher.';
const drifted = (sha, name) => !!sha && !!cypherFor.get(name)?.sha && cypherFor.get(name).sha !== sha;
function loadCypher(name) {
  if (!cypherFor.has(name)) {
    cypherFor.set(name, api('GET', `/api/queries/${enc(name)}`).then((r) => { cypherFor.set(name, r); return r; },
      (e) => { if (e.status !== 404) cypherFor.delete(name); throw e; })); // other failures are tried again on reopen
  }
  return Promise.resolve(cypherFor.get(name));
}
function fillCypher(details) {
  if (!details.open) return;
  for (const code of details.querySelectorAll('code[data-query]')) {
    const name = code.dataset.query;
    loadCypher(name).then((r) => {
      if (!code.dataset.query) return; // an earlier open already filled it
      code.textContent = r.cypher; code.removeAttribute('data-query');
      if (drifted(code.dataset.sha, name)) code.parentElement.after(h('p', { class: 'small muted' }, DRIFTED));
    }, (e) => {
      code.textContent = e.status === 404 ? 'This query is no longer in the catalogue: the product changed after this step ran.'
        : 'The Cypher did not load. Close and open this list to try again.';
    });
  }
}

function queryBlock(q, key) {
  const cypher = knownCypher(q), n = rowCount(q);
  return h('div', { class: 'q' },
    h('div', { class: 'qhead' }, h('b', {}, q.name),
      h('span', { class: 'rw', title: q.readonly ? 'GRAPH.RO_QUERY' : 'GRAPH.QUERY (writes)' }, q.readonly ? 'read' : 'write'),
      h('span', {}, `${plural(n, 'row')}, ${q.ms} ms`),
      q.name === 'incident_board' ? h('span', {}, 'the agent re-reads the shared board') : null,
      copyBtn(() => knownCypher(q), 'Copy', `Copy the ${q.name} query`, `copy-${key}`)),
    // focusable, so a keyboard can scroll a wide block sideways (Safari does not make scrollers focusable itself)
    h('pre', { tabindex: 0, 'aria-label': `${q.name} Cypher` },
      h('code', { 'data-query': cypher == null ? q.name : null, 'data-sha': q.sha }, cypher ?? 'Loading the Cypher…')),
    drifted(q.sha, q.name) ? h('p', { class: 'small muted' }, DRIFTED) : null,
    h('pre', { tabindex: 0, 'aria-label': `${q.name} parameters` }, h('code', {},
      q.params == null ? 'params not stored (too long to keep with the step)' : `params ${JSON.stringify(q.params)}`)),
    q.rows?.length ? h('details', { 'data-key': `rows-${key}` }, h('summary', {}, `Rows (${n})`),
      h('pre', { tabindex: 0, 'aria-label': `${q.name} rows` }, h('code', {}, JSON.stringify(q.rows, null, 1)))) : null);
}

function cypherList(queries, key) {
  if (!queries?.length) return null;
  const ms = queries.reduce((a, q) => a + q.ms, 0), rows = queries.reduce((a, q) => a + rowCount(q), 0);
  const lazy = queries.some((q) => knownCypher(q) == null); // a stored step: the Cypher arrives when the list opens
  return h('details', { 'data-key': `cy-${key}`, ontoggle: lazy ? (e) => fillCypher(e.currentTarget) : null },
    h('summary', {}, `${plural(queries.length, 'query')}, ${plural(rows, 'row')}, ${ms < 10 ? ms.toFixed(1) : Math.round(ms)} ms`),
    queries.map((q, j) => queryBlock(q, `${key}-${j}`)));
}

// Who chose a step: a model, 'model' (a run recorded before deciders were kept: its reason reads "LLM chose …" and its
// decider says rules), or 'rules'. The step list and the footer count with this one rule.
const oldStep = (s) => /^LLM chose /.test(s.reason || '');
const decider = (s) => (oldStep(s) && s.by === 'rules' ? 'model' : s.by || 'rules');
const deciderName = (by) => (by === 'model' ? 'the model' : modelName(by));

function stepRow(step, i, num) {
  const d = step.data, verdict = step.tool === 'check_hypothesis' && d ? d.verdict : /^SUPPORTS /.test(step.summary || '') ? 'supports' : null;
  const by = decider(step), why = oldStep(step) ? null : cap(plain(step.reason)); // an older run's reason was not kept
  const selected = state.selectedStep === i && state.current?.steps?.[i] === step;
  return h('li', { class: `step${selected ? ' selected' : ''}`, 'data-i': i, 'data-key': `steprow-${i}` },
    h('span', { class: 'seq' }, num),
    h('div', {},
      h('h4', {}, h('button', { class: 'step-btn', type: 'button', 'aria-pressed': String(selected), 'data-key': `step-${i}`,
        title: 'Light up this step on the graph' }, stepTitle(step))),
      h('p', { class: 'by' }, `Chosen by ${deciderName(by)}`),
      why ? h('p', { class: 'reason' }, why) : null,
      h('p', { class: `result${verdict === 'supports' ? ' sig' : ''}` }, stepResult(step)),
      cypherList(step.queries, `s${i}`)));
}

function renderWhy(cur) {
  const steps = cur.steps || [];
  const ms = steps.reduce((a, s) => a + (s.queries || []).reduce((b, q) => b + q.ms, 0), 0);
  const tokens = cur.res?.llm_tokens || 0;
  const work = steps.filter((s) => s.tool !== 'handoff'), hands = steps.length - work.length;
  const numOf = new Map(work.map((s, k) => [s, k + 1])); // steps are numbered as listed; handoffs are lines, not steps
  const groups = ROLES.map((role) => {
    const mine = steps.map((s, i) => [s, i]).filter(([s]) => s.role === role);
    if (!mine.length) return null;
    const hand = mine.find(([s]) => s.tool === 'handoff')?.[0];
    const mineWork = mine.filter(([s]) => s.tool !== 'handoff');
    const target = hand && (ROLES.includes(hand.target) ? hand.target : (String(hand.summary).match(/hands off to (\w+)/) || [])[1]);
    const to = target === 'human' ? 'you' : ROLE_NAME[target] || target;
    return h('section', { class: 'group', 'aria-label': `${ROLE_NAME[role]} steps` },
      h('h3', {}, ROLE_NAME[role], h('span', { class: 'count' }, plural(mineWork.length, 'step'))),
      hand ? h('p', { class: 'hand' }, `Handed to ${to}. ${cap(plain(hand.reason))}`) : null,
      h('ol', {}, mineWork.map(([s, i]) => stepRow(s, i, numOf.get(s)))));
  });
  // Who chose the steps, counted over the steps listed (handoffs are lines, not steps), models first.
  const tally = new Map();
  for (const s of work) tally.set(decider(s), (tally.get(decider(s)) || 0) + 1);
  const chose = [...tally].sort(([a], [b]) => (a === 'rules') - (b === 'rules')).map(([by, n]) => `${deciderName(by)} chose ${n}`);
  const foot = tally.size === 1 ? `${cap(deciderName([...tally.keys()][0]))} chose all ${plural(work.length, 'step')}.`
    : `Of the ${plural(work.length, 'step')}, ${and(chose)}.`;
  const counted = `${plural(work.length, 'step')}${hands ? ` and ${plural(hands, 'handoff')}` : ''}`;
  const unkept = cur.stored ? work.filter((s) => !s.queries).length : 0; // stored before steps kept their queries
  set('why-side',
    h('div', { class: 'why-intro' },
      h('h2', {}, 'How the agents got here'),
      h('p', {}, `Every step the three agents took, in order${unkept && unkept === work.length ? '' : ', with the graph queries behind it'}. Select a step to light up its part of the graph.`),
      h('p', { class: 'small muted' }, steps.length ? [`${counted}${ms ? `, ${(ms / 1000).toFixed(1)} s of graph queries` : ''}`
        + `${tokens ? `, ${Math.round(tokens / 1000)}k model tokens` : ''}.`,
      work.some(oldStep) ? ' Steps from an older recording show their tool and result, without the model\'s reason.' : '',
      !unkept ? '' : unkept === work.length ? ' This incident was stored before steps kept their queries.'
        : ` ${plural(unkept, 'step')} here ${unkept === 1 ? 'was' : 'were'} stored before steps kept their queries.`]
        : 'The steps appear here as the agents take them.')),
    groups,
    work.length ? h('p', { class: 'why-foot' }, foot) : null);
}

function onStepClick(ev) {
  if (ev.target.closest('details, pre') || (ev.target.closest('button') && !ev.target.closest('.step-btn'))) return; // let people read the Cypher
  const li = ev.target.closest('li[data-i]'), cur = state.current;
  if (!li || !cur?.steps) return;
  state.selectedStep = Number(li.dataset.i);
  for (const x of $('why-side').querySelectorAll('.step.selected')) {
    x.classList.remove('selected');
    x.querySelector('.step-btn')?.setAttribute('aria-pressed', 'false');
  }
  li.classList.add('selected');
  li.querySelector('.step-btn')?.setAttribute('aria-pressed', 'true');
  const eles = cur.steps[state.selectedStep]?.eles;
  if (eles?.nonempty() && state.graphOwner === cur) {
    state.frame = 'step';
    G.paint(cur, eles, [G.around(eles), eles]);
    renderGraphTools();
    if (mobile()) $('graph-wrap').scrollIntoView({ block: 'start', behavior: 'instant' });
  }
}

// ---------- the graph's picture of a run ----------
function renderLegend() {
  const k = G.kinds(), owner = state.graphOwner, word = (key, text) => { const s = $('legend').querySelector(`[data-k="${key}"] span`); if (s) s.textContent = text; };
  for (const li of $('legend').children) li.hidden = !k[li.dataset.k];
  word('hot', owner === 'ask' ? 'in this answer' : isLive(owner) ? 'in the latest step' : 'in the selected step');
  word('ctx', owner === 'ask' ? 'linked, not in the answer' : 'not touched by the agents');
}

function renderGraphTools() {
  const owner = state.graphOwner, g = state.graph, scoped = G.isScoped(), run = owner && owner !== 'ask' ? owner : null;
  let caption = '';
  if (g && G.ready()) {
    const of = `${G.shownServices()} of ${plural(g.nodes.length, 'service')}`;
    if (!scoped) caption = `The whole company: ${plural(g.nodes.length, 'service')} and ${plural(g.edges.length, 'dependency')}.${G.readable() ? '' : ' Scroll or pinch on the graph to zoom in.'}`;
    else if (owner === 'ask') caption = 'What this answer is linked to in the graph.';
    else if (scoped === 'live') caption = `What the agents have touched so far: ${of}.`;
    else caption = `What this incident touched: ${of}.`;
    const inView = { cause: 'The cause path is in view', step: 'The selected step is in view', live: 'The latest step is in view' }[state.frame];
    const how = matchMedia('(pointer: coarse)').matches ? 'use Zoom out or Fit it all' : 'drag the graph or use Zoom out';
    if (!G.inView()) caption += ` ${(scoped && inView) || 'Part of it is in view'}; ${how} to see the rest.`;
    if (scoped && !G.readable()) caption += ' It is drawn small to fit; use Zoom in to read the labels.';
  }
  set('hud', caption);
  const canScope = owner === 'ask' ? !!state.askEles?.nonempty() : !!run?.touched?.nonempty();
  // The camera by button as well as by wheel, pinch and drag (the only way on touch, where a drag scrolls the page).
  const cam = (label, act) => h('button', { class: 'btn small', type: 'button', 'data-key': `cam-${label}`, onclick: () => { act(); renderGraphTools(); } }, label);
  set('graph-tools', G.ready() && g ? [canScope ? h('button', { class: 'btn small', type: 'button', 'data-key': 'scope', onclick: () => {
    if (G.isScoped()) { state.wide = true; G.scopeAll(); } else { state.wide = false; rescope(); }
    renderGraphTools();
  } }, scoped ? 'Show whole company' : owner === 'ask' ? 'Only this answer' : 'Only this incident') : null,
  cam('Zoom out', () => G.zoomBy(0.8)), cam('Zoom in', () => G.zoomBy(1.25)), cam('Fit it all', () => G.fitShown())] : null);
  // The graph's name and text alternative: the evidence path as a sentence, else what the picture holds.
  $('graph').setAttribute('aria-label', owner === 'ask' ? 'Graph of this answer' : run ? 'Graph of this incident' : 'Service dependency graph');
  const rc = run ? facts(run).rc : null, p = pathOf(rc)?.map(short);
  // (the evidence path is shown under the graph; the list of everything touched is for screen readers only)
  set('graph-alt', p ? `Evidence path: the change ${short(rc.change)} on ${p[0]}, then ${p.slice(1).join(', then ')}, where the alert fired.`
    : run?.touched?.nonempty() && scoped ? `${scoped === 'live' ? 'So far the agents have touched' : 'This incident touched'} ${and(G.labels(run.touched))}.`
      : owner === 'ask' && state.askEles?.nonempty() ? `The answer is linked to ${and(G.labels(state.askEles))}.` : '');
  $('graph-alt').classList.toggle('sr-only', !p);
  renderLegend();
}

function rescope() {
  const cur = state.current;
  if (state.graphOwner === 'ask') return paintAsk();
  if (!cur || state.graphOwner !== cur) return;
  if (outcomeOf(cur)) return finalPaint(cur);
  G.scopeLive(cur.touched, cur.home);
  state.frame = 'live';
  G.paint(cur, null, [cur.touched], { crop: true });
}

// Stored incidents keep no per-step highlight, so rebuild one from what the step names: graph ids in its target and
// summary, services named in its prose, a change's service from the outcome, the people paged or warned by name.
function storedHighlight(s, cur) {
  const o = outcomeOf(cur) || {}, text = `${s.target || ''} ${s.summary || ''}`, nodes = new Set(), edges = [];
  for (const m of text.matchAll(/\b(?:svc|chg|inc|rb|person|team):[A-Za-z0-9_-]+(?:[.:][A-Za-z0-9_-]+)*/g)) nodes.add(m[0]);
  const svcByName = new Map((state.graph?.nodes || []).map((n) => [n.name, n.id]));
  for (const w of String(s.summary || '').match(/[a-z][a-z0-9-]*[a-z0-9]/g) || []) if (svcByName.has(w)) nodes.add(svcByName.get(w));
  const changes = [o.root_cause, ...(o.refuted || []), ...(o.co_causes || [])].filter(Boolean);
  if (s.tool === 'propose_hypotheses' || s.tool === 'conclude') for (const c of changes) nodes.add(c.change); // every suspect
  for (const c of changes) {
    if (c.service && nodes.has(c.change)) { nodes.add(c.service); edges.push([c.change, c.service, 'CHANGED']); }
  }
  // People, linked the way a live run links them: paged on-call to their team to the service, a heads-up from the
  // incident, the expert to the service they know best.
  const named = (p) => p?.person && p.name && String(s.summary).includes(p.name);
  for (const p of o.paged || []) {
    if (!named(p)) continue;
    nodes.add(p.person);
    if (p.team && p.service) edges.push([p.team, p.service, 'OWNS'], [p.person, p.team, 'ON_CALL']);
  }
  for (const w of o.warned || []) if (named(w)) { nodes.add(w.person); if (cur.incident) edges.push([cur.incident, w.person, 'WARNED']); }
  const ex = s.tool === 'who_knows' && (o.expert ? { ...o.expert, person: o.expert.id } : expertFromSummary([s]));
  if (ex?.name) {
    const id = ex.person || personId(ex.name), svc = ex.service || svcOf(s);
    names.set(id, ex.name);
    nodes.add(id);
    if (svc) edges.push([id, svc, 'KNOWS']);
  }
  if (s.tool === 'recall_similar') for (const id of nodes) if (kindOf(id) === 'inc' && id !== cur.incident) edges.push([cur.incident, id, 'RECALLS']);
  const svcs = new Set([...nodes].filter((id) => kindOf(id) === 'svc'));
  for (const e of state.graph?.edges || []) if (e.live && svcs.has(e.source) && svcs.has(e.target)) edges.push([e.source, e.target, 'DEPENDS_ON']);
  return { nodes: [...nodes], edges };
}

// who_knows names a few people with no edge between them and anything: the graph shows only the one who knows the
// service best, joined to it by a dotted "knows" line.
function highlightOf(step) {
  const hl = step.highlight;
  if (step.tool !== 'who_knows' || !hl?.nodes) return hl;
  const svc = hl.nodes.find((id) => kindOf(id) === 'svc'), top = hl.nodes.find((id) => kindOf(id) === 'person');
  return { nodes: [svc, top].filter(Boolean), edges: svc && top ? [[top, svc, 'KNOWS']] : [] };
}

function applyStep(run, step, live) {
  if (!G.ready()) return;
  let eles = G.elementsFor(highlightOf(step), run);
  if (!eles) return;
  if (step.tool === 'correlate_alerts' && step.data && new Set([run.home, ...(step.data.alerts || []).map((a) => a.service)]).size > 1) {
    eles = eles.union(G.markStorm(step.data, run));
  }
  step.eles = eles;
  run.touched = run.touched.union(eles);
  if (step.tool === 'check_hypothesis' && step.data) {
    if (step.data.verdict === 'supports') run.cause = run.cause.union(eles);
    else G.mark(step.data.change, 'refuted');
  }
  if (live) {
    if (!state.wide) G.scopeLive(run.touched, run.home);
    // A step the reader selected stays lit, and the camera stays put, until they select another one.
    const held = state.current === run && state.selectedStep != null && run.steps[state.selectedStep]?.eles;
    if (held) return G.paint(run, held, []), renderGraphTools();
    state.frame = 'live';
    // The camera: all it touched if readable, else around this step with the alerting service, else around this step,
    // else this step at a readable zoom (centred, even if that crops it: a live step is read, then the next one lands).
    // A handoff keeps the camera still.
    G.paint(run, eles, eles.nonempty() ? [run.touched, G.around(eles).union(G.byIds([run.home])), G.around(eles), eles] : [], { crop: true });
    renderGraphTools();
  }
}

// A person picked another change under Wrong cause: that change becomes the cause on the graph.
function applyPick(run) {
  const o = outcomeOf(run), alt = pickedAlt(run, o);
  if (!alt) return;
  if (o.root_cause) G.mark(o.root_cause.change, 'refuted');
  G.unmark(alt.change, 'refuted');
  run.cause = G.elementsFor({ nodes: [alt.change, alt.service].filter(Boolean), edges: alt.service ? [[alt.change, alt.service, 'CHANGED']] : [] }, run) || G.empty();
  run.touched = run.touched.union(run.cause);
}

// End on the answer: the incident subgraph, with the cause path (and the memory chain, if memory solved it) lit.
function finalPaint(run) {
  const o = outcomeOf(run);
  if (!o || !G.ready()) return;
  state.wide = false;
  applyPick(run);
  const memo = o.memory?.solved_by_memory ? G.elementsFor({ nodes: [], edges: o.memory.recalled.flatMap((r) =>
    [[run.incident, r.incident, 'RECALLS'], [r.incident, r.runbook, 'FIXED_WITH']]) }, run) : null;
  if (memo) run.touched = run.touched.union(memo);
  const learned = run.resolved?.highlight && G.elementsFor(run.resolved.highlight, run);
  if (learned) run.touched = run.touched.union(learned);
  // The cause on the graph is the agents' final pick only (another suspect may have been supported, then outranked).
  const won = !pickedAlt(run, o) && o.root_cause && run.steps.find((s) => s.tool === 'check_hypothesis' && s.data?.change === o.root_cause.change);
  if (won?.eles?.nonempty()) run.cause = won.eles;
  const storm = realStorm(o, run.home) ? G.select('.storm, .shared') : G.empty();
  const focus = run.cause.union(storm).union(memo || G.empty());
  G.scopeTo(run.touched, facts(run).rc?.live_path || []); // the evidence path as the spine of the layout
  // The camera: the whole subgraph if readable, else the cause and its neighbours, else the cause with the storm and
  // the memory chain, else the cause path with every alerting service (never cropped: at whatever zoom it needs).
  state.frame = 'cause';
  G.paint(run, learned || memo, run.cause.nonempty() ? [G.around(focus), focus, focus.nodes('.svc'), run.cause.union(G.select('.alerting'))] : [run.touched]);
  renderGraphTools();
}

// Rebuild the graph's picture of a run from its steps (switching incidents, or back from Ask).
function replayGraph(cur) {
  state.graphOwner = cur;
  state.wide = false;
  if (!G.ready()) return renderGraphTools();
  G.clear();
  if (!cur) { G.paint(null); return renderGraphTools(); }
  cur.touched = G.empty();
  cur.cause = G.empty();
  G.mark(cur.home, 'alerting');
  const o = outcomeOf(cur);
  if (cur.stored) for (const s of cur.steps || []) s.highlight ??= storedHighlight(s, cur);
  for (const s of cur.steps || []) applyStep(cur, s, false);
  if (cur.stored && o) { // no live trace: light the cause path, the ruled-out changes and the storm the graph remembers
    const rc = o.root_cause, p = rc?.live_path || [];
    const eles = G.elementsFor({ nodes: [...p, ...(rc ? [rc.change] : [])], edges: [...p.slice(1).map((n, i) => [p[i], n, 'DEPENDS_ON']),
      ...(rc ? [[rc.change, rc.service, 'CHANGED']] : [])] }, cur);
    if (eles) { cur.touched = cur.touched.union(eles); cur.cause = eles; }
    for (const r of o.refuted || []) G.mark(r.change, 'refuted');
    if (realStorm(o, cur.home)) cur.touched = cur.touched.union(G.markStorm(o.storm, cur));
  }
  if (o) finalPaint(cur);
  else {
    const seen = cur.touched.nonempty() ? cur.touched : G.byIds([cur.home]);
    G.scopeLive(seen, cur.home);
    state.frame = 'live';
    G.paint(cur, null, [seen], { crop: true });
  }
  renderGraphTools();
}

// Ask's picture: the last answer's subgraph, rebuilt from its highlight every time (an incident visit clears the graph).
function paintAsk() {
  state.graphOwner = 'ask';
  if (!G.ready()) return renderGraphTools();
  G.clear();
  const eles = state.askHl ? G.elementsFor(state.askHl, null) : null;
  state.askEles = eles;
  if (eles?.nonempty()) { G.scopeTo(eles); G.paint(null, eles, [eles]); }
  renderGraphTools();
}

// ---------- views ----------
function syncBody() {
  const inc = state.view === 'incidents';
  document.body.classList.toggle('on-landing', inc && !state.current);
  document.body.classList.toggle('has-acts-toast', inc && !!state.current && $('incident').classList.contains('has-acts'));
}

const VIEW_TITLE = { incidents: 'On-call Brain', ask: 'Ask the brain: On-call Brain', connect: 'Connect: On-call Brain' };
// focus: the reader chose this view (a tab or a link), so keyboard focus moves to its heading and the title changes.
function showView(view, focus = false) {
  if (view === 'incidents' && state.view === 'incidents' && state.current) return showIncident(null); // the tab is also "all incidents"
  state.view = view;
  closeMenus();
  for (const b of document.querySelectorAll('.view-tab')) b.setAttribute('aria-current', b.dataset.view === view ? 'page' : 'false');
  for (const v of ['incidents', 'ask', 'connect']) $(`view-${v}`).hidden = v !== view;
  if (view === 'connect') renderConnect();
  if (view === 'ask') renderChat(false);
  syncBody();
  placeGraph();
  window.scrollTo({ top: 0 });
  document.title = VIEW_TITLE[view];
  if (focus) $({ ask: 'ask-title', connect: 'connect-title' }[view] || (state.current ? 'inc-title' : 'landing-title'))?.focus({ preventScroll: true });
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

// Show me why docks the bar under the header, so its graph (sized and stuck for exactly that position) is on screen
// whole; on phone it brings the graph to the top of the screen. Answer keeps the slab where it is, unless the reader is
// already scrolled past the bar: then it starts right under it.
function tabTo(tab) {
  showTab(tab);
  if (mobile()) {
    const y = $('why-view').getBoundingClientRect().top + scrollY;
    if (tab === 'why' && scrollY < y - 1) window.scrollTo({ top: y });
    return;
  }
  const y = $('slab').getBoundingClientRect().bottom + scrollY - $('main').offsetTop;
  if (tab === 'why' ? Math.abs(scrollY - y) > 1 : scrollY > y + 1) window.scrollTo({ top: y });
}

// One Cytoscape canvas, moved to wherever it is shown; its picture is rebuilt when its owner changes. Ask shows it
// only once an answer has a subgraph (before that, one line says what will appear).
function placeGraph() {
  const ask = state.view === 'ask', hasAsk = !!state.askHl;
  $('ask-phone-slot').hidden = !(ask && mobile() && state.askGraphOpen && hasAsk);
  $('ask-graph-empty').hidden = hasAsk;
  $('ask-graph-empty').textContent = state.chat.some((m) => m.data) ? 'This answer is not linked to anything in the graph.'
    : 'Ask a question and the part of the graph its answer is linked to appears here.';
  const slot = ask && hasAsk ? (mobile() ? $('ask-phone-slot') : $('ask-graph-slot')) : $('why-graph-slot');
  if ($('graph-wrap').parentElement !== slot) slot.append($('graph-wrap'));
  if (ask && hasAsk && state.graphOwner !== 'ask') paintAsk();
  else if (!ask && state.tab === 'why' && state.graphOwner !== state.current) replayGraph(state.current);
  requestAnimationFrame(() => { G.refit(); renderGraphTools(); });
}

let printTimer;
// The one orchestrated motion: an answer arrives, the slab prints, then the rows follow (CSS does the timing).
function printAnswer() {
  const el = $('incident');
  el.classList.remove('print');
  void el.offsetWidth; // restart the animation
  el.classList.add('print');
  clearTimeout(printTimer);
  printTimer = setTimeout(() => el.classList.remove('print'), 1100);
}

// focus: move keyboard focus to the new content (the incident title; back on the list, the row it came from).
function showIncident(cur, focus = true) {
  const prev = state.current;
  state.current = cur;
  state.selectedStep = null;
  $('landing').hidden = !!cur;
  $('incident').hidden = !cur;
  $('view-incidents').classList.toggle('has-current', !!cur);
  renderAll();
  if (state.view !== 'incidents') showView('incidents');
  else { syncBody(); placeGraph(); window.scrollTo({ top: 0 }); }
  if (!focus) return;
  if (cur) $('inc-title')?.focus({ preventScroll: true });
  else (rowFor(prev) || $('landing-title'))?.focus({ preventScroll: true });
}

function renderIncident(cur) {
  const f = facts(cur);
  renderSlab(cur, f);
  renderActs(cur, f);
  renderProgress(cur);
  renderUpdate(cur, renderDispatch(cur, f), f);
  if (state.tab === 'why') renderWhy(cur);
}

function renderAll() {
  const rows = state.loaded && !state.loadError ? inboxItems() : [];
  renderNotice();
  renderInbox(rows);
  if (!$('simulate-menu').hidden) renderSimulateMenu();
  const cur = state.current;
  if (cur) renderIncident(cur);
  else renderLanding(rows);
  renderHealth(rows); // after the landing: it names the time zone only if nothing else on screen does
  syncBody();
}

function openRun(run) {
  if (state.current === run) return;
  openSeq++;
  showTab('answer');
  showIncident(run);
  if (run.done) printAnswer();
}

let openSeq = 0; // the last incident asked for wins, however its response races the others
async function openStored(incident) {
  const seq = ++openSeq;
  try {
    const d = await api('GET', `${T()}/incidents/${enc(incident)}`);
    if (seq !== openSeq) return;
    const alerts = state.alerts.filter((a) => a.incident === incident);
    const alert = { id: d.alert, name: d.alert_name, service: d.service, at: d.at, symptom: d.symptom };
    const cur = { stored: true, done: true, incident, alert, alerts: alerts.length ? alerts : [alert], home: d.service,
      status: d.status, res: { outcome: d.outcome, steps: d.steps, planner: null, llm_tokens: 0 }, steps: d.steps,
      act: alerts.find((a) => a.act != null)?.act ?? null,
      resolved: null, picked: null, showAlt: false, saving: null, touched: G.empty(), cause: G.empty() };
    learnOutcome(d.outcome);
    showTab('answer');
    showIncident(cur);
    printAnswer();
  } catch (e) {
    if (seq === openSeq) toast(`This incident could not open: ${e.message}`, true);
  }
}

// ---------- actions ----------
// Reloads the alert list (statuses) and redraws the list, the menu and the landing. The open incident redraws itself.
async function refreshAlerts() {
  if (!OFFLINE) {
    try {
      state.alerts = await api('GET', `${T()}/alerts`);
      state.stale = false;
    } catch {
      state.stale = true; // keep the old list and say so in the health line
    }
  }
  renderInbox();
  if (!$('simulate-menu').hidden) renderSimulateMenu();
  if (!state.current) renderLanding();
  renderHealth();
}

function setRunning(on) {
  state.running = on;
  simButtonState();
  if (!$('simulate-menu').hidden) renderSimulateMenu();
  if (!state.current) renderLanding();
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
    toast(`The alert could not be raised: ${e.message}`, true);
  }
}

async function runAlert(alert, alerts, act) {
  if (state.running) return;
  const run = newRun(alert, alerts, act);
  state.runs.push(run);
  state.skip = false;
  openSeq++;
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
        if (state.current === run) renderDispatch(run, facts(run));
      } else if (ev.error) throw new Error(ev.error);
    }
    if (!run.done) throw new Error('the agent run ended without a result');
  } catch (e) {
    run.error = e.name === 'TimeoutError' ? 'the run went on for more than five minutes, so this page stopped waiting' : e.message;
    run.done = true;
    if (state.current === run) renderIncident(run);
    else toast(`The agents could not finish: ${e.message}`, true);
    announce(`The agents could not finish: ${e.message}`);
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
  announce(`${ROLE_NAME[step.role]}: ${plain(step.reason)}`);
  renderInbox();
  if (state.current === run) renderIncident(run);
}

function onResult(run, res) {
  run.res = res;
  run.incident = res.incident_id;
  run.done = true;
  run.folded = true;
  learnOutcome(res.outcome);
  if (state.graphOwner === run) finalPaint(run);
  const rc = res.outcome.root_cause;
  announce(rc ? `Cause found: ${short(rc.change)} on ${short(rc.service)}.` : 'No cause found; a human should look.');
  if (state.current === run) {
    renderAll();
    printAnswer();
  } else toast(rc ? `Cause found for ${run.alert.name}.` : `${run.alert.name}: no cause found.`);
}

// The human's call: written to the graph (CAUSED_BY, the runbook, its success count). The incident redraws here,
// live and offline alike, so the slab flips to Confirmed and the learned fix shows under Do this.
async function resolve(cur, change) {
  cur.saving = change;
  renderActs(cur, facts(cur));
  try {
    const r = await api('POST', `${T()}/incidents/${enc(cur.incident)}/resolve`, { change_id: change });
    cur.resolved = r;
    cur.picked = change;
    cur.showAlt = false;
    if (r.data) names.set(r.data.runbook, r.data.title || 'runbook');
    if (state.graphOwner === cur) finalPaint(cur);
    announce('Cause confirmed. The fix is saved to memory.');
  } catch (e) {
    toast(`The cause could not be saved: ${e.message}`, true);
  }
  cur.saving = null;
  if (state.current === cur) renderIncident(cur);
  await refreshAlerts();
}

async function doReset() {
  if (state.running) return;
  try {
    const r = await api('POST', `${T()}/reset`);
    names.clear();
    Object.assign(state, { runs: [], chat: [], graphOwner: null, askEles: null, askHl: null, loadError: null });
    await loadTenant();
    showIncident(null);
    if (state.view === 'connect') renderConnect();
    toast(r.status === 'seeded' ? 'The demo company is loaded into FalkorDB.' : 'The demo company is reset: its graph was restored from the pristine copy.');
  } catch (e) {
    toast(`The reset failed: ${e.message}`, true);
  }
}

// ---------- ask the brain ----------
// The answer first (one or two sentences), then its sources, then the rest behind disclosures. A follow-up's "Taking
// "it" as kafka, from your earlier question …" is a preface, set apart, not the lead. Returns [lead, rest, preface].
function splitAnswer(text) {
  const full = localTimes(text), pre = full.match(/^Taking "[^"]+" as [^.]+?\.\s+/)?.[0] || '', body = full.slice(pre.length);
  // Sentences end at punctuation followed by whitespace, so "@hana.costa" and "inc:0911" never split a sentence.
  const sentences = body.split(/(?<=[.!?])\s+/);
  let lead = '';
  for (const s of sentences) {
    if (lead && lead.length + s.length > 260) break;
    lead += (lead ? ' ' : '') + s;
  }
  return [lead.trim(), body.slice(lead.length).trim(), pre.trim()];
}

// The answer's subgraph, plus anyone the answer names who is linked to it, or null when it links to nothing. The
// owning team's members ("members: A, B.") join their team by MEMBER_OF, as they do in the graph.
function askHighlight(r) {
  const hl = r.highlight || { nodes: [], edges: [] }, d = r.data || {}, related = d.related || [];
  const named = related.filter((x) => kindOf(x.id) === 'person' && String(d.answer).includes(x.name) && !hl.nodes.includes(x.id));
  const nodes = [...hl.nodes, ...named.map((x) => x.id)], edges = [...hl.edges];
  const team = related.find((x) => kindOf(x.id) === 'team');
  const members = String(d.answer || '').match(/\bmembers: ([^.;]+)/)?.[1].split(/,\s*/) || [];
  if (team) {
    for (const name of members) {
      const id = related.find((x) => x.name === name && kindOf(x.id) === 'person')?.id || personId(name);
      names.set(id, name);
      if (!nodes.includes(id)) nodes.push(id);
      if (!edges.some(([s, t]) => (s === id && t === team.id) || (s === team.id && t === id))) edges.push([id, team.id, 'MEMBER_OF']);
    }
    if (!nodes.includes(team.id)) nodes.push(team.id);
  }
  return nodes.length ? { nodes, edges } : null;
}

function askBlocked() {
  if (OFFLINE) return 'This page is a recorded replay, so questions need the live server (make dev).';
  if (dbDown()) return 'Questions need FalkorDB, which is not reachable. Start it with make db, then reload.';
  if (state.loadError) return 'Questions need a company graph, and this company could not load. Open the demo company from Incidents.';
  return '';
}

function brainMessage(m, n) {
  if (m.pending) return [h('p', { class: 'muted' }, 'Searching the graph.'), skel('w80 tall', 'w60', 'w40')];
  if (m.error) {
    return h('div', { class: 'err' }, h('p', {}, 'That question could not be answered.'),
      h('p', {}, 'Try again in a moment, or ask it another way.'), h('details', { 'data-key': `err-${n}` }, h('summary', {}, 'What the server said'), h('pre', {}, m.error)));
  }
  const d = m.data, [lead, rest, pre] = splitAnswer(d.answer);
  const hits = (d.hits || []).slice(0, 5), more = d.related || [];
  return [
    pre ? h('p', { class: 'a-pre' }, plain(pre)) : null,
    h('p', { class: 'a-lead' }, lead),
    rest ? h('details', { class: 'a-more', 'data-key': `more-${n}` }, h('summary', {}, 'More detail'), h('p', {}, rest)) : null,
    // each source opens in place to its quote (a <details>, so a re-render keeps it open)
    hits.length ? h('div', { class: 'a-sources' }, h('h3', {}, 'Sources'), h('ul', {}, hits.map((x, j) => h('li', {},
      h('details', { class: 'src', 'data-key': `src-${n}-${j}` },
        h('summary', {}, h('span', {}, kindWord(x.kind)), h('span', {}, x.title, x.superseded_by ? h('span', { class: 'tag' }, 'superseded') : null),
          h('span', {}, x.at ? dmon(x.at) : '')),
        h('blockquote', { class: 'quote' }, localTimes(x.snippet))))))) : null,
    more.length ? h('details', { 'data-key': `linked-${n}` }, h('summary', {}, `More linked (${more.length})`),
      h('ul', { class: 'linked' }, more.map((r) => h('li', {}, `${kindWord(r.kind)}: `, h('b', {}, r.name))))) : null,
    mobile() && m === state.chat.at(-1) && state.askHl ? h('button', { class: 'btn small', type: 'button', 'aria-controls': 'ask-phone-slot',
      'aria-expanded': String(state.askGraphOpen), 'data-key': 'ask-graph', onclick: () => toggleAskGraph() }, state.askGraphOpen ? 'Hide graph' : 'Show on graph') : null,
    cypherList(m.queries, `a${n}`)];
}

// Phone and tablet: the graph opens above the answer and scrolls into view.
function toggleAskGraph() {
  state.askGraphOpen = !state.askGraphOpen;
  renderChat(false);
  placeGraph();
  if (state.askGraphOpen) requestAnimationFrame(() => { G.refit(); renderGraphTools(); $('ask-phone-slot').scrollIntoView({ block: 'start' }); });
}

function renderChat(scroll = true) {
  const blocked = askBlocked();
  $('ask-blocked').hidden = !blocked;
  $('ask-blocked').textContent = blocked;
  $('ask-q').disabled = !!blocked;
  $('ask-go').disabled = !!blocked || state.asking;
  $('ask-q').placeholder = state.chat.length ? 'Ask a follow-up, for example: who is on call for it?' : 'Who owns kafka?';
  set('ask-examples', state.chat.length ? null : [h('h2', {}, 'Try one of these'),
    h('ul', {}, EXAMPLES.map((q, i) => h('li', {}, h('button', { class: 'btn small', type: 'button', disabled: !!blocked || state.asking,
      'data-key': `ex-${i}`, onclick: () => { askQ(q); $('ask-q').focus(); } }, q))))]);
  const turns = [];
  for (let i = 0; i < state.chat.length; i += 2) {
    turns.push(h('div', { class: 'turn' }, h('h2', { class: 'asked' }, 'You asked: ', h('b', {}, state.chat[i].text)),
      state.chat[i + 1] ? brainMessage(state.chat[i + 1], i / 2) : null));
  }
  set('chat-log', turns);
  if (scroll && turns.length > 1) turns.at(-1).scrollIntoView({ block: 'start' });
}

// One conversation per browser tab: ask remembers it in the graph (Session and Question nodes), so a follow-up can
// say "it" and "what did I ask about X" works. Keys match services/sessions.py (USER and KEY).
const CHAT = { user: `web-${Math.random().toString(36).slice(2, 10)}`, session: 'tab' }; // one asker per tab

async function askQ(q) {
  if (!q || state.asking || askBlocked()) return;
  state.asking = true;
  const m = { who: 'brain', pending: true };
  state.chat.push({ who: 'you', text: q }, m);
  renderChat();
  try {
    const r = await api('POST', `${T()}/tools/ask`, { question: q, user: CHAT.user, session: CHAT.session });
    Object.assign(m, { pending: false, data: r.data, queries: r.queries });
    learnNames({ tool: 'ask', data: r.data });
    announce(splitAnswer(r.data.answer)[0]);
    state.askHl = askHighlight(r);
    state.graphOwner = null; // repaint the answer's subgraph
  } catch (e) {
    Object.assign(m, { pending: false, error: e.message });
    announce('That question could not be answered. Try again in a moment, or ask it another way.');
  } finally {
    state.asking = false;
    renderChat();
    if (state.view === 'ask') placeGraph();
  }
}

// ---------- connect ----------
function renderConnect() {
  const origin = OFFLINE ? 'http://localhost:8000' : location.origin;
  // On a deployment (not localhost) the plugin step also shows remote mode: nothing local but the plugin.
  const deployed = !OFFLINE && !/^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
  const code = (text, label) => h('div', { class: 'code-wrap' }, h('pre', { tabindex: 0, 'aria-label': text.split('\n')[0] }, h('code', {}, text)),
    copyBtn(text, label, null, `copy-${label}-${text.length}`));
  const c = (text) => h('code', {}, text);
  const hl = state.health;
  // "at" pins the sample to the demo company's act-1 time (datagen.T1), where its changes sit; without it the alert is
  // stamped now and the demo graph has nothing recent to blame. A real alerting tool leaves it out.
  const curl = `curl -X POST '${origin}${T()}/alerts?respond=true' \\\n  -H 'content-type: application/json' \\\n  -d '{"service": "svc:checkout", "symptom": "latency", "name": "checkout p99 latency above 2s", "at": 1792036800}'`;
  const hook = OFFLINE ? 'needs the live server' : dbDown() ? 'not ready: FalkorDB is not reachable'
    : state.loadError ? 'not ready: this company could not load' : 'ready';
  const step = (n, title, ...kids) => h('li', {}, h('span', { class: 'num' }, n), h('div', {}, h('h2', {}, title), ...kids));
  set('connect',
    h('div', { class: 'connect-head' }, h('h1', { id: 'connect-title', tabindex: '-1' }, 'Connect'),
      h('p', {}, 'Plug On-call Brain into your alerts, your editor and Slack. Every agent tool is defined once and served three ways: '
        + 'to the agents, over MCP and over HTTP. Start with the webhook; each step works on its own.')),
    h('dl', { class: 'status-list' },
      h('dt', {}, 'FalkorDB'), h('dd', { class: hl?.falkordb || OFFLINE ? null : 'sig' }, OFFLINE ? 'not used by this recorded replay' : hl?.falkordb ? 'connected' : 'not reachable'),
      h('dt', {}, 'Alert webhook'), h('dd', { class: hook.startsWith('not ready') ? 'sig' : null }, hook),
      h('dt', {}, 'Slack'), h('dd', {}, hl?.slack ? 'connected' : 'not connected'),
      h('dt', {}, 'Steps chosen by'), h('dd', {}, plannerLabel()),
      h('dt', {}, 'Company (tenant)'), h('dd', {}, `${state.tenant || 'none'}${isDemo() ? ', the demo company' : ''}`)),
    h('ol', { class: 'connect-steps' },
      step(1, 'Send alerts in with the webhook',
        h('p', {}, 'Point your alerting tool at this endpoint and map its payload to service, symptom (latency, errors or saturation) and name. '
          + 'With respond=true the agents start right away and the incident shows up in the inbox. The sample pins "at" to the demo story\'s time; '
          + 'leave it out and the alert is stamped now.'),
        code(curl, 'Copy command')),
      step(2, 'Use it from Claude Code with the plugin',
        h('p', {}, 'The plugin ships the MCP server (the same graph tools the agents use, plus respond to alert) and three skills. From the repo, in your shell:'),
        code('claude --plugin-dir ./plugin', 'Copy command'),
        h('p', {}, 'Then, inside Claude Code:'),
        code('/oncall-brain:incident alert:checkout-latency\n/oncall-brain:who-owns kafka', 'Copy commands'),
        deployed ? h('p', {}, 'Against this deployment, with nothing local but the plugin (the token is the MCP_TOKEN set on the host):') : null,
        deployed ? code(`ONCALL_BRAIN_URL=${origin} ONCALL_BRAIN_TOKEN=<MCP_TOKEN> claude --plugin-dir ./plugin`, 'Copy command') : null,
        h('p', { class: 'small muted' }, 'Any other MCP client: ', c('python -m oncall_brain.mcp_server'), ' (stdio) or ', c('--http --port 8001'), '.'),
        state.tools?.length ? h('details', { 'data-key': 'tools' }, h('summary', {}, `The ${plural(state.tools.length, 'graph tool')} it serves`),
          h('ul', { class: 'tool-list' }, state.tools.map((t) => h('li', {}, c(t))))) : null),
      step(3, 'Post status updates to Slack',
        hl?.slack ? h('p', {}, 'Connected: every status update is also posted to your channel.')
          : [h('p', {}, 'Not connected yet. Create an incoming webhook in Slack (Apps, then Incoming Webhooks), add it to .env and restart the server:'),
            code('SLACK_WEBHOOK_URL=https://hooks.slack.com/services/…', 'Copy line')]),
      step(4, 'Bring your own data',
        h('p', {}, `This demo runs on a synthetic company (${state.graph ? plural(state.graph.nodes.length, 'service') : 'services'}, teams, people and changes). `
          + 'Real systems feed the same graph as things happen, through write tools on MCP and HTTP:'),
        h('ul', {},
          h('li', {}, c('record_change'), ' from CI/CD (deploys, config changes)'),
          h('li', {}, c('record_anomaly'), ' and ', c('raise_alert'), ' from monitoring'),
          h('li', {}, c('add_dependency'), ' and ', c('retire_dependency'), ' from the service catalog'),
          h('li', {}, c('record_doc'), ' from your wiki (decision records, design notes, postmortems, runbook pages)'),
          h('li', {}, c('record_message'), ' from chat (a message and what it mentions)'),
          h('li', {}, c('record_ticket'), ' from your tracker (a ticket, the change it asks for, the initiative it is part of)')),
        h('p', { class: 'small muted' }, 'Every write is an idempotent MERGE on the record\'s id: send the source\'s id or time and replays and retries are safe.')),
      step(5, 'Keep each company in its own graph',
        h('p', {}, 'One FalkorDB graph per company (tenant): memory, incidents and knowledge never mix. ', h('b', {}, `This company: ${state.tenant || 'none'}.`),
          ' Add ', c('?tenant=<name>'), ' to the URL to open another.'),
        OFFLINE ? null : resetControl('connect')),
      step(6, 'Choose who decides each step',
        h('p', {}, 'Now: ', h('b', {}, plannerLabel()), '. Set ', c('LLM_PROVIDER'), ' (anthropic, openai, gemini, groq, ollama) and a key in ', c('.env'),
          ' to let a model choose the tools; without one, rules choose each step from what the graph returns. Either way every fact comes from a graph query, '
          + 'and each run is capped in tokens.'))));
}

// ---------- startup ----------
async function loadTenant() {
  if (!OFFLINE && !state.tools) api('GET', '/api/tools').then((t) => { state.tools = t.map((x) => x.name); if (state.view === 'connect') renderConnect(); }, () => {});
  state.alerts = await api('GET', `${T()}/alerts`);
  const g = state.graph = await api('GET', `${T()}/graph`);
  G.build($('graph'), g);
  state.graphOwner = null;
  renderGraphTools();
}

// Event listeners, once.
function wire() {
  for (const b of document.querySelectorAll('.view-tab')) b.onclick = () => showView(b.dataset.view, true);
  $('tab-answer').onclick = () => tabTo('answer');
  $('tab-why').onclick = () => tabTo('why');
  document.querySelector('.seg').addEventListener('keydown', (e) => {
    const to = { ArrowLeft: state.tab === 'answer' ? 'why' : 'answer', ArrowRight: state.tab === 'answer' ? 'why' : 'answer', Home: 'answer', End: 'why' }[e.key];
    if (!to) return;
    e.preventDefault();
    tabTo(to);
    $(to === 'answer' ? 'tab-answer' : 'tab-why').focus({ preventScroll: true });
  });
  $('btn-back').onclick = () => showIncident(null);
  $('btn-simulate').onclick = (e) => {
    e.stopPropagation();
    if (!$('simulate-menu').hidden) return closeMenus();
    renderSimulateMenu();
    $('simulate-menu').hidden = false;
    if (mobile()) sheetModal(true);
    $('btn-simulate').setAttribute('aria-expanded', 'true');
    const m = $('simulate-menu');
    (m.querySelector('.scenarios button:not([disabled])') || m.querySelector('.custom summary') || m.querySelector('.menu-close'))?.focus();
  };
  const menu = $('simulate-menu');
  menu.addEventListener('click', (e) => e.stopPropagation());
  // Arrow keys, Home and End move between the menu's controls (not inside the custom alert's fields).
  menu.addEventListener('keydown', (e) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key) || /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    const items = [...menu.querySelectorAll('button:not([disabled]), summary')] // not the fields of a closed <details>
      .filter((el) => el.tagName === 'SUMMARY' || !el.closest('details:not([open])'));
    const i = items.indexOf(document.activeElement);
    const j = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : (i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    e.preventDefault();
    items[j]?.focus();
  });
  // Focus leaving the menu closes it (a re-render inside it has no relatedTarget, so it stays open).
  $('menu-wrap').addEventListener('focusout', (e) => { if (e.relatedTarget && !$('menu-wrap').contains(e.relatedTarget)) closeMenus(); });
  document.addEventListener('click', () => closeMenus());
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (cancelReset()) return; // a reset confirm (in the menu or on Connect) closes first
    if (!$('simulate-menu').hidden) return closeMenus(true);
    if (state.current?.showAlt && state.view === 'incidents') closeAlts(state.current);
  });
  $('toast-close').onclick = () => { $('toast').hidden = true; };
  $('why-side').addEventListener('click', onStepClick);
  $('ask-form').onsubmit = (e) => {
    e.preventDefault(); // the native form gives Enter-to-ask; never navigate
    const q = $('ask-q').value.trim();
    $('ask-q').value = '';
    askQ(q);
  };
  matchMedia('(max-width: 899px)').addEventListener('change', () => {
    renderAll();
    if (state.view === 'ask') renderChat(false);
    if (state.view === 'ask' && state.askHl) state.graphOwner = null; // the scoped layout direction depends on the width
    else if (state.tab === 'why' && state.current) replayGraph(state.current);
    placeGraph();
  });
}

// Health, company, data, first render.
async function boot() {
  // GitHub Pages has no API to ask: go straight to the recorded replay (no failed request in the console).
  if (!OFFLINE && location.hostname.endsWith('github.io')) {
    params.set('offline', '1');
    location.search = params.toString();
    return;
  }
  if (OFFLINE) {
    $('btn-simulate').textContent = 'Replay an incident';
    $('simulate-menu').setAttribute('aria-label', 'Replay an incident');
  }
  placeGraph();
  showIncident(null, false);
  let hl;
  try {
    // A 503 with the health body = FalkorDB down: show it.
    hl = state.health = await api('GET', '/api/health').catch((e) => { if (!OFFLINE && e.status === 503 && 'falkordb' in (e.body || {})) return e.body; throw e; });
  } catch (e) {
    if (!OFFLINE && (e.status === 404 || e.notJson)) { // a static host with no API: replay the recorded runs instead
      params.set('offline', '1');
      location.search = params.toString();
      return;
    }
    state.loaded = true;
    state.loadError = OFFLINE ? { title: 'The recorded runs could not load.', hint: 'Reload the page. The recordings live in web/fixtures next to this page.', raw: e.message }
      : { title: 'The server is not answering.', hint: 'Reload in a moment; the server may be restarting. A recorded run of the agents works without it.',
        action: h('p', {}, h('a', { class: 'btn', href: `${location.pathname}?offline=1` }, 'Open the recorded run')), raw: e.message };
    announce(state.loadError.title);
    simButtonState();
    return renderAll();
  }
  const tenant = params.get('tenant'), bad = tenant != null && !/^[a-z0-9_]{1,40}$/.test(tenant);
  state.tenant = tenant && !bad ? tenant : hl.default_tenant;
  if (OFFLINE) hl.falkordb = true; // a recording of real runs; the live line is not shown offline anyway
  if (bad) { // a mistyped company must not silently open the demo company
    state.tenant = tenant;
    state.loadError = { title: `“${tenant}” is not a company name here.`, hint: 'Company names use a to z, 0 to 9 and _. Check the link, or open the demo company.',
      action: demoLink() };
    announce(state.loadError.title);
  } else {
    try {
      await loadTenant();
    } catch (e) {
      state.loadError = describeLoadError(e);
      if (state.loadError.title) announce(state.loadError.title);
    }
  }
  state.loaded = true;
  simButtonState();
  renderAll();
}

wire();
boot();
