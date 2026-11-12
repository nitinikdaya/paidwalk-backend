"""End-to-end API tests. Run from backend/:  python -m unittest discover -s tests -v"""
import datetime
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from paidwalk import core, create_app  # noqa: E402

NOON = int(datetime.datetime(2026, 11, 12, 6, 30, tzinfo=datetime.timezone.utc).timestamp())  # 12:00 IST


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = NOON
        self._now = core.now
        core.now = lambda: self.clock
        self.tmp = tempfile.mkdtemp()
        self.app = create_app({"DB_PATH": os.path.join(self.tmp, "t.db"), "TESTING": True})
        self.c = self.app.test_client()
        self.n = 0
        self.seq = 0

    def tearDown(self):
        core.now = self._now

    # helpers ---------------------------------------------------------
    def call(self, method, path, token=None, **json):
        h = {"Authorization": "Bearer " + token} if token else {}
        r = self.c.open(path, method=method, json=json if method != "GET" else None, headers=h)
        return r.status_code, r.get_json()

    def login(self, phone, device="dev-" , name=None, district="Alwar", state="Rajasthan"):
        device = device + phone
        _, r = self.call("POST", "/api/auth/otp/request", phone=phone)
        s, r = self.call("POST", "/api/auth/otp/verify", phone=phone, code=r["dev_code"], device_id=device, platform="test")
        self.assertEqual(s, 200)
        tok = r["token"]
        if name:
            s, r = self.call("PATCH", "/api/me", tok, display_name=name, state=state, district=district)
            self.assertEqual(s, 200, r)
        return tok

    def admin(self):
        tok = self.login("9000000001", name="Boss")
        import sqlite3
        db = sqlite3.connect(self.app.config["DB_PATH"])
        db.execute("UPDATE users SET role='admin' WHERE display_name='Boss'")
        db.commit()
        db.close()
        return tok

    def fund(self, atok, paise=100000):
        s, _ = self.call("POST", "/api/admin/budgets", atok, name="Launch", funded_paise=paise, starts="2026-11-01", ends="2026-11-30")
        self.assertEqual(s, 200)

    def walk(self, tok, steps, minutes=60, ago_min=None, source="health_connect", **extra):
        """Submit one batch ending `ago_min` minutes ago (non-overlapping by default)."""
        self.n += 1
        self.seq += 1
        end = self.clock - (ago_min if ago_min is not None else self.n * 130) * 60
        b = dict(client_batch_id="b%d" % self.seq, source=source, start_ts=end - minutes * 60, end_ts=end, steps=steps, **extra)
        s, r = self.call("POST", "/api/activity/batches", tok, batches=[b])
        self.assertEqual(s, 200, r)
        return r["results"][0], r["today"]


class AuthTests(Base):
    def test_login_setup_and_validation(self):
        s, r = self.call("POST", "/api/auth/otp/request", phone="12345")
        self.assertEqual((s, r["error"]["code"]), (400, "bad_phone"))
        self.call("POST", "/api/auth/otp/request", phone="9876543210")
        s, r = self.call("POST", "/api/auth/otp/verify", phone="9876543210", code="000000x")
        self.assertEqual(s, 401)
        tok = self.login("9876543210")
        s, r = self.call("GET", "/api/me", tok)
        self.assertTrue(r["user"]["needs_setup"])
        s, r = self.call("PATCH", "/api/me", tok, display_name="a b")
        self.assertEqual(r["error"]["code"], "bad_name")
        s, r = self.call("PATCH", "/api/me", tok, display_name="AlwarStrider", state="Rajasthan", district="alwar")
        self.assertEqual((r["user"]["district"], r["user"]["verified"]), ("Alwar", True))
        tok2 = self.login("9876543211")
        s, r = self.call("PATCH", "/api/me", tok2, display_name="AlwarStrider")
        self.assertEqual(s, 409)

    def test_auth_required_and_admin_forbidden(self):
        self.assertEqual(self.call("GET", "/api/wallet")[0], 401)
        self.assertEqual(self.call("GET", "/api/wallet", "nonsense")[0], 401)
        tok = self.login("9876543210", name="Walker1")
        for method, path in (("GET", "/api/admin/overview"), ("POST", "/api/admin/budgets"), ("PUT", "/api/admin/config"), ("POST", "/api/admin/settle")):
            self.assertEqual(self.call(method, path, tok)[0], 403, path)

    def test_otp_rate_limit(self):
        codes = [self.call("POST", "/api/auth/otp/request", phone="9876543210")[0] for _ in range(6)]
        self.assertEqual(codes, [200] * 5 + [429])


class RewardTests(Base):
    def test_tiers_idempotency_and_budget(self):
        a = self.admin()
        tok = self.login("9876543210", name="Walker1")
        # no funded budget: steps count, but no money is created
        res, today = self.walk(tok, 5200)
        self.assertEqual((res["accepted_steps"], today["earned_today_paise"], today["rewards_funded"]), (5200, 0, False))
        self.fund(a)
        res, today = self.walk(tok, 2400)                      # 7,600 -> ₹3 tier
        self.assertEqual(today["earned_today_paise"], 300)
        res, today = self.walk(tok, 2500)                      # 10,100 -> ₹10 tier, topped up not added
        self.assertEqual((today["steps"], today["earned_today_paise"], today["next_tier"]), (10100, 1000, None))
        # resending the same batch id changes nothing
        b = dict(client_batch_id="b%d" % self.seq, source="health_connect", start_ts=self.clock - 9000, end_ts=self.clock - 8000, steps=9999)
        s, r = self.call("POST", "/api/activity/batches", tok, batches=[b])
        self.assertEqual((r["results"][0]["status"], r["today"]["steps"], r["today"]["earned_today_paise"]), ("duplicate", 10100, 1000))
        s, w = self.call("GET", "/api/wallet", tok)
        self.assertEqual((w["summary"]["pending_paise"], w["summary"]["available_paise"]), (1000, 0))

    def test_liability_never_exceeds_budget(self):
        a = self.admin()
        self.fund(a, paise=1500)  # enough for one ₹10 and nothing more
        t1 = self.login("9876543210", name="Walker1")
        t2 = self.login("9876543211", name="Walker2")
        self.assertEqual(self.walk(t1, 10000, minutes=90)[1]["earned_today_paise"], 1000)
        self.assertEqual(self.walk(t2, 10000, minutes=90)[1]["earned_today_paise"], 0)   # ₹10 does not fit in the ₹5 left
        s, o = self.call("GET", "/api/admin/overview", a)
        self.assertLessEqual(o["liabilities_paise"], o["funded_paise"])

    def test_unverified_source_earns_nothing_outside_sandbox(self):
        a = self.admin()
        self.fund(a)
        self.call("PUT", "/api/admin/config", a, reward_sources=["health_connect", "healthkit"])
        tok = self.login("9876543210", name="Walker1")
        res, today = self.walk(tok, 8000, minutes=80, source="web_sensor")
        self.assertEqual((today["steps"], today["reward_steps"], today["earned_today_paise"]), (8000, 0, 0))

    def test_settle_moves_pending_to_available_next_day(self):
        a = self.admin()
        self.fund(a)
        tok = self.login("9876543210", name="Walker1")
        self.walk(tok, 10000, minutes=90)
        self.call("POST", "/api/admin/settle", a)
        self.assertEqual(self.call("GET", "/api/wallet", tok)[1]["summary"]["available_paise"], 0)  # same day: still pending
        self.clock += 86400
        s, r = self.call("POST", "/api/admin/settle", a)
        self.assertEqual(r["released"], 1)
        self.assertEqual(self.call("GET", "/api/wallet", tok)[1]["summary"]["available_paise"], 1000)


class FraudTests(Base):
    def test_impossible_cadence_is_capped_and_flagged(self):
        tok = self.login("9876543210", name="Walker1")
        res, _ = self.walk(tok, 20000, minutes=10)             # 2,000 steps a minute
        self.assertEqual((res["accepted_steps"], res["flags"]), (2000, ["impossible_cadence"]))

    def test_overlap_future_and_old_batches_rejected(self):
        tok = self.login("9876543210", name="Walker1")
        self.walk(tok, 3000, minutes=60, ago_min=60)
        self.assertEqual(self.walk(tok, 3000, minutes=60, ago_min=90)[0]["reason"], "overlap")
        self.assertEqual(self.walk(tok, 100, minutes=10, ago_min=-60)[0]["reason"], "future_timestamp")
        self.assertEqual(self.walk(tok, 100, minutes=10, ago_min=5 * 1440)[0]["reason"], "too_old")
        self.assertEqual(self.call("GET", "/api/activity/today", tok)[1]["steps"], 3000)

    def test_gps_spoofing_signals(self):
        tok = self.login("9876543210", name="Walker1")
        r1, _ = self.walk(tok, 3000, minutes=30, kind="run", gps=True, distance_m=3000)
        self.assertTrue(r1["gps_verified"])
        r2, _ = self.walk(tok, 3000, minutes=30, kind="run", gps=True, distance_m=30000)       # 60 km/h
        self.assertEqual((r2["gps_verified"], r2["flags"]), (False, ["impossible_speed"]))
        r3, _ = self.walk(tok, 3000, minutes=30, gps=True, distance_m=2500, signals={"mock_location": True})
        self.assertEqual((r3["gps_verified"], r3["flags"]), (False, ["mock_location"]))
        s, t = self.call("GET", "/api/activity/today", tok)
        self.assertEqual(t["run_m"], 3000)   # only the genuine run counts as GPS-verified running

    def test_one_signal_never_holds_but_two_do_and_review_releases(self):
        a = self.admin()
        self.fund(a)
        tok = self.login("9876543210", name="Walker1")
        self.walk(tok, 10000, minutes=90, signals={"rooted": True})
        self.assertFalse(self.call("GET", "/api/me", tok)[1]["user"]["on_hold"])                # 30 points: no hold
        self.walk(tok, 5000, minutes=10, samples=[500] * 10)                                     # cadence + robotic pattern
        u = self.call("GET", "/api/me", tok)[1]["user"]
        self.assertTrue(u["on_hold"])
        self.assertEqual(self.call("GET", "/api/me", tok)[0], 200)                               # held, not banned
        self.clock += 86400
        self.call("POST", "/api/admin/settle", a)
        w = self.call("GET", "/api/wallet", tok)[1]["summary"]
        self.assertEqual((w["held_paise"], w["available_paise"]), (1000, 0))
        s, r = self.call("POST", "/api/wallet/withdrawals", tok, amount_paise=5000, upi="me@upi", idempotency_key="k")
        self.assertEqual(r["error"]["code"], "account_on_hold")
        self.assertEqual(self.call("POST", "/api/appeals", tok, message="I was on a treadmill, please check.")[0], 200)
        for f in self.call("GET", "/api/admin/flags", a)[1]["flags"]:
            self.call("POST", "/api/admin/flags/%d/resolve" % f["id"], a, status="cleared")
        self.call("POST", "/api/admin/settle", a)
        self.assertEqual(self.call("GET", "/api/wallet", tok)[1]["summary"]["available_paise"], 1000)

    def test_daily_cap(self):
        tok = self.login("9876543210", name="Walker1")
        total = 0
        for i in range(6):
            total = self.walk(tok, 11000, minutes=60, ago_min=60 + i * 61)[1]["steps"]
        self.assertEqual(total, 60000)


class WalletTests(Base):
    def rich(self):
        a = self.admin()
        self.fund(a)
        tok = self.login("9876543210", name="Walker1")
        for _ in range(6):                                     # six days of ₹10
            self.n = 0
            self.walk(tok, 10000, minutes=90)
            self.clock += 86400
            self.call("POST", "/api/admin/settle", a)
        return a, tok

    def test_withdrawal_rules_idempotency_and_reversal(self):
        a, tok = self.rich()
        bal = lambda: self.call("GET", "/api/wallet", tok)[1]["summary"]["available_paise"]
        self.assertEqual(bal(), 6000)
        post = lambda **k: self.call("POST", "/api/wallet/withdrawals", tok, **k)
        self.assertEqual(post(amount_paise=4000, upi="me@upi", idempotency_key="a")[1]["error"]["code"], "below_minimum")
        self.assertEqual(post(amount_paise=9000, upi="me@upi", idempotency_key="b")[1]["error"]["code"], "insufficient_balance")
        self.assertEqual(post(amount_paise=5000, upi="not a upi", idempotency_key="c")[1]["error"]["code"], "bad_upi")
        s, r = post(amount_paise=5000, upi="me@upi", idempotency_key="d")
        self.assertEqual((s, r["withdrawal"]["status"], bal()), (200, "requested", 1000))
        s, r2 = post(amount_paise=5000, upi="me@upi", idempotency_key="d")     # retry of the same request
        self.assertEqual((r2["withdrawal"]["id"], bal()), (r["withdrawal"]["id"], 1000))
        self.assertEqual(post(amount_paise=5000, upi="me@upi", idempotency_key="e")[1]["error"]["code"], "daily_limit")
        wid = r["withdrawal"]["id"]
        s, r = self.call("POST", "/api/admin/withdrawals/%d/reject" % wid, a, note="name mismatch")
        self.assertEqual((r["withdrawal"]["status"], bal()), ("rejected", 6000))
        self.assertEqual(self.call("POST", "/api/admin/withdrawals/%d/reject" % wid, a)[0], 409)   # cannot refund twice

    def test_sandbox_payout_is_labelled(self):
        a, tok = self.rich()
        s, r = self.call("POST", "/api/wallet/withdrawals", tok, amount_paise=5000, upi="me@upi", idempotency_key="x")
        s, r = self.call("POST", "/api/admin/withdrawals/%d/approve" % r["withdrawal"]["id"], a)
        self.assertEqual((r["withdrawal"]["status"], r["withdrawal"]["provider_ref"][:7]), ("sandbox_paid", "SANDBOX"))
        self.assertTrue(any(x["action"] == "withdrawal.approve" for x in self.call("GET", "/api/admin/audit", a)[1]["audit"]))


class BoardAndReferralTests(Base):
    def test_leaderboard_scopes_privacy_and_gap(self):
        t1 = self.login("9876543210", name="Walker1")
        t2 = self.login("9876543211", name="Walker2")
        t3 = self.login("9876543212", name="Jaipuri", district="Jaipur")
        t4 = self.login("9876543213", name="Hidden1")
        self.call("PATCH", "/api/me", t4, public_ranking=False)
        for tok, steps in ((t1, 4000), (t2, 6000), (t3, 9000), (t4, 8000)):
            self.n = 0
            self.walk(tok, steps, minutes=90)
        s, d = self.call("GET", "/api/leaderboard?scope=district&period=daily", t1)
        self.assertEqual([x["display_name"] for x in d["top"]], ["Walker2", "Walker1"])       # Jaipur and hidden users absent
        self.assertEqual((d["me"]["rank"], d["me"]["gap_to_next"], d["place"]), (2, 2000, "Alwar"))
        s, st = self.call("GET", "/api/leaderboard?scope=state&period=weekly", t1)
        self.assertEqual([x["display_name"] for x in st["top"]], ["Jaipuri", "Walker2", "Walker1"])
        s, h = self.call("GET", "/api/leaderboard?scope=district", t4)
        self.assertEqual((h["me"]["rank"], [x["display_name"] for x in h["top"]]), (1, ["Walker2", "Walker1"]))  # private rank only
        self.assertNotIn("phone", str(d))

    def test_referral_pays_after_real_activity_only(self):
        a = self.admin()
        self.fund(a)
        t1 = self.login("9876543210", name="Walker1")
        t2 = self.login("9876543211", name="Friend1")
        code = self.call("GET", "/api/referral", t1)[1]["code"]
        self.assertEqual(self.call("POST", "/api/referral/apply", t1, code=code)[1]["error"]["code"], "bad_code")   # own code
        self.assertEqual(self.call("POST", "/api/referral/apply", t2, code=code)[1]["status"], "pending")
        self.assertEqual(self.call("POST", "/api/referral/apply", t2, code=code)[1]["error"]["code"], "already_referred")
        self.call("POST", "/api/admin/settle", a)
        refbal = lambda t: sum(x["amount_paise"] for x in self.call("GET", "/api/wallet", t)[1]["transactions"] if x["type"] == "referral")
        self.assertEqual(refbal(t1), 0)                        # friend has not walked yet
        for _ in range(3):
            self.n = 0
            self.walk(t2, 5500, minutes=60)
            self.clock += 86400
        self.call("POST", "/api/admin/settle", a)
        self.call("POST", "/api/admin/settle", a)              # running twice must not pay twice
        self.assertEqual((refbal(t1), refbal(t2)), (500, 200))

    def test_same_device_referral_is_rejected(self):
        t1 = self.login("9876543210", name="Walker1", device="shared")
        _, r = self.call("POST", "/api/auth/otp/request", phone="9876543211")
        _, r = self.call("POST", "/api/auth/otp/verify", phone="9876543211", code=r["dev_code"], device_id="shared9876543210")
        code = self.call("GET", "/api/referral", t1)[1]["code"]
        self.assertEqual(self.call("POST", "/api/referral/apply", r["token"], code=code)[1]["status"], "rejected")
        self.assertEqual(self.call("GET", "/api/fraud/flags", t1)[1]["flags"][0]["signal"], "self_referral")

    def test_delete_account_erases_personal_data(self):
        tok = self.login("9876543210", name="Walker1")
        self.walk(tok, 3000)
        self.assertEqual(self.call("POST", "/api/me/delete", tok)[0], 200)
        self.assertEqual(self.call("GET", "/api/me", tok)[0], 401)
        import sqlite3
        db = sqlite3.connect(self.app.config["DB_PATH"])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE phone LIKE '+91%' AND status='deleted'").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM activity_batches").fetchone()[0], 0)
        db.close()


if __name__ == "__main__":
    unittest.main()
