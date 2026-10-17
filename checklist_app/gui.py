from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QLineEdit, QComboBox, QProgressBar,
    QDialog, QFormLayout, QDialogButtonBox, QTextEdit, QCheckBox, QMessageBox, QFileDialog,
    QAbstractItemView, QMenu)
from datetime import date
from .scheduling import next_reset
from .sidebar import ChecklistSidebar, CATEGORY_ROLE


class Editor(QDialog):
    def __init__(self, parent, checklist=False, row=None):
        super().__init__(parent)
        self.setWindowTitle('Checklist details' if checklist else 'Task details')
        self.checklist = checklist
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


    def accept(self):
        if not self.title.text().strip():
            QMessageBox.warning(self, 'Name required', 'Please enter a name before saving.')
            self.title.setFocus()
            return
        if not self.checklist and self.due.text().strip():
            try:
                value = self.due.text().strip()
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, 'Check the due date', 'Enter a real date in YYYY-MM-DD format, or leave the due date empty. Your edits are still here.')
                self.due.setFocus()
                return
        super().accept()


class Window(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.selected = db.setting('selected')
        self.loading = False
        self.reporting_error = False
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
        self.sidebar = ChecklistSidebar()
        self.sidebar.reorderRequested.connect(lambda ident, destination:self.safe(lambda:self.reorder_checklist(ident, destination)))
        self.sidebar.setMinimumWidth(230)
        self.sidebar.currentItemChanged.connect(self.select)
        side.addWidget(self.sidebar)
        self.edit_checklist_button = QPushButton('Edit Checklist')
        self.checklist_menu = QMenu(self)
        for title, callback in [('Create checklist',self.create),('Checklist settings',self.edit_list),('Duplicate checklist',self.duplicate),('Delete checklist',self.delete_list)]:
            action = self.checklist_menu.addAction(title)
            action.triggered.connect(lambda checked=False, cb=callback:self.safe(cb))
        self.checklist_menu.aboutToShow.connect(self.update_checklist_menu)
        self.edit_checklist_button.setMenu(self.checklist_menu)
        side.addWidget(self.edit_checklist_button)
        for title, callback in [('Settings',self.settings),('Back up database',self.backup)]:
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
        self.task_buttons = []
        for title, callback in [('Add task',self.add_task),('Edit task',lambda:self.edit_task(self.tasks.currentItem())),('Delete task',self.delete_task),('Clear completed',self.clear)]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, cb=callback:self.safe(cb))
            buttons.addWidget(button)
            self.task_buttons.append(button)
        main.addLayout(buttons)
        main.addWidget(QLabel('Double-click a task to edit. Drag tasks to reorder when showing all tasks.'))
        layout.addLayout(main,3)
        self.theme()
        self.refresh_sidebar()
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda:self.safe(self.tick))
        self.timer.start(1000)
        if getattr(self.db,'is_cloud',False):
            self.tick()

    def safe(self, callback):
        if self.reporting_error:
            return
        try:
            callback()
        except Exception as error:
            self.reporting_error = True
            try:
                QMessageBox.warning(self,'Could not complete action',f'{error}\nPlease retry or check the database folder permissions. Do not delete your database to resolve this error.')
            finally:
                self.reporting_error = False

    def confirm(self, message):
        return not self.db.setting('confirm',True) or QMessageBox.question(self,'Please confirm',message)==QMessageBox.Yes

    def refresh_sidebar(self):
        self.sidebar.blockSignals(True)
        self.sidebar.clear()
        chosen = None
        for kind, title in [('daily','DAILY'),('weekly','WEEKLY'),('normal','OTHER')]:
            header = QListWidgetItem(title)
            header.setFlags(Qt.ItemIsEnabled)
            header.setData(CATEGORY_ROLE,kind)
            header.setSizeHint(QSize(200,44))
            font = header.font()
            font.setBold(True)
            font.setPointSize(10)
            header.setFont(font)
            light = self.db.setting('light',False)
            colors = {'daily':('#dcecff','#18334d','#235fa4','#8fc6ff'), 'weekly':('#ede4ff','#302745','#6942a1','#c9abff'), 'normal':('#dcf2eb','#1c3935','#256e5e','#8edac6')}
            day_bg, night_bg, day_fg, night_fg = colors[kind]
            header.setBackground(QBrush(QColor(day_bg if light else night_bg)))
            header.setForeground(QBrush(QColor(day_fg if light else night_fg)))
            self.sidebar.addItem(header)
            badge = QLabel(title)
            badge.setAttribute(Qt.WA_TransparentForMouseEvents)
            badge.setStyleSheet(f"background:{day_bg if light else night_bg}; color:{day_fg if light else night_fg}; border-radius:6px; padding:10px 12px; font-size:12px; font-weight:700;")
            self.sidebar.setItemWidget(header, badge)
            for row in self.db.checklists():
                if row['type']==kind:
                    item = QListWidgetItem(row['name'])
                    item.setData(Qt.UserRole,row['id'])
                    item.setData(CATEGORY_ROLE,kind)
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
                    item.setToolTip(row['name'] + '\nDrag within this category to reorder.')
                    self.sidebar.addItem(item)
                    if row['id']==self.selected:
                        chosen = item
        if chosen is None:
            chosen = next((self.sidebar.item(i) for i in range(self.sidebar.count()) if self.sidebar.item(i).data(Qt.UserRole)),None)
        self.sidebar.setCurrentItem(chosen)
        self.sidebar.blockSignals(False)
        self.select(chosen)

    def select(self, item, previous=None):
        if item is not None and item.data(Qt.UserRole) is None:
            return
        self.selected = item.data(Qt.UserRole) if item else None
        if self.db.setting('remember',True):
            self.db.set_setting('selected',self.selected)
        self.refresh_tasks()

    def current(self):
        return next((r for r in self.db.checklists() if r['id']==self.selected),None)

    def refresh_tasks(self, *args):
        selected_item = self.tasks.currentItem()
        selected_id = selected_item.data(Qt.UserRole) if selected_item else None
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
        if getattr(self.db,'is_cloud',False):
            self.reset_label.setText(self.db.reset_text(row) if row else 'Cloud account • Create or import a checklist')
        else:
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
            if getattr(self.db,'is_cloud',False):
                item.setData(Qt.UserRole+1,row['period_key'])
                item.setData(Qt.UserRole+2,self.db.snapshot['revision'])
            item.setFlags((item.flags() | Qt.ItemIsUserCheckable) if self.can_edit() else (item.flags() & ~Qt.ItemIsUserCheckable))
            item.setCheckState(Qt.Checked if task['is_completed'] else Qt.Unchecked)
            font = item.font()
            font.setStrikeOut(bool(task['is_completed']))
            item.setFont(font)
            self.tasks.addItem(item)
            if task['id'] == selected_id:
                self.tasks.setCurrentItem(item)
        self.tasks.setDragDropMode(QAbstractItemView.InternalMove if self.can_edit() and not query and self.filter.currentIndex()==0 and not bottom else QAbstractItemView.NoDragDrop)
        self.loading = False

    def toggle(self, item):
        if not self.loading:
            if getattr(self.db,'is_cloud',False):
                self.safe(lambda:self.db.complete(item.data(Qt.UserRole),item.checkState()==Qt.Checked,item.data(Qt.UserRole+1),item.data(Qt.UserRole+2)))
            else:
                self.safe(lambda:self.db.complete(item.data(Qt.UserRole),item.checkState()==Qt.Checked))
            self.refresh_tasks()

    def can_edit(self):
        return not getattr(self.db,'is_cloud',False) or self.db.online

    def tick(self):
        if self.db.reset_due():
            if getattr(self.db,'is_cloud',False):
                self.refresh_sidebar()
                self.theme()
            else:
                self.refresh_tasks()
        if getattr(self.db,'is_cloud',False):
            for button in self.task_buttons:
                button.setEnabled(self.can_edit())
            self.edit_checklist_button.setEnabled(self.can_edit())
            self.sidebar.setDragEnabled(self.can_edit())
            if not self.can_edit():
                self.refresh_tasks()


    def create(self):
        dialog = Editor(self,True)
        from uuid import uuid4
        cloud_id = str(uuid4())
        def save():
            if getattr(self.db,'is_cloud',False):
                self.selected = self.db.create_checklist(dialog.title.text(),dialog.choice.currentText(),cloud_id)
            else:
                self.selected = self.db.create_checklist(dialog.title.text(),dialog.choice.currentText())
            self.refresh_sidebar()
        self.run_editor(dialog,save)

    def edit_list(self):
        row = self.current()
        if row:
            dialog = Editor(self,True,row)
            def save():
                self.db.edit_checklist(row['id'],dialog.title.text(),dialog.choice.currentText())
                self.refresh_sidebar()
            self.run_editor(dialog,save)

    def duplicate(self):
        if self.current():
            self.selected = self.db.duplicate(self.selected)
            self.refresh_sidebar()

    def delete_list(self):
        row = self.current()
        revision = self.db.snapshot['revision'] if getattr(self.db,'is_cloud',False) else None
        if row and self.confirm('Delete this checklist and all of its tasks? This cannot be undone.'):
            if revision is None:
                self.db.delete_checklist(row['id'])
            else:
                self.db.delete_checklist(row['id'],revision)
            self.refresh_sidebar()

    def update_checklist_menu(self):
        self.checklist_menu.actions()[0].setEnabled(self.can_edit())
        for action in self.checklist_menu.actions()[1:]:
            action.setEnabled(self.can_edit() and self.current() is not None)

    def reorder_checklist(self, ident, destination):
        source = next((self.sidebar.item(i) for i in range(self.sidebar.count())
                       if self.sidebar.item(i).data(Qt.UserRole) == ident), None)
        if not self.sidebar.can_drop(source, destination):
            return
        kind = source.data(CATEGORY_ROLE)
        items = [self.sidebar.item(i) for i in range(self.sidebar.count())
                 if self.sidebar.item(i).data(Qt.UserRole) is not None
                 and self.sidebar.item(i).data(CATEGORY_ROLE) == kind]
        ordered = [item.data(Qt.UserRole) for item in items]
        insertion = sum(self.sidebar.row(item) < destination and item is not source for item in items)
        ordered.remove(ident)
        ordered.insert(insertion, ident)
        self.db.reorder('checklists', ordered)
        self.selected = ident
        self.refresh_sidebar()

    def add_task(self):
        if self.current():
            self.task_dialog()

    def edit_task(self, item):
        if not self.can_edit():
            return
        if item:
            row = next(t for t in self.db.tasks(self.selected) if t['id']==item.data(Qt.UserRole))
            self.task_dialog(row)

    def run_editor(self, dialog, save):
        revision = self.db.snapshot['revision'] if getattr(self.db,'is_cloud',False) else None
        while dialog.exec():
            try:
                if revision is not None and self.db.snapshot['revision']!=revision:
                    raise RuntimeError('The cloud changed while this editor was open. Your draft is preserved. Compare it with the current checklist before saving again.')
                save()
                return
            except Exception as error:
                if revision is None:
                    QMessageBox.warning(dialog,'Could not save',str(error))
                else:
                    self.db.refresh()
                    revision = self.db.snapshot['revision']
                    current = self.db.tasks(self.selected)
                    details = '\n'.join(f"{t['title']} [{t['priority']}] — {t['description']}" for t in current)
                    QMessageBox.warning(dialog,'Review your unsaved draft',str(error)+'\n\nCurrent cloud tasks:\n'+details)

    def task_dialog(self, row=None):
        dialog = Editor(self,row=row)
        checklist = self.selected
        from uuid import uuid4
        cloud_id = str(uuid4())
        def save():
            arguments = (checklist,dialog.title.text(),dialog.description.toPlainText(),dialog.choice.currentText(),dialog.due.text().strip() or None,row['id'] if row else None)
            if getattr(self.db,'is_cloud',False):
                self.db.save_task(*arguments,new_id=cloud_id)
            else:
                self.db.save_task(*arguments)
            self.refresh_tasks()
        self.run_editor(dialog,save)

    def delete_task(self):
        item = self.tasks.currentItem()
        ident = item.data(Qt.UserRole) if item else None
        revision = self.db.snapshot['revision'] if getattr(self.db,'is_cloud',False) else None
        if ident and self.confirm('Delete the selected task? This cannot be undone.'):
            if revision is None:
                self.db.delete_task(ident)
            else:
                self.db.delete_task(ident,revision)
            self.refresh_tasks()

    def clear(self):
        row = self.current()
        revision = self.db.snapshot['revision'] if getattr(self.db,'is_cloud',False) else None
        if row and self.confirm('Permanently delete completed tasks from this checklist?'):
            if revision is None:
                self.db.clear_completed(row['id'])
            else:
                self.db.clear_completed(row['id'],row['period_key'],revision)
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
        initial_shared = {key:widgets[key].isChecked() for key in ('light','completed_bottom','confirm')}
        if getattr(self.db,'is_cloud',False) and not self.can_edit():
            for key in initial_shared:
                widgets[key].setEnabled(False)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        def save():
            if getattr(self.db,'is_cloud',False):
                shared = {key:widgets[key].isChecked() for key in initial_shared if widgets[key].isChecked()!=initial_shared[key]}
                if shared:
                    self.db.save_shared_settings(shared)
                self.db.set_setting('remember',widgets['remember'].isChecked())
            else:
                for key, box in widgets.items():
                    self.db.set_setting(key,box.isChecked())
            if not widgets['remember'].isChecked():
                self.db.set_setting('selected',None)
            self.theme()
            self.refresh_sidebar()
        self.run_editor(dialog,save)

    def theme(self):
        light = self.db.setting('light',False)
        bg, panel, text = ('#f1f3f8','#ffffff','#182235') if light else ('#191c24','#252a36','#edf0fa')
        thumb = '#adb8ca' if light else '#566178'
        hover = '#7b8da9' if light else '#8293b2'
        self.setStyleSheet(f'''QWidget {{background:{bg}; color:{text}; font-size:14px;}}
        QListWidget,QLineEdit,QTextEdit,QComboBox {{background:{panel}; border:1px solid #657089; border-radius:6px; padding:8px;}}
        QListWidget::item {{padding:10px;}} QListWidget::item:selected {{background:#465eaa; color:white;}}
        QPushButton {{background:{panel}; border:1px solid #657089; border-radius:6px; padding:9px;}}
        QPushButton:hover {{background:#465eaa; color:white;}}
        QProgressBar {{border:0; background:{panel}; border-radius:6px; text-align:center;}}
        QProgressBar::chunk {{background:#657ee8; border-radius:6px;}}
        QMenu {{background:{panel}; border:1px solid #657089; padding:6px;}}
        QMenu::item {{padding:9px 24px; border-radius:4px;}}
        QMenu::item:selected {{background:#465eaa; color:white;}}
        QMenu::item:disabled {{color:#7e8798;}}
        QListWidget#checklistSidebar {{border:0; padding:4px;}}
        QListWidget#checklistSidebar::item {{margin:3px 0; border-radius:6px;}}
        QListWidget#checklistSidebar::item:hover {{background:#465eaa; color:white;}}
        QScrollBar:vertical {{background:transparent; width:10px; margin:3px 1px;}}
        QScrollBar::handle:vertical {{background:{thumb}; min-height:32px; border-radius:4px;}}
        QScrollBar::handle:vertical:hover {{background:{hover};}}
        QScrollBar:horizontal {{background:transparent; height:10px; margin:1px 3px;}}
        QScrollBar::handle:horizontal {{background:{thumb}; min-width:32px; border-radius:4px;}}
        QScrollBar::handle:horizontal:hover {{background:{hover};}}
        QScrollBar::add-line,QScrollBar::sub-line {{width:0; height:0; background:transparent; border:0;}}
        QScrollBar::add-page,QScrollBar::sub-page {{background:transparent;}}
        QCheckBox::indicator,QListWidget::indicator {{width:22px;height:22px;}}''')

    def backup(self):
        cloud = getattr(self.db,'is_cloud',False)
        path, _ = QFileDialog.getSaveFileName(self,'Save a new backup','cloud-snapshot.json' if cloud else 'checklists-backup.db','JSON snapshot (*.json)' if cloud else 'SQLite database (*.db)')
        if path:
            self.db.backup(path)
            QMessageBox.information(self,'Backup saved','Your snapshot was saved. Existing files are never overwritten.')

    def closeEvent(self, event):
        rect = self.geometry()
        self.safe(lambda:self.db.set_setting('geometry',[rect.x(),rect.y(),rect.width(),rect.height()]))
        event.accept()
