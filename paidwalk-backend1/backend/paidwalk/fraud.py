"""Anti-cheat. The client only makes *claims*; this module decides what is accepted.

Principles: every signal has a weight; the user's risk score is the sum of open/confirmed
flags from the last 30 days; nobody is banned automatically. At or above the hold threshold,
rewards are held and withdrawals paused until a reviewer clears or confirms the flags.
"""
from . import core

WEIGHTS = {
    "impossible_cadence": 30,     # more steps per minute than a human can take
    "robotic_pattern": 30,        # identical per-minute counts (shaker / script)
    "mock_location": 40,          # OS reported a mock location provider
    "device_integrity": 30,       # rooted / tampered app / failed attestation
    "impossible_speed": 30,       # GPS distance implies a vehicle
    "stride_mismatch": 15,        # GPS distance does not match step count
    "device_farm": 35,            # one device used by more than two accounts
    "duplicate_activity": 10,     # overlapping time range submitted again
    "manipulated_timestamp": 30,  # future timestamps or client-reported clock tampering
    "daily_cap": 20,              # hit the daily step ceiling
    "abnormal_spike": 15,         # far above the user's own recent average
    "self_referral": 30,          # referrer and referee share a device
    "stationary_steps": 20,       # GPS on but the phone did not move (shaking in place)
}
MAX_CADENCE = 220     # steps/min above this is flagged
ACCEPT_CADENCE = 200  # ... and accepted steps are capped to this rate
MAX_SPEED = 7.0       # m/s (~25 km/h)


def add_flag(db, user_id, signal, detail="", batch_id=None, day=None):
    """At most one flag per user, signal and day, so one bad sync cannot snowball."""
    db.execute(
        "INSERT OR IGNORE INTO fraud_flags(user_id,batch_id,day,signal,weight,detail,created_at) VALUES(?,?,?,?,?,?,?)",
        (user_id, batch_id, day or core.today(), signal, WEIGHTS[signal], detail, core.now()))
    recompute_risk(db, user_id)


def recompute_risk(db, user_id):
    since = core.now() - 30 * 86400
    s = db.execute("SELECT COALESCE(SUM(weight),0) FROM fraud_flags WHERE user_id=? AND status IN('open','confirmed') AND created_at>?",
                   (user_id, since)).fetchone()[0]
    db.execute("UPDATE users SET risk_score=? WHERE id=?", (min(100, s), user_id))
    return min(100, s)


def evaluate(db, user_id, b, shared_device_users):
    """Returns dict(accepted, gps_ok, flags=[(signal, detail)], reject=None|reason)."""
    n = core.now()
    start, end, steps = b["start_ts"], b["end_ts"], b["steps"]
    out = {"accepted": 0, "gps_ok": False, "flags": [], "reject": None}
    if end <= start or steps < 0:
        out["reject"] = "bad_range"
        return out
    if end > n + 300:
        out["flags"].append(("manipulated_timestamp", "batch ends in the future"))
        out["reject"] = "future_timestamp"
        return out
    if start < n - 3 * 86400:
        out["reject"] = "too_old"
        return out
    if end - start > 7200:
        out["reject"] = "batch_too_long"
        return out
    if db.execute("SELECT 1 FROM activity_batches WHERE user_id=? AND status='accepted' AND start_ts<? AND end_ts>? LIMIT 1",
                  (user_id, end, start)).fetchone():
        out["flags"].append(("duplicate_activity", "time range overlaps an accepted batch"))
        out["reject"] = "overlap"
        return out

    minutes = max((end - start) / 60.0, 1 / 6)
    accepted = steps
    cadence = steps / minutes
    if cadence > MAX_CADENCE:
        out["flags"].append(("impossible_cadence", "%d steps/min" % cadence))
        accepted = int(ACCEPT_CADENCE * minutes)
    samples = b.get("samples") or []
    if len(samples) >= 10 and samples[0] > 0 and len(set(samples)) == 1:
        out["flags"].append(("robotic_pattern", "%d identical per-minute samples" % len(samples)))

    sig = b.get("signals") or {}
    dist = b.get("distance_m")
    gps_ok = bool(b.get("gps")) and isinstance(dist, (int, float)) and dist >= 0
    if sig.get("mock_location"):
        out["flags"].append(("mock_location", "mock location provider active"))
        gps_ok = False
    if sig.get("rooted") or sig.get("integrity") == "failed":
        out["flags"].append(("device_integrity", "device or app integrity check failed"))
    if sig.get("clock_tampered"):
        out["flags"].append(("manipulated_timestamp", "client reported clock change"))
    if gps_ok:
        speed = dist / (end - start)
        if dist < 20 and steps > 300:
            # GPS reported but the phone barely moved while "steps" piled up: shaking in place.
            out["flags"].append(("stationary_steps", "%d steps over %.0f m" % (steps, dist)))
            gps_ok = False
        elif speed > MAX_SPEED:
            out["flags"].append(("impossible_speed", "%.1f m/s" % speed))
            gps_ok = False
        elif steps > 0 and not (0.3 <= dist / steps <= 2.5):
            out["flags"].append(("stride_mismatch", "%.2f m per step" % (dist / steps)))
            gps_ok = False
    if shared_device_users > 2:
        out["flags"].append(("device_farm", "%d accounts on this device" % shared_device_users))
    out["accepted"], out["gps_ok"] = accepted, gps_ok
    return out


def check_spike(db, user_id, day):
    rows = db.execute("SELECT steps FROM daily_stats WHERE user_id=? AND day<? AND day>=?",
                      (user_id, day, core.day_add(day, -14))).fetchall()
    cur = db.execute("SELECT steps FROM daily_stats WHERE user_id=? AND day=?", (user_id, day)).fetchone()
    if cur and len(rows) >= 3:
        avg = sum(r[0] for r in rows) / len(rows)
        if cur[0] > 20000 and cur[0] > 5 * max(avg, 1):
            add_flag(db, user_id, "abnormal_spike", "%d steps vs average %d" % (cur[0], avg), day=day)
