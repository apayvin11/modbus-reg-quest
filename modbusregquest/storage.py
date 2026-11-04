# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile

from .models import Configuration, MAX_CONFIG_BYTES


class Store:
    """One validated, transactional configuration; never persist polling state."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise ValueError("This database requires a newer ModbusRegQuest version")
        with self.connection:
            self.connection.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self.connection.execute("CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            self.connection.execute("CREATE TABLE IF NOT EXISTS parameters (id TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id), data TEXT NOT NULL)")
            self.connection.execute("PRAGMA user_version=1")

    def load(self):
        theme = self.connection.execute("SELECT value FROM settings WHERE key='theme'").fetchone()
        language = self.connection.execute("SELECT value FROM settings WHERE key='language'").fetchone()
        return Configuration.from_dict({"format": "modbusregquest", "version": 1,
            "language": language[0] if language else "ru", "theme": theme[0] if theme else "light",
            "devices": [json.loads(row[0]) for row in self.connection.execute("SELECT data FROM devices ORDER BY rowid")],
            "parameters": [json.loads(row[0]) for row in self.connection.execute("SELECT data FROM parameters ORDER BY rowid")]})

    def save(self, config: Configuration):
        config.validate()
        data = config.to_dict()
        with self.connection:
            self.connection.execute("DELETE FROM parameters")
            self.connection.execute("DELETE FROM devices")
            self.connection.executemany("INSERT INTO devices VALUES (?, ?)", [(d["id"], json.dumps(d, ensure_ascii=False)) for d in data["devices"]])
            self.connection.executemany("INSERT INTO parameters VALUES (?, ?, ?)", [(p["id"], p["device_id"], json.dumps(p, ensure_ascii=False)) for p in data["parameters"]])
            self.connection.execute("INSERT INTO settings VALUES ('language', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (config.language,))

            self.connection.execute("INSERT INTO settings VALUES ('theme', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (config.theme,))

    def close(self):
        self.connection.close()


def read_configuration(path: Path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("Configuration exceeds 5 MiB")
    return Configuration.from_dict(json.loads(raw))


def export_configuration(config: Configuration, path: Path):
    config.validate()
    path = Path(path)
    payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    atomic_write(path, payload)


def atomic_write(path: Path, payload: str):
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def migrate_legacy_database(target: Path, legacy: Path):
    """Copy the previous application database once, including committed WAL data."""
    target, legacy = Path(target), Path(legacy)
    if target.exists() or not legacy.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".migration-", dir=target.parent)
    os.close(handle)
    try:
        source = sqlite3.connect(legacy.resolve().as_uri()+"?mode=ro", uri=True)
        destination = sqlite3.connect(temporary)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        check = Store(Path(temporary))
        try:
            check.load().validate()
        finally:
            check.close()
        os.replace(temporary, target)
        return True
    finally:
        for suffix in ("", "-wal", "-shm"):
            path = Path(temporary+suffix)
            if path.exists():
                path.unlink()
