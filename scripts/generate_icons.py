#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Render the source SVG with Qt. No image generation service is required."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import subprocess
import sys
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]


def generate():
    app = QApplication.instance() or QApplication([])
    target = ROOT / "assets" / "icons"
    target.mkdir(exist_ok=True)
    renderer = QSvgRenderer(QByteArray((ROOT / "assets" / "modbusregquest.svg").read_bytes()))
    for size in (16, 32, 48, 64, 128, 256, 512, 1024):
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        if not image.save(str(target / f"modbusregquest-{size}.png")):
            raise RuntimeError("Could not render icon")
    if sys.platform == "darwin":
        import shutil
        iconset = target / "ModbusRegQuest.iconset"
        iconset.mkdir(exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            shutil.copy2(target/f"modbusregquest-{size}.png", iconset/f"icon_{size}x{size}.png")
            shutil.copy2(target/f"modbusregquest-{size*2}.png", iconset/f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target/"ModbusRegQuest.icns")], check=True)
    return target


if __name__ == "__main__":
    print(generate())
