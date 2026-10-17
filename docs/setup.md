# First-time cloud setup

The original local-only Windows app still works without Supabase. Cloud mode is separate and opt-in. It does not upload, clear, or reset your original SQLite database. This branch is an upgrade under development: live Supabase authentication/Realtime and native builds still require the checks below.

## 1. Create your Supabase project

1. Go to https://supabase.com/dashboard and create an account.
2. Create a **new project**. Give it a name such as ChecklistApp, choose a region near you, and set a strong database password. Keep the database password in your password manager; do not send it in chat or commit it.
3. Wait until the database is running.
4. Open the project's **SQL Editor → New query**. Open the provided repository file `supabase/migrations/202610170001_sync.sql`, copy its contents into the editor, and click **Run**. You are applying the supplied code, not writing it yourself. Apply this file once to the new project; it is a versioned migration, not a rerunnable setup script. Do not paste the test bootstrap file into Supabase.
5. Under **Authentication → Sign In / Providers** (the exact menu wording can vary), enable Email with email/password authentication. Keep email confirmation enabled. For confirmation links, configure **Authentication → URL Configuration → Site URL** to an HTTPS page you control that tells users to return to the app after confirmation. Do not put tokens on a public page or disable confirmation just to make a test pass. No mobile deep-link callback is needed for this version: open the confirmation email, follow its link, return to the app, and sign in normally.
6. Under database replication/Realtime publication settings, confirm `public.profiles` is included in `supabase_realtime`. The migration adds it automatically if the publication already exists. The clients subscribe to **owner-visible profile revision changes** and refetch an authoritative snapshot. Tasks themselves do not need to be broadcast publicly. RLS remains enabled on every table.
7. Under **Project settings → API / API Keys**, copy the project URL and the **publishable key** (`sb_publishable_...`). Never copy `sb_secret_...`, `service_role`, your database password, or a personal access token into a client.

You now have the two non-secret client configuration values: project URL and publishable key. Authentication and RLS still control access to your data. No server you must host is needed. Supabase quotas, email limits, backups, and project pausing depend on your plan; check them before relying on the service.

## 2. Configure and run Windows

Open PowerShell in the project folder. Install Python 3.12+ first if needed.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Replace only the placeholder URL and publishable key in `.env`, then save it. `.env` is excluded from Git. This file must never contain a password, service-role key, or secret key.

Launch cloud mode:

```powershell
.\.venv\Scripts\python.exe -m checklist_app --cloud
```

Use **Create account**, check your email, then sign in with your email and password. The app saves the session in **Windows Credential Manager**, using Python keyring. Sessions are not stored in SQLite or `.env`. Linux development requires an unlocked Secret Service keyring; if secure storage is unavailable, the app refuses to fall back to plain text. macOS uses Keychain.

The cloud account starts empty. This does not mean your old data was deleted. Use **Import SQLite…** only after reading [migration.md](migration.md), or create a new cloud checklist. You can always open the existing independent local app with:

```powershell
.\.venv\Scripts\python.exe -m checklist_app
```

The old SQLite file remains `%LOCALAPPDATA%\ChecklistApp\checklists.db`. Cloud read caches are separate files under `%LOCALAPPDATA%\ChecklistApp\cloud\<project>\<account>.db`. Window position and selected checklist are device-local. Appearance, completed-at-bottom, confirmation preferences, and timezone are shared. Signing out removes this device's saved session and closes the cloud view; the account-specific read cache remains on disk but is hidden until that account signs in again. These caches contain checklist text, so protect your OS account and disk.

In the cloud window, **Refresh cloud** immediately refetches. Automatic refresh also runs on Realtime updates and every 15 seconds. Status distinguishes saved, saving, offline, and unconfirmed outcomes. Offline mode is read-only. A request that times out may have reached the server: refresh before retrying. Changes from stale editor revisions or periods are rejected and the draft is kept for review. This first release uses a conservative **account-wide revision**: even edits to different tasks can require a refresh, to protect against silent overwrites.

The desktop currently requires relaunching cloud mode to sign back in after an expired/revoked session; use Sign out, then the launch command again. The app does not try to replay expired-session writes.

## 3. Configure and run mobile

Install Flutter **3.35.7 or a later compatible stable release** from https://docs.flutter.dev/get-started/install. The Android and iOS projects are already in `mobile/`; this is a Flutter native application, not a website. Its native scaffolding is based on the official Flutter 3.35.7 templates; licenses are included.

```powershell
cd mobile
Copy-Item config.example.json config.local.json
notepad config.local.json
flutter pub get
flutter run --dart-define-from-file=config.local.json
```

Put the **same** project URL and publishable key into `config.local.json`. Do not include a secret key. This private configuration is ignored by Git. Choose an Android device/emulator, or use a Mac for an iOS simulator/device. Run `flutter doctor` to diagnose missing SDK tools. Android SDK and iOS signing setup are explained in [deployment.md](deployment.md).

Mobile sessions use Android encrypted storage or iOS Keychain via `flutter_secure_storage`. They are never stored in the JSON read cache. Android backup of this app is disabled so encrypted session data is not restored with an unavailable device key. iOS session accessibility is restricted to this device. The read cache is stored in app support storage under a project/account-specific name. Sign out hides it; uninstalling generally removes app support files, while iOS Keychain behavior follows the OS policy. Use Sign out before handing a device to someone else.

The mobile app supports checklist/task CRUD, priorities/descriptions/due dates, search/filter, progress, themes/shared settings, and ordering. Long-press a task in the unfiltered list to reorder it (completed-at-bottom must be off). Tap a category's reorder icon to reorder checklists in that category. Daily/weekly next reset times are supplied by the server in the account timezone. Pull to refresh, use the refresh icon, or resume the app to fetch again.

## 4. Check synchronization before importing important data

1. Sign into both devices with the same account.
2. Create a test checklist on Windows; confirm it appears on mobile.
3. Add a task on mobile. Confirm it appears on Windows, with the same priority and due date.
4. Complete it on mobile; Windows progress should update automatically or after Refresh.
5. Rename and reorder on each device. Confirm the other device matches.
6. Temporarily disconnect one device. It should show cached data and reject edits. Reconnect and refresh; authoritative changes should appear.
7. Open an editor on both devices. Save on one, then save the older draft on the other. A conflict must be shown; the old draft must not overwrite silently.
8. Sign out and sign into a **different** test account. It must not show the first account's cloud records or cache.

Do not change the computer/phone clock to test resets. PostgreSQL calculates periods using server time and the account timezone, default `Asia/Seoul`. Normal completion never expires; daily periods start at 06:00 and weekly periods start Monday at 06:00. Changing account timezone explicitly starts new recurring generations and preserves old completion rows. Historical completion records are retained in Supabase; a history browser is not implemented yet.

## Cloud workspace prerequisites

The prepared environment currently blocks `storage.googleapis.com`, which hosts the official Flutter SDK artifacts. An additive network draft for that hostname was saved. Review/save it in environment settings and publish to enable Flutter installation. A future live test here also needs the exact `<your-project>.supabase.co` destination allowed, including HTTPS/WSS support. Do not replace unknown existing domain rules or disable TLS verification. No Supabase credentials or bindings were present during implementation.

See [testing.md](testing.md) for what was actually verified, and which checks remain external.
