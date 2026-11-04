# Third-party software

The ModbusRegQuest application source is licensed under Apache-2.0.
See LICENSE for the full Apache License, Version 2.0, and NOTICE for attribution.

ModbusRegQuest uses the following components. Their respective licenses apply to
those components independently of the application source code.

| Component | License | Source and license |
| --- | --- | --- |
| Python | PSF License | https://www.python.org/downloads/source/ |
| Qt / PySide6 / Shiboken6 | LGPL v3 / GPL / commercial, depending on component | https://code.qt.io/pyside/pyside-setup.git/ and https://www.qt.io/licensing/open-source-lgpl-obligations |
| pyserial | BSD 3-Clause | https://github.com/pyserial/pyserial |
| PyInstaller bootloader | GPL with the PyInstaller bootloader exception | https://pyinstaller.org/en/stable/license.html |

Qt libraries are included as shared libraries in the desktop bundle. They are
not statically linked into ModbusRegQuest. This notice is copied into the release
bundle's `licenses` directory. Full license texts and Qt/PySide source are
available from the upstream source repository;
use the tag matching the version in `requirements-release.txt`.

The release workflow creates unsigned/ad-hoc-signed macOS builds unless the
maintainer supplies a Developer ID signing identity and notarization profile
for a local release build.
