// The service graph (Cytoscape): draws the dependency graph from FalkorDB and lights up each agent step's evidence.
// A "run" here is { home, incident, touched, cause }: the alerting service, the incident id, and the elements the
// run has lit so far (touched) and its supported cause path (cause). The graph shows one of three scopes: what an
// incident touched (laid out again top to bottom around the evidence path), what a live run has touched so far plus
// the alerting service's neighbours (laid out the same way, growing in place), or the whole company.

export const kindOf = (id) => id.split(':', 1)[0];
export const short = (id) => (id ? id.slice(id.indexOf(':') + 1) : '');
export const names = new Map(); // id -> friendlier label learned from step data (people, teams, runbooks, past incidents)

// Colours and the font come from the CSS custom properties in style.css (one source); read when a graph is built.
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const tokens = () => ({ paper: css('--paper'), paper2: css('--paper-2'), rule: css('--rule'), muted: css('--muted'),
  ink: css('--ink'), signal: css('--signal'), onInk: css('--on-ink'), font: css('--font-body') });
// Satellite (non-service) node kinds, with the direction (degrees, y down) we prefer to place them from their
// anchor. Anything else in a highlight (ticket:, msg:, alert:, doc:) stays off the graph.
const SAT_ANGLE = { chg: 0, person: -40, team: -100, inc: 180, rb: 160 };
// People-to-team-to-service relations (and the derived "knows it best"): drawn dotted, under "owns, on call" in the legend.
const REL = 'edge.owns, edge.on_call, edge.warned, edge.knows, edge.member_of';
// The whole company is wide and shallow, so it runs callers-left, dependencies-right. A scoped incident or answer runs
// top to bottom on its services only (satellites are placed around them afterwards, so they never widen a rank).
const LAYOUT = { name: 'dagre', rankDir: 'LR', nodeSep: 12, rankSep: 72, padding: 30 };
const SCOPED = { name: 'dagre', rankDir: 'TB', nodeSep: 24, rankSep: 60, padding: 30 };
const PHONE_SCOPED = { ...SCOPED, nodeSep: 16, rankSep: 52, padding: 20 };
const phone = () => matchMedia('(max-width: 899px)').matches;
const coarse = () => matchMedia('(pointer: coarse)').matches;
const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
// Labels are 15px: at this zoom they render at 13px, the rulebook's smallest type. The camera never frames below it if
// a smaller set can be framed instead (see camera()).
const READ = 0.87;

// Squares for services, small squares and circles for everything else; no glows, no press overlay. Later rules win in
// Cytoscape, so the order is: base, context (dim), lit by the run, a clicked step (hot), then what is broken.
const style = (T) => {
  const t = still() ? 0 : 150;
  return [
    { selector: 'core', style: { 'active-bg-opacity': 0, 'selection-box-opacity': 0 } },
    // nothing on the graph takes a click or a touch (steps are chosen from the list): a press on a node acts like one on
    // the background, so on a touch screen a swipe that starts on a node scrolls the page too
    { selector: 'node, edge', style: { events: 'no' } },
    { selector: 'node', style: { label: 'data(label)', 'font-family': T.font, 'font-size': 15, color: T.ink,
      'text-valign': 'center', 'text-halign': 'center', 'transition-property': 'background-color, border-color',
      'transition-duration': t, 'overlay-opacity': 0 } },
    { selector: 'node.svc', style: { shape: 'rectangle', width: 'data(w)', height: 34, 'background-color': T.paper,
      'border-width': 1.5, 'border-color': T.ink } },
    { selector: 'node.t1', style: { 'border-width': 3, 'font-weight': 600 } },
    { selector: 'node.sat', style: { width: 18, height: 18, 'text-valign': 'bottom', 'text-margin-y': 4, 'text-wrap': 'wrap',
      'text-max-width': 130, 'text-background-color': T.paper, 'text-background-opacity': 1, 'text-background-padding': 2,
      'border-width': 0, 'border-color': T.ink } },
    { selector: 'node.chg', style: { shape: 'rectangle', width: 16, height: 16, 'background-color': T.ink } },
    { selector: 'node.person', style: { shape: 'ellipse', 'background-color': T.paper, 'border-width': 1.5 } },
    { selector: 'node.team', style: { shape: 'ellipse', width: 20, height: 20, 'background-color': T.ink } },
    { selector: 'node.inc', style: { shape: 'ellipse', 'background-color': T.paper2, 'border-width': 1.5, 'border-style': 'dashed' } },
    { selector: 'node.rb', style: { shape: 'rectangle', width: 26, height: 16, 'background-color': T.paper2, 'border-width': 1.5 } },
    { selector: 'edge', style: { width: 1.5, 'line-color': T.ink, 'target-arrow-color': T.ink, 'target-arrow-shape': 'triangle',
      'arrow-scale': 0.8, 'curve-style': 'bezier', 'transition-property': 'line-color, width', 'transition-duration': t,
      'overlay-opacity': 0 } },
    { selector: REL, style: { 'line-color': T.muted, 'target-arrow-color': T.muted, 'line-style': 'dotted' } },
    { selector: 'edge.recalls, edge.fixed_with', style: { width: 2.5, 'line-style': 'dashed', 'line-dash-pattern': [6, 3] } },
    { selector: 'edge.retired', style: { 'line-style': 'dashed', 'line-color': T.muted, 'target-arrow-color': T.muted } },
    // context: services and edges the run did not touch read as rule-coloured scenery (labels stay muted, never faded)
    { selector: 'node.svc.dim, node.svc.ctx', style: { 'border-color': T.rule, color: T.muted } },
    { selector: 'edge.dim, edge.ctx', style: { 'line-color': T.rule, 'target-arrow-color': T.rule } },
    { selector: 'edge.dim', style: { opacity: 0.55 } },
    { selector: 'node.sat.dim', style: { 'background-opacity': 0.35, 'border-opacity': 0.35, color: T.muted } },
    { selector: '.off', style: { display: 'none' } },
    { selector: 'node.svc.touched', style: { 'border-color': T.ink, color: T.ink } },
    { selector: 'edge.touched', style: { width: 2, 'line-color': T.ink, 'target-arrow-color': T.ink, opacity: 1 } },
    { selector: 'node.svc.shared', style: { 'background-color': T.paper2, 'border-color': T.ink, 'border-width': 3, color: T.ink } },
    { selector: 'node.choke', style: { 'border-width': 4.5 } },
    { selector: 'node.refuted', style: { 'background-color': T.paper, 'border-width': 1.5, 'border-color': T.muted, color: T.muted } },
    { selector: 'node.svc.hot', style: { 'background-color': T.ink, 'border-color': T.ink, color: T.onInk, 'font-weight': 600 } },
    { selector: 'node.sat.hot', style: { 'border-width': 3, 'border-color': T.ink, 'background-opacity': 1, 'border-opacity': 1, color: T.ink } },
    { selector: 'edge.hot', style: { width: 3.5, 'line-color': T.ink, 'target-arrow-color': T.ink, opacity: 1 } },
    // a lit dotted relation stays a thin dashed line (a thick dotted one reads as a zipper)
    { selector: REL.split(', ').map((s) => `${s}.hot`).join(', '), style: { width: 2, 'line-style': 'dashed', 'line-dash-pattern': [2, 3] } },
    { selector: 'node.alerting', style: { 'background-color': T.signal, 'border-color': T.signal, color: T.onInk } },
    { selector: 'node.svc.cause', style: { 'border-color': T.signal, 'border-width': 3.5 } },
    // the change that caused it: an ink square ringed in signal, so a filled red square only ever means "alerting"
    { selector: 'node.chg.cause', style: { 'background-color': T.ink, 'border-width': 3, 'border-color': T.signal,
      'background-opacity': 1, 'border-opacity': 1, color: T.ink } },
    { selector: 'edge.cause', style: { width: 4, 'line-color': T.signal, 'target-arrow-color': T.signal, 'line-style': 'solid', opacity: 1 } },
  ];
};

let cy = null;
let lastCands = []; // what the camera was asked to frame; re-applied when a hidden graph becomes visible or resizes
let lastCrop = false;
let framed = { all: true, zoom: 1 }; // what the camera framed last: everything shown, and at which zoom
let scoped = false; // false (whole company) | 'live' (what a live run touched so far) | true (an incident or an answer)
let liveShown = null; // the nodes a live scope showed after its last step (they keep their places as it grows)
let homePositions = null; // whole-graph layout positions, restored when the scope is widened again
let homeId = null; // the alerting service of the run on screen; satellites without an anchor sit next to it

export const ready = () => !!cy;
export const empty = () => (cy ? cy.collection() : null);
export const select = (sel) => (cy ? cy.$(sel) : null);
// Elements by id without building a selector string (ids come from the API and may hold any character).
export const byIds = (ids) => (cy ? ids.reduce((c, id) => c.union(cy.getElementById(id)), cy.collection()) : null);
export const isScoped = () => scoped;
// Shown = not scoped out (.off). Cytoscape's :visible lags behind class changes, so the scope is read from classes.
const shown = () => cy.elements().not('.off');
export const shownServices = () => (cy ? shown().nodes('.svc').length : 0);
export const labels = (eles) => (eles ? eles.nodes().not('.off').map((n) => n.data('label')) : []);
export const inView = () => framed.all;
export const readable = () => framed.zoom >= READ - 0.01;
const visible = () => cy && cy.container().offsetParent !== null && cy.container().clientWidth > 0;
const box = (n) => n.boundingBox({ includeLabels: true });

export function build(container, g) {
  cy?.destroy();
  cy = null;
  scoped = false;
  liveShown = null;
  lastCands = [];
  if (typeof cytoscape === 'undefined') {
    container.textContent = 'The graph library did not load. Everything else still works.';
    return;
  }
  const elements = [
    ...g.nodes.map((n) => ({ group: 'nodes', classes: n.tier === 1 ? 'svc t1' : 'svc',
      data: { id: n.id, label: n.name, w: n.name.length * 8.6 + 26 } })),
    ...g.edges.map((e) => ({ group: 'edges', classes: e.live ? 'dep' : 'dep retired',
      data: { id: `${e.source}>${e.target}>DEPENDS_ON`, source: e.source, target: e.target } })),
  ];
  // Callers on the left, dependencies on the right. Built-in breadthfirst (rotated) if dagre did not load.
  const layout = typeof cytoscapeDagre !== 'undefined' ? LAYOUT
    : { name: 'breadthfirst', directed: true, padding: 30, transform: (_, p) => ({ x: p.y * 1.6, y: p.x / 1.6 }) };
  // On a touch screen a drag scrolls the page, not the graph (the zoom buttons move the camera); pinch still zooms.
  cy = cytoscape({ container, elements, style: style(tokens()), layout, minZoom: 0.2, maxZoom: 1,
    boxSelectionEnabled: false, autoungrabify: true, userPanningEnabled: !coarse() });
  document.fonts?.ready.then(() => cy?.style(style(tokens())));  // re-measure labels once the vendored font has loaded
  homePositions = new Map(cy.nodes().map((n) => [n.id(), { ...n.position() }]));
  reroute('horizontal');
}

// ---------- placement ----------
const inside = (p, b) => p.x > b.x1 && p.x < b.x2 && p.y > b.y1 && p.y < b.y2;
// Does the segment a-b cross the box (Liang-Barsky clipping)? through(): the same, but a box holding either end does
// not count (the line starts inside it). hitsPath(): does a polyline cross it?
function segHits(a, b, bx) {
  const dx = b.x - a.x, dy = b.y - a.y;
  let t0 = 0, t1 = 1;
  for (const [p, q] of [[-dx, a.x - bx.x1], [dx, bx.x2 - a.x], [-dy, a.y - bx.y1], [dy, bx.y2 - a.y]]) {
    if (p === 0) { if (q < 0) return false; continue; }
    const t = q / p;
    if (p < 0) { if (t > t1) return false; t0 = Math.max(t0, t); } else { if (t < t0) return false; t1 = Math.min(t1, t); }
  }
  return t0 < t1;
}
const through = (a, b, bx) => !inside(a, bx) && !inside(b, bx) && segHits(a, b, bx);
const hitsPath = (pts, bx) => pts.slice(1).some((p, i) => segHits(pts[i], p, bx));
// The edges already drawn between placed nodes, as straight lines (a new node is kept off them).
const edgeLines = (skip) => shown().edges().filter((e) => !skip.contains(e.source()) && !skip.contains(e.target()))
  .map((e) => [{ ...e.source().position() }, { ...e.target().position() }]);
// A satellite's footprint: its icon (up) and its label underneath (down), wrapped at 130px.
const satSize = (label) => {
  const px = String(label || '').length * 8;
  return { w: Math.max(40, Math.min(130, px) + 8), up: 18, down: 18 + 19 * Math.max(1, Math.ceil(px / 130)) };
};

// Place a node next to its anchor, at the first spot (preferred angle first, then fanning out, nearest first) that
// overlaps no box in `boxes` (nodes and their labels), needs no line from the anchor through one, and sits on none of
// `lines` (edges already drawn); failing that, the free spot with the fewest such crossings. The spot taken and its
// line to the anchor are added to `boxes` and `lines`.
// ponytail: O(nodes + edges) per candidate, fine for the ~60 nodes we ever draw.
function freeSpot(base, pref, boxes, { w, up, down }, lines = []) {
  let spot = null, best = null, least = Infinity;
  for (const r of [70, 105, 140, 180, 230, 290]) {
    for (let k = 0; k < 12 && !spot; k++) {
      const a = ((pref + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 30) * Math.PI) / 180;
      const p = { x: base.x + r * Math.cos(a), y: base.y + r * Math.sin(a) };
      const cb = { x1: p.x - w / 2, x2: p.x + w / 2, y1: p.y - up, y2: p.y + down };
      if (!boxes.every((b) => cb.x2 < b.x1 || cb.x1 > b.x2 || cb.y2 < b.y1 || cb.y1 > b.y2)) continue;
      const bad = 2 * boxes.filter((b) => through(base, p, b)).length + lines.filter(([s, t]) => through(s, t, cb)).length;
      if (!bad) spot = p;
      else if (bad < least) [best, least] = [p, bad];
    }
    if (spot) break;
  }
  spot ||= best || { x: base.x, y: base.y + 70 };
  boxes.push({ x1: spot.x - w / 2, x2: spot.x + w / 2, y1: spot.y - up, y2: spot.y + down });
  lines.push([{ ...base }, spot]);
  return spot;
}

// The node a satellite sits next to: the one it was placed by, else a visible service it connects to, else home.
function anchorOf(n) {
  const a = cy.getElementById(n.data('anchor') || '');
  if (a.nonempty() && !a.hasClass('off')) return a;
  const svc = n.neighborhood('node.svc').not('.off');
  if (svc.nonempty()) return svc[0];
  const h = cy.getElementById(homeId || '');
  return h.nonempty() && !h.hasClass('off') ? h : null;
}

// Re-place satellites around their anchors' current positions (after a layout or a scope change).
function placeSats(sats) {
  const boxes = shown().nodes().not(sats).map(box), lines = edgeLines(sats);
  for (const n of sats) {
    const a = anchorOf(n);
    n.position(freeSpot(a ? a.position() : { x: 0, y: 0 }, SAT_ANGLE[kindOf(n.id())] ?? 0, boxes, satSize(n.data('label')), lines));
  }
}

// Line the evidence path up as one straight column (the spine), pushing the other services of each rank sideways in
// their order, so the path reads top to bottom and the camera can frame it narrow.
function straighten(spine, gap) {
  const col = spine.map((id) => cy.getElementById(id)[0]).filter((n) => n && !n.hasClass('off'));
  if (col.length < 2) return;
  const svcs = cy.nodes('.svc').not('.off').toArray(), x0 = col[0].position('x');
  for (const n of col) {
    const y = n.position('y');
    const row = svcs.filter((m) => Math.abs(m.position('y') - y) < 2).sort((a, b) => a.position('x') - b.position('x'));
    const i = row.indexOf(n);
    n.position('x', x0);
    let edge = x0 - n.outerWidth() / 2;
    for (let k = i - 1; k >= 0; k--) {
      const m = row[k], x = Math.min(m.position('x'), edge - gap - m.outerWidth() / 2);
      m.position('x', x);
      edge = x - m.outerWidth() / 2;
    }
    edge = x0 + n.outerWidth() / 2;
    for (let k = i + 1; k < row.length; k++) {
      const m = row[k], x = Math.max(m.position('x'), edge + gap + m.outerWidth() / 2);
      m.position('x', x);
      edge = x + m.outerWidth() / 2;
    }
  }
}

// A straight edge drawn through a node it does not join reads as a relation that does not exist. Such an edge is
// routed instead, by the route that crosses the least (a service counts more than a satellite): first curves bent to
// either side, a little then more, then a right-angled "taxi" route along the layout's direction (turning just after
// the source, halfway or just before the target, so it runs in a gap between ranks; last, because its stem leaves
// the source's centre and would double any evidence-path edge leaving there). dir: the layout's main axis.
const ROUTE_KEYS = 'curve-style taxi-direction taxi-turn control-point-distances control-point-weights';
const routes = (dir) => [...[40, -40, 80, -80, 120, -120, 170, -170].map((d) => ({ 'curve-style': 'unbundled-bezier', 'control-point-distances': d, 'control-point-weights': 0.5 })),
  ...[24, '50%', -24].map((turn) => ({ 'curve-style': 'taxi', 'taxi-direction': dir, 'taxi-turn': turn }))];
const quad = (a, c, b, u) => ({ x: (1 - u) ** 2 * a.x + 2 * u * (1 - u) * c.x + u * u * b.x, y: (1 - u) ** 2 * a.y + 2 * u * (1 - u) * c.y + u * u * b.y });
function reroute(dir = 'vertical') {
  cy.edges('.routed').removeClass('routed').removeStyle(ROUTE_KEYS);
  const boxes = shown().nodes().map((n) => [n, box(n), n.hasClass('svc') ? 3 : 1]);
  for (const e of shown().edges()) {
    if (e.parallelEdges().length > 1) continue; // already drawn as curves apart from each other
    const s = e.source(), t = e.target(), others = boxes.filter(([n]) => n !== s && n !== t), a = s.position(), b = t.position();
    // the edge as drawn now, as a polyline: straight, its taxi segments, or its curve in 16 pieces
    const along = () => {
      const kind = e.pstyle('curve-style').value, c = kind === 'unbundled-bezier' ? e.controlPoints()?.[0] : null;
      if (kind === 'taxi') return [a, ...(e.segmentPoints() || []), b];
      return c ? Array.from({ length: 17 }, (_, i) => quad(a, c, b, i / 16)) : [a, b];
    };
    const cost = () => { const pts = along(); return others.reduce((k, [, bx, wt]) => k + (hitsPath(pts, bx) ? wt : 0), 0); };
    let least = cost(), pick = null;
    for (const r of least ? routes(dir) : []) {
      e.style(r);
      const k = cost();
      if (k < least) [least, pick] = [k, r];
      if (!k) break;
    }
    e.removeStyle(ROUTE_KEYS);
    if (pick) e.style(pick).addClass('routed');
  }
}

// The scoped layout: services top to bottom with `spine` (the evidence path, alert first) as one straight column,
// satellites around them, then crossing edges bent.
function arrange(spine) {
  const vis = shown(), svcs = vis.nodes('.svc'), opts = phone() ? PHONE_SCOPED : SCOPED;
  if (typeof cytoscapeDagre !== 'undefined') {
    svcs.union(svcs.edgesWith(svcs)).layout({ ...opts, fit: false, animate: false }).run();
    straighten(spine, opts.nodeSep);
  }
  placeSats(vis.nodes('.sat'));
  reroute();
}

function ensureNode(id, anchorId, run) {
  const kind = kindOf(id);
  if (cy.getElementById(id).nonempty() || !(kind in SAT_ANGLE)) return;
  const home = run?.home;
  const anchor = cy.getElementById(id === run?.incident ? home : anchorId || '');
  const base = anchor.nonempty() ? anchor.position() : (home && cy.getElementById(home).nonempty()
    ? cy.getElementById(home).position() : { x: 0, y: 0 });
  // a team nobody named yet is still a team, not a bare id
  const label = id === run?.incident ? 'this incident' : names.get(id) || (kind === 'team' ? `${short(id)[0].toUpperCase()}${short(id).slice(1)} team` : short(id));
  cy.add({ group: 'nodes', classes: `sat ${kind}`, data: { id, label, anchor: anchor.nonempty() ? anchor.id() : home },
    position: freeSpot(base, SAT_ANGLE[kind], shown().nodes().map(box), satSize(label), edgeLines(cy.collection())) });
}

// Turn a highlight {nodes, edges} into graph elements, adding satellites and non-DEPENDS_ON edges on the fly.
// Satellites without an edge sit next to the highlight's first service.
export function elementsFor(hl, run) {
  if (!cy || !hl) return null;
  if (run?.home) homeId = run.home;
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
export const unmark = (id, cls) => cy?.getElementById(id).removeClass(cls);

// Alert storm (correlate_alerts): alert ids are not graph nodes, so the alerting services get the alert style and
// the shared upstream a tint; the top convergence point gets the choke ring. Returns those services.
export function markStorm(d, run) {
  const alerting = byIds([run.home, ...d.alerts.map((a) => a.service)]).addClass('alerting storm');
  const shared = byIds(d.shared.map((s) => s.service)).addClass('shared');
  if (d.shared[0]) mark(d.shared[0].service, 'choke');
  return alerting.union(shared);
}

// ---------- the camera ----------
const zoomFor = (eles, pad) => {
  const bb = eles.boundingBox();
  return Math.min((cy.width() - 2 * pad) / Math.max(bb.w, 1), (cy.height() - 2 * pad) / Math.max(bb.h, 1));
};

// Pan along one axis, within lo..hi (the range that keeps the framed part in view), so as few nodes as possible are
// cut by the canvas edge: each cut node is either brought fully in or pushed fully out. spans: node extents at pan 0.
function settle(p, lo, hi, spans, size) {
  const cut = (q) => spans.reduce((k, [a, b]) => k + ((a + q < 0 && b + q > 0) || (a + q < size && b + q > size) ? 1 : 0), 0);
  let best = p, most = cut(p);
  for (const [a, b] of spans) {
    for (const q of [2 - a, size - 2 - b, -2 - b, size + 2 - a]) {
      if (q < lo || q > hi) continue;
      const k = cut(q);
      if (k < most || (k === most && Math.abs(q - p) < Math.abs(best - p))) [best, most] = [q, k];
    }
  }
  return best;
}

// Frames everything shown if its labels stay readable; otherwise the first of `cands` (most context first, the
// evidence last) that does, at the readable zoom, centred on everything shown as far as that keeps the candidate in
// view; if none does, the last one at whatever zoom fits it, so the evidence is never cropped (crop: true, for a live
// step, keeps the readable zoom instead and centres the step). Nothing given: it stays put.
function camera(cands, animate, crop = false) {
  const list = (cands || []).filter((c) => c?.nonempty());
  if (!cy || !list.length) return;
  lastCands = list;
  lastCrop = crop;
  if (!visible()) return;
  cy.resize();
  const pad = phone() ? 24 : 40, all = shown();
  const opts = [all, ...list.map((c) => c.not('.off'))].filter((c) => c.nonempty());
  if (!opts.length) return;
  const pick = opts.find((c) => zoomFor(c, pad) >= READ) || opts.at(-1);
  const fit = Math.min(Math.max(zoomFor(pick, pad), cy.minZoom()), cy.maxZoom());
  const z = pick === opts[0] || (fit < READ && !crop) ? fit : READ;
  const W = cy.width(), H = cy.height(), pb = pick.boundingBox(), ab = all.boundingBox();
  const boxes = all.nodes().map(box);
  const axis = (a1, a2, p1, p2, size, k1, k2) => {
    const lo = pad - z * p1, hi = size - pad - z * p2;
    if (lo > hi) return size / 2 - (z * (p1 + p2)) / 2; // wider than the canvas (a cropped live step): centre it
    const p = Math.min(Math.max(size / 2 - (z * (a1 + a2)) / 2, lo), hi);
    return settle(p, lo, hi, boxes.map((b) => [z * b[k1], z * b[k2]]), size);
  };
  const pan = { x: axis(ab.x1, ab.x2, pb.x1, pb.x2, W, 'x1', 'x2'), y: axis(ab.y1, ab.y2, pb.y1, pb.y2, H, 'y1', 'y2') };
  framed = { all: boxes.every((b) => z * b.x1 + pan.x >= 0 && z * b.x2 + pan.x <= W && z * b.y1 + pan.y >= 0 && z * b.y2 + pan.y <= H), zoom: z };
  cy.stop(true);
  if (animate && !still()) cy.animate({ zoom: z, pan, duration: 300, easing: 'ease-out-cubic' });
  else cy.viewport({ zoom: z, pan });
}

// The reader's own camera (the zoom buttons): keyboard and single-pointer alternatives to wheel, pinch and drag.
const allInView = () => {
  const e = cy.extent();
  return shown().nodes().every((n) => { const b = box(n); return b.x1 >= e.x1 && b.x2 <= e.x2 && b.y1 >= e.y1 && b.y2 <= e.y2; });
};
export function zoomBy(f) {
  if (!cy) return;
  cy.stop(true);
  const level = Math.min(Math.max(cy.zoom() * f, cy.minZoom()), cy.maxZoom());
  cy.zoom({ level, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  framed = { all: allInView(), zoom: level };
}
export function fitShown() {
  if (!cy) return;
  cy.stop(true);
  cy.fit(shown(), 30);
  framed = { all: true, zoom: cy.zoom() };
}

// One step of context around some elements (a candidate for the camera when a step is selected).
export const around = (eles) => eles.union(eles.nodes().closedNeighborhood());

// Dim everything except what the run touched (in the whole-company view, plus one dependency hop of context); brighten
// `hot`, then point the camera at the first readable candidate (see camera()). run may be null (company-brain answers).
export function paint(run, hot, cands = [], { crop = false } = {}) {
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
  camera(cands, true, crop);
}

const hide = (keep) => cy.batch(() => {
  cy.elements().addClass('off');
  keep.union(keep.nodes().edgesWith(keep.nodes())).removeClass('off');
});

// While a run streams: what it has touched plus one hop around the alerting service, laid out like the incident view.
// As it grows, what is on screen keeps its place: each new service lands next to a neighbour already shown (below it
// if it is a dependency), each new satellite next to its anchor. So nothing jumps between steps.
export function scopeLive(touched, home) {
  if (!cy || !touched?.nonempty()) return;
  const hop = cy.getElementById(home || '').connectedEdges('.dep');
  const before = scoped === 'live' ? liveShown : null;
  hide(touched.union(hop).union(hop.connectedNodes()));
  scoped = 'live';
  if (!before) arrange([home]);
  else {
    const now = shown().nodes(), fresh = now.not(before), boxes = now.not(fresh).map(box), lines = edgeLines(fresh);
    const todo = fresh.filter('.svc').toArray();
    const placedNear = (n) => n.neighborhood('node.svc').filter((m) => !m.hasClass('off') && m !== n && !todo.includes(m));
    while (todo.length) {
      const i = Math.max(0, todo.findIndex((n) => placedNear(n).nonempty()));
      const [n] = todo.splice(i, 1), m = placedNear(n)[0] || cy.getElementById(home);
      n.position(freeSpot(m.position(), m.edgesTo(n).nonempty() ? 90 : -90, boxes, { w: n.outerWidth() + 24, up: 30, down: 30 }, lines));
    }
    placeSats(fresh.filter('.sat'));
    reroute();
  }
  liveShown = shown().nodes();
}

// Show only `eles` (what an incident touched, or what an answer links to), laid out again top to bottom on its
// services so the subgraph is compact, with `spine` (the evidence path, alert first) as one straight column.
// Whole-graph positions are kept for scopeAll(). The caller points the camera (paint).
export function scopeTo(eles, spine = []) {
  if (!cy || !eles?.nonempty()) return;
  hide(eles);
  scoped = true;
  liveShown = null;
  arrange(spine);
}

// The whole company again: home positions, satellites re-placed next to their anchors, everything framed.
export function scopeAll() {
  if (!cy) return;
  cy.batch(() => {
    cy.elements().removeClass('off');
    for (const n of cy.nodes('.svc')) {
      const p = homePositions?.get(n.id());
      if (p) n.position(p);
    }
  });
  placeSats(cy.nodes('.sat'));
  reroute('horizontal');
  scoped = false;
  liveShown = null;
  camera([cy.elements()], true);
}

// Back to the plain graph: satellites gone, every highlight class cleared, whole graph shown.
export function clear() {
  if (!cy) return;
  cy.remove('.sat');
  cy.elements().removeClass('dim ctx touched hot cause refuted alerting storm shared choke off');
  for (const n of cy.nodes()) {
    const p = homePositions?.get(n.id());
    if (p) n.position(p);
  }
  reroute('horizontal');
  scoped = false;
  liveShown = null;
  lastCands = [];
  cy.stop(true);
  if (visible()) cy.fit(undefined, 30);
  framed = { all: true, zoom: cy.zoom() };
}

// The container was moved, resized or un-hidden: recompute its size and put the camera back where it should be.
export function refit() {
  if (!cy || !visible()) return;
  cy.resize();
  if (lastCands.length) camera(lastCands, false, lastCrop);
  else fitShown();
}

// Which legend entries the picture on screen uses (index.html .legend li[data-k]).
export function kinds() {
  if (!cy) return {};
  const v = shown(), has = (sel) => v.filter(sel).nonempty();
  const lit = has('.touched, .hot');
  return { svc: has('node.svc'), t1: has('node.t1'), alerting: has('node.alerting'), path: has('edge.cause'),
    hot: has('node.svc.hot'), ctx: lit && v.nodes('.svc').filter((n) => !n.hasClass('touched') && !n.hasClass('hot')).nonempty(),
    cause: has('node.chg.cause'), chg: v.filter((e) => e.hasClass('chg') && !e.hasClass('cause') && !e.hasClass('refuted')).nonempty(),
    refuted: has('node.refuted'), person: has('node.person'), team: has('node.team'), inc: has('node.inc'),
    rb: has('node.rb'), rel: has(REL), retired: has('edge.retired'), memory: has('edge.recalls, edge.fixed_with') };
}
