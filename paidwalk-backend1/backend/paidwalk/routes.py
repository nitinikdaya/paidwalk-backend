"""User-facing JSON API. The web app and the future Android/iOS apps use exactly these endpoints."""
import re
import secrets
import sqlite3

from flask import Blueprint, current_app, g, jsonify, request

from . import core, engine, fraud
from .core import ApiError, auth, body
from .db import get_db, tx

api = Blueprint("api", __name__, url_prefix="/api")

STATES = ["Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
          "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha",
          "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
          "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
          "Ladakh", "Lakshadweep", "Puducherry"]
NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,18}$")
DISTRICT_RE = re.compile(r"^[A-Za-z][A-Za-z .-]{1,39}$")


def norm_phone(p):
    d = re.sub(r"\D", "", str(p or ""))
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    if len(d) != 10 or d[0] not in "6789":
        raise ApiError("bad_phone", "Enter a valid 10-digit Indian mobile number.")
    return "+91" + d


def user_view(u):
    return {"id": u["id"], "display_name": u["display_name"], "state": u["state"], "district": u["district"],
            "public_ranking": bool(u["public_ranking"]), "lang": u["lang"], "role": u["role"], "verified": bool(u["verified"]),
            "risk_score": u["risk_score"], "on_hold": u["risk_score"] >= core.cfg(get_db(), "risk_hold_threshold"),
            "referral_code": u["referral_code"], "needs_setup": not u["verified"]}


def register_device(db, uid, device_id, platform):
    if device_id:
        db.execute("INSERT OR IGNORE INTO devices(user_id,device_id,platform,first_seen) VALUES(?,?,?,?)",
                   (uid, str(device_id)[:80], str(platform or "")[:20], core.now()))


# ------------------------------------------------------------------ auth
@api.post("/auth/otp/request")
def otp_request():
    db = get_db()
    phone = norm_phone(body().get("phone"))
    core.rate_limit(db, "otp:" + phone, 5, 3600)
    core.rate_limit(db, "otpip:" + (request.remote_addr or "?"), 30, 3600)
    code = "%06d" % secrets.randbelow(10 ** 6)
    db.execute("INSERT INTO otps(phone,code_hash,expires_at,attempts) VALUES(?,?,?,0) ON CONFLICT(phone) DO UPDATE SET code_hash=excluded.code_hash, expires_at=excluded.expires_at, attempts=0",
               (phone, core.sha(phone + code + current_app.config["SECRET_KEY"]), core.now() + 300))
    if current_app.config["SANDBOX"]:
        return jsonify(sent=True, sandbox=True, dev_code=code)  # sandbox only: shown on screen instead of SMS
    sender = current_app.config.get("SMS_SENDER")
    if not sender:
        raise ApiError("sms_not_configured", "SMS provider is not configured on this server yet.", 503)
    sender(phone, code)
    return jsonify(sent=True, sandbox=False)


@api.post("/auth/otp/verify")
def otp_verify():
    db = get_db()
    d = body()
    phone = norm_phone(d.get("phone"))
    core.rate_limit(db, "verify:" + phone, 10, 600)
    with tx(db):
        row = db.execute("SELECT * FROM otps WHERE phone=?", (phone,)).fetchone()
        ok = row and row["expires_at"] > core.now() and row["attempts"] < 5 and \
            secrets.compare_digest(row["code_hash"], core.sha(phone + str(d.get("code", "")) + current_app.config["SECRET_KEY"]))
        if not ok:
            if row:
                db.execute("UPDATE otps SET attempts=attempts+1 WHERE phone=?", (phone,))
        else:
            db.execute("DELETE FROM otps WHERE phone=?", (phone,))
            u = db.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
            if not u:
                while True:
                    rc = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(7))
                    if not db.execute("SELECT 1 FROM users WHERE referral_code=?", (rc,)).fetchone():
                        break
                db.execute("INSERT INTO users(phone,referral_code,created_at) VALUES(?,?,?)", (phone, rc, core.now()))
                u = db.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
            token = secrets.token_urlsafe(32)
            dev = str(d.get("device_id") or "")[:80] or None
            db.execute("INSERT INTO sessions(token_hash,user_id,device_id,created_at,expires_at) VALUES(?,?,?,?,?)",
                       (core.sha(token), u["id"], dev, core.now(), core.now() + 30 * 86400))
            register_device(db, u["id"], dev, d.get("platform"))
    if not ok:
        raise ApiError("bad_code", "That code is wrong or has expired.", 401)
    return jsonify(token=token, user=user_view(u))


@api.post("/auth/logout")
@auth()
def logout():
    get_db().execute("DELETE FROM sessions WHERE token_hash=?", (core.sha(request.headers["Authorization"][7:]),))
    return jsonify(ok=True)


# ------------------------------------------------------------------ profile
@api.get("/config")
def public_config():
    db = get_db()
    return jsonify(tiers=core.cfg(db, "tiers"), min_withdrawal_paise=core.cfg(db, "min_withdrawal_paise"), states=STATES,
                   sandbox=current_app.config["SANDBOX"], reward_sources=core.cfg(db, "reward_sources"),
                   referral={"referrer_paise": core.cfg(db, "referral_referrer_paise"), "referee_paise": core.cfg(db, "referral_referee_paise"),
                             "days": core.cfg(db, "referral_days"), "min_steps": core.cfg(db, "referral_min_steps")})


@api.get("/me")
@auth()
def me():
    return jsonify(user=user_view(g.user))


@api.patch("/me")
@auth()
def update_me():
    db, d, u = get_db(), body(), g.user
    sets, args = [], []
    if "display_name" in d:
        if not NAME_RE.match(str(d["display_name"])):
            raise ApiError("bad_name", "Display name: 3–18 letters, numbers or underscore.")
        sets.append("display_name=?"), args.append(d["display_name"])
    if "state" in d:
        if d["state"] not in STATES:
            raise ApiError("bad_state", "Choose a state from the list.")
        sets.append("state=?"), args.append(d["state"])
    if "district" in d:
        dist = " ".join(str(d["district"]).split()).title()
        if not DISTRICT_RE.match(dist):
            raise ApiError("bad_district", "Enter your district name in English letters.")
        if u["district"] and dist != u["district"]:
            if u["district_changed_at"] and u["district_changed_at"] > core.now() - 30 * 86400:
                raise ApiError("district_locked", "District can be changed once every 30 days.")
            sets.append("district_changed_at=?"), args.append(core.now())
        sets.append("district=?"), args.append(dist)
    if "public_ranking" in d:
        sets.append("public_ranking=?"), args.append(1 if d["public_ranking"] else 0)
    if d.get("lang") in ("en", "hi"):
        sets.append("lang=?"), args.append(d["lang"])
    if sets:
        try:
            db.execute("UPDATE users SET %s WHERE id=?" % ",".join(sets), args + [u["id"]])
        except sqlite3.IntegrityError:
            raise ApiError("name_taken", "That display name is taken. Try another.", 409)
        db.execute("UPDATE users SET verified=1 WHERE id=? AND display_name IS NOT NULL AND state IS NOT NULL AND district IS NOT NULL", (u["id"],))
    return jsonify(user=user_view(db.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()))


@api.post("/me/delete")
@auth()
def delete_me():
    """Data deletion request: personal data is erased now; money records are kept, anonymised, as financial records."""
    db, uid = get_db(), g.user["id"]
    if engine.wallet_summary(db, uid)["available_paise"] > 0 and not body().get("forfeit_balance"):
        raise ApiError("balance_remaining", "Withdraw your balance first, or confirm that you give it up.", 409)
    with tx(db):
        for t in ("sessions", "devices", "activity_batches", "daily_stats", "appeals"):
            db.execute("DELETE FROM %s WHERE user_id=?" % t, (uid,))
        db.execute("UPDATE users SET phone=?, display_name=NULL, state=NULL, district=NULL, status='deleted', public_ranking=0 WHERE id=?", ("deleted:%d" % uid, uid))
        db.execute("UPDATE withdrawals SET upi='deleted' WHERE user_id=?", (uid,))
        core.audit(db, uid, "user.delete", uid)
    return jsonify(ok=True)


# ------------------------------------------------------------------ activity
@api.post("/activity/batches")
@auth()
def post_batches():
    db, d = get_db(), body()
    core.rate_limit(db, "ingest:%d" % g.user["id"], 240, 3600)
    batches = d.get("batches")
    if not isinstance(batches, list) or not 1 <= len(batches) <= 50:
        raise ApiError("bad_request", "Send 1 to 50 batches.")
    dev = str(d.get("device_id") or g.user["session_device"] or "")[:80] or None
    register_device(db, g.user["id"], dev, d.get("platform"))
    results = [engine.ingest_batch(db, g.user, dev, b) for b in batches]
    return jsonify(results=results, today=today_view(db, g.user["id"]))


def today_view(db, uid):
    day = core.today()
    s = db.execute("SELECT * FROM daily_stats WHERE user_id=? AND day=?", (uid, day)).fetchone()
    steps = s["steps"] if s else 0
    rsteps = s["reward_steps"] if s else 0
    tiers = core.cfg(db, "tiers")
    earned = db.execute("SELECT COALESCE(SUM(amount_paise),0) FROM ledger WHERE user_id=? AND day=? AND type='reward' AND status!='void'", (uid, day)).fetchone()[0]
    nxt = next(([t, p] for t, p in tiers if rsteps < t), None)
    funded = db.execute("SELECT 1 FROM budgets WHERE active=1 AND starts<=? AND ends>=? AND funded_paise>spent_paise LIMIT 1", (day, day)).fetchone()
    return {"day": day, "steps": steps, "reward_steps": rsteps, "goal": tiers[-1][0] if tiers else 10000,
            "walk_m": round(s["walk_m"]) if s else 0, "run_m": round(s["run_m"]) if s else 0, "active_min": s["active_min"] if s else 0,
            "kcal_estimate": round(steps * 0.04), "streak": engine.streak(db, uid), "earned_today_paise": earned,
            "next_tier": {"steps": nxt[0], "paise": nxt[1], "steps_to_go": nxt[0] - rsteps} if nxt else None,
            "rewards_funded": bool(funded)}


@api.get("/activity/today")
@auth()
def get_today():
    return jsonify(today_view(get_db(), g.user["id"]))


@api.get("/activity/history")
@auth()
def history():
    days = min(max(request.args.get("days", 7, type=int), 1), 90)
    rows = get_db().execute("SELECT day,steps,walk_m,run_m,active_min FROM daily_stats WHERE user_id=? AND day>=? ORDER BY day",
                            (g.user["id"], core.day_add(core.today(), -(days - 1)))).fetchall()
    return jsonify(days=[dict(r) for r in rows])


# ------------------------------------------------------------------ wallet
@api.get("/wallet")
@auth()
def wallet():
    db = get_db()
    tx_rows = db.execute("SELECT id,type,amount_paise,status,day,note,created_at FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 100", (g.user["id"],)).fetchall()
    wd = db.execute("SELECT id,amount_paise,upi,status,note,created_at,updated_at FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 50", (g.user["id"],)).fetchall()
    return jsonify(summary=engine.wallet_summary(db, g.user["id"]), transactions=[dict(r) for r in tx_rows], withdrawals=[dict(r) for r in wd])


@api.post("/wallet/withdrawals")
@auth()
def withdraw():
    db, d = get_db(), body()
    core.rate_limit(db, "wd:%d" % g.user["id"], 10, 3600)
    w = engine.request_withdrawal(db, g.user["id"], d.get("amount_paise"), d.get("upi"), d.get("idempotency_key"))
    return jsonify(withdrawal={k: w[k] for k in ("id", "amount_paise", "upi", "status", "created_at")}, summary=engine.wallet_summary(db, g.user["id"]))


# ------------------------------------------------------------------ leaderboard / referral / fraud
@api.get("/leaderboard")
@auth()
def get_leaderboard():
    if not g.user["verified"]:
        raise ApiError("needs_setup", "Finish your profile to see rankings.", 409)
    a = request.args
    limit = min(max(a.get("limit", 50, type=int), 1), 100)
    return jsonify(engine.leaderboard(get_db(), g.user, a.get("scope", "district"), a.get("period", "daily"), a.get("metric", "steps"), limit))


@api.get("/referral")
@auth()
def referral():
    db = get_db()
    rows = db.execute("SELECT r.status, r.created_at, u.display_name FROM referrals r JOIN users u ON u.id=r.referee_id WHERE r.referrer_id=? ORDER BY r.id DESC", (g.user["id"],)).fetchall()
    mine = db.execute("SELECT status FROM referrals WHERE referee_id=?", (g.user["id"],)).fetchone()
    return jsonify(code=g.user["referral_code"], invited=[dict(r) for r in rows], my_referral=mine["status"] if mine else None,
                   can_apply=not mine and g.user["created_at"] > core.now() - 7 * 86400)


@api.post("/referral/apply")
@auth()
def referral_apply():
    return jsonify(status=engine.apply_referral(get_db(), g.user, body().get("code")))


@api.get("/fraud/flags")
@auth()
def my_flags():
    rows = get_db().execute("SELECT signal,day,status,created_at FROM fraud_flags WHERE user_id=? ORDER BY id DESC LIMIT 50", (g.user["id"],)).fetchall()
    return jsonify(risk_score=g.user["risk_score"], flags=[dict(r) for r in rows])


@api.post("/appeals")
@auth()
def appeal():
    db = get_db()
    msg = str(body().get("message") or "").strip()[:1000]
    if len(msg) < 10:
        raise ApiError("bad_request", "Please write at least 10 characters.")
    core.rate_limit(db, "appeal:%d" % g.user["id"], 3, 86400)
    db.execute("INSERT INTO appeals(user_id,message,created_at) VALUES(?,?,?)", (g.user["id"], msg, core.now()))
    return jsonify(ok=True)
