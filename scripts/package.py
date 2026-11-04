#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build a native desktop bundle and an installer for the current architecture."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys

from generate_icons import generate

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0"
BUNDLE_ID = "io.modbusregquest.desktop"


def run(*args, **kwargs):
    print("+", " ".join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, cwd=ROOT, **kwargs)


def architecture():
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    raise SystemExit(f"Unsupported architecture: {machine}")


def bundle(arch, icons):
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--specpath", ROOT/"build"/"spec",
            "--windowed", "--name", "ModbusRegQuest", "--paths", ROOT,
            "--hidden-import", "serial.tools.list_ports", "--collect-data", "modbusregquest",
            "--add-data", f"{ROOT/'assets'/'icons'/'modbusregquest-512.png'}:assets",
            "--add-data", f"{ROOT/'THIRD_PARTY_NOTICES.md'}:licenses",
            "--add-data", f"{ROOT/'LICENSE'}:licenses",
            "--add-data", f"{ROOT/'NOTICE'}:licenses",
            "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
            "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtQuick"]
    if sys.platform == "darwin":
        args += ["--target-architecture", arch, "--icon", icons/"ModbusRegQuest.icns", "--osx-bundle-identifier", BUNDLE_ID]
        identity = os.environ.get("MACOS_CODESIGN_IDENTITY")
        if identity:
            args += ["--codesign-identity", identity]
    args += [ROOT/"scripts"/"launcher.py"]
    run(*args)
    if sys.platform == "darwin":
        app = ROOT/"dist"/"ModbusRegQuest.app"
        info = app/"Contents"/"Info.plist"
        with info.open("rb") as stream:
            data = plistlib.load(stream)
        data.update(CFBundleShortVersionString=VERSION, CFBundleVersion="1.0.0",
                    NSHighResolutionCapable=True, LSMinimumSystemVersion="15.0",
                    CFBundleDisplayName="ModbusRegQuest", NSHumanReadableCopyright="ModbusRegQuest contributors")
        with info.open("wb") as stream:
            plistlib.dump(data, stream)
        # Editing Info.plist invalidates the bundle seal; sign it again.
        identity = os.environ.get("MACOS_CODESIGN_IDENTITY", "-")
        signing = ["codesign", "--force", "--deep", "--sign", identity]
        if identity != "-":
            signing += ["--options", "runtime", "--timestamp"]
        run(*signing, app)
        run("codesign", "--verify", "--deep", "--strict", app)
        return app
    return ROOT/"dist"/"ModbusRegQuest"


def dmg(app, arch, output):
    stage = ROOT/"build"/"dmg-stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    # ditto preserves the .app's framework symlinks and metadata.
    run("ditto", app, stage/"ModbusRegQuest.app")
    (stage/"Applications").symlink_to("/Applications", target_is_directory=True)
    target = output/f"ModbusRegQuest-{VERSION}-macos-{arch}.dmg"
    if target.exists():
        target.unlink()
    run("hdiutil", "create", "-volname", "ModbusRegQuest", "-srcfolder", stage,
        "-ov", "-format", "UDZO", target)
    profile = os.environ.get("MACOS_NOTARY_PROFILE")
    if profile:
        run("xcrun", "notarytool", "submit", target, "--keychain-profile", profile, "--wait")
        run("xcrun", "stapler", "staple", target)
        run("xcrun", "stapler", "validate", target)
    run("hdiutil", "verify", target)
    return target


def deb(app, arch, output, icons):
    deb_arch = "amd64" if arch == "x86_64" else "arm64"
    stage = ROOT/"build"/f"deb-{deb_arch}"
    if stage.exists():
        shutil.rmtree(stage)
    (stage/"DEBIAN").mkdir(parents=True)
    lib = stage/"usr"/"lib"/"modbusregquest"
    shutil.copytree(app, lib, symlinks=True)
    executable = stage/"usr"/"bin"
    executable.mkdir(parents=True)
    (executable/"modbusregquest").symlink_to("../lib/modbusregquest/ModbusRegQuest")
    applications = stage/"usr"/"share"/"applications"
    applications.mkdir(parents=True)
    shutil.copy2(ROOT/"packaging"/"modbusregquest.desktop", applications/"modbusregquest.desktop")
    for size in (16, 32, 48, 64, 128, 256, 512):
        directory = stage/"usr"/"share"/"icons"/"hicolor"/f"{size}x{size}"/"apps"
        directory.mkdir(parents=True)
        shutil.copy2(icons/f"modbusregquest-{size}.png", directory/"modbusregquest.png")
    scalable = stage/"usr"/"share"/"icons"/"hicolor"/"scalable"/"apps"
    scalable.mkdir(parents=True)
    shutil.copy2(ROOT/"assets"/"modbusregquest.svg", scalable/"modbusregquest.svg")
    docs = stage/"usr"/"share"/"doc"/"modbusregquest"
    docs.mkdir(parents=True)
    for filename in ("Readme.md", "THIRD_PARTY_NOTICES.md", "LICENSE", "NOTICE"):
        shutil.copy2(ROOT/filename, docs/filename)
    installed_size = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file() and not p.is_symlink())//1024
    dependencies = ("libc6 (>= 2.39), libstdc++6 (>= 13), libgl1, libegl1, libopengl0, "
        "libxkbcommon0, libxkbcommon-x11-0, libxcb1, libxcb-cursor0, libxcb-icccm4, "
        "libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render0, libxcb-render-util0, "
        "libxcb-shape0, libxcb-shm0, libxcb-sync1, libxcb-xfixes0, libxcb-xinerama0, "
        "libdbus-1-3, libfontconfig1, libfreetype6, libx11-6, libx11-xcb1, libxi6, libxrender1, "
        "libglib2.0-0t64 | libglib2.0-0")
    (stage/"DEBIAN"/"control").write_text(f"""Package: modbusregquest
Version: {VERSION}
Section: utils
Priority: optional
Architecture: {deb_arch}
Maintainer: Alex Payvin <106412250+apayvin11@users.noreply.github.com>
Installed-Size: {installed_size}
Depends: {dependencies}
Description: Desktop Modbus TCP and RTU read/write workstation
 Configure devices and parameters, monitor current values,
 write coils and registers, inspect decoded/HEX frames, and transfer configurations.
 Russian and English interface. Python runtime is included.
""", encoding="utf-8")
    for script in ("postinst", "postrm"):
        path = stage/"DEBIAN"/script
        path.write_text("#!/bin/sh\nset -e\nif command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi\nif command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true; fi\nexit 0\n")
        path.chmod(0o755)
    for path in stage.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.name == "ModbusRegQuest" or path.parent.name == "DEBIAN" and path.name in ("postinst", "postrm"):
            path.chmod(0o755)
        elif not path.stat().st_mode & 0o111:
            path.chmod(0o644)
    target = output/f"modbusregquest_{VERSION}_{deb_arch}.deb"
    run("dpkg-deb", "--root-owner-group", "--build", stage, target)
    run("dpkg-deb", "--info", target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("bundle", "dmg", "deb"), required=True)
    parser.add_argument("--arch", choices=("arm64", "x86_64"), help="Expected native architecture; prevents mislabeled builds")
    parser.add_argument("--skip-bundle", action="store_true", help="Package an existing dist/ModbusRegQuest bundle")
    args = parser.parse_args()
    arch = architecture()
    if args.arch and args.arch != arch:
        raise SystemExit(f"Use a native {args.arch} runner. Current Python architecture: {arch}")
    if args.format == "dmg" and sys.platform != "darwin" or args.format == "deb" and sys.platform != "linux":
        raise SystemExit("DMG requires macOS; DEB requires Linux")
    os.chdir(ROOT)
    icons = generate()
    app = (ROOT/"dist"/("ModbusRegQuest.app" if sys.platform == "darwin" else "ModbusRegQuest")) if args.skip_bundle else bundle(arch, icons)
    if not app.exists():
        raise SystemExit(f"Bundle does not exist: {app}")
    if args.format == "bundle":
        print(f"Built: {app}")
        return
    output = ROOT/"release"
    output.mkdir(exist_ok=True)
    artifact = dmg(app, arch, output) if args.format == "dmg" else deb(app, arch, output, icons)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    artifact.with_suffix(artifact.suffix+".sha256").write_text(f"{digest}  {artifact.name}\n")
    print(f"Release: {artifact}\nSHA256: {digest}")


if __name__ == "__main__":
    main()
