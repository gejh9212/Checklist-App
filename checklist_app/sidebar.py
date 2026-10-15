"""Category-aware checklist dragging; headers and category boundaries stay fixed."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QAbstractItemView

CATEGORY_ROLE = Qt.UserRole + 1


class ChecklistSidebar(QListWidget):
    reorderRequested = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('checklistSidebar')
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropOverwriteMode(False)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setToolTip('Drag checklists up or down within the same category.')
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def insertion_row(self, position):
        item = self.itemAt(position)
        if item is None:
            return self.count()
        return self.row(item) + int(position.y() >= self.visualItemRect(item).center().y())

    def can_drop(self, source, destination):
        if source is None or source.data(Qt.UserRole) is None:
            return False
        kind = source.data(CATEGORY_ROLE)
        rows = [i for i in range(self.count())
                if self.item(i).data(Qt.UserRole) is not None
                and self.item(i).data(CATEGORY_ROLE) == kind]
        return bool(rows) and min(rows) <= destination <= max(rows) + 1

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)
        if event.source() is self and self.can_drop(self.currentItem(), self.insertion_row(event.position().toPoint())):
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        source = self.currentItem()
        destination = self.insertion_row(event.position().toPoint())
        if event.source() is not self or not self.can_drop(source, destination):
            event.ignore()
            return
        # The receiver saves first, then reloads the list; Qt must not remove a row.
        self.reorderRequested.emit(source.data(Qt.UserRole), destination)
        event.ignore()
