# PaidWalk — backend and web app

Walk-to-earn platform for India. Made by @nitinikdaya.

This package contains the **backend API** and the **web app (PWA)**. Android and iOS apps are not in this package; the API is built so they plug into the same endpoints (see "Connecting Android and iOS").

## What works today

| Area | Status |
|---|---|
| Phone + one-time-code login, profile, privacy toggle, account deletion | Working. SMS sending is **pending** (sandbox shows the code on screen). |
| Step ingestion, idempotent, server-verified | Working |
| Fake-step detection and risk scoring, holds, appeals, manual review | Working (12 signals) |
| Reward engine tied to a funded budget | Working |
| Wallet ledger, withdrawals with review | Working. Real UPI payout is **pending** (sandbox marks payouts `sandbox_paid`). |
| Leaderboards: district / state / national × daily / weekly / monthly / all-time × steps / walking / running / consistency | Working |
| Referral with anti-abuse checks | Working |
| Admin dashboard: stats, budgets, settings, fraud queue, appeals, withdrawals, users, audit log | Working |
| Real step tracking in the browser | Motion-sensor pedometer, only while the page is open. Low trust. |
| Real step tracking from Health Connect / HealthKit | **Pending**: needs the native apps. The API for it is ready. |
| City Battles, achievements, challenges, ads, sponsorships, premium | **Not built yet** (Phase 2–3) |
| Privacy policy, terms, reward rules documents | **Pending legal review** |

## Project structure

```
backend/
  paidwalk/__init__.py   app factory, security headers, error handling
  paidwalk/core.py       settings, auth, role checks, rate limiting, audit
  paidwalk/db.py         database schema and transactions
  paidwalk/fraud.py      anti-cheat signals and risk score
  paidwalk/engine.py     activity ingestion, rewards, wallet, withdrawals, referrals, leaderboards
  paidwalk/routes.py     user API
  paidwalk/admin.py      admin API
  manage.py              run / make-admin / settle
  wsgi.py, passenger_wsgi.py   server entry points
  tests/test_api.py      18 automated tests
web/
  index.html, app.js, styles.css      the app
  admin.html, admin.js                admin dashboard
  manifest.webmanifest, sw.js, icon.svg   installable PWA
```

Stack: Python 3.9+, Flask (the only dependency), SQLite. The web app is plain JavaScript with no build step.

## Run it on your computer

```
cd backend
pip install -r requirements.txt
python manage.py run          # http://localhost:8000
python -m unittest discover -s tests -v
```

Sign in once in the app, then make yourself admin and open `/admin.html`:

```
python manage.py make-admin 9876543210
```

Rewards only appear after you add a funded budget in the admin dashboard.

## Deploy on your hosting server

**cPanel / shared hosting with "Setup Python App":** upload the `paidwalk` folder, create a Python app with application root `paidwalk/backend`, startup file `passenger_wsgi.py`, entry point `application`. Run `pip install -r requirements.txt` from the panel. Add the environment variables from `.env.example`.

**VPS:** `pip install flask gunicorn`, then `gunicorn -w 2 -b 127.0.0.1:8000 wsgi:application` behind Nginx with HTTPS.

Required for both:

1. Set `PAIDWALK_SECRET` to a long random string and `PAIDWALK_DB` to a path **outside** the public web folder.
2. Serve over **HTTPS** only (the motion sensor and PWA install need it, and tokens must not travel in clear text).
3. Add a daily cron job at 00:30 IST: `python manage.py settle` (verifies yesterday's rewards, pays referrals).
4. Back up the database file daily.
5. Keep `PAIDWALK_SANDBOX=1` until SMS and payouts are connected. With `0`, login needs an SMS provider and browser steps stop earning money.

## How the money stays safe

- Money is stored as whole paise in an append-only `ledger`. Balances are always sums of ledger rows, never a stored number.
- Every ledger row has a unique `ref` (for example `reward:42:2026-11-12:1000`), so a retried request cannot pay twice.
- A reward is created only if a funded budget covers it, inside the same database transaction. No budget means no reward and no liability. The database also refuses `spent > funded`.
- Highest milestone pays once per day: reaching 7,500 after 5,000 tops ₹1 up to ₹3; it does not add ₹1 + ₹3.
- Rewards start as `pending`, become `available` after the nightly check, or `held` if the user's risk score is at or above the threshold.
- A withdrawal debits the ledger at request time; a rejection writes a reversal row.

## How fake steps are caught

The app only makes claims; `fraud.py` decides what is accepted. Each signal adds points for 30 days. At 50 points rewards are held and withdrawals paused. **No single signal reaches 50, and nothing bans automatically**; a reviewer clears or confirms flags, and users can appeal.

| Signal | Points | What it means |
|---|---|---|
| impossible_cadence | 30 | Over 220 steps a minute; accepted steps are capped at 200 a minute |
| robotic_pattern | 30 | 10 or more identical per-minute counts |
| mock_location | 40 | Phone reported a fake-GPS provider; GPS distance is discarded |
| device_integrity | 30 | Rooted device or failed app attestation |
| impossible_speed | 30 | GPS distance implies over 25 km/h |
| stride_mismatch | 15 | GPS distance does not fit the step count |
| device_farm | 35 | One device used by more than two accounts |
| duplicate_activity | 10 | Overlapping time range sent again (batch rejected) |
| manipulated_timestamp | 30 | Future timestamps or clock tampering |
| daily_cap | 20 | Hit the 60,000 steps a day ceiling |
| abnormal_spike | 15 | Over 5× the user's own 14-day average |
| self_referral | 30 | Referrer and friend share a device |

Batches older than 3 days or longer than 2 hours are rejected. Late syncs older than yesterday never create money.

## API

All requests and responses are JSON. Send `Authorization: Bearer <token>` after login. Errors look like `{"error": {"code": "...", "message": "..."}}`.

| Method and path | Purpose |
|---|---|
| POST `/api/auth/otp/request` `{phone}` | Send login code (sandbox returns `dev_code`) |
| POST `/api/auth/otp/verify` `{phone, code, device_id, platform}` | Returns `token` and `user` |
| POST `/api/auth/logout` | End session |
| GET `/api/config` | Reward tiers, minimum withdrawal, states, referral terms |
| GET / PATCH `/api/me` | Profile: `display_name, state, district, public_ranking, lang` |
| POST `/api/me/delete` | Erase personal data |
| POST `/api/activity/batches` | Upload steps (below) |
| GET `/api/activity/today`, `/api/activity/history?days=30` | Stats |
| GET `/api/wallet` | Summary, transactions, withdrawals |
| POST `/api/wallet/withdrawals` `{amount_paise, upi, idempotency_key}` | Request payout |
| GET `/api/leaderboard?scope=&period=&metric=&limit=` | Rankings plus your own position |
| GET `/api/referral`, POST `/api/referral/apply` `{code}` | Referral |
| GET `/api/fraud/flags`, POST `/api/appeals` `{message}` | Transparency and appeal |
| `/api/admin/...` | overview, budgets, config, flags, appeals, withdrawals, users, settle, audit (reviewer or admin role) |

### Connecting Android and iOS

The native apps read steps from Health Connect (Android) or HealthKit (iOS) and post them in buckets of one hour or less:

```json
POST /api/activity/batches
{"device_id": "stable-install-id", "platform": "android",
 "batches": [{
   "client_batch_id": "hc-2026-11-12T07",      // unique per bucket: safe to resend
   "source": "health_connect",                 // or "healthkit"
   "start_ts": 1794461400, "end_ts": 1794465000,
   "steps": 4210, "kind": "walk",              // or "run"
   "gps": true, "distance_m": 3150,            // only for GPS-tracked outdoor sessions
   "samples": [68, 72, 70],                    // optional steps per minute
   "signals": {"mock_location": false, "rooted": false, "integrity": "ok", "clock_tampered": false}
 }]}
```

The response gives, per batch, `status` (`accepted`, `duplicate`, `rejected`), `accepted_steps`, `flags`, and the updated `today` totals. The apps should display only server numbers.

## Known limitations

1. **Client signals can be forged by a modified app.** Before real money goes live the native apps must send Play Integrity (Android) and App Attest (iOS) tokens and the server must verify them. The `integrity` field exists; server-side verification is not written yet.
2. **Browser steps are easy to fake.** That is why they stop earning money when sandbox is off.
3. **SQLite** suits one server and early users. The SQL is standard; move to PostgreSQL before heavy load. Leaderboards are computed per request and need caching at scale.
4. **District names are free text** (cleaned to title case). A master district list should be loaded so "Alwar" and a misspelling do not become two boards.
5. **No SMS or payout provider is connected.** Both need accounts in your name (for example an SMS gateway with DLT registration, and a payout provider with KYC).
6. **Legal.** Paying users, storing phone numbers and step data means you need a privacy policy, terms, reward rules and a compliance check under India's data protection law before public launch. This is not legal advice; please have a lawyer review it.
7. Referral amounts (₹5 and ₹2), the 60,000-step cap, the 50-point hold threshold and the 30-day district lock are starting values I chose. Change them in admin settings.

## Roadmap

1. Android app (Health Connect) and iOS app (HealthKit) on this API, with Play Integrity / App Attest.
2. SMS provider and UPI payout provider; switch sandbox off.
3. City Battles, achievements, daily and weekly challenges (designs are already in the UI prototype).
4. PostgreSQL, cached leaderboards, push notifications.
5. Sponsored campaigns, ads, premium; legal documents.
