"""Command line tasks.

  python manage.py run                      start a development server on port 8000
  python manage.py make-admin 9876543210    give an existing user the admin role
  python manage.py settle                   nightly job (put it in cron at 00:30 IST)
"""
import sys

from paidwalk import create_app, engine
from paidwalk.db import get_db
from paidwalk.routes import norm_phone

app = create_app()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        app.run(host="0.0.0.0", port=8000)
    elif cmd == "make-admin":
        with app.app_context():
            n = get_db().execute("UPDATE users SET role='admin' WHERE phone=?", (norm_phone(sys.argv[2]),)).rowcount
            print("updated" if n else "no user with that phone; sign in once in the app first")
    elif cmd == "settle":
        with app.app_context():
            print(engine.settle(get_db()))
    else:
        print(__doc__)
