#!/usr/bin/env python3
"""Извлечение Java-адаптера отладки платформы 1С:Предприятие.Элемент из дистрибутива.

Адаптер лежит внутри .car (это ZIP) сервера-с-IDE по пути
data/ide/theia/plugins/@1c-appengine-plugin/bin/debugger/ (подкаталоги bin/ и
repo/ с jar-файлами адаптера). Проприетарные компоненты 1С в состав elemctl не
входят – их извлекает этот скрипт из дистрибутива, которым вы лицензированы.

Результат – каталог <output>/<версия>/ с подкаталогом repo/: готовое значение
настройки xbslDebug.adapterPath расширения VS Code keyfire.xbsl-debug. Скрипт также
пишет <output>/index.json (доступные версии и версия по умолчанию) – его читает
пакет-плагин elemctl (группа точек расширения elemctl.debug_adapter), когда адаптер
поставляется через плагин.

Использование:
    # для ручной настройки adapterPath:
    python tools/extract_adapter.py <путь к .car или к каталогу дистрибутива> --output C:/tools/xbsl-adapter
    # для сборки пакета-плагина:
    python tools/extract_adapter.py <дистрибутив> --output <elemctl-plugin>/elemctl_plugin/adapter
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
import re

ADAPTER_PREFIX = "data/ide/theia/plugins/@1c-appengine-plugin/bin/debugger/"
VERSION_RE = re.compile(r"(\d+\.\d+\.\d+\+\d+)")


def find_car(path: Path) -> Path:
    """Путь к .car сервера-с-IDE: сам файл либо внутри каталога дистрибутива."""
    if path.is_file():
        return path
    if path.is_dir():
        cars = sorted(path.glob("*element-server-with-ide-*.car"))
        if not cars:
            cars = sorted(path.glob("*.car"))
        if cars:
            return cars[0]
    raise SystemExit(f"не найден .car в {path}")


def detect_version(car: Path) -> str:
    """Версия платформы из имени .car (major.minor.patch+build)."""
    match = VERSION_RE.search(car.name)
    if not match:
        raise SystemExit(f"не удалось определить версию из имени {car.name}")
    return match.group(1)


def extract(car: Path, version: str, output: Path) -> tuple[Path, int]:
    """Извлечь каталог адаптера из .car в <output>/<версия>/; вернуть путь и число файлов."""
    target = output / version
    if target.exists():
        raise SystemExit(f"каталог версии уже есть: {target} (удалите его для переизвлечения)")
    count = 0
    with zipfile.ZipFile(car) as archive:
        members = [
            name
            for name in archive.namelist()
            if name.startswith(ADAPTER_PREFIX) and not name.endswith("/")
        ]
        if not members:
            raise SystemExit(f"в {car.name} нет каталога {ADAPTER_PREFIX}")
        for name in members:
            relative = name[len(ADAPTER_PREFIX):]
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(archive.read(name))
            count += 1
    return target, count


def update_index(output: Path, version: str) -> None:
    """Дописать версию в <output>/index.json и сделать её версией по умолчанию."""
    index = output / "index.json"
    data = {"available": [], "default": version}
    if index.exists():
        data = json.loads(index.read_text(encoding="utf-8"))
    if version not in data["available"]:
        data["available"].append(version)
    data["available"].sort()
    data["default"] = version
    index.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="извлечь debug-адаптер платформы 1С:Элемент из дистрибутива"
    )
    parser.add_argument("distro", help="путь к .car или к каталогу дистрибутива")
    parser.add_argument(
        "--output",
        default="adapter",
        help="каталог для adapter/<версия>/ и index.json (по умолчанию ./adapter)",
    )
    args = parser.parse_args(argv)

    car = find_car(Path(args.distro))
    version = detect_version(car)
    output = Path(args.output)
    target, count = extract(car, version, output)
    update_index(output, version)
    print(f"извлечено {count} файлов; adapterPath = {target}")
    print(f"index.json обновлён в {output} (default={version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
