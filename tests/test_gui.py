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
