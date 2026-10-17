from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QMessageBox
from .migration import preview, backup_source, validate_import, remember_source
from .store import SyncError


def import_sqlite(window, store, default_path):
    if not store.online:
        raise SyncError('Reconnect before previewing a cloud import.')
    path, _ = QFileDialog.getOpenFileName(window,'Choose existing ChecklistApp database',str(default_path),'SQLite database (*.db)')
    if not path:
        return
    manifest = preview(path,store.cache.user_id)
    message = (f"Import preview: {len(manifest['checklists'])} checklists and {len(manifest['tasks'])} tasks.\n"
               f"Account timezone: {store.snapshot['timezone']}.\n"
               'A new backup will be created beside the SQLite file before any upload. The original is never overwritten. '
               'Existing cloud checklists will stay. Recurring completions transfer only when the stored source period matches the account period.\n\n'
               'Import these rows into the signed-in cloud account now?')
    if QMessageBox.question(window,'Confirm cloud import',message,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
        return
    if not store.refresh() and not store.online:
        raise SyncError('Could not refresh cloud data. Import was not started.')
    remember_source(path,manifest)
    backup = backup_source(path)
    # Preview the consistent backup, not a changing source file.
    remember_source(backup,manifest)
    backed_up = preview(backup,store.cache.user_id)
    if backed_up['content_hash']!=manifest['content_hash']:
        raise SyncError('The SQLite source changed after preview. A backup was made, but nothing was uploaded. Preview again.')
    store.busy = True
    try:
        result = store.runner(lambda:store.transport.import_manifest(store.snapshot['revision'],manifest))
    except Exception:
        store.online = False
        raise SyncError('Import could not be confirmed. Refresh and preview the SAME source again; server import IDs prevent duplicates. Your original and backup remain intact.') from None
    finally:
        store.busy = False
    store.refresh()
    if not store.online:
        raise SyncError('Import response arrived but validation needs a connection. Keep your backup and reconnect before retrying.')
    if not result.get('already_imported'):
        validate_import(manifest,store.snapshot)
    window.refresh_sidebar()
    QMessageBox.information(window,'Import complete',f"{'This source was already imported; no rows were duplicated.' if result.get('already_imported') else 'Imported rows were downloaded and validated.'}\nBackup: {Path(backup).name}")
