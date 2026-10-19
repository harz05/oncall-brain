// FalkorDB user-defined functions (GRAPH.UDF LOAD oncall <this file>), called from Cypher as oncall.<name>(...).
// Read-only by design: FalkorDB runs UDFs in a sandboxed JavaScript engine that cannot write the graph.

// Is a temporal edge live at `at`? The same test every Cypher query in queries/*.cypher spells out.
function live(e, at) {
  var a = e.attributes;
  return a.valid_from <= at && (a.valid_to === undefined || a.valid_to === null || a.valid_to > at);
}

// Every service that transitively depends on `target` over DEPENDS_ON edges live at `at`, within `maxHops`, as
// [{service, hops, path}] in breadth-first order, path = [caller id, ..., target id] through the first parent met.
// Dead edges are pruned while walking, so a retired dependency never puts its subtree in the frontier. Same rows as
// the Cypher breadth-first in triage.cypher: blast_radius (tests/integration/test_query_equivalence.py).
function live_upstream(target, at, maxHops) {
  var out = [], seen = {}, level = [[target]];
  for (var hop = 1; hop <= maxHops && level.length; hop++) {
    var next = [];
    for (var i = 0; i < level.length; i++) {
      var path = level[i];
      var callers = path[0].getNeighbors({direction: 'incoming', types: ['DEPENDS_ON'], returnType: 'edges'})
        .filter(function (e) { return live(e, at); })
        .map(function (e) { return e.source; })
        .sort(function (p, q) { return q.id - p.id; });  // ties: the order the Cypher form meets them
      for (var j = 0; j < callers.length; j++) {
        var n = callers[j];
        if (seen[n.id]) continue;
        seen[n.id] = true;
        var p = [n].concat(path);
        next.push(p);
        out.push({service: n.attributes.id, hops: hop,
                  path: p.map(function (m) { return m.attributes.id; })});
      }
    }
    level = next;
  }
  return out;
}

// Every service `origin` reaches over DEPENDS_ON edges live at `at`, within `maxHops`, as {service id: fewest hops}
// (origin itself at 0). One breadth-first walk per origin, along the edge direction, dropping a dead edge as it meets
// it; path_suspects and recall_similar look each suspect's service up in it (reach[s.id], null: not reachable live),
// instead of walking once per (origin, service) pair. With `targets` (service ids), only those are returned and the
// walk stops once it has found them all, so the map a query carries stays small. Same rows as the plain forms in
// queries/reference.cypher (tests/integration/test_query_equivalence.py).
function live_reach(origin, at, maxHops, targets) {
  var out = {}, frontier = [origin], seen = {}, want = null, left = 0;
  if (targets) {
    want = {};
    for (var t = 0; t < targets.length; t++) {
      if (!want[targets[t]]) left++;
      want[targets[t]] = true;
    }
  }
  var keep = function (id, hops) {
    if (!want) { out[id] = hops; return; }
    if (want[id] && out[id] === undefined) { out[id] = hops; left--; }
  };
  seen[origin.id] = true;
  keep(origin.attributes.id, 0);
  for (var hop = 1; hop <= maxHops && frontier.length && !(want && left === 0); hop++) {
    var next = [];
    for (var i = 0; i < frontier.length; i++) {
      var edges = frontier[i].getNeighbors({direction: 'outgoing', types: ['DEPENDS_ON'], returnType: 'edges'});
      for (var j = 0; j < edges.length; j++) {
        if (!live(edges[j], at)) continue;
        var n = edges[j].target;
        if (seen[n.id]) continue;
        seen[n.id] = true;
        keep(n.attributes.id, hop);
        next.push(n);
      }
    }
    frontier = next;
  }
  return out;
}

falkor.register('live_upstream', live_upstream);
falkor.register('live_reach', live_reach);
