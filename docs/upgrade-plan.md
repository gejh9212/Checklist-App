# Upgrade plan and preservation contract

Branch: `upgrade/windows-mobile-sync`. Existing desktop sources stay at the repository root so imports, Git history, and Windows packaging continue to work. The separate Flutter application lives in `mobile/`; managed database migrations live in `supabase/migrations/`.

## Existing architecture (inspected before implementation)

- `checklist_app/database.py`: SQLite schema version 1, integer checklist/task IDs, settings JSON, transaction/savepoint helpers, five first-launch default checklists, backups.
- `scheduling.py`: local calendar daily/weekly period keys at 06:00; SQLite completion flags reset transactionally.
- `gui.py`, `sidebar.py`: reusable PySide6 desktop, checklist edit menu, category-safe drag order, task CRUD, search/filter, progress, theme and window settings.
- `__main__.py`, `windows_entry.py`, `build_windows.ps1`: development and Windows PyInstaller entry points.
- Existing tests cover local SQLite and offscreen Qt behavior. Keep these running unchanged alongside new cloud tests.

## Stages

1. Preserve the local-only app as the default. Cloud is an explicit opt-in command; never open or reset the original SQLite database merely by signing in.
2. Add RLS-protected PostgreSQL tables, stable UUIDs, server-derived UTC timestamps/account periods, revision-based conflict rejection, a transactional mutation RPC, a consistent snapshot RPC, and Realtime invalidation.
3. Adapt the existing desktop GUI through the same database interface. Use a separate per-project/account SQLite read cache, Windows Credential Manager for sessions, authoritative refresh on login/reconnect, and background network work. Disable cloud editing when disconnected; no hidden offline write queue.
4. Separate historical completion records from tasks. Both clients use server-provided period keys. No scheduled destructive reset job and no client-clock-based cloud writes.
5. Create Flutter Android/iOS project and mobile CRUD, reordering, progress, account settings, secure sessions, read cache, and Realtime plus periodic refetch.
6. Add read-only SQLite migration preview, stable content-derived import IDs, exclusive timestamped backup, explicit confirmation, atomic idempotent server import, and post-import validation. Import into existing cloud data without clearing anything.
7. Run local storage, Qt, timezone, client synchronization, SQL authorization/concurrency, and Flutter tests where the available tools support them. Hosted Auth/Realtime and physical-platform checks remain distinct from local tests.

## Conflict and offline policy

Every mutation carries the account revision it was based on. The server locks the account and rejects a stale revision, stale period, or mismatched checklist generation. Clients retain pending editor text on conflicts, show an error, and refetch rather than silently overwrite. Deletions are transactional and no disconnected client can resurrect a deleted row. A timed-out write is reported as uncertain and requires an authoritative fetch before another edit.

Shared settings: appearance, completed-at-bottom, confirmation preferences, account timezone. Window geometry, selected checklist, and remember-selection are device-local. Sessions never live in application tables or plain SQLite. Different users/projects have separate cache and credential namespaces. Logging out hides cached data and removes this device's saved session.

## External prerequisites

A user-owned Supabase project and email/password Auth configuration are required for live device testing. Only its project URL and publishable key belong in client configuration. Never use a service-role/secret key in a client. Schema deployment, real import, push, merge, and production deployment require user approval. Android release builds require an Android SDK and signing key; iOS requires macOS/Xcode and Apple signing. Windows EXEs must be built and validated on Windows.
