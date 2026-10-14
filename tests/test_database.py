import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from checklist_app.database import Database
from checklist_app.scheduling import period, next_reset


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.path = Path(self.temp.name)/'test.db'
        self.now = datetime(2026,10,18,22)
        self.db = Database(self.path,lambda:self.now)
        self.daily = self.db.create_checklist('Daily','daily')
        self.weekly = self.db.create_checklist('Weekly','weekly')
        self.normal = self.db.create_checklist('Normal','normal')
        self.ids = {}
        for checklist in (self.daily,self.weekly,self.normal):
            task = self.db.save_task(checklist,'Title','Details','High','2026-10-30')
            self.ids[checklist] = task
            self.db.complete(task,True)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def completed(self, ident):
        return self.db.tasks(ident)[0]['is_completed']

    def test_daily_boundary_and_preservation(self):
        before = dict(self.db.tasks(self.daily)[0])
        self.now = datetime(2026,10,19,5,59,59)
        self.assertEqual(self.db.reset_due(),[])
        self.assertTrue(self.completed(self.daily))
        self.now = datetime(2026,10,19,6)
        self.assertTrue({self.daily,self.weekly}.issubset(self.db.reset_due()))
        after = dict(self.db.tasks(self.daily)[0])
        self.assertFalse(after.pop('is_completed'))
        before.pop('is_completed')
        self.assertEqual(before,after)
        self.assertTrue(self.completed(self.normal))

    def test_weekly_monday_six_not_midnight(self):
        self.now = datetime(2026,10,19,0)
        self.assertEqual(self.db.reset_due(),[])
        self.assertTrue(self.completed(self.weekly))
        self.now = datetime(2026,10,19,6)
        self.db.reset_due()
        self.assertFalse(self.completed(self.weekly))

    def test_no_duplicate_or_backward_reset(self):
        self.now = datetime(2026,10,19,6)
        self.db.reset_due()
        self.db.complete(self.ids[self.daily],True)
        self.assertEqual(self.db.reset_due(),[])
        self.now = datetime(2026,10,18,23)
        self.assertEqual(self.db.reset_due(),[])
        self.now = datetime(2026,10,19,8)
        self.assertEqual(self.db.reset_due(),[])
        self.assertTrue(self.completed(self.daily))

    def test_missed_resets_and_restarts(self):
        self.db.close()
        self.now = datetime(2026,11,3,9)
        self.db = Database(self.path,lambda:self.now)
        self.assertFalse(self.completed(self.daily))
        self.assertFalse(self.completed(self.weekly))
        self.assertTrue(self.completed(self.normal))
        self.db.complete(self.ids[self.daily],True)
        for _ in range(3):
            self.db.close()
            self.db = Database(self.path,lambda:self.now)
            self.assertTrue(self.completed(self.daily))
        self.assertEqual(len(self.db.checklists()),8)

    def test_first_creation_and_type_change(self):
        self.assertEqual(self.db.reset_due(),[])
        self.assertTrue(self.completed(self.daily))
        self.db.edit_checklist(self.normal,'Converted','daily')
        self.assertEqual(self.db.reset_due(),[])
        self.assertTrue(self.completed(self.normal))

    def test_crud_duplicate_order_settings_backup(self):
        new = self.db.duplicate(self.daily)
        self.assertEqual(len(self.db.tasks(new)),1)
        self.db.save_task(new,'Edited','Description','Low',None,self.db.tasks(new)[0]['id'])
        self.assertEqual(self.db.tasks(new)[0]['title'],'Edited')
        second = self.db.save_task(new,'Second')
        self.db.reorder('tasks',[second,self.db.tasks(new)[0]['id']])
        self.assertEqual(self.db.tasks(new)[0]['id'],second)
        self.db.set_setting('light',True)
        self.assertTrue(self.db.setting('light'))
        backup = self.path.with_name('backup.db')
        self.db.backup(backup)
        with self.assertRaises(FileExistsError):
            self.db.backup(backup)
        self.db.clear_completed(new)
        self.assertEqual(len(self.db.tasks(new)),1)
        self.db.delete_checklist(new)
        self.assertEqual(self.db.tasks(new),[])

    def test_atomic_rollback(self):
        self.db.connection.execute("CREATE TRIGGER fail_reset BEFORE UPDATE OF is_completed ON tasks WHEN NEW.is_completed=0 BEGIN SELECT RAISE(ABORT,'test failure'); END")
        self.now = datetime(2026,10,19,6)
        with self.assertRaises(Exception):
            self.db.reset_due()
        self.assertTrue(self.completed(self.daily))
        self.db.connection.execute('DROP TRIGGER fail_reset')
        self.assertTrue({self.daily,self.weekly}.issubset(self.db.reset_due()))

    def test_calendar_dst_and_next_reset(self):
        self.assertEqual(period('daily',datetime(2026,11,1,5,59)),'2026-10-31')
        self.assertEqual(period('daily',datetime(2026,11,1,6)),'2026-11-01')
        self.assertEqual(next_reset('weekly',datetime(2026,10,19,5)),datetime(2026,10,19,6))
        self.assertEqual(next_reset('weekly',datetime(2026,10,19,6)),datetime(2026,10,26,6))


if __name__ == '__main__':
    unittest.main()
