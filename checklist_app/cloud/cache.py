import json
import sqlite3
from pathlib import Path


class ReadCache:
    """Separate, account-bound local snapshots; contains no authentication tokens."""
    def __init__(self, path, user_id):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute('CREATE TABLE IF NOT EXISTS snapshot(user_id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.connection.execute('CREATE TABLE IF NOT EXISTS device_settings(user_id TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(user_id,key))')
        self.user_id = user_id

    def load(self):
        row = self.connection.execute('SELECT data FROM snapshot WHERE user_id=?',(self.user_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, snapshot):
        if snapshot['user_id'] != self.user_id:
            raise ValueError('Refusing a snapshot belonging to another account.')
        with self.connection:
            self.connection.execute('INSERT INTO snapshot VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data',(self.user_id,json.dumps(snapshot)))

    def setting(self, key, default=None):
        row = self.connection.execute('SELECT value FROM device_settings WHERE user_id=? AND key=?',(self.user_id,key)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connection:
            self.connection.execute('INSERT INTO device_settings VALUES(?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value',(self.user_id,key,json.dumps(value)))

    def close(self):
        self.connection.close()
