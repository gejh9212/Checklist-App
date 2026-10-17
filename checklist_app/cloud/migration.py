"""Read-only preview and consistent SQLite backup. No original Database constructor."""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
import json
import sqlite3


def preview(path, user_id):
    path = Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        if db.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError('Only the existing ChecklistApp schema version 1 can be imported.')
        lists = [dict(r) for r in db.execute('SELECT * FROM checklists ORDER BY display_order,id')]
        tasks = [dict(r) for r in db.execute('SELECT * FROM tasks ORDER BY checklist_id,display_order,id')]
        settings = {r['key']:json.loads(r['value']) for r in db.execute("SELECT * FROM settings WHERE key IN ('light','completed_bottom','confirm')")}
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('SQLite validation failed. Preserve this file and repair a separate copy first.')
    # Stable identity for the same source, including later edits. Does not depend on its path.
    identity = [(c['id'],c['created_at']) for c in lists]
    if not identity:
        raise ValueError('There are no checklists to import.')
    source_file = path.with_suffix(path.suffix+'.cloud-import.json')
    source = UUID(json.loads(source_file.read_text())['source_id']) if source_file.exists() else uuid5(NAMESPACE_URL,json.dumps(identity,separators=(',',':')))
    namespace = uuid5(UUID(user_id),str(source))
    ids = {c['id']:str(uuid5(namespace,'checklist:'+str(c['id']))) for c in lists}
    converted_lists = [{**{key:c[key] for key in ('name','type','display_order','last_processed_period')},'id':ids[c['id']]} for c in lists]
    converted_tasks = [{**{key:t[key] for key in ('title','description','priority','due_date','display_order','is_completed')},'id':str(uuid5(namespace,'task:'+str(t['id']))),'checklist_id':ids[t['checklist_id']]} for t in tasks]
    manifest = {'source_id':str(source),'checklists':converted_lists,'tasks':converted_tasks,'settings':settings}
    manifest['content_hash'] = sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return manifest


def remember_source(path, manifest):
    marker = Path(path).with_suffix(Path(path).suffix+'.cloud-import.json')
    try:
        with marker.open('x',encoding='utf-8') as output:
            json.dump({'source_id':manifest['source_id']},output)
    except FileExistsError:
        if json.loads(marker.read_text())['source_id']!=manifest['source_id']:
            raise RuntimeError('Import source identity changed. Preview again before importing.')


def backup_source(path):
    source = Path(path).resolve(strict=True)
    destination = source.with_name(source.stem+'.before-cloud-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]+'.db')
    with destination.open('xb'):
        pass
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as original, closing(sqlite3.connect(destination)) as backup:
        original.backup(backup)
        if backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise RuntimeError('Backup validation failed. Cloud import was not started.')
    return destination


def validate_import(manifest, snapshot):
    source_lists = {row['id']:row for row in manifest['checklists']}
    cloud_lists = {row['id']:row for row in snapshot['checklists']}
    for name in ('checklists','tasks'):
        cloud = {row['id']:row for row in snapshot[name]}
        for row in manifest[name]:
            if row['id'] not in cloud:
                raise RuntimeError('Import validation could not find every imported row. Preserve the backup and contact support before retrying.')
            for key, value in row.items():
                if key in ('id','last_processed_period','is_completed'):
                    continue
                if cloud[row['id']].get(key) != value:
                    raise RuntimeError('Imported content differs from the preview. Preserve the backup and review the cloud data.')
            if name=='tasks':
                checklist = source_lists[row['checklist_id']]
                current = cloud_lists[row['checklist_id']]
                period_matches = checklist['type']=='normal' or checklist.get('last_processed_period')==current.get('period_key','').split(':')[-1]
                expected = bool(row['is_completed']) and period_matches
                if bool(cloud[row['id']]['is_completed'])!=expected:
                    raise RuntimeError('Imported completion differs from the expected account period, or another device changed it. Preserve the backup and review before retrying.')
