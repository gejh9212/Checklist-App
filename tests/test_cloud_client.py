import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime
from uuid import uuid4
from checklist_app.cloud.auth import SecureStorage
from checklist_app.cloud.cache import ReadCache
from checklist_app.cloud.config import CloudConfig
from checklist_app.cloud.migration import preview, backup_source, remember_source, validate_import
from checklist_app.cloud.store import CloudDatabase, SyncError
from checklist_app.database import Database


class Transport:
    def __init__(self, user):
        self.answer = {'user_id':user,'revision':0,'settings':{},'timezone':'Asia/Seoul','server_time':'2026-10-18T12:00:00+00:00','checklists':[],'tasks':[]}
        self.fail = False
        self.calls = []
    def snapshot(self):
        if self.fail:
            raise OSError('network unavailable')
        return copy.deepcopy(self.answer)
    def mutate(self, revision, operation, payload):
        if self.fail:
            raise OSError('network unavailable')
        self.calls.append((revision,operation,payload))
        self.answer['revision'] += 1
        return {'id':payload.get('id'),'revision':self.answer['revision']}


class CloudClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.user = str(uuid4())
        self.cache = ReadCache(Path(self.temp.name)/'cache.db',self.user)
        self.transport = Transport(self.user)
        self.store = CloudDatabase(self.transport,self.cache)
    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
    def test_offline_edits_are_blocked_and_cache_survives(self):
        self.assertTrue(self.store.refresh())
        self.transport.fail = True
        self.store.refresh()
        with self.assertRaises(SyncError):
            self.store.create_checklist('Offline draft','normal')
        self.assertEqual(self.transport.calls,[])
        self.assertEqual(self.cache.load()['user_id'],self.user)
        self.transport.fail = False
        self.store.refresh()
        self.assertTrue(self.store.online)
        ident = self.store.create_checklist('Online','normal')
        self.assertIsNotNone(ident)
        self.assertEqual(self.transport.calls[0][0],0)
    def test_account_mismatch_is_never_cached(self):
        self.store.refresh()
        self.transport.answer['user_id'] = str(uuid4())
        self.store.refresh()
        self.assertFalse(self.store.online)
        self.assertEqual(self.cache.load()['user_id'],self.user)
        with self.assertRaises(ValueError):
            self.cache.save(self.transport.answer)
    def test_ambiguous_save_keeps_draft_and_disables_next_write(self):
        self.store.refresh()
        self.transport.fail = True
        with self.assertRaises(SyncError):
            self.store.save_task('list','Typed title','Keep details')
        self.assertEqual(self.store.last_error['payload']['title'],'Typed title')
        self.assertFalse(self.store.online)
        with self.assertRaises(SyncError):
            self.store.delete_task('task')
    def test_completion_sends_server_period_not_device_date(self):
        self.transport.answer['checklists']=[{'id':'list','type':'daily','display_order':0,'period_key':'daily:4:2026-10-18','next_reset':'2026-10-18T21:00:00+00:00'}]
        self.transport.answer['tasks']=[{'id':'task','checklist_id':'list','display_order':0,'is_completed':False}]
        self.store.refresh()
        self.store.complete('task',True)
        self.assertEqual(self.transport.calls[-1][2]['period_key'],'daily:4:2026-10-18')
    def test_shared_and_local_settings_are_separate(self):
        self.store.refresh()
        self.store.set_setting('geometry',[1,2,800,600])
        self.store.set_setting('selected','checklist-id')
        self.assertEqual(self.transport.calls,[])
        self.assertEqual(self.store.setting('geometry'),[1,2,800,600])
        self.store.save_shared_settings({'light':True,'confirm':True})
        self.assertEqual(self.transport.calls[-1][1],'settings')
    def test_cache_does_not_leak_between_accounts(self):
        self.store.refresh()
        second = ReadCache(Path(self.temp.name)/'cache.db',str(uuid4()))
        try:
            self.assertIsNone(second.load())
            self.assertIsNone(second.setting('selected'))
        finally:
            second.close()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.path = Path(self.temp.name)/'original.db'
        self.db = Database(self.path,lambda:datetime(2026,10,18,22))
        self.user = str(uuid4())
        self.ident = self.db.create_checklist('Existing list','normal')
        task=self.db.save_task(self.ident,'Existing task','Details','High','2026-12-01')
        self.db.complete(task,True)
    def tearDown(self):
        self.db.close()
        self.temp.cleanup()
    def test_preview_and_backup_leave_original_bytes_unchanged(self):
        before=self.path.read_bytes()
        manifest=preview(self.path,self.user)
        self.assertEqual(manifest,preview(self.path,self.user))
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(manifest['tasks'][0]['title'],'Existing task')
        self.assertTrue(manifest['tasks'][0]['is_completed'])
        backup=backup_source(self.path)
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute('SELECT title FROM tasks').fetchone()[0],'Existing task')
        self.assertEqual(self.path.read_bytes(),before)
    def test_import_identity_retained_after_source_edits(self):
        first=preview(self.path,self.user)
        remember_source(self.path,first)
        self.db.create_checklist('New after import','daily')
        second=preview(self.path,self.user)
        self.assertEqual(second['source_id'],first['source_id'])
        self.assertNotEqual(second['content_hash'],first['content_hash'])
        original_ids={r['name']:r['id'] for r in first['checklists']}
        self.assertTrue(all(original_ids[r['name']]==r['id'] for r in second['checklists'] if r['name'] in original_ids))
    def test_import_ids_scoped_to_user_and_validated(self):
        manifest=preview(self.path,self.user)
        other=preview(self.path,str(uuid4()))
        self.assertNotEqual(manifest['tasks'][0]['id'],other['tasks'][0]['id'])
        validate_import(manifest,manifest)
        broken=copy.deepcopy(manifest)
        broken['tasks'][0]['title']='Different'
        with self.assertRaises(RuntimeError):
            validate_import(manifest,broken)


class ConfigurationTests(unittest.TestCase):
    def test_rejects_secret_keys_and_non_https_urls(self):
        for url,key in [('http://example.com','sb_publishable_test'),('https://example.com','sb_secret_test'),('https://user:password@example.com','sb_publishable_test')]:
            with self.assertRaises(ValueError):
                CloudConfig(url,key)
        self.assertTrue(CloudConfig('https://example.supabase.co','sb_publishable_test').namespace)
    def test_sdk_sessions_use_only_secure_backend(self):
        class Backend:
            data={}
            def get_password(self, service, key): return self.data.get((service,key))
            def set_password(self, service, key, value):
                if len(value)>1200:
                    raise ValueError('Credential blob too large')
                self.data[(service,key)]=value
            def delete_password(self, service, key): del self.data[(service,key)]
        backend=Backend()
        storage=SecureStorage('test-project',backend)
        storage.set_item('session','test-session-value')
        self.assertEqual(storage.get_item('session'),'test-session-value')
        storage.set_item('large-session','x'*6000)
        self.assertEqual(storage.get_item('large-session'),'x'*6000)
        self.assertIsNone(SecureStorage('different-project',backend).get_item('session'))
        storage.clear()
        self.assertIsNone(storage.get_item('session'))
        self.assertEqual(backend.data,{})

    def test_actual_sdk_client_supports_public_close_without_session_timer(self):
        from checklist_app.cloud.auth import make_client
        class Backend:
            def get_password(self,service,key): return None
            def set_password(self,service,key,value): pass
            def delete_password(self,service,key): pass
        client = make_client(CloudConfig('https://example.supabase.co','sb_publishable_test'),SecureStorage('sdk-test',Backend()))
        try:
            self.assertFalse(client.options.auto_refresh_token)
            self.assertIsNone(client.auth.get_session())
        finally:
            client.auth.close()
