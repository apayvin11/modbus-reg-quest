# SPDX-License-Identifier: Apache-2.0
"""A small in-memory Modbus slave used by the demo and the TCP test server."""
import math
import struct
import threading
import time


class MemoryDevice:
    def __init__(self, dynamic=False):
        self.dynamic = dynamic
        self.registers = {}
        self.coils = {}
        self.lock = threading.RLock()

    def register(self, address, inputs=False):
        wave = math.sin(time.monotonic()/4) if self.dynamic else 0
        defaults = [round(2304+wave*12), round(842+wave*30), 0, round(1938+wave*80),
                    round(5000+wave*3), round(973+wave*7), 0, 48216, round(324+wave*9)]
        default = defaults[address] if address < len(defaults) else address % 65536
        return default if inputs else self.registers.get(address, default)

    def exchange(self, pdu):
        with self.lock:
            return self._exchange(pdu)

    def _exchange(self, pdu):
        if not pdu:
            return b""
        function = pdu[0]
        def error(code):
            return bytes([function | 0x80, code])
        if function not in (1, 2, 3, 4, 5, 6, 15, 16, 22):
            return error(1)
        if len(pdu) < 5:
            return error(3)
        address, field = struct.unpack(">HH", pdu[1:5])
        if function in (1, 2, 3, 4):
            if len(pdu) != 5 or not 1 <= field <= (2000 if function in (1, 2) else 125) or address+field > 65536:
                return error(3)
            if function in (1, 2):
                data = bytearray((field+7)//8)
                for i in range(field):
                    value = (address+i) % 2 if function == 2 else self.coils.get(address+i, (address+i) % 2)
                    data[i//8] |= value << (i % 8)
            else:
                data = struct.pack(">"+"H"*field, *(self.register(address+i, function == 4) for i in range(field)))
            return bytes([function, len(data)]) + data
        if function in (5, 6):
            if len(pdu) != 5 or function == 5 and field not in (0, 0xFF00):
                return error(3)
            if function == 5:
                self.coils[address] = int(field == 0xFF00)
            else:
                self.registers[address] = field
            return pdu
        if function == 22:
            if len(pdu) != 7:
                return error(3)
            or_mask = int.from_bytes(pdu[5:7], "big")
            self.registers[address] = (self.register(address) & field) | (or_mask & (0xFFFF ^ field))
            return pdu
        if len(pdu) < 6 or not 1 <= field <= (1968 if function == 15 else 123) or address+field > 65536:
            return error(3)
        expected = (field+7)//8 if function == 15 else field*2
        if pdu[5] != expected or len(pdu) != expected+6:
            return error(3)
        for i in range(field):
            if function == 15:
                self.coils[address+i] = (pdu[6+i//8] >> (i % 8)) & 1
            else:
                self.registers[address+i] = int.from_bytes(pdu[6+i*2:8+i*2], "big")
        return pdu[:5]
