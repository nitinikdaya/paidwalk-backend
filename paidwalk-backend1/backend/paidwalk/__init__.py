"""PaidWalk backend. One Flask app serves the JSON API under /api and the web app from /."""
import os

from flask import Flask, g, jsonify, request, send_from_directory

from .core import ApiError
from .db import init_db

WEB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "web"))


def create_app(config=None):
    app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")
    app.config.update(
        DB_PATH=os.environ.get("PAIDWALK_DB", os.path.join(os.getcwd(), "paidwalk.db")),
        SECRET_KEY=os.environ.get("PAIDWALK_SECRET", "dev-only-change-me"),
        SANDBOX=os.environ.get("PAIDWALK_SANDBOX", "1") == "1",   # sandbox: OTP shown on screen, payouts simulated
        PAYOUT_PROVIDER=os.environ.get("PAIDWALK_PAYOUT", "sandbox"),
        SMS_SENDER=None,                                         # set to a function(phone, code) for real SMS
        MAX_CONTENT_LENGTH=256 * 1024,
    )
    app.config.update(config or {})
    if not app.config["SANDBOX"] and app.config["SECRET_KEY"] == "dev-only-change-me":
        raise RuntimeError("Set PAIDWALK_SECRET before running with PAIDWALK_SANDBOX=0.")
    init_db(app.config["DB_PATH"])

    from .admin import admin
    from .routes import api
    app.register_blueprint(api)
    app.register_blueprint(admin)

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.errorhandler(ApiError)
    def api_error(e):
        return jsonify(error={"code": e.code, "message": e.message}), e.status

    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith("/api/"):
            return jsonify(error={"code": "not_found", "message": "No such endpoint."}), 404
        return send_from_directory(WEB_DIR, "index.html")

    @app.errorhandler(405)
    def bad_method(_e):
        return jsonify(error={"code": "method_not_allowed", "message": "Method not allowed."}), 405

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception("unhandled error: %s", e)
        return jsonify(error={"code": "server_error", "message": "Something went wrong. Please try again."}), 500

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:"
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    return app
