from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QLineEdit, QComboBox, QProgressBar,
    QDialog, QFormLayout, QDialogButtonBox, QTextEdit, QCheckBox, QMessageBox, QFileDialog,
    QAbstractItemView)
from .scheduling import next_reset


class Editor(QDialog):
    def __init__(self, parent, checklist=False, row=None):
        super().__init__(parent)
        self.setWindowTitle('Checklist details' if checklist else 'Task details')
        form = QFormLayout(self)
        self.title = QLineEdit(row['name' if checklist else 'title'] if row else '')
        form.addRow('Name' if checklist else 'Title', self.title)
        self.choice = QComboBox()
        self.choice.addItems(['normal','daily','weekly'] if checklist else ['Low','Medium','High'])
        self.choice.setCurrentText(row['type' if checklist else 'priority'] if row else ('normal' if checklist else 'Medium'))
        form.addRow('Type' if checklist else 'Priority', self.choice)
        if not checklist:
            self.description = QTextEdit(row['description'] if row else '')
            self.due = QLineEdit(row['due_date'] or '' if row else '')
            self.due.setPlaceholderText('Optional: YYYY-MM-DD')
            form.addRow('Description', self.description)
            form.addRow('Due date', self.due)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class Window(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.selected = db.setting('selected')
        self.loading = False
        self.setWindowTitle('ChecklistApp')
        self.resize(1050, 700)
        geometry = db.setting('geometry')
        if geometry:
            self.setGeometry(*geometry)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        side = QVBoxLayout()
        side.addWidget(QLabel('ChecklistApp'))
        self.sidebar = QListWidget()
        self.sidebar.setMinimumWidth(230)
        self.sidebar.currentItemChanged.connect(self.select)
        side.addWidget(self.sidebar)
        for title, callback in [('Create checklist',self.create),('Checklist settings',self.edit_list),('Duplicate checklist',self.duplicate),('Delete checklist',self.delete_list),('Move checklist up',lambda:self.move_list(-1)),('Move checklist down',lambda:self.move_list(1)),('Settings',self.settings),('Back up database',self.backup)]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, cb=callback:self.safe(cb))
            side.addWidget(button)
        layout.addLayout(side,1)
        main = QVBoxLayout()
        self.heading = QLabel()
        self.heading.setStyleSheet('font-size:24px;font-weight:600')
        main.addWidget(self.heading)
        self.summary = QLabel()
        main.addWidget(self.summary)
        self.progress = QProgressBar()
        main.addWidget(self.progress)
        self.reset_label = QLabel()
        main.addWidget(self.reset_label)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search titles and descriptions')
        self.search.textChanged.connect(self.refresh_tasks)
        controls.addWidget(self.search)
        self.filter = QComboBox()
        self.filter.addItems(['All tasks','Incomplete','Completed'])
        self.filter.currentIndexChanged.connect(self.refresh_tasks)
        controls.addWidget(self.filter)
        main.addLayout(controls)
        self.tasks = QListWidget()
        self.tasks.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tasks.itemChanged.connect(self.toggle)
        self.tasks.itemDoubleClicked.connect(lambda item:self.safe(lambda:self.edit_task(item)))
        self.tasks.model().rowsMoved.connect(lambda *args:self.safe(self.reorder_tasks))
        main.addWidget(self.tasks)
        buttons = QHBoxLayout()
        for title, callback in [('Add task',self.add_task),('Edit task',lambda:self.edit_task(self.tasks.currentItem())),('Delete task',self.delete_task),('Clear completed',self.clear)]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, cb=callback:self.safe(cb))
            buttons.addWidget(button)
        main.addLayout(buttons)
        main.addWidget(QLabel('Double-click a task to edit. Drag tasks to reorder when showing all tasks.'))
        layout.addLayout(main,3)
        self.theme()
        self.refresh_sidebar()
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda:self.safe(self.tick))
        self.timer.start(1000)

    def safe(self, callback):
        try:
            callback()
        except Exception as error:
            QMessageBox.warning(self,'Could not complete action',f'{error}\nYour saved data has not been replaced. Please retry or check the database folder permissions.')

    def confirm(self, message):
        return not self.db.setting('confirm',True) or QMessageBox.question(self,'Please confirm',message)==QMessageBox.Yes

    def refresh_sidebar(self):
        self.sidebar.blockSignals(True)
        self.sidebar.clear()
        chosen = None
        for kind, title in [('daily','DAILY'),('weekly','WEEKLY'),('normal','OTHER')]:
            header = QListWidgetItem(title)
            header.setFlags(Qt.NoItemFlags)
            self.sidebar.addItem(header)
            for row in self.db.checklists():
                if row['type']==kind:
                    item = QListWidgetItem(row['name'])
                    item.setData(Qt.UserRole,row['id'])
                    self.sidebar.addItem(item)
                    if row['id']==self.selected:
                        chosen = item
        if chosen is None:
            chosen = next((self.sidebar.item(i) for i in range(self.sidebar.count()) if self.sidebar.item(i).data(Qt.UserRole)),None)
        self.sidebar.setCurrentItem(chosen)
        self.sidebar.blockSignals(False)
        self.select(chosen)

    def select(self, item, previous=None):
        self.selected = item.data(Qt.UserRole) if item else None
        if self.db.setting('remember',True):
            self.db.set_setting('selected',self.selected)
        self.refresh_tasks()

    def current(self):
        return next((r for r in self.db.checklists() if r['id']==self.selected),None)

    def refresh_tasks(self, *args):
        self.loading = True
        self.tasks.clear()
        row = self.current()
        self.heading.setText(row['name'] if row else 'Create your first checklist')
        records = self.db.tasks(self.selected) if row else []
        completed = sum(t['is_completed'] for t in records)
        total = len(records)
        percent = round(completed*100/total) if total else 0
        self.summary.setText(f'{completed}/{total} completed • {total-completed} remaining • {percent}%')
        self.progress.setValue(percent)
        self.reset_label.setText(f"{row['type'].title()} • Next reset: {next_reset(row['type'],self.db.clock()):%A, %B %d, %Y at %H:%M}" if row and row['type']!='normal' else 'Normal • No automatic reset')
        bottom = self.db.setting('completed_bottom',False)
        if bottom:
            records = sorted(records,key=lambda t:t['is_completed'])
        query = self.search.text().casefold()
        for task in records:
            if query not in (task['title']+' '+task['description']).casefold():
                continue
            if self.filter.currentIndex()==1 and task['is_completed'] or self.filter.currentIndex()==2 and not task['is_completed']:
                continue
            label = f"{task['title']}   [{task['priority']}]" + (f" • Due {task['due_date']}" if task['due_date'] else '')
            item = QListWidgetItem(label)
            item.setToolTip(task['description'])
            item.setData(Qt.UserRole,task['id'])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if task['is_completed'] else Qt.Unchecked)
            font = item.font()
            font.setStrikeOut(bool(task['is_completed']))
            item.setFont(font)
            self.tasks.addItem(item)
        self.tasks.setDragDropMode(QAbstractItemView.InternalMove if not query and self.filter.currentIndex()==0 and not bottom else QAbstractItemView.NoDragDrop)
        self.loading = False

    def toggle(self, item):
        if not self.loading:
            self.safe(lambda:self.db.complete(item.data(Qt.UserRole),item.checkState()==Qt.Checked))
            self.refresh_tasks()

    def tick(self):
        if self.db.reset_due():
            self.refresh_tasks()

    def create(self):
        dialog = Editor(self,True)
        if dialog.exec():
            self.selected = self.db.create_checklist(dialog.title.text(),dialog.choice.currentText())
            self.refresh_sidebar()

    def edit_list(self):
        row = self.current()
        if row:
            dialog = Editor(self,True,row)
            if dialog.exec():
                self.db.edit_checklist(row['id'],dialog.title.text(),dialog.choice.currentText())
                self.refresh_sidebar()

    def duplicate(self):
        if self.current():
            self.selected = self.db.duplicate(self.selected)
            self.refresh_sidebar()

    def delete_list(self):
        if self.current() and self.confirm('Delete this checklist and all of its tasks? This cannot be undone.'):
            self.db.delete_checklist(self.selected)
            self.refresh_sidebar()

    def move_list(self, delta):
        row = self.current()
        if not row:
            return
        ids = [r['id'] for r in self.db.checklists() if r['type']==row['type']]
        index = ids.index(self.selected)
        other = index+delta
        if 0 <= other < len(ids):
            ids[index],ids[other] = ids[other],ids[index]
            self.db.reorder('checklists',ids)
            self.refresh_sidebar()

    def add_task(self):
        if self.current():
            self.task_dialog()

    def edit_task(self, item):
        if item:
            row = next(t for t in self.db.tasks(self.selected) if t['id']==item.data(Qt.UserRole))
            self.task_dialog(row)

    def task_dialog(self, row=None):
        dialog = Editor(self,row=row)
        if dialog.exec():
            self.db.save_task(self.selected,dialog.title.text(),dialog.description.toPlainText(),dialog.choice.currentText(),dialog.due.text().strip() or None,row['id'] if row else None)
            self.refresh_tasks()

    def delete_task(self):
        item = self.tasks.currentItem()
        if item and self.confirm('Delete the selected task? This cannot be undone.'):
            self.db.delete_task(item.data(Qt.UserRole))
            self.refresh_tasks()

    def clear(self):
        if self.current() and self.confirm('Permanently delete completed tasks from this checklist?'):
            self.db.clear_completed(self.selected)
            self.refresh_tasks()

    def reorder_tasks(self):
        if not self.loading:
            self.db.reorder('tasks',[self.tasks.item(i).data(Qt.UserRole) for i in range(self.tasks.count())])

    def settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Settings')
        form = QFormLayout(dialog)
        widgets = {}
        for key, label, default in [('light','Light appearance',False),('completed_bottom','Move completed tasks to bottom',False),('remember','Remember selected checklist',True),('confirm','Confirm destructive actions',True)]:
            box = QCheckBox(label)
            box.setChecked(self.db.setting(key,default))
            widgets[key] = box
            form.addRow(box)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            for key, box in widgets.items():
                self.db.set_setting(key,box.isChecked())
            if not widgets['remember'].isChecked():
                self.db.set_setting('selected',None)
            self.theme()
            self.refresh_tasks()

    def theme(self):
        light = self.db.setting('light',False)
        bg, panel, text = ('#f1f3f8','#ffffff','#182235') if light else ('#191c24','#252a36','#edf0fa')
        self.setStyleSheet(f'''QWidget {{background:{bg}; color:{text}; font-size:14px;}}
        QListWidget,QLineEdit,QTextEdit,QComboBox {{background:{panel}; border:1px solid #657089; border-radius:6px; padding:8px;}}
        QListWidget::item {{padding:10px;}} QListWidget::item:selected {{background:#465eaa; color:white;}}
        QPushButton {{background:{panel}; border:1px solid #657089; border-radius:6px; padding:9px;}}
        QPushButton:hover {{background:#465eaa; color:white;}}
        QProgressBar {{border:0; background:{panel}; border-radius:6px; text-align:center;}}
        QProgressBar::chunk {{background:#657ee8; border-radius:6px;}}
        QCheckBox::indicator,QListWidget::indicator {{width:22px;height:22px;}}''')

    def backup(self):
        path, _ = QFileDialog.getSaveFileName(self,'Save a new backup','checklists-backup.db','SQLite database (*.db)')
        if path:
            self.db.backup(path)
            QMessageBox.information(self,'Backup saved','Your database backup was saved. Existing backups are never overwritten.')

    def closeEvent(self, event):
        rect = self.geometry()
        self.safe(lambda:self.db.set_setting('geometry',[rect.x(),rect.y(),rect.width(),rect.height()]))
        event.accept()
