/* PaidWalk web app. All numbers come from the server; nothing here is trusted for rewards. */
'use strict';
const $ = (s) => document.querySelector(s);
const app = $('#app'), nav = $('#nav');
const S = { token: localStorage.getItem('pw_token'), user: null, cfg: null, lang: localStorage.getItem('pw_lang') || 'en', lb: { scope: 'district', period: 'daily', metric: 'steps' } };
const deviceId = localStorage.getItem('pw_device') || (() => { const d = 'web-' + crypto.randomUUID(); localStorage.setItem('pw_device', d); return d; })();

const HI = { 'Home': 'होम', 'Ranks': 'रैंक', 'Wallet': 'वॉलेट', 'Invite': 'आमंत्रण', 'Profile': 'प्रोफ़ाइल', 'Namaste,': 'नमस्ते,', 'Today · verified': 'आज · सत्यापित',
  'steps': 'कदम', 'Walking': 'पैदल', 'Running': 'दौड़', 'Earned today': 'आज की कमाई', 'Available to withdraw': 'निकासी के लिए उपलब्ध', 'Active streak': 'लगातार दिन',
  'days': 'दिन', 'Start walking': 'चलना शुरू करें', 'Withdraw to UPI': 'UPI में निकालें', 'Available balance': 'उपलब्ध राशि', 'Pending': 'लंबित', 'On hold': 'रोकी गई',
  'Lifetime': 'कुल कमाई', 'Leaderboard': 'लीडरबोर्ड', 'District': 'ज़िला', 'State': 'राज्य', 'National': 'राष्ट्रीय', 'Daily': 'दैनिक', 'Weekly': 'साप्ताहिक',
  'Monthly': 'मासिक', 'All-time': 'कुल', 'Invite friends': 'दोस्तों को बुलाएँ', 'Log out': 'लॉग आउट', 'Send code': 'कोड भेजें', 'Verify and continue': 'सत्यापित करें',
  'Enter your mobile number': 'अपना मोबाइल नंबर डालें', 'Set up your profile': 'प्रोफ़ाइल बनाएँ', 'Continue': 'आगे बढ़ें', 'Show me on public rankings': 'मुझे सार्वजनिक रैंकिंग में दिखाएँ',
  'Language': 'भाषा', 'Delete my account': 'मेरा खाता हटाएँ', 'Live session': 'लाइव सत्र', 'Estimated from steps': 'कदमों से अनुमानित', 'GPS verified': 'GPS सत्यापित' };
const t = (s) => (S.lang === 'hi' && HI[s]) || s;
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (n) => Math.round(n).toLocaleString('en-IN');
const rs = (p) => '₹' + (p / 100).toLocaleString('en-IN', { minimumFractionDigits: p % 100 ? 2 : 0, maximumFractionDigits: 2 });
const km = (m) => (m / 1000).toFixed(1);
const ICON = { home: 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z', ranks: 'M4 20V10h4v10M10 20V4h4v16M16 20v-7h4v7', wallet: 'M3 7a2 2 0 0 1 2-2h13v4M3 7v10a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2zM16 14h.01',
  invite: 'M16 11a4 4 0 1 0-8 0 4 4 0 0 0 8 0zM4 21c0-3 3.5-5 8-5M18 15v6M15 18h6', profile: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 4-6 8-6s8 2 8 6', back: 'M15 5l-7 7 7 7' };
const icon = (k) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICON[k]}"/></svg>`;
const LOGO = '<svg width="40" height="40" viewBox="0 0 40 40" role="img" aria-label="PaidWalk"><rect width="40" height="40" rx="11" fill="#D9162B"/><path d="M12.5 29 L18.5 11" stroke="#fff" stroke-width="5" stroke-linecap="round"/><path d="M22.5 29 L28.5 17" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".72"/></svg>';

function toast(msg, err) { const el = $('#toast'); el.textContent = msg; el.className = err ? 'err' : ''; el.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (el.hidden = true), 4200); }

async function api(method, path, body) {
  let res;
  try {
    res = await fetch('/api' + path, { method, headers: Object.assign({ 'Content-Type': 'application/json' }, S.token ? { Authorization: 'Bearer ' + S.token } : {}), body: body ? JSON.stringify(body) : undefined });
  } catch (e) { throw new Error('You seem to be offline. Your steps are safe and will sync later.'); }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && S.token) { signOut(); throw new Error('Please sign in again.'); }
  if (!res.ok) { const e = new Error((data.error && data.error.message) || 'Something went wrong.'); e.code = data.error && data.error.code; throw e; }
  return data;
}
function signOut() { S.token = null; S.user = null; localStorage.removeItem('pw_token'); location.hash = '#/login'; }
const seg = (name, cur, opts) => `<div class="seg" role="group">${opts.map(([v, l]) => `<button data-act="seg" data-name="${name}" data-v="${v}" aria-pressed="${cur === v}">${esc(t(l))}</button>`).join('')}</div>`;
const header = (title, back) => `<header class="row">${back ? `<a href="#/${back}" aria-label="Back" class="card" style="padding:0;width:44px;height:44px;border-radius:14px;display:flex;align-items:center;justify-content:center">${icon('back')}</a>` : ''}<h1 class="grow">${esc(t(title))}</h1></header>`;
const skeleton = () => '<div class="skel" style="height:220px"></div><div class="skel" style="height:64px"></div><div class="skel" style="height:64px"></div>';
const errorBox = (e) => `<div class="card empty"><h2>Could not load this</h2><p class="small sub">${esc(e.message)}</p><button class="btn ghost" data-act="retry">Try again</button></div>`;

/* ---------------------------------------------------------------- screens */
const screens = {};

screens.login = async () => {
  nav.hidden = true;
  let phone = '';
  const step1 = () => {
    app.innerHTML = `<div class="logo" style="margin-top:24px">${LOGO}<span>Paid<em>Walk</em></span></div>
      <h1 style="font-size:32px;line-height:1.15;margin-top:18px">${t('Enter your mobile number')}</h1>
      <p class="sub">We sign you in with a one-time code. No password to remember.</p>
      <div class="field"><label for="ph">Mobile number (+91)</label><input id="ph" class="input num" inputmode="numeric" maxlength="10" autocomplete="tel-national" placeholder="98765 43210"></div>
      <button class="btn" id="go">${t('Send code')}</button>
      <p class="tiny dim">By continuing you agree to the Terms, Privacy Policy and Reward Eligibility Rules. One account per person and per device.</p>
      <p class="tiny dim" style="margin-top:auto;text-align:center">Made in India by <b style="color:#FAFAFA">@nitinikdaya</b></p>`;
    $('#go').onclick = async () => {
      phone = $('#ph').value.replace(/\D/g, '');
      try { const r = await api('POST', '/auth/otp/request', { phone }); step2(r); } catch (e) { $('#ph').classList.add('bad'); toast(e.message, true); }
    };
  };
  const step2 = (r) => {
    app.innerHTML = `<div class="logo" style="margin-top:24px">${LOGO}</div><h1 style="font-size:32px;line-height:1.15;margin-top:18px">Enter the 6-digit code</h1>
      <p class="sub">Sent to +91 ${esc(phone)}.</p>
      ${r.sandbox ? `<div class="note">Sandbox server: no SMS is sent. Your code is <b style="color:#FAFAFA">${esc(r.dev_code)}</b>.</div>` : ''}
      <div class="field"><label for="otp">One-time code</label><input id="otp" class="input num" inputmode="numeric" maxlength="6" autocomplete="one-time-code" style="font-size:28px;letter-spacing:12px;text-align:center;height:64px"></div>
      <button class="btn" id="go">${t('Verify and continue')}</button><button class="btn ghost" id="again" style="border:0">Use a different number</button>`;
    $('#again').onclick = step1;
    $('#go').onclick = async () => {
      try {
        const v = await api('POST', '/auth/otp/verify', { phone, code: $('#otp').value.trim(), device_id: deviceId, platform: 'web' });
        S.token = v.token; S.user = v.user; localStorage.setItem('pw_token', v.token);
        location.hash = v.user.needs_setup ? '#/setup' : '#/home';
      } catch (e) { $('#otp').classList.add('bad'); toast(e.message, true); }
    };
  };
  step1();
};

screens.setup = async () => {
  nav.hidden = true;
  app.innerHTML = `<h1 style="font-size:30px;margin-top:24px">${t('Set up your profile')}</h1><p class="sub">We ask only for what rankings need. No real name, no address.</p>
    <div class="card col" style="gap:16px">
      <div class="field"><label for="dn">Display name (shown on leaderboards)</label><input id="dn" class="input" maxlength="18" placeholder="e.g. AlwarStrider"><span class="tiny dim">3–18 letters, numbers or underscore.</span></div>
      <div class="field"><label for="st">State</label><select id="st" class="input">${S.cfg.states.map((s) => `<option${s === 'Rajasthan' ? ' selected' : ''}>${esc(s)}</option>`).join('')}</select></div>
      <div class="field"><label for="di">District</label><input id="di" class="input" maxlength="40" placeholder="e.g. Alwar"></div>
      <div class="field"><label for="rc">Referral code (optional)</label><input id="rc" class="input" maxlength="8" autocapitalize="characters"></div>
    </div>
    <div class="card row"><div class="grow col" style="gap:2px"><b id="pl">${t('Show me on public rankings')}</b><span class="tiny dim">Others see your display name and district only.</span></div><button class="switch" id="pub" role="switch" aria-checked="true" aria-labelledby="pl"><span></span></button></div>
    <button class="btn" id="go">${t('Continue')}</button>`;
  $('#pub').onclick = (e) => { const b = e.currentTarget; b.setAttribute('aria-checked', b.getAttribute('aria-checked') !== 'true'); };
  $('#go').onclick = async () => {
    try {
      const r = await api('PATCH', '/me', { display_name: $('#dn').value.trim(), state: $('#st').value, district: $('#di').value.trim(), public_ranking: $('#pub').getAttribute('aria-checked') === 'true' });
      S.user = r.user;
      const code = $('#rc').value.trim();
      if (code) { try { await api('POST', '/referral/apply', { code }); } catch (e) { toast('Profile saved. Referral code: ' + e.message, true); } }
      location.hash = '#/home';
    } catch (e) { toast(e.message, true); }
  };
};

function ringHtml(pct) {
  const c = (extra) => `<svg width="300" height="300" viewBox="0 0 300 300">${extra}</svg>`;
  return `<div class="ring base" aria-hidden="true"><div>${c('<circle cx="150" cy="150" r="124" fill="none" stroke="#2C2C32" stroke-width="30"/>')}</div></div>
    <div class="ring prog" aria-hidden="true"><div>${c(`<circle id="ringp" cx="150" cy="150" r="124" fill="none" stroke="#FF2D3F" stroke-width="30" stroke-linecap="round" pathLength="100" transform="rotate(90 150 150)" stroke-dasharray="0 100" data-pct="${pct}"/>`)}</div></div>`;
}
function animateRing() { const el = $('#ringp'); if (el) requestAnimationFrame(() => el.setAttribute('stroke-dasharray', Math.min(100, +el.dataset.pct).toFixed(2) + ' 100')); }
function tiersHtml(d) {
  return `<div class="tiers grid3">${S.cfg.tiers.map(([s, p]) => { const done = d.reward_steps >= s, next = d.next_tier && d.next_tier.steps === s;
    return `<div class="tier ${done ? 'done' : next ? 'next' : ''}"><span>${num(s)}${done ? ' · done' : next ? ' · next' : ''}</span><b>${rs(p)}</b></div>`; }).join('')}</div>`;
}

screens.home = async () => {
  app.innerHTML = skeleton();
  const [d, w, lb] = await Promise.all([api('GET', '/activity/today'), api('GET', '/wallet'), api('GET', '/leaderboard?scope=district&period=daily&limit=1').catch(() => null)]);
  const pct = d.steps / d.goal * 100;
  app.innerHTML = `<header class="row"><div class="grow col" style="gap:2px"><span class="small sub">${t('Namaste,')}</span><h1 style="font-size:24px">${esc(S.user.display_name)}</h1></div>
      <a href="#/profile" aria-label="Profile" class="num" style="width:44px;height:44px;border-radius:14px;background:#FAFAFA;color:#09090B;display:flex;align-items:center;justify-content:center">${esc(S.user.display_name.slice(0, 2).toUpperCase())}</a></header>
    ${S.user.on_hold ? '<a href="#/profile" class="card small" style="border-color:rgba(255,45,63,.6)">Your rewards are on hold while we review unusual activity. Tap to see details or appeal.</a>' : ''}
    <section class="card hero" aria-label="Today's verified steps">
      <div class="top row between"><span class="lbl">${t('Today · verified')}</span><a href="#/live" class="pill" style="height:44px;padding:0 14px"><span style="width:8px;height:8px;border-radius:50%;background:#FF2D3F"></span>Live</a></div>
      ${ringHtml(pct)}
      <div class="center"><div class="num">${num(d.steps)}</div><div class="small sub">of ${num(d.goal)} ${t('steps')} · ${Math.round(pct)}%</div></div>
      ${tiersHtml(d)}
    </section>
    ${d.rewards_funded ? '' : '<div class="note">No reward budget is funded for today, so steps count for rankings but do not earn money right now.</div>'}
    <div class="grid2">
      <div class="card tile col"><span class="tiny sub"><b>${t('Walking')}</b></span><span class="v">${km(d.walk_m)} <small>km</small></span><span class="tiny dim">${t('Estimated from steps')}</span></div>
      <div class="card tile col"><span class="tiny sub"><b>${t('Running')}</b></span><span class="v">${km(d.run_m)} <small>km</small></span><span class="tiny dim">${t('GPS verified')}</span></div>
      <a href="#/wallet" class="card red tile col"><span class="tiny"><b>${t('Earned today')}</b></span><span class="v">${rs(d.earned_today_paise)}</span><span class="tiny">${d.next_tier ? `${rs(d.next_tier.paise)} in ${num(d.next_tier.steps_to_go)} more steps` : 'Top milestone reached'}</span></a>
      <a href="#/wallet" class="card tile col"><span class="tiny sub"><b>${t('Wallet')}</b></span><span class="v">${rs(w.summary.available_paise)}</span><span class="tiny dim">${t('Available to withdraw')}</span></a>
      <a href="#/ranks" class="card tile col"><span class="tiny sub"><b>${esc(S.user.district)} rank</b></span><span class="v">${lb && lb.me ? '#' + num(lb.me.rank) : '–'}</span><span class="tiny dim">${lb && lb.me ? (lb.me.rank > 1 ? num(lb.me.gap_to_next) + ' steps to #' + (lb.me.rank - 1) : 'You lead today') : 'Walk to enter today'}</span></a>
      <div class="card tile col"><span class="tiny sub"><b>${t('Active streak')}</b></span><span class="v">${d.streak} <small>${t('days')}</small></span><span class="tiny dim">${d.active_min} active min · ~${num(d.kcal_estimate)} kcal est.</span></div>
    </div>
    <a href="#/live" class="btn">${t('Start walking')}</a>
    <p class="tiny dim">Calories are a rough estimate (0.04 kcal per step), not medical data.</p>`;
  animateRing();
};

/* ---- live session: real steps from the phone's motion sensor (lower trust than Health Connect / HealthKit) */
const ped = { on: false, steps: 0, sent: 0, segStart: 0, avg: 9.8, above: false, last: 0, timer: null, mins: [], minStart: 0, minBase: 0 };
function onMotion(e) {
  const a = e.accelerationIncludingGravity; if (!a || a.x === null) return;
  const m = Math.sqrt(a.x * a.x + a.y * a.y + a.z * a.z); ped.avg = ped.avg * 0.92 + m * 0.08; const d = m - ped.avg, now = performance.now();
  if (d > 1.3 && !ped.above && now - ped.last > 280) { ped.steps++; ped.last = now; ped.above = true; const el = $('#lsteps'); if (el) el.textContent = num(ped.steps); }
  if (d < 0.3) ped.above = false;
}
async function flushSteps() {
  const now = Math.floor(Date.now() / 1000), delta = ped.steps - ped.sent;
  if (now - ped.minStart >= 60) { ped.mins.push(ped.steps - ped.minBase); ped.minBase = ped.steps; ped.minStart = now; }
  if (delta <= 0 || now - ped.segStart < 20) return;
  const b = { client_batch_id: 'w-' + ped.segStart + '-' + now, source: 'web_sensor', start_ts: ped.segStart, end_ts: now, steps: delta, kind: 'walk', samples: ped.mins.splice(0) };
  try { const r = await api('POST', '/activity/batches', { device_id: deviceId, platform: 'web', batches: [b] }); ped.sent = ped.steps; ped.segStart = now + 1;
    const el = $('#lsync'); if (el) el.textContent = 'Synced · ' + num(r.today.steps) + ' verified today' + (r.results[0].flags.length ? ' · flagged for review' : '');
  } catch (e) { const el = $('#lsync'); if (el) el.textContent = e.message; }
}
async function startPed() {
  if (typeof DeviceMotionEvent === 'undefined') { toast('This device has no motion sensor. Open PaidWalk on your phone.', true); return; }
  if (DeviceMotionEvent.requestPermission) { const p = await DeviceMotionEvent.requestPermission().catch(() => 'denied'); if (p !== 'granted') { toast('Motion access was not allowed. You can turn it on in browser settings.', true); return; } }
  const now = Math.floor(Date.now() / 1000);
  Object.assign(ped, { on: true, steps: 0, sent: 0, segStart: now, minStart: now, minBase: 0, mins: [] });
  window.addEventListener('devicemotion', onMotion); ped.timer = setInterval(flushSteps, 30000); render();
}
async function stopPed() { ped.on = false; window.removeEventListener('devicemotion', onMotion); clearInterval(ped.timer); await flushSteps(); render(); }

screens.live = async () => {
  const d = await api('GET', '/activity/today');
  app.innerHTML = `${header('Live session', 'home')}
    <section class="card hero" style="height:290px">
      <div class="top row between"><span class="lbl">This session</span><span class="pill"><span style="width:8px;height:8px;border-radius:50%;background:${ped.on ? '#FF2D3F' : '#8B8B95'}"></span>${ped.on ? 'Recording' : 'Ready'}</span></div>
      ${ringHtml(d.steps / d.goal * 100)}
      <div class="center"><div class="num" id="lsteps">${num(ped.on ? ped.steps : 0)}</div><div class="small sub">${num(d.steps)} verified today</div></div>
      <div class="tiers small sub" id="lsync" style="text-align:center">${ped.on ? 'Syncing every 30 seconds' : 'Keep this page open and the phone in your hand or pocket.'}</div>
    </section>
    <button class="btn" data-act="${ped.on ? 'ped-stop' : 'ped-start'}">${ped.on ? 'Stop and sync' : 'Start'}</button>
    <div class="note">Browser step counting uses the motion sensor and only works while this page is open. ${S.cfg.reward_sources.includes('web_sensor') ? 'On this sandbox server these steps can earn rewards.' : 'These steps count for rankings; money rewards need the Android or iOS app (Health Connect / HealthKit).'}</div>
    ${S.cfg.sandbox ? '<button class="btn ghost" data-act="sandbox-walk">Sandbox: add a 10-minute test walk (1,000 steps)</button>' : ''}`;
  animateRing();
};

screens.ranks = async () => {
  const L = S.lb;
  app.innerHTML = `<header class="row between"><div class="col" style="gap:2px"><span class="lbl">${t('Leaderboard')}</span><h1 id="place" style="font-size:24px">&nbsp;</h1></div>
    <div class="field" style="gap:2px"><label for="metric" class="tiny">Rank by</label><select id="metric" class="input" style="height:44px;font-size:14px;width:auto;padding:0 10px">
    ${[['steps', 'Steps'], ['walk', 'Walking km'], ['run', 'Running km'], ['consistency', 'Consistency']].map(([v, l]) => `<option value="${v}"${L.metric === v ? ' selected' : ''}>${l}</option>`).join('')}</select></div></header>
    ${seg('scope', L.scope, [['district', 'District'], ['state', 'State'], ['national', 'National']])}
    ${seg('period', L.period, [['daily', 'Daily'], ['weekly', 'Weekly'], ['monthly', 'Monthly'], ['all', 'All-time']])}
    <div id="lb" class="col" style="gap:12px">${skeleton()}</div><div style="height:70px"></div>`;
  $('#metric').onchange = (e) => { L.metric = e.target.value; render(); };
  const d = await api('GET', `/leaderboard?scope=${L.scope}&period=${L.period}&metric=${L.metric}&limit=50`);
  const val = (v) => L.metric === 'steps' ? num(v) : L.metric === 'consistency' ? v + ' days' : km(v) + ' km';
  $('#place').textContent = d.place + (L.scope === 'district' ? ' District' : L.scope === 'state' ? ' State' : ' National');
  const top = d.top;
  const pod = (e, cls) => e ? `<div class="p ${cls}"><div class="av">${esc(e.display_name.slice(0, 2).toUpperCase())}</div><div class="nm">${esc(e.display_name)}</div><div class="tiny sub">${val(e.value)}</div><div class="blk">${e.rank}</div></div>` : '<div></div>';
  $('#lb').innerHTML = !top.length ? `<div class="card empty"><h2>No rankings yet</h2><p class="small sub">Be the first in ${esc(d.place)}: walk and sync your steps.</p><a class="btn ghost" href="#/live">Start walking</a></div>` :
    `<section class="card podium" aria-label="Top three">${pod(top[1], 'p2')}${pod(top[0], 'p1')}${pod(top[2], 'p3')}</section>
     ${top.length > 3 ? `<ol class="card list" style="list-style:none;margin:0;padding:2px 16px">${top.slice(3).map((e) => `<li><span class="num" style="width:28px;color:#C9C9D1">${e.rank}</span><span class="grow col" style="gap:0"><b class="small">${esc(e.display_name)}${e.is_me ? ' (you)' : ''}</b><span class="tiny dim">${esc(L.scope === 'national' ? e.state : e.district)}</span></span><span class="num">${val(e.value)}</span></li>`).join('')}</ol>` : ''}
     <p class="tiny dim">${num(d.participants)} ${d.participants === 1 ? 'walker' : 'walkers'}. Only display names and region are shown.</p>`;
  if (d.me) $('#over').innerHTML = (`<aside class="mecard" aria-label="Your position"><span class="num" style="font-size:20px">#${num(d.me.rank)}</span><span class="grow col" style="gap:0"><b class="small">You · ${esc(S.user.display_name)}</b><span class="tiny">${d.me.rank > 1 ? val(d.me.gap_to_next) + ' to reach #' + num(d.me.rank - 1) : 'You are leading'}${S.user.public_ranking ? '' : ' · private'}</span></span><span class="num">${val(d.me.value)}</span></aside>`);
};

screens.wallet = async () => {
  app.innerHTML = skeleton();
  const w = await api('GET', '/wallet'), s = w.summary, min = s.min_withdrawal_paise;
  const stColor = { pending: 'amber', held: 'redtxt', void: 'dim' };
  const open = w.withdrawals.filter((x) => x.status === 'requested' || x.status === 'approved');
  app.innerHTML = `${header('Wallet')}
    <section class="card col" style="border-radius:28px;padding:22px;gap:18px;box-shadow:0 6px 0 #17171A,0 30px 60px rgba(0,0,0,.5)">
      <div class="col"><span class="lbl">${t('Available balance')}</span><span class="num" style="font-size:52px;letter-spacing:-2px;line-height:1">${rs(s.available_paise)}</span><span class="small sub">Verified rewards you can withdraw now</span></div>
      <div class="grid3"><div class="col" style="gap:2px"><span class="tiny sub">${t('Pending')}</span><b class="num amber">${rs(s.pending_paise)}</b></div><div class="col" style="gap:2px"><span class="tiny sub">${t('On hold')}</span><b class="num ${s.held_paise ? 'redtxt' : ''}">${rs(s.held_paise)}</b></div><div class="col" style="gap:2px"><span class="tiny sub">${t('Lifetime')}</span><b class="num">${rs(s.lifetime_paise)}</b></div></div>
      ${s.available_paise >= min ? `<div class="field"><label for="amt">Amount (₹${min / 100} to ₹${Math.floor(s.available_paise / 100)})</label><input id="amt" class="input num" inputmode="numeric" value="${Math.floor(s.available_paise / 100)}"></div>
        <div class="field"><label for="upi">UPI ID</label><input id="upi" class="input" autocapitalize="none" placeholder="yourname@bank"></div><button class="btn" data-act="withdraw">${t('Withdraw to UPI')}</button>`
        : `<div class="col"><div style="height:8px;border-radius:999px;background:rgba(255,255,255,.12);overflow:hidden"><div style="height:100%;width:${Math.min(100, s.available_paise / min * 100)}%;background:#FAFAFA;border-radius:999px"></div></div><span class="small sub">${rs(Math.max(0, min - s.available_paise))} more to reach the ${rs(min)} minimum withdrawal.</span></div>`}
      <span class="tiny dim">One request per day. Requests are reviewed before payout.${S.cfg.sandbox ? ' Sandbox server: no real money moves.' : ''}</span>
    </section>
    ${open.length ? `<div class="card col"><h2>Payout status</h2>${open.map((x) => `<div class="row between small"><span>${rs(x.amount_paise)} to ${esc(x.upi)}</span><span class="pill amber">${x.status === 'requested' ? 'In review' : 'Approved, payout queued'}</span></div>`).join('')}</div>` : ''}
    <section class="card list" style="padding:4px 18px" aria-label="Transactions">${w.transactions.length ? w.transactions.map((x) => `<div><span class="grow col" style="gap:2px"><b class="small">${esc(x.note || x.type)}</b><span class="tiny dim">${esc(x.day)} · <span class="${stColor[x.status] || ''}">${x.status === 'available' ? 'verified' : x.status}</span></span></span><b class="num">${x.amount_paise < 0 ? '−' : '+'}${rs(Math.abs(x.amount_paise))}</b></div>`).join('')
      : '<div class="empty" style="width:100%"><h2>No transactions yet</h2><p class="small sub">Reach 5,000 verified steps to earn your first reward.</p></div>'}</section>
    <div class="card col small sub"><h2 style="color:#FAFAFA">How rewards are calculated</h2><span>1. Only steps verified by the server count.</span><span>2. You are paid once a day for the highest milestone reached: ${S.cfg.tiers.map(([st, p]) => `${num(st)} = ${rs(p)}`).join(', ')}.</span><span>3. Rewards stay Pending until the nightly check, then become Available.</span><span>4. Rewards come from a funded budget. If it runs out, the app says so before you walk.</span></div>`;
};

screens.invite = async () => {
  app.innerHTML = skeleton();
  const r = await api('GET', '/referral'), c = S.cfg.referral;
  app.innerHTML = `${header('Invite friends')}
    <section class="card col" style="gap:14px;border-radius:26px;padding:22px"><span class="lbl">Your code</span><div class="num" style="font-size:40px;letter-spacing:6px">${esc(r.code)}</div>
      <button class="btn" data-act="share" data-code="${esc(r.code)}">Share invite</button>
      <p class="small sub">You get ${rs(c.referrer_paise)} and your friend gets ${rs(c.referee_paise)} after they reach ${num(c.min_steps)} verified steps on ${c.days} different days. Paid only from a funded budget. Accounts on the same phone do not count.</p></section>
    ${r.can_apply ? '<div class="card col"><div class="field"><label for="code">Have a friend\'s code?</label><input id="code" class="input" maxlength="8" autocapitalize="characters"></div><button class="btn ghost" data-act="apply-code">Apply code</button></div>' : r.my_referral ? `<div class="note">You joined with a friend's code. Status: ${esc(r.my_referral)}.</div>` : ''}
    <section class="card list" style="padding:4px 18px">${r.invited.length ? r.invited.map((x) => `<div><b class="grow small">${esc(x.display_name || 'New walker')}</b><span class="pill ${x.status === 'rewarded' ? '' : x.status === 'rejected' ? 'red' : 'amber'}">${esc(x.status)}</span></div>`).join('') : '<div class="empty" style="width:100%"><h2>No invites yet</h2><p class="small sub">Friends who join with your code appear here.</p></div>'}</section>`;
};

screens.profile = async () => {
  const f = await api('GET', '/fraud/flags'), u = S.user;
  app.innerHTML = `${header('Profile')}
    <section class="card row" style="border-radius:26px;padding:20px;gap:16px"><div class="num" style="width:72px;height:72px;border-radius:24px;background:#FAFAFA;color:#09090B;display:flex;align-items:center;justify-content:center;font-size:26px;box-shadow:0 5px 0 #8B8B95">${esc(u.display_name.slice(0, 2).toUpperCase())}</div>
      <div class="col grow" style="gap:4px"><h2 class="num" style="font-size:22px">${esc(u.display_name)}</h2><span class="small sub">${esc(u.district)}, ${esc(u.state)}</span><span class="pill ${u.on_hold ? 'red' : ''}" style="align-self:flex-start">${u.on_hold ? 'Under review' : 'Verified account'}</span></div></section>
    <section class="card list" style="padding:4px 18px">
      <div><span class="grow col" style="gap:2px"><b class="small" id="pl">${t('Show me on public rankings')}</b><span class="tiny dim">Display name and district only</span></span><button class="switch" role="switch" aria-checked="${u.public_ranking}" aria-labelledby="pl" data-act="toggle-public"><span></span></button></div>
      <div><b class="grow small">${t('Language')}</b><div style="width:170px">${seg('lang', S.lang, [['en', 'English'], ['hi', 'हिन्दी']])}</div></div></section>
    ${f.flags.length ? `<section class="card col"><h2>Activity checks</h2><p class="small sub">Risk score ${f.risk_score} of 100. A hold is not a ban; a person reviews every case.</p>${f.flags.slice(0, 5).map((x) => `<div class="row between small"><span>${esc(x.signal.replace(/_/g, ' '))} · ${esc(x.day)}</span><span class="pill ${x.status === 'open' ? 'amber' : x.status === 'confirmed' ? 'red' : ''}">${esc(x.status)}</span></div>`).join('')}
      <div class="field"><label for="appeal">Appeal or explain</label><textarea id="appeal" class="input" rows="3" placeholder="Tell us the date and what happened."></textarea></div><button class="btn ghost" data-act="appeal">Send appeal</button></section>` : ''}
    <section class="card col small sub"><h2 style="color:#FAFAFA">Privacy</h2><span>We store your phone number, display name, state, district and step totals. No heart rate, sleep or medical data. Location is never stored by this web app.</span><span>Privacy Policy, Terms and Reward Rules: documents pending legal review.</span></section>
    ${u.role !== 'user' ? '<a class="btn ghost" href="/admin.html">Open admin dashboard</a>' : ''}
    <button class="btn ghost" data-act="logout">${t('Log out')}</button><button class="btn ghost danger" data-act="delete">${t('Delete my account')}</button>
    <p class="tiny dim" style="text-align:center">PaidWalk · Made in India by <b style="color:#FAFAFA">@nitinikdaya</b>, founder and owner</p>`;
};

/* ---------------------------------------------------------------- actions */
const actions = {
  retry: () => render(),
  seg: (el) => { const { name, v } = el.dataset; if (name === 'lang') { S.lang = v; localStorage.setItem('pw_lang', v); api('PATCH', '/me', { lang: v }).catch(() => {}); } else S.lb[name] = v; render(); },
  'ped-start': startPed, 'ped-stop': stopPed,
  'sandbox-walk': async () => {
    const now = Math.floor(Date.now() / 1000), last = +localStorage.getItem('pw_sbx') || 0, start = Math.max(now - 600, last + 1), mins = (now - start) / 60;
    if (mins < 1) return toast('Wait a minute before adding another test walk.', true);
    const r = await api('POST', '/activity/batches', { device_id: deviceId, platform: 'web', batches: [{ client_batch_id: 'sbx-' + now, source: 'sandbox', start_ts: start, end_ts: now, steps: Math.round(mins * 100) }] });
    localStorage.setItem('pw_sbx', now); toast('Sandbox walk added: ' + num(r.results[0].accepted_steps) + ' steps accepted.'); render();
  },
  withdraw: async (el) => {
    el.disabled = true;
    try { await api('POST', '/wallet/withdrawals', { amount_paise: Math.round(parseFloat($('#amt').value || '0') * 100), upi: $('#upi').value, idempotency_key: actions.wdKey || (actions.wdKey = crypto.randomUUID()) });
      actions.wdKey = null; toast('Request received. It is pending review and not paid yet.'); render();
    } catch (e) { el.disabled = false; if (e.code !== 'bad_upi' && e.code !== 'below_minimum' && e.code !== 'insufficient_balance') actions.wdKey = null; toast(e.message, true); }
  },
  share: async (el) => { const text = `Join me on PaidWalk and earn for walking. Use my code ${el.dataset.code}: ${location.origin}`;
    if (navigator.share) navigator.share({ text }).catch(() => {}); else { await navigator.clipboard.writeText(text).catch(() => {}); toast('Invite copied.'); } },
  'apply-code': async () => { const r = await api('POST', '/referral/apply', { code: $('#code').value }); toast(r.status === 'pending' ? 'Code applied.' : 'This code cannot be used on this device.', r.status !== 'pending'); render(); },
  'toggle-public': async () => { const r = await api('PATCH', '/me', { public_ranking: !S.user.public_ranking }); S.user = r.user; render(); },
  appeal: async () => { await api('POST', '/appeals', { message: $('#appeal').value }); toast('Appeal sent. A reviewer will look at it.'); $('#appeal').value = ''; },
  logout: async () => { await api('POST', '/auth/logout').catch(() => {}); signOut(); },
  delete: async (el) => {
    if (el.dataset.sure !== '1') { el.dataset.sure = '1'; el.textContent = 'Tap again to delete for ever. This cannot be undone.'; return; }
    try { await api('POST', '/me/delete', { forfeit_balance: el.dataset.forfeit === '1' }); signOut(); toast('Your account and personal data were deleted.'); }
    catch (e) { if (e.code === 'balance_remaining') { el.dataset.forfeit = '1'; el.textContent = 'You still have a balance. Tap again to give it up and delete.'; } else toast(e.message, true); }
  }
};
document.addEventListener('click', (e) => { const el = e.target.closest('[data-act]'); if (!el) return; Promise.resolve(actions[el.dataset.act](el)).catch((err) => toast(err.message, true)); });

/* ---------------------------------------------------------------- router */
const TABS = [['home', 'Home', 'home'], ['ranks', 'Ranks', 'ranks'], ['wallet', 'Wallet', 'wallet'], ['invite', 'Invite', 'invite'], ['profile', 'Profile', 'profile']];
async function render() {
  let route = (location.hash.replace('#/', '') || 'home').split('?')[0];
  try {
    if (!S.cfg) S.cfg = await api('GET', '/config');
    if (S.token && !S.user) S.user = (await api('GET', '/me')).user;
    if (!S.token) route = 'login'; else if (S.user.needs_setup) route = 'setup'; else if (route === 'login' || route === 'setup' || !screens[route]) route = 'home';
    document.documentElement.lang = S.lang;
    nav.hidden = route === 'login' || route === 'setup';
    nav.innerHTML = TABS.map(([r, l, i]) => `<a href="#/${r}"${r === route ? ' aria-current="page"' : ''}>${icon(i)}${esc(t(l))}</a>`).join('');
    window.scrollTo(0, 0);
    $('#over').innerHTML = '';
    await screens[route]();
  } catch (e) { if (S.token || route === 'login') app.innerHTML = errorBox(e); }
}
window.addEventListener('hashchange', render);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
render();
