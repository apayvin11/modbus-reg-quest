#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Local TCP read/write simulator. Standard library only."""
import argparse
from pathlib import Path
import socketserver
import struct
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modbusregquest.simulation import MemoryDevice


class Handler(socketserver.BaseRequestHandler):
    def receive(self, count):
        data = b""
        while len(data) < count:
            chunk = self.request.recv(count-len(data))
            if not chunk:
                return None
            data += chunk
        return data

    def handle(self):
        while True:
            header = self.receive(7)
            if not header:
                return
            transaction, protocol, length, unit = struct.unpack(">HHHB", header)
            if protocol or not 2 <= length <= 254:
                return
            pdu = self.receive(length-1)
            if not pdu:
                return
            response = self.server.device(unit).exchange(pdu)
            self.request.sendall(struct.pack(">HHHB", transaction, 0, len(response)+1, unit)+response)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.memories = {}
        self.memory_lock = threading.Lock()
        super().__init__(*args, **kwargs)

    def device(self, unit):
        with self.memory_lock:
            return self.memories.setdefault(unit, MemoryDevice())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1502)
    args = parser.parse_args()
    with Server((args.host, args.port), Handler) as server:
        print(f"Modbus TCP read/write simulator: {args.host}:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
