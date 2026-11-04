# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from copy import deepcopy
import queue
import threading
import time

from PySide6.QtCore import QThread, Signal

from .commands import Command
from .models import Configuration, new_id
from .protocol import decode_value, make_client, plan_requests


class Poller(QThread):
    """Single owner of all transports; writes and reads are serialized on each bus."""
    readings = Signal(int, object)
    activity = Signal(object)
    statistics = Signal(int, object)
    command_finished = Signal(object)

    def __init__(self, config: Configuration, parent=None, *, polling=True):
        super().__init__(parent)
        self._config = deepcopy(config)
        self._revision = 0
        self._polling = polling
        self._session = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._clients = {}
        self._commands = queue.Queue(maxsize=16)

    @property
    def revision(self):
        with self._lock:
            return self._revision

    @property
    def polling(self):
        with self._lock:
            return self._polling

    def set_polling(self, enabled):
        with self._lock:
            if enabled and not self._polling:
                self._session += 1
            self._polling = enabled
        self._wake.set()

    def configure(self, config):
        config.validate()
        with self._lock:
            self._config = deepcopy(config)
            self._revision += 1
        self._wake.set()

    def enqueue(self, command: Command):
        command.validate()
        with self._lock:
            if self._stop.is_set():
                raise ValueError("Worker is stopping")
            device = next((d for d in self._config.devices if d.id == command.device_id), None)
            if not device:
                raise ValueError("Unknown device")
            self._commands.put_nowait((command, self._revision, deepcopy(device)))
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
        with self._lock:
            clients = list(self._clients.values())
        for client in clients:
            client.close()

    def _client(self, device):
        key = ("rtu", device.serial_port) if device.transport == "rtu" else device.id
        with self._lock:
            if self._stop.is_set():
                raise ValueError("Worker is stopping")
            if key not in self._clients:
                self._clients[key] = make_client(device)
            return self._clients[key]

    @staticmethod
    def _kwargs(device):
        return {"unit_id": device.unit_id, "timeout": device.timeout} if device.transport == "rtu" else {}

    def _cancel_command(self, command, device, reason):
        event = {"id": new_id(), "command_id": command.id, "time": time.time(), "device": device.name,
            "device_id": device.id, "endpoint": device.endpoint, "transport": device.transport,
            "unit_id": device.unit_id, "operation": "write", "function": command.function,
            "address": command.address, "count": command.count, "parameters": 0, "ms": 0,
            "request": b"", "response": b"", "request_pdu": command.pdu(), "sent": 0, "error": reason}
        self.activity.emit(event)
        self.command_finished.emit(event)

    def _execute_command(self, item):
        command, revision, device = item
        if revision != self.revision or self._stop.is_set():
            self._cancel_command(command, device, "Configuration changed or command cancelled before sending")
            return None
        try:
            client = self._client(device)
        except ValueError as exc:
            self._cancel_command(command, device, str(exc))
            return None
        error = ""
        try:
            client.write(command, **self._kwargs(device))
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        event = dict(client.trace)
        event.update(command_id=command.id, error=error)
        self.activity.emit(event)
        self.command_finished.emit(event)
        return event

    def run(self):
        revision = session = -1
        due = {}
        stats = {"requests": 0, "errors": 0, "saved": 0, "latency": 0}
        try:
            while not self._stop.is_set():
                with self._lock:
                    current, current_session, polling = self._revision, self._session, self._polling
                    config = deepcopy(self._config) if current != revision else None
                if config is not None:
                    with self._lock:
                        old_clients, self._clients = self._clients, {}
                    for client in old_clients.values():
                        client.close()
                    revision = current
                    devices = {d.id: d for d in config.devices}
                    parameters = [p for p in config.parameters if p.enabled]
                    due = {p.id: 0.0 for p in parameters}
                if current_session != session:
                    session = current_session
                    stats = {"requests": 0, "errors": 0, "saved": 0, "latency": 0}
                    due = {p.id: 0.0 for p in parameters}
                try:
                    item = self._commands.get_nowait()
                except queue.Empty:
                    item = None
                if item:
                    if self.revision != revision:
                        self._commands.put_nowait(item)
                        continue
                    event = self._execute_command(item)
                    if event:
                        stats["requests"] += 1
                        stats["errors"] += bool(event["error"])
                        self.statistics.emit(revision, dict(stats))
                        if not event["error"]:
                            due = {p.id: 0.0 for p in parameters}
                    continue
                now = time.monotonic()
                ready = [p for p in parameters if polling and due[p.id] <= now+0.005]
                blocks = plan_requests(ready, devices)
                cycle_start = time.monotonic()
                for block in blocks:
                    if self._stop.is_set() or self.revision != revision or not self.polling or not self._commands.empty():
                        break
                    device = devices[block.device_id]
                    client = self._client(device)
                    start, timestamp = time.monotonic(), time.time()
                    values, error = [], ""
                    stats["requests"] += 1
                    stats["saved"] += len(block.parameters)-1
                    try:
                        registers = client.read(block.function, block.address, block.count, **self._kwargs(device))
                        for parameter in block.parameters:
                            offset = parameter.wire_address(device)-block.address
                            try:
                                value = decode_value(parameter, registers[offset:offset+parameter.width])
                                values.append({"id": parameter.id, "value": value, "error": "", "time": timestamp})
                            except Exception as exc:
                                values.append({"id": parameter.id, "value": None, "error": str(exc), "time": timestamp})
                    except Exception as exc:
                        error = str(exc) or type(exc).__name__
                        stats["errors"] += 1
                        values = [{"id": p.id, "value": None, "error": error, "time": timestamp} for p in block.parameters]
                    # Keep the wire log even when configuration changes during the request.
                    event = dict(client.trace)
                    event.update(error=error, parameters=len(block.parameters), decoded_values=[
                        {**value, "name": parameter.name, "type": parameter.data_type, "unit": parameter.unit}
                        for value, parameter in zip(values, block.parameters)])
                    self.activity.emit(event)
                    if not self._stop.is_set():
                        self.readings.emit(revision, values)
                    for p in block.parameters:
                        due[p.id] = max(start+p.interval, time.monotonic()+0.02)
                if blocks and not self._stop.is_set():
                    stats["latency"] = round((time.monotonic()-cycle_start)*1000, 1)
                    self.statistics.emit(revision, dict(stats))
                wait = max(0.02, min(0.25, min(due.values(), default=time.monotonic()+0.25)-time.monotonic())) if polling else 0.25
                self._wake.wait(wait)
                self._wake.clear()
        finally:
            while not self._commands.empty():
                command, _, device = self._commands.get_nowait()
                self._cancel_command(command, device, "Command cancelled before sending")
            with self._lock:
                clients, self._clients = self._clients, {}
            for client in clients.values():
                client.close()
