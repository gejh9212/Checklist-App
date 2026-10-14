import json
import os
import sqlite3
from datetime import datetime, date
from pathlib import Path
from .scheduling import period


def data_path():
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA')
        if not base:
            raise RuntimeError('Windows Local AppData is unavailable. No database was opened.')
        return Path(base) / 'ChecklistApp' / 'checklists.db'
    return Path.home() / '.local' / 'share' / 'ChecklistApp' / 'checklists.db'


class Database:
    def __init__(self, path, clock=datetime.now):
        self.clock = clock
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.execute('PRAGMA busy_timeout=5000')
        version = self.connection.execute('PRAGMA user_version').fetchone()[0]
        if version > 1:
            self.connection.close()
            raise RuntimeError('This database was created by a newer app. Please update ChecklistApp.')
        with self.connection:
            self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS checklists(
              id INTEGER PRIMARY KEY, name TEXT NOT NULL,
              type TEXT NOT NULL CHECK(type IN ('normal','daily','weekly')),
              display_order INTEGER NOT NULL, last_processed_period TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(
              id INTEGER PRIMARY KEY, checklist_id INTEGER NOT NULL REFERENCES checklists(id) ON DELETE CASCADE,
              title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
              is_completed INTEGER NOT NULL DEFAULT 0 CHECK(is_completed IN (0,1)),
              priority TEXT NOT NULL DEFAULT 'Medium', due_date TEXT,
              display_order INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            PRAGMA user_version=1;
            ''')
            if not self.setting('initialized', False):
                # Existing databases are never reseeded or cleared.
                if not self.checklists():
                    for name, kind in [('Daily Routine','daily'),('Weekly Goals','weekly'),('Weekly Cleaning','weekly'),('Shopping List','normal'),('Projects','normal')]:
                        self.create_checklist(name, kind)
                self.set_setting('initialized', True)
        self.reset_due()

    def close(self):
        self.connection.close()

    def setting(self, key, default=None):
        row = self.connection.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connection:
            self.connection.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key,json.dumps(value)))

    def checklists(self):
        return self.connection.execute('SELECT * FROM checklists ORDER BY display_order,id').fetchall()

    def create_checklist(self, name, kind):
        if not name.strip() or kind not in ('normal','daily','weekly'):
            raise ValueError('Enter a checklist name and a valid type.')
        now = self.clock()
        with self.connection:
            return self.connection.execute('INSERT INTO checklists(name,type,display_order,last_processed_period,created_at,updated_at) VALUES(?,?,(SELECT COALESCE(MAX(display_order),-1)+1 FROM checklists),?,?,?)', (name.strip(),kind,period(kind,now) if kind!='normal' else None,now.isoformat(),now.isoformat())).lastrowid

    def edit_checklist(self, ident, name, kind):
        old = self.connection.execute('SELECT * FROM checklists WHERE id=?',(ident,)).fetchone()
        if not name.strip() or kind not in ('normal','daily','weekly'):
            raise ValueError('Enter a checklist name and a valid type.')
        marker = old['last_processed_period'] if old['type']==kind else (period(kind,self.clock()) if kind!='normal' else None)
        with self.connection:
            self.connection.execute('UPDATE checklists SET name=?,type=?,last_processed_period=?,updated_at=? WHERE id=?',(name.strip(),kind,marker,self.clock().isoformat(),ident))

    def delete_checklist(self, ident):
        with self.connection:
            self.connection.execute('DELETE FROM checklists WHERE id=?',(ident,))

    def duplicate(self, ident):
        row = self.connection.execute('SELECT * FROM checklists WHERE id=?',(ident,)).fetchone()
        with self.connection:
            new = self.create_checklist(row['name']+' (copy)',row['type'])
            self.connection.execute('INSERT INTO tasks(checklist_id,title,description,is_completed,priority,due_date,display_order,created_at,updated_at) SELECT ?,title,description,is_completed,priority,due_date,display_order,created_at,updated_at FROM tasks WHERE checklist_id=?',(new,ident))
        return new

    def tasks(self, ident):
        return self.connection.execute('SELECT * FROM tasks WHERE checklist_id=? ORDER BY display_order,id',(ident,)).fetchall()

    def save_task(self, checklist, title, description='', priority='Medium', due_date=None, ident=None):
        if not title.strip():
            raise ValueError('Please enter a task title.')
        if priority not in ('Low','Medium','High'):
            raise ValueError('Invalid priority.')
        if due_date:
            date.fromisoformat(due_date)
        now = self.clock().isoformat()
        with self.connection:
            if ident is None:
                return self.connection.execute('INSERT INTO tasks(checklist_id,title,description,priority,due_date,display_order,created_at,updated_at) VALUES(?,?,?,?,?,(SELECT COALESCE(MAX(display_order),-1)+1 FROM tasks WHERE checklist_id=?),?,?)',(checklist,title.strip(),description,priority,due_date,checklist,now,now)).lastrowid
            self.connection.execute('UPDATE tasks SET title=?,description=?,priority=?,due_date=?,updated_at=? WHERE id=? AND checklist_id=?',(title.strip(),description,priority,due_date,now,ident,checklist))
            return ident

    def complete(self, ident, completed):
        self.reset_due()
        with self.connection:
            self.connection.execute('UPDATE tasks SET is_completed=?,updated_at=? WHERE id=?',(int(completed),self.clock().isoformat(),ident))

    def delete_task(self, ident):
        with self.connection:
            self.connection.execute('DELETE FROM tasks WHERE id=?',(ident,))

    def clear_completed(self, ident):
        with self.connection:
            self.connection.execute('DELETE FROM tasks WHERE checklist_id=? AND is_completed=1',(ident,))

    def reorder(self, table, identifiers):
        if table not in ('tasks','checklists'):
            raise ValueError('Invalid ordering target.')
        with self.connection:
            self.connection.executemany(f'UPDATE {table} SET display_order=? WHERE id=?',enumerate(identifiers))

    def reset_due(self):
        now = self.clock()
        changed = []
        # BEGIN IMMEDIATE serializes checking and resetting across app instances.
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            for row in self.connection.execute("SELECT * FROM checklists WHERE type!='normal'").fetchall():
                current = period(row['type'],now)
                previous = row['last_processed_period']
                if previous is None or current > previous:
                    if previous is not None:
                        self.connection.execute('UPDATE tasks SET is_completed=0 WHERE checklist_id=?',(row['id'],))
                        changed.append(row['id'])
                    self.connection.execute('UPDATE checklists SET last_processed_period=?,updated_at=? WHERE id=?',(current,now.isoformat(),row['id']))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return changed

    def backup(self, destination):
        # Exclusive creation prevents overwriting an existing backup.
        with open(destination, 'xb'):
            pass
        target = sqlite3.connect(destination)
        try:
            self.connection.backup(target)
        finally:
            target.close()
