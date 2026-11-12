"""Admin API. reviewer = fraud queue and withdrawals; admin = money, config and roles. Every change is audited."""
import json

from flask import Blueprint, g, jsonify, request

from . import core, engine, fraud
from .core import ApiError, auth, body
from .db import get_db, tx

admin = Blueprint("admin", __name__, url_prefix="/api/admin")


def one(db, sql, *a):
    return db.execute(sql, a).fetchone()[0]


@admin.get("/overview")
@auth("reviewer")
def overview():
    db, day = get_db(), core.today()
    return jsonify(
        users=one(db, "SELECT COUNT(*) FROM users WHERE status!='deleted'"),
        daily_active=one(db, "SELECT COUNT(*) FROM daily_stats WHERE day=?", day),
        monthly_active=one(db, "SELECT COUNT(DISTINCT user_id) FROM daily_stats WHERE day>=?", core.day_add(day, -29)),
        verified_steps_today=one(db, "SELECT COALESCE(SUM(steps),0) FROM daily_stats WHERE day=?", day),
        liabilities_paise=one(db, "SELECT COALESCE(SUM(amount_paise),0) FROM ledger WHERE status IN('pending','available','held')"),
        funded_paise=one(db, "SELECT COALESCE(SUM(funded_paise),0) FROM budgets WHERE active=1"),
        budget_remaining_paise=one(db, "SELECT COALESCE(SUM(funded_paise-spent_paise),0) FROM budgets WHERE active=1 AND starts<=? AND ends>=?", day, day),
        pending_withdrawals=one(db, "SELECT COUNT(*) FROM withdrawals WHERE status IN('requested','approved')"),
        completed_withdrawals=one(db, "SELECT COUNT(*) FROM withdrawals WHERE status IN('paid','sandbox_paid')"),
        open_flags=one(db, "SELECT COUNT(*) FROM fraud_flags WHERE status='open'"),
        open_appeals=one(db, "SELECT COUNT(*) FROM appeals WHERE status='open'"))


@admin.get("/budgets")
@auth("reviewer")
def budgets():
    return jsonify(budgets=[dict(r) for r in get_db().execute("SELECT * FROM budgets ORDER BY id DESC")])


@admin.post("/budgets")
@auth("admin")
def add_budget():
    db, d = get_db(), body()
    funded = d.get("funded_paise")
    if not isinstance(funded, int) or funded <= 0 or not d.get("name") or not d.get("starts") or not d.get("ends") or d["starts"] > d["ends"]:
        raise ApiError("bad_request", "Give name, funded_paise (>0), starts and ends (YYYY-MM-DD).")
    bid = db.execute("INSERT INTO budgets(name,funded_paise,starts,ends,created_at) VALUES(?,?,?,?,?)",
                     (str(d["name"])[:80], funded, d["starts"], d["ends"], core.now())).lastrowid
    core.audit(db, g.user["id"], "budget.create", bid, d)
    return jsonify(id=bid)


@admin.post("/budgets/<int:bid>/active")
@auth("admin")
def budget_active(bid):
    db = get_db()
    on = 1 if body().get("active") else 0
    db.execute("UPDATE budgets SET active=? WHERE id=?", (on, bid))
    core.audit(db, g.user["id"], "budget.active", bid, {"active": on})
    return jsonify(ok=True)


@admin.get("/config")
@auth("reviewer")
def get_config():
    db = get_db()
    return jsonify({k: core.cfg(db, k) for k in core.DEFAULTS})


@admin.put("/config")
@auth("admin")
def put_config():
    db, d = get_db(), body()
    for k, v in d.items():
        if k not in core.DEFAULTS or type(v) is not type(core.DEFAULTS[k]):
            raise ApiError("bad_request", "Unknown or wrongly typed setting: %s" % k)
        if k == "tiers" and not all(isinstance(t, list) and len(t) == 2 and all(isinstance(x, int) and x >= 0 for x in t) for t in v):
            raise ApiError("bad_request", "tiers must be [[steps, paise], ...].")
        db.execute("INSERT INTO reward_config(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, json.dumps(v)))
    core.audit(db, g.user["id"], "config.update", "", d)
    return get_config()


@admin.get("/flags")
@auth("reviewer")
def flags():
    rows = get_db().execute(
        "SELECT f.*, u.display_name, u.risk_score FROM fraud_flags f JOIN users u ON u.id=f.user_id WHERE f.status=? ORDER BY f.id DESC LIMIT 200",
        (request.args.get("status", "open"),)).fetchall()
    return jsonify(flags=[dict(r) for r in rows])


@admin.post("/flags/<int:fid>/resolve")
@auth("reviewer")
def resolve_flag(fid):
    db, d = get_db(), body()
    if d.get("status") not in ("cleared", "confirmed"):
        raise ApiError("bad_request", "status must be cleared or confirmed.")
    with tx(db):
        f = db.execute("SELECT * FROM fraud_flags WHERE id=?", (fid,)).fetchone()
        if not f:
            raise ApiError("not_found", "Flag not found.", 404)
        db.execute("UPDATE fraud_flags SET status=?, resolved_by=?, resolved_at=? WHERE id=?", (d["status"], g.user["id"], core.now(), fid))
        risk = fraud.recompute_risk(db, f["user_id"])
        core.audit(db, g.user["id"], "flag." + d["status"], fid, {"user": f["user_id"], "note": d.get("note", "")})
    return jsonify(ok=True, risk_score=risk)


@admin.get("/appeals")
@auth("reviewer")
def appeals():
    rows = get_db().execute("SELECT a.*, u.display_name, u.risk_score FROM appeals a JOIN users u ON u.id=a.user_id WHERE a.status='open' ORDER BY a.id").fetchall()
    return jsonify(appeals=[dict(r) for r in rows])


@admin.post("/appeals/<int:aid>/close")
@auth("reviewer")
def close_appeal(aid):
    db = get_db()
    db.execute("UPDATE appeals SET status='closed' WHERE id=?", (aid,))
    core.audit(db, g.user["id"], "appeal.close", aid)
    return jsonify(ok=True)


@admin.get("/withdrawals")
@auth("reviewer")
def withdrawals():
    rows = get_db().execute(
        "SELECT w.*, u.display_name, u.risk_score FROM withdrawals w JOIN users u ON u.id=w.user_id ORDER BY (w.status IN('requested','approved')) DESC, w.id DESC LIMIT 200").fetchall()
    return jsonify(withdrawals=[dict(r) for r in rows])


@admin.post("/withdrawals/<int:wid>/<action>")
@auth("reviewer")
def withdrawal_action(wid, action):
    if action not in ("approve", "reject", "mark_paid"):
        raise ApiError("bad_request", "Unknown action.")
    return jsonify(withdrawal=engine.resolve_withdrawal(get_db(), g.user["id"], wid, action, str(body().get("note") or "")[:200]))


@admin.get("/users")
@auth("reviewer")
def users():
    q = "%" + request.args.get("q", "") + "%"
    rows = get_db().execute("SELECT id,display_name,state,district,role,verified,risk_score,status,created_at FROM users "
                            "WHERE status!='deleted' AND COALESCE(display_name,'') LIKE ? ORDER BY risk_score DESC, id DESC LIMIT 100", (q,)).fetchall()
    return jsonify(users=[dict(r) for r in rows])


@admin.post("/users/<int:uid>")
@auth("admin")
def update_user(uid):
    """Manual, audited decisions only: ban/unban after review, change role, void held rewards."""
    db, d = get_db(), body()
    if d.get("status") in ("active", "banned"):
        db.execute("UPDATE users SET status=? WHERE id=? AND status!='deleted'", (d["status"], uid))
        if d["status"] == "banned":
            db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    if d.get("role") in ("user", "reviewer", "admin"):
        db.execute("UPDATE users SET role=? WHERE id=?", (d["role"], uid))
    voided = engine.void_held(db, g.user["id"], uid) if d.get("void_held") else 0
    core.audit(db, g.user["id"], "user.update", uid, d)
    return jsonify(ok=True, voided=voided)


@admin.post("/settle")
@auth("admin")
def run_settle():
    db = get_db()
    out = engine.settle(db)
    core.audit(db, g.user["id"], "settle.run", "", out)
    return jsonify(out)


@admin.get("/audit")
@auth("admin")
def audit_log():
    rows = get_db().execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200").fetchall()
    return jsonify(audit=[dict(r) for r in rows])
