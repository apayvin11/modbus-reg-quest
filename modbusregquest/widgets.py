# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QStyledItemDelegate, QWidget


class Toggle(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(34, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#11A387" if self.isChecked() else "#DCE3EC"))
        painter.drawRoundedRect(QRectF(0, 1, 34, 18), 9, 9)
        painter.setBrush(QColor("white"))
        painter.drawEllipse(QRectF(17 if self.isChecked() else 3, 4, 12, 12))
        if self.hasFocus():
            painter.setPen(QPen(QColor("#536B87"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, 33, 19), 9, 9)


class TrendDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        values = index.data(Qt.ItemDataRole.UserRole) or []
        rect = QRectF(option.rect).adjusted(10, 17, -12, -17)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if len(values) < 2:
            painter.setPen(QPen(QColor("#D8E1EB"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(rect.left(), rect.center().y(), rect.right(), rect.center().y())
        else:
            low, high = min(values), max(values)
            spread = max(high-low, abs(high)*0.001, 0.001)
            path = QPainterPath()
            for i, value in enumerate(values):
                x = rect.left() + rect.width() * i / (len(values)-1)
                y = rect.bottom() - rect.height() * (0.15 + 0.7*(value-low)/spread)
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            fill = QPainterPath(path)
            fill.lineTo(rect.right(), rect.bottom())
            fill.lineTo(rect.left(), rect.bottom())
            fill.closeSubpath()
            gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
            gradient.setColorAt(0, QColor("#244D48") if option.palette.base().color().lightness() < 128 else QColor("#BBEADC"))
            gradient.setColorAt(1, option.palette.base().color())
            painter.fillPath(fill, gradient)
            painter.setPen(QPen(QColor("#1AA88A"), 1.6))
            painter.drawPath(path)
        painter.restore()


class TraceView(QWidget):
    """A stable inspector: polling does not replace the exchange being inspected."""
    def __init__(self, language="ru", parent=None):
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QTabWidget, QVBoxLayout
        from PySide6.QtGui import QFontDatabase
        from .i18n import tr
        super().__init__(parent)
        self.language = language
        self.editors = {}
        self.byte_views = {}
        self.headings = {}
        self.exchange_event = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        for response, title in ((False, "request"), (True, "response")):
            card = QFrame()
            card.setObjectName("card")
            body = QVBoxLayout(card)
            body.setContentsMargins(16, 14, 16, 8)
            heading = QLabel(tr(title, language))
            heading.setObjectName("eyebrow")
            body.addWidget(heading)
            self.headings[response] = heading
            tabs = QTabWidget()
            for kind, key in (("decoded", "decoded"), ("hex", "bytes")):
                if kind == "hex":
                    byte_view = AnnotatedBytes(language)
                    tabs.addTab(byte_view, tr(key, language))
                    self.byte_views[response] = byte_view
                    self.editors[response, kind] = byte_view.raw
                    continue
                editor = QPlainTextEdit()
                editor.setReadOnly(True)
                editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
                editor.setMinimumHeight(120)
                tabs.addTab(editor, tr(key, language))
                self.editors[response, kind] = editor
            body.addWidget(tabs)
            layout.addWidget(card, 1)
        self.set_event(None)

    def set_event(self, event):
        from .i18n import tr
        from .tracing import decoded_text, hex_dump
        self.exchange_event = event
        for response in (False, True):
            transport = (" · " + event.get("transport", "").upper()) if event else ""
            self.headings[response].setText(tr("response" if response else "request", self.language)+transport)
            if event is None:
                decoded = raw = tr("choose_exchange", self.language)
            else:
                decoded = decoded_text(event, response)
                frame = event.get("response" if response else "request", b"")
                if response:
                    raw = hex_dump(frame) or tr("no_frame", self.language)
                else:
                    sent = event.get("sent", 0)
                    raw = hex_dump(frame[:sent]) or tr("not_sent", self.language)
                    if sent < len(frame):
                        raw += "\n\n" + tr("prepared_frame", self.language) + "\n" + hex_dump(frame)
            self.editors[response, "decoded"].setPlainText(decoded)
            self.editors[response, "hex"].setPlainText(raw)
            self.byte_views[response].set_event(event, response)


class AnnotatedBytes(QWidget):
    def __init__(self, language, parent=None):
        from PySide6.QtWidgets import QGridLayout, QLabel, QPlainTextEdit, QScrollArea, QVBoxLayout
        from PySide6.QtGui import QFontDatabase
        from .i18n import tr
        super().__init__(parent)
        self.language = language
        self.groups = []
        self._columns = 0
        self.cards = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 0)
        self.note = QLabel(tr("byte_addresses", language))
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        outer.addWidget(self.note)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(0, 4, 6, 4)
        self.grid.setSpacing(8)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.data_heading = QLabel(tr("data", language))
        self.data_heading.setObjectName("eyebrow")
        self.data_heading.hide()
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.raw.setMaximumHeight(92)
        outer.addWidget(self.raw)

    def set_event(self, event, response):
        from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout
        from PySide6.QtGui import QFontDatabase
        from .i18n import tr
        from .tracing import frame_groups
        for card in self.cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self.cards = []
        self.groups = frame_groups(event, response) if event else []
        self.data_heading.setVisible(any(group["kind"] == "data" for group in self.groups))
        for group in self.groups:
            card = QFrame()
            card.setObjectName("byteGroupData" if group["kind"] == "data" else "byteGroup")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(8, 8, 8, 7)
            layout.setSpacing(5)
            key = "byte_unit" if group["label"] == "unit_id" else group["label"]
            title = tr(key, self.language)
            if group["address"] is not None:
                title += f" · {group['address']}"
            heading = QLabel(title)
            heading.setObjectName("muted")
            heading.setWordWrap(True)
            layout.addWidget(heading)
            value = QLabel(group["data"].hex(" ").upper())
            value.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setStyleSheet("font-size: 16px; font-weight: 600;")
            layout.addWidget(value)
            offset = QLabel(f"+{group['offset']:04X} · {len(group['data'])} B")
            offset.setObjectName("muted")
            layout.addWidget(offset)
            self.cards.append(card)
        self._columns = 0
        self.arrange()

    def arrange(self):
        columns = max(1, self.scroll.viewport().width()//142)
        if columns != self._columns:
            for column in range(self._columns):
                self.grid.setColumnStretch(column, 0)
            self._columns = columns
            self.grid.removeWidget(self.data_heading)
            row = column = 0
            data_started = False
            for card, group in zip(self.cards, self.groups):
                if group["kind"] == "data" and not data_started:
                    if column:
                        row += 1
                        column = 0
                    self.grid.addWidget(self.data_heading, row, 0, 1, columns)
                    row += 1
                    data_started = True
                self.grid.addWidget(card, row, column)
                column += 1
                if column == columns:
                    row += 1
                    column = 0
            for column in range(columns):
                self.grid.setColumnStretch(column, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange()
