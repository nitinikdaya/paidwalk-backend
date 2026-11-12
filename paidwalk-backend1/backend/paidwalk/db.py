"""SQLite storage. Schema is plain SQL so it can move to PostgreSQL later."""
import sqlite3
from contextlib import contextmanager

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, phone TEXT UNIQUE NOT NULL, display_name TEXT UNIQUE,
  state TEXT, district TEXT, district_changed_at INTEGER, public_ranking INTEGER NOT NULL DEFAULT 1,
  lang TEXT NOT NULL DEFAULT 'en', role TEXT NOT NULL DEFAULT 'user',
  verified INTEGER NOT NULL DEFAULT 0, risk_score INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',              -- active | banned | deleted
  referral_code TEXT UNIQUE NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS otps(phone TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires_at INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), device_id TEXT, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS devices(user_id INTEGER NOT NULL REFERENCES users(id), device_id TEXT NOT NULL, platform TEXT, integrity TEXT NOT NULL DEFAULT 'unknown', first_seen INTEGER NOT NULL, PRIMARY KEY(user_id, device_id));
CREATE INDEX IF NOT EXISTS ix_devices_device ON devices(device_id);
CREATE TABLE IF NOT EXISTS activity_batches(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), client_batch_id TEXT NOT NULL,
  source TEXT NOT NULL, device_id TEXT, kind TEXT NOT NULL DEFAULT 'walk',
  start_ts INTEGER NOT NULL, end_ts INTEGER NOT NULL, day TEXT NOT NULL,
  steps INTEGER NOT NULL, accepted_steps INTEGER NOT NULL, distance_m REAL, gps_verified INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL, reason TEXT, created_at INTEGER NOT NULL,
  UNIQUE(user_id, client_batch_id));
CREATE INDEX IF NOT EXISTS ix_batches_time ON activity_batches(user_id, start_ts, end_ts);
CREATE TABLE IF NOT EXISTS daily_stats(
  user_id INTEGER NOT NULL REFERENCES users(id), day TEXT NOT NULL,
  steps INTEGER NOT NULL DEFAULT 0, reward_steps INTEGER NOT NULL DEFAULT 0, raw_steps INTEGER NOT NULL DEFAULT 0,
  walk_m REAL NOT NULL DEFAULT 0, run_m REAL NOT NULL DEFAULT 0, active_min INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(user_id, day));
CREATE INDEX IF NOT EXISTS ix_daily_day ON daily_stats(day);
CREATE TABLE IF NOT EXISTS fraud_flags(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), batch_id INTEGER, day TEXT NOT NULL,
  signal TEXT NOT NULL, weight INTEGER NOT NULL, detail TEXT,
  status TEXT NOT NULL DEFAULT 'open',                -- open | cleared | confirmed
  created_at INTEGER NOT NULL, resolved_by INTEGER, resolved_at INTEGER,
  UNIQUE(user_id, signal, day));
CREATE TABLE IF NOT EXISTS appeals(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reward_config(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS budgets(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, funded_paise INTEGER NOT NULL, spent_paise INTEGER NOT NULL DEFAULT 0,
  starts TEXT NOT NULL, ends TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL,
  CHECK(spent_paise <= funded_paise));
CREATE TABLE IF NOT EXISTS ledger(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  type TEXT NOT NULL,                                 -- reward | referral | withdrawal | reversal
  amount_paise INTEGER NOT NULL,                      -- signed: credits positive, debits negative
  status TEXT NOT NULL,                               -- pending | available | held | void
  ref TEXT UNIQUE NOT NULL,                           -- idempotency key
  day TEXT NOT NULL, budget_id INTEGER, note TEXT, created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ix_ledger_user ON ledger(user_id, status);
CREATE TABLE IF NOT EXISTS withdrawals(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), amount_paise INTEGER NOT NULL, upi TEXT NOT NULL,
  status TEXT NOT NULL,                               -- requested | approved | sandbox_paid | paid | rejected
  idem TEXT NOT NULL, note TEXT, provider_ref TEXT, day TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  UNIQUE(user_id, idem));
CREATE TABLE IF NOT EXISTS referrals(
  id INTEGER PRIMARY KEY, referrer_id INTEGER NOT NULL REFERENCES users(id), referee_id INTEGER UNIQUE NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'pending',             -- pending | rewarded | rejected
  reason TEXT, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT NOT NULL, target TEXT, detail TEXT, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS rate_limits(key TEXT NOT NULL, window_start INTEGER NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(key, window_start));
"""


def connect(path):
    db = sqlite3.connect(path, isolation_level=None, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_db(path):
    db = connect(path)
    db.executescript(SCHEMA)
    db.close()


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


@contextmanager
def tx(db):
    """One atomic write transaction. BEGIN IMMEDIATE takes the write lock up front,
    so budget checks and ledger inserts cannot interleave with another request."""
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
