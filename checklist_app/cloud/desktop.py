"""Opt-in desktop cloud startup. Reuses the existing Window and widgets."""
from pathlib import Path
from PySide6.QtCore import QThread, QEventLoop, Qt
from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout, QLineEdit,
    QPushButton, QLabel, QMessageBox, QHBoxLayout)
from .auth import SecureStorage, make_client
from .cache import ReadCache
from .config import CloudConfig
from .store import CloudDatabase, SupabaseTransport
from .realtime import RealtimeWatcher


class Request(QThread):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.value = None
        self.error = None

    def run(self):
        try:
            self.value = self.callback()
        except Exception as error:
            self.error = error


def run_request(callback):
    """Run HTTP away from Qt; keep painting, prevent reentrant user mutations."""
    request = Request(callback)
    loop = QEventLoop()
    request.finished.connect(loop.quit)
    windows = [w for w in QApplication.topLevelWidgets() if w.isEnabled()]
    for window in windows:
        window.setEnabled(False)
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        request.start()
        loop.exec()
        request.wait()
    finally:
        QApplication.restoreOverrideCursor()
        for window in windows:
            window.setEnabled(True)
    if request.error:
        raise request.error
    return request.value


class Login(QDialog):
    def __init__(self, client):
        super().__init__()
        self.client = client
        self.user_id = None
        self.setWindowTitle('ChecklistApp • Cloud account')
        self.setMinimumWidth(360)
        form = QFormLayout(self)
        form.addRow(QLabel('Sign in with the same email on Windows and mobile.'))
        self.email = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow('Email',self.email)
        form.addRow('Password',self.password)
        self.message = QLabel()
        self.message.setWordWrap(True)
        form.addRow(self.message)
        row = QHBoxLayout()
        for label, signup in [('Sign in',False),('Create account',True)]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False,s=signup:self.authenticate(s))
            row.addWidget(button)
        form.addRow(row)

    def authenticate(self, signup=False):
        email = self.email.text().strip()
        password = self.password.text()
        if not email or len(password)<6:
            self.message.setText('Enter your email and a password of at least six characters.')
            return
        try:
            credentials = {'email':email,'password':password}
            result = run_request(lambda:self.client.auth.sign_up(credentials) if signup else self.client.auth.sign_in_with_password(credentials))
            self.password.clear()
            if result.session and result.user:
                self.user_id = str(result.user.id)
                self.accept()
            else:
                self.message.setText('Check your email for a confirmation link, then return here to sign in.')
        except Exception:
            self.password.clear()
            self.message.setText('Sign-in failed. Check your email/password, internet connection, and Supabase email confirmation settings. No local checklist data was changed.')


def launch(app, base_path):
    from ..gui import Window
    config = CloudConfig.load()
    storage = SecureStorage(config.namespace)
    client = make_client(config,storage)
    user_id = None
    try:
        user = run_request(lambda:client.auth.get_user()).user
        if user:
            user_id = str(user.id)
    except Exception:
        # Cached view is allowed only for the last securely recorded account.
        user_id = storage.get_item('checklist-last-user')
    if not user_id:
        login = Login(client)
        if not login.exec():
            client.auth.close()
            return 0
        user_id = login.user_id
    storage.set_item('checklist-last-user',user_id)
    cache = ReadCache(Path(base_path).parent/'cloud'/config.namespace/(user_id+'.db'),user_id)
    store = CloudDatabase(SupabaseTransport(client),cache,run_request)
    store.refresh()
    window = Window(store)
    window.setWindowTitle('ChecklistApp • Cloud')
    status = QLabel(store.status)
    window.statusBar().addWidget(status,1)
    refresh = QPushButton('Refresh cloud')
    refresh.clicked.connect(lambda:window.safe(lambda:(store.refresh(),window.refresh_sidebar())))
    window.statusBar().addPermanentWidget(refresh)
    from .migration_ui import import_sqlite
    migrate = QPushButton('Import SQLite…')
    migrate.clicked.connect(lambda:window.safe(lambda:import_sqlite(window,store,base_path)))
    window.statusBar().addPermanentWidget(migrate)
    zone = QPushButton('Account timezone…')
    def change_zone():
        from PySide6.QtWidgets import QInputDialog
        revision = store.snapshot['revision']
        value, accepted = QInputDialog.getText(window,'Account timezone','IANA timezone (changes recurring periods on all devices):',text=store.snapshot['timezone'])
        if accepted and value and value!=store.snapshot['timezone'] and window.confirm('Changing timezone starts fresh recurring periods. Earlier completions remain in history. Continue?'):
            store.mutate('timezone',{'timezone':value.strip()},revision)
            window.refresh_sidebar()
    zone.clicked.connect(lambda:window.safe(change_zone))
    window.statusBar().addPermanentWidget(zone)
    logout = QPushButton('Sign out')
    def sign_out():
        watcher.close()
        try:
            run_request(lambda:client.auth.sign_out({'scope':'local'}))
        except Exception:
            pass
        storage.clear()
        window.close()
    logout.clicked.connect(lambda:window.safe(sign_out))
    window.statusBar().addPermanentWidget(logout)
    window.timer.timeout.connect(lambda:status.setText(store.status))
    watcher = RealtimeWatcher(client,config,user_id,lambda:setattr(store,'dirty',True))
    window.show()
    result = app.exec()
    watcher.close()
    client.auth.close()
    store.close()
    return result
