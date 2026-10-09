/* Local Poker Arena. API values are rendered as text, never as HTML. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const list = value => Array.isArray(value) ? value : [];
  const selected = new Set();
  const runNodes = new Map();
  const tournamentScores = new Map(), tournamentScoreRequests = new Set();
  let state = { agents: [], runs: [], leaderboard: [], profiles: [] };
  let profile = 'default', refreshing = false, refreshAgain = false;
  let rosterSignature = '', boardSignature = '';
  const terminal = status => /^(completed|complete|done|success|failed|error|cancelled|canceled|interrupted)$/i.test(status || '');
  const display = value => value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value);
  const number = value => value == null || value === '' || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = display(text);
    if (className) node.className = className;
    return node;
  }
  function empty(parent, title, body) {
    const box = el('div', null, 'empty');
    box.append(el('strong', title), el('span', body));
    parent.replaceChildren(box);
  }
  function message(id, text, error = false) {
    $(id).textContent = text;
    $(id).classList.toggle('error-text', error);
  }
  async function api(path, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(path, { signal: controller.signal, cache: 'no-store', ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
      const text = await response.text();
      let data;
      try { data = text ? JSON.parse(text) : {}; } catch { throw new Error(`Server returned an unreadable response (${response.status}).`); }
      if (!response.ok) throw new Error(display(data.error || data.detail || data.message || `Request failed (${response.status}).`));
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Request timed out. Check the queue or registry before retrying; the server may have accepted it.');
      throw error;
    } finally { clearTimeout(timeout); }
  }
  function date(value) {
    if (!value) return 'Time unavailable';
    const parsed = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
    return Number.isNaN(parsed.getTime()) ? display(value) : parsed.toLocaleString();
  }
  function table(parent, rows, columns) {
    const wrap = el('div', null, 'table-wrap'), t = el('table'), head = el('tr');
    columns.forEach(c => { const th = el('th', c.label, c.numeric ? 'numeric' : ''); th.scope = 'col'; head.append(th); });
    const thead = el('thead'); thead.append(head); t.append(thead);
    const tbody = el('tbody');
    rows.forEach((row, index) => {
      const tr = el('tr');
      columns.forEach(c => {
        const value = c.get ? c.get(row, index) : row[c.key];
        const td = el('td', value instanceof Node ? null : c.numeric ? number(value) : display(value), c.numeric ? 'numeric' : '');
        if (value instanceof Node) td.append(value);
        if (c.signed && value != null && Number.isFinite(Number(value))) td.classList.add(Number(value) < 0 ? 'negative' : 'positive');
        tr.append(td);
      });
      tbody.append(tr);
    });
    t.append(tbody); wrap.append(t); parent.replaceChildren(wrap);
  }
  function downloadAgent(id) {
    const agent = list(state.agents).find(a => a.id === id);
    if (!agent) return el('span', 'Code not published', 'muted');
    const link = el('a', 'Download ZIP', 'button secondary');
    link.href = `/api/agents/${encodeURIComponent(id)}/download`;
    link.download = `${agent.slug || id}.zip`;
    link.addEventListener('click', event => event.stopPropagation());
    return link;
  }
  function updateSelection() {
    $('selection-count').textContent = `${selected.size} agent${selected.size === 1 ? '' : 's'} selected`;
  }
  function renderAgents() {
    const agents = list(state.agents), ids = new Set(agents.map(a => String(a.id)));
    for (const id of selected) if (!ids.has(id)) selected.delete(id);
    const signature = JSON.stringify(agents);
    if (signature !== rosterSignature) {
      rosterSignature = signature;
      $('agent-list').replaceChildren();
      if (!agents.length) empty($('agent-list'), 'Your first contender starts here', 'Register a Python file or ZIP, then select agents for a run.');
      agents.forEach(agent => {
        const row = el('label', null, 'agent-row'), check = el('input');
        check.type = 'checkbox'; check.value = String(agent.id); check.checked = selected.has(check.value);
        check.addEventListener('change', () => { check.checked ? selected.add(check.value) : selected.delete(check.value); updateSelection(); });
        const info = el('span', null, 'agent-info');
        info.append(el('strong', agent.name || agent.id), el('small', `${String(agent.hash || 'No hash').slice(0, 12)} · ${date(agent.created)}`));
        row.append(check, el('span', String(agent.name || 'A').slice(0, 1).toUpperCase(), 'agent-avatar'), info, downloadAgent(agent.id));
        $('agent-list').append(row);
      });
    }
    $('agent-count').textContent = `${agents.length} agents`;
    updateSelection();
  }
  function renderProfiles() {
    const profiles = list(state.profiles).filter(p => p && p.id != null);
    if (!profiles.some(p => String(p.id) === profile)) profiles.unshift({ id: profile, label: profile === 'default' ? 'Default' : profile });
    const signature = JSON.stringify(profiles);
    if ($('profile').dataset.signature !== signature) {
      $('profile').replaceChildren(...profiles.map(p => new Option(p.label || p.id, String(p.id))));
      $('profile').value = profile; $('profile').dataset.signature = signature;
    }
    $('run-profile').textContent = `Profile: ${profiles.find(p => String(p.id) === profile)?.label || profile}`;
  }
  function renderBoard() {
    const rows = list(state.leaderboard), signature = JSON.stringify(rows);
    if (signature === boardSignature) return;
    boardSignature = signature;
    if (!rows.length) { empty($('leaderboard'), 'A clean slate. A fair comparison.', 'Complete a benchmark in this profile to see agent performance here.'); return; }
    table($('leaderboard'), rows, [
      { label: '#', get: (_, i) => String(i + 1).padStart(2, '0') }, { label: 'Agent', get: r => r.name || r.id },
      { label: 'Chips', key: 'chips', numeric: true, signed: true }, { label: 'Hands', key: 'hands', numeric: true },
      { label: 'mbb / hand', key: 'mbb', numeric: true, signed: true },
      { label: 'Sets', key: 'sets', numeric: true }, { label: 'Set win rate', get: r => r.win_rate == null ? '—' : typeof r.win_rate === 'number' ? `${number(r.win_rate)}%` : r.win_rate },
      { label: 'Failures', key: 'failures', numeric: true },
      { label: 'Export', get: r => downloadAgent(r.id) }
    ]);
  }
  function placementScores(results) {
    const totals = new Map(), counts = new Map();
    for (const group of list(results)) {
      if (group.round === 'playoff') continue;
      const agents = list(group.agents), n = agents.length;
      if (!n) continue;
      for (const game of list(group.games)) {
        const chips = list(game.chips);
        if (chips.length !== n || !chips.every(Number.isFinite)) continue;
        chips.forEach((value, i) => {
          const higher = chips.filter(x => x > value).length;
          const tied = chips.filter(x => x === value).length;
          const score = (n - higher - (tied - 1) / 2) / n;
          const id = agents[i].id;
          totals.set(id, (totals.get(id) || 0) + score);
          counts.set(id, (counts.get(id) || 0) + 1);
        });
      }
    }
    return new Map([...totals].map(([id, total]) => [id, total / counts.get(id)]));
  }
  function renderTournament() {
    const runs = list(state.runs).filter(r => r.mode === 'tournament');
    const select = $('tournament-run'), chosen = select.value || 'latest';
    select.replaceChildren(new Option('Latest completed tournament', 'latest'), ...runs.map(r => new Option(`${date(r.created)} · ${r.status} · ${r.id.slice(0, 8)}`, r.id)));
    select.value = chosen === 'latest' || runs.some(r => r.id === chosen) ? chosen : 'latest';
    const run = select.value === 'latest' ? runs.filter(r => r.status === 'completed').sort((a, b) => String(b.finished).localeCompare(String(a.finished)))[0] : runs.find(r => r.id === select.value);
    if (!run) {
      $('tournament-note').textContent = 'No completed tournament yet. Queued and running tournaments can be selected above.';
      empty($('tournament-board'), 'No tournament standings yet', 'Queue a tournament between selected agents.'); return;
    }
    const scoreVersion = JSON.stringify([run.status, run.progress, run.leaderboard]);
    const cached = tournamentScores.get(run.id);
    const scores = cached?.version === scoreVersion ? cached.scores : null;
    if (!scores && !tournamentScoreRequests.has(run.id)) {
      tournamentScoreRequests.add(run.id);
      api(`/api/runs/${encodeURIComponent(run.id)}`).then(detail => {
        tournamentScores.set(run.id, {version: scoreVersion, scores: placementScores(detail.results)});
        tournamentScoreRequests.delete(run.id);
        renderTournament();
      }).catch(() => { tournamentScoreRequests.delete(run.id); });
    }
    $('tournament-note').textContent = `${run.id} · ${run.status} · ${run.config.deals} hands/game · ${run.config.seeds.length} seed(s). ${run.status === 'completed' ? 'Final local standings.' : 'Provisional results; failed/cancelled runs are not final rankings.'} Placement score = average game points ÷ table size, excluding playoffs; not a win rate. Rank uses round placement points. Scores depend on opponents and table sizes; unlike the separate evaluation, sizes are not equally weighted.`;
    const rows = list(run.leaderboard).slice().sort((a, b) => b.placement_points - a.placement_points || b.playoff_points - a.playoff_points);
    if (!rows.length) { empty($('tournament-board'), 'Waiting for round results', display(run.progress)); return; }
    table($('tournament-board'), rows, [
      {label:'Rank',get:r => r.rank ?? 1 + rows.filter(o => o.placement_points > r.placement_points || (o.placement_points === r.placement_points && o.playoff_points > r.playoff_points)).length,numeric:true},
      {label:'Agent',key:'name'},
      {label:'Placement score',get:r => scores?.has(r.id) ? `${number(scores.get(r.id)*100)}%` : '—'},
      {label:'Round placement points',key:'placement_points',numeric:true},
      {label:'Game points',key:'game_points',numeric:true}, {label:'Playoff points',key:'playoff_points',numeric:true},
      {label:'Chips',key:'chips',numeric:true,signed:true}, {label:'Failures',key:'failures',numeric:true},
      {label:'Export',get:r => downloadAgent(r.id)}
    ]);
  }
  function renderEvaluation() {
    const parent = $('evaluation');
    if (!parent) return;
    const run = list(state.runs).find(r => r.mode === 'evaluation' && r.evaluation);
    parent.hidden = !run;
    if (!run) return;
    const p = run.evaluation;
    const signature = JSON.stringify(p);
    if (parent.dataset.signature === signature) return;
    parent.dataset.signature = signature;
    const heading = el('div', null, 'panel-heading');
    const title = el('div'); title.append(el('p', 'LIVE EXPERIMENT', 'eyebrow'), el('h2', p.title || '600k training and evaluation'));
    heading.append(title, el('span', `${p.status} · ${p.stage}`, `tag status-${p.status}`));
    const trainingText = p.training_budget_seconds
      ? `${number(p.new_hands)} additional training hands · ${number(p.training_elapsed_seconds / 60)} / ${number(p.training_budget_seconds / 60)} training minutes`
      : `${number(p.new_hands)} / ${number(p.target_new_hands)} additional training hands`;
    const summary = el('p', `${trainingText} · ${number(p.candidates_completed)} / ${number(p.candidates_total)} candidates completed · Updated ${date(p.updated_utc)}`, 'profile-note');
    const progress = el('progress'); progress.max = p.duplicate_rounds_total || 1; progress.value = p.duplicate_rounds_completed || 0;
    const unit = p.progress_unit || 'duplicate rounds';
    progress.setAttribute('aria-label', `Completed ${unit}`);
    const current = el('p', p.active_candidate ? `Evaluating ${p.active_candidate} · ${number(p.duplicate_rounds_completed)} / ${number(p.duplicate_rounds_total)} ${unit} completed` : `Stage: ${p.stage} · ${list(p.completed_stages).join(' → ')}`, 'small');
    const results = el('div');
    table(results, list(p.candidates), [
      {label:'Candidate',key:'name'}, {label:'Status',key:'status'},
      {label:'Placement score',get:r => r.score == null ? '—' : `${number(r.score*100)}%`},
      ...(p.table_sizes || [2,3,4,5,6]).map(n => ({label:`${n} players`,get:r => r.sizes?.[n] == null ? '—' : `${number(r.sizes[n]*100)}%`})),
      {label:'Hands',key:'hands',numeric:true},{label:'Failures',key:'failures',numeric:true}
    ]);
    parent.replaceChildren(heading, summary, progress, current, results, el('p', p.note, 'profile-note'));
    if (p.active_candidate) parent.append(el('p', Object.entries(p.active_panels || {}).map(([name,rounds]) => `${name}: ${rounds}/8 rounds`).join(' · '), 'small muted'));
    for (const native of list(p.dashboard_runs)) {
      const link = el('a', `Dashboard tournament: ${native.status} · ${native.progress || native.id}`, 'button secondary');
      link.href = '#tournament-rankings'; link.onclick = () => { $('tournament-run').value = native.id; renderTournament(); };
      parent.append(link);
    }
    if (p.recommended_agent_id) parent.append(el('p', p.recommendation_reason, 'small'), downloadAgent(p.recommended_agent_id));
    if (p.error) parent.append(el('p', p.error, 'notice error'));
  }
  function raw(parent, title, value, open = false) {
    const details = el('details', null, 'raw'); details.open = open;
    details.append(el('summary', title), el('pre', value == null ? 'Not provided.' : JSON.stringify(value, null, 2))); parent.append(details);
  }
  function section(parent, title) {
    const node = el('section', null, 'detail-section'); node.append(el('h3', title)); parent.append(node); return node;
  }
  function gameRows(game, agents) {
    const chips = game.chips || [], verdicts = game.verdicts || [];
    const count = Math.max(agents.length, Object.keys(chips).length, Object.keys(verdicts).length);
    return Array.from({ length: count }, (_, i) => ({ name: agents[i]?.name || agents[i]?.id || `Seat ${i + 1}`, chips: chips[i] ?? chips[agents[i]?.id], verdict: verdicts[i] ?? verdicts[agents[i]?.id] }));
  }
  function historyHands(data) {
    if (Array.isArray(data)) return data;
    for (const key of ['hands', 'hand_histories', 'histories', 'history', 'deals']) {
      if (Array.isArray(data?.[key])) return data[key];
      if (data?.[key] && typeof data[key] === 'object') return Object.values(data[key]);
    }
    return data && typeof data === 'object' ? [data] : [];
  }
  function renderHand(parent, hand, history, game) {
    parent.replaceChildren();
    const cards = hand?.board ?? [...(hand?.events || [])].reverse().find(e => e.board)?.board ?? hand?.community_cards ?? hand?.cards ?? hand?.public_cards;
    const board = section(parent, 'Cards');
    if (Array.isArray(cards) && cards.every(c => typeof c === 'string' || typeof c === 'number')) {
      const row = el('div', null, 'history-board');
      cards.forEach(c => row.append(el('span', c, /[♥♦hd]$/i.test(String(c)) ? 'playing-card red' : 'playing-card')));
      board.append(row);
    } else raw(board, 'Card data', cards, true);
    const grid = el('div', null, 'history-grid'); parent.append(grid);
    const seats = section(grid, 'Seat map & private cards');
    const mapping = hand?.seat_map || [], agents = game.agents || [];
    const names = player => agents[player]?.name || `Player ${player}`;
    const seatTarget = el('div'); seats.append(seatTarget);
    table(seatTarget, mapping.map((player, seat) => ({ seat, name:names(player), cards:(hand?.holes?.[seat] || []).join(' '), delta:hand?.deltas_by_bot?.[player] })), [
      {label:'Seat',key:'seat',numeric:true},{label:'Agent',key:'name'},{label:'Cards',key:'cards'},{label:'Δ chips',key:'delta',numeric:true,signed:true}
    ]);
    if ((hand?.holes ?? hand?.hole_cards) != null) raw(seats, 'Hole cards (spectator only)', hand.holes ?? hand.hole_cards);
    const deltas = section(grid, 'Chip deltas');
    raw(deltas, 'Per-player changes', hand?.deltas_by_bot ?? hand?.deltas ?? hand?.chip_deltas ?? hand?.payoffs ?? hand?.rewards ?? hand?.chips, true);
    const eventsBox = section(parent, 'Hand events');
    const events = hand?.events ?? hand?.actions ?? hand?.history ?? hand?.steps;
    if (Array.isArray(events) && events.length) {
      const ol = el('ol', null, 'events'); events.forEach(event => {
        let text = display(event);
        if(event.type === 'action') text = `${event.street} · ${names(mapping[event.seat])} (seat ${event.seat}): ${event.action}, amount ${event.amount} · pot ${event.pot}`;
        if(event.type === 'street') text = `${event.street.toUpperCase()} · ${(event.board || []).join(' ')}`;
        if(event.type === 'blinds') text = `Blinds · seat ${event.sb_seat}: ${event.sb} · seat ${event.bb_seat}: ${event.bb}`;
        if(event.type === 'hand_end') text = `Hand complete · board ${(event.board || []).join(' ')} · ${list(event.pots).map(p => `pot ${p.amount} → ${list(p.winners).map(s => names(mapping[s])).join(', ')}`).join(' / ')}`;
        ol.append(el('li', text));
      }); eventsBox.append(ol);
    } else eventsBox.append(el('p', 'No structured events supplied. Expand the raw hand below to inspect all fields.', 'muted small'));
    raw(parent, 'Raw hand JSON · all fields', hand);
  }
  function historyViewer(parent, runId, games) {
    const box = section(parent, 'Hand history explorer');
    const available = games.filter(g => g.game.history_file);
    if (!available.length) { box.append(el('p', 'Hand histories will appear when games provide history files.', 'muted small')); return; }
    const controls = el('div', null, 'history-controls'), gameLabel = el('label', 'Game'), gameSelect = el('select');
    available.forEach((g, i) => gameSelect.add(new Option(g.label, String(i))));
    gameLabel.append(gameSelect);
    const handLabel = el('label', 'Hand'), handSelect = el('select'); handLabel.append(handSelect);
    const download = el('a', '↓ Raw JSON'); download.download = 'history.json';
    controls.append(gameLabel, handLabel, download);
    const content = el('div'); box.append(controls, content);
    let request = 0, hands = [], history = null;
    const show = () => renderHand(content, hands[Number(handSelect.value)], history, available[Number(gameSelect.value)]);
    handSelect.addEventListener('change', show);
    async function load() {
      const version = ++request, entry = available[Number(gameSelect.value)];
      const path = `/api/history/${encodeURIComponent(runId)}/${encodeURIComponent(entry.game.history_file)}`;
      download.href = path; handSelect.replaceChildren(); handSelect.disabled = true;
      content.replaceChildren(el('p', 'Loading hand history…', 'muted'));
      try {
        const data = await api(path); if (version !== request || !box.isConnected) return;
        history = data; hands = historyHands(data);
        hands.forEach((h, i) => handSelect.add(new Option(`Hand ${h?.hand_id ?? h?.hand_number ?? i + 1}`, String(i))));
        handSelect.disabled = !hands.length;
        if (hands.length) show(); else empty(content, 'No hands in this file', 'Download the raw JSON to inspect its contents.');
      } catch (error) {
        if (version !== request) return;
        const retry = el('button', 'Retry history', 'button secondary'); retry.type = 'button'; retry.onclick = load;
        content.replaceChildren(el('p', error.message, 'error-text'), retry);
      }
    }
    gameSelect.addEventListener('change', load); load();
  }
  function renderDetail(body, data, runId) {
    body.replaceChildren();
    if (data.error) body.append(el('div', display(data.error), 'notice error'));
    raw(body, 'Run configuration', data.config);
    if (data.mode === 'evaluation') {
      raw(body, 'Live evaluation progress', data.evaluation, true);
      const link = el('a', 'View live comparison table', 'button secondary'); link.href = '#evaluation'; body.append(link);
      return;
    }
    const standings = list(data.leaderboard);
    if (standings.length) {
      const box = section(body, 'Run standings'), target = el('div'); box.append(target);
      table(target, standings, [{label:'Rank',key:'rank',numeric:true}, { label: 'Agent', get: r => r.name || r.id }, ...['placement_points', 'game_points', 'playoff_points', 'chips', 'failures'].map(key => ({ key, label: key.replaceAll('_', ' '), numeric: true }))]);
    }
    const results = list(data.results), allGames = [];
    if (!results.length) empty(body.appendChild(el('div')), 'No game results yet', 'Queued and running experiments update automatically.');
    results.forEach((result, ri) => {
      const box = section(body, `Round ${result.round ?? ri + 1} · Table ${result.table ?? '—'} · Seed ${result.seed ?? '—'}`);
      list(result.games).forEach((game, gi) => {
        const entry = { game, agents: list(result.agents), label: `Round ${result.round ?? ri + 1} / Table ${result.table ?? '—'} / Game ${gi + 1} / ${result.seed ?? '—'}` };
        allGames.push(entry);
        const detail = el('details', null, 'game');
        detail.append(el('summary', `Game ${gi + 1} · ${number(game.num_hands)} hands`));
        const target = el('div'); detail.append(target);
        table(target, gameRows(game, entry.agents), [{ label: 'Agent / seat', key: 'name' }, { label: 'Chips', key: 'chips', numeric: true, signed: true }, { label: 'Verdict', key: 'verdict' }]);
        raw(detail, 'Execution logs', game.logs);
        box.append(detail);
      });
      if (list(result.standings).length) raw(box, 'Table standings', result.standings);
    });
    historyViewer(body, runId, allGames);
  }
  function currentAgentNames(value, names = new Map(list(state.agents).map(a => [a.id, a.name]))) {
    if (!value || typeof value !== 'object') return;
    if (!Array.isArray(value) && names.has(value.id) && Object.hasOwn(value, 'name')) value.name = names.get(value.id);
    for (const child of Object.values(value)) currentAgentNames(child, names);
  }
  async function loadDetail(entry, force = false) {
    if (entry.loading || (!force && entry.loaded && terminal(entry.run.status) && entry.loadedStatus === entry.run.status)) return;
    entry.loading = true;
    if (!entry.loaded) entry.detail.replaceChildren(el('p', 'Loading run details…', 'muted'));
    try {
      const data = await api(`/api/runs/${encodeURIComponent(entry.run.id)}`);
      currentAgentNames(data);
      if (!entry.root.isConnected) return;
      const signature = JSON.stringify(data);
      if (signature !== entry.signature) {
        // Progress-only updates must not reset an open game or selected hand.
        const contentSignature = JSON.stringify([data.results, data.leaderboard, data.error, data.config, data.evaluation]);
        if (contentSignature !== entry.contentSignature) { renderDetail(entry.detail, data, entry.run.id); entry.contentSignature = contentSignature; }
        entry.signature = signature;
      }
      entry.loaded = true; entry.loadedStatus = data.status; entry.detailError.textContent = '';
    } catch (error) { entry.detailError.textContent = `Could not refresh details: ${error.message}`; }
    finally { entry.loading = false; }
  }
  function renderRuns() {
    const runs = list(state.runs), ids = new Set(runs.map(r => String(r.id)));
    for (const [id, entry] of runNodes) if (!ids.has(id)) { entry.root.remove(); runNodes.delete(id); }
    if (!runs.length) { empty($('run-list'), 'The table is waiting', 'Select your agents and queue a benchmark or tournament. Runs remain in the server queue when you leave this page.'); return; }
    $('run-list').querySelector(':scope > .empty')?.remove();
    runs.forEach(run => {
      const id = String(run.id); let entry = runNodes.get(id);
      if (!entry) {
        const root = el('details', null, 'run'), summary = el('summary'), title = el('span', null, 'run-title');
        const name = el('strong'), meta = el('small'), badge = el('span', null, 'tag'), progress = el('span', null, 'run-progress');
        title.append(name, meta); summary.append(title, progress, badge);
        const body = el('div', null, 'run-body'), tools = el('div', null, 'run-tools'), cancel = el('button', 'Cancel run', 'button danger'), retry = el('button', 'Refresh details', 'button secondary');
        cancel.type = retry.type = 'button'; tools.append(retry, cancel);
        const detailError = el('div', null, 'error-text small'); detailError.setAttribute('role', 'status');
        const detail = el('div'); body.append(tools, detailError, detail); root.append(summary, body);
        entry = { root, name, meta, badge, progress, cancel, detail, detailError, run, loaded: false, loading: false };
        const current = entry;
        root.addEventListener('toggle', () => { if (root.open) loadDetail(current, true); });
        retry.onclick = () => loadDetail(current, true);
        cancel.onclick = async () => {
          cancel.disabled = true;
          try { await api(`/api/runs/${encodeURIComponent(id)}/cancel`, {}); detailError.textContent = 'Cancellation requested.'; await refresh(); }
          catch (error) { detailError.textContent = error.message; }
          finally { cancel.disabled = false; }
        };
        runNodes.set(id, entry); $('run-list').append(root);
      }
      const previousStatus = entry.run.status; entry.run = run;
      entry.name.textContent = `${run.mode === 'evaluation' ? (run.evaluation?.title || 'Evaluation') : run.mode === 'tournament' ? 'Tournament' : 'Benchmark'} · ${id}`;
      entry.meta.textContent = `${date(run.created)} · ${list(run.config?.agents).length} agents · ${number(run.config?.deals)} hands · ${number(run.config?.parallel_games || 1)} parallel`;
      const status = String(run.status || 'unknown');
      entry.badge.textContent = status; entry.badge.className = `tag status-${status.toLowerCase().replace(/[^a-z]/g, '')}`;
      entry.progress.textContent = run.progress == null ? '' : display(run.progress);
      entry.cancel.hidden = terminal(status) || run.mode === 'evaluation';
      if (entry.root.open) loadDetail(entry, previousStatus !== run.status);
    });
  }
  async function refresh() {
    if (refreshing) { refreshAgain = true; return; }
    refreshing = true; const requestedProfile = profile;
    try {
      const next = await api(`/api/state?profile=${encodeURIComponent(requestedProfile)}`);
      if (requestedProfile !== profile) { refreshAgain = true; return; }
      state = next || {}; currentAgentNames(state); profile = state.profile || 'default'; renderProfiles(); renderAgents(); renderBoard(); renderTournament(); renderEvaluation(); renderRuns();
      $('stat-agents').textContent = number(list(state.agents).length);
      $('stat-active').textContent = number(list(state.runs).filter(r => !terminal(r.status)).length);
      $('stat-complete').textContent = number(list(state.runs).filter(r => /^(completed|complete|done|success)$/i.test(r.status)).length);
      const hands = list(state.leaderboard).filter(r => r.hands != null && Number.isFinite(Number(r.hands)));
      $('stat-hands').textContent = hands.length ? number(hands.reduce((sum, r) => sum + Number(r.hands), 0)) : '—';
      $('connection').textContent = 'Live · local server'; $('connection').classList.add('online');
      $('state-error').hidden = true;
    } catch (error) {
      $('connection').textContent = 'Connection interrupted'; $('connection').classList.remove('online');
      $('state-error').textContent = `Unable to refresh: ${error.message} Showing the last available data. Retrying automatically.`;
      $('state-error').hidden = false;
    } finally {
      refreshing = false;
      if (refreshAgain) { refreshAgain = false; refresh(); }
    }
  }
  $('profile').addEventListener('change', () => {
    profile = $('profile').value; boardSignature = '';
    $('leaderboard').replaceChildren(el('p', 'Loading selected profile…', 'muted'));
    $('stat-hands').textContent = '—'; $('run-profile').textContent = `Profile: ${profile}`; refresh();
  });
  $('select-all').onclick = () => { list(state.agents).forEach(a => selected.add(String(a.id))); $('agent-list').querySelectorAll('input').forEach(c => { c.checked = true; }); updateSelection(); };
  $('select-none').onclick = () => { selected.clear(); $('agent-list').querySelectorAll('input').forEach(c => { c.checked = false; }); updateSelection(); };
  $('deals-preset').onchange = () => { const custom = $('deals-preset').value === 'custom'; $('custom-deals-label').hidden = !custom; $('custom-deals').required = custom; };
  $('agent-files').onchange = () => { $('file-preview').textContent = Array.from($('agent-files').files).map(f => f.name).join(' · ') || 'Each file is registered as a separate agent.'; };
  function base64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',')[1]);
      reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
      reader.onabort = () => reject(new Error(`Reading ${file.name} was cancelled.`));
      reader.readAsDataURL(file);
    });
  }
  $('upload-form').addEventListener('submit', async event => {
    event.preventDefault(); const files = Array.from($('agent-files').files), prefix = $('agent-name').value.trim();
    if (!files.length) return message('upload-status', 'Choose at least one .py or .zip file.', true);
    if (files.some(f => !/\.(py|zip)$/i.test(f.name))) return message('upload-status', 'Only .py and .zip files can be registered.', true);
    $('upload-button').disabled = true; $('agent-files').disabled = true;
    let success = 0; const failures = [];
    for (let i = 0; i < files.length; i++) {
      const file = files[i], stem = file.name.replace(/\.(py|zip)$/i, '');
      message('upload-status', `Registering ${i + 1}/${files.length}: ${file.name}`);
      try {
        await api('/api/agents', { name: prefix ? files.length === 1 ? prefix : `${prefix} · ${stem}` : stem, filename: file.name, content: await base64(file) }); success++;
      } catch (error) { failures.push(`${file.name}: ${error.message}`); }
    }
    message('upload-status', `${success}/${files.length} agents registered.${failures.length ? ` Failed files: ${failures.join(' | ')} Successful uploads are already saved; retry only failed files.` : ''}`, !!failures.length);
    $('agent-files').value = ''; $('file-preview').textContent = 'Each file is registered as a separate agent.';
    $('upload-button').disabled = false; $('agent-files').disabled = false; refresh();
  });
  $('run-form').addEventListener('submit', async event => {
    event.preventDefault();
    const agents = list(state.agents).filter(a => selected.has(String(a.id))).map(a => a.id);
    const seeds = [...new Set($('seeds').value.split(',').map(s => s.trim()).filter(Boolean))];
    const deals = Number($('deals-preset').value === 'custom' ? $('custom-deals').value : $('deals-preset').value);
    const parallelGames = Number($('parallel-games').value);
    if (!agents.length) return message('run-status', 'Select at least one registered agent.', true);
    if (!seeds.length) return message('run-status', 'Enter at least one seed.', true);
    if (!Number.isSafeInteger(deals) || deals < 1) return message('run-status', 'Hands must be a positive whole number.', true);
    const maxParallel = state.scheduler?.max_parallel_games || 16;
    if (!Number.isSafeInteger(parallelGames) || parallelGames < 1 || parallelGames > maxParallel) return message('run-status', `Parallel games must be a whole number from 1 to ${maxParallel}.`, true);
    $('queue-button').disabled = true;
    try {
      await api('/api/runs', { mode: document.querySelector('input[name="mode"]:checked').value, agents, seeds, deals, parallel_games: parallelGames, profile });
      message('run-status', 'Run queued. Follow its progress in the run queue below.'); refresh();
    } catch (error) { message('run-status', error.message, true); }
    finally { $('queue-button').disabled = false; }
  });
  $('tournament-run').onchange = renderTournament;
  function navigation() { document.querySelectorAll('nav a').forEach(a => a.classList.toggle('active', a.hash === (location.hash || '#overview'))); }
  window.addEventListener('hashchange', navigation); navigation();
  empty($('leaderboard'), 'Connecting to your arena', 'Loading benchmark results…');
  refresh(); setInterval(refresh, 2000);
})();
