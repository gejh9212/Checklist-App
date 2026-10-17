# Safely import your existing SQLite data

Import is optional and is never triggered by sign-in. The original file is not opened through the local app's Database constructor, so preview does not run local resets or change schema/data. Import reads SQLite in read-only mode.

1. Set up the **new** Supabase project and confirm synchronization with disposable test data first ([setup.md](setup.md)).
2. Close the local-only app so the preview is easy to review. The backup mechanism is still SQLite's consistent backup API, not an unsafe byte copy of an active database.
3. Launch cloud mode and sign into the correct account. Check that this is the account you intend to use on your phone.
4. Click **Import SQLite…** and select `%LOCALAPPDATA%\ChecklistApp\checklists.db`.
5. Read the preview: checklist count, task count, and account timezone. Choose **No** to do a dry run without modifying cloud data. Simply signing into an empty cloud account never replaces local data.
6. Choose **Yes** only after reviewing. The app writes a small source-identity marker beside the SQLite file (`.db.cloud-import.json`) and creates a new timestamped `.before-cloud-...db` backup beside it. These files are ignored by Git and existing filenames are never overwritten. Both operations must succeed before uploading.
7. The consistent backup is checked and compared with the preview. If the source changed after preview, the app stops without uploading; preview again.
8. A single server transaction adds the imported checklists/tasks alongside existing cloud data. Stable UUIDs are scoped to the source and signed-in account. An import ledger prevents repeated imports, including after a network timeout or after you later delete some imported cloud tasks. It never clears unrelated cloud records.
9. The app downloads the result and checks IDs and field values. Review counts and task content on both devices before relying on cloud mode. Keep the original file and backup.

Normal completion flags transfer. Daily/weekly flags transfer only if `last_processed_period` matches the current account period, preventing an old completed day/week from marking the new period complete. Task names, descriptions, priorities, due dates, and order transfer independently of completion. The original SQLite database did not keep past completion rows, so past history cannot be reconstructed.

The initial content-derived source ID is recorded by the marker after confirmation. Keep that marker with the original database: it keeps the same source identity even if you later add/remove checklists locally. Copying or moving a database **without** its marker and changing its contents may be interpreted as a different source. The importer is a one-time migration, not a local-to-cloud synchronization bridge. If a previously imported source has changed, the server refuses the changed import rather than duplicating/overwriting it. Review and manually move those later changes, or seek a separate incremental-migration implementation. Do not remove markers or ledger rows to force a reimport.

If the import's response is lost, its outcome is uncertain, not necessarily a failure. Reconnect and preview the **same source** again. The server returns the existing import receipt without creating duplicates. If it reports that this source was already imported, tasks deleted after that import are intentionally not recreated.

The importer adds shared appearance/completed-at-bottom/confirmation preferences. It does not import window position, the remembered selected checklist, passwords, or credentials. It also does not replace the account timezone; configure that before import.

## Recovery

Never delete or restore over your only personal-data copy. Keep local and cloud modes independent until the transfer has been reviewed. To return to the original app, launch without `--cloud`; its original file remains in Local AppData. An import error rolls back the cloud transaction and leaves that original and backup intact. For an ambiguous response, inspect/refresh before retrying.

A cloud **Back up database** action exports the last downloaded snapshot as JSON, not a SQLite database or a complete Supabase backup. It does not include all historical completions or Auth records. Use Supabase's own database backup/export facilities for a complete cloud backup. Local-only mode still produces a SQLite backup.
