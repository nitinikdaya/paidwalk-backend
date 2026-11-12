"""Shared helpers: time, errors, auth, rate limiting, config, audit."""
import datetime
import functools
import hashlib
import json
import time

from flask import current_app, g, request

IST_OFFSET = 19800  # all "days" are Indian Standard Time days

# Admin-editable settings (stored in table reward_config). Money is in paise.
DEFAULTS = {
    "tiers": [[5000, 100], [7500, 300], [10000, 1000]],  # [verified steps, paise]; highest tier reached pays once/day
    "daily_budget_paise": 0,            # 0 = no extra daily cap (funded budgets still apply)
    "min_withdrawal_paise": 5000,
    "reward_sources": ["health_connect", "healthkit"],  # sources whose steps can earn money
    "risk_hold_threshold": 50,
    "daily_step_cap": 60000,
    "referral_referrer_paise": 500,
    "referral_referee_paise": 200,
    "referral_days": 3,                 # referee needs this many days ...
    "referral_min_steps": 5000,         # ... with at least this many reward-eligible steps
}
SOURCES = ["health_connect", "healthkit", "web_sensor"]


class ApiError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def now():
    return int(time.time())


def day_of(ts):
    return datetime.datetime.fromtimestamp(ts + IST_OFFSET, datetime.timezone.utc).strftime("%Y-%m-%d")


def day_add(day, n):
    d = datetime.date.fromisoformat(day) + datetime.timedelta(days=n)
    return d.isoformat()


def today():
    return day_of(now())


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def cfg(db, key):
    row = db.execute("SELECT value FROM reward_config WHERE key=?", (key,)).fetchone()
    if row:
        return json.loads(row["value"])
    val = DEFAULTS[key]
    if key == "reward_sources" and current_app.config["SANDBOX"]:
        return val + ["web_sensor", "sandbox"]
    return val


def allowed_sources():
    return SOURCES + (["sandbox"] if current_app.config["SANDBOX"] else [])


def rate_limit(db, key, max_n, window_s):
    """Fixed-window limiter kept in the database so it works across workers."""
    start = now() // window_s * window_s
    db.execute(
        "INSERT INTO rate_limits(key,window_start,count) VALUES(?,?,1) "
        "ON CONFLICT(key,window_start) DO UPDATE SET count=count+1", (key, start))
    n = db.execute("SELECT count FROM rate_limits WHERE key=? AND window_start=?", (key, start)).fetchone()[0]
    if n > max_n:
        raise ApiError("rate_limited", "Too many requests. Please try again later.", 429)


def audit(db, actor_id, action, target="", detail=""):
    db.execute("INSERT INTO audit_log(actor_id,action,target,detail,created_at) VALUES(?,?,?,?,?)",
               (actor_id, action, str(target), json.dumps(detail) if not isinstance(detail, str) else detail, now()))


def auth(role=None):
    """Require a valid bearer token. role='reviewer' or 'admin' adds role-based access control."""
    rank = {"user": 0, "reviewer": 1, "admin": 2}

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            from .db import get_db
            db = get_db()
            head = request.headers.get("Authorization", "")
            if not head.startswith("Bearer "):
                raise ApiError("unauthorized", "Sign in required.", 401)
            row = db.execute(
                "SELECT u.*, s.device_id AS session_device FROM sessions s JOIN users u ON u.id=s.user_id "
                "WHERE s.token_hash=? AND s.expires_at>?", (sha(head[7:]), now())).fetchone()
            if not row or row["status"] == "deleted":
                raise ApiError("unauthorized", "Session expired. Sign in again.", 401)
            if role and rank[row["role"]] < rank[role]:
                raise ApiError("forbidden", "You do not have access to this.", 403)
            g.user = row
            return fn(*a, **kw)
        return wrapper
    return deco


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("bad_request", "Send a JSON object.")
    return data
