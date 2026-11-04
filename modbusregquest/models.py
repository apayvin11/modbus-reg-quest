# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import math
import uuid


TYPES = {"uint16": (1, "H"), "int16": (1, "h"), "uint32": (2, "I"),
         "int32": (2, "i"), "float32": (2, "f"), "uint64": (4, "Q"),
         "int64": (4, "q"), "float64": (4, "d"), "bool": (1, "?")}
FUNCTIONS = (1, 2, 3, 4)
MAX_CONFIG_BYTES = 5 * 1024 * 1024


def new_id() -> str:
    return uuid.uuid4().hex


def integer(value, name: str, low: int, high: int):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name}: {low} … {high}")


def number(value, name: str, low: float, high: float):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: {low} … {high}")


def string(value, name: str, max_length=200, allow_empty=False):
    if not isinstance(value, str) or len(value) > max_length or (not allow_empty and not value.strip()):
        raise ValueError(f"{name}: invalid text")


@dataclass
class Device:
    id: str = field(default_factory=new_id)
    name: str = "Device 01"
    transport: str = "tcp"
    host: str = "127.0.0.1"
    port: int = 502
    unit_id: int = 1
    serial_port: str = "/dev/ttyUSB0"
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1
    timeout: float = 1.0
    address_base: int = 0

    def validate(self):
        string(self.id, "device.id", 64)
        string(self.name, "device.name", 100)
        if self.transport not in ("tcp", "rtu", "demo"):
            raise ValueError("device.transport")
        string(self.host, "device.host", 253)
        string(self.serial_port, "device.serial_port", 512)
        integer(self.port, "device.port", 1, 65535)
        integer(self.unit_id, "device.unit_id", 1 if self.transport == "rtu" else 0,
                247 if self.transport == "rtu" else 255)
        integer(self.baudrate, "device.baudrate", 300, 4000000)
        if self.parity not in ("N", "E", "O"):
            raise ValueError("device.parity")
        integer(self.stopbits, "device.stopbits", 1, 2)
        number(self.timeout, "device.timeout", 0.1, 10)
        integer(self.address_base, "device.address_base", 0, 1)

    @property
    def endpoint(self):
        if self.transport == "tcp":
            return f"{self.host}:{self.port} · ID {self.unit_id}"
        if self.transport == "rtu":
            return f"{self.serial_port} · {self.baudrate} · ID {self.unit_id}"
        return "SIMULATOR · ID 1"


@dataclass
class Parameter:
    id: str = field(default_factory=new_id)
    device_id: str = ""
    name: str = ""
    address: int = 0
    function: int = 3
    data_type: str = "uint16"
    unit: str = ""
    decimal_shift: int = 0
    byte_order: str = "ABCD"
    interval: float = 1.0
    enabled: bool = True
    bit: int = 0

    @property
    def width(self):
        return 1 if self.function in (1, 2) else TYPES[self.data_type][0]

    def wire_address(self, device: Device):
        return self.address - device.address_base

    def validate(self, devices: dict[str, Device]):
        string(self.id, "parameter.id", 64)
        string(self.device_id, "parameter.device_id", 64)
        string(self.name, "parameter.name", 100)
        string(self.unit, "parameter.unit", 30, allow_empty=True)
        integer(self.function, "parameter.function", 1, 4)
        if self.data_type not in TYPES:
            raise ValueError("parameter.data_type")
        if self.byte_order not in ("ABCD", "BADC", "CDAB", "DCBA"):
            raise ValueError("parameter.byte_order")
        if self.function in (1, 2) and self.data_type != "bool":
            raise ValueError("Coils and discrete inputs require bool")
        integer(self.address, "parameter.address", 0, 65536)
        integer(self.decimal_shift, "parameter.decimal_shift", -9, 9)
        integer(self.bit, "parameter.bit", 0, 15)
        number(self.interval, "parameter.interval", 0.1, 86400)
        if type(self.enabled) is not bool:
            raise ValueError("parameter.enabled")
        device = devices.get(self.device_id)
        if not device:
            raise ValueError("Unknown device")
        address = self.wire_address(device)
        if address < 0 or address + self.width > 65536:
            raise ValueError("Address exceeds Modbus range (0 … 65535)")


@dataclass
class Configuration:
    language: str = "ru"
    devices: list[Device] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    theme: str = "light"

    def validate(self):
        if self.theme not in ("light", "dark"):
            raise ValueError("theme")
        if self.language not in ("ru", "en"):
            raise ValueError("language")
        if len(self.devices) > 256 or len(self.parameters) > 10000:
            raise ValueError("Configuration is too large")
        ids = set()
        for device in self.devices:
            device.validate()
            if device.id in ids:
                raise ValueError("Duplicate device ID")
            ids.add(device.id)
        devices = {d.id: d for d in self.devices}
        buses = {}
        for device in self.devices:
            if device.transport == "rtu":
                settings = (device.baudrate, device.parity, device.stopbits)
                if device.serial_port in buses and buses[device.serial_port] != settings:
                    raise ValueError("RTU devices sharing a port must use the same baud rate, parity and stop bits")
                buses[device.serial_port] = settings
        ids = set()
        for parameter in self.parameters:
            parameter.validate(devices)
            if parameter.id in ids:
                raise ValueError("Duplicate parameter ID")
            ids.add(parameter.id)

    def to_dict(self):
        return {"format": "modbusregquest", "version": 1, **asdict(self)}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get("format") not in ("modbusregquest", "modbuspoll") or type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("Unsupported configuration format/version")
        if not isinstance(data.get("devices"), list) or not isinstance(data.get("parameters"), list):
            raise ValueError("devices/parameters must be arrays")
        def parse(model, values):
            allowed = {f.name for f in fields(model)}
            if not isinstance(values, dict) or set(values) - allowed:
                raise ValueError(f"Invalid {model.__name__} fields")
            return model(**values)
        config = cls(data.get("language", "ru"), [parse(Device, d) for d in data["devices"]],
                     [parse(Parameter, p) for p in data["parameters"]], data.get("theme", "light"))
        config.validate()
        return config


def demo_configuration(language="ru"):
    device = Device(name="Demo · Energy meter", transport="demo")
    samples = [("Напряжение", "Voltage", 0, "uint16", "V", 1),
               ("Ток", "Current", 1, "uint16", "A", 2),
               ("Активная мощность", "Active power", 2, "uint32", "kW", 3),
               ("Частота", "Frequency", 4, "uint16", "Hz", 2),
               ("Коэффициент мощности", "Power factor", 5, "uint16", "", 3),
               ("Энергия", "Energy", 6, "uint32", "kWh", 1),
               ("Температура", "Temperature", 8, "int16", "°C", 1)]
    return Configuration(language, [device], [Parameter(device_id=device.id,
        name=ru if language == "ru" else en, address=address, data_type=kind, unit=unit,
        decimal_shift=shift) for ru, en, address, kind, unit, shift in samples])
