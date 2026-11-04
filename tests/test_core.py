# SPDX-License-Identifier: Apache-2.0
import dataclasses
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import unittest

from modbusregquest.models import Configuration, Device, Parameter, demo_configuration
from modbusregquest.protocol import (ModbusError, ProtocolException, RtuClient, TcpClient,
    crc16, decode_response, decode_value, plan_requests)
from modbusregquest.storage import Store, export_configuration, read_configuration
from scripts.modbus_simulator import Server, Handler


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.device = Device()
        self.devices = {self.device.id: self.device}

    def parameter(self, address, **kwargs):
        return Parameter(device_id=self.device.id, name="P", address=address, **kwargs)

    def test_adjacent_overlap_and_gap(self):
        parameters = [self.parameter(4), self.parameter(0, data_type="uint32"),
                      self.parameter(1), self.parameter(2)]
        blocks = plan_requests(parameters, self.devices)
        self.assertEqual([(b.address, b.count, len(b.parameters)) for b in blocks], [(0, 3, 3), (4, 1, 1)])

    def test_limits_never_split_multiregister_parameter(self):
        parameters = [self.parameter(i, data_type="float32") for i in range(0, 252, 2)]
        blocks = plan_requests(parameters, self.devices)
        self.assertEqual([b.count for b in blocks], [124, 124, 4])
        self.assertEqual(sum(len(b.parameters) for b in blocks), 126)

    def test_separate_devices_and_functions_and_skip_disabled(self):
        other = Device()
        self.devices[other.id] = other
        blocks = plan_requests([self.parameter(0), self.parameter(1, function=4),
            self.parameter(2, enabled=False), Parameter(device_id=other.id, name="X", address=0)], self.devices)
        self.assertEqual(len(blocks), 3)

    def test_one_based_and_bits(self):
        self.device.address_base = 1
        blocks = plan_requests([self.parameter(1), self.parameter(2)], self.devices)
        self.assertEqual((blocks[0].address, blocks[0].count), (0, 2))
        parameters = [self.parameter(i+1, function=1, data_type="bool") for i in range(2001)]
        self.assertEqual([b.count for b in plan_requests(parameters, self.devices)], [2000, 1])


class DecodingTests(unittest.TestCase):
    def decode(self, kind, data, order="ABCD", shift=0):
        registers = list(struct.unpack(">"+"H"*(len(data)//2), data))
        return decode_value(Parameter(data_type=kind, byte_order=order, decimal_shift=shift), registers)

    def test_signed_and_scaling(self):
        self.assertEqual(self.decode("int16", b"\xff\x9c", shift=1), -10)
        self.assertAlmostEqual(self.decode("uint16", struct.pack(">H", 2345), shift=2), 23.45)
        self.assertEqual(self.decode("uint16", b"\x00\x0c", shift=-2), 1200)
        self.assertEqual(self.decode("uint64", b"\xff"*8), 2**64-1)

    def test_all_orders_float32_and_float64(self):
        for kind, fmt, value in (("float32", "f", 123.25), ("float64", "d", -987.125)):
            raw = struct.pack(">"+fmt, value)
            for order in ("ABCD", "BADC", "CDAB", "DCBA"):
                encoded = raw
                if order in ("CDAB", "DCBA"):
                    encoded = b"".join(encoded[i:i+2] for i in range(len(encoded)-2, -1, -2))
                if order in ("BADC", "DCBA"):
                    encoded = b"".join(encoded[i:i+2][::-1] for i in range(0, len(encoded), 2))
                self.assertEqual(self.decode(kind, encoded, order), value)

    def test_bits_nan_and_protocol_errors(self):
        self.assertTrue(decode_value(Parameter(data_type="bool", bit=8), [256]))
        self.assertEqual(decode_response(1, 9, b"\x01\x02\x85\x01"), [1,0,1,0,0,0,0,1,1])
        with self.assertRaises(ModbusError):
            self.decode("float32", struct.pack(">f", float("nan")))
        with self.assertRaises(ProtocolException) as context:
            decode_response(3, 1, b"\x83\x02")
        self.assertEqual(context.exception.code, 2)
        for malformed in (b"", b"\x04\x02\x00\x01", b"\x03\x01\x00"):
            with self.assertRaises(ModbusError):
                decode_response(3, 1, malformed)

    def test_crc_known_modbus_vector(self):
        self.assertEqual(crc16(bytes.fromhex("01030000000a")), 0xCDC5)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.store = Store(self.path/"config.db")
        self.config = demo_configuration()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_sqlite_restart_and_json_roundtrip(self):
        self.store.save(self.config)
        self.store.close()
        self.store = Store(self.path/"config.db")
        self.assertEqual(self.store.load(), self.config)
        export_configuration(self.config, self.path/"config.json")
        self.assertEqual(read_configuration(self.path/"config.json"), self.config)

    def test_invalid_save_preserves_database(self):
        self.store.save(self.config)
        invalid = demo_configuration()
        invalid.parameters[0].device_id = "missing"
        with self.assertRaises(ValueError):
            self.store.save(invalid)
        self.assertEqual(self.store.load(), self.config)

    def test_invalid_imports_and_ranges(self):
        for mutate in (lambda d: d.update(version=2), lambda d: d["parameters"][0].update(interval=0),
            lambda d: d["parameters"][0].update(enabled="false"), lambda d: d["devices"][0].update(port=True),
            lambda d: d["parameters"][0].update(address=65535, data_type="uint32"),
            lambda d: d["parameters"].append(d["parameters"][0]), lambda d: d["devices"][0].update(timeout=float("nan"))):
            data = self.config.to_dict()
            mutate(data)
            with self.assertRaises(ValueError):
                Configuration.from_dict(data)

    def test_one_based_range_validation(self):
        self.config.devices[0].address_base = 1
        with self.assertRaises(ValueError):
            self.config.validate()
        self.config.parameters[0].address = 1
        self.config.validate()


class TcpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = TcpClient(Device(port=self.server.server_address[1], timeout=0.3))

    def tearDown(self):
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_real_tcp_batch_keepalive_coils_inputs(self):
        self.assertEqual(self.client.read(3, 0, 5), [2304,842,0,1938,5000])
        self.assertEqual(self.client.read(4, 8, 1), [324])
        self.assertEqual(self.client.read(1, 0, 9), [0,1,0,1,0,1,0,1,0])
        self.assertEqual(self.client.read(2, 1, 2), [1,0])

    def test_device_exception(self):
        with self.assertRaises(ProtocolException):
            self.client.read(3, 0, 126)

    def test_disconnect_and_reconnect(self):
        self.assertEqual(self.client.read(3, 0, 1), [2304])
        self.client._disconnect()
        self.assertEqual(self.client.read(3, 1, 1), [842])

    def test_cancelled_client_does_not_connect(self):
        self.client.close()
        with self.assertRaises(ModbusError):
            self.client.read(3, 0, 1)


@unittest.skipUnless(hasattr(__import__('os'), 'openpty'), 'POSIX pseudo terminal required')
class RtuIntegrationTests(unittest.TestCase):
    def test_serial_pseudoterminal_crc_and_decode(self):
        import os
        import select
        master, slave = os.openpty()
        device = Device(transport="rtu", serial_port=os.ttyname(slave), timeout=0.5)
        captured = []
        def serve():
            if not select.select([master], [], [], 2)[0]:
                return
            data = os.read(master, 256)
            captured.append(data)
            payload = b"\x01\x03\x04\x09\x00\x03\x4a"
            os.write(master, payload + struct.pack("<H", crc16(payload)))
        thread = threading.Thread(target=serve)
        thread.start()
        client = RtuClient(device)
        try:
            self.assertEqual(client.read(3, 0, 2), [2304,842])
            thread.join(3)
            self.assertEqual(captured[0][:6], b"\x01\x03\x00\x00\x00\x02")
            self.assertEqual(crc16(captured[0][:-2]), int.from_bytes(captured[0][-2:], "little"))
        finally:
            client.close()
            os.close(master)
            os.close(slave)
            thread.join(3)


if __name__ == "__main__":
    unittest.main()
