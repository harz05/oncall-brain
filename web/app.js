// On-call Brain UI: replays an agent run (RunResult from the API) as a step-by-step trace while lighting up
// each step's evidence on the service graph. No build step. Every piece of data reaches the DOM as text
// (see h()), never as HTML.

const params = new URLSearchParams(location.search);
const OFFLINE = params.has('offline'); // ?offline=1 replays web/fixtures (generated from the real code)
const STEP_MS = Number(params.get('step_ms')) || 750;
const ACTS = [1, 2, 3]; // one #btn-actN each; the alerts of an act come from GET /alerts
const COUNT = ['', 'one', 'two', 'three', 'four', 'five'];
const FONT = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
const C = {
  bg: '#0b1020', svc: '#162033', svcBorder: '#3a4a64', lit: '#1d3b61', text: '#dbe4f0', t1: '#7dd3fc',
  edge: '#4b5b75', hot: '#fde047', cause: '#fb7a3c', chg: '#f5b041', person: '#2dd4bf', team: '#60a5fa',
  inc: '#b48cff', rb: '#34d399', refuted: '#6b7689', alert: '#f87171', shared: '#e879f9', sharedBg: '#3f1a47',
};
// Satellite (non-service) node kinds, with the direction (degrees, y down) we prefer to place them from
// their anchor. Anything else in a highlight (ticket:, msg:, alert:) stays off the graph.
const SAT_ANGLE = { chg: 90, person: -60, team: -90, inc: -140, rb: 180 };

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const kindOf = (id) => id.split(':', 1)[0];
const short = (id) => (id ? id.slice(id.indexOf(':') + 1) : '');
const names = new Map(); // id -> friendlier graph label learned from step data (people, teams)
const state = { tenant: '', acts: {}, alerts: {}, cy: null, run: null, best: {}, busy: false, next: 'btn-reset', skip: false };

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
const pathChips = (ids) => h('span', { class: 'path' }, ids.map((id, i) => [i ? h('span', { class: 'arrow' }, '→') : null,
  h('span', { class: 'hop' }, short(id))]));
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const ist = (at) => new Date(at * 1000).toLocaleString('en-GB', {
  timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) + ' IST';

function status(text, isError = false) {
  const el = $('status');
  el.textContent = text;
  el.title = text; // the line is ellipsized on narrow screens
  el.classList.toggle('error', isError);
}

// ---------- API ----------
async function api(method, path, body) {
  if (OFFLINE) return fixture(path);
  const r = await fetch(path, { method, headers: body ? { 'content-type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `${r.status} ${r.statusText}`);
  return data;
}

async function fixture(path) {
  const p = decodeURIComponent(path);
  if (p.endsWith('/reset')) return { tenant: state.tenant, status: 'restored' };
  const routes = [[/\/health$/, 'health'], [/\/alerts$/, 'alerts'], [/\/graph/, 'graph'], [/\/resolve$/, 'resolve'],
    [/checkout-latency\/respond$/, 'act1'], [/refunds-latency\/respond$/, 'act2'],
    [/subscriptions-latency\/respond$/, 'act3']];
  const hit = routes.find(([re]) => re.test(p));
  if (!hit) throw new Error(`no offline fixture for ${p}`);
  await sleep(300);
  return (await fetch(new URL(`fixtures/${hit[1]}.json`, import.meta.url))).json();  // works on any static host
}
const T = () => `/api/tenants/${encodeURIComponent(state.tenant)}`;

// ---------- graph ----------
const STYLE = [
  { selector: 'node', style: { label: 'data(label)', 'font-family': FONT, 'font-size': 13, color: C.text,
    'text-valign': 'center', 'text-halign': 'center', 'transition-property': 'opacity, background-color, border-color',
    'transition-duration': 300 } },
  { selector: 'node.svc', style: { shape: 'round-rectangle', width: 'data(w)', height: 30, 'background-color': C.svc,
    'border-width': 1.5, 'border-color': C.svcBorder } },
  { selector: 'node.t1', style: { 'border-width': 2.5, 'border-color': C.t1, 'font-weight': 600 } },
  { selector: 'node.sat', style: { width: 18, height: 18, 'font-size': 11, 'text-valign': 'bottom', 'text-margin-y': 4,
    'text-background-color': C.bg, 'text-background-opacity': 0.75, 'text-background-padding': 2, 'border-width': 0 } },
  { selector: 'node.chg', style: { shape: 'diamond', width: 24, height: 24, 'background-color': C.chg } },
  { selector: 'node.person', style: { shape: 'ellipse', 'background-color': C.person } },
  { selector: 'node.team', style: { shape: 'hexagon', width: 22, 'background-color': C.team } },
  { selector: 'node.inc', style: { shape: 'octagon', 'background-color': C.inc } },
  { selector: 'node.rb', style: { shape: 'round-rectangle', width: 26, height: 16, 'background-color': C.rb } },
  { selector: 'edge', style: { width: 1.5, 'line-color': C.edge, 'target-arrow-color': C.edge,
    'target-arrow-shape': 'triangle', 'arrow-scale': 0.8, 'curve-style': 'bezier',
    'transition-property': 'opacity, line-color, width', 'transition-duration': 300 } },
  { selector: 'edge.changed', style: { 'line-color': C.chg, 'target-arrow-color': C.chg, width: 2 } },
  { selector: 'edge.owns, edge.on_call', style: { 'line-color': C.team, 'target-arrow-color': C.team, 'line-style': 'dotted' } },
  { selector: 'edge.recalls', style: { 'line-color': C.inc, 'target-arrow-color': C.inc, width: 2.5 } },
  { selector: 'edge.fixed_with', style: { 'line-color': C.rb, 'target-arrow-color': C.rb, width: 2.5 } },
  { selector: 'edge.caused_by', style: { 'line-color': C.cause, 'target-arrow-color': C.cause, width: 2.5 } },
  { selector: 'edge.retired', style: { 'line-style': 'dashed', 'line-color': C.refuted, 'target-arrow-color': C.refuted,
    opacity: 0.45 } },
  { selector: '.dim', style: { opacity: 0.12 } },
  { selector: '.ctx', style: { opacity: 0.5 } },
  { selector: 'node.svc.touched', style: { 'background-color': C.lit } },
  { selector: 'edge.dep.touched', style: { width: 2.5, 'line-color': '#7b8db0', 'target-arrow-color': '#7b8db0' } },
  { selector: 'node.svc.shared', style: { 'background-color': C.sharedBg, 'border-color': C.shared, 'border-width': 2 } },
  { selector: 'node.alerting', style: { 'border-color': C.alert, 'border-width': 3 } },
  { selector: 'node.refuted', style: { 'background-color': C.refuted, color: '#8a94a6' } },
  { selector: 'node.hot', style: { 'border-color': C.hot, 'border-width': 3, 'underlay-color': C.hot,
    'underlay-opacity': 0.25, 'underlay-padding': 7 } },
  { selector: 'edge.hot', style: { 'line-color': C.hot, 'target-arrow-color': C.hot, width: 3.5, opacity: 1 } },
  // Alert storm: the alerting services and the top convergence point keep their colour even while lit (hot).
  { selector: 'node.storm', style: { 'border-color': C.alert, 'border-width': 3.5, 'underlay-color': C.alert,
    'underlay-opacity': 0.3, 'underlay-padding': 7 } },
  { selector: 'node.choke', style: { 'border-width': 3.5, 'underlay-color': C.shared, 'underlay-opacity': 0.35,
    'underlay-padding': 8 } },
  { selector: 'node.note', style: { width: 1, height: 1, 'background-opacity': 0, 'border-width': 0, 'underlay-opacity': 0,
    color: C.shared, 'font-size': 12.5, 'font-weight': 600, 'text-wrap': 'wrap' } }, // after .hot: only its label shows
  { selector: 'edge.note-link', style: { width: 1.5, 'line-color': C.shared, 'line-style': 'dotted',
    'target-arrow-shape': 'none' } },
  { selector: 'edge.recalls.hot', style: { 'line-color': C.inc, 'target-arrow-color': C.inc, 'underlay-color': C.inc,
    'underlay-opacity': 0.3, 'underlay-padding': 5 } },
  { selector: 'node.cause', style: { 'border-color': C.cause, 'border-width': 3.5, 'underlay-color': C.cause,
    'underlay-opacity': 0.35, 'underlay-padding': 9 } },
  { selector: 'edge.cause', style: { 'line-color': C.cause, 'target-arrow-color': C.cause, width: 5,
    'underlay-color': C.cause, 'underlay-opacity': 0.3, 'underlay-padding': 6, opacity: 1 } },
];

function hudIdle() {
  $('hud').replaceChildren(h('span', { class: 'muted' }, state.graphCaption || ''));
}

function buildGraph(g) {
  state.cy?.destroy();
  state.cy = null;
  if (typeof cytoscape === 'undefined') {
    $('graph').textContent = 'Graph library did not load (is the CDN reachable?). The trace still works.';
    return;
  }
  const elements = [
    ...g.nodes.map((n) => ({ group: 'nodes', classes: n.tier === 1 ? 'svc t1' : 'svc',
      data: { id: n.id, label: n.name, w: n.name.length * 8 + 28 } })),
    ...g.edges.map((e) => ({ group: 'edges', classes: e.live ? 'dep' : 'dep retired',
      data: { id: `${e.source}>${e.target}>DEPENDS_ON`, source: e.source, target: e.target } })),
  ];
  // Callers on the left, dependencies on the right. Built-in breadthfirst (rotated) if dagre did not load.
  const layout = typeof cytoscapeDagre !== 'undefined'
    ? { name: 'dagre', rankDir: 'LR', nodeSep: 14, rankSep: 90, padding: 24 }
    : { name: 'breadthfirst', directed: true, padding: 30, transform: (_, p) => ({ x: p.y * 1.6, y: p.x / 1.6 }) };
  const retired = g.edges.filter((e) => !e.live).length;
  state.graphCaption = `Service dependency graph · ${g.nodes.length} services · ${g.edges.length} dependencies`
    + ` (${retired} retired) · callers left, dependencies right`;
  hudIdle();
  state.cy = cytoscape({ container: $('graph'), elements, style: STYLE, layout, minZoom: 0.25, maxZoom: 1.3,
    boxSelectionEnabled: false, autoungrabify: true });
}

// Place a satellite next to its anchor, at the first spot (preferred angle first, then fanning out) that does
// not overlap a node or its label. ponytail: O(nodes) per candidate, fine for the ~60 nodes we ever draw.
function freeSpot(base, pref, W = 92) {
  const boxes = state.cy.nodes().map((n) => n.boundingBox({ includeLabels: true }));
  const UP = 16, DOWN = 32; // satellite icon plus its label underneath (W wide)
  for (const r of [60, 95, 130, 170, 220]) {
    for (let k = 0; k < 12; k++) {
      const a = ((pref + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 30) * Math.PI) / 180;
      const p = { x: base.x + r * Math.cos(a), y: base.y + r * Math.sin(a) };
      if (boxes.every((b) => p.x + W / 2 < b.x1 || p.x - W / 2 > b.x2 || p.y + DOWN < b.y1 || p.y - UP > b.y2)) return p;
    }
  }
  return { x: base.x, y: base.y + 70 };
}

function ensureNode(id, anchorId) {
  const cy = state.cy;
  const kind = kindOf(id);
  if (cy.getElementById(id).nonempty() || !(kind in SAT_ANGLE)) return;
  const home = state.run?.res.alert.service;
  const anchor = cy.getElementById(id === state.run?.res.incident_id ? home : anchorId);
  const base = anchor.nonempty() ? anchor.position() : (cy.getElementById(home).nonempty()
    ? cy.getElementById(home).position() : { x: 0, y: 0 });
  cy.add({ group: 'nodes', classes: `sat ${kind}`, data: { id, label: names.get(id) || short(id) },
    position: freeSpot(base, SAT_ANGLE[kind]) });
}

// Turn a highlight {nodes, edges} into graph elements, adding satellites and non-DEPENDS_ON edges on the fly.
// Satellites without an edge (e.g. who_knows people) sit next to the highlight's first service.
function elementsFor(hl) {
  const cy = state.cy;
  if (!cy || !hl) return null;
  const has = (id) => cy.getElementById(id).nonempty();
  const home = (hl.nodes || []).find((id) => kindOf(id) === 'svc' && has(id)) || state.run?.res.alert.service;
  let eles = cy.collection();
  for (const [s, t, rel] of hl.edges || []) {
    if (![s, t].every((id) => has(id) || kindOf(id) in SAT_ANGLE)) continue; // e.g. CORRELATED_WITH an alert: id
    if (!has(s) && !has(t)) ensureNode(s, home);
    if (!has(s)) ensureNode(s, t);
    if (!has(t)) ensureNode(t, s);
    if (!has(s) || !has(t)) continue;
    const id = `${s}>${t}>${rel}`;
    eles = eles.union(has(id) ? cy.getElementById(id)
      : cy.add({ group: 'edges', classes: `rel ${rel.toLowerCase()}`, data: { id, source: s, target: t } }));
  }
  for (const id of hl.nodes || []) {
    ensureNode(id, home);
    eles = eles.union(cy.getElementById(id));
  }
  return eles.union(eles.connectedNodes());
}

// Alert storm (correlate_alerts): alert ids are not graph nodes, so the alerting services get the alert style,
// the shared upstream a tint, and the top convergence point a note. Returns the note to light with the step.
function markStorm(d) {
  const cy = state.cy;
  cy.getElementById(state.run.res.alert.service).addClass('alerting storm');
  for (const a of d.alerts) cy.getElementById(a.service).addClass('alerting storm');
  for (const s of d.shared) cy.getElementById(s.service).addClass('shared');
  const top = d.shared[0] && cy.getElementById(d.shared[0].service);
  if (!top?.nonempty()) return cy.collection();
  top.addClass('choke');
  const label = `paths converge here\n${d.shared[0].hops} hops from the alerts`;
  const note = cy.add({ group: 'nodes', classes: 'sat note', data: { id: 'note:choke', label },
    position: freeSpot(top.position(), 90, 150) });
  return note.union(cy.add({ group: 'edges', classes: 'note-link',
    data: { id: 'note:choke>link', source: note.id(), target: top.id() } }));
}

// Fade everything except what this run touched (plus one dependency hop of context); brighten `hot`.
// Works without a run too (company-brain answers before act 1).
function paint(hot, focus) {
  const cy = state.cy;
  if (!cy) return;
  const touched = state.run?.touched || cy.collection();
  hot = hot || cy.collection();
  cy.batch(() => {
    cy.elements().removeClass('hot ctx touched cause').addClass('dim');
    const ctx = touched.union(hot).nodes('.svc').connectedEdges('.dep');
    ctx.union(ctx.connectedNodes()).removeClass('dim').addClass('ctx');
    touched.removeClass('dim ctx').addClass('touched');
    state.run?.cause.addClass('cause');
    hot.removeClass('dim ctx').addClass('hot');
  });
  const target = focus && focus.nonempty() ? focus : touched;
  if (target.nonempty()) {
    cy.stop(true);
    cy.animate({ fit: { eles: target, padding: 36 }, duration: 450, easing: 'ease-in-out-cubic' });
  }
}

function resetGraphView() {
  const cy = state.cy;
  if (!cy) return;
  cy.remove('.sat');
  cy.elements().removeClass('dim ctx touched hot cause refuted alerting storm shared choke');
  cy.stop(true);
  cy.animate({ fit: { padding: 30 }, duration: 300 });
}

// ---------- trace ----------
function learnNames(step) {
  const d = step.data;
  if (step.tool === 'page_on_call' && d && d.person) {
    names.set(d.person, d.name);
    names.set(d.team, `${d.team_name} team`);
  }
  if (step.tool === 'who_knows') for (const p of d || []) names.set(p.person, p.name);
}

function queryBlock(q) {
  return h('div', { class: 'q' },
    h('div', { class: 'qhead' },
      h('b', {}, q.name),
      h('span', { class: `rw ${q.readonly ? 'ro' : 'w'}`, title: q.readonly ? 'GRAPH.RO_QUERY' : 'GRAPH.QUERY (writes)' },
        q.readonly ? 'RO' : 'W'),
      h('span', { class: 'muted' }, `${q.rows.length} rows · ${q.ms} ms`),
      q.name === 'incident_board' ? h('span', { class: 'tag' }, 'planner reads the shared board') : null),
    h('pre', { class: 'cypher' }, q.cypher),
    h('pre', { class: 'params' }, `params ${JSON.stringify(q.params)}`),
    q.rows.length ? h('details', { class: 'rows' }, h('summary', {}, `rows (${q.rows.length})`),
      h('pre', {}, JSON.stringify(q.rows, null, 1))) : null);
}

function cypherList(queries) {
  const ms = queries.reduce((a, q) => a + q.ms, 0);
  const rows = queries.reduce((a, q) => a + q.rows.length, 0);
  return h('details', { class: 'cypher-list' },
    h('summary', {}, `Cypher: ${queries.length === 1 ? '1 query' : `${queries.length} queries`}, ${plural(rows, 'row')}, `
      + `${ms.toFixed(1)} ms`),
    queries.map(queryBlock));
}

function stepCard(step, i) {
  if (step.tool === 'handoff') {
    const to = (step.summary.match(/hands off to (\S+)/) || [])[1] || '?';
    return h('li', { class: 'handoff', 'data-i': i },
      h('div', { class: 'handoff-line' }, h('span', { class: `role ${step.role}` }, step.role), h('span', { class: 'arrow' }, '→'),
        h('span', { class: `role ${to}` }, to)),
      h('p', { class: 'why' }, step.reason));
  }
  const d = step.data;
  const verdict = step.tool === 'check_hypothesis' && d ? d.verdict : null;
  const body = verdict
    ? h('p', { class: 'summary' }, h('span', { class: `verdict ${verdict}` }, verdict.toUpperCase()), ' ',
      verdict === 'supports' ? h('b', {}, short(d.change)) : h('s', {}, short(d.change)), ` on ${short(d.service)}: `,
      h('span', { class: 'reason' }, d.reason),
      verdict === 'supports' && d.live_path?.length > 1 ? pathChips(d.live_path) : null)
    : h('p', { class: 'summary' }, step.summary);
  return h('li', { class: `card ${step.role}${verdict ? ` v-${verdict}` : ''}`, 'data-i': i, tabindex: 0 },
    h('div', { class: 'card-head' },
      h('span', { class: `role ${step.role}` }, step.role),
      h('code', { class: 'tool' }, step.tool),
      h('span', { class: 'seq' }, `#${step.seq}`)),
    body,
    h('p', { class: 'why' }, h('span', { class: 'why-label' }, 'why '), step.reason),
    cypherList(step.queries));
}

function reveal(i) {
  const run = state.run, step = run.res.steps[i];
  learnNames(step);
  const li = stepCard(step, i);
  $('trace').querySelector('.current')?.classList.remove('current');
  li.classList.add('current');
  $('trace').append(li);
  li.scrollIntoView({ block: 'nearest', behavior: state.skip ? 'auto' : 'smooth' });
  $('trace-count').textContent = `${i + 1}/${run.res.steps.length}`; // short: must share 380px with tabs + Skip
  if (step.role === 'investigator' && step.tool !== 'handoff') run.calls++;
  if (step.tool === 'check_hypothesis') run.hyps++;
  renderCounter();
  let eles = elementsFor(step.highlight); // the server already keeps only strong recalls in the highlight
  if (!eles) return;
  if (step.tool === 'correlate_alerts' && step.data?.alerts.length) eles = eles.union(markStorm(step.data));
  step.eles = eles;
  run.touched = run.touched.union(eles);
  if (step.tool === 'check_hypothesis' && step.data) {
    if (step.data.verdict === 'supports') run.cause = run.cause.union(eles);
    else state.cy.getElementById(step.data.change).addClass('refuted');
  }
  paint(eles);
}

function onTraceClick(ev) {
  if (ev.target.closest('summary, pre, details[open] *')) return; // let people read/expand Cypher
  const li = ev.target.closest('li[data-i]');
  if (!li || !state.run) return;
  $('trace').querySelectorAll('.selected').forEach((x) => x.classList.remove('selected'));
  li.classList.add('selected');
  const step = state.run.res.steps[Number(li.dataset.i)];
  if (step?.eles) paint(step.eles, step.eles);
}

// ---------- outcome ----------
function renderCounter() {
  const run = state.run, o = run.res.outcome;
  const prev = run.act === 2 && state.best[1];
  const num = (label, now, before) => h('div', { class: 'num' },
    h('span', { class: 'big' }, before != null ? [h('span', { class: 'before' }, before), h('span', { class: 'arrow' }, '→'), now] : now),
    h('span', { class: 'lbl' }, label));
  const ctc = run.done ? o.checks_to_culprit : null; // shown once the replay ends, so it can't spoil it
  const el = h('div', { class: 'card counter', id: 'counter' },
    h('h3', {}, run.act === 2 && prev ? 'Act 2 vs act 1' : `Act ${run.act}`),
    h('div', { class: 'nums' },
      num('investigator calls', run.calls, run.done && prev ? prev.calls : null),
      num('hypotheses checked', run.hyps, run.done && prev ? prev.hyps : null)),
    ctc != null ? h('p', { class: 'ctc' }, `culprit on check ${ctc} of ${o.hypotheses_checked}`,
      prev?.checks != null ? h('span', { class: 'muted' }, ` (act 1: ${prev.checks} of ${prev.hyps})`) : null) : null,
    run.done && o.memory.solved_by_memory ? h('span', { class: 'pill memory' }, 'solved by memory') : null);
  const old = $('counter');
  if (old) old.replaceWith(el);
  else $('outcome').prepend(el);
}

function intro() {
  $('outcome').replaceChildren(h('div', { class: 'card intro' },
    h('h3', {}, 'How to read this demo'),
    h('ol', {},
      h('li', {}, 'Triage, investigator and comms agents hand off through one Incident node in FalkorDB; each decision re-reads that board.'),
      h('li', {}, 'Every suspect change is tested by traversal at alert time; decoys are refuted with the Cypher that refuted them.'),
      h('li', {}, 'A confirmed fix is written back as a runbook, so the next incident is recalled by graph structure.'))));
}

function renderOutcome() {
  const res = state.run.res, o = res.outcome;
  const rc = o.root_cause, bp = o.baseline_pick, ab = o.anomaly_baseline_pick, mem = o.memory, rb = o.runbook,
    ex = o.expert;
  const cites = res.steps.find((s) => s.tool === 'post_update')?.data?.cites || [];
  const recalled = mem.recalled[0];

  const cause = h('div', { class: 'card cause' },
    h('h3', {}, 'Root cause'),
    rc ? [h('p', { class: 'lead' }, h('b', {}, short(rc.change)), ` on ${short(rc.service)}`), pathChips(rc.live_path)]
      : h('p', {}, 'No suspect was supported by the graph.'),
    rb || ex ? h('div', { class: 'next' },
      rb ? h('p', {}, h('span', { class: 'k' }, 'Next action'), rb.steps?.[0] || rb.title,
        h('span', { class: 'sub' }, `runbook “${rb.title}”`,
          rb.uses != null ? ` · worked ${rb.successes ?? 0} of ${rb.uses} times` : '')) : null,
      ex ? h('p', {}, h('span', { class: 'k' }, 'Ask'), h('b', {}, ex.name), ` (${ex.handle}, ${ex.team})`,
        ex.changes != null ? h('span', { class: 'sub' }, `authored ${plural(ex.changes, 'change')}`) : null) : null)
      : null,
    bp ? h('p', { class: `baseline ${o.baseline_correct ? 'ok' : 'bad'}` },
      'Flat change log would blame: ', h('b', {}, short(bp.change)), ' ',
      h('span', { class: 'pill' }, o.baseline_correct ? 'same answer' : 'wrong'),
      h('span', { class: 'sub' }, bp.summary)) : null,
    ab ? h('p', { class: `baseline ${o.anomaly_baseline_correct ? 'ok' : 'bad'}` },
      'Change log + anomalies (no graph) would blame: ', h('b', {}, short(ab.change)), ' ',
      h('span', { class: 'pill' }, o.anomaly_baseline_correct ? 'same answer' : 'wrong'),
      h('span', { class: 'sub' }, ab.summary)) : null,
    rc ? [h('p', {}, rc.summary), h('p', { class: 'muted' }, rc.reason)] : null,
    (o.co_causes || []).map((c) => h('p', { class: 'baseline' }, 'Also contributing: ', h('b', {}, short(c.change)),
      ` on ${short(c.service)}`, h('span', { class: 'sub' }, c.reason))));

  const ruled = h('div', { class: 'card ruled' },
    h('h3', {}, `Ruled out (${o.refuted.length})`),
    o.refuted.length ? h('ul', {}, o.refuted.map((r) => h('li', {},
      h('s', {}, short(r.change)), ` on ${short(r.service)}: `, h('span', { class: 'reason' }, r.reason))))
      : h('p', { class: 'muted' }, 'Nothing to rule out: memory went straight to the cause.'));

  const memory = h('div', { class: 'card memory-card' },
    h('h3', {}, 'Memory'),
    recalled ? h('p', {}, 'Recalled ', h('b', {}, `“${recalled.title}”`), ` (${recalled.incident}), runbook `,
      h('b', {}, `“${recalled.runbook_title}”`), '. ',
      mem.solved_by_memory ? h('span', { class: 'pill memory' }, 'solved by memory')
        : h('span', { class: 'muted' }, mem.suspects.length ? 'Its suspect was refuted, so the search widened.'
          : `No change on ${short(recalled.cause_service)} in this window, so the search widened.`))
      : h('p', { class: 'muted' }, 'No similar past incident on this dependency path.'),
    h('div', { id: 'learned' }),
    h('p', {}, h('span', { class: 'k' }, 'Paged '), o.paged.map((p, i) => [i ? ', ' : '', h('b', {}, p.name),
      ` ${p.handle} (${p.team_name})`])),
    h('p', {}, h('span', { class: 'k' }, 'Impact '), o.blast_radius.map(short).join(', ') || 'none'),
    h('p', {}, h('span', { class: 'k' }, 'Also at risk '), o.at_risk.map(short).join(', ') || 'none'));

  const update = h('div', { class: 'card update' },
    h('h3', {}, 'Status update posted to #incidents'),
    h('pre', {}, o.update_text || '(none)'),
    cites.length ? h('p', {}, h('span', { class: 'k' }, 'Sources '), cites.map((c) => h('span', { class: 'src' }, c))) : null);

  const st = o.storm, alerts = st ? [...st.alerts, { ...res.alert, name: res.alert.alert }] : [];
  const storm = st && h('div', { class: 'card storm' },
    h('h3', {}, 'Alert storm'),
    h('p', { class: 'lead' }, h('b', {}, `${alerts.length} alerts`), ' → 1 incident'),
    h('span', { class: 'path' }, alerts.sort((a, b) => a.at - b.at).map((a) =>
      h('span', { class: 'hop alerting', title: `${a.name} · ${ist(a.at)}` }, short(a.service)))),
    h('p', {}, h('span', { class: 'k' }, 'Shared upstream'), h('span', { class: 'muted' }, 'nearest to all alerts first')),
    h('ol', { class: 'shared-list' }, st.shared.slice(0, 3).map((s) => h('li', { value: s.rank },
      h('span', {}, short(s.service)), h('span', { class: 'score' }, `${s.hops} hops`)))),
    state.run.act === 3 ? h('p', { class: 'caption' },
      'Without correlating the alerts, the same planner blames subs-88: it explains only one alert (see make demo).') : null);

  $('outcome').classList.toggle('has-storm', !!st);
  $('outcome').replaceChildren(...[h('div', { id: 'counter' }), storm, cause, ruled, memory, update].filter(Boolean));
  renderCounter();
}

function renderLearned(r) {
  const d = r.data;
  $('learned').replaceChildren(h('div', { class: 'learned' },
    h('p', {}, h('span', { class: 'pill rb' }, 'saved to memory'), ' ', d ? ['runbook ', h('b', {}, `“${d.title}”`),
      ` (${d.successes} success${d.successes === 1 ? '' : 'es'})`] : r.summary),
    d ? h('ol', {}, d.steps.map((s) => h('li', {}, s))) : null));
}

// ---------- company brain (track 03): the registry tools agents and MCP clients use, asked directly ----------
function showTab(ask) {
  $('tab-trace').setAttribute('aria-selected', String(!ask));
  $('tab-ask').setAttribute('aria-selected', String(ask));
  $('trace').hidden = ask;
  $('trace-count').hidden = ask;
  $('ask').hidden = !ask;
  if (ask) return;
  if (state.run) paint(); // drop an answer's highlight, back to the run's picture
  else resetGraphView();
}

// Pickers: every service in the graph (filled by loadTenant), every change this run looked at (root cause first).
function fillAsk() {
  if (OFFLINE) return;
  const res = state.run?.done ? state.run.res : null, o = res?.outcome;
  $('ask-svc').value = o?.root_cause?.service || res?.alert.service || state.alerts[1]?.service || $('ask-svc').value;
  const refuted = new Set(o?.refuted.map((r) => r.change));
  const ids = res ? [o.root_cause?.change, ...res.steps.flatMap((s) => s.highlight?.nodes || []), o.baseline_pick?.change] : [];
  const chg = [...new Set(ids)].filter((id) => id && kindOf(id) === 'chg');
  $('ask-chg').replaceChildren(...(chg.length ? chg.map((id) => h('option', { value: id }, short(id)
    + (id === o.root_cause?.change ? ' · root cause' : refuted.has(id) ? ' · ruled out' : '')))
    : [h('option', { value: '' }, 'run an act first')]));
}

const whoKnows = (rows) => (rows.length ? h('ol', { class: 'people' }, rows.map((p) => h('li', {},
  h('div', { class: 'who' }, h('span', {}, h('b', {}, p.name), ' ', h('span', { class: 'muted' }, `${p.handle} · ${p.team}`)),
    h('span', { class: 'score' }, `score ${p.score}`)),
  h('div', { class: 'why' }, [p.on_owning_team ? 'on the owning team' : null, `authored ${plural(p.changes, 'change')}`,
    `paged for ${plural(p.incidents, 'incident')}`].filter(Boolean).join(' · ')))))
  : h('p', { class: 'muted' }, 'Nobody on record for this service.'));

const changeStory = (c) => [
  h('p', { class: 'lead' }, h('b', {}, short(c.change)), ` on ${short(c.service)}`,
    h('span', { class: 'muted' }, ` · ${c.kind}${c.at ? ` · ${ist(c.at)}` : ''}`)),
  h('p', {}, c.summary),
  h('p', {}, h('span', { class: 'k' }, 'By'), c.author ? `${c.author} (${c.team})` : 'unknown'),
  c.sources.length ? h('ul', { class: 'sources' }, c.sources.map((s) => h('li', {},
    h('span', { class: 'src' }, s.kind === 'Ticket' ? 'ticket' : s.channel || 'chat'), ' ',
    s.title ? [h('b', {}, s.title), ' '] : null, h('span', { class: 'reason' }, s.text))))
    : h('p', { class: 'muted' }, 'No ticket or chat message on record.'),
  h('p', {}, h('span', { class: 'k' }, 'Caused'), c.incidents.map(short).join(', ') || 'no incidents'),
];

async function ask(tool, args, render) {
  const out = $('ask-out');
  out.replaceChildren(h('p', { class: 'muted' }, 'Querying FalkorDB…'));
  try {
    const r = await api('POST', `${T()}/tools/${tool}`, args);
    learnNames({ tool, data: r.data });
    out.replaceChildren(h('div', { class: 'card brain' },
      h('div', { class: 'card-head' }, h('span', { class: 'role brain' }, 'brain'), h('code', { class: 'tool' }, tool)),
      render(r.data), cypherList(r.queries)));
    const eles = elementsFor(r.highlight);
    if (eles) paint(eles, eles);
  } catch (e) {
    out.replaceChildren(h('p', { class: 'error' }, e.message));
  }
}

// ---------- scenario ----------
function syncButtons() {
  const b = state.busy, run = state.run;
  $('btn-reset').disabled = b;
  for (const n of ACTS) $(`btn-act${n}`).disabled = b || !state.alerts[n];
  $('btn-resolve').disabled = b || !(run?.done && run.res.outcome.root_cause && !run.resolved);
  for (const el of document.querySelectorAll('.controls .step')) el.classList.toggle('primary', !b && el.id === state.next);
  if (OFFLINE) return;
  $('ask-who').disabled = b || !$('ask-svc').value;
  $('ask-why').disabled = b || !$('ask-chg').value;
}

async function busy(fn) {
  state.busy = true;
  syncButtons();
  try {
    await fn();
  } catch (e) {
    status(e.message, true);
  } finally {
    state.busy = false;
    syncButtons();
  }
}

async function loadTenant() {
  const alerts = await api('GET', `${T()}/alerts`);
  state.acts = {};
  state.alerts = {};
  for (const a of [...alerts].sort((x, y) => x.at - y.at)) (state.acts[a.act] ||= []).push(a);
  for (const [act, group] of Object.entries(state.acts)) {
    const a = state.alerts[act] = group.at(-1); // the act's last alert to fire is the one the agents respond to
    const btn = $(`btn-act${act}`);
    if (!btn) continue;
    btn.replaceChildren(btn.querySelector('b'), ` Act ${act}: ${group.length > 1
      ? `${COUNT[group.length] || group.length} alerts at once`
      : `${short(a.service)} is ${a.symptom === 'latency' ? 'slow' : a.symptom}`}`);
    btn.title = group.map((x) => x.name).join('\n');
  }
  const g = await api('GET', `${T()}/graph`);
  buildGraph(g);
  if (!OFFLINE) $('ask-svc').replaceChildren(...[...g.nodes].sort((a, b) => a.name.localeCompare(b.name))
    .map((n) => h('option', { value: n.id }, n.name)));
  fillAsk();
}

function clearRun() {
  state.run = null;
  $('trace').replaceChildren();
  $('trace-count').textContent = '';
  hudIdle();
  intro();
  resetGraphView();
  fillAsk();
}

async function doReset() {
  const r = await api('POST', `${T()}/reset`);
  state.best = {};
  names.clear();
  await loadTenant();
  clearRun();
  state.next = 'btn-act1';
  status(r.status === 'seeded' ? 'Seeded the synthetic company graph.' : 'Graph restored from the pristine copy (GRAPH.COPY).');
}

async function doAct(act) {
  const alert = state.alerts[act];
  status(`Agents are working on “${alert.name}”…`);
  const res = await api('POST', `${T()}/alerts/${encodeURIComponent(alert.id)}/respond`);
  clearRun();
  showTab(false);
  const cy = state.cy;
  state.run = { res, act, calls: 0, hyps: 0, done: false, resolved: false,
    touched: cy ? cy.collection() : null, cause: cy ? cy.collection() : null };
  cy?.getElementById(res.alert.service).addClass('alerting');
  const group = state.acts[act] || [];
  $('hud').replaceChildren(...(group.length > 1
    ? [h('span', { class: 'pill alert' }, 'ALERTS'), h('b', {}, `${group.length} alerts in `
      + `${plural(Math.round((group.at(-1).at - group[0].at) / 60), 'minute')}: ${group.map((a) => short(a.service)).join(', ')}`),
      h('span', { class: 'muted' }, `${ist(res.alert.at)} · ${res.incident_id}`)]
    : [h('span', { class: 'pill alert' }, 'ALERT'), h('b', {}, res.alert.alert),
      h('span', { class: 'muted' }, `${short(res.alert.service)} · ${ist(res.alert.at)} · ${res.incident_id}`)]));
  $('outcome').replaceChildren();
  renderCounter();
  status(`Act ${act}: replaying ${res.steps.length} agent steps (planner: ${res.planner}).`);
  state.skip = false;
  $('btn-skip').hidden = false;
  for (let i = 0; i < res.steps.length; i++) {
    reveal(i);
    if (!state.skip) await sleep(res.steps[i].tool === 'handoff' ? STEP_MS * 0.7 : STEP_MS);
  }
  $('btn-skip').hidden = true;
  state.run.done = true;
  const o = res.outcome;
  state.best[act] = { calls: o.investigator_calls, hyps: o.hypotheses_checked, checks: o.checks_to_culprit };
  renderOutcome();
  fillAsk();
  // Memory moment: draw new incident -> recalled incident -> its runbook (the chain the recall query walked).
  const memo = o.memory.solved_by_memory ? elementsFor({ nodes: [], edges: o.memory.recalled.flatMap((r) =>
    [[res.incident_id, r.incident, 'RECALLS'], [r.incident, r.runbook, 'FIXED_WITH']]) }) : null;
  if (memo) state.run.touched = state.run.touched.union(memo);
  // Alert storm: the whole run spans most of the graph, so end on the alerting services, shared upstream and cause.
  paint(memo, o.storm && state.cy ? state.run.cause.union(state.cy.$('.storm, .shared')) : null);
  state.next = o.root_cause ? 'btn-resolve' : 'btn-reset';
  status(o.root_cause ? `Act ${act} done: ${short(o.root_cause.change)} on ${short(o.root_cause.service)} in `
    + `${o.investigator_calls} investigator calls. Confirm it to save the fix to memory.` : `Act ${act} done: no root cause.`);
}

async function doResolve() {
  const run = state.run, change = run.res.outcome.root_cause.change;
  const r = await api('POST', `${T()}/incidents/${encodeURIComponent(run.res.incident_id)}/resolve`, { change_id: change });
  run.resolved = true;
  if (r.data) names.set(r.data.runbook, 'runbook');
  renderLearned(r);
  const eles = elementsFor(r.highlight);
  if (eles) {
    run.touched = run.touched.union(eles);
    paint(eles);
  }
  state.next = state.alerts[run.act + 1] ? `btn-act${run.act + 1}` : 'btn-reset';
  status(r.summary);
}

async function init() {
  $('btn-reset').onclick = () => busy(doReset);
  for (const n of ACTS) $(`btn-act${n}`).onclick = () => busy(() => doAct(n));
  $('btn-resolve').onclick = () => busy(doResolve);
  $('btn-skip').onclick = () => { state.skip = true; };
  $('trace').addEventListener('click', onTraceClick);
  $('trace').addEventListener('keydown', (e) => { if (e.key === 'Enter') onTraceClick(e); });
  $('tab-trace').onclick = () => showTab(false);
  $('tab-ask').onclick = () => showTab(true);
  if (OFFLINE) {
    $('ask').replaceChildren(h('p', { class: 'card note' }, 'Ask the brain runs live Cypher against FalkorDB, so it needs '
      + 'the live API: start the server and open this page without ?offline=1.'));
  } else {
    $('ask-who').onclick = () => busy(() => ask('who_knows', { service: $('ask-svc').value }, whoKnows));
    $('ask-why').onclick = () => busy(() => ask('change_story', { change_id: $('ask-chg').value }, changeStory));
  }
  intro();
  syncButtons();
  try {
    const hl = await api('GET', '/api/health');
    const tenant = params.get('tenant');
    state.tenant = tenant && /^[a-z0-9_]{1,40}$/.test(tenant) ? tenant : hl.default_tenant;
    $('tenant').textContent = `tenant: ${state.tenant}${OFFLINE ? ' · offline replay' : ''}`;
    $('db').textContent = hl.falkordb ? 'FalkorDB' : 'FalkorDB down';
    $('db').title = hl.falkordb ? 'FalkorDB connected' : 'FalkorDB unreachable';
    $('db').classList.add(hl.falkordb ? 'ok' : 'bad');
    $('planner').textContent = /deterministic|mock/i.test(hl.planner)
      ? 'deterministic planner: the graph picks every branch' : `LLM planner: ${hl.planner}`;
  } catch (e) {
    if (!OFFLINE) {  // no backend (e.g. a static host): replay the recorded fixtures instead
      params.set('offline', '1');
      location.search = params.toString();
      return;
    }
    status(`Could not load the recorded fixtures (${e.message}).`, true);
    return;
  }
  await busy(async () => {
    try {
      await loadTenant();
      status('Ready. Reset the demo, then run act 1.');
    } catch (e) {
      status(`${e.message}. Press “Reset demo” to seed tenant ${state.tenant}.`, true);
    }
  });
}

init();
