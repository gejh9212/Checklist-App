"""Real PostgreSQL checks. Requires a DISPOSABLE local DB with the migration applied.

CHECKLIST_TEST_PG_DSN must point to that database, never a personal/production DB.
Auth claims are emulated here; hosted JWT validation needs the separate device smoke test.
"""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

DSN = os.environ.get('CHECKLIST_TEST_PG_DSN')


@unittest.skipUnless(DSN, 'Set CHECKLIST_TEST_PG_DSN for disposable PostgreSQL integration tests')
class CloudSqlTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.psycopg = psycopg
        self.owner = str(uuid4())
        self.other = str(uuid4())
        self.admin = psycopg.connect(DSN,autocommit=True)
        self.admin.execute('INSERT INTO auth.users(id) VALUES(%s),(%s)',(self.owner,self.other))
        self.a = self.connect(self.owner)
        self.b = self.connect(self.other)
        self.snapshot(self.a)
        self.snapshot(self.b)

    def connect(self, user):
        connection = self.psycopg.connect(DSN,autocommit=True)
        connection.execute('SET ROLE authenticated')
        connection.execute("SELECT set_config('request.jwt.claim.sub',%s,false)",(user,))
        return connection

    def tearDown(self):
        self.a.close()
        self.b.close()
        self.admin.execute('DELETE FROM auth.users WHERE id IN (%s,%s)',(self.owner,self.other))
        self.admin.close()

    def snapshot(self, connection):
        return connection.execute('SELECT public.checklist_snapshot()').fetchone()[0]

    def mutate(self, connection, revision, operation, payload):
        from psycopg.types.json import Jsonb
        return connection.execute('SELECT public.checklist_mutate(%s,%s,%s)',(revision,operation,Jsonb(payload))).fetchone()[0]

    def checklist(self, kind='daily'):
        return self.mutate(self.a,self.snapshot(self.a)['revision'],'create_checklist',{'name':'Test','type':kind})['id']

    def task(self, checklist):
        return self.mutate(self.a,self.snapshot(self.a)['revision'],'create_task',{'checklist_id':checklist,'title':'Task','priority':'High','description':'Details','due_date':'2026-12-01'})['id']

    def test_account_isolation_and_direct_writes_denied(self):
        checklist = self.checklist()
        task = self.task(checklist)
        self.assertEqual(self.snapshot(self.b)['checklists'],[])
        self.assertEqual(self.b.execute('SELECT count(*) FROM public.tasks').fetchone()[0],0)
        for operation, payload in [('delete_checklist',{'id':checklist}),('edit_task',{'id':task,'title':'Stolen'}),('complete',{'id':task,'completed':True,'period_key':'bad'})]:
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                self.mutate(self.b,0,operation,payload)
        with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
            self.a.execute("UPDATE public.tasks SET title='Bypass'")
        with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
            self.a.execute("SELECT private.period_key('daily',1,'Asia/Seoul',now())")

    def test_anonymous_access_denied(self):
        self.b.execute('SET ROLE anon')
        for query in ['SELECT public.checklist_snapshot()', 'SELECT * FROM public.tasks']:
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                self.b.execute(query)

    def test_cross_device_completion_and_unique_records(self):
        checklist = self.checklist()
        task = self.task(checklist)
        second = self.connect(self.owner)
        try:
            for value in [True,False,True]:
                snap = self.snapshot(second)
                self.mutate(second,snap['revision'],'complete',{'id':task,'completed':value,'period_key':snap['checklists'][0]['period_key']})
                self.assertEqual(self.snapshot(self.a)['tasks'][0]['is_completed'],value)
            self.assertEqual(self.a.execute('SELECT count(*) FROM public.task_completions').fetchone()[0],1)
        finally:
            second.close()

    def test_simultaneous_updates_one_conflicts(self):
        checklist = self.checklist()
        revision = self.snapshot(self.a)['revision']
        def edit(name):
            c = self.connect(self.owner)
            try:
                self.mutate(c,revision,'edit_checklist',{'id':checklist,'name':name,'type':'daily'})
                return 'saved'
            except self.psycopg.errors.SerializationFailure:
                return 'conflict'
            finally:
                c.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(edit,['Device A','Device B']))
        self.assertCountEqual(results,['saved','conflict'])
        self.assertEqual(self.snapshot(self.a)['revision'],revision+1)

    def test_stale_period_rejected_and_history_preserved(self):
        checklist = self.checklist()
        task = self.task(checklist)
        snap = self.snapshot(self.a)
        with self.assertRaises(self.psycopg.errors.SerializationFailure):
            self.mutate(self.a,snap['revision'],'complete',{'id':task,'completed':True,'period_key':'daily:1:2000-01-01'})
        self.mutate(self.a,snap['revision'],'complete',{'id':task,'completed':True,'period_key':snap['checklists'][0]['period_key']})
        self.mutate(self.a,self.snapshot(self.a)['revision'],'timezone',{'timezone':'America/New_York'})
        self.assertFalse(self.snapshot(self.a)['tasks'][0]['is_completed'])
        self.assertEqual(self.a.execute('SELECT count(*) FROM public.task_completions').fetchone()[0],1)

    def test_timezone_boundaries_and_dst(self):
        query = 'SELECT private.period_key(%s,1,%s,%s::timestamptz)'
        cases = [('daily','Asia/Seoul','2026-10-18 20:59:59+00','daily:1:2026-10-18'),
                 ('daily','Asia/Seoul','2026-10-18 21:00:00+00','daily:1:2026-10-19'),
                 ('weekly','Asia/Seoul','2026-10-18 20:59:59+00','weekly:1:2026-10-12'),
                 ('weekly','Asia/Seoul','2026-10-18 21:00:00+00','weekly:1:2026-10-19'),
                 ('daily','America/New_York','2026-11-01 10:59:59+00','daily:1:2026-10-31'),
                 ('daily','America/New_York','2026-11-01 11:00:00+00','daily:1:2026-11-01'),
                 ('normal','Asia/Seoul','2050-01-01 00:00+00','normal:1')]
        for kind,zone,instant,expected in cases:
            self.assertEqual(self.admin.execute(query,(kind,zone,instant)).fetchone()[0],expected)
        next_date = self.admin.execute("SELECT private.next_reset('weekly','Asia/Seoul','2026-10-18 21:00+00')").fetchone()[0]
        self.assertEqual(next_date.isoformat(),'2026-10-25T21:00:00+00:00')

    def test_reorder_validates_membership_and_deletion_conflicts(self):
        checklist = self.checklist()
        first, second = self.task(checklist), self.task(checklist)
        snap = self.snapshot(self.a)
        self.mutate(self.a,snap['revision'],'reorder',{'table':'tasks','checklist_id':checklist,'ids':[second,first]})
        self.assertEqual([r['id'] for r in self.snapshot(self.a)['tasks']],[second,first])
        with self.assertRaises(self.psycopg.errors.SerializationFailure):
            self.mutate(self.a,self.snapshot(self.a)['revision'],'reorder',{'table':'tasks','checklist_id':checklist,'ids':[first]})
        revision = self.snapshot(self.a)['revision']
        self.mutate(self.a,revision,'delete_task',{'id':first})
        with self.assertRaises(self.psycopg.errors.SerializationFailure):
            self.mutate(self.a,revision,'edit_task',{'id':first,'title':'Old copy','priority':'Low'})
        self.assertEqual(len(self.snapshot(self.a)['tasks']),1)

    def test_import_is_atomic_and_idempotent(self):
        from psycopg.types.json import Jsonb
        c, t = str(uuid4()), str(uuid4())
        manifest = {'source_id':str(uuid4()),'content_hash':'test-hash','settings':{'light':True},'checklists':[{'id':c,'name':'Imported','type':'normal','display_order':0}], 'tasks':[{'id':t,'checklist_id':c,'title':'Imported task','description':'Keep','priority':'High','due_date':None,'display_order':0,'is_completed':True}]}
        query = 'SELECT public.checklist_import(%s,%s)'
        self.a.execute(query,(0,Jsonb(manifest)))
        result = self.a.execute(query,(0,Jsonb(manifest))).fetchone()[0]
        self.assertTrue(result['already_imported'])
        snap = self.snapshot(self.a)
        self.assertEqual(len(snap['checklists']),1)
        self.assertTrue(snap['tasks'][0]['is_completed'])
        self.assertTrue(snap['settings']['light'])
        manifest['source_id'] = str(uuid4())
        manifest['checklists'][0]['id'] = str(uuid4())
        manifest['tasks'][0]['id'] = str(uuid4())
        with self.assertRaises(self.psycopg.errors.RaiseException):
            self.a.execute(query,(snap['revision'],Jsonb(manifest)))
        self.assertEqual(len(self.snapshot(self.a)['checklists']),1)

    def test_desktop_adapters_sync_through_real_postgres(self):
        from checklist_app.cloud.store import CloudDatabase, SyncError
        from checklist_app.cloud.cache import ReadCache
        from pathlib import Path
        import tempfile
        test = self
        class Transport:
            def __init__(self, connection):
                self.connection = connection
            def snapshot(self):
                return test.snapshot(self.connection)
            def mutate(self, revision, operation, payload):
                return test.mutate(self.connection,revision,operation,payload)
        connection = self.connect(self.owner)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            desktop = CloudDatabase(Transport(self.a),ReadCache(Path(folder)/'desktop.db',self.owner))
            phone_contract = CloudDatabase(Transport(connection),ReadCache(Path(folder)/'phone-contract.db',self.owner))
            try:
                desktop.refresh()
                phone_contract.refresh()
                checklist = desktop.create_checklist('Cross device','daily')
                phone_contract.refresh()
                self.assertEqual(phone_contract.checklists()[0]['name'],'Cross device')
                task = phone_contract.save_task(checklist,'Created by second client','Details','High')
                desktop.refresh()
                self.assertEqual(desktop.tasks(checklist)[0]['title'],'Created by second client')
                desktop.complete(task,True)
                phone_contract.refresh()
                self.assertTrue(phone_contract.tasks(checklist)[0]['is_completed'])
                phone_contract.edit_checklist(checklist,'Renamed by second client','daily')
                desktop.refresh()
                self.assertEqual(desktop.checklists()[0]['name'],'Renamed by second client')
                phone_contract.delete_task(task)
                with self.assertRaises(SyncError):
                    desktop.save_task(checklist,'Stale edit',ident=task)
                desktop.refresh()
                self.assertEqual(desktop.tasks(checklist),[])
            finally:
                desktop.close()
                phone_contract.close()
                connection.close()

    def test_old_period_is_history_not_current_progress(self):
        checklist = self.checklist()
        task = self.task(checklist)
        self.admin.execute("INSERT INTO public.task_completions(task_id,user_id,period_key,is_completed,completed_at) VALUES(%s,%s,'daily:1:2000-01-01',true,'2000-01-01Z')",(task,self.owner))
        snap = self.snapshot(self.a)
        self.assertFalse(snap['tasks'][0]['is_completed'])
        self.assertEqual(snap['tasks'][0]['title'],'Task')
        self.assertEqual(self.a.execute('SELECT count(*) FROM public.task_completions').fetchone()[0],1)
        self.assertTrue(snap['checklists'][0]['next_reset_local'].endswith('06:00'))
