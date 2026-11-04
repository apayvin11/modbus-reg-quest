# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from pathlib import Path
import os
import select
import socketserver
import struct
import tempfile
import threading
import time
import unittest

from modbusregquest.commands import Command, encode_value, parameter_command, parse_values
from modbusregquest.models import Configuration, Device, Parameter, demo_configuration
from modbusregquest.protocol import ModbusError, RtuClient, TcpClient, crc16, decode_value
from modbusregquest.storage import Store, migrate_legacy_database
from modbusregquest.tracing import dissect_frame, frame_groups, export_event
from modbusregquest.simulation import MemoryDevice
from scripts.modbus_simulator import Handler, Server


class CommandTests(unittest.TestCase):
    def test_wire_formats(self):
        self.assertEqual(Command('d',5,10,(1,)).pdu().hex(), '05000aff00')
        self.assertEqual(Command('d',6,10,(0x1234,)).pdu().hex(), '06000a1234')
        self.assertEqual(Command('d',15,10,(1,0,1,0,0,0,0,1,1)).pdu().hex(), '0f000a0009028501')
        self.assertEqual(Command('d',16,10,(0x1234,0xABCD)).pdu().hex(), '10000a0002041234abcd')
        self.assertEqual(Command('d',22,10,(0xFFFE,1)).pdu().hex(), '16000afffe0001')
        self.assertEqual(parse_values('123; 0xFFFF, 001'), (123,65535,1))

    def test_limits_and_validation(self):
        for command in (Command('d',3,0,(1,)),Command('d',5,0,(2,)),Command('d',6,0,(-1,)),
            Command('d',6,0,(65536,)),Command('d',16,65535,(1,2)),Command('d',15,0,(1,)*1969),
            Command('d',16,0,(1,)*124),Command('d',22,0,(1,)),Command('d',6,0,()),Command('d',6,0,(True,))):
            with self.assertRaises(ValueError):
                command.pdu()
        self.assertEqual(len(Command('d',16,0,(0,)*123).pdu()),252)
        self.assertEqual(len(Command('d',15,0,(0,)*1968).pdu()),252)

    def test_typed_inverse_byte_orders_and_scale(self):
        for kind, value in (('int16','-12.5'),('uint32','2345.67'),('int64','-92233720368547758.08'),
                            ('uint64','184467440737095516.15'),('float32','123.25'),('float64','-0.125')):
            shift = 1 if kind == 'int16' else 2 if kind not in ('float32','float64') else 0
            for order in ('ABCD','BADC','CDAB','DCBA'):
                p=Parameter(data_type=kind,decimal_shift=shift,byte_order=order)
                registers=encode_value(p,value)
                self.assertAlmostEqual(decode_value(p,registers),float(value))
        with self.assertRaises(ValueError):
            encode_value(Parameter(data_type='uint16'), '1.5')
        with self.assertRaises(ValueError):
            encode_value(Parameter(data_type='float32'), 'nan')
        with self.assertRaises(ValueError):
            encode_value(Parameter(data_type='float32'), '1e100')

    def test_parameter_commands_and_bit_masks(self):
        d=Device(address_base=1)
        p=Parameter(device_id=d.id,address=101,data_type='uint32',decimal_shift=2)
        command=parameter_command(p,d,'23.45')
        self.assertEqual((command.function,command.address,command.values),(16,100,(0,2345)))
        p.data_type='bool';p.bit=3
        command=parameter_command(p,d,'1')
        self.assertEqual((command.function,command.values),(22,(0xFFF7,8)))
        p.function=4
        with self.assertRaises(ValueError):
            parameter_command(p,d,'1')


class TcpWriteTests(unittest.TestCase):
    def setUp(self):
        self.server=Server(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.device=Device(port=self.server.server_address[1],timeout=0.3)
        self.client=TcpClient(self.device)

    def tearDown(self):
        self.client.close();self.server.shutdown();self.server.server_close();self.thread.join()

    def command(self,fc,address,values):
        return Command(self.device.id,fc,address,values)

    def test_all_functions_write_readback_and_trace(self):
        for fc,address,values,read_fc in ((5,100,(1,),1),(6,100,(65535,),3),
            (15,200,(1,0,1,0,1,1,0,0,1),1),(16,300,(0x1234,0x5678),3)):
            command=self.command(fc,address,values)
            self.assertTrue(self.client.write(command))
            trace=dict(self.client.trace)
            self.assertEqual(trace['request'][7:],command.pdu())
            self.assertEqual(trace['sent'],len(trace['request']))
            expected=command.pdu()[:5] if fc in (15,16) else command.pdu()
            self.assertEqual(trace['response'][7:],expected)
            self.assertEqual(trace['operation'],'write')
            self.assertEqual(self.client.read(read_fc,address,len(values)),list(values))
        self.client.write(self.command(6,400,(0xAAAA,)))
        self.client.write(self.command(22,400,(0xFFFE,1)))
        self.assertEqual(self.client.read(3,400,1),[0xAAAB])
        self.assertEqual(self.client.read(4,400,1),[400])  # input registers are independent

    def test_decoded_frames_and_annotated_register_addresses(self):
        self.client.write(self.command(16,100,(0x1234,0x5678)))
        trace=dict(self.client.trace)
        groups=frame_groups(trace)
        data=[g for g in groups if g['label']=='register']
        self.assertEqual([(g['address'],g['data']) for g in data],[(100,b'\x12\x34'),(101,b'\x56\x78')])
        self.assertEqual(next(g for g in groups if g['label']=='length')['data'],b'\x00\x0b')
        self.assertEqual(b''.join(g['data'] for g in groups),trace['request'])
        self.client.read(3,100,2)
        trace=dict(self.client.trace)
        groups=frame_groups(trace,True)
        self.assertEqual([g['address'] for g in groups if g['label']=='register'],[100,101])
        self.assertEqual(b''.join(g['data'] for g in groups),trace['response'])
        decoded=dissect_frame(trace['response'],'tcp',response=True,request_pdu=trace['request_pdu'])
        self.assertEqual(decoded['registers'],[0x1234,0x5678])
        self.assertEqual(export_event(trace)['response'],trace['response'].hex(' ').upper())


class BrokenWriteTests(unittest.TestCase):
    def exchange(self,response_factory):
        requests=[]
        class Broken(Handler):
            def handle(inner):
                header=inner.receive(7)
                if not header:return
                length=int.from_bytes(header[4:6],'big')
                pdu=inner.receive(length-1)
                requests.append(header+pdu)
                payload=response_factory(header,pdu)
                inner.request.sendall(payload)
        server=Server(('127.0.0.1',0),Broken)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        client=TcpClient(Device(port=server.server_address[1],timeout=0.1))
        try:
            with self.assertRaises((ModbusError,OSError)):
                client.write(Command('d',6,10,(123,)))
            self.assertEqual(len(requests),1)
            self.assertEqual(client.trace['response'],response_factory(requests[0][:7],requests[0][7:]))
            return dict(client.trace)
        finally:
            client.close();server.shutdown();server.server_close();thread.join()

    def test_mismatched_ack_is_not_success_or_retried(self):
        trace=self.exchange(lambda header,pdu: header+pdu[:2]+b'\xff'+pdu[3:])
        self.assertIn('acknowledgement',trace['error'])

    def test_partial_response_keeps_received_bytes(self):
        trace=self.exchange(lambda header,pdu: header+pdu[:2])
        self.assertEqual(len(trace['response']),9)
        self.assertTrue(trace['error'])

    def test_exception_response_preserved_and_decoded(self):
        def error(header,pdu):
            return header[:4]+b'\x00\x03'+header[6:7]+b'\x86\x02'
        trace=self.exchange(error)
        self.assertIn('0x02',trace['error'])
        self.assertEqual(dissect_frame(trace['response'],'tcp',response=True)['exception_code'],'0x02')


@unittest.skipUnless(hasattr(os,'openpty'),'POSIX required')
class RtuWriteTests(unittest.TestCase):
    def test_write_ack_crc_and_labeled_frames(self):
        master,slave=os.openpty()
        memory=MemoryDevice()
        captured=[]
        def serve():
            for _ in range(3):
                data=bytearray()
                while len(data)<8:
                    if not select.select([master],[],[],2)[0]:return
                    data.extend(os.read(master,256))
                    if len(data)>=7 and data[1] in (15,16):
                        while len(data)<9+data[6]:
                            if not select.select([master],[],[],2)[0]:return
                            data.extend(os.read(master,256))
                captured.append(bytes(data))
                response=bytes([data[0]])+memory.exchange(bytes(data[1:-2]))
                os.write(master,response+struct.pack('<H',crc16(response)))
        thread=threading.Thread(target=serve);thread.start()
        d=Device(transport='rtu',serial_port=os.ttyname(slave),timeout=0.5)
        client=RtuClient(d)
        try:
            self.assertTrue(client.write(Command(d.id,16,100,(0x1234,0x5678))))
            trace=dict(client.trace)
            self.assertTrue(dissect_frame(trace['request'],'rtu')['crc_valid'])
            groups=frame_groups(trace)
            self.assertEqual([g['address'] for g in groups if g['label']=='register'],[100,101])
            self.assertEqual(groups[-1]['label'],'crc')
            self.assertEqual(b''.join(g['data'] for g in groups),trace['request'])
            self.assertEqual(client.read(3,100,2),[0x1234,0x5678])
            self.assertTrue(client.write(Command(d.id,22,100,(0xFFFE,1))))
            self.assertEqual(memory.register(100),0x1235)
        finally:
            client.close();thread.join(3);os.close(master);os.close(slave)


class CompatibilityTests(unittest.TestCase):
    def test_legacy_json_and_theme_roundtrip(self):
        old=demo_configuration().to_dict();old['format']='modbuspoll';old.pop('theme',None)
        config=Configuration.from_dict(old)
        self.assertEqual(config.theme,'light')
        self.assertEqual(config.to_dict()['format'],'modbusregquest')
        config.theme='dark'
        self.assertEqual(Configuration.from_dict(config.to_dict()).theme,'dark')
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'config.db')
            store.save(config)
            self.assertEqual(store.load().theme,'dark');store.close()

    def test_database_migration_with_wal_preserves_legacy_and_existing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy=Path(tmp)/'old'/'configuration.db';target=Path(tmp)/'new'/'configuration.db'
            store=Store(legacy);config=demo_configuration();store.save(config)
            self.assertTrue(migrate_legacy_database(target,legacy))
            migrated=Store(target)
            self.assertEqual(migrated.load(),config)
            self.assertEqual(store.load(),config)
            self.assertFalse(migrate_legacy_database(target,legacy))
            migrated.close();store.close()
