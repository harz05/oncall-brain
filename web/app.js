// On-call Brain UI: replays an agent run (RunResult from the API) as a step-by-step trace while lighting up
// each step's evidence on the service graph. No build step. Every piece of data reaches the DOM as text
// (see h()), never as HTML.

const params = new URLSearchParams(location.search);
const OFFLINE = params.has('offline'); // ?offline=1 replays web/fixtures (generated from the real code)
const STEP_MS = Number(params.get('step_ms')) || 750;
const FONT = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
const C = {
  bg: '#0b1020', svc: '#162033', svcBorder: '#3a4a64', lit: '#1d3b61', text: '#dbe4f0', t1: '#7dd3fc',
  edge: '#4b5b75', hot: '#fde047', cause: '#fb7a3c', chg: '#f5b041', person: '#2dd4bf', team: '#60a5fa',
  inc: '#b48cff', rb: '#34d399', refuted: '#6b7689', alert: '#f87171',
};
// Satellite (non-service) node kinds, with the direction (degrees, y down) we prefer to place them from
// their anchor. Anything else in a highlight (ticket:, msg:, alert:) stays off the graph.
const SAT_ANGLE = { chg: 90, person: -60, team: -90, inc: -140, rb: 180 };

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const kindOf = (id) => id.split(':', 1)[0];
const short = (id) => (id ? id.slice(id.indexOf(':') + 1) : '');
const names = new Map(); // id -> friendlier graph label learned from step data (people, teams)
const state = { tenant: '', alerts: {}, cy: null, run: null, best: {}, busy: false, next: 'btn-reset', skip: false };

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
const ist = (at) => new Date(at * 1000).toLocaleString('en-GB', {
  timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) + ' IST';

function status(text, isError = false) {
  const el = $('status');
  el.textContent = text;
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
    [/checkout-latency\/respond$/, 'act1'], [/refunds-latency\/respond$/, 'act2']];
  const hit = routes.find(([re]) => re.test(p));
  if (!hit) throw new Error(`no offline fixture for ${p}`);
  await sleep(300);
  return (await fetch(`/web/fixtures/${hit[1]}.json`)).json();
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
  { selector: 'node.alerting', style: { 'border-color': C.alert, 'border-width': 3 } },
  { selector: 'node.refuted', style: { 'background-color': C.refuted, color: '#8a94a6' } },
  { selector: 'node.hot', style: { 'border-color': C.hot, 'border-width': 3, 'underlay-color': C.hot,
    'underlay-opacity': 0.25, 'underlay-padding': 7 } },
  { selector: 'edge.hot', style: { 'line-color': C.hot, 'target-arrow-color': C.hot, width: 3.5, opacity: 1 } },
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
function freeSpot(base, pref) {
  const boxes = state.cy.nodes().map((n) => n.boundingBox({ includeLabels: true }));
  const W = 92, UP = 16, DOWN = 32; // satellite icon plus its label underneath
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
function elementsFor(hl) {
  const cy = state.cy;
  if (!cy || !hl) return null;
  const has = (id) => cy.getElementById(id).nonempty();
  const home = state.run?.res.alert.service;
  let eles = cy.collection();
  for (const [s, t, rel] of hl.edges || []) {
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

// Fade everything except what this run touched (plus one dependency hop of context); brighten `hot`.
function paint(hot, focus) {
  const cy = state.cy, run = state.run;
  if (!cy || !run) return;
  cy.batch(() => {
    cy.elements().removeClass('hot ctx touched cause').addClass('dim');
    const ctx = run.touched.nodes('.svc').connectedEdges('.dep');
    ctx.union(ctx.connectedNodes()).removeClass('dim').addClass('ctx');
    run.touched.removeClass('dim ctx').addClass('touched');
    run.cause.addClass('cause');
    hot?.addClass('hot');
  });
  const target = focus && focus.nonempty() ? focus : run.touched;
  if (target.nonempty()) {
    cy.stop(true);
    cy.animate({ fit: { eles: target, padding: 36 }, duration: 450, easing: 'ease-in-out-cubic' });
  }
}

function resetGraphView() {
  const cy = state.cy;
  if (!cy) return;
  cy.remove('.sat');
  cy.elements().removeClass('dim ctx touched hot cause refuted alerting');
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
  const ms = step.queries.reduce((a, q) => a + q.ms, 0);
  const rows = step.queries.reduce((a, q) => a + q.rows.length, 0);
  return h('li', { class: `card ${step.role}${verdict ? ` v-${verdict}` : ''}`, 'data-i': i, tabindex: 0 },
    h('div', { class: 'card-head' },
      h('span', { class: `role ${step.role}` }, step.role),
      h('code', { class: 'tool' }, step.tool),
      h('span', { class: 'seq' }, `#${step.seq}`)),
    body,
    h('p', { class: 'why' }, h('span', { class: 'why-label' }, 'why '), step.reason),
    h('details', { class: 'cypher-list' },
      h('summary', {}, `Cypher: ${step.queries.length} queries, ${rows} rows, ${ms.toFixed(1)} ms`),
      step.queries.map(queryBlock)));
}

// Recall returns every past incident touching the path; only strong matches (score >= 3, the planner's bar) are
// worth drawing, the rest would bury the one that matters.
function strongRecalls(step) {
  const strong = (step.data || []).filter((r) => r.score >= 3);
  const keep = new Set(strong.flatMap((r) => [r.incident, r.cause_service]));
  return { nodes: step.highlight.nodes.filter((id) => keep.has(id)),
    edges: step.highlight.edges.filter(([, t]) => keep.has(t)) };
}

function reveal(i) {
  const run = state.run, step = run.res.steps[i];
  learnNames(step);
  const li = stepCard(step, i);
  $('trace').querySelector('.current')?.classList.remove('current');
  li.classList.add('current');
  $('trace').append(li);
  li.scrollIntoView({ block: 'nearest', behavior: state.skip ? 'auto' : 'smooth' });
  $('trace-count').textContent = `${i + 1} / ${run.res.steps.length} steps`;
  if (step.role === 'investigator' && step.tool !== 'handoff') run.calls++;
  if (step.tool === 'check_hypothesis') run.hyps++;
  renderCounter();
  const eles = elementsFor(step.tool === 'recall_similar' ? strongRecalls(step) : step.highlight);
  if (!eles) return;
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
  const run = state.run;
  const prev = run.act === 2 && state.best[1];
  const num = (label, now, before) => h('div', { class: 'num' },
    h('span', { class: 'big' }, before != null ? [h('span', { class: 'before' }, before), h('span', { class: 'arrow' }, '→'), now] : now),
    h('span', { class: 'lbl' }, label));
  const el = h('div', { class: 'card counter', id: 'counter' },
    h('h3', {}, run.act === 2 && prev ? 'Act 2 vs act 1' : `Act ${run.act}`),
    h('div', { class: 'nums' },
      num('investigator calls', run.calls, run.done && prev ? prev.calls : null),
      num('hypotheses checked', run.hyps, run.done && prev ? prev.hyps : null)),
    run.done && run.res.outcome.memory.solved_by_memory ? h('span', { class: 'pill memory' }, 'solved by memory') : null);
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
  const res = state.run.res, o = res.outcome, home = res.alert.service;
  const rc = o.root_cause, bp = o.baseline_pick, mem = o.memory;
  const cites = res.steps.find((s) => s.tool === 'post_update')?.data?.cites || [];
  const paged = [...new Map(o.paged.map((p) => [p.person, p])).values()];
  const recalled = mem.recalled[0];

  const cause = h('div', { class: 'card cause' },
    h('h3', {}, 'Root cause'),
    rc ? [h('p', { class: 'lead' }, h('b', {}, short(rc.change)), ` on ${short(rc.service)}`), pathChips(rc.live_path)]
      : h('p', {}, 'No suspect was supported by the graph.'),
    bp ? h('p', { class: `baseline ${o.baseline_correct ? 'ok' : 'bad'}` },
      'Flat change log would blame: ', h('b', {}, short(bp.change)), ' ',
      h('span', { class: 'pill' }, o.baseline_correct ? 'same answer' : 'wrong'),
      h('span', { class: 'sub' }, bp.summary)) : null,
    rc ? [h('p', {}, rc.summary), h('p', { class: 'muted' }, rc.reason)] : null);

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
    h('p', {}, h('span', { class: 'k' }, 'Paged '), paged.map((p, i) => [i ? ', ' : '', h('b', {}, p.name),
      ` ${p.handle} (${p.team_name})`])),
    h('p', {}, h('span', { class: 'k' }, 'Impact '), o.blast_radius.map(short).join(', ') || 'none'),
    h('p', {}, h('span', { class: 'k' }, 'Also at risk '),
      o.at_risk.filter((s) => s !== home && !o.blast_radius.includes(s)).map(short).join(', ') || 'none'));

  const update = h('div', { class: 'card update' },
    h('h3', {}, 'Status update posted to #incidents'),
    h('pre', {}, o.update_text || '(none)'),
    cites.length ? h('p', {}, h('span', { class: 'k' }, 'Sources '), cites.map((c) => h('span', { class: 'src' }, c))) : null);

  $('outcome').replaceChildren(h('div', { id: 'counter' }), cause, ruled, memory, update);
  renderCounter();
}

function renderLearned(r) {
  const d = r.data;
  $('learned').replaceChildren(h('div', { class: 'learned' },
    h('p', {}, h('span', { class: 'pill rb' }, 'saved to memory'), ' ', d ? ['runbook ', h('b', {}, `“${d.title}”`),
      ` (${d.successes} success${d.successes === 1 ? '' : 'es'})`] : r.summary),
    d ? h('ol', {}, d.steps.map((s) => h('li', {}, s))) : null));
}

// ---------- scenario ----------
function syncButtons() {
  const b = state.busy, run = state.run;
  $('btn-reset').disabled = b;
  $('btn-act1').disabled = b || !state.alerts[1];
  $('btn-act2').disabled = b || !state.alerts[2];
  $('btn-resolve').disabled = b || !(run?.done && run.res.outcome.root_cause && !run.resolved);
  for (const id of ['btn-reset', 'btn-act1', 'btn-resolve', 'btn-act2']) $(id).classList.toggle('primary', !b && id === state.next);
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
  state.alerts = {};
  for (const a of alerts) {
    state.alerts[a.act] = a;
    const btn = $(`btn-act${a.act}`);
    if (!btn) continue;
    btn.replaceChildren(btn.querySelector('b'), ` Act ${a.act}: ${short(a.service)} is ${a.symptom === 'latency' ? 'slow' : a.symptom}`);
    btn.title = a.name;
  }
  buildGraph(await api('GET', `${T()}/graph`));
}

function clearRun() {
  state.run = null;
  $('trace').replaceChildren();
  $('trace-count').textContent = '';
  hudIdle();
  intro();
  resetGraphView();
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
  const cy = state.cy;
  state.run = { res, act, calls: 0, hyps: 0, done: false, resolved: false,
    touched: cy ? cy.collection() : null, cause: cy ? cy.collection() : null };
  cy?.getElementById(res.alert.service).addClass('alerting');
  $('hud').replaceChildren(h('span', { class: 'pill alert' }, 'ALERT'), h('b', {}, res.alert.alert),
    h('span', { class: 'muted' }, `${short(res.alert.service)} · ${ist(res.alert.at)} · ${res.incident_id}`));
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
  state.best[act] = { calls: o.investigator_calls, hyps: o.hypotheses_checked };
  renderOutcome();
  // Memory moment: draw new incident -> recalled incident -> its runbook (the chain the recall query walked).
  const memo = o.memory.solved_by_memory ? elementsFor({ nodes: [], edges: o.memory.recalled.flatMap((r) =>
    [[res.incident_id, r.incident, 'RECALLS'], [r.incident, r.runbook, 'FIXED_WITH']]) }) : null;
  if (memo) state.run.touched = state.run.touched.union(memo);
  paint(memo);
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
  state.next = run.act === 1 ? 'btn-act2' : 'btn-reset';
  status(r.summary);
}

async function init() {
  $('btn-reset').onclick = () => busy(doReset);
  $('btn-act1').onclick = () => busy(() => doAct(1));
  $('btn-act2').onclick = () => busy(() => doAct(2));
  $('btn-resolve').onclick = () => busy(doResolve);
  $('btn-skip').onclick = () => { state.skip = true; };
  $('trace').addEventListener('click', onTraceClick);
  $('trace').addEventListener('keydown', (e) => { if (e.key === 'Enter') onTraceClick(e); });
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
    status(`API unreachable (${e.message}). Add ?offline=1 to replay recorded fixtures.`, true);
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
