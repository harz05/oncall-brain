// The service graph (Cytoscape): draws the dependency graph from FalkorDB and lights up each agent step's evidence.
// A "run" here is { home, incident, touched, cause }: the alerting service, the incident id, and the elements the
// run has lit so far (touched) and its supported cause path (cause).

export const kindOf = (id) => id.split(':', 1)[0];
export const short = (id) => (id ? id.slice(id.indexOf(':') + 1) : '');
export const names = new Map(); // id -> friendlier label learned from step data (people, teams, runbooks)

const FONT = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
const C = {
  bg: '#0b1020', svc: '#162033', svcBorder: '#3a4a64', lit: '#1d3b61', text: '#dbe4f0', t1: '#7dd3fc',
  edge: '#4b5b75', hot: '#fde047', cause: '#fb7a3c', chg: '#f5b041', person: '#2dd4bf', team: '#60a5fa',
  inc: '#b48cff', rb: '#34d399', refuted: '#6b7689', alert: '#f87171', shared: '#e879f9', sharedBg: '#3f1a47',
};
// Satellite (non-service) node kinds, with the direction (degrees, y down) we prefer to place them from their
// anchor. Anything else in a highlight (ticket:, msg:, alert:, doc:) stays off the graph.
const SAT_ANGLE = { chg: 90, person: -60, team: -90, inc: -140, rb: 180 };

const STYLE = [
  { selector: 'node', style: { label: 'data(label)', 'font-family': FONT, 'font-size': 16, color: C.text,
    'text-valign': 'center', 'text-halign': 'center', 'transition-property': 'opacity, background-color, border-color',
    'transition-duration': 300 } },
  { selector: 'node.svc', style: { shape: 'round-rectangle', width: 'data(w)', height: 36, 'background-color': C.svc,
    'border-width': 1.5, 'border-color': C.svcBorder } },
  { selector: 'node.t1', style: { 'border-width': 2.5, 'border-color': C.t1, 'font-weight': 600 } },
  { selector: 'node.sat', style: { width: 22, height: 22, 'font-size': 14, 'text-valign': 'bottom', 'text-margin-y': 4,
    'text-background-color': C.bg, 'text-background-opacity': 0.75, 'text-background-padding': 2, 'border-width': 0 } },
  { selector: 'node.chg', style: { shape: 'diamond', width: 30, height: 30, 'background-color': C.chg } },
  { selector: 'node.person', style: { shape: 'ellipse', 'background-color': C.person } },
  { selector: 'node.team', style: { shape: 'hexagon', width: 27, 'background-color': C.team } },
  { selector: 'node.inc', style: { shape: 'octagon', 'background-color': C.inc } },
  { selector: 'node.rb', style: { shape: 'round-rectangle', width: 32, height: 20, 'background-color': C.rb } },
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
    color: C.shared, 'font-size': 15, 'font-weight': 600, 'text-wrap': 'wrap' } }, // after .hot: only its label shows
  { selector: 'edge.note-link', style: { width: 1.5, 'line-color': C.shared, 'line-style': 'dotted',
    'target-arrow-shape': 'none' } },
  { selector: 'edge.recalls.hot', style: { 'line-color': C.inc, 'target-arrow-color': C.inc, 'underlay-color': C.inc,
    'underlay-opacity': 0.3, 'underlay-padding': 5 } },
  { selector: 'node.cause', style: { 'border-color': C.cause, 'border-width': 3.5, 'underlay-color': C.cause,
    'underlay-opacity': 0.35, 'underlay-padding': 9 } },
  { selector: 'edge.cause', style: { 'line-color': C.cause, 'target-arrow-color': C.cause, width: 5,
    'underlay-color': C.cause, 'underlay-opacity': 0.3, 'underlay-padding': 6, opacity: 1 } },
];

let cy = null;
let lastFocus = null; // where the camera should be; re-applied when a hidden graph becomes visible

export const ready = () => !!cy;
export const empty = () => (cy ? cy.collection() : null);
export const select = (sel) => (cy ? cy.$(sel) : null);
const visible = () => cy && cy.container().offsetParent !== null && cy.container().clientWidth > 0;

// Returns a one-line caption, or an error text if the graph library did not load.
export function build(container, g) {
  cy?.destroy();
  cy = null;
  if (typeof cytoscape === 'undefined') {
    container.textContent = 'Graph library did not load (is the CDN reachable?). Everything else still works.';
    return '';
  }
  const elements = [
    ...g.nodes.map((n) => ({ group: 'nodes', classes: n.tier === 1 ? 'svc t1' : 'svc',
      data: { id: n.id, label: n.name, w: n.name.length * 9.5 + 30 } })),
    ...g.edges.map((e) => ({ group: 'edges', classes: e.live ? 'dep' : 'dep retired',
      data: { id: `${e.source}>${e.target}>DEPENDS_ON`, source: e.source, target: e.target } })),
  ];
  // Callers on the left, dependencies on the right. Built-in breadthfirst (rotated) if dagre did not load.
  const layout = typeof cytoscapeDagre !== 'undefined'
    ? { name: 'dagre', rankDir: 'LR', nodeSep: 16, rankSep: 100, padding: 24 }
    : { name: 'breadthfirst', directed: true, padding: 30, transform: (_, p) => ({ x: p.y * 1.6, y: p.x / 1.6 }) };
  cy = cytoscape({ container, elements, style: STYLE, layout, minZoom: 0.25, maxZoom: 1.15,
    boxSelectionEnabled: false, autoungrabify: true });
  const retired = g.edges.filter((e) => !e.live).length;
  return `${g.nodes.length} services · ${g.edges.length} dependencies (${retired} retired) · callers left, `
    + 'dependencies right';
}

// Place a satellite next to its anchor, at the first spot (preferred angle first, then fanning out) that does not
// overlap a node or its label. ponytail: O(nodes) per candidate, fine for the ~60 nodes we ever draw.
function freeSpot(base, pref, W = 110) {
  const boxes = cy.nodes().map((n) => n.boundingBox({ includeLabels: true }));
  const UP = 18, DOWN = 38; // satellite icon plus its label underneath (W wide)
  for (const r of [70, 105, 140, 180, 230]) {
    for (let k = 0; k < 12; k++) {
      const a = ((pref + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 30) * Math.PI) / 180;
      const p = { x: base.x + r * Math.cos(a), y: base.y + r * Math.sin(a) };
      if (boxes.every((b) => p.x + W / 2 < b.x1 || p.x - W / 2 > b.x2 || p.y + DOWN < b.y1 || p.y - UP > b.y2)) return p;
    }
  }
  return { x: base.x, y: base.y + 70 };
}

function ensureNode(id, anchorId, run) {
  const kind = kindOf(id);
  if (cy.getElementById(id).nonempty() || !(kind in SAT_ANGLE)) return;
  const home = run?.home;
  const anchor = cy.getElementById(id === run?.incident ? home : anchorId);
  const base = anchor.nonempty() ? anchor.position() : (home && cy.getElementById(home).nonempty()
    ? cy.getElementById(home).position() : { x: 0, y: 0 });
  cy.add({ group: 'nodes', classes: `sat ${kind}`, data: { id, label: names.get(id) || short(id) },
    position: freeSpot(base, SAT_ANGLE[kind]) });
}

// Turn a highlight {nodes, edges} into graph elements, adding satellites and non-DEPENDS_ON edges on the fly.
// Satellites without an edge (e.g. who_knows people) sit next to the highlight's first service.
export function elementsFor(hl, run) {
  if (!cy || !hl) return null;
  const has = (id) => cy.getElementById(id).nonempty();
  const home = (hl.nodes || []).find((id) => kindOf(id) === 'svc' && has(id)) || run?.home;
  let eles = cy.collection();
  for (const [s, t, rel] of hl.edges || []) {
    if (![s, t].every((id) => has(id) || kindOf(id) in SAT_ANGLE)) continue; // e.g. CORRELATED_WITH an alert: id
    if (!has(s) && !has(t)) ensureNode(s, home, run);
    if (!has(s)) ensureNode(s, t, run);
    if (!has(t)) ensureNode(t, s, run);
    if (!has(s) || !has(t)) continue;
    const id = `${s}>${t}>${rel}`;
    eles = eles.union(has(id) ? cy.getElementById(id)
      : cy.add({ group: 'edges', classes: `rel ${rel.toLowerCase()}`, data: { id, source: s, target: t } }));
  }
  for (const id of hl.nodes || []) {
    ensureNode(id, home, run);
    eles = eles.union(cy.getElementById(id));
  }
  return eles.union(eles.connectedNodes());
}

export const mark = (id, cls) => cy?.getElementById(id).addClass(cls);

// Alert storm (correlate_alerts): alert ids are not graph nodes, so the alerting services get the alert style, the
// shared upstream a tint, and the top convergence point a note. Returns the note to light with the step.
export function markStorm(d, run) {
  cy.getElementById(run.home).addClass('alerting storm');
  for (const a of d.alerts) cy.getElementById(a.service).addClass('alerting storm');
  for (const s of d.shared) cy.getElementById(s.service).addClass('shared');
  const top = d.shared[0] && cy.getElementById(d.shared[0].service);
  if (!top?.nonempty()) return cy.collection();
  top.addClass('choke');
  // It is not where the cause is (that can be further upstream), only the nearest service every alert reaches.
  const n = new Set([run.home, ...d.alerts.map((a) => a.service)]).size;
  const note = cy.add({ group: 'nodes', classes: 'sat note', data: { id: 'note:choke', label: `shared by all ${n}\nalerting services` },
    position: freeSpot(top.position(), 90, 170) });
  return note.union(cy.add({ group: 'edges', classes: 'note-link',
    data: { id: 'note:choke>link', source: note.id(), target: top.id() } }));
}

// Fade everything except what the run touched (plus one dependency hop of context); brighten `hot`, then zoom to
// `focus` (default: all the run touched). run may be null (company-brain answers).
export function paint(run, hot, focus) {
  if (!cy) return;
  const touched = run?.touched || cy.collection();
  hot = hot || cy.collection();
  cy.batch(() => {
    cy.elements().removeClass('hot ctx touched cause').addClass('dim');
    const ctx = touched.union(hot).nodes('.svc').connectedEdges('.dep');
    ctx.union(ctx.connectedNodes()).removeClass('dim').addClass('ctx');
    touched.removeClass('dim ctx').addClass('touched');
    run?.cause?.addClass('cause');
    hot.removeClass('dim ctx').addClass('hot');
  });
  const target = focus ?? touched; // an empty focus (a handoff) keeps the camera where it is
  if (target?.nonempty()) {
    lastFocus = target;
    if (!visible()) return;
    cy.stop(true);
    cy.animate({ fit: { eles: target, padding: 36 }, duration: 450, easing: 'ease-in-out-cubic' });
  }
}

// Zoom target for a step: its elements plus one hop of context, unless that hop would shrink labels below ~13px
// (a hub like checkout touches half the graph); then just the step's own elements. 72 = paint()'s fit padding x2.
export function near(eles) {
  if (!visible()) return eles;
  const wide = eles.union(eles.nodes().closedNeighborhood()), bb = wide.boundingBox();
  return Math.min((cy.width() - 72) / bb.w, (cy.height() - 72) / bb.h) >= 0.8 ? wide : eles;
}

// Back to the plain graph: satellites gone, every highlight class cleared.
export function clear(animate = true) {
  if (!cy) return;
  cy.remove('.sat');
  cy.elements().removeClass('dim ctx touched hot cause refuted alerting storm shared choke');
  lastFocus = null;
  cy.stop(true);
  if (visible()) animate ? cy.animate({ fit: { padding: 30 }, duration: 300 }) : cy.fit(undefined, 30);
}

// The container was moved or un-hidden: recompute its size and put the camera back where it should be.
export function refit() {
  if (!visible()) return;
  cy.resize();
  cy.fit(lastFocus?.nonempty() ? lastFocus : undefined, lastFocus ? 36 : 30);
}
