# SPDX-License-Identifier: Apache-2.0
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import time
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from modbusregquest.dialogs import DeviceDialog, ParameterDialog
from modbusregquest.models import Device, Parameter, demo_configuration
from modbusregquest.storage import Store, export_configuration, read_configuration
from modbusregquest.theme import STYLE
from modbusregquest.window import MainWindow
from scripts.modbus_simulator import Handler, Server


APP = QApplication.instance() or QApplication([])
APP.setStyle("Fusion")
APP.setStyleSheet(STYLE)
APP.setQuitOnLastWindowClosed(False)


def wait_for(predicate, timeout=2500):
    deadline = time.monotonic() + timeout/1000
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        QTest.qWait(20)
    return False


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/"config.db")
        self.window = MainWindow(self.store)
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        if self.window.poller:
            self.window.poller.stop()
            self.assertTrue(wait_for(lambda: self.window.poller is None))
        self.window.close()
        APP.processEvents()
        self.store.close()
        self.temp.cleanup()

    def test_empty_demo_poll_stop_and_switch_language(self):
        self.assertEqual(self.window.table_stack.currentIndex(), 1)
        self.assertFalse(self.window.poll_button.isEnabled())
        QTest.mouseClick(self.window.demo_button, Qt.MouseButton.LeftButton)
        self.assertTrue(wait_for(lambda: len(self.window.values) == 7))
        self.assertEqual(self.window.table.rowCount(), 7)
        self.assertEqual(self.window.stats["errors"], 0)
        self.assertGreater(self.window.stats["saved"], 0)
        self.window.language.setCurrentIndex(1)
        APP.processEvents()
        self.assertEqual(self.window.config.language, "en")
        self.assertEqual(self.window.nav_buttons[0].text(), "Monitoring")
        self.assertIsNotNone(self.window.poller)
        QTest.mouseClick(self.window.poll_button, Qt.MouseButton.LeftButton)
        self.assertFalse(self.window.polling)
        self.assertEqual(self.window.state(self.window.config.parameters[0])[0], "paused")
        self.assertEqual(self.store.load().language, "en")

    def test_crud_filter_toggle_and_reopen(self):
        config = demo_configuration()
        self.assertTrue(self.window.apply_config(config))
        self.assertIsNone(self.window.poller)
        self.window.duplicate_parameter(config.parameters[0])
        self.assertEqual(len(self.window.config.parameters), 8)
        self.window.search.setText("Частота")
        self.assertEqual(self.window.table.rowCount(), 1)
        self.window.search.clear()
        parameter = self.window.config.parameters[0]
        self.window.toggle_parameter(parameter.id, False)
        self.assertFalse(self.store.load().parameters[0].enabled)
        self.assertEqual(self.window.state(self.window.config.parameters[0])[0], "off")
        path = Path(self.temp.name)/"export.json"
        export_configuration(self.window.config, path)
        self.assertEqual(read_configuration(path), self.store.load())
        reopened = MainWindow(self.store)
        self.assertEqual(len(reopened.config.parameters), 8)
        self.assertIsNone(reopened.poller)
        reopened.close()

    def test_editor_fields_and_addressing_preview(self):
        config = demo_configuration()
        config.devices[0].address_base = 1
        for parameter in config.parameters:
            parameter.address += 1
        dialog = ParameterDialog(config)
        dialog.show()
        APP.processEvents()
        self.assertGreater(dialog.interval.lineEdit().width(), 80)
        self.assertGreater(dialog.address.lineEdit().width(), 80)
        dialog.name.setText("Temperature")
        dialog.address.setValue(3)
        dialog.data_type.setCurrentIndex(dialog.data_type.findData("float32"))
        dialog.interval.setValue(0.25)
        dialog.decimal_shift.setValue(2)
        self.assertIn("2", dialog.hint.text())
        dialog.submit()
        self.assertEqual(dialog.result_parameter.width, 2)
        self.assertEqual(dialog.result_parameter.wire_address(config.devices[0]), 2)
        self.assertEqual(dialog.result_parameter.interval, 0.25)
        self.assertEqual(dialog.result_parameter.decimal_shift, 2)
        dialog.function.setCurrentIndex(dialog.function.findData(1))
        self.assertEqual(dialog.data_type.currentData(), "bool")
        self.assertFalse(dialog.data_type.isEnabled())
        dialog.close()
        device_dialog = DeviceDialog(config, config.devices[0])
        device_dialog.name.setText("PLC A")
        device_dialog.transport.setCurrentIndex(device_dialog.transport.findData("tcp"))
        device_dialog.submit()
        self.assertEqual(device_dialog.result_device.name, "PLC A")
        self.assertEqual(device_dialog.result_device.address_base, 1)
        device_dialog.close()

    def test_real_tcp_polling_errors_and_recovery(self):
        server = Server(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = demo_configuration()
        config.devices[0].transport = "tcp"
        config.devices[0].port = server.server_address[1]
        config.devices[0].timeout = 0.2
        for parameter in config.parameters:
            parameter.interval = 0.1
        try:
            self.window.apply_config(config)
            self.window.toggle_polling()
            self.assertTrue(wait_for(lambda: len(self.window.values) == 7))
            self.assertEqual(self.window.values[config.parameters[0].id]["value"], 230.4)
            self.assertEqual(self.window.values[config.parameters[2].id]["value"], 1.938)
            # Redirect to a closed port while the worker is running.
            broken = deepcopy(config)
            broken.devices[0].port = 1
            self.window.apply_config(broken)
            self.assertTrue(wait_for(lambda: any(v["error"] for v in self.window.values.values())))
            self.assertTrue(APP.activeWindow() is not None)
            self.window.apply_config(config)
            self.assertTrue(wait_for(lambda: len(self.window.values) == 7 and all(not v["error"] for v in self.window.values.values())))
        finally:
            if self.window.poller:
                self.window.poller.stop()
                wait_for(lambda: self.window.poller is None)
            server.shutdown()
            server.server_close()
            thread.join()

    def test_disabling_all_stops_worker(self):
        self.window.load_demo()
        self.assertTrue(wait_for(lambda: len(self.window.values) == 7))
        config = deepcopy(self.window.config)
        for parameter in config.parameters:
            parameter.enabled = False
        self.window.apply_config(config)
        self.assertFalse(self.window.polling)
        self.assertFalse(self.window.poll_button.isEnabled())

    def test_close_waits_for_worker(self):
        self.window.load_demo()
        self.assertTrue(wait_for(lambda: len(self.window.values) == 7))
        self.window.close()
        self.assertTrue(wait_for(lambda: self.window.poller is None))
        self.assertFalse(self.window.isVisible())

    def test_command_when_polling_is_off_and_byte_inspector(self):
        from modbusregquest.commands import Command
        self.window.apply_config(demo_configuration())
        device=self.window.config.devices[0]
        command=Command(device.id,16,100,(0x1234,0x5678))
        self.assertTrue(self.window.send_command(command))
        self.assertFalse(self.window.polling)
        self.assertTrue(wait_for(lambda: not self.window._pending_commands))
        self.assertEqual(len(self.window.logs),1)
        event=self.window._last_command
        self.assertFalse(event['error'])
        self.assertEqual(event['request'][7:],command.pdu())
        self.assertTrue(self.window.command_trace.editors[False,'hex'].toPlainText())
        groups=self.window.command_trace.byte_views[False].groups
        self.assertEqual([g['address'] for g in groups if g['label']=='register'],[100,101])
        self.assertEqual(next(g for g in groups if g['label']=='length')['data'],b'\x00\x0b')
        self.window.navigate(2)
        self.assertEqual(self.window.log_table.rowCount(),1)
        self.assertEqual(self.window.trace_view.exchange_event['id'],event['id'])

    def test_theme_saved_and_presentation_change_does_not_cancel_command(self):
        from modbusregquest.commands import Command
        self.window.apply_config(demo_configuration())
        worker=self.window.ensure_worker()
        revision=worker.revision
        self.window.send_command(Command(self.window.config.devices[0].id,6,100,(123,)))
        self.window.change_theme('dark')
        self.assertEqual(self.window.config.theme,'dark')
        self.assertEqual(self.store.load().theme,'dark')
        self.assertLess(APP.palette().base().color().lightness(),128)
        self.assertEqual(worker.revision,revision)
        self.assertTrue(wait_for(lambda: not self.window._pending_commands))
        self.assertFalse(self.window._last_command['error'])
        self.window.change_theme('light')
        self.assertGreater(APP.palette().base().color().lightness(),200)
        self.assertEqual(self.store.load().theme,'light')

    def test_log_selection_stays_pinned_filters_and_clear(self):
        from modbusregquest.commands import Command
        self.window.load_demo()
        self.assertTrue(wait_for(lambda: len(self.window.logs)>0))
        self.window.navigate(2)
        self.window.populate_log()
        selected=self.window.trace_view.exchange_event['id']
        self.assertTrue(wait_for(lambda: len(self.window.logs)>1))
        self.window.populate_log()
        self.assertEqual(self.window.trace_view.exchange_event['id'],selected)
        self.window.toggle_polling()
        self.window.send_command(Command(self.window.config.devices[0].id,5,10,(1,)))
        self.assertTrue(wait_for(lambda: not self.window._pending_commands))
        self.window.navigate(2)
        self.window.log_filter.setCurrentIndex(self.window.log_filter.findData('write'))
        self.assertEqual(self.window.log_table.rowCount(),1)
        self.window.clear_log()
        self.assertIsNone(self.window.trace_view.exchange_event)
        self.assertEqual(self.window.log_table.rowCount(),0)

    def test_command_dialog_validates_and_typed_value_uses_scale(self):
        from modbusregquest.dialogs import CommandDialog
        config=demo_configuration()
        dialog=CommandDialog(config)
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.function.setCurrentIndex(dialog.function.findData(16))
        dialog.address.setValue(100)
        dialog.values.setPlainText('0x1234 0x5678')
        self.assertTrue(dialog.save_button.isEnabled())
        self.assertIn('10 00 64 00 02 04 12 34 56 78',dialog.preview.toPlainText())
        dialog.submit()
        self.assertEqual(dialog.result_command.values,(0x1234,0x5678))
        typed=CommandDialog(config,parameter=config.parameters[0])
        typed.value.setText('23,4')
        typed.submit()
        self.assertEqual(typed.result_command.values,(234,))
        self.assertEqual(typed.result_command.function,6)
        dialog.close();typed.close()


if __name__ == "__main__":
    unittest.main()
