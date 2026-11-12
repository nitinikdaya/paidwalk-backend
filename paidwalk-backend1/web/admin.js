/* PaidWalk admin dashboard. Uses the same sign-in as the app; the server enforces roles on every call. */
'use strict';
const $ = (s) => document.querySelector(s), app = $('#app'), token = localStorage.getItem('pw_token');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const rs = (p) => '₹' + (p / 100).toLocaleString('en-IN'), num = (n) => Number(n).toLocaleString('en-IN');
function toast(m, err) { const el = $('#toast'); el.textContent = m; el.className = err ? 'err' : ''; el.hidden = false; setTimeout(() => (el.hidden = true), 4000); }
async function api(method, path, body) {
  const r = await fetch('/api/admin' + path, { method, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token }, body: body ? JSON.stringify(body) : undefined });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((d.error && d.error.message) || 'Request failed');
  return d;
}
const table = (heads, rows) => rows.length ? `<div class="scroll"><table><tr>${heads.map((h) => `<th>${h}</th>`).join('')}</tr>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</table></div>` : '<p class="small sub">Nothing here.</p>';
const btn = (label, act, id, extra = '') => `<button class="btn ghost mini" data-act="${act}" data-id="${id}" ${extra}>${label}</button>`;

async function load() {
  if (!token) { app.innerHTML = '<div class="card empty"><h2>Sign in first</h2><a class="btn" href="/">Open PaidWalk</a></div>'; return; }
  try {
    const [o, b, c, f, w, ap, u] = await Promise.all([api('GET', '/overview'), api('GET', '/budgets'), api('GET', '/config'), api('GET', '/flags'), api('GET', '/withdrawals'), api('GET', '/appeals'), api('GET', '/users')]);
    const stat = (l, v) => `<div class="card col"><span class="tiny sub"><b>${l}</b></span><span class="num" style="font-size:24px">${v}</span></div>`;
    const over = o.liabilities_paise > o.funded_paise;
    app.innerHTML = `<header class="row between"><h1>PaidWalk admin</h1><a class="btn ghost mini" href="/">Back to app</a></header>
      <div class="stats">${stat('Registered users', num(o.users))}${stat('Active today', num(o.daily_active))}${stat('Active, 30 days', num(o.monthly_active))}${stat('Verified steps today', num(o.verified_steps_today))}
        ${stat('Reward liabilities', rs(o.liabilities_paise))}${stat('Funded budget', rs(o.funded_paise))}${stat('Budget left today', rs(o.budget_remaining_paise))}${stat('Withdrawals waiting', num(o.pending_withdrawals))}${stat('Withdrawals done', num(o.completed_withdrawals))}${stat('Open fraud flags', num(o.open_flags))}</div>
      ${over ? '<div class="card" style="border-color:#FF2D3F">Liabilities are above the funded budget. Check budgets.</div>' : ''}
      <section class="card col"><h2>Reward budgets (campaigns)</h2>${table(['Name', 'Funded', 'Spent', 'From', 'To', 'Active', ''], b.budgets.map((x) => [esc(x.name), rs(x.funded_paise), rs(x.spent_paise), x.starts, x.ends, x.active ? 'yes' : 'no', btn(x.active ? 'Pause' : 'Resume', 'budget', x.id, `data-on="${x.active ? 0 : 1}"`)]))}
        <div class="row" style="flex-wrap:wrap"><input id="bn" class="input" style="flex:2 1 160px;height:44px" placeholder="Campaign name"><input id="bf" class="input" style="flex:1 1 110px;height:44px" inputmode="numeric" placeholder="Amount ₹"><input id="bs" class="input" style="flex:1 1 140px;height:44px" type="date" aria-label="Starts"><input id="be" class="input" style="flex:1 1 140px;height:44px" type="date" aria-label="Ends">${btn('Add funded budget', 'add-budget', 0)}</div>
        <p class="tiny dim">Only add money you actually hold for rewards. Rewards stop automatically when a budget is used up.</p></section>
      <section class="card col"><h2>Withdrawals</h2>${table(['#', 'User', 'Risk', 'Amount', 'UPI', 'Status', 'Actions'], w.withdrawals.map((x) => [x.id, esc(x.display_name), x.risk_score, rs(x.amount_paise), esc(x.upi), esc(x.status) + (x.provider_ref ? ' · ' + esc(x.provider_ref) : ''),
        x.status === 'requested' ? btn('Approve', 'wd', x.id, 'data-a="approve"') + ' ' + btn('Reject', 'wd', x.id, 'data-a="reject"') : x.status === 'approved' ? btn('Mark paid', 'wd', x.id, 'data-a="mark_paid"') + ' ' + btn('Reject', 'wd', x.id, 'data-a="reject"') : '']))}</section>
      <section class="card col"><h2>Fraud review queue</h2>${table(['#', 'User', 'Risk', 'Signal', 'Detail', 'Day', 'Decision'], f.flags.map((x) => [x.id, esc(x.display_name), x.risk_score, esc(x.signal), esc(x.detail), x.day, btn('Clear', 'flag', x.id, 'data-s="cleared"') + ' ' + btn('Confirm', 'flag', x.id, 'data-s="confirmed"')]))}
        <p class="tiny dim">Confirming keeps the points on the user's risk score. Nobody is banned automatically; banning is a separate manual step below.</p></section>
      <section class="card col"><h2>Appeals</h2>${table(['#', 'User', 'Risk', 'Message', ''], ap.appeals.map((x) => [x.id, esc(x.display_name), x.risk_score, esc(x.message), btn('Close', 'appeal', x.id)]))}</section>
      <section class="card col"><h2>Users (highest risk first)</h2>${table(['#', 'Name', 'District', 'Role', 'Risk', 'Status', 'Actions'], u.users.map((x) => [x.id, esc(x.display_name || '(setup pending)'), esc(x.district || ''), x.role, x.risk_score, x.status,
        btn(x.status === 'banned' ? 'Unban' : 'Ban', 'user', x.id, `data-k="status" data-v="${x.status === 'banned' ? 'active' : 'banned'}"`) + ' ' + btn('Void held rewards', 'user', x.id, 'data-k="void_held" data-v="1"')]))}</section>
      <section class="card col"><h2>Reward settings</h2><p class="tiny dim">Money is in paise (100 = ₹1). tiers = [[verified steps, paise]].</p><textarea id="cfg" class="input" rows="14" style="font-family:monospace;font-size:13px">${esc(JSON.stringify(c, null, 1))}</textarea><div class="row">${btn('Save settings', 'save-cfg', 0)}${btn('Run nightly settle now', 'settle', 0)}</div></section>`;
  } catch (e) { app.innerHTML = `<div class="card empty"><h2>No access</h2><p class="small sub">${esc(e.message)}</p><a class="btn ghost" href="/">Back to app</a></div>`; }
}
const acts = {
  'add-budget': () => api('POST', '/budgets', { name: $('#bn').value, funded_paise: Math.round(parseFloat($('#bf').value || '0') * 100), starts: $('#bs').value, ends: $('#be').value }),
  budget: (el) => api('POST', `/budgets/${el.dataset.id}/active`, { active: el.dataset.on === '1' }),
  wd: (el) => { const note = el.dataset.a === 'approve' ? '' : prompt(el.dataset.a === 'mark_paid' ? 'Payment provider reference' : 'Reason for rejection') || ''; return api('POST', `/withdrawals/${el.dataset.id}/${el.dataset.a}`, { note }); },
  flag: (el) => api('POST', `/flags/${el.dataset.id}/resolve`, { status: el.dataset.s }),
  appeal: (el) => api('POST', `/appeals/${el.dataset.id}/close`, {}),
  user: (el) => confirm('Apply this change to user #' + el.dataset.id + '?') ? api('POST', `/users/${el.dataset.id}`, { [el.dataset.k]: el.dataset.k === 'void_held' ? true : el.dataset.v }) : null,
  'save-cfg': () => api('PUT', '/config', JSON.parse($('#cfg').value)),
  settle: () => api('POST', '/settle', {})
};
document.addEventListener('click', async (e) => { const el = e.target.closest('[data-act]'); if (!el) return; try { const r = await acts[el.dataset.act](el); if (r) { toast('Done.'); load(); } } catch (err) { toast(err.message, true); } });
load();
