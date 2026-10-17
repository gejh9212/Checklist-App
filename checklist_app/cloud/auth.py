"""SDK session persistence in OS credential storage, never in SQLite or .env."""
from supabase_auth import SyncSupportedStorage
import keyring
import json
from threading import RLock
from uuid import uuid4

_STORAGE_LOCK = RLock()


class SecureStorage(SyncSupportedStorage):
    def __init__(self, namespace, backend=None):
        self.backend = backend or keyring.get_keyring()
        module = type(self.backend).__module__
        if backend is None and not module.startswith(('keyring.backends.Windows', 'keyring.backends.macOS', 'keyring.backends.SecretService')):
            raise RuntimeError('Secure credential storage is unavailable. On Windows use Windows Credential Manager; on Linux unlock a Secret Service keyring. Plain-text token storage is deliberately disabled.')
        self.service = 'ChecklistApp.Supabase.' + namespace

    def _index(self):
        value = self.backend.get_password(self.service, 'sdk-storage')
        return json.loads(value) if value else {}

    def _load(self):
        index = self._index()
        if index.get('_format')!=1:
            return index
        if not index.get('active'):
            return index.get('inline',{})
        parts = [self.backend.get_password(self.service,key) for key in index['active']]
        if any(part is None for part in parts):
            raise RuntimeError('Saved login is incomplete. Sign in again; checklist data is unaffected.')
        return json.loads(''.join(parts))

    def _save(self, data):
        # Windows Credential Manager limits each credential blob's size. Split
        # ASCII JSON into small encrypted credentials rather than use a plain file.
        previous = self._index()
        generation = uuid4().hex
        encoded = json.dumps(data,ensure_ascii=True)
        parts = [encoded[i:i+1000] for i in range(0,len(encoded),1000)]
        keys = [f'session-{generation}-{i}' for i in range(len(parts))]
        old_keys = previous.get('tracked',[]) if previous.get('_format')==1 else []
        staged = {'_format':1,'active':previous.get('active',[]),'inline':previous.get('inline',{}) if previous.get('_format')==1 else previous,'tracked':old_keys+keys}
        # Register new chunks before writing, so logout can remove interrupted writes.
        self.backend.set_password(self.service,'sdk-storage',json.dumps(staged))
        for key,part in zip(keys,parts):
            self.backend.set_password(self.service,key,part)
        staged = {'_format':1,'active':keys,'tracked':old_keys+keys}
        self.backend.set_password(self.service,'sdk-storage',json.dumps(staged))
        remaining = []
        for key in old_keys:
            try:
                if self.backend.get_password(self.service,key) is not None:
                    self.backend.delete_password(self.service,key)
            except Exception:
                remaining.append(key)
        staged['tracked'] = remaining+keys
        self.backend.set_password(self.service,'sdk-storage',json.dumps(staged))

    def get_item(self, key):
        with _STORAGE_LOCK:
            return self._load().get(key)

    def set_item(self, key, value):
        with _STORAGE_LOCK:
            data = self._load()
            data[key] = value
            self._save(data)

    def remove_item(self, key):
        with _STORAGE_LOCK:
            data = self._load()
            data.pop(key, None)
            self._save(data)

    def clear(self):
        with _STORAGE_LOCK:
            index = self._index()
            for key in index.get('tracked',[]) if index.get('_format')==1 else []:
                if self.backend.get_password(self.service,key) is not None:
                    self.backend.delete_password(self.service,key)
            if self.backend.get_password(self.service, 'sdk-storage') is not None:
                self.backend.delete_password(self.service, 'sdk-storage')


def make_client(config, storage):
    from supabase import create_client, ClientOptions
    import httpx
    return create_client(config.url, config.key, options=ClientOptions(
        storage=storage, persist_session=True, auto_refresh_token=True,
        postgrest_client_timeout=12, httpx_client=httpx.Client(timeout=12)))
