import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from checklist_app.database import Database
from checklist_app.gui import Window, Editor


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_invalid_edit_keeps_dialog_and_entered_text(self):
        dialog = Editor(None)
        dialog.title.setText('Keep this title')
        dialog.description.setPlainText('Keep these details')
        dialog.due.setText('2026-02-30')
        with patch('checklist_app.gui.QMessageBox.warning') as warning:
            dialog.accept()
            warning.assert_called_once()
        self.assertEqual(dialog.result(), 0)
        self.assertEqual(dialog.title.text(), 'Keep this title')
        self.assertEqual(dialog.description.toPlainText(), 'Keep these details')
        dialog.due.setText('2026-02-28')
        dialog.accept()
        self.assertEqual(dialog.result(), 1)
        dialog.close()

    def test_empty_name_is_rejected(self):
        dialog = Editor(None, checklist=True)
        dialog.title.setText('   ')
        with patch('checklist_app.gui.QMessageBox.warning'):
            dialog.accept()
        self.assertEqual(dialog.result(), 0)
        dialog.close()

    def test_completion_search_filter_and_live_reset(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            now = [datetime(2026,10,18,22)]
            db = Database(Path(folder)/'test.db',lambda:now[0])
            daily = db.checklists()[0]['id']
            db.save_task(daily,'Drink water','A glass','High')
            db.save_task(daily,'Read')
            window = Window(db)
            window.show()
            self.app.processEvents()
            self.assertEqual(window.tasks.count(),2)
            window.tasks.setCurrentRow(0)
            selected_id = window.tasks.currentItem().data(Qt.UserRole)
            window.tasks.item(0).setCheckState(Qt.Checked)
            self.assertEqual(window.tasks.currentItem().data(Qt.UserRole), selected_id)
            self.assertEqual(window.progress.value(),50)
            window.search.setText('water')
            self.assertEqual(window.tasks.count(),1)
            window.filter.setCurrentIndex(1)
            self.assertEqual(window.tasks.count(),0)
            window.filter.setCurrentIndex(0)
            window.search.clear()
            now[0] = datetime(2026,10,19,6)
            window.tick()
            self.assertEqual(window.progress.value(),0)
            self.assertEqual(window.tasks.count(),2)
            window.timer.stop()
            window.close()
            db.close()


class SidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.path = Path(self.temp.name)/'sidebar.db'
        self.db = Database(self.path)
        self.window = Window(self.db)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.timer.stop()
        self.window.close()
        self.db.close()
        self.temp.cleanup()

    def test_category_styles_and_fixed_headers(self):
        sidebar = self.window.sidebar
        headers = [sidebar.item(i) for i in range(sidebar.count())
                   if sidebar.item(i).data(Qt.UserRole) is None]
        self.assertEqual([h.text() for h in headers], ['DAILY','WEEKLY','OTHER'])
        self.assertEqual(len({h.background().color().name() for h in headers}), 3)
        for header in headers:
            self.assertFalse(header.flags() & Qt.ItemIsDragEnabled)
            self.assertFalse(header.flags() & Qt.ItemIsSelectable)
            self.assertFalse(sidebar.can_drop(header, 0))
        self.db.set_setting('light', True)
        self.window.theme()
        self.window.refresh_sidebar()
        self.assertEqual(sidebar.item(0).background().color().name(), '#dcecff')

    def test_menu_replaces_old_buttons_and_dispatches_actions(self):
        from PySide6.QtWidgets import QPushButton
        labels = [button.text() for button in self.window.findChildren(QPushButton)]
        self.assertIn('Edit Checklist', labels)
        for old in ['Create checklist','Checklist settings','Duplicate checklist','Delete checklist','Move checklist up','Move checklist down']:
            self.assertNotIn(old, labels)
        actions = self.window.checklist_menu.actions()
        self.assertEqual([a.text() for a in actions], ['Create checklist','Checklist settings','Duplicate checklist','Delete checklist'])
        # Exercise real menu actions without opening modal editors.
        def fill_editor(dialog):
            dialog.title.setText('Created through menu')
            return 1
        with patch.object(Editor, 'exec', fill_editor):
            actions[0].trigger()
        self.assertEqual(self.window.current()['name'], 'Created through menu')
        actions[2].trigger()
        self.assertEqual(self.window.current()['name'], 'Created through menu (copy)')
        with patch.object(self.window, 'confirm', return_value=True):
            actions[3].trigger()
        self.assertNotIn('Created through menu (copy)', [r['name'] for r in self.db.checklists()])
        for row in self.db.checklists():
            self.db.delete_checklist(row['id'])
        self.window.refresh_sidebar()
        self.window.update_checklist_menu()
        self.assertTrue(actions[0].isEnabled())
        self.assertTrue(all(not a.isEnabled() for a in actions[1:]))

    def test_drop_persists_same_category_order_and_rejects_cross_category(self):
        sidebar = self.window.sidebar
        weekly = [r for r in self.db.checklists() if r['type']=='weekly']
        source = next(sidebar.item(i) for i in range(sidebar.count()) if sidebar.item(i).data(Qt.UserRole)==weekly[1]['id'])
        target = next(sidebar.item(i) for i in range(sidebar.count()) if sidebar.item(i).data(Qt.UserRole)==weekly[0]['id'])
        sidebar.setCurrentItem(source)
        destination = sidebar.row(target)
        self.assertTrue(sidebar.can_drop(source, destination))
        class Drop:
            ignored = False
            def source(self):
                return sidebar
            def position(self):
                from PySide6.QtCore import QPointF
                return QPointF(sidebar.visualItemRect(target).topLeft())
            def ignore(self):
                self.ignored = True
        drop = Drop()
        sidebar.dropEvent(drop)
        self.assertTrue(drop.ignored)  # Qt must not delete the dragged row afterward.
        self.assertEqual([r['id'] for r in self.db.checklists() if r['type']=='weekly'], [weekly[1]['id'],weekly[0]['id']])
        self.assertEqual(self.window.selected, weekly[1]['id'])
        before = [dict(r) for r in self.db.checklists()]
        self.window.reorder_checklist(weekly[1]['id'], 0)
        self.window.reorder_checklist(weekly[1]['id'], sidebar.count())
        self.assertEqual([dict(r) for r in self.db.checklists()], before)
        second = Database(self.path)
        try:
            self.assertEqual([r['id'] for r in second.checklists() if r['type']=='weekly'], [weekly[1]['id'],weekly[0]['id']])
        finally:
            second.close()
        # Move the first weekly item down to the end of its own category.
        source = next(sidebar.item(i) for i in range(sidebar.count()) if sidebar.item(i).data(Qt.UserRole)==weekly[1]['id'])
        last = next(sidebar.item(i) for i in range(sidebar.count()) if sidebar.item(i).data(Qt.UserRole)==weekly[0]['id'])
        self.window.reorder_checklist(source.data(Qt.UserRole), sidebar.row(last)+1)
        self.assertEqual([r['id'] for r in self.db.checklists() if r['type']=='weekly'], [weekly[0]['id'],weekly[1]['id']])


class CloudWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_uuid_sidebar_and_account_timezone_display(self):
        from checklist_app.cloud.cache import ReadCache
        from checklist_app.cloud.store import CloudDatabase
        from uuid import uuid4
        from copy import deepcopy
        user, first, second = [str(uuid4()) for _ in range(3)]
        snapshot = {'user_id':user,'revision':0,'settings':{},'timezone':'Asia/Seoul','server_time':'2026-10-18T20:00:00Z','tasks':[], 'checklists':[
            {'id':first,'name':'First daily','type':'daily','display_order':0,'period_key':'daily:1:2026-10-18','next_reset':'2026-10-18T21:00:00Z','next_reset_local':'2026-10-19 06:00'},
            {'id':second,'name':'Second daily','type':'daily','display_order':1,'period_key':'daily:1:2026-10-18','next_reset':'2026-10-18T21:00:00Z','next_reset_local':'2026-10-19 06:00'}]}
        class Transport:
            payload = None
            offline = False
            def snapshot(self):
                if self.offline:
                    raise OSError('offline')
                return deepcopy(snapshot)
            def mutate(self, revision, operation, payload):
                self.payload=payload
                for index, ident in enumerate(payload['ids']):
                    next(row for row in snapshot['checklists'] if row['id']==ident)['display_order']=index
                snapshot['revision']+=1
                return {'id':None}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            transport = Transport()
            db = CloudDatabase(transport,ReadCache(Path(folder)/'cloud.db',user))
            db.refresh()
            window = Window(db)
            window.show()
            self.app.processEvents()
            try:
                self.assertIn('2026-10-19 06:00',window.reset_label.text())
                self.assertIn('Asia/Seoul',window.reset_label.text())
                window.sidebar.reorderRequested.emit(second,1)
                self.assertEqual(transport.payload['ids'],[second,first])
                self.assertEqual(window.selected,second)
                transport.offline=True
                db.refresh()
                window.tick()
                self.assertFalse(window.edit_checklist_button.isEnabled())
                self.assertFalse(window.sidebar.dragEnabled())
                self.assertTrue(all(not b.isEnabled() for b in window.task_buttons))
                transport.offline=False
                db.refresh()
                original=window.selected
                def change_selection_during_confirmation(message):
                    window.selected=first if original==second else second
                    return True
                with patch.object(window,'confirm',change_selection_during_confirmation), patch.object(db,'delete_checklist') as delete:
                    window.delete_list()
                    self.assertEqual(delete.call_args.args[0],original)
            finally:
                window.timer.stop()
                window.close()
                db.close()
