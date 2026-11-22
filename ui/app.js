'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

// ---------- numbers and values

const ONES = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
  'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen'];
const TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'];
function below100(n) { return n < 20 ? ONES[n] : TENS[Math.floor(n / 10)] + (n % 10 ? '-' + ONES[n % 10] : ''); }
function below1000(n) {
  const h = Math.floor(n / 100), r = n % 100;
  return [h ? ONES[h] + ' hundred' : '', r ? (h ? 'and ' : '') + below100(r) : ''].filter(Boolean).join(' ');
}
// Indian grouping: crore, lakh, thousand.
function words(n) {
  n = Math.trunc(Number(n));
  if (!Number.isFinite(n) || n < 0) return '';
  if (n === 0) return 'zero';
  const parts = [];
  for (const [unit, name] of [[1e7, 'crore'], [1e5, 'lakh'], [1e3, 'thousand']]) {
    const k = Math.floor(n / unit); n %= unit;
    if (k) parts.push((k >= 100 ? words(k) : below100(k)) + ' ' + name);
  }
  if (n) parts.push(below1000(n));
  return parts.join(' ');
}
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;
const rupees = n => '₹' + Number(n).toLocaleString('en-IN');
function ordinal(d) { const s = ['th', 'st', 'nd', 'rd'], v = d % 100; return d + (s[(v - 20) % 10] || s[v] || s[0]); }
function due(v) {
  const day = v.weekday ? cap(v.weekday) : '', date = v.day_of_month ? 'the ' + ordinal(v.day_of_month) : '';
  return [day, date].filter(Boolean).join(', ') || '';
}
function show(slot, value) {
  if (value == null) return 'nothing';
  if (slot === 'amount_rupees') return rupees(value);
  if (slot === 'day_of_month') return 'the ' + ordinal(value);
  if (slot === 'weekday') return cap(value);
  return String(value);
}
const showAll = v => Object.entries(v || {}).map(([k, x]) => show(k, x)).join(', ') || 'no value';
const secs = ms => (ms / 1000).toFixed(1) + ' s';

// ---------- the slip

function amountCells(el, value, alt) {
  if (value == null) { el.innerHTML = '<span class="rs">₹</span>' + '<span class="cell empty">0</span>'.repeat(4); return; }
  const a = String(value), b = alt == null ? null : String(alt);
  const grouped = Number(value).toLocaleString('en-IN');
  let i = 0;
  el.innerHTML = '<span class="rs">₹</span>' + [...grouped].map(ch => {
    if (ch === ',') return '<span class="cell gap">,</span>';
    const k = i++;
    const doubt = b != null && (a.length !== b.length || a[k] !== b[k]);
    const hint = doubt && a.length === b.length ? ` data-alt="${esc(b[k])}"` : '';
    return `<span class="cell${doubt ? ' doubt' : ''}"${hint}>${esc(ch)}</span>`;
  }).join('');
}
function phoneCells(el, value, alt, positions) {
  const a = String(value ?? ''), b = alt == null ? null : String(alt);
  const marked = new Set(positions || []);
  if (b != null && a.length === b.length) [...a].forEach((ch, k) => { if (ch !== b[k]) marked.add(k); });
  const bad = a.length !== 10;
  el.innerHTML = [...a.padEnd(10, ' ')].slice(0, Math.max(10, a.length)).map((ch, k) => {
    const doubt = marked.has(k) || (b != null && a.length !== b.length) || (bad && b == null && value != null && marked.size === 0 && false);
    const hint = doubt && b && a.length === b.length && b[k] !== ch ? ` data-alt="${esc(b[k])}"` : '';
    return `<span class="cell${doubt ? ' doubt' : ''}${ch === ' ' ? ' empty' : ''}"${hint}>${ch === ' ' ? '0' : esc(ch)}</span>`;
  }).join('');
}
// doubts: {slot: {alt, positions}} for the slots the guard is not satisfied with.
function slip(side, values, doubts = {}) {
  const v = values || {}, root = $('slip' + side);
  root.classList.toggle('live', values != null);
  const hasPhone = v.phone != null, hasAmount = v.amount_rupees != null, hasDue = v.weekday != null || v.day_of_month != null;
  root.querySelectorAll('.row').forEach(r => {
    const s = r.dataset.slot;
    const on = values == null ? s !== 'phone' : (s === 'phone' ? hasPhone : s === 'due' ? hasDue || !hasPhone : hasAmount || !hasPhone);
    r.classList.toggle('off', !on);
  });
  const da = doubts.amount_rupees;
  amountCells($('fig' + side), v.amount_rupees, da && da.alt);
  const w = $('words' + side);
  w.classList.toggle('doubt', !!da);
  if (!hasAmount) w.innerHTML = '&nbsp;';
  else if (da && da.alt != null) w.textContent = `${cap(words(v.amount_rupees))}, or ${words(da.alt)}`;
  else w.textContent = cap(words(v.amount_rupees)) + ' rupees only';
  const d = $('day' + side), dd = doubts.weekday || doubts.day_of_month;
  d.classList.toggle('bad', !!dd);
  if (!hasDue) d.innerHTML = '&nbsp;';
  else {
    const altV = {...v};
    if (doubts.weekday && doubts.weekday.alt != null) altV.weekday = doubts.weekday.alt;
    if (doubts.day_of_month && doubts.day_of_month.alt != null) altV.day_of_month = doubts.day_of_month.alt;
    d.textContent = due(v) + (dd && due(altV) !== due(v) ? `, or ${due(altV)}` : '');
  }
  const dp = doubts.phone;
  phoneCells($('phone' + side), v.phone, dp && dp.alt, dp && dp.positions);
}
function status(side, html, held) { const el = $('st' + side); el.className = 'status' + (held ? ' held' : ''); el.innerHTML = html; }
function note(side, html) { const el = $('note' + side); el.innerHTML = html || ''; el.classList.toggle('on', !!html); }

// ---------- state for one call

const REASONS = {
  families_agree: 'independent recognisers agree with it',
  repaired: 'corrected to the value the recognisers and the acoustic check agree on',
  repaired_omission: 'added: the model left it out, the evidence agrees the caller said it',
  omitted: 'the model left out a value the recognisers agree the caller said',
  insufficient_families: 'too few independent recognisers support it',
  mismatch: 'the recognisers heard a different value',
  too_many_candidates: 'the recognisers disagree among themselves',
  malformed: 'it is not a valid value of its kind',
  no_evidence: 'no recogniser answered in time',
  proposed_unsupported: 'no recogniser supports the value the model proposed',
  witness_prefers_other: 'the acoustic check favours a different value',
  invented: 'no recogniser heard any such value in the audio',
  malformed_phone: 'the number is not a valid 10-digit mobile number',
  below_threshold: 'the evidence is too thin to act without asking',
  witness_absent: 'the acoustic check did not answer in time',
  too_few_families: 'too few independent recognisers answered in time',
};
const reason = code => REASONS[code] || String(code || '').replace(/_/g, ' ');

let S = null, health = {}, clips = [], current = null;
function fresh() {
  return {left: null, right: null, decision: null, evidence: null, proposedLatency: 0, ledger: [], asked: 0,
    truth: current ? current.truth : null, committed: null, awaiting: false, deadline: null, policy: ''};
}
function resetCall() {
  S = fresh();
  for (const s of ['L', 'R']) { slip(s, null); status(s, 'Waiting for the call'); note(s, ''); }
  $('askR').classList.remove('on'); $('ansBox').hidden = true;
  $('err').classList.remove('on');
  renderEvidence();
}

function doubtsFrom(decision) {
  const out = {};
  for (const s of (decision && decision.slots) || []) {
    if (s.verdict === 'pass') continue;
    const alt = (s.candidates || []).find(c => String(c) !== String(s.proposed));
    out[s.slot] = {alt: alt ?? null, positions: s.slot === 'phone' ? s.contested_positions : []};
  }
  return out;
}
function leftNote() {
  if (!S.left) return;
  const ref = S.truth || S.committed, label = S.truth ? 'The caller said' : 'After checking, the value was';
  if (!ref) return;
  const wrong = Object.keys(ref).filter(k => String(S.left.values[k] ?? '') !== String(ref[k] ?? ''));
  if (!wrong.length) return note('L', '');
  const k = wrong[0];
  const omitted = S.left.values[k] == null;
  const slotName = {amount_rupees: 'amount', phone: 'phone number', weekday: 'day', day_of_month: 'date'}[k] || 'value';
  const acted = omitted ? `Left out the ${slotName}` : `Logged ${esc(show(k, S.left.values[k]))}`;
  note('L', `<strong>${acted}. ${label} ${esc(show(k, ref[k]))}.</strong> Nothing in the model's output marked the value as uncertain, so nobody finds out until later.`);
  slip('L', S.left.values, Object.fromEntries(wrong.map(w => [w, {alt: ref[w], positions: []}])));
}

let offlineMode = false;
const handlers = {
  'session.ready'(e) {
    S.deadline = e.deadline_ms; S.policy = e.policy_hash;
    $('fake').classList.toggle('on', e.guard === 'fake');
    $('offline').classList.toggle('on', e.mode === 'offline-replay');
    status('L', 'Listening'); status('R', 'Listening');
  },
  'replay.clip'() { $('said').classList.add('playing'); },
  'turn.started'() { $('said').classList.add('playing'); if (!S.right) { status('L', 'Listening'); status('R', 'Listening'); } },
  'turn.ended'(e) {
    $('said').classList.remove('playing');
    if (S.awaiting) {
      $('ansBox').hidden = false; $('ansMeta').textContent = `Caller, ${secs(e.duration_ms)}`; $('ansText').textContent = '…';
      status('R', '<b>Held</b>, checking the answer', true);
    }
  },
  'left.committed'(e) {
    if (S.left) return;  // the bare agent's first action is the one being compared
    S.left = e; slip('L', e.values); status('L', `<b>Committed</b> in ${secs(e.latency_ms)}`); leftNote();
  },
  'right.proposed'(e) {
    S.right = e; if (!S.awaiting) S.proposedLatency = e.latency_ms;
    slip('R', e.values); status('R', '<b>Held</b>, checking', true);
  },
  'evidence'(e) {
    S.evidence = e;
    if (S.awaiting) { const h = (e.timings.find(t => t.heard && t.in_time) || {}).heard; if (h) $('ansText').textContent = h; }
    renderEvidence();
  },
  'decision'(e) {
    S.decision = e;
    if (e.verdict !== 'pass') {
      slip('R', e.proposed, doubtsFrom(e));
      const bad = e.slots.filter(s => s.verdict !== 'pass');
      note('R', bad.map(s => {
        const fam = (s.supporting_families || []).length;
        const alt = (s.candidates || []).find(c => String(c) !== String(s.proposed));
        return `<strong>${esc(show(s.slot, s.proposed))} is held:</strong> ${esc(reason(s.reason))}` +
          (alt != null ? `. The evidence points to ${esc(show(s.slot, alt))}` : '') +
          (fam ? `, with ${fam} independent ${fam === 1 ? 'family' : 'families'} behind the proposed value.` : '.');
      }).join('<br>'));
    }
    renderEvidence();
  },
  'question.asked'(e) {
    S.asked = e.n; S.awaiting = true;
    $('askR').classList.add('on'); $('askText').textContent = e.text; $('ansBox').hidden = true;
    status('R', '<b>Held</b>, asking the caller', true);
  },
  'right.committed'(e) {
    S.committed = e.values; S.awaiting = false;
    slip('R', e.values);
    const q = e.questions;
    status('R', q ? `<b>Committed</b> after ${q} question${q > 1 ? 's' : ''}, ${secs(e.total_ms)}`
      : `<b>Committed</b>, checked in ${secs(S.evidence ? S.evidence.waited_ms : 0)} after the tool call`);
    if (e.repaired_from && !q) status('R', `<b>Corrected and committed</b>, checked in ${secs(S.evidence ? S.evidence.waited_ms : 0)} after the tool call`);
    if (!q) note('R', S.decision ? S.decision.slots.map(s => `${esc(show(s.slot, s.final ?? s.proposed))}${s.final != null && s.proposed != null && s.final !== s.proposed ? ` (model proposed ${esc(show(s.slot, s.proposed))})` : ''}: ${esc(reason(s.reason))}`).join('<br>') : '');
    if (q) note('R', `<strong>${esc(showAll(e.values))}</strong>: confirmed by the caller's answer and the recognisers.`);
    leftNote(); renderEvidence();
  },
  'right.duplicate'() { status('R', '<b>Committed</b> already; a repeated tool call was not executed again'); },
  'right.voided'(e) {
    if (S.committed) return;
    status('R', `<b>Voided</b>, ${esc(reason(e.reason))}`, true); S.awaiting = false; renderEvidence();
  },
  'right.escalated'(e) {
    S.awaiting = false; status('R', `<b>Not committed</b>, passed to a person after ${e.questions} questions`, true); renderEvidence();
  },
  'ledger'(e) { S.ledger = e.transitions; renderEvidence(); },
  'agent.audio'(e) { play(e.audio, agentQ); },
  'agent.flush'() { flush(agentQ); },
  'caller.audio'(e) { level(play(e.audio, callerQ)); },
  'replay.done'() { endCall(); },
  'error'(e) { $('err').textContent = e.message; $('err').classList.add('on'); },
};

// ---------- evidence view

function renderEvidence() {
  const ev = S && S.evidence, dec = S && S.decision;
  $('evEmpty').hidden = !!ev; $('evCols').hidden = !ev;
  if (!ev) return;
  const verdict = dec ? dec.verdict : '';
  $('evTitle').textContent = verdict === 'pass' ? 'Why the action went through' : verdict === 'block' ? 'Why the action was stopped' : 'Why the action was held';
  const proposed = dec ? dec.proposed : (S.right || {}).values;
  $('evLede').textContent = `The model proposed ${showAll(proposed)}. Each recogniser listened to the same audio separately, and none of them was told what the model had proposed.`;
  const badSlots = new Set(((dec && dec.slots) || []).filter(s => s.verdict !== 'pass').map(s => s.slot));
  const agentVal = Object.entries(proposed || {}).map(([k, v]) => `<span class="${badSlots.has(k) ? 'bad' : ''}">${esc(show(k, v))}</span>`).join(' · ');
  const rows = [`<tr><td>Realtime model<small>The agent, proposing the action</small></td><td>none given</td><td class="heard">${agentVal}</td><td class="n late">not exposed</td></tr>`];
  for (const t of ev.timings) {
    const late = !t.in_time;
    rows.push(`<tr><td class="${late ? 'late' : ''}">${esc(t.source)}<small>${esc(t.family)}</small></td>` +
      (late ? '<td class="late">arrived after the decision</td><td class="late">not counted</td><td class="n late"></td>'
        : `<td>${esc(t.heard) || '<span class="late">no transcript</span>'}</td><td class="heard">${esc(showAll(t.values))}</td><td class="n${t.confidence && t.confidence !== 'not exposed' ? '' : ' late'}">${esc(t.confidence || 'not exposed')}</td>`) + '</tr>');
  }
  $('evRows').innerHTML = rows.join('');

  // Latencies run from the end of the caller's turn; the decision lands at tool call + guard wait.
  const decideAt = S.proposedLatency + (ev.waited_ms ?? ev.decided_after_ms ?? 0);
  const max = Math.max(decideAt * 1.25, ...ev.timings.map(t => t.latency_ms * 1.05), 800);
  const lanes = ev.timings.map(t => `<div class="lane"><span>${esc(t.source)}</span><div class="track"><b class="${t.in_time ? '' : 'late'}" style="left:0;width:${(100 * t.latency_ms / max).toFixed(1)}%"></b></div></div>`);
  lanes.push(`<div class="lane"><span>Model's tool call</span><div class="track"><b class="self" style="left:${(100 * S.proposedLatency / max).toFixed(1)}%;width:3px"></b></div></div>`);
  $('fall').style.setProperty('--f', (decideAt / max).toFixed(4));
  $('fall').innerHTML = lanes.join('') + `<div class="deadline"><em>Decision at ${secs(decideAt)}</em></div>`;
  $('axis').innerHTML = [0, .25, .5, .75, 1].map(f => `<span>${f ? secs(max * f) : '0'}</span>`).join('');

  const kv = [];
  if (dec) {
    const outcome = S.committed ? `Committed as ${showAll(S.committed)}${S.asked ? ` after ${S.asked} question${S.asked > 1 ? 's' : ''}` : ' without asking'}`
      : dec.verdict === 'pass' ? 'Passed' : dec.verdict === 'ask' ? 'Held, one question to the caller' : 'Stopped, caller asked to repeat';
    kv.push(['Decision', esc(outcome)]);
    for (const s of dec.slots) {
      const llr = s.witness_llr == null ? '' : `; acoustic check ${s.witness_llr >= 0 ? 'for' : 'against'} it, ${Math.abs(s.witness_llr).toFixed(1)} nats`;
      kv.push([esc(show(s.slot, s.proposed)), `${esc(reason(s.reason))}; score ${Number(s.score).toFixed(2)}${llr}`]);
    }
  }
  kv.push(['Added to the call', `${secs(ev.waited_ms ?? 0)} to decide after the tool call` + (S.deadline ? `, limit ${secs(S.deadline)}` : '')]);
  if (ev.absent_sources && ev.absent_sources.length) kv.push(['Not counted', esc(ev.absent_sources.join(', '))]);
  kv.push(['Record', `bundle ${esc(ev.bundle_id || 'none')}, policy ${esc(ev.policy_hash || S.policy || 'none')}, audio kept by reference`]);
  $('kv').innerHTML = kv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
  $('steps').innerHTML = (S.ledger || []).map(t => `<li class="${esc(t.state)}">${esc(t.state)}</li>`).join('') || '<li>no entry yet</li>';
}

// ---------- results view

const DASH = ['', '6 4', '2 4', '10 4 2 4', '1 5', '8 3'];
function renderResults(r) {
  $('resEmpty').hidden = !!r; $('resBody').hidden = !r;
  if (!r) return;
  const ds = r.dataset || {}, arms = r.arms || [];
  $('resTitle').textContent = `The same ${ds.n_actions ?? ''} recorded calls, ${arms.length} ways`.replace('  ', ' ');
  const kind = ds.kind === 'synthetic-tts' ? 'These are synthetic voices, not people; treat the numbers as a system check, not a field result. '
    : ds.kind === 'human-recorded' ? `Recorded from ${ds.n_speakers === 1 ? 'one person' : (ds.n_speakers ?? 'several') + ' people'}, scored on the policy frozen beforehand.${ds.n_actions < 100 ? ' Too few calls to rank the approaches.' : ''} ` : '';
  $('resLede').textContent = kind + 'Each row scales its calls to 100 dots. A red dot is a wrong value that was acted on without anyone being asked.' +
    (ds.condition ? ` Audio: ${ds.condition}.` : '');
  const pct = (k, n) => n ? Math.round(100 * k / n) : 0;
  $('arms').innerHTML = '<div class="arm head"><span>Approach</span><span></span><span style="text-align:right">Wrong, unnoticed</span><span style="text-align:right">Caller time added</span></div>' +
    arms.map(a => {
      const wrong = pct(a.wrong_silent ?? 0, a.n), asked = Math.min(pct(a.asked ?? 0, a.n), 100 - wrong);
      const kinds = Array.from({length: 100}, (_, i) => i < wrong ? 'w' : i < wrong + asked ? 'q' : '');
      const order = kinds.map((k, i) => [(i * 37 + 11) % 100, k]).sort((x, y) => x[0] - y[0]).map(x => x[1]);
      const cs = a.caller_seconds;
      return `<div class="arm${a.ours ? ' ours' : ''}">
        <div><h3>${esc(a.name || a.id)}</h3><p>${esc(a.how || '')}</p></div>
        <div class="dots" role="img" aria-label="${a.wrong_silent ?? 0} of ${a.n ?? 0} wrong and unnoticed, ${a.asked ?? 0} asked">${order.map(k => `<i class="${k}"></i>`).join('')}</div>
        <div class="fig${wrong > 5 ? ' bad' : ''}">${a.wrong_silent ?? '–'}<small>of ${a.n ?? '–'}</small></div>
        <div class="fig${cs == null ? ' na' : ''}">${cs == null ? 'not measured' : Number(cs).toFixed(1) + '<small>s</small>'}</div></div>`;
    }).join('');

  const c = r.certificate;
  $('cert').hidden = !c;
  if (c) {
    $('certBig').textContent = c.upper_bound == null ? '–' : `≤ ${(100 * c.upper_bound).toFixed(1)}%`;
    const conf = Math.round(100 * (c.confidence ?? 0.95));
    $('certText').innerHTML = `<strong>Of the ${c.n_accepted} actions let through without asking, ${c.k_wrong} ${c.k_wrong === 1 ? 'was' : 'were'} wrong.</strong> ` +
      `With ${conf}% confidence the true rate is at most ${c.upper_bound == null ? 'unknown' : (100 * c.upper_bound).toFixed(1) + '%'}, for callers like the ${c.n_speakers ?? ds.n_speakers ?? ''} ${ds.kind === 'synthetic-tts' ? 'synthetic voices' : 'people'} recorded here. ` +
      (c.speaker_level_bound != null ? `Counting each speaker once, the bound is ${(100 * c.speaker_level_bound).toFixed(1)}%. ` : '') +
      'This covers decisions made without asking; calls where the caller was asked are counted separately.' +
      (r.policy_hash ? ` Policy ${esc(r.policy_hash)}.` : '');
  }

  const rc = r.risk_coverage || {}, ids = Object.keys(rc).filter(k => (rc[k] || []).length);
  $('curveBox').hidden = !ids.length;
  if (ids.length) {
    const W = 720, H = 300, L = 48, B = 36, T = 12, R = 12;
    const maxY = Math.max(0.06, ...ids.flatMap(k => rc[k].map(p => p[1]))) * 1.1;
    const x = c => L + (W - L - R) * c, y = v => H - B - (H - B - T) * (v / maxY);
    const ours = new Set(arms.filter(a => a.ours).map(a => a.id));
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Risk against coverage for each gated approach">`;
    for (const f of [0, .25, .5, .75, 1]) svg += `<line x1="${x(f)}" x2="${x(f)}" y1="${T}" y2="${H - B}" stroke="var(--line)"/><text x="${x(f)}" y="${H - 12}" text-anchor="middle">${Math.round(f * 100)}%</text>`;
    for (let i = 0; i <= 4; i++) { const v = maxY * i / 4; svg += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${(100 * v).toFixed(0)}%</text>`; }
    svg += `<line x1="${L}" x2="${W - R}" y1="${y(0.05)}" y2="${y(0.05)}" stroke="var(--doubt)" stroke-dasharray="3 4"/><text x="${W - R}" y="${y(0.05) - 6}" text-anchor="end" style="fill:var(--doubt)">5% target</text>`;
    const legend = [];
    ids.forEach((id, i) => {
      const mine = ours.has(id), pts = [...rc[id]].sort((a, b) => a[0] - b[0]).map(p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
      const dash = mine ? '' : DASH[1 + (i % (DASH.length - 1))];
      svg += `<polyline points="${pts}" fill="none" stroke="${mine ? 'var(--ink)' : 'var(--ink-3)'}" stroke-width="${mine ? 2.5 : 1.5}" stroke-dasharray="${dash}" stroke-linejoin="round"/>`;
      const name = (arms.find(a => a.id === id) || {}).name || id;
      legend.push(`<span><svg width="28" height="10"><line x1="0" x2="28" y1="5" y2="5" stroke="${mine ? 'var(--ink)' : 'var(--ink-3)'}" stroke-width="${mine ? 2.5 : 1.5}" stroke-dasharray="${dash}"/></svg>${esc(name)}</span>`);
    });
    $('curve').innerHTML = svg + '</svg>';
    $('curveLegend').innerHTML = legend.join('');
  }

  const abl = r.ablations || [];
  $('ablBox').hidden = !abl.length;
  $('abl').innerHTML = abl.map(a => `<tr><td>${esc(a.name)}</td><td class="n">${a.wrong_silent ?? '–'} of ${a.n ?? '–'}</td><td class="n">${a.asked ?? '–'}</td></tr>`).join('');
  const sh = Object.entries(r.shapley || {});
  $('shapBox').hidden = !sh.length;
  const top = Math.max(...sh.map(([, v]) => Math.abs(v)), 1e-9);
  $('shap').innerHTML = sh.map(([k, v]) => `<div class="lane"><span>${esc(k)}</span><div class="track"><b style="left:0;width:${(100 * Math.abs(v) / top).toFixed(1)}%"></b></div></div>`).join('');
}

function renderAnalysis(a) {
  $('analysis').hidden = !a;
  if (!a) return;
  const tile = (n, label, bad) => `<div><b${bad ? ' class="bad"' : ''}>${n}</b><span>${esc(label)}</span></div>`;
  const fate = a.agent_errors.fate;
  $('fate').innerHTML = tile(a.agent_errors.n, 'wrong values proposed') +
    Object.entries(fate).map(([k, v]) => tile(v, k, k.startsWith('acted'))).join('');
  const q = a.questions;
  $('qBox').hidden = !q;
  if (q) {
    $('qOut').innerHTML = tile(q.n, 'asked calls replayed live') +
      Object.entries(q.outcomes).map(([k, v]) => tile(v, k.replace(/_/g, ' '), k === 'committed_wrong')).join('');
    $('qNote').textContent = `The answers are synthetic and cooperative: ${q.answers.split(': ')[1] || q.answers}. ${q.questions_per_action_mean} questions per asked call on average.`;
  }
  const names = {'B-2M': 'gpt-transcribe vs VerbX', 'B-2S': 'gpt-transcribe vs Sarvam'};
  $('matched').innerHTML = Object.entries(a.matched).map(([k, m]) => `<tr><td>${esc(names[k] || k)}</td><td class="n">${m.baseline_wrong} wrong, ${m.baseline_asked} asked</td>` +
    `<td class="n">${m.pramaan_asked_there == null ? 'not reachable' : `${m.pramaan_wrong_at_no_more_questions} wrong, ${m.pramaan_asked_there} asked`}</td>` +
    `<td class="n">${m.pramaan_asked_at_no_more_errors == null ? 'not reachable' : `${m.pramaan_wrong_there} wrong, ${m.pramaan_asked_at_no_more_errors} asked`}</td></tr>`).join('');
  const lang = {hi: 'Hindi and Hinglish', en: 'English'};
  const two = arm => arm ? `${arm.wrong_silent} / ${arm.asked}` : '–';
  $('slices').innerHTML = Object.entries(a.by.language).map(([k, v]) => `<tr><td>${esc(lang[k] || k)}</td><td class="n">${v.n}</td><td class="n">${two(v['B-2S'])}</td><td class="n">${two(v.P)}</td></tr>`).join('') +
    Object.entries(a.vendor_outage).map(([k, v]) => `<tr><td>Without ${esc(k)}</td><td class="n">${a.n}</td><td class="n">${k === 'VerbX' ? 'unaffected' : 'cannot run'}</td><td class="n">${two(v)}</td></tr>`).join('');
  const c = a.cost;
  $('costLine').textContent = c ? `Checking one action costs about $${(c.usd_per_1000_actions / 1000).toFixed(4)} in recogniser calls at list prices (${c.as_of}); ${c.note}.` : '';
}

// ---------- audio

let ctx = null, ws = null, micStream = null, micNode = null;
const agentQ = {next: 0, nodes: new Set()}, callerQ = {next: 0, nodes: new Set()};
function audio() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)({sampleRate: 24000});
  if (ctx.state === 'suspended') ctx.resume().catch(() => {});
  return ctx;
}
function play(b64, q) {
  const bin = atob(b64), n = bin.length >> 1, f = new Float32Array(n);
  for (let i = 0; i < n; i++) { let v = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8); if (v & 0x8000) v -= 0x10000; f[i] = v / 32768; }
  try {
    const c = audio(), buf = c.createBuffer(1, n, 24000);
    buf.copyToChannel(f, 0);
    const src = c.createBufferSource();
    src.buffer = buf; src.connect(c.destination);
    // A small lead keeps network jitter from opening gaps between chunks.
    const at = Math.max(c.currentTime + 0.08, q.next);
    src.start(at); q.next = at + buf.duration;
    q.nodes.add(src); src.onended = () => q.nodes.delete(src);
  } catch (e) { /* playback is best effort; the event stream still drives the page */ }
  return f;
}
function flush(q) { for (const s of q.nodes) { try { s.stop(); } catch (e) { /* already stopped */ } } q.nodes.clear(); q.next = 0; }

const BARS = 26, levels = new Array(BARS).fill(0);
$('wave').innerHTML = '<i></i>'.repeat(BARS);
function level(f) {
  let sum = 0; for (let i = 0; i < f.length; i++) sum += f[i] * f[i];
  levels.push(Math.min(1, Math.sqrt(sum / Math.max(f.length, 1)) * 6)); levels.shift();
  [...$('wave').children].forEach((el, i) => { el.style.height = (4 + levels[i] * 36).toFixed(0) + 'px'; });
}

// ---------- call control

function connect(query) {
  resetCall();
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws${query}`);
  ws.binaryType = 'arraybuffer';
  ws.onmessage = m => { const e = JSON.parse(m.data); (handlers[e.type] || (() => {}))(e); };
  ws.onclose = () => endCall();
  ws.onerror = () => handlers.error({message: 'The connection to the server dropped.'});
  return ws;
}
function endCall() {
  if (micNode) { micNode.disconnect(); micNode = null; }
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
  if (ws) { const w = ws; ws = null; try { w.close(); } catch (e) { /* closing twice is fine */ } }
  $('mic').classList.remove('live'); $('micLabel').textContent = offlineMode ? 'Microphone needs the network' : 'Start a call';
  $('replay').disabled = !$('clip').value; $('mic').disabled = offlineMode;
  $('said').classList.remove('playing');
}
async function startMic() {
  current = null;
  $('quote').firstChild.textContent = 'Listening to you';
  $('quoteSub').textContent = 'Say an amount, a date or a phone number. Use a headset so the agent does not hear itself.';
  try {
    micStream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, channelCount: 1}});
    const c = audio();
    await c.audioWorklet.addModule('capture-worklet.js');
    const sock = connect('');
    micNode = new AudioWorkletNode(c, 'capture');
    micNode.port.onmessage = m => {
      const f = m.data, pcm = new Int16Array(f.length);
      for (let i = 0; i < f.length; i++) pcm[i] = Math.max(-1, Math.min(1, f[i])) * 32767;
      if (sock.readyState === 1) sock.send(pcm.buffer);
      level(f);
    };
    c.createMediaStreamSource(micStream).connect(micNode);
    $('mic').classList.add('live'); $('micLabel').textContent = 'End the call'; $('replay').disabled = true;
  } catch (e) {
    endCall(); handlers.error({message: `Could not open the microphone: ${e.message}`});
  }
}
$('mic').addEventListener('click', () => (ws ? endCall() : startMic()));
function playClip(id, answer, meta) {
  if (ws) endCall();
  audio();
  current = meta || clips.find(c => c.clip_id === id) || null;
  $('quote').firstChild.textContent = current && current.say ? `“${current.say}”` : id;
  $('quoteSub').textContent = current && current.truth ? `Recorded call. The caller's actual words mean ${showAll(current.truth)}` : 'Recorded call';
  connect(`?replay=${encodeURIComponent(id)}${answer === '-' ? '' : ',' + encodeURIComponent(answer || id)}`);
  $('replay').disabled = true; $('mic').disabled = true;
}
$('replay').addEventListener('click', () => { if ($('clip').value) playClip($('clip').value, $('answer').value); });
$('clip').addEventListener('change', () => { $('replay').disabled = !$('clip').value || !!ws; });

document.querySelectorAll('[role=tab]').forEach(t => t.addEventListener('click', () => {
  document.querySelectorAll('[role=tab]').forEach(x => x.setAttribute('aria-selected', x === t));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === t.dataset.view));
  if (t.dataset.view === 'results') loadResults();
}));

function showView(name) { document.querySelector(`[role=tab][data-view=${name}]`).click(); }
function dotGrid(wrong, asked, n) {
  const w = Math.round(100 * wrong / n), q = Math.min(Math.round(100 * asked / n), 100 - w);
  const kinds = Array.from({length: 100}, (_, i) => i < w ? 'w' : i < w + q ? 'q' : '');
  return kinds.map((k, i) => [(i * 37 + 11) % 100, k]).sort((x, y) => x[0] - y[0]).map(x => `<i class="${x[1]}"></i>`).join('');
}
async function loadOverview() {
  const get = u => fetch('/api/' + u).then(x => x.ok ? x.json() : null).catch(() => null);
  const [strong, fresh, first, human, a, sc] = await Promise.all([get('results?set=strong'), get('results?set=fresh2').then(x => x || get('results?set=fresh')), get('results?set=synthetic'), get('results?set=human'), get('analysis'), get('scenarios')]);
  const r = strong || fresh || first;
  if (r) {
    const arm = id => r.arms.find(x => x.id === id), A = arm('A'), P = arm('P'), pc = (k, n) => (100 * k / n).toFixed(1) + '%';
    $('ba').hidden = false;
    $('baBefore').innerHTML = `${pc(A.wrong_silent, A.n)}<small>wrong</small>`;
    $('baBeforeText').textContent = `Acted on a wrong amount, date or phone number in ${A.wrong_silent} of ${A.n} calls. Nobody was asked; nothing flagged it.`;
    $('baAfter').innerHTML = `${pc(P.wrong_silent, P.n)}<small>wrong</small>`;
    $('baAfterText').textContent = `${P.wrong_silent} of ${P.n} calls. The caller was asked one short question on ${P.asked} (${pc(P.asked, P.n)}); the rest went through or were corrected silently.`;
    $('baBeforeDots').innerHTML = dotGrid(A.wrong_silent, 0, A.n);
    $('baAfterDots').innerHTML = dotGrid(P.wrong_silent, P.asked, P.n);
    const c = r.certificate, ds = r.dataset;
    $('baNote').textContent = `The same ${ds.n_actions} recorded calls on both sides, from ${ds.n_speakers} held-out synthetic voices over a phone channel` +
      (strong ? ', with an agent prompted specifically for Indian numbers, on the frozen policy' : fresh ? ', scored once after the policy was frozen' : '') + `. With 95% confidence, at most ${(100 * c.upper_bound).toFixed(1)}% of actions let through are wrong.` +
      (human ? ` Recorded people so far: ${human.dataset.n_speakers}, ${human.dataset.n_actions} calls (see Results).` : ' No recordings of people yet.');
  }
  if (a) {
    const tile = (n, label, bad) => `<div><b${bad ? ' class="bad"' : ''}>${n}</b><span>${esc(label)}</span></div>`;
    const f = a.agent_errors.fate, q = a.questions;
    $('flow').hidden = false;
    $('flowTiles').innerHTML = tile(a.agent_errors.n, `wrong values proposed in ${a.n} calls`) + tile(f['repaired to the true value'] ?? 0, 'corrected without asking') +
      tile(f['caller asked'] ?? 0, 'held for a question') + tile(f['acted on, wrong'] ?? 0, 'got through', true) +
      (q ? tile(`${q.outcomes.committed_right ?? 0} of ${q.n}`, 'asked calls ended with the right value') : '');
  }
  $('cards').innerHTML = (sc || []).map((s, i) => `<article class="card"><h3>${esc(s.title)}</h3><p class="said" lang="hi">“${esc(s.say)}”</p>
    <dl><dt>Model alone</dt><dd class="bad">${esc(s.alone)}</dd><dt>With Pramaan</dt><dd>${esc(s.guarded)} · ${esc(s.outcome)}</dd></dl>
    <p class="why">${esc(s.note)}</p><button class="ghost" data-scenario="${i}">Play this call</button></article>`).join('');
  document.querySelectorAll('[data-scenario]').forEach(b => b.addEventListener('click', () => {
    const s = sc[+b.dataset.scenario];
    showView('call');
    playClip(s.id, s.answer || '-', {clip_id: s.id, say: s.say, truth: s.truth});
  }));
}
$('goLive').addEventListener('click', () => showView('call'));

let resultSet = 'synthetic';
async function loadResults() {
  try {
    const [r, f, f2, h, a] = await Promise.all(['results?set=synthetic', 'results?set=fresh', 'results?set=fresh2', 'results?set=human', 'analysis'].map(s => fetch('/api/' + s).then(x => x.ok ? x.json() : null)));
    const sets = {synthetic: r, fresh: f, fresh2: f2, human: h};
    $('sets').hidden = !f && !f2 && !h;
    document.querySelectorAll('#sets button').forEach(b => { if (b.dataset.set !== 'synthetic') b.hidden = !sets[b.dataset.set]; });
    renderResults(sets[resultSet] || r);
    renderAnalysis(resultSet === 'synthetic' ? a : null);
  } catch (e) { renderResults(null); renderAnalysis(null); }
}
document.querySelectorAll('#sets button').forEach(b => b.addEventListener('click', () => {
  resultSet = b.dataset.set;
  document.querySelectorAll('#sets button').forEach(x => x.setAttribute('aria-pressed', x === b));
  loadResults();
}));
async function boot() {
  resetCall();
  loadOverview();
  try {
    health = await (await fetch('/api/health')).json();
    const ok = health.offline || (health.key_present && health.model_reachable);
    offlineMode = !!health.offline;
    if (offlineMode) { $('mic').disabled = true; $('micLabel').textContent = 'Microphone needs the network'; }
    $('chip').className = 'chip ' + (ok ? 'ok' : 'bad');
    $('chipText').textContent = health.offline ? 'Offline replay: recorded answers' : !health.key_present ? 'No OpenAI key on the server' : !health.model_reachable ? `${health.model} is not reachable` : `${health.model} ready`;
    $('fake').classList.toggle('on', health.guard === 'fake');
  } catch (e) { $('chip').className = 'chip bad'; $('chipText').textContent = 'Server not reachable'; }
  try {
    clips = await (await fetch('/api/clips')).json();
    const groups = new Map();
    for (const c of clips) {
      if (c.condition === 'clean') continue;
      if (!groups.has(c.speaker)) groups.set(c.speaker, []);
      groups.get(c.speaker).push(c);
    }
    $('clip').insertAdjacentHTML('beforeend', [...groups].map(([speaker, list]) =>
      `<optgroup label="${esc(speaker)}">` + list.map(c =>
        `<option value="${esc(c.clip_id)}">${esc(c.truth ? showAll(c.truth) : c.clip_id)}${c.condition && c.condition !== 'phone' ? ' (' + esc(c.condition) + ')' : ''}</option>`).join('') + '</optgroup>').join(''));
    const want = new URLSearchParams(location.search).get('clip');
    if (want && clips.some(c => c.clip_id === want)) { $('clip').value = want; $('replay').disabled = false; showView('call'); }
  } catch (e) { /* the page still works with the microphone */ }
  if (location.hash === '#call') showView('call');
  if (location.hash === '#results') document.querySelector('[data-view=results]').click();
  if (location.hash === '#evidence') document.querySelector('[data-view=evidence]').click();
}
boot();
