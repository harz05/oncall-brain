// On-call Brain UI. Three views:
//   Incidents  an inbox; each incident shows the agents working live, then the update the comms agent posted (with
//              Confirm / Wrong cause), and "Show me why": the graph, every agent step and the Cypher behind it.
//   Ask        company questions answered from the graph, as a chat.
//   Connect    how to plug it in: MCP (Claude Code), the alert webhook, Slack, your own data.
// No build step. Every piece of data reaches the DOM as text (see h()), never as HTML.

import * as G from './graph.js';

const { kindOf, short, names } = G;
const params = new URLSearchParams(location.search);
const OFFLINE = params.has('offline'); // ?offline=1 replays web/fixtures (recorded from the real code)
const STEP_MS = Number(params.get('step_ms')) || 750; // fastest pace at which steps appear (an LLM is slower anyway)
const ROLES = ['triage', 'investigator', 'comms'];
const ROLE_JOB = { triage: 'Finds who is hurt and pages on-call', investigator: 'Tests every recent change against the graph',
  comms: 'Writes the update, with sources' };
const SCENARIO_NOTE = {
  1: 'A bad config change hides among four other recent changes. Watch each decoy get ruled out.',
  2: 'The same kind of failure again. Confirm the first fix and memory solves this one in a few steps.',
  3: 'Three services alert within four minutes. One shared cause, or three?',
};
const EXAMPLES = ['Who owns kafka?', 'Why was legacy-billing retired?', 'Why was the payments gateway pool lowered?',
  'How do I roll back a bad deploy on cart?', 'What happened to auth?', 'Who knows payments-gw?'];

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const enc = encodeURIComponent;
const plural = (n, word) => `${n} ${n === 1 ? word : word === 'query' ? 'queries' : `${word}s`}`;
const ist = (at) => new Date(at * 1000).toLocaleString('en-GB', {
  timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) + ' IST';

// running: an agent run is streaming; graphOwner: whose picture the graph shows (a run, 'ask', or null)
const state = { tenant: '', health: null, caption: '', stats: '', alerts: [], runs: [], current: null,
  view: 'incidents', tab: 'answer', running: false, skip: false, chat: [], graphOwner: null };

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
const goto = (view, label) => h('a', { href: '#', class: 'link', onclick: (e) => { e.preventDefault(); showView(view); } }, label);

let toastTimer;
function toast(text, isError = false) {
  const el = $('toast');
  el.textContent = text;
  el.classList.toggle('error', isError);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 10000 : 5000);
}

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
// opened is loaded from the graph instead (GET /incidents/{id}): its update and steps, without the trace details.
function newRun(alert, alerts, act) {
  return { alert, alerts, act, home: alert.service, incident: null, steps: [], res: null, ablation: null,
    resolved: null, done: false, error: null, folded: alerts.length < 2, showAlt: false,
    touched: G.empty(), cause: G.empty() };
}

function statusOf(run, serverStatus) {
  if (run?.error) return ['error', 'Failed'];
  if (run && !run.done) return ['working', 'Investigating'];
  if (run?.resolved || serverStatus === 'resolved' || run?.status === 'resolved') return ['resolved', 'Resolved'];
  if (run?.res) return run.res.outcome.root_cause ? ['found', 'Cause found'] : ['human', 'Needs a human'];
  return ['open', 'Open'];
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
const scenarioTitle = (sc) => (sc.alerts.length > 1 ? `${sc.alerts.length} alerts at once`
  : `${short(sc.trigger.service)} is ${sc.trigger.symptom === 'latency' ? 'slow' : `showing ${sc.trigger.symptom}`}`);

function inboxItems() {
  const items = new Map();
  for (const a of state.alerts) {
    if (!a.incident) continue;
    if (!items.has(a.incident)) items.set(a.incident, { incident: a.incident, status: a.status, alerts: [] });
    items.get(a.incident).alerts.push(a);
  }
  const rows = [...items.values()];
  for (const run of state.runs) {
    const it = run.incident && items.get(run.incident);
    if (it) it.run = run;
    else if (run.folded) rows.push({ incident: run.incident, alerts: run.alerts, run });
    else for (const a of run.alerts) rows.push({ incident: null, alerts: [a], run }); // a storm before correlation
  }
  const latest = (it) => Math.max(...it.alerts.map((a) => a.at));
  return rows.sort((x, y) => latest(y) - latest(x));
}

// ---------- rendering: inbox, demo alerts, landing ----------
function renderInbox() {
  const rows = inboxItems();
  $('inbox-count').textContent = rows.length ? String(rows.length) : '';
  $('inbox').replaceChildren(...(rows.length ? rows.map((it) => {
    const [cls, label] = statusOf(it.run, it.status);
    const trigger = it.run?.alert || it.alerts.find((a) => `inc:${short(a.id)}` === it.incident) || it.alerts.at(-1);
    const many = it.alerts.length > 1;
    const selected = state.current && (state.current === it.run || (it.incident && state.current.incident === it.incident));
    return h('li', {},
      h('button', { class: `inbox-item${selected ? ' selected' : ''}`, onclick: () => (it.run ? openRun(it.run) : openStored(it.incident)) },
        h('span', { class: `dot ${cls}` }),
        h('span', { class: 'ii-main' },
          h('span', { class: 'ii-title' }, many ? `${it.alerts.length} alerts → 1 incident` : trigger.name),
          h('span', { class: 'ii-sub' }, many ? it.alerts.map((a) => short(a.service)).join(', ') : short(trigger.service),
            ` · ${ist(trigger.at)}`)),
        h('span', { class: `status-pill ${cls}` }, label)));
  }) : [h('li', { class: 'inbox-empty' }, h('p', {}, 'No incidents.'),
    h('p', { class: 'muted small' }, 'Fire a demo alert below, or send one in through the webhook (Connect).'))]));
}

function renderScenarios() {
  const list = scenarios(), next = list.find((s) => !fired(s));
  $('scenarios').replaceChildren(...list.map((sc) => {
    const done = fired(sc);
    return h('li', { class: `scenario${done ? ' done' : ''}${sc === next ? ' next' : ''}` },
      h('div', { class: 'sc-text' }, h('b', {}, scenarioTitle(sc)), h('span', { class: 'muted small' }, SCENARIO_NOTE[sc.act] || '')),
      h('button', { class: sc === next ? 'primary-btn' : 'ghost', disabled: done || state.running,
        onclick: () => fire(sc.act) }, done ? 'Fired' : 'Fire'));
  }));
}

function renderLanding() {
  const next = scenarios().find((s) => !fired(s));
  const how = (n, title, text) => h('li', {}, h('span', { class: 'how-n' }, n), h('div', {}, h('b', {}, title), h('p', {}, text)));
  $('landing').replaceChildren(h('div', { class: 'hero' },
    h('p', { class: 'eyebrow' }, 'Incident response on a knowledge graph · FalkorDB'),
    h('h2', {}, 'Your AI on-call teammate'),
    h('p', { class: 'lede' }, 'When an alert fires, three AI agents work it over your company’s knowledge graph: what '
      + 'depends on what, who owns it, what changed, and what fixed it last time. You get the likely cause, who to page '
      + 'and the fix, with sources. Confirm the fix and it remembers.'),
    h('ol', { class: 'how' },
      how('1', 'An alert fires', 'From your monitoring through a webhook, or from the demo alerts on the left.'),
      how('2', 'Agents investigate the graph', 'Triage finds who is hurt and pages on-call. The investigator tests every '
        + 'recent change against the dependency graph and rules out the decoys. Comms writes the update.'),
      how('3', 'You confirm, it learns', 'Your call becomes memory in the graph, so the next similar incident is solved '
        + 'in a few steps.')),
    next ? h('button', { class: 'cta', disabled: state.running || !state.alerts.length, onclick: () => fire(next.act) },
      `${next.act === 1 ? 'Fire the first alert' : 'Fire the next alert'}: ${scenarioTitle(next)}`)
      : h('p', { class: 'muted' }, 'All demo alerts have been handled. Pick one on the left, or reset the demo.'),
    h('p', { class: 'muted small' }, state.stats ? `Demo company: ${state.stats}, all synthetic. ` : '',
      goto('ask', 'Ask the company brain'), ' · ', goto('connect', 'Use it from Claude Code or your alerting'))));
}

// ---------- rendering: one incident ----------
function renderHead(cur) {
  const [cls, label] = statusOf(cur, cur.status);
  $('inc-status').className = `status-pill ${cls}`;
  $('inc-status').textContent = label;
  $('inc-title').textContent = cur.alerts.length > 1
    ? `${cur.alerts.length} alerts: ${cur.alerts.map((a) => short(a.service)).join(', ')}` : cur.alert.name;
  $('inc-sub').textContent = `${short(cur.home)} · ${ist(cur.alert.at)}${cur.incident ? ` · ${cur.incident}` : ''}`;
}

function plannerName() {
  const p = state.health?.planner || '';
  return /deterministic|mock/i.test(p) ? 'the rule planner' : p.split(' via ')[0];
}

function renderProgress(cur) {
  const steps = cur.steps || [];
  const handed = new Set(steps.filter((s) => s.tool === 'handoff').map((s) => s.role));
  const working = cur.done ? null : ROLES.find((r) => !handed.has(r));
  const checks = steps.filter((s) => s.tool === 'check_hypothesis' && s.data);
  const tiles = ROLES.map((role) => {
    const mine = steps.filter((s) => s.role === role && s.tool !== 'handoff');
    const st = handed.has(role) || (cur.done && mine.length) ? 'done' : role === working ? 'working' : 'waiting';
    let text = st === 'waiting' ? ROLE_JOB[role] : mine.at(-1)?.summary || 'Reading the incident board…';
    if (role === 'investigator' && checks.length) {
      const out = checks.filter((s) => s.data.verdict !== 'supports').length;
      text = `Tested ${plural(checks.length, 'suspect')}, ruled out ${out}. ${st === 'working' ? `Now: ${mine.at(-1)?.summary || ''}` : ''}`;
    }
    return h('div', { class: `tile ${st} ${role}` },
      h('div', { class: 'tile-head' }, h('span', { class: `role ${role}` }, role),
        h('span', { class: 'tile-state' }, st === 'done' ? '✓ done' : st === 'working' ? 'working…' : 'waiting')),
      h('p', {}, text));
  });
  const last = steps.at(-1);
  $('progress').replaceChildren(...[h('div', { class: 'tiles' }, tiles),
    !cur.done && !cur.stored ? h('p', { class: 'progress-line' },
      h('span', { class: 'spinner' }), last ? [h('b', {}, `${last.role}: `), last.reason] : 'Opening the incident…',
      h('span', { class: 'muted' }, ` · steps chosen by ${plannerName()}`),
      h('button', { class: 'ghost', onclick: () => { state.skip = true; } }, 'Skip animation')) : null,
    cur.error ? h('p', { class: 'error' }, cur.error) : null].filter(Boolean)); // replaceChildren(null) renders "null"
}

// The status update, rendered the way it lands in Slack: the comms agent's text, line by line ("Key: value").
function slackCard(cur) {
  const text = cur.resolved?.update_text || cur.res?.outcome.update_text || cur.update_text;
  const head = h('div', { class: 'slack-head' }, h('span', { class: 'logo sm' }),
    h('b', {}, 'On-call Brain'), h('span', { class: 'app' }, 'APP'), h('span', { class: 'muted' }, ist(cur.alert.at)));
  if (!text) {
    return h('div', { class: 'slack pending' }, h('div', { class: 'channel' }, '# incidents'), head,
      h('p', { class: 'muted' }, cur.done ? 'No update was posted.' : 'The comms agent posts here once the cause is clear…'),
      cur.done ? null : [h('div', { class: 'skel' }), h('div', { class: 'skel short' })]);
  }
  const [first, ...rest] = text.split('\n');
  const m = first.match(/^\[(.*)\]\s*status:\s*(.*)$/);
  const lines = rest.map((line) => {
    const k = line.match(/^([A-Z][\w ()]{1,30}):\s(.*)$/);
    if (!k) return h('p', {}, line);
    if (k[1] === 'Sources') return h('p', { class: 'sources' }, h('b', {}, 'Sources: '), k[2].split(', ').map((s) => h('span', { class: 'src' }, s)));
    return h('p', { class: /cause/i.test(k[1]) ? 'cause-line' : null }, h('b', {}, `${k[1]}: `), k[2]);
  });
  const slack = cur.resolved?.slack || cur.res?.slack;
  return h('div', { class: 'slack' }, h('div', { class: 'channel' }, '# incidents'), head,
    m ? h('p', { class: 'slack-title' }, h('span', { class: 'siren' }, '●'), h('b', {}, m[1]), ' — ', m[2]) : h('p', {}, first),
    lines,
    actions(cur),
    slack === 'posted' ? h('p', { class: 'slack-note ok' }, '✓ Also posted to your Slack channel')
      : slack && slack !== 'off' ? h('p', { class: 'slack-note bad' }, `Slack post ${slack}`)
        : cur.res ? h('p', { class: 'slack-note' }, 'Shown here only. ', goto('connect', 'Connect Slack'), ' to post it to a real channel.') : null);
}

function actions(cur) {
  if (cur.stored || !cur.res) return null;
  const o = cur.res.outcome, rc = o.root_cause;
  if (cur.resolved) {
    const d = cur.resolved.data;
    return h('div', { class: 'learned' }, h('p', {}, h('span', { class: 'pill rb' }, 'saved to memory'), ' ',
      d ? [`Fix confirmed. Runbook `, h('b', {}, `“${d.title}”`), ` now has ${plural(d.successes, 'success')}.`] : cur.resolved.summary),
      d?.steps ? h('ol', {}, d.steps.map((s) => h('li', {}, s))) : null);
  }
  const alts = [...o.refuted, ...(o.co_causes || [])].filter((r) => r.change !== rc?.change);
  return h('div', { class: 'actions' },
    rc ? h('button', { class: 'confirm', disabled: state.running && !cur.done,
      onclick: () => resolve(cur, rc.change) }, `✓ Confirm: ${short(rc.change)} caused it`)
      : h('p', { class: 'muted' }, 'No recent change explains this alert, so a human needs to look.'),
    alts.length ? h('button', { class: 'ghost', onclick: () => { cur.showAlt = !cur.showAlt; renderAnswer(cur); } },
      rc ? 'Wrong cause?' : 'Pick the cause yourself') : null,
    cur.showAlt ? h('div', { class: 'alts' },
      h('p', { class: 'muted small' }, 'Pick the change that really caused it. Your call is written to the graph and becomes memory.'),
      h('ul', {}, alts.map((r) => h('li', {}, h('span', {}, h('b', {}, short(r.change)), ` on ${short(r.service)} `,
        h('span', { class: 'pill out' }, r.tag || 'suspect')),
        h('button', { class: 'ghost', onclick: () => resolve(cur, r.change) }, 'This one'))))) : null);
}

function sideCards(cur) {
  if (cur.stored) {
    return [h('div', { class: 'card' }, h('h3', {}, 'From the graph'),
      h('p', {}, 'This incident was handled before this page was opened. Its update and every agent step are stored on '
        + 'the incident in FalkorDB; see them under “Show me why”.'))];
  }
  const steps = cur.steps, checks = steps.filter((s) => s.tool === 'check_hypothesis' && s.data);
  if (!cur.res) {
    return [h('div', { class: 'card' }, h('h3', {}, 'What the agents can see'),
      h('p', {}, 'Services and their dependencies (with dates), owners, on-call rotas, every deploy and config change, '
        + 'anomalies, past incidents and what fixed them, docs, tickets and chat: one FalkorDB graph per company.'),
      h('p', { class: 'muted small' }, 'Open “Show me why” to watch them walk it.'))];
  }
  const o = cur.res.outcome, rc = o.root_cause, mem = o.memory, recalled = mem.recalled[0], wo = cur.ablation?.without_memory;
  const cards = [];
  if (o.storm) {
    const alerts = [...o.storm.alerts.map((a) => a.service), cur.home];
    cards.push(h('div', { class: 'card storm' }, h('h3', {}, 'Alert storm'),
      h('p', { class: 'big-line' }, h('b', {}, `${new Set(alerts).size} alerts`), ' → 1 incident'),
      h('p', {}, 'They share upstream services; the nearest to all of them: ',
        h('b', {}, o.storm.shared.slice(0, 2).map((s) => short(s.service)).join(', ') || 'none')),
      h('p', { class: 'muted small' }, 'Without correlating them first, the same agents blame a change that explains only one alert.')));
  }
  if (rc) {
    cards.push(h('div', { class: 'card cause' }, h('h3', {}, 'Why this change'),
      rc.live_path?.length > 1 ? pathChips(rc.live_path) : null,
      h('p', {}, rc.reason),
      h('p', { class: 'muted small' }, `${plural(checks.length, 'suspect')} tested against the graph, `
        + `${checks.filter((s) => s.data.verdict !== 'supports').length} ruled out (each with its reason, in the update).`),
      (o.co_causes || []).map((c) => h('p', { class: 'small' }, 'Also contributing: ', h('b', {}, short(c.change)), ` on ${short(c.service)}`))));
  }
  const bp = o.baseline_pick, ab = o.anomaly_baseline_pick;
  if (bp || ab) {
    const row = (label, pick, ok) => pick && h('li', { class: ok ? 'ok' : 'bad' }, h('span', {}, label),
      h('b', {}, short(pick.change)), h('span', { class: 'pill' }, ok ? 'same answer' : 'wrong'));
    cards.push(h('div', { class: 'card nograph' }, h('h3', {}, 'Without the graph'),
      h('ul', {}, row('Newest change', bp, o.baseline_correct), row('Change log + anomalies', ab, o.anomaly_baseline_correct)),
      h('p', { class: 'muted small' }, 'What you would blame from a change log and dashboards alone, without walking the dependencies.')));
  }
  cards.push(h('div', { class: 'card memory-card' }, h('h3', {}, 'Memory'),
    recalled ? h('p', {}, 'Recalled ', h('b', {}, `“${recalled.title}”`), ' and its fix ', h('b', {}, `“${recalled.runbook_title}”`), '. ',
      mem.solved_by_memory ? h('span', { class: 'pill memory' }, 'solved by memory')
        : h('span', { class: 'muted' }, 'It did not apply here, so the search widened.'))
      : h('p', { class: 'muted' }, 'No similar past incident on this dependency path.'),
    wo ? h('div', { class: 'compare' }, h('p', { class: 'muted small' }, 'Same incident, replayed on the graph without this memory:'),
      h('div', { class: 'nums' },
        h('div', {}, h('span', { class: 'big' }, h('span', { class: 'before' }, wo.investigator_calls), ' → ', o.investigator_calls),
          h('span', { class: 'lbl' }, 'investigator steps')),
        h('div', {}, h('span', { class: 'big' }, h('span', { class: 'before' }, wo.hypotheses_checked), ' → ', o.hypotheses_checked),
          h('span', { class: 'lbl' }, 'suspects tested'))))
      : cur.act === 2 && !cur.ablation ? h('p', { class: 'muted small' }, 'Replaying it without memory for comparison…') : null));
  return cards;
}

function renderAnswer(cur) {
  $('answer-main').replaceChildren(slackCard(cur));
  $('answer-side').replaceChildren(...sideCards(cur));
}

// ---------- rendering: show me why (trace) ----------
function learnNames(step) {
  const d = step.data;
  if (step.tool === 'page_on_call' && d?.person) {
    names.set(d.person, d.name);
    names.set(d.team, `${d.team_name} team`);
  }
  if (step.tool === 'who_knows') for (const p of d || []) names.set(p.person, p.name);
  if (step.tool === 'ask') for (const r of d?.related || []) if (['person', 'team'].includes(kindOf(r.id))) names.set(r.id, r.name);
}

function queryBlock(q) {
  return h('div', { class: 'q' },
    h('div', { class: 'qhead' }, h('b', {}, q.name),
      h('span', { class: `rw ${q.readonly ? 'ro' : 'w'}`, title: q.readonly ? 'GRAPH.RO_QUERY' : 'GRAPH.QUERY (writes)' }, q.readonly ? 'RO' : 'W'),
      h('span', { class: 'muted' }, `${q.rows.length} rows · ${q.ms} ms`),
      q.name === 'incident_board' ? h('span', { class: 'tag' }, 'the agent reads the shared board') : null),
    h('pre', { class: 'cypher' }, q.cypher),
    h('pre', { class: 'params' }, `params ${JSON.stringify(q.params)}`),
    q.rows.length ? h('details', { class: 'rows' }, h('summary', {}, `rows (${q.rows.length})`),
      h('pre', {}, JSON.stringify(q.rows, null, 1))) : null);
}

function cypherList(queries) {
  if (!queries?.length) return null;
  const ms = queries.reduce((a, q) => a + q.ms, 0), rows = queries.reduce((a, q) => a + q.rows.length, 0);
  return h('details', { class: 'cypher-list' },
    h('summary', {}, `Cypher: ${plural(queries.length, 'query')}, ${plural(rows, 'row')}, ${ms.toFixed(1)} ms`),
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
  const d = step.data, verdict = step.tool === 'check_hypothesis' && d ? d.verdict : null;
  const body = verdict
    ? h('p', { class: 'summary' }, h('span', { class: `verdict ${verdict}` }, verdict.toUpperCase()), ' ',
      verdict === 'supports' ? h('b', {}, short(d.change)) : h('s', {}, short(d.change)), ` on ${short(d.service)}: `,
      h('span', { class: 'reason' }, d.reason),
      verdict === 'supports' && d.live_path?.length > 1 ? pathChips(d.live_path) : null)
    : h('p', { class: 'summary' }, step.summary);
  return h('li', { class: `card ${step.role}${verdict ? ` v-${verdict}` : ''}`, 'data-i': i, tabindex: 0 },
    h('div', { class: 'card-head' }, h('span', { class: `role ${step.role}` }, step.role), h('code', { class: 'tool' }, step.tool),
      h('span', { class: 'seq' }, `#${step.seq}`)),
    body,
    h('p', { class: 'why' }, h('span', { class: 'why-label' }, 'why '), step.reason),
    cypherList(step.queries));
}

function renderTrace(cur) {
  $('trace').replaceChildren(...(cur.steps || []).map(stepCard));
  $('trace-count').textContent = cur.steps?.length ? plural(cur.steps.length, 'step') : '';
  $('btn-skip').hidden = cur.done || !!cur.stored;
}

function appendTrace(cur, step) {
  const li = stepCard(step, cur.steps.length - 1);
  $('trace').querySelector('.current')?.classList.remove('current');
  li.classList.add('current');
  $('trace').append(li);
  if (state.tab === 'why') li.scrollIntoView({ block: 'nearest', behavior: state.skip ? 'auto' : 'smooth' });
  $('trace-count').textContent = plural(cur.steps.length, 'step');
}

function onTraceClick(ev) {
  if (ev.target.closest('summary, pre, details[open] *')) return; // let people read and expand the Cypher
  const li = ev.target.closest('li[data-i]'), cur = state.current;
  if (!li || !cur?.steps) return;
  $('trace').querySelectorAll('.selected').forEach((x) => x.classList.remove('selected'));
  li.classList.add('selected');
  const eles = cur.steps[Number(li.dataset.i)]?.eles;
  if (eles && state.graphOwner === cur) G.paint(cur, eles, G.near(eles));
}

// ---------- the graph's picture of a run ----------
function hudFor(cur) {
  $('hud').replaceChildren(...(cur
    ? [h('span', { class: 'pill alert' }, cur.alerts.length > 1 ? 'ALERTS' : 'ALERT'),
      h('b', {}, cur.alerts.length > 1 ? cur.alerts.map((a) => short(a.service)).join(', ') : cur.alert.name),
      h('span', { class: 'muted' }, `${ist(cur.alert.at)}${cur.incident ? ` · ${cur.incident}` : ''}`)]
    : [h('span', { class: 'muted' }, state.caption)]));
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

// End on the answer, big enough to read: a storm ends on the alerting services, shared upstream and cause; otherwise
// the cause path and, if memory solved it, the chain new incident -> recalled incident -> its runbook.
function finalPaint(run) {
  const o = run.res.outcome;
  const memo = o.memory.solved_by_memory ? G.elementsFor({ nodes: [], edges: o.memory.recalled.flatMap((r) =>
    [[run.incident, r.incident, 'RECALLS'], [r.incident, r.runbook, 'FIXED_WITH']]) }, run) : null;
  if (memo) run.touched = run.touched.union(memo);
  const learned = run.resolved && G.elementsFor(run.resolved.highlight, run);
  if (learned) run.touched = run.touched.union(learned);
  const storm = o.storm ? G.select('.storm, .shared') : null;
  const focus = storm ? run.cause.union(storm) : run.cause.nonempty() ? run.cause.union(memo || G.empty()) : null;
  G.paint(run, learned || memo, focus);
}

// Rebuild the graph's picture of a run from its steps (switching incidents, or back from Ask).
function replayGraph(cur) {
  state.graphOwner = cur;
  hudFor(cur);
  if (!G.ready()) return;
  G.clear(false);
  if (!cur) return G.paint(null);
  cur.touched = G.empty();
  cur.cause = G.empty();
  G.mark(cur.home, 'alerting');
  for (const s of cur.steps || []) applyStep(cur, s, false);
  if (cur.res) finalPaint(cur);
  else G.paint(cur, null, cur.touched.nonempty() ? cur.touched : G.select(`[id = "${cur.home}"]`));
}

// ---------- views ----------
function showView(view) {
  state.view = view;
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
  $('answer-view').hidden = tab !== 'answer';
  $('why-view').hidden = tab !== 'why';
  placeGraph();
}

// One Cytoscape canvas, moved to wherever it is shown; its picture is rebuilt when its owner changes.
function placeGraph() {
  const ask = state.view === 'ask';
  const slot = ask ? $('ask-graph-slot') : $('why-graph-slot');
  if ($('graph-wrap').parentElement !== slot) slot.append($('graph-wrap'));
  if (ask && state.graphOwner !== 'ask') {
    state.graphOwner = 'ask';
    hudFor(null);
    G.clear(false);
  } else if (!ask && state.tab === 'why' && state.graphOwner !== state.current) replayGraph(state.current);
  requestAnimationFrame(() => G.refit());
}

function showIncident(cur) {
  state.current = cur;
  $('landing').hidden = !!cur;
  $('incident').hidden = !cur;
  renderAll();
  if (state.view !== 'incidents') showView('incidents');
  else placeGraph();
}

function renderAll() {
  renderInbox();
  renderScenarios();
  const cur = state.current;
  if (!cur) return renderLanding();
  renderHead(cur);
  renderProgress(cur);
  renderAnswer(cur);
  renderTrace(cur);
}

function openRun(run) {
  if (state.current === run) return;
  showIncident(run);
}

async function openStored(incident) {
  try {
    const d = await api('GET', `${T()}/incidents/${enc(incident)}`);
    const alerts = state.alerts.filter((a) => a.incident === incident);
    const alert = { id: d.alert, name: d.alert_name, service: d.service, at: d.at };
    showIncident({ stored: true, done: true, incident, alert, alerts: alerts.length ? alerts : [alert], home: d.service,
      status: d.status, update_text: d.update_text, steps: d.steps, touched: G.empty(), cause: G.empty() });
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
  $('btn-reset').disabled = on;
  renderScenarios();
  if (!state.current) renderLanding();
}

async function fire(act) {
  if (state.running) return;
  const sc = scenarios().find((s) => s.act === act);
  if (!sc) return;
  const run = newRun(sc.trigger, sc.alerts, act);
  state.runs.push(run);
  state.skip = false;
  setRunning(true);
  showIncident(run);
  showTab('answer');
  replayGraph(run);
  let last = 0;
  try {
    for await (const ev of runEvents(`${T()}/alerts/${enc(sc.trigger.id)}/respond/stream${act === 2 ? '?compare=memory' : ''}`)) {
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
    toast(`Agent run failed: ${e.message}`, true);
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
  renderInbox();
  if (state.current !== run) return;
  renderHead(run);
  renderProgress(run);
  appendTrace(run, step);
  if (step.tool === 'post_update') renderAnswer(run);
}

function onResult(run, res) {
  run.res = res;
  run.incident = res.incident_id;
  run.done = true;
  run.folded = true;
  if (state.graphOwner === run) finalPaint(run);
  if (state.current === run) renderAll();
  const rc = res.outcome.root_cause;
  toast(rc ? `Cause found: ${short(rc.change)} on ${short(rc.service)}. Confirm it to save the fix to memory.`
    : 'No change explains this alert; the update asks a human to look.');
}

async function resolve(cur, change) {
  try {
    const r = await api('POST', `${T()}/incidents/${enc(cur.incident)}/resolve`, { change_id: change });
    cur.resolved = r;
    cur.showAlt = false;
    if (r.data) names.set(r.data.runbook, 'runbook');
    if (state.graphOwner === cur) finalPaint(cur);
    toast(r.summary);
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
    Object.assign(state, { runs: [], chat: [], graphOwner: null });
    await loadTenant();
    showIncident(null);
    toast(r.status === 'seeded' ? 'Loaded the demo company into FalkorDB.' : 'Demo reset: the graph was restored from its pristine copy (GRAPH.COPY).');
  } catch (e) {
    toast(e.message, true);
  }
}

// ---------- ask the brain ----------
function brainMessage(m) {
  if (m.pending) return h('div', { class: 'msg brain' }, h('p', { class: 'muted' }, h('span', { class: 'spinner' }), 'Searching the graph…'));
  if (m.error) return h('div', { class: 'msg brain' }, h('p', { class: 'error' }, m.error));
  const d = m.data;
  return h('div', { class: 'msg brain' },
    h('p', { class: 'answer' }, d.answer),
    d.hits?.length ? [h('p', { class: 'k' }, 'Sources'), h('ol', { class: 'hits' }, d.hits.map((x) => h('li', {},
      h('div', {}, h('span', { class: 'pill kind' }, x.kind), ' ', h('b', {}, x.title),
        x.superseded_by ? [' ', h('span', { class: 'pill out' }, `superseded by ${short(x.superseded_by)}`)] : null),
      h('div', { class: 'reason' }, x.snippet))))] : null,
    d.related?.length ? [h('p', { class: 'k' }, 'Linked in the graph'), h('div', { class: 'chips' }, d.related.map((r) =>
      h('span', { class: 'chip-static' }, h('span', { class: 'pill kind' }, r.kind), ' ', r.name)))] : null,
    cypherList(m.queries));
}

function renderChat() {
  const log = $('chat-log');
  if (!state.chat.length) {
    log.replaceChildren(h('div', { class: 'chat-empty' },
      h('h2', {}, 'Ask the company brain'),
      h('p', { class: 'muted' }, 'Answers come from the same graph the agents use: services, owners, on-call, changes, '
        + 'past incidents, docs, tickets and chat. Every answer cites its sources. No LLM writes it: it is assembled '
        + 'from graph facts and quoted text.'),
      OFFLINE ? h('p', { class: 'note' }, 'This page is a recorded replay, so questions need the live server '
        + '(run make dev and open it without ?offline=1). Questions it answers, for example:') : null,
      h('div', { class: 'chips' }, EXAMPLES.map((q) => h('button', { class: 'chip-btn', disabled: OFFLINE, onclick: () => askQ(q) }, q)))));
    return;
  }
  log.replaceChildren(...state.chat.map((m) => (m.who === 'you' ? h('div', { class: 'msg you' }, m.text) : brainMessage(m))));
  log.scrollTop = log.scrollHeight;
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
    if (state.view === 'ask' && G.ready()) {
      state.graphOwner = 'ask';
      G.clear(false);
      const eles = G.elementsFor(r.highlight, null);
      G.paint(null, eles, eles?.nonempty() ? G.near(eles) : null);
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
  const code = (text) => h('pre', { class: 'code' }, text);
  const card = (title, ...kids) => h('div', { class: 'card connect-card' }, h('h3', {}, title), ...kids);
  $('connect').replaceChildren(
    h('div', { class: 'connect-intro' }, h('h2', {}, 'Plug it into your stack'),
      h('p', { class: 'muted' }, 'Every agent tool is defined once and exposed three ways: to the agents, over MCP, and over HTTP.')),
    h('div', { class: 'connect-grid' },
      card('Use it from Claude Code (MCP)',
        h('p', {}, 'The same graph tools the agents use (blast radius, dependency paths, suspects, who knows, ask…) plus '
          + '“respond to alert”, for any MCP client.'),
        code('claude mcp add --transport stdio oncall-brain -- \\\n  <venv>/bin/python -m oncall_brain.mcp_server'),
        h('p', { class: 'muted small' }, 'Then ask Claude: “checkout is slow. Use oncall-brain to find out why.” '
          + 'Over HTTP instead: python -m oncall_brain.mcp_server --http --port 8001')),
      card('Send alerts in (webhook)',
        h('p', {}, 'Point your alerting tool at this endpoint (map its payload to service, symptom and name). With '
          + 'respond=true the agents start on it right away.'),
        code(`curl -X POST '${origin}${T()}/alerts?respond=true' \\\n  -H 'content-type: application/json' \\\n`
          + `  -d '{"service": "svc:checkout", "symptom": "latency",\n       "name": "checkout p99 latency above 2s"}'`),
        h('p', { class: 'muted small' }, 'symptom is latency, errors or saturation. New alerts show up in the inbox.')),
      card('Post updates to Slack',
        state.health?.slack ? h('p', { class: 'ok-line' }, '✓ Connected: every status update is also posted to your channel.')
          : h('p', {}, 'Not connected. Create an incoming webhook in Slack (Apps → Incoming Webhooks), then add it to .env '
            + 'and restart:'),
        state.health?.slack ? null : code('SLACK_WEBHOOK_URL=https://hooks.slack.com/services/…')),
      card('Bring your own data',
        h('p', {}, `This demo runs on a synthetic company (${state.stats || 'services, teams, people, changes'}). Real `
          + 'systems feed the same graph as things happen, through write tools on MCP and HTTP:'),
        h('ul', { class: 'small' },
          h('li', {}, h('code', {}, 'record_change'), ' from CI/CD (deploys, config changes)'),
          h('li', {}, h('code', {}, 'record_anomaly'), ' and ', h('code', {}, 'raise_alert'), ' from monitoring'),
          h('li', {}, h('code', {}, 'add_dependency'), ' / ', h('code', {}, 'retire_dependency'), ' from the service catalog')),
        h('p', { class: 'muted small' }, 'Every write is an idempotent MERGE, so replays and retries are safe.')),
      card('Who decides each step',
        h('p', {}, 'Now: ', h('b', {}, plannerName()), '. Set LLM_PROVIDER (anthropic, openai, gemini, groq, ollama…) and a key '
          + 'in .env to let a model choose the tools; without one, rules choose each step from what the graph returns. '
          + 'Either way, every fact comes from a Cypher query.')),
      card('Each company is its own graph',
        h('p', {}, 'One FalkorDB graph per tenant: memory, incidents and knowledge never mix between companies. This page '
          + 'shows tenant ', h('b', {}, state.tenant), '; add ?tenant=<name> to the URL and Reset demo to try another.'))));
}

// ---------- startup ----------
async function loadTenant() {
  state.alerts = await api('GET', `${T()}/alerts`);
  const g = await api('GET', `${T()}/graph`);
  state.caption = G.build($('graph'), g);
  state.stats = `${g.nodes.length} services, ${new Set(g.nodes.map((n) => n.team)).size} teams, ${g.edges.length} dependencies`;
  state.graphOwner = null;
  hudFor(null);
}

async function init() {
  for (const b of document.querySelectorAll('.view-tab')) b.onclick = () => showView(b.dataset.view);
  $('tab-answer').onclick = () => showTab('answer');
  $('tab-why').onclick = () => showTab('why');
  $('btn-reset').onclick = doReset;
  $('btn-skip').onclick = () => { state.skip = true; };
  $('trace').addEventListener('click', onTraceClick);
  $('trace').addEventListener('keydown', (e) => { if (e.key === 'Enter') onTraceClick(e); });
  $('ask-form').onsubmit = (e) => {
    e.preventDefault(); // the native form gives Enter-to-ask; never navigate
    const q = $('ask-q').value.trim();
    $('ask-q').value = '';
    askQ(q);
  };
  if (OFFLINE) $('ask-q').disabled = $('ask-go').disabled = true;
  placeGraph();
  showIncident(null);
  try {
    const hl = state.health = await api('GET', '/api/health');
    const tenant = params.get('tenant');
    state.tenant = tenant && /^[a-z0-9_]{1,40}$/.test(tenant) ? tenant : hl.default_tenant;
    $('tenant').textContent = `company: ${state.tenant}`;
    if (OFFLINE) { // a recording, not a connection: no green dot
      $('db').textContent = 'recorded replay';
      $('db').title = 'Replaying runs recorded from the real code (web/fixtures); no FalkorDB behind this page';
    } else {
      $('db').textContent = hl.falkordb ? 'FalkorDB' : 'FalkorDB down';
      $('db').classList.add(hl.falkordb ? 'ok' : 'bad');
    }
    $('planner').textContent = /deterministic|mock/i.test(hl.planner) ? 'planner: rules' : `planner: ${plannerName()}`;
    $('planner').title = hl.planner;
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
    toast(`${e.message}. Press “Reset demo” to load the demo company.`, true);
  }
  renderAll();
}

init();
