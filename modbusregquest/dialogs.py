# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt, QLocale
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from .i18n import tr
from .models import Configuration, Device, Parameter, TYPES
from .theme import icon


def label(text, style=None):
    widget = QLabel(text)
    if style:
        widget.setObjectName(style)
    return widget


def field(title, control, hint=None):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(7)
    layout.addWidget(label(title))
    layout.addWidget(control)
    if hint:
        description = label(hint, "muted")
        description.setWordWrap(True)
        layout.addWidget(description)
    return widget


def spin(low, high, value, decimals=None):
    control = QSpinBox() if decimals is None else QDoubleSpinBox()
    if decimals is not None:
        control.setDecimals(decimals)
        control.setSingleStep(0.1)
    control.setRange(low, high)
    control.setValue(value)
    control.lineEdit().setTextMargins(10, 0, 8, 0)
    return control


def button(text, callback=None, kind=None, symbol=None):
    control = QPushButton(text)
    control.setCursor(Qt.CursorShape.PointingHandCursor)
    if kind:
        control.setObjectName(kind)
    if symbol:
        control.setIcon(icon(symbol, "#FFFFFF" if kind == "primary" else "#7B889B"))
    if callback:
        control.clicked.connect(callback)
    return control


class Editor(QDialog):
    def __init__(self, title, language, parent=None):
        super().__init__(parent)
        self.language = language
        self.setLocale(QLocale("ru_RU" if language == "ru" else "en_US"))
        self.setWindowTitle(title)
        self.setMinimumWidth(620)
        self.resize(660, 740)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 25, 26, 22)
        outer.setSpacing(18)
        outer.addWidget(label(title, "sectionTitle"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("editorBody")
        self.form = QGridLayout(body)
        self.form.setContentsMargins(0, 3, 8, 8)
        self.form.setHorizontalSpacing(16)
        self.form.setVerticalSpacing(18)
        self.form.setColumnStretch(0, 1)
        self.form.setColumnStretch(1, 1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button(self.t("cancel"), self.reject))
        self.save_button = button(self.t("save"), self.submit, "primary", "check")
        self.save_button.setDefault(True)
        actions.addWidget(self.save_button)
        outer.addLayout(actions)

    def t(self, key, **kwargs):
        return tr(key, self.language, **kwargs)

    def invalid(self, exc):
        QMessageBox.warning(self, self.t("invalid"), str(exc))


class DeviceDialog(Editor):
    def __init__(self, config: Configuration, device=None, parent=None):
        self.config = config
        self.result_device = deepcopy(device) if device else Device(name="")
        super().__init__(tr("edit" if device else "add_device", config.language), config.language, parent)
        d = self.result_device
        self.name = QLineEdit(d.name)
        self.name.setPlaceholderText("PLC · Main cabinet")
        self.name.setMaxLength(100)
        self.transport = QComboBox()
        for title, value in (("Modbus TCP", "tcp"), ("Modbus RTU", "rtu"), ("Simulator / Demo", "demo")):
            self.transport.addItem(title, value)
        self.transport.setCurrentIndex(self.transport.findData(d.transport))
        self.form.addWidget(field(self.t("device_name"), self.name), 0, 0, 1, 2)
        self.form.addWidget(field(self.t("transport"), self.transport), 1, 0)
        self.unit_id = spin(1 if d.transport == "rtu" else 0, 247 if d.transport == "rtu" else 255, d.unit_id)
        self.transport.currentIndexChanged.connect(lambda: self.unit_id.setRange(
            1 if self.transport.currentData() == "rtu" else 0,
            247 if self.transport.currentData() == "rtu" else 255))
        self.form.addWidget(field(self.t("unit_id"), self.unit_id), 1, 1)
        self.stack = QStackedWidget()
        tcp = QWidget()
        tcp_form = QGridLayout(tcp)
        tcp_form.setContentsMargins(0, 0, 0, 0)
        tcp_form.setHorizontalSpacing(16)
        self.host = QLineEdit(d.host)
        self.host.setMaxLength(253)
        self.port = spin(1, 65535, d.port)
        tcp_form.addWidget(field(self.t("host"), self.host), 0, 0)
        tcp_form.addWidget(field(self.t("port"), self.port), 0, 1)
        self.stack.addWidget(tcp)
        rtu = QWidget()
        rtu_form = QGridLayout(rtu)
        rtu_form.setContentsMargins(0, 0, 0, 0)
        rtu_form.setHorizontalSpacing(16)
        rtu_form.setVerticalSpacing(16)
        self.serial_port = QComboBox()
        self.serial_port.setEditable(True)
        try:
            from serial.tools.list_ports import comports
            for serial_port in comports():
                self.serial_port.addItem(serial_port.device)
        except OSError:
            pass
        self.serial_port.setCurrentText(d.serial_port)
        self.baudrate = QComboBox()
        for baudrate in sorted({1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, d.baudrate}):
            self.baudrate.addItem(str(baudrate), baudrate)
        self.baudrate.setCurrentIndex(self.baudrate.findData(d.baudrate))
        self.parity = QComboBox()
        for title, value in (("None (N)", "N"), ("Even (E)", "E"), ("Odd (O)", "O")):
            self.parity.addItem(title, value)
        self.parity.setCurrentIndex(self.parity.findData(d.parity))
        self.stopbits = spin(1, 2, d.stopbits)
        rtu_form.addWidget(field(self.t("serial_port"), self.serial_port), 0, 0)
        rtu_form.addWidget(field(self.t("baudrate"), self.baudrate), 0, 1)
        rtu_form.addWidget(field(self.t("parity"), self.parity), 1, 0)
        rtu_form.addWidget(field(self.t("stopbits"), self.stopbits), 1, 1)
        self.stack.addWidget(rtu)
        demo = label(self.t("demo_notice"), "muted")
        demo.setWordWrap(True)
        self.stack.addWidget(demo)
        self.stack.setCurrentIndex(self.transport.currentIndex())
        self.transport.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.form.addWidget(self.stack, 2, 0, 1, 2)
        self.timeout = spin(0.1, 10, d.timeout, 1)
        self.form.addWidget(field(self.t("timeout"), self.timeout), 3, 0)
        self.base = QCheckBox(self.t("base"))
        self.base.setChecked(d.address_base == 1)
        self.form.addWidget(self.base, 4, 0, 1, 2)
        hint = label(self.t("base_hint"), "muted")
        hint.setWordWrap(True)
        self.form.addWidget(hint, 5, 0, 1, 2)
        self.form.setRowStretch(6, 1)
        self.name.setFocus()

    def submit(self):
        d = deepcopy(self.result_device)
        d.name = self.name.text().strip()
        d.transport = self.transport.currentData()
        d.host = self.host.text().strip()
        d.port = self.port.value()
        d.unit_id = self.unit_id.value()
        d.serial_port = self.serial_port.currentText().strip()
        d.baudrate = self.baudrate.currentData()
        d.parity = self.parity.currentData()
        d.stopbits = self.stopbits.value()
        d.timeout = self.timeout.value()
        d.address_base = int(self.base.isChecked())
        candidate = deepcopy(self.config)
        candidate.devices = [existing for existing in candidate.devices if existing.id != d.id] + [d]
        try:
            candidate.validate()
        except (ValueError, TypeError) as exc:
            self.invalid(exc)
            return
        self.result_device = d
        self.accept()


class ParameterDialog(Editor):
    def __init__(self, config: Configuration, parameter=None, parent=None):
        self.config = config
        self.result_parameter = deepcopy(parameter) if parameter else Parameter(device_id=config.devices[0].id)
        super().__init__(tr("edit" if parameter else "add_parameter", config.language), config.language, parent)
        p = self.result_parameter
        self.name = QLineEdit(p.name)
        self.name.setMaxLength(100)
        self.name.setPlaceholderText("Temperature · Supply")
        self.device = QComboBox()
        for device in config.devices:
            self.device.addItem(device.name, device.id)
        self.device.setCurrentIndex(self.device.findData(p.device_id))
        self.function = QComboBox()
        for code, title in ((3, "03 · Holding registers"), (4, "04 · Input registers"), (1, "01 · Coils"), (2, "02 · Discrete inputs")):
            self.function.addItem(title, code)
        self.function.setCurrentIndex(self.function.findData(p.function))
        self.address = spin(0, 65536, p.address)
        self.data_type = QComboBox()
        for kind, (width, _) in TYPES.items():
            self.data_type.addItem(f"{kind}   ·   {width} {self.t('registers')}", kind)
        self.data_type.setCurrentIndex(self.data_type.findData(p.data_type))
        self.unit = QComboBox()
        self.unit.setEditable(True)
        self.unit.addItems(["", "°C", "°F", "V", "A", "W", "kW", "kWh", "Hz", "%", "bar", "Pa", "m³/h", "rpm", "s"])
        self.unit.setCurrentText(p.unit)
        self.unit.lineEdit().setMaxLength(30)
        self.interval = spin(0.1, 86400, p.interval, 2)
        self.decimal_shift = spin(-9, 9, p.decimal_shift)
        self.byte_order = QComboBox()
        for title, value in (("ABCD · Big endian", "ABCD"), ("BADC · Byte swap", "BADC"), ("CDAB · Word swap", "CDAB"), ("DCBA · Little endian", "DCBA")):
            self.byte_order.addItem(title, value)
        self.byte_order.setCurrentIndex(self.byte_order.findData(p.byte_order))
        self.bit = spin(0, 15, p.bit)
        self.enabled = QCheckBox(self.t("poll_enabled"))
        self.enabled.setChecked(p.enabled)
        self.hint = label("", "muted")
        self.hint.setWordWrap(True)
        self.form.addWidget(field(self.t("parameter_name"), self.name), 0, 0, 1, 2)
        self.form.addWidget(field(self.t("device"), self.device), 1, 0)
        self.form.addWidget(field(self.t("function"), self.function), 1, 1)
        self.form.addWidget(field(self.t("address"), self.address), 2, 0)
        self.form.addWidget(field(self.t("data_type"), self.data_type), 2, 1)
        self.form.addWidget(field(self.t("measurement_unit"), self.unit), 3, 0)
        self.form.addWidget(field(self.t("interval"), self.interval), 3, 1)
        self.form.addWidget(field(self.t("decimal_shift"), self.decimal_shift), 4, 0)
        self.form.addWidget(field(self.t("byte_order"), self.byte_order), 4, 1)
        self.form.addWidget(field(self.t("bit"), self.bit), 5, 0)
        self.form.addWidget(field("", self.enabled), 5, 1)
        scale_hint = label(self.t("scale_hint"), "muted")
        scale_hint.setWordWrap(True)
        self.form.addWidget(scale_hint, 6, 0, 1, 2)
        self.form.addWidget(self.hint, 7, 0, 1, 2)
        self.form.setRowStretch(8, 1)
        self.function.currentIndexChanged.connect(self.sync)
        self.device.currentIndexChanged.connect(self.sync)
        self.data_type.currentIndexChanged.connect(self.sync)
        self.address.valueChanged.connect(self.sync)
        self.decimal_shift.valueChanged.connect(self.sync)
        self.sync()
        self.name.setFocus()

    def sync(self, *_):
        bits = self.function.currentData() in (1, 2)
        if bits and self.data_type.currentData() != "bool":
            self.data_type.setCurrentIndex(self.data_type.findData("bool"))
        self.data_type.setEnabled(not bits)
        boolean = self.data_type.currentData() == "bool"
        self.bit.setEnabled(boolean and not bits)
        self.decimal_shift.setEnabled(not boolean)
        self.byte_order.setEnabled(not boolean)
        device = next(d for d in self.config.devices if d.id == self.device.currentData())
        self.address.setMinimum(device.address_base)
        width = 1 if bits else TYPES[self.data_type.currentData()][0]
        self.hint.setText(self.t("wire_hint", address=self.address.value()-device.address_base,
            width=width, scale=f"× 10^({-self.decimal_shift.value()})" if not boolean else "bool"))

    def submit(self):
        p = deepcopy(self.result_parameter)
        p.name = self.name.text().strip()
        p.device_id = self.device.currentData()
        p.function = self.function.currentData()
        p.address = self.address.value()
        p.data_type = self.data_type.currentData()
        p.unit = self.unit.currentText().strip()
        p.interval = self.interval.value()
        p.decimal_shift = self.decimal_shift.value()
        p.byte_order = self.byte_order.currentData()
        p.bit = self.bit.value()
        p.enabled = self.enabled.isChecked()
        try:
            p.validate({d.id: d for d in self.config.devices})
        except (ValueError, TypeError) as exc:
            self.invalid(exc)
            return
        self.result_parameter = p
        self.accept()


class CommandDialog(Editor):
    def __init__(self, config, device_id=None, parameter=None, parent=None):
        from PySide6.QtWidgets import QPlainTextEdit
        self.config, self.parameter = config, parameter
        self.result_command = None
        super().__init__(tr("write_value" if parameter else "send_command", config.language), config.language, parent)
        self.save_button.setText(self.t("send_command"))
        self.save_button.setDefault(False)
        self.device = QComboBox()
        for device in config.devices:
            self.device.addItem(device.name, device.id)
        self.device.setCurrentIndex(max(0, self.device.findData(parameter.device_id if parameter else device_id)))
        self.function = QComboBox()
        for code, name in ((5, "05 · Write single coil"), (6, "06 · Write single register"),
                           (15, "0F · Write multiple coils"), (16, "10 · Write multiple registers"),
                           (22, "16 · Mask write register")):
            self.function.addItem(name, code)
        self.address = spin(0, 65536, parameter.address if parameter else 0)
        self.values = QPlainTextEdit()
        self.values.setMaximumHeight(100)
        self.values.setPlaceholderText("123 456 / 0x007B 0x01C8")
        self.value = QLineEdit()
        self.value.setPlaceholderText("0")
        self.value.setMaxLength(100)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(100)
        self.validation = label("", "muted")
        self.validation.setWordWrap(True)
        self.form.addWidget(field(self.t("device"), self.device), 0, 0, 1, 2)
        self.form.addWidget(field(self.t("write_function"), self.function), 1, 0)
        self.form.addWidget(field(self.t("address"), self.address), 1, 1)
        if parameter:
            self.device.setEnabled(False)
            self.function.setEnabled(False)
            self.address.setEnabled(False)
            self.form.addWidget(label(parameter.name + " · " + parameter.data_type + " · " + parameter.unit, "sectionTitle"), 2, 0, 1, 2)
            self.form.addWidget(field(self.t("new_value"), self.value), 3, 0, 1, 2)
        else:
            self.form.addWidget(field(self.t("write_values"), self.values, self.t("write_values_hint")), 2, 0, 2, 2)
        self.form.addWidget(field(self.t("preview"), self.preview), 4, 0, 1, 2)
        self.form.addWidget(self.validation, 5, 0, 1, 2)
        hint = label(self.t("write_hint"), "muted")
        hint.setWordWrap(True)
        self.form.addWidget(hint, 6, 0, 1, 2)
        self.form.setRowStretch(7, 1)
        self.device.currentIndexChanged.connect(self.sync_command)
        self.function.currentIndexChanged.connect(self.sync_command)
        self.address.valueChanged.connect(self.sync_command)
        self.values.textChanged.connect(self.sync_command)
        self.value.textChanged.connect(self.sync_command)
        self.sync_command()
        (self.value if parameter else self.values).setFocus()

    def build_command(self):
        from .commands import Command, parameter_command, parse_values
        device = next(d for d in self.config.devices if d.id == self.device.currentData())
        if self.parameter:
            return parameter_command(self.parameter, device, self.value.text())
        return Command(device.id, self.function.currentData(), self.address.value()-device.address_base,
                       parse_values(self.values.toPlainText()))

    def sync_command(self, *_):
        device = next(d for d in self.config.devices if d.id == self.device.currentData())
        self.address.setMinimum(device.address_base)
        try:
            command = self.build_command()
            command.validate()
            self.preview.setPlainText(command.pdu().hex(" ").upper())
            self.validation.setText(self.t("wire_hint", address=command.address, width=command.count, scale=device.endpoint))
            if self.parameter:
                self.function.blockSignals(True)
                self.function.setCurrentIndex(self.function.findData(command.function))
                self.function.blockSignals(False)
            self.save_button.setEnabled(True)
        except (ValueError, OverflowError) as exc:
            self.preview.clear()
            self.validation.setText(str(exc))
            self.save_button.setEnabled(False)

    def submit(self):
        try:
            command = self.build_command()
            command.validate()
        except (ValueError, OverflowError) as exc:
            self.invalid(exc)
            return
        self.result_command = command
        self.accept()
