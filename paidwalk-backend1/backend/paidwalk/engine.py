"""Activity ingestion, reward engine, wallet ledger, withdrawals, referrals, leaderboards.

Money rules enforced here:
  * rewards are computed only on the server, from accepted steps;
  * every ledger row has a unique `ref`, so retries can never pay twice;
  * a reward is only created if a funded budget can cover it (same transaction).
"""
import datetime
import re

from flask import current_app

from . import core, fraud
from .core import ApiError
from .db import tx

UPI_RE = re.compile(r"^[a-z0-9._-]{2,64}@[a-z]{2,32}$")


# ---------------------------------------------------------------- activity
def _int(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("bad_request", "%s must be a number." % name)
    return int(v)


def ingest_batch(db, user, device_id, b):
    if not isinstance(b, dict):
        raise ApiError("bad_request", "Each batch must be an object.")
    cid = str(b.get("client_batch_id") or "")[:64]
    source = b.get("source")
    if not cid:
        raise ApiError("bad_request", "client_batch_id is required.")
    if source not in core.allowed_sources():
        raise ApiError("bad_source", "Unknown activity source.")
    clean = {"start_ts": _int(b.get("start_ts"), "start_ts"), "end_ts": _int(b.get("end_ts"), "end_ts"),
             "steps": _int(b.get("steps"), "steps"), "distance_m": b.get("distance_m"), "gps": b.get("gps"),
             "samples": b.get("samples") if isinstance(b.get("samples"), list) else [],
             "signals": b.get("signals") if isinstance(b.get("signals"), dict) else {}}
    kind = "run" if b.get("kind") == "run" else "walk"
    uid = user["id"]
    with tx(db):
        dup = db.execute("SELECT accepted_steps,status FROM activity_batches WHERE user_id=? AND client_batch_id=?", (uid, cid)).fetchone()
        if dup:
            return {"client_batch_id": cid, "status": "duplicate", "accepted_steps": dup["accepted_steps"], "flags": []}
        shared = db.execute("SELECT COUNT(DISTINCT user_id) FROM devices WHERE device_id=?", (device_id,)).fetchone()[0] if device_id else 0
        r = fraud.evaluate(db, uid, clean, shared)
        day = core.day_of(clean["start_ts"]) if clean["start_ts"] > 0 else core.today()
        accepted = r["accepted"]
        if not r["reject"]:
            cap = core.cfg(db, "daily_step_cap")
            cur = db.execute("SELECT steps FROM daily_stats WHERE user_id=? AND day=?", (uid, day)).fetchone()
            cur = cur[0] if cur else 0
            if cur + accepted > cap:
                accepted = max(0, cap - cur)
                r["flags"].append(("daily_cap", "daily ceiling of %d steps reached" % cap))
        status = "rejected" if r["reject"] else "accepted"
        bid = db.execute(
            "INSERT INTO activity_batches(user_id,client_batch_id,source,device_id,kind,start_ts,end_ts,day,steps,accepted_steps,distance_m,gps_verified,status,reason,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, cid, source, device_id, kind, clean["start_ts"], clean["end_ts"], day, clean["steps"], accepted,
             clean["distance_m"] if r["gps_ok"] else None, int(r["gps_ok"]), status, r["reject"], core.now())).lastrowid
        for signal, detail in r["flags"]:
            fraud.add_flag(db, uid, signal, detail, bid, day)
        if status == "accepted" and accepted > 0:
            minutes = (clean["end_ts"] - clean["start_ts"]) / 60.0
            run_m = clean["distance_m"] if (kind == "run" and r["gps_ok"]) else 0
            walk_m = 0 if run_m else (clean["distance_m"] if r["gps_ok"] else accepted * 0.75)
            active = int(round(minutes)) if accepted / max(minutes, 1 / 6) >= 60 else 0
            # ---- reward eligibility: pay only for real, GPS-verified movement ----
            # Shaking the phone in place produces no displacement, so it earns nothing.
            eligible, indoor_add = 0, 0
            if source in core.cfg(db, "reward_sources"):
                dist = clean["distance_m"]
                gps_move = (r["gps_ok"] and isinstance(dist, (int, float))
                            and dist >= core.cfg(db, "min_gps_move_m")
                            and 0.3 <= dist / accepted <= 2.5)
                if gps_move:
                    eligible = accepted                       # verified outdoor walking/running
                elif not core.cfg(db, "gps_required_for_rewards"):
                    # small indoor allowance (treadmill/mall), capped per day so it can't be farmed
                    cap = core.cfg(db, "indoor_daily_reward_steps")
                    used = db.execute("SELECT indoor_reward_steps FROM daily_stats WHERE user_id=? AND day=?", (uid, day)).fetchone()
                    used = used[0] if used else 0
                    eligible = max(0, min(accepted, cap - used))
                    indoor_add = eligible
            db.execute(
                "INSERT INTO daily_stats(user_id,day,steps,reward_steps,indoor_reward_steps,raw_steps,walk_m,run_m,active_min) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(user_id,day) DO UPDATE SET steps=steps+excluded.steps, reward_steps=reward_steps+excluded.reward_steps,"
                " indoor_reward_steps=indoor_reward_steps+excluded.indoor_reward_steps,"
                " raw_steps=raw_steps+excluded.raw_steps, walk_m=walk_m+excluded.walk_m, run_m=run_m+excluded.run_m, active_min=active_min+excluded.active_min",
                (uid, day, accepted, eligible, indoor_add, clean["steps"], walk_m, run_m, active))
            fraud.check_spike(db, uid, day)
            award_day(db, uid, day)
    return {"client_batch_id": cid, "status": status, "reason": r["reject"], "accepted_steps": accepted if status == "accepted" else 0,
            "gps_verified": r["gps_ok"], "flags": [f[0] for f in r["flags"]]}


# ---------------------------------------------------------------- rewards
def spend_budget(db, amount, day):
    """Reserve `amount` from a funded campaign. Must run inside tx(). Returns budget id or None."""
    row = db.execute("SELECT id FROM budgets WHERE active=1 AND starts<=? AND ends>=? AND funded_paise-spent_paise>=? ORDER BY id LIMIT 1",
                     (day, day, amount)).fetchone()
    if not row:
        return None
    db.execute("UPDATE budgets SET spent_paise=spent_paise+? WHERE id=?", (amount, row["id"]))
    return row["id"]


def tier_amount(db, steps):
    return max([p for s, p in core.cfg(db, "tiers") if steps >= s] or [0])


def award_day(db, uid, day):
    """Top up the user's base reward for `day` to the highest tier reached. Runs inside tx()."""
    if day < core.day_add(core.today(), -1):
        return 0  # late syncs older than yesterday never create money
    u = db.execute("SELECT status FROM users WHERE id=?", (uid,)).fetchone()
    st = db.execute("SELECT reward_steps FROM daily_stats WHERE user_id=? AND day=?", (uid, day)).fetchone()
    if not st or u["status"] != "active":
        return 0
    target = tier_amount(db, st["reward_steps"])
    posted = db.execute("SELECT COALESCE(SUM(amount_paise),0) FROM ledger WHERE user_id=? AND day=? AND type='reward' AND status!='void'", (uid, day)).fetchone()[0]
    delta = target - posted
    if delta <= 0:
        return 0
    cap = core.cfg(db, "daily_budget_paise")
    if cap:
        spent = db.execute("SELECT COALESCE(SUM(amount_paise),0) FROM ledger WHERE day=? AND type='reward' AND status!='void'", (day,)).fetchone()[0]
        if spent + delta > cap:
            return 0
    budget_id = spend_budget(db, delta, day)
    if not budget_id:
        return 0  # no funded budget: no liability is created
    db.execute("INSERT OR IGNORE INTO ledger(user_id,type,amount_paise,status,ref,day,budget_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
               (uid, "reward", delta, "pending", "reward:%d:%s:%d" % (uid, day, target), day, budget_id, "%s step milestone" % format(max(t for t, pz in core.cfg(db, "tiers") if pz == target), ","), core.now()))
    return delta


def settle(db):
    """Nightly job: verify yesterday's pending rewards, hold risky ones, release cleared ones, pay referrals."""
    thr = None
    out = {"released": 0, "held": 0, "referrals_paid": 0}
    with tx(db):
        thr = core.cfg(db, "risk_hold_threshold")
        rows = db.execute("SELECT l.id, u.risk_score, l.status FROM ledger l JOIN users u ON u.id=l.user_id "
                          "WHERE (l.status='pending' AND l.day<?) OR l.status='held'", (core.today(),)).fetchall()
        for r in rows:
            new = "held" if r["risk_score"] >= thr else "available"
            if new != r["status"]:
                db.execute("UPDATE ledger SET status=? WHERE id=?", (new, r["id"]))
                out["released" if new == "available" else "held"] += 1
        need_days, need_steps = core.cfg(db, "referral_days"), core.cfg(db, "referral_min_steps")
        a, b = core.cfg(db, "referral_referrer_paise"), core.cfg(db, "referral_referee_paise")
        for r in db.execute("SELECT * FROM referrals WHERE status='pending'").fetchall():
            days = db.execute("SELECT COUNT(*) FROM daily_stats WHERE user_id=? AND reward_steps>=?", (r["referee_id"], need_steps)).fetchone()[0]
            people = db.execute("SELECT id,risk_score,status FROM users WHERE id IN(?,?)", (r["referrer_id"], r["referee_id"])).fetchall()
            if days < need_days or any(p["risk_score"] >= thr or p["status"] != "active" for p in people):
                continue
            budget_id = spend_budget(db, a + b, core.today())
            if not budget_id:
                continue
            for uid, amt, who in ((r["referrer_id"], a, "referrer"), (r["referee_id"], b, "referee")):
                if amt:
                    db.execute("INSERT OR IGNORE INTO ledger(user_id,type,amount_paise,status,ref,day,budget_id,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                               (uid, "referral", amt, "available", "referral:%d:%s" % (r["id"], who), core.today(), budget_id, "Referral bonus", core.now()))
            db.execute("UPDATE referrals SET status='rewarded' WHERE id=?", (r["id"],))
            out["referrals_paid"] += 1
    return out


# ---------------------------------------------------------------- wallet
def wallet_summary(db, uid):
    q = lambda sql, *a: db.execute(sql, (uid,) + a).fetchone()[0]
    return {
        "available_paise": q("SELECT COALESCE(SUM(amount_paise),0) FROM ledger WHERE user_id=? AND status='available'"),
        "pending_paise": q("SELECT COALESCE(SUM(amount_paise),0) FROM ledger WHERE user_id=? AND status='pending'"),
        "held_paise": q("SELECT COALESCE(SUM(amount_paise),0) FROM ledger WHERE user_id=? AND status='held'"),
        "lifetime_paise": q("SELECT COALESCE(SUM(amount_paise),0) FROM ledger WHERE user_id=? AND amount_paise>0 AND type IN('reward','referral') AND status!='void'"),
        "withdrawn_paise": q("SELECT COALESCE(SUM(amount_paise),0) FROM withdrawals WHERE user_id=? AND status!='rejected'"),
        "min_withdrawal_paise": core.cfg(db, "min_withdrawal_paise"),
    }


def request_withdrawal(db, uid, amount, upi, idem):
    upi = str(upi or "").strip().lower()
    idem = str(idem or "")[:64]
    if not idem:
        raise ApiError("bad_request", "idempotency_key is required.")
    amount = _int(amount, "amount_paise")
    with tx(db):
        old = db.execute("SELECT * FROM withdrawals WHERE user_id=? AND idem=?", (uid, idem)).fetchone()
        if old:
            return dict(old)
        u = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u["verified"]:
            raise ApiError("not_verified", "Complete your profile before withdrawing.", 403)
        if u["risk_score"] >= core.cfg(db, "risk_hold_threshold") or u["status"] != "active":
            raise ApiError("account_on_hold", "Withdrawals are paused while your account is under review. You can appeal in Help.", 403)
        if not UPI_RE.match(upi):
            raise ApiError("bad_upi", "Enter a valid UPI ID, like name@bank.")
        if amount < core.cfg(db, "min_withdrawal_paise"):
            raise ApiError("below_minimum", "Minimum withdrawal is ₹%d." % (core.cfg(db, "min_withdrawal_paise") // 100))
        day = core.today()
        if db.execute("SELECT 1 FROM withdrawals WHERE user_id=? AND day=? AND status!='rejected'", (uid, day)).fetchone():
            raise ApiError("daily_limit", "Only one withdrawal request per day.")
        if amount > wallet_summary(db, uid)["available_paise"]:
            raise ApiError("insufficient_balance", "Amount is more than your available balance.")
        db.execute("INSERT INTO ledger(user_id,type,amount_paise,status,ref,day,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (uid, "withdrawal", -amount, "available", "wd:%d:%s" % (uid, idem), day, "Withdrawal to UPI", core.now()))
        wid = db.execute("INSERT INTO withdrawals(user_id,amount_paise,upi,status,idem,day,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                         (uid, amount, upi, "requested", idem, day, core.now(), core.now())).lastrowid
        return dict(db.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone())


def resolve_withdrawal(db, actor_id, wid, action, note=""):
    with tx(db):
        w = db.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
        if not w:
            raise ApiError("not_found", "Withdrawal not found.", 404)
        if action == "approve" and w["status"] == "requested":
            if current_app.config["SANDBOX"] and current_app.config["PAYOUT_PROVIDER"] == "sandbox":
                new, ref = "sandbox_paid", "SANDBOX-%d" % wid  # no real money moves
            else:
                new, ref = "approved", None  # real payout must be made and then recorded with mark_paid
        elif action == "mark_paid" and w["status"] == "approved":
            if not note:
                raise ApiError("bad_request", "Give the payment provider reference in note.")
            new, ref = "paid", note
        elif action == "reject" and w["status"] in ("requested", "approved"):
            new, ref = "rejected", None
            db.execute("INSERT INTO ledger(user_id,type,amount_paise,status,ref,day,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
                       (w["user_id"], "reversal", w["amount_paise"], "available", "wdrev:%d" % wid, core.today(), "Withdrawal rejected, amount returned", core.now()))
        else:
            raise ApiError("bad_state", "That action is not allowed for a withdrawal that is %s." % w["status"], 409)
        db.execute("UPDATE withdrawals SET status=?, note=?, provider_ref=COALESCE(?,provider_ref), updated_at=? WHERE id=?", (new, note, ref, core.now(), wid))
        core.audit(db, actor_id, "withdrawal." + action, wid, {"status": new, "note": note})
        return dict(db.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone())


def void_held(db, actor_id, uid):
    """After confirmed fraud: cancel the user's held rewards and return the money to its budget."""
    with tx(db):
        rows = db.execute("SELECT id,amount_paise,budget_id FROM ledger WHERE user_id=? AND status='held'", (uid,)).fetchall()
        for r in rows:
            db.execute("UPDATE ledger SET status='void' WHERE id=?", (r["id"],))
            if r["budget_id"]:
                db.execute("UPDATE budgets SET spent_paise=spent_paise-? WHERE id=?", (r["amount_paise"], r["budget_id"]))
        core.audit(db, actor_id, "ledger.void_held", uid, {"rows": len(rows)})
    return len(rows)


# ---------------------------------------------------------------- referrals
def apply_referral(db, user, code):
    code = str(code or "").strip().upper()
    with tx(db):
        if db.execute("SELECT 1 FROM referrals WHERE referee_id=?", (user["id"],)).fetchone():
            raise ApiError("already_referred", "A referral code is already linked to your account.")
        if user["created_at"] < core.now() - 7 * 86400:
            raise ApiError("too_late", "Referral codes can be added in the first 7 days only.")
        ref = db.execute("SELECT id FROM users WHERE referral_code=? AND status='active'", (code,)).fetchone()
        if not ref or ref["id"] == user["id"]:
            raise ApiError("bad_code", "That referral code is not valid.")
        shared = db.execute("SELECT 1 FROM devices a JOIN devices b ON a.device_id=b.device_id WHERE a.user_id=? AND b.user_id=? LIMIT 1",
                            (user["id"], ref["id"])).fetchone()
        status, reason = ("rejected", "same_device") if shared else ("pending", None)
        db.execute("INSERT INTO referrals(referrer_id,referee_id,status,reason,created_at) VALUES(?,?,?,?,?)", (ref["id"], user["id"], status, reason, core.now()))
        if shared:
            fraud.add_flag(db, user["id"], "self_referral", "same device as referrer")
            fraud.add_flag(db, ref["id"], "self_referral", "same device as referee")
        return status


# ---------------------------------------------------------------- stats
def streak(db, uid):
    days = {r[0] for r in db.execute("SELECT day FROM daily_stats WHERE user_id=? AND steps>=1000 AND day>=?", (uid, core.day_add(core.today(), -400)))}
    d = core.today()
    if d not in days:
        d = core.day_add(d, -1)
    n = 0
    while d in days:
        n, d = n + 1, core.day_add(d, -1)
    return n


METRICS = {"steps": "SUM(d.steps)", "walk": "SUM(d.walk_m)", "run": "SUM(d.run_m)", "consistency": "SUM(d.steps>=5000)"}


def period_start(period):
    t = datetime.date.fromisoformat(core.today())
    if period == "daily":
        return t.isoformat()
    if period == "weekly":
        return (t - datetime.timedelta(days=t.weekday())).isoformat()
    if period == "monthly":
        return t.replace(day=1).isoformat()
    return "0000-00-00"


def leaderboard(db, user, scope, period, metric, limit):
    if metric not in METRICS or period not in ("daily", "weekly", "monthly", "all") or scope not in ("district", "state", "national"):
        raise ApiError("bad_request", "Unknown scope, period or metric.")
    where, args = "", []
    if scope in ("district", "state"):
        where += " AND u.state=?"
        args.append(user["state"])
    if scope == "district":
        where += " AND u.district=?"
        args.append(user["district"])
    thr = core.cfg(db, "risk_hold_threshold")
    rows = db.execute(
        "SELECT u.id, u.display_name, u.district, u.state, %s AS v FROM daily_stats d JOIN users u ON u.id=d.user_id "
        "WHERE d.day>=? AND d.day<=? AND u.status='active' AND ((u.public_ranking=1 AND u.risk_score<?) OR u.id=?)%s "
        "GROUP BY u.id HAVING v>0 ORDER BY v DESC, u.id" % (METRICS[metric], where),
        [period_start(period), core.today(), thr, user["id"]] + args).fetchall()
    top, me = [], None
    for i, r in enumerate(rows):
        entry = {"rank": i + 1, "display_name": r["display_name"], "district": r["district"], "state": r["state"],
                 "value": round(r["v"], 1), "is_me": r["id"] == user["id"]}
        if r["id"] == user["id"]:
            me = dict(entry, gap_to_next=round(rows[i - 1]["v"] - r["v"], 1) if i else 0)
        # private or under-review users see themselves but never appear in the public list
        if i < limit and (r["id"] != user["id"] or (user["public_ranking"] and user["risk_score"] < thr)):
            top.append(entry)
    place = {"district": user["district"], "state": user["state"], "national": "India"}[scope]
    return {"scope": scope, "period": period, "metric": metric, "place": place, "top": top, "me": me, "participants": len(rows)}
