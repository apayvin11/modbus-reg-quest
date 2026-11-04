# SPDX-License-Identifier: Apache-2.0
"""Validated, explicit write commands. A command is never automatically retried."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import math
import struct

from .models import Device, Parameter, TYPES, integer, new_id

WRITE_FUNCTIONS = (5, 6, 15, 16, 22)


@dataclass(frozen=True)
class Command:
    device_id: str
    function: int
    address: int  # Zero-based address on the wire.
    values: tuple[int, ...]
    id: str = field(default_factory=new_id)

    @property
    def count(self):
        return 1 if self.function in (5, 6, 22) else len(self.values)

    def validate(self):
        if self.function not in WRITE_FUNCTIONS:
            raise ValueError("Unsupported write function")
        integer(self.address, "address", 0, 65535)
        if not isinstance(self.values, tuple):
            raise ValueError("values must be a tuple")
        limit = 1968 if self.function == 15 else 123
        if not self.values or len(self.values) > limit:
            raise ValueError(f"Value count must be 1 … {limit}")
        expected = 2 if self.function == 22 else 1
        if self.function in (5, 6, 22) and len(self.values) != expected:
            raise ValueError(f"This function requires {expected} value(s)")
        for value in self.values:
            integer(value, "value", 0, 1 if self.function in (5, 15) else 65535)
        if self.address + self.count > 65536:
            raise ValueError("Address exceeds Modbus range")

    def pdu(self):
        self.validate()
        if self.function in (5, 6):
            value = self.values[0] * 0xFF00 if self.function == 5 else self.values[0]
            return struct.pack(">BHH", self.function, self.address, value)
        if self.function == 22:
            return struct.pack(">BHHH", self.function, self.address, *self.values)
        if self.function == 15:
            data = bytearray((self.count + 7)//8)
            for index, value in enumerate(self.values):
                data[index//8] |= value << (index % 8)
        else:
            data = struct.pack(">" + "H" * self.count, *self.values)
        return struct.pack(">BHHB", self.function, self.address, self.count, len(data)) + data


def encode_value(parameter: Parameter, value: str):
    """Inverse of decode_value, preserving integer precision before byte packing."""
    if parameter.data_type == "bool":
        if value.strip().lower() not in ("0", "1", "true", "false", "on", "off"):
            raise ValueError("Boolean value: 0 / 1")
        return [int(value.strip().lower() in ("1", "true", "on"))]
    try:
        raw = Decimal(value.strip().replace(",", ".")) * Decimal(10) ** parameter.decimal_shift
    except InvalidOperation as exc:
        raise ValueError("Invalid numeric value") from exc
    if not raw.is_finite():
        raise ValueError("Value must be finite")
    fmt = TYPES[parameter.data_type][1]
    if parameter.data_type.startswith(("uint", "int")):
        if raw != raw.to_integral_value():
            raise ValueError("Value cannot be represented with the configured decimal scale")
        raw = int(raw)
    else:
        raw = float(raw)
        if not math.isfinite(raw):
            raise ValueError("Value is out of range")
    try:
        data = struct.pack(">" + fmt, raw)
    except (struct.error, OverflowError) as exc:
        raise ValueError("Value is out of range for " + parameter.data_type) from exc
    # Both permutations are their own inverses and commute.
    if parameter.byte_order in ("CDAB", "DCBA"):
        data = b"".join(data[i:i+2] for i in range(len(data)-2, -1, -2))
    if parameter.byte_order in ("BADC", "DCBA"):
        data = b"".join(data[i:i+2][::-1] for i in range(0, len(data), 2))
    return list(struct.unpack(">" + "H"*(len(data)//2), data))


def parameter_command(parameter: Parameter, device: Device, value: str):
    if parameter.function not in (1, 3):
        raise ValueError("Input registers and discrete inputs are read-only")
    values = tuple(encode_value(parameter, value))
    address = parameter.wire_address(device)
    if parameter.function == 1:
        return Command(device.id, 5, address, values)
    if parameter.data_type == "bool":
        bit_mask = 1 << parameter.bit
        return Command(device.id, 22, address, (0xFFFF ^ bit_mask, bit_mask if values[0] else 0))
    return Command(device.id, 6 if len(values) == 1 else 16, address, values)


def parse_values(text):
    tokens = text.replace(",", " ").replace(";", " ").split()
    return tuple(int(token, 16) if token.lower().startswith("0x") else int(token, 10) for token in tokens)
