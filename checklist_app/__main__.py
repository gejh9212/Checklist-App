import sys
from .database import Database, data_path


def main():
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .gui import Window
    app = QApplication(sys.argv)
    try:
        if '--cloud' in sys.argv:
            from .cloud.desktop import launch
            return launch(app, data_path())
        db = Database(data_path())
        window = Window(db)
        window.show()
        result = app.exec()
        db.close()
        return result
    except Exception as error:
        QMessageBox.critical(None,'ChecklistApp could not start',f'{error}\nYour existing database has not been replaced. Check folder permissions or restore a separate backup only after preserving the original database.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
