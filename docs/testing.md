# Validation and remaining checks

## Results actually obtained in the Linux workspace

- **43 Python tests passed**, with **zero skips** in the final full run using a disposable PostgreSQL 17 instance. This includes the original 20 tests, a cloud Qt regression test, 12 client/configuration/migration tests, and 10 real PostgreSQL integration tests.
- The complete SQL migration was applied successfully to a fresh disposable database, not just patched into a pre-existing test schema.
- PostgreSQL tests exercise RLS isolation, anonymous access denial, denial of direct writes, inaccessible private functions, concurrent writes from two connections, duplicate completion prevention, historical periods, daily/weekly boundaries, Seoul/New York daylight saving boundaries, ordering, atomic/idempotent import, and the desktop adapter's create/edit/complete/delete flow through real SQL.
- Local client tests cover offline read cache, blocked writes, reconnection, account separation, period payloads independent of the device clock, preserved uncertain drafts, configuration key rejection, secure-storage adapter behavior with an in-memory test backend, stable import IDs, and original SQLite byte preservation.
- Qt tests use offscreen rendering with temporary databases, including cloud UUID sidebar ordering, account reset labels, and offline control disabling. No personal database is used.
- All six Dart source/test files passed an independent Dart grammar parse. **This is only a syntax check**, not Flutter analysis, execution, or a native build.
- Gradle's binary distribution and packaged wrapper JAR passed their official SHA256 checks. Python dependency compatibility was checked with `pip check`.

The SQL tests emulate `auth.uid()` in an isolated local database. They prove database authorization behavior under those claims, **not Supabase-hosted JWT verification or authentication service behavior**. The two-client contract test uses the desktop adapter against SQL, not an executed Flutter client.

## Python 3.15 compatibility update

Current pins are PySide6 6.12.0, PyInstaller 6.22.3, and psycopg binary 3.3.6. The complete 43-test suite passed on CPython **3.15.0rc3 on Linux**, using the new dependencies and real disposable PostgreSQL. The available managed Python 3.15 build was a release candidate; this does not establish testing on a final Windows release. Standard Windows x64/Python 3.15 dependencies also resolved successfully in a binary-only cross-platform dependency check. PyInstaller 6.22.3 starts successfully on this interpreter; a Windows executable still needs a native build and run. Free-threaded Python is not supported by the selected Qt wheels.

The workflow now checks Python 3.12 and 3.15 with PostgreSQL on Linux and adds a Windows x64/Python 3.15 GUI/storage test job. Those GitHub checks must run after the compatibility commit is pushed; a dependency resolution is not a Windows runtime test. Update your local repository before reinstalling because older copies pin incompatible packages.

## Run Python tests yourself

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Without `CHECKLIST_TEST_PG_DSN`, the ten PostgreSQL integration tests are explicitly skipped; this does not validate database security. The other 33 tests run locally, with temporary files inside `tests/`. Qt may print offscreen-platform messages; those are separate from the test result.

For database checks, create an **empty, disposable local PostgreSQL database** with a test administrator. Never use your production database or your personal Supabase project. Apply, in order:

```text
supabase/tests/local_bootstrap.sql
supabase/migrations/202610170001_sync.sql
```

Set `CHECKLIST_TEST_PG_DSN` to that test database in your local environment (not Git), then run the same unittest command. The bootstrap creates a minimal test Auth schema and test roles, so it must **never** be applied to Supabase. The SQL tests create and remove only their own random test users and dependent records. They need a local administrator connection to emulate separate authenticated sessions and inspect invariants.

A GitHub Actions workflow is provided for manual dispatch or pull requests after you approve pushing this branch. It starts disposable PostgreSQL, applies the test bootstrap/migration, runs all Python tests, and has a separate Flutter analysis/test job. It does not deploy to Supabase, build signed releases, or access production secrets. The `disposable-ci-only` password is deliberately public and belongs only to the ephemeral CI database.

## Flutter tests (not yet executed here)

From `mobile/`, after SDK setup/network access:

```text
flutter pub get
dart format lib test
flutter analyze
flutter test
```

The checked-in tests cover controller reconnection, cached viewing, account cache isolation, stale editor revision rejection, completion period payloads, preservation of failed drafts, and home progress rendering on a small phone layout. Running them needs Flutter and its dependencies; these tests are currently **unrun** because the official SDK artifacts are blocked by the workspace network policy. The grammar parse does not replace them. Resolve and commit `pubspec.lock` after the first successful analysis/test run.

## Hosted and physical-device checks still required

Create a Supabase project first ([setup.md](setup.md)). Use two temporary accounts and disposable checklists before importing personal data.

1. Email/password sign-up, confirmation, sign-in, wrong-password errors, logout, session persistence after restart, token refresh, password changes/revoked sessions, and signing into a different account.
2. Windows Credential Manager and Android/iOS secure-storage behavior. No real OS credential-store session has been created in this Linux workspace.
3. Windows/mobile bidirectional creation, rename/edit, completion/uncompletion, ordering, settings, deletion, Realtime invalidation, periodic refresh recovery, reconnection, and foreground resume. Realtime isn't the only refresh mechanism.
4. Data isolation with each account's own authenticated SDK session, including attempted foreign checklist/task IDs and anonymous requests. Local emulated claims do not replace real hosted Auth testing.
5. Actual daily/weekly boundary observations in the configured account timezone. Server calculation functions are tested using fixed UTC instants; no device clock changes are needed.
6. Confirmed import into disposable cloud data, repeated import, source changes after import, preservation of original/backup files, and manual review on both devices. No real migration has run.
7. Windows 10/11 `.exe`, signed Android release APK install/update, iOS simulator and signed physical-device builds, smaller screens, long task titles, accessibility text sizes, and offline cache availability. None of these native builds were produced here.

Offline editing, a history browser, incremental legacy SQLite synchronization, password-reset deep links, app-store deployment, and push notifications are intentionally outside this first version. Historical cloud completion rows are preserved until their parent task/checklist is explicitly deleted; no history screen exists yet.
