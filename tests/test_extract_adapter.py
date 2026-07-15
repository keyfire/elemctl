"""Тест извлечения debug-адаптера: мини-.car во временном каталоге.

Экстрактор – скрипт в tools/ (не часть пакета), загружается по пути.
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "tools" / "extract_adapter.py"
_spec = importlib.util.spec_from_file_location("extract_adapter", _TOOLS)
extract_adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract_adapter)

_PREFIX = "data/ide/theia/plugins/@1c-appengine-plugin/bin/debugger/"


def _make_car(path: Path) -> Path:
    car = path / "1c-enterprise-element-server-with-ide-9.2.8+11-linux-x86_64.e1c.car"
    with zipfile.ZipFile(car, "w") as z:
        z.writestr(_PREFIX + "repo/com.e1c.g5rt.debugger.adapter-9.2.8-1.jar", b"JAR")
        z.writestr(_PREFIX + "repo/netty-common-4.1.0.jar", b"JAR")
        z.writestr(_PREFIX + "bin/g5rt.debugger.adapter", b"#!/bin/sh\n")
        z.writestr("data/other/ignored.txt", b"nope")  # вне каталога адаптера
    return car


def test_extract_places_adapter_and_index(tmp_path):
    car = _make_car(tmp_path)
    out = tmp_path / "out"
    rc = extract_adapter.main([str(car), "--output", str(out)])
    assert rc == 0
    version_dir = out / "9.2.8+11"
    assert (version_dir / "repo" / "com.e1c.g5rt.debugger.adapter-9.2.8-1.jar").exists()
    assert (version_dir / "bin" / "g5rt.debugger.adapter").exists()
    assert not (version_dir / "ignored.txt").exists()  # взято только из debugger/
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert index["default"] == "9.2.8+11"
    assert "9.2.8+11" in index["available"]


def test_extract_refuses_existing_version(tmp_path):
    car = _make_car(tmp_path)
    out = tmp_path / "out"
    extract_adapter.main([str(car), "--output", str(out)])
    with __import__("pytest").raises(SystemExit):
        extract_adapter.extract(car, "9.2.8+11", out)


def test_find_car_in_directory(tmp_path):
    car = _make_car(tmp_path)
    assert extract_adapter.find_car(tmp_path) == car


def test_detect_version(tmp_path):
    car = _make_car(tmp_path)
    assert extract_adapter.detect_version(car) == "9.2.8+11"
