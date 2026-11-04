# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import time

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QApplication, QSplitter)

from .dialogs import CommandDialog, DeviceDialog, ParameterDialog, button, field, label
from .i18n import tr
from .models import Configuration, demo_configuration, new_id
from .poller import Poller
from .storage import Store, export_configuration, read_configuration
from .theme import icon, apply_theme, themed_color
from .widgets import Toggle, TrendDelegate, TraceView


class MainWindow(QMainWindow):
    def __init__(self, store: Store, config: Configuration | None = None):
        super().__init__()
        self.store = store
        self.config = config or store.load()
        self.poller = None
        self.polling = False
        self.values = {}
        self.histories = {}
        self.logs = deque(maxlen=500)
        self._log_dirty = True
        self._selected_log_id = None
        self._pending_commands = set()
        self._last_command = None
        self.stats = {"requests": 0, "errors": 0, "saved": 0, "latency": 0}
        self.page_index = 0
        self.last_update = None
        self._closing = False
        self.resize(1500, 1000)
        self.setMinimumSize(1160, 740)
        self.setWindowTitle("ModbusRegQuest")
        self.build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_live)
        self.timer.start(250)
        shortcut = QShortcut(QKeySequence("Space"), self)
        shortcut.activated.connect(self.toggle_polling)
        add_shortcut = QShortcut(QKeySequence.StandardKey.New, self)
        add_shortcut.activated.connect(self.edit_parameter)

    def t(self, key, **kwargs):
        return tr(key, self.config.language, **kwargs)

    def build_ui(self):
        apply_theme(QApplication.instance(), self.config.theme)
        old = self.centralWidget()
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(250)
        nav_layout = QVBoxLayout(sidebar)
        nav_layout.setContentsMargins(18, 32, 18, 22)
        nav_layout.setSpacing(6)
        brand_row = QHBoxLayout()
        brand_icon = QLabel()
        brand_icon.setPixmap(icon("activity", "#5DE0C0", 29).pixmap(29, 29))
        brand_row.addWidget(brand_icon)
        brand_row.addWidget(label("ModbusRegQuest", "brand"))
        brand_row.addStretch()
        nav_layout.addLayout(brand_row)
        sub = label("DEVICE WORKSPACE", "brandSub")
        sub.setContentsMargins(36, 1, 0, 0)
        nav_layout.addWidget(sub)
        nav_layout.addSpacing(44)
        nav_title = label(self.t("workspace"), "navTitle")
        nav_title.setContentsMargins(12, 0, 0, 12)
        nav_layout.addWidget(nav_title)
        self.nav_buttons = []
        for index, (key, symbol) in enumerate((("monitor", "grid"), ("devices", "devices"), ("activity", "activity"), ("commands", "bolt"), ("settings", "settings"))):
            control = button(self.t(key), lambda checked=False, index=index: self.navigate(index), "nav")
            control.setIcon(icon(symbol, "#8CA0BC", 18, "#111C2E"))
            control.setCheckable(True)
            control.setMinimumHeight(45)
            nav_layout.addWidget(control)
            self.nav_buttons.append(control)
        nav_layout.addStretch()
        bottom = QFrame()
        bottom.setObjectName("sidebarBottom")
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(14, 15, 14, 15)
        bottom_layout.setSpacing(7)
        local_row = QHBoxLayout()
        db = QLabel()
        db.setPixmap(icon("database", "#5CD7B9", 16).pixmap(16, 16))
        local_row.addWidget(db)
        local_row.addWidget(label("SQLite · local", "sidebarLabel"))
        local_row.addStretch()
        bottom_layout.addLayout(local_row)
        bottom_layout.addWidget(label(self.t("saved_local"), "sidebarMuted"))
        nav_layout.addWidget(bottom)
        nav_layout.addSpacing(8)
        version = label("v1.0.0     macOS / Linux", "sidebarMuted")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(version)
        root_layout.addWidget(sidebar)
        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(30, 28, 30, 18)
        content_layout.setSpacing(22)
        top = QHBoxLayout()
        self.breadcrumb = label("WORKSPACE  /  MODBUS", "eyebrow")
        top.addWidget(self.breadcrumb)
        top.addStretch()
        self.run_status = label(self.t("stopped"), "muted")
        top.addWidget(self.run_status)
        top.addSpacing(16)
        globe = QLabel()
        globe.setPixmap(icon("globe", "#8290A4", 16).pixmap(16, 16))
        top.addWidget(globe)
        self.language = QComboBox()
        self.language.addItem("Русский", "ru")
        self.language.addItem("English", "en")
        self.language.setCurrentIndex(self.language.findData(self.config.language))
        self.language.setFixedWidth(119)
        self.language.currentIndexChanged.connect(lambda: self.change_language(self.language.currentData()))
        top.addWidget(self.language)
        self.theme_button = button("", lambda: self.change_theme(
            "light" if self.config.theme == "dark" else "dark"), "ghost")
        self.theme_button.setFixedSize(38, 38)
        self.theme_button.setIcon(icon("sun" if self.config.theme == "dark" else "moon",
            "#A5B5CA" if self.config.theme == "dark" else "#738198", 20))
        self.theme_button.setIconSize(QSize(20, 20))
        self.theme_button.setToolTip(self.t("toggle_theme"))
        self.theme_button.setAccessibleName(self.t("toggle_theme"))
        top.addWidget(self.theme_button)
        content_layout.addLayout(top)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_monitor())
        self.pages.addWidget(self.build_devices())
        self.pages.addWidget(self.build_log())
        self.pages.addWidget(self.build_commands())
        self.pages.addWidget(self.build_settings())
        content_layout.addWidget(self.pages, 1)
        self.toast = label("", "toast")
        self.toast.hide()
        content_layout.addWidget(self.toast)
        footer = QHBoxLayout()
        self.footer_label = label(self.t("footer"), "muted")
        footer.addWidget(self.footer_label)
        footer.addStretch()
        self.update_label = label(self.t("shortcut"), "muted")
        footer.addWidget(self.update_label)
        content_layout.addLayout(footer)
        root_layout.addWidget(content, 1)
        self.setCentralWidget(root)
        if old:
            old.deleteLater()
        self.navigate(self.page_index)
        self.populate_parameters()
        self.populate_devices()
        self.refresh_live()

    def heading(self, title, subtitle):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.addWidget(label(self.t(title), "title"))
        layout.addWidget(label(self.t(subtitle), "subtitle"))
        return layout

    def build_monitor(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        heading = QHBoxLayout()
        heading.addLayout(self.heading("monitor", "subtitle"))
        heading.addStretch()
        heading.addWidget(button(self.t("send_command"), self.open_command, symbol="bolt"))
        self.poll_button = button(self.t("start"), self.toggle_polling, "primary", "play")
        self.poll_button.setMinimumHeight(42)
        self.poll_button.setMinimumWidth(166)
        heading.addWidget(self.poll_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(heading)
        metrics = QHBoxLayout()
        metrics.setSpacing(14)
        self.metric_values = {}
        self.metric_hints = {}
        for key, symbol in (("active", "activity"), ("requests", "network"), ("optimized", "bolt"), ("errors", "shield")):
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 17, 18, 16)
            card_layout.setSpacing(10)
            header = QHBoxLayout()
            header.addWidget(label(self.t(key), "eyebrow"))
            header.addStretch()
            glyph = QLabel()
            glyph.setPixmap(icon(symbol, "#0D9E81" if key in ("active", "optimized") else "#9AA8BB", 17).pixmap(17, 17))
            header.addWidget(glyph)
            card_layout.addLayout(header)
            value = label("0", "metric")
            hint = label("", "metricHint")
            card_layout.addWidget(value)
            card_layout.addWidget(hint)
            self.metric_values[key] = value
            self.metric_hints[key] = hint
            metrics.addWidget(card, 1)
        layout.addLayout(metrics)
        card = QFrame()
        card.setObjectName("tableCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(9)
        toolbar.setContentsMargins(20, 18, 20, 15)
        toolbar.addWidget(label(self.t("parameters"), "sectionTitle"))
        self.count_label = label("0", "muted")
        self.count_label.setContentsMargins(6, 0, 0, 0)
        toolbar.addWidget(self.count_label)
        toolbar.addStretch()
        toolbar.addWidget(button(self.t("import"), self.import_config, symbol="arrow_down"))
        toolbar.addWidget(button(self.t("export"), self.export_config, symbol="arrow_up"))
        toolbar.addWidget(button(self.t("add_parameter"), self.edit_parameter, "primary", "plus"))
        card_layout.addLayout(toolbar)
        filters = QHBoxLayout()
        filters.setContentsMargins(20, 0, 20, 18)
        filters.setSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(self.t("search"))
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.populate_parameters)
        filters.addWidget(self.search, 1)
        self.device_filter = QComboBox()
        self.device_filter.addItem(self.t("all_devices"), "")
        for device in self.config.devices:
            self.device_filter.addItem(device.name, device.id)
        self.device_filter.setMinimumWidth(170)
        self.device_filter.setMaximumWidth(240)
        self.device_filter.currentIndexChanged.connect(self.populate_parameters)
        filters.addWidget(self.device_filter)
        self.state_filter = QComboBox()
        for title in ("all_states", "enabled", "disabled", "error_filter"):
            self.state_filter.addItem(self.t(title), title)
        self.state_filter.setMinimumWidth(155)
        self.state_filter.currentIndexChanged.connect(self.populate_parameters)
        filters.addWidget(self.state_filter)
        card_layout.addLayout(filters)
        self.table_stack = QStackedWidget()
        self.table = self.make_table(["", "name", "device", "address", "type", "value", "unit", "trend", "status", ""])
        self.table.setItemDelegateForColumn(7, TrendDelegate(self.table))
        self.table.setColumnWidth(0, 54)
        self.table.setColumnWidth(1, 205)
        self.table.setColumnWidth(2, 170)
        for column, width in ((3, 80), (4, 82), (5, 112), (6, 55), (7, 100), (8, 100), (9, 50)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda row, column: self.edit_parameter(self.parameter_by_id(self.row_ids[row])))
        self.table_stack.addWidget(self.table)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setSpacing(16)
        empty_layout.addStretch()
        glyph = QLabel()
        glyph.setPixmap(icon("network", "#0C9B80", 52).pixmap(52, 52))
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(glyph)
        self.empty_title = label(self.t("empty_title"), "sectionTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_body = label(self.t("empty_body"), "muted")
        self.empty_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_body)
        empty_actions = QHBoxLayout()
        empty_actions.addStretch()
        self.empty_add_button = button(self.t("add_device"),
            lambda: self.edit_parameter() if self.config.devices else self.edit_device(), "primary", "plus")
        empty_actions.addWidget(self.empty_add_button)
        self.demo_button = button(self.t("demo"), self.load_demo)
        empty_actions.addWidget(self.demo_button)
        empty_actions.addStretch()
        empty_layout.addLayout(empty_actions)
        empty_layout.addStretch()
        self.table_stack.addWidget(empty)
        card_layout.addWidget(self.table_stack, 1)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(20, 13, 20, 14)
        self.shown_label = label("", "muted")
        bottom.addWidget(self.shown_label)
        bottom.addStretch()
        self.demo_badge = label(self.t("demo_badge"), "demoPill")
        self.demo_badge.setToolTip(self.t("demo_notice"))
        self.demo_badge.setVisible(any(d.transport == "demo" for d in self.config.devices))
        bottom.addWidget(self.demo_badge)
        bottom.addSpacing(8)
        bottom.addWidget(label(self.t("batching"), "muted"))
        card_layout.addLayout(bottom)
        layout.addWidget(card, 1)
        return page

    def make_table(self, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels([self.t(key) if key else "" for key in headers])
        table.verticalHeader().hide()
        table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.horizontalHeader().setHighlightSections(False)
        table.horizontalHeader().setMinimumSectionSize(35)
        table.verticalHeader().setDefaultSectionSize(56)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        return table

    def build_devices(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        heading = QHBoxLayout()
        heading.addLayout(self.heading("devices", "devices_subtitle"))
        heading.addStretch()
        heading.addWidget(button(self.t("add_device"), self.edit_device, "primary", "plus"))
        layout.addLayout(heading)
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 12, 0, 14)
        self.devices_table = self.make_table(["device", "transport", "endpoint", "base", "parameters", ""])
        self.devices_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in ((1, 110), (2, 270), (3, 240), (4, 110), (5, 50)):
            self.devices_table.setColumnWidth(column, width)
        self.devices_table.cellDoubleClicked.connect(lambda row, _: self.edit_device(self.config.devices[row]))
        card_layout.addWidget(self.devices_table)
        hint = label(self.t("device_hint"), "muted")
        hint.setContentsMargins(18, 10, 0, 0)
        card_layout.addWidget(hint)
        layout.addWidget(card, 1)
        return page

    def build_log(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        heading = QHBoxLayout()
        heading.addLayout(self.heading("activity", "log_subtitle"))
        heading.addStretch()
        heading.addWidget(button(self.t("export_log"), self.export_log, symbol="arrow_up"))
        heading.addWidget(button(self.t("clear"), self.clear_log))
        layout.addLayout(heading)
        splitter = QSplitter(Qt.Orientation.Vertical)
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 10, 0, 8)
        self.log_filter = QComboBox()
        for key in ("log_all", "read", "write", "error_filter"):
            self.log_filter.addItem(self.t(key), key)
        self.log_filter.currentIndexChanged.connect(self.populate_log)
        filters = QHBoxLayout()
        filters.setContentsMargins(16, 0, 16, 6)
        filters.addWidget(self.log_filter)
        filters.addStretch()
        card_layout.addLayout(filters)
        self.log_table = self.make_table(["time", "device", "operation", "function", "range", "duration", "result"])
        self.log_table.verticalHeader().setDefaultSectionSize(42)
        self.log_table.setMinimumHeight(130)
        for column, width in ((0, 110), (1, 190), (2, 95), (3, 80), (4, 110), (5, 95)):
            self.log_table.setColumnWidth(column, width)
        self.log_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.log_table.itemSelectionChanged.connect(self.select_log)
        card_layout.addWidget(self.log_table)
        self.log_empty = label(self.t("log_empty"), "muted")
        self.log_empty.setContentsMargins(16, 6, 0, 6)
        card_layout.addWidget(self.log_empty)
        splitter.addWidget(card)
        self.trace_view = TraceView(self.config.language)
        splitter.addWidget(self.trace_view)
        splitter.setSizes([310, 390])
        layout.addWidget(splitter, 1)
        return page

    def build_commands(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        heading = QHBoxLayout()
        heading.addLayout(self.heading("commands", "commands_subtitle"))
        heading.addStretch()
        self.command_button = button(self.t("send_command"), self.open_command, "primary", "bolt")
        self.command_button.setEnabled(not self._pending_commands)
        heading.addWidget(self.command_button)
        layout.addLayout(heading)
        self.command_status = label(self.t("command_pending" if self._pending_commands else "command_empty"), "muted")
        self.command_status.setWordWrap(True)
        layout.addWidget(self.command_status)
        hint = label(self.t("write_hint"), "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.command_trace = TraceView(self.config.language)
        layout.addWidget(self.command_trace, 1)
        if self._last_command:
            self.command_trace.set_event(self._last_command)
            self.command_status.setText(self.t("command_failed", error=self._last_command["error"]) if self._last_command["error"] else self.t("command_success"))
        return page

    def build_settings(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        layout.addLayout(self.heading("settings", "settings_subtitle"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 8, 0)
        body_layout.setSpacing(16)
        for title, description, symbol in (("database", "storage_hint", "database"), ("config_files", "config_hint", "file"), ("about", "about_text", "activity")):
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(24, 22, 24, 22)
            card_layout.setSpacing(14)
            heading = QHBoxLayout()
            glyph = QLabel()
            glyph.setPixmap(icon(symbol, "#0C9B80", 22).pixmap(22, 22))
            heading.addWidget(glyph)
            heading.addWidget(label(self.t(title), "sectionTitle"))
            heading.addStretch()
            card_layout.addLayout(heading)
            info = label(self.t(description), "muted")
            info.setWordWrap(True)
            card_layout.addWidget(info)
            if title == "database":
                path = label(str(self.store.path))
                path.setWordWrap(True)
                path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                card_layout.addWidget(path)
            if title == "config_files":
                actions = QHBoxLayout()
                actions.addWidget(button(self.t("import"), self.import_config, symbol="arrow_down"))
                actions.addWidget(button(self.t("export"), self.export_config, symbol="arrow_up"))
                actions.addStretch()
                card_layout.addLayout(actions)
            body_layout.addWidget(card)
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        return page

    def navigate(self, index):
        self.page_index = index
        self.pages.setCurrentIndex(index)
        for i, control in enumerate(self.nav_buttons):
            control.setChecked(i == index)
        if index == 2:
            self.populate_log()

    def parameter_by_id(self, identifier):
        return next((parameter for parameter in self.config.parameters if parameter.id == identifier), None)

    def cell(self, table, row, column, text, color=None, bold=False):
        item = QTableWidgetItem(str(text))
        item.setToolTip(str(text))
        if color:
            item.setForeground(QColor(themed_color(color, self.config.theme)))
        if bold:
            font = item.font()
            font.setWeight(QFont.Weight.DemiBold)
            item.setFont(font)
        table.setItem(row, column, item)
        return item

    def populate_parameters(self, *_):
        if not hasattr(self, "table_stack"):
            return
        devices = {device.id: device for device in self.config.devices}
        query = self.search.text().strip().casefold()
        device_filter = self.device_filter.currentData()
        state = self.state_filter.currentData()
        parameters = []
        for parameter in self.config.parameters:
            if device_filter and parameter.device_id != device_filter:
                continue
            if state == "enabled" and not parameter.enabled or state == "disabled" and parameter.enabled:
                continue
            if state == "error_filter" and not self.values.get(parameter.id, {}).get("error"):
                continue
            device = devices[parameter.device_id]
            if query and query not in f"{parameter.name} {parameter.address} {device.name} {parameter.unit}".casefold():
                continue
            parameters.append(parameter)
        self.row_ids = [parameter.id for parameter in parameters]
        self.table.setRowCount(len(parameters))
        for row, parameter in enumerate(parameters):
            device = devices[parameter.device_id]
            toggle = Toggle(parameter.enabled)
            toggle.setAccessibleName(f"{self.t('poll_enabled')}: {parameter.name}")
            toggle.setToolTip(self.t("poll_enabled"))
            toggle.toggled.connect(lambda checked, identifier=parameter.id: self.toggle_parameter(identifier, checked))
            toggle_wrapper = QWidget()
            toggle_layout = QHBoxLayout(toggle_wrapper)
            toggle_layout.setContentsMargins(0, 0, 0, 0)
            toggle_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            toggle_layout.addWidget(toggle)
            self.table.setCellWidget(row, 0, toggle_wrapper)
            self.cell(self.table, row, 1, parameter.name, bold=True)
            self.cell(self.table, row, 2, device.name, "#7B889C")
            item = self.cell(self.table, row, 3, str(parameter.address), "#52647C")
            item.setToolTip(f"FC{parameter.function:02d} · {parameter.width} {self.t('registers')} · PDU {parameter.wire_address(device)}")
            self.cell(self.table, row, 4, parameter.data_type, "#8290A3")
            self.cell(self.table, row, 5, "—", bold=True)
            self.cell(self.table, row, 6, parameter.unit, "#8390A3")
            self.cell(self.table, row, 7, "")
            self.cell(self.table, row, 8, "")
            actions = button("", kind="ghost", symbol="more")
            actions.setAccessibleName(self.t("edit") + " " + parameter.name)
            actions.setFixedWidth(34)
            actions.clicked.connect(lambda checked=False, identifier=parameter.id, control=actions: self.parameter_menu(identifier, control))
            self.table.setCellWidget(row, 9, actions)
        self.count_label.setText(f"{len(self.config.parameters):02d}")
        self.shown_label.setText(self.t("shown", shown=len(parameters), total=len(self.config.parameters)))
        self.table_stack.setCurrentIndex(0 if parameters else 1)
        is_empty = not self.config.parameters
        self.empty_title.setText(self.t("empty_title" if is_empty else "no_results"))
        self.empty_body.setVisible(is_empty)
        self.empty_add_button.setVisible(is_empty)
        self.empty_add_button.setText(self.t("add_parameter" if self.config.devices else "add_device"))
        self.demo_button.setVisible(is_empty and not self.config.devices)
        self.refresh_live()

    def populate_devices(self):
        self.devices_table.setRowCount(len(self.config.devices))
        for row, device in enumerate(self.config.devices):
            self.cell(self.devices_table, row, 0, device.name, bold=True)
            self.cell(self.devices_table, row, 1, device.transport.upper(), "#0C9B80")
            self.cell(self.devices_table, row, 2, device.endpoint, "#76869C")
            self.cell(self.devices_table, row, 3, "1 → 0 (−1)" if device.address_base else "0 → 0", "#76869C")
            self.cell(self.devices_table, row, 4, sum(p.device_id == device.id for p in self.config.parameters))
            actions = button("", kind="ghost", symbol="more")
            actions.clicked.connect(lambda checked=False, d=device, control=actions: self.device_menu(d, control))
            self.devices_table.setCellWidget(row, 5, actions)

    def state(self, parameter):
        value = self.values.get(parameter.id)
        if not parameter.enabled:
            return "off", "#A0AABC"
        if not self.polling:
            return ("paused" if value else "waiting"), "#97A2B3"
        if not value:
            return "waiting", "#97A2B3"
        if value.get("error"):
            return "error", "#D46663"
        if time.time() - value["time"] > max(parameter.interval*2.5, parameter.interval+2):
            return "stale", "#C49A3A"
        return "live", "#0E9B7C"

    def format_value(self, value):
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, int):
            return str(value)
        text = f"{value:.6f}".rstrip("0").rstrip(".") if abs(value) >= 0.000001 or value == 0 else f"{value:.6g}"
        return text.replace(".", ",") if self.config.language == "ru" else text

    def refresh_live(self):
        if not hasattr(self, "metric_values"):
            return
        active = sum(parameter.enabled for parameter in self.config.parameters)
        self.metric_values["active"].setText(f"{active:02d}")
        for key, stat in (("requests", "requests"), ("optimized", "saved"), ("errors", "errors")):
            self.metric_values[key].setText(str(self.stats[stat]))
        self.metric_hints["active"].setText(self.t("enabled_of", enabled=active, total=len(self.config.parameters)))
        self.metric_hints["requests"].setText(self.t("session"))
        self.metric_hints["optimized"].setText(self.t("batching"))
        percent = round(100*(1-self.stats["errors"]/self.stats["requests"]), 1) if self.stats["requests"] else 100
        self.metric_hints["errors"].setText(self.t("successful", percent=percent))
        self.run_status.setText(("●  " if self.polling else "○  ") + self.t("running" if self.polling else "stopped"))
        self.run_status.setStyleSheet("color: #0C9B80;" if self.polling else "color: #8491A3;")
        self.poll_button.setText(self.t("stop" if self.polling else "start"))
        self.poll_button.setObjectName("stop" if self.polling else "primary")
        self.poll_button.setIcon(icon("pause" if self.polling else "play", "#BC4A48" if self.polling else "#FFFFFF"))
        self.poll_button.style().unpolish(self.poll_button)
        self.poll_button.style().polish(self.poll_button)
        self.poll_button.setEnabled(bool(active) or self.polling)
        parameter_map = {parameter.id: parameter for parameter in self.config.parameters}
        for row, identifier in enumerate(getattr(self, "row_ids", [])):
            parameter = parameter_map.get(identifier)
            if not parameter:
                continue
            value = self.values.get(identifier, {})
            status, color = self.state(parameter)
            item = self.table.item(row, 5)
            if not item:
                continue
            item.setText(self.format_value(value.get("value")))
            item.setForeground(QColor(themed_color("#344C64" if parameter.enabled else "#A0AABC", self.config.theme)))
            item.setToolTip(value.get("error") or (self.t("last_read", time=datetime.fromtimestamp(value["time"]).strftime("%H:%M:%S")) if value.get("time") else ""))
            self.table.item(row, 7).setData(Qt.ItemDataRole.UserRole, list(self.histories.get(identifier, [])))
            self.table.item(row, 8).setText("●  " + self.t(status))
            self.table.item(row, 8).setForeground(QColor(themed_color(color, self.config.theme)))
            self.table.item(row, 8).setToolTip(value.get("error", ""))
        if self.last_update:
            self.update_label.setText(self.t("updated", time=datetime.fromtimestamp(self.last_update).strftime("%H:%M:%S")))
        self.table.viewport().update()
        if self.page_index == 2 and self._log_dirty:
            self.populate_log()

    def ensure_worker(self):
        if self.poller is None:
            self.poller = Poller(self.config, self, polling=False)
            self.poller.readings.connect(self.on_readings)
            self.poller.activity.connect(self.on_activity)
            self.poller.statistics.connect(self.on_statistics)
            self.poller.command_finished.connect(self.on_command_finished)
            self.poller.finished.connect(self.polling_finished)
            self.poller.start()
        return self.poller

    def toggle_polling(self):
        if self.polling:
            self.polling = False
            self.poller.set_polling(False)
        elif any(parameter.enabled for parameter in self.config.parameters):
            self.stats = {"requests": 0, "errors": 0, "saved": 0, "latency": 0}
            self.polling = True
            self.ensure_worker().set_polling(True)
        self.refresh_live()

    def polling_finished(self):
        worker = self.sender()
        if self.poller is worker:
            self.poller = None
            self.polling = False
        worker.deleteLater()
        self.refresh_live()
        if self._closing:
            self.close()

    def valid_revision(self, revision):
        return self.poller and not self.poller._stop.is_set() and revision == self.poller.revision

    def on_readings(self, revision, values):
        if not self.valid_revision(revision):
            return
        for value in values:
            if value["error"]:
                previous = self.values.get(value["id"], {})
                value["value"] = previous.get("value")
                value["time"] = previous.get("time", value["time"])
            else:
                self.histories.setdefault(value["id"], deque(maxlen=60)).append(float(value["value"]))
                self.last_update = value["time"]
            self.values[value["id"]] = value
        if self.state_filter.currentData() == "error_filter":
            self.populate_parameters()

    def on_activity(self, event):
        self.logs.appendleft(event)
        self._log_dirty = True

    def on_statistics(self, revision, stats):
        if self.valid_revision(revision):
            self.stats = stats

    def populate_log(self, *_):
        self._log_dirty = False
        mode = self.log_filter.currentData()
        events = [event for event in self.logs if mode == "log_all" or event["operation"] == mode
                  or mode == "error_filter" and event["error"]]
        self._log_row_events = events
        self.log_table.blockSignals(True)
        self.log_table.setUpdatesEnabled(False)
        self.log_table.setRowCount(len(events))
        self.log_empty.setVisible(not events)
        selected_row = None
        for row, event in enumerate(events):
            values = [datetime.fromtimestamp(event["time"]).strftime("%H:%M:%S.%f")[:-3], event["device"],
                self.t(event["operation"]), f"0x{event['function']:02X}",
                f"{event['address']}–{event['address']+event['count']-1}", event["ms"], event["error"] or self.t("ok")]
            for column, value in enumerate(values):
                self.cell(self.log_table, row, column, value, ("#CF6662" if event["error"] else "#0C9B80") if column == 6 else "#697D95")
            if event["id"] == self._selected_log_id:
                selected_row = row
        if events:
            self.log_table.selectRow(selected_row if selected_row is not None else 0)
        self.log_table.setUpdatesEnabled(True)
        self.log_table.blockSignals(False)
        self.select_log()

    def select_log(self):
        row = self.log_table.currentRow()
        if 0 <= row < len(getattr(self, "_log_row_events", [])):
            event = self._log_row_events[row]
            if self.trace_view.exchange_event is None or self.trace_view.exchange_event["id"] != event["id"]:
                self.trace_view.set_event(event)
            self._selected_log_id = event["id"]
        else:
            self._selected_log_id = None
            self.trace_view.set_event(None)

    def clear_log(self):
        self.logs.clear()
        self._selected_log_id = None
        self.log_table.clearSelection()
        self.log_table.setCurrentCell(-1, -1)
        self.populate_log()

    def export_log(self):
        import json
        from .tracing import export_event
        path, _ = QFileDialog.getSaveFileName(self, self.t("export_log"), "modbusregquest-log.json", "JSON (*.json)")
        if path:
            try:
                from .storage import atomic_write
                payload = {"format": "modbusregquest-log", "version": 1,
                           "exchanges": [export_event(event) for event in self.logs]}
                atomic_write(Path(path), json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
                self.show_toast(self.t("log_exported"))
            except Exception as exc:
                QMessageBox.warning(self, self.t("operation_error"), str(exc))

    def open_command(self, device_id=None, parameter=None):
        if self._pending_commands:
            self.navigate(3)
            return
        if not self.config.devices:
            self.edit_device()
            if not self.config.devices:
                return
        dialog = CommandDialog(self.config, device_id if isinstance(device_id, str) else None, parameter, self)
        if dialog.exec():
            self.send_command(dialog.result_command)

    def send_command(self, command):
        if self._pending_commands:
            return False
        try:
            self.ensure_worker().enqueue(command)
        except Exception as exc:
            QMessageBox.warning(self, self.t("operation_error"), str(exc))
            return False
        self._pending_commands.add(command.id)
        self.navigate(3)
        self.command_status.setText(self.t("command_pending"))
        self.command_button.setEnabled(False)
        self.command_trace.set_event(None)
        return True

    def on_command_finished(self, event):
        self._pending_commands.discard(event["command_id"])
        self._last_command = event
        self.command_trace.set_event(event)
        self.command_button.setEnabled(not self._pending_commands)
        self.command_status.setText(self.t("command_failed", error=event["error"]) if event["error"] else self.t("command_success"))

    def change_theme(self, theme):
        if theme == self.config.theme:
            return
        config = deepcopy(self.config)
        config.theme = theme
        self.apply_config(config)

    def apply_config(self, config, rebuild=True):
        try:
            self.store.save(config)
        except Exception as exc:
            QMessageBox.critical(self, self.t("save_error"), self.t("unsaved_error") + "\n\n" + str(exc))
            return False
        old_parameters = {p.id: p for p in self.config.parameters}
        old_devices = {d.id: d for d in self.config.devices}
        devices = {d.id: d for d in config.devices}
        keep = {p.id for p in config.parameters if old_parameters.get(p.id) == p and old_devices.get(p.device_id) == devices[p.device_id]}
        self.values = {key: value for key, value in self.values.items() if key in keep}
        self.histories = {key: value for key, value in self.histories.items() if key in keep}
        wire_changed = self.config.devices != config.devices or self.config.parameters != config.parameters
        self.config = config
        if self.poller:
            if wire_changed:
                self.poller.configure(config)
            if not any(parameter.enabled for parameter in config.parameters):
                self.polling = False
                self.poller.set_polling(False)
        if rebuild:
            self.build_ui()
        return True

    def edit_parameter(self, parameter=None):
        if isinstance(parameter, bool):
            parameter = None
        if not self.config.devices:
            self.edit_device()
            if not self.config.devices:
                return
        dialog = ParameterDialog(self.config, parameter, self)
        if dialog.exec():
            config = deepcopy(self.config)
            p = dialog.result_parameter
            if parameter:
                config.parameters = [p if existing.id == p.id else existing for existing in config.parameters]
            else:
                config.parameters.append(p)
            self.apply_config(config)

    def edit_device(self, device=None):
        if isinstance(device, bool):
            device = None
        dialog = DeviceDialog(self.config, device, self)
        if dialog.exec():
            config = deepcopy(self.config)
            d = dialog.result_device
            if device:
                config.devices = [d if existing.id == d.id else existing for existing in config.devices]
            else:
                config.devices.append(d)
            self.apply_config(config)

    def toggle_parameter(self, identifier, checked):
        config = deepcopy(self.config)
        next(p for p in config.parameters if p.id == identifier).enabled = checked
        if not self.apply_config(config, rebuild=False):
            self.populate_parameters()
        elif self.state_filter.currentData() != "all_states":
            QTimer.singleShot(0, self.populate_parameters)

    def parameter_menu(self, identifier, control):
        parameter = self.parameter_by_id(identifier)
        if not parameter:
            return
        menu = QMenu(self)
        if parameter.function in (1, 3):
            menu.addAction(self.t("write_value"), lambda: self.open_command(parameter=parameter))
            menu.addSeparator()
        menu.addAction(self.t("edit"), lambda: self.edit_parameter(parameter))
        menu.addAction(self.t("duplicate"), lambda: self.duplicate_parameter(parameter))
        menu.addSeparator()
        menu.addAction(self.t("delete"), lambda: self.delete_parameter(parameter))
        menu.exec(control.mapToGlobal(control.rect().bottomLeft()))

    def duplicate_parameter(self, parameter):
        config = deepcopy(self.config)
        p = deepcopy(parameter)
        p.id = new_id()
        p.name = (p.name[:85] + " · " + self.t("copy"))[:100]
        config.parameters.append(p)
        self.apply_config(config)

    def delete_parameter(self, parameter):
        if self.confirm(self.t("delete_parameter", name=parameter.name)):
            config = deepcopy(self.config)
            config.parameters = [p for p in config.parameters if p.id != parameter.id]
            self.apply_config(config)

    def device_menu(self, device, control):
        menu = QMenu(self)
        menu.addAction(self.t("send_command"), lambda: self.open_command(device.id))
        menu.addAction(self.t("edit"), lambda: self.edit_device(device))
        menu.addAction(self.t("delete"), lambda: self.delete_device(device))
        menu.exec(control.mapToGlobal(control.rect().bottomLeft()))

    def delete_device(self, device):
        count = sum(p.device_id == device.id for p in self.config.parameters)
        if self.confirm(self.t("delete_device", name=device.name, count=count)):
            config = deepcopy(self.config)
            config.devices = [d for d in config.devices if d.id != device.id]
            config.parameters = [p for p in config.parameters if p.device_id != device.id]
            self.apply_config(config)

    def change_language(self, language):
        if language == self.config.language:
            return
        config = deepcopy(self.config)
        config.language = language
        self.apply_config(config)

    def confirm(self, text):
        message = QMessageBox(QMessageBox.Icon.Question, "ModbusRegQuest", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        message.button(QMessageBox.StandardButton.Yes).setText(self.t("save") if "?" not in text else self.t("ok"))
        message.button(QMessageBox.StandardButton.Cancel).setText(self.t("cancel"))
        message.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return message.exec() == QMessageBox.StandardButton.Yes

    def load_demo(self):
        if self.config.devices:
            return
        if self.apply_config(demo_configuration(self.config.language)):
            self.toggle_polling()

    def export_config(self):
        path, _ = QFileDialog.getSaveFileName(self, self.t("export_title"), "modbusregquest.json", "JSON (*.json)")
        if path:
            try:
                export_configuration(self.config, Path(path))
                self.show_toast(self.t("exported"))
            except Exception as exc:
                QMessageBox.warning(self, self.t("operation_error"), str(exc))

    def import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, self.t("import_title"), "", "JSON (*.json)")
        if not path:
            return
        try:
            config = read_configuration(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, self.t("operation_error"), str(exc))
            return
        if self.confirm(self.t("import_confirm", devices=len(config.devices), parameters=len(config.parameters))):
            if self.apply_config(config):
                self.show_toast(self.t("imported"))

    def show_toast(self, text):
        self.toast.setText(text)
        self.toast.show()
        QTimer.singleShot(4000, self.toast.hide)

    def closeEvent(self, event):
        if self.poller and self.poller.isRunning():
            self._closing = True
            self.poller.stop()
            event.ignore()
            return
        self.timer.stop()
        event.accept()
