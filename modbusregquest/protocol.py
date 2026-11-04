# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
import math
import socket
import struct
import threading
import time

from .models import Device, Parameter, TYPES


class ModbusError(Exception):
    pass


class ProtocolException(ModbusError):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Modbus exception 0x{code:02X}")


@dataclass
class ReadBlock:
    device_id: str
    function: int
    address: int
    count: int
    parameters: list[Parameter]


def plan_requests(parameters: list[Parameter], devices: dict[str, Device]):
    """Merge adjacent/overlapping addresses only. Never read undocumented gaps."""
    ordered = sorted((p for p in parameters if p.enabled),
                     key=lambda p: (p.device_id, p.function, p.wire_address(devices[p.device_id])))
    blocks: list[ReadBlock] = []
    for parameter in ordered:
        address = parameter.wire_address(devices[parameter.device_id])
        end = address + parameter.width
        limit = 2000 if parameter.function in (1, 2) else 125
        last = blocks[-1] if blocks else None
        if (last and (last.device_id, last.function) == (parameter.device_id, parameter.function)
                and address <= last.address + last.count and max(last.address + last.count, end) - last.address <= limit):
            last.count = max(last.count, end - last.address)
            last.parameters.append(parameter)
        else:
            blocks.append(ReadBlock(parameter.device_id, parameter.function, address, parameter.width, [parameter]))
    return blocks


def decode_value(parameter: Parameter, registers: list[int]):
    if parameter.function in (1, 2):
        return bool(registers[0])
    if parameter.data_type == "bool":
        return bool(registers[0] & (1 << parameter.bit))
    data = b"".join(struct.pack(">H", register) for register in registers[:parameter.width])
    if parameter.byte_order in ("BADC", "DCBA"):
        data = b"".join(data[i:i+2][::-1] for i in range(0, len(data), 2))
    if parameter.byte_order in ("CDAB", "DCBA"):
        data = b"".join(data[i:i+2] for i in range(len(data)-2, -1, -2))
    raw = struct.unpack(">" + TYPES[parameter.data_type][1], data)[0]
    if isinstance(raw, float) and not math.isfinite(raw):
        raise ModbusError("Non-finite value (NaN / Infinity)")
    return raw if parameter.decimal_shift == 0 else raw * 10.0 ** -parameter.decimal_shift


def decode_response(function: int, count: int, pdu: bytes):
    if len(pdu) == 2 and pdu[0] == function | 0x80:
        raise ProtocolException(pdu[1])
    size = (count + 7) // 8 if function in (1, 2) else count * 2
    if len(pdu) != size + 2 or pdu[0] != function or pdu[1] != size:
        raise ModbusError("Invalid function, byte count or response length")
    if function in (1, 2):
        return [(pdu[2 + i // 8] >> (i % 8)) & 1 for i in range(count)]
    return list(struct.unpack(">" + "H" * count, pdu[2:]))


class TracedClient:
    def __init__(self, device):
        self.device = device
        self.trace = {}

    def _begin(self, pdu, transport, unit_id=None):
        from .models import new_id
        self.trace = {"id": new_id(), "time": time.time(), "device": self.device.name,
            "device_id": self.device.id, "endpoint": self.device.endpoint, "transport": transport,
            "unit_id": self.device.unit_id if unit_id is None else unit_id,
            "function": pdu[0], "operation": "read" if pdu[0] in (1, 2, 3, 4) else "write",
            "address": int.from_bytes(pdu[1:3], "big"),
            "count": int.from_bytes(pdu[3:5], "big") if pdu[0] in (1, 2, 3, 4, 15, 16) else 1,
            "request": b"", "response": b"", "request_pdu": pdu,
            "sent": 0, "error": "", "ms": 0.0, "parameters": 0}
        self._started = time.monotonic()

    def read(self, function, address, count, **kwargs):
        try:
            pdu = self.exchange(struct.pack(">BHH", function, address, count), **kwargs)
            return decode_response(function, count, pdu)
        except Exception as exc:
            self.trace["error"] = str(exc) or type(exc).__name__
            raise

    def write(self, command, **kwargs):
        request = command.pdu()
        try:
            response = self.exchange(request, **kwargs)
            if len(response) == 2 and response[0] == command.function | 0x80:
                raise ProtocolException(response[1])
            expected = request[:5] if command.function in (15, 16) else request
            if response != expected:
                raise ModbusError("Write acknowledgement does not match the request")
            return True
        except Exception as exc:
            self.trace["error"] = str(exc) or type(exc).__name__
            raise


class TcpClient(TracedClient):
    def __init__(self, device: Device):
        super().__init__(device)
        self.socket = None
        self.transaction = 0
        self.cancelled = threading.Event()

    def close(self):
        self.cancelled.set()
        self._disconnect()

    def _disconnect(self):
        sock, self.socket = self.socket, None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _receive(self, sock, size, deadline):
        data = bytearray()
        while len(data) < size:
            if self.cancelled.is_set():
                raise ModbusError("Cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Response timeout")
            sock.settimeout(remaining)
            chunk = sock.recv(size-len(data))
            if not chunk:
                raise ModbusError("Connection closed")
            data.extend(chunk)
            self.trace["response"] += chunk
        return bytes(data)

    def exchange(self, pdu):
        self._begin(pdu, "tcp")
        self.transaction = (self.transaction+1) & 0xFFFF
        request = struct.pack(">HHHB", self.transaction, 0, len(pdu)+1, self.device.unit_id) + pdu
        self.trace["request"] = request
        try:
            if self.cancelled.is_set():
                raise ModbusError("Cancelled")
            deadline = time.monotonic() + self.device.timeout
            if not self.socket:
                self.socket = socket.create_connection((self.device.host, self.device.port), self.device.timeout)
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock = self.socket
            while self.trace["sent"] < len(request):
                if self.cancelled.is_set():
                    raise ModbusError("Cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Request timeout")
                sock.settimeout(remaining)
                written = sock.send(request[self.trace["sent"]:])
                if not written:
                    raise ModbusError("Connection closed")
                self.trace["sent"] += written
            header = self._receive(sock, 7, deadline)
            transaction, protocol, length, unit = struct.unpack(">HHHB", header)
            if transaction != self.transaction or protocol != 0 or unit != self.device.unit_id or not 2 <= length <= 254:
                raise ModbusError("Invalid MBAP header")
            return self._receive(sock, length-1, deadline)
        except Exception as exc:
            self.trace["error"] = str(exc) or type(exc).__name__
            self._disconnect()
            raise
        finally:
            self.trace["ms"] = round((time.monotonic()-self._started)*1000, 1)


def crc16(data: bytes):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


class RtuClient(TracedClient):
    def __init__(self, device: Device):
        super().__init__(device)
        self.serial = None
        self.cancelled = threading.Event()

    def close(self):
        self.cancelled.set()
        port = self.serial
        if port:
            try:
                port.cancel_read()
                port.cancel_write()
            except (AttributeError, OSError):
                pass
            try:
                port.close()
            except OSError:
                pass

    def _receive(self, port, count, deadline):
        data = bytearray()
        while len(data) < count:
            if self.cancelled.is_set():
                raise ModbusError("Cancelled")
            port.timeout = max(0, deadline-time.monotonic())
            if port.timeout <= 0:
                raise TimeoutError("RTU response timeout")
            chunk = port.read(count-len(data))
            if not chunk:
                raise TimeoutError("RTU response timeout")
            data.extend(chunk)
            self.trace["response"] += chunk
        return bytes(data)

    def exchange(self, pdu, *, unit_id=None, timeout=None):
        import serial
        unit_id = self.device.unit_id if unit_id is None else unit_id
        timeout = self.device.timeout if timeout is None else timeout
        self._begin(pdu, "rtu", unit_id)
        request = bytes([unit_id]) + pdu
        request += struct.pack("<H", crc16(request))
        self.trace["request"] = request
        try:
            if self.cancelled.is_set():
                raise ModbusError("Cancelled")
            if not self.serial or not self.serial.is_open:
                self.serial = serial.Serial(self.device.serial_port, baudrate=self.device.baudrate,
                    bytesize=8, parity=self.device.parity, stopbits=self.device.stopbits,
                    timeout=timeout, write_timeout=timeout, exclusive=True)
            port = self.serial
            if self.cancelled.is_set():
                raise ModbusError("Cancelled")
            time.sleep(max(0.00175, 3.5*11/self.device.baudrate))
            port.reset_input_buffer()
            port.write_timeout = timeout
            deadline = time.monotonic()+timeout
            self.trace["sent"] = port.write(request)
            if self.trace["sent"] != len(request):
                raise TimeoutError("RTU request was only partially written")
            header = self._receive(port, 2, deadline)
            if header[1] & 0x80:
                size = 5
            elif header[1] in (1, 2, 3, 4):
                header += self._receive(port, 1, deadline)
                size = 5+header[2]
            else:
                size = 10 if header[1] == 22 else 8
            if size > 256:
                raise ModbusError("Invalid RTU length")
            response = header+self._receive(port, size-len(header), deadline)
            if response[0] != unit_id or crc16(response[:-2]) != int.from_bytes(response[-2:], "little"):
                raise ModbusError("Invalid RTU unit or CRC")
            return response[1:-2]
        except Exception as exc:
            self.trace["error"] = str(exc) or type(exc).__name__
            raise
        finally:
            self.trace["ms"] = round((time.monotonic()-self._started)*1000, 1)


class DemoClient(TracedClient):
    def __init__(self, device):
        super().__init__(device)
        from .simulation import MemoryDevice
        self.memory = MemoryDevice(dynamic=True)
        self.transaction = 0

    def close(self):
        pass

    def exchange(self, pdu):
        self._begin(pdu, "demo")
        self.transaction = (self.transaction+1) & 0xFFFF
        self.trace["request"] = struct.pack(">HHHB", self.transaction, 0, len(pdu)+1, self.device.unit_id)+pdu
        self.trace["sent"] = len(self.trace["request"])
        response = self.memory.exchange(pdu)
        self.trace["response"] = struct.pack(">HHHB", self.transaction, 0, len(response)+1, self.device.unit_id)+response
        self.trace["ms"] = round((time.monotonic()-self._started)*1000, 1)
        return response


def make_client(device):
    return {"tcp": TcpClient, "rtu": RtuClient, "demo": DemoClient}[device.transport](device)
