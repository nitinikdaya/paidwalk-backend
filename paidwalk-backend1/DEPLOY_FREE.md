# Put the PaidWalk backend online for free (Render)

This gives you a public web address like `https://paidwalk-api.onrender.com`.
You put that address into the Android app, and logins/steps/wallet start working.
No cost. You don't install anything.

## Steps

1. Make a free **GitHub** account (if you don't have one): https://github.com
2. Create a new repository, e.g. `paidwalk-backend`. Private is fine.
3. Upload the whole `paidwalk` folder's contents to that repo
   (**Add file → Upload files** → drag in the `backend` folder, the `web` folder,
   `render.yaml`, and `README.md` → Commit). Make sure `render.yaml` sits at the
   **top level** of the repo.
4. Make a free account at **Render**: https://render.com (sign in with GitHub).
5. In Render click **New → Blueprint**, pick your `paidwalk-backend` repo, and
   **Apply**. Render reads `render.yaml` and builds it (~3–5 minutes).
6. When it goes live, Render shows a URL like `https://paidwalk-api.onrender.com`.
   Open it in a browser — you should see the PaidWalk web app. The API is at
   `.../api/config`.

## Then make yourself admin

Rewards only appear after a funded budget exists, and only an admin can add one.

1. Open your Render URL on your phone or browser, sign in with a mobile number.
   In sandbox the login code is shown on screen.
2. Back in Render, open your service → **Shell** tab, and run:
   ```
   cd backend && python manage.py make-admin 9876543210
   ```
   (use the number you signed in with)
3. Open `https://your-url.onrender.com/admin.html` → add a funded budget.

## Point the Android app at it

In the app project, open `lib/config.dart` and set:
```
const String kApiBaseUrl = "https://paidwalk-api.onrender.com";
```
(use your real Render URL). Rebuild the APK (the GitHub Actions build in GET_APK.md).

## Good to know on the free plan

- The service **sleeps after 15 minutes idle**; the next request wakes it (takes
  ~30 seconds the first time). Fine for testing, not for real users.
- Storage is **temporary**: a redeploy or sleep can reset the database, so test
  accounts and balances may disappear. That's expected until you move to the
  Hostinger VPS (where data is permanent). The code is identical either way.
- If Render asks for a card even on the free plan, the alternative is a Hostinger
  VPS (permanent, small monthly cost) — tell me and I'll give those commands instead.
