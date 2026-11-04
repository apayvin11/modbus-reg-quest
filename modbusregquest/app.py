# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from .models import demo_configuration
from .storage import Store, migrate_legacy_database
from .theme import STYLE
from .window import MainWindow


def main(argv=None):
    parser = argparse.ArgumentParser(description="ModbusRegQuest desktop workstation")
    parser.add_argument("--db", type=Path, help="SQLite configuration path")
    parser.add_argument("--demo", action="store_true", help="Open an isolated simulator workspace")
    parser.add_argument("--language", choices=("ru", "en"), help="Interface language")
    parser.add_argument("--theme", choices=("light", "dark"), help="Interface theme")
    parser.add_argument("--screenshot", type=Path, help="Save a window screenshot after 2 seconds")
    parser.add_argument("--quit-after", type=float, default=0, help="Quit after N seconds (smoke tests)")
    args = parser.parse_args(argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ModbusRegQuest")
    app.setOrganizationName("ModbusRegQuest")
    app.setApplicationVersion("1.0.0")
    app.setDesktopFileName("modbusregquest")
    asset_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "assets"
    app.setWindowIcon(QIcon(str(asset_root / ("modbusregquest-512.png" if getattr(sys, "frozen", False) else "modbusregquest.svg"))))
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#F5F7FA"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#1B293C"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#1B293C"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#1B293C"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#0C9B80"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
    path = args.db or (Path(":memory:") if args.demo else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / "configuration.db")
    try:
        if not args.db and not args.demo:
            legacy = path.parent.parent.parent / "ModbusPoll" / "ModbusPoll" / "configuration.db"
            migrate_legacy_database(path, legacy)
        store = Store(path)
        config = demo_configuration(args.language or "ru") if args.demo else store.load()
        if args.language:
            config.language = args.language
        if args.theme:
            config.theme = args.theme
        window = MainWindow(store, config)
    except Exception as exc:
        QMessageBox.critical(None, "ModbusRegQuest", f"Could not open configuration database:\n{exc}")
        return 1
    window.show()
    if args.demo:
        window.toggle_polling()
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(args.screenshot)):
                print("Could not save screenshot", file=sys.stderr)
        QTimer.singleShot(2000, capture)
    if args.quit_after > 0:
        QTimer.singleShot(round(args.quit_after*1000), window.close)
    result = app.exec()
    store.close()
    return result
