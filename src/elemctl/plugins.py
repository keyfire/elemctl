"""Точки расширения elemctl: внешние пакеты приносят debug-адаптер платформы.

Публичный elemctl не несёт проприетарные jar debug-адаптера 1С:Элемент. Внешний
пакет-плагин объявляет каталог адаптера через группу entry points
"elemctl.debug_adapter" – значение указывает либо на путь (Path/str), либо на
функцию без аргументов, возвращающую путь. Путь – это каталог, содержащий
подкаталог repo/ с jar-файлами адаптера (готовое значение xbslDebug.adapterPath
для расширения VS Code keyfire.xbsl-debug).

Объявление в pyproject.toml пакета-плагина:

    [project.entry-points."elemctl.debug_adapter"]
    имя-пакета = "мой_пакет:adapter_root"

Переменная окружения ELEMCTL_NO_PLUGINS=1 отключает обнаружение плагинов –
прогон только со штатными возможностями ядра.

Сбой загрузки точки расширения – это ошибка (PluginError), а не тихий пропуск:
инструмент, молча потерявший плагин, оставил бы пользователя без отладки и без
объяснения причины.
"""

from __future__ import annotations

import os
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path

from .errors import PluginError

DEBUG_ADAPTER_GROUP = "elemctl.debug_adapter"
ENV_DISABLE = "ELEMCTL_NO_PLUGINS"

# Главный класс Java-адаптера отладки платформы; расширение VS Code запускает его
# как stdio-DAP по classpath из каталога адаптера.
ADAPTER_MAIN_CLASS = "com.e1c.g5rt.debugger.adapter.App"

_FALSY = {"", "0", "false", "no"}


def disabled() -> bool:
    """Отключено ли обнаружение плагинов (ELEMCTL_NO_PLUGINS)."""
    return os.environ.get(ENV_DISABLE, "").strip().lower() not in _FALSY


def _points(group: str) -> list[EntryPoint]:
    if disabled():
        return []
    return sorted(entry_points(group=group), key=lambda ep: ep.name)


def _load(ep: EntryPoint):
    try:
        return ep.load()
    except Exception as exc:
        raise PluginError(
            f"точка расширения '{ep.name}' группы {ep.group} не загрузилась "
            f"({ep.value}): {exc}"
        ) from exc


def debug_adapter_paths() -> list[Path]:
    """Каталоги debug-адаптера, объявленные внешними пакетами (в порядке имени точки).

    Значение точки расширения – путь либо функция без аргументов, возвращающая путь.
    Валидность каталога (наличие jar адаптера) здесь не проверяется – это делает
    debug_adapter_path; полный список нужен для диагностики (команда plugins).
    """
    paths: list[Path] = []
    for ep in _points(DEBUG_ADAPTER_GROUP):
        target = _load(ep)
        if callable(target):
            target = target()
        paths.append(Path(target))
    return paths


def has_adapter_jars(path: Path) -> bool:
    """Есть ли в каталоге подкаталог repo/ с jar debug-адаптера платформы."""
    repo = path / "repo"
    if not repo.is_dir():
        return False
    return any(repo.glob("com.e1c.g5rt.debugger.adapter*.jar"))


def debug_adapter_path() -> Path | None:
    """Первый объявленный каталог адаптера с jar внутри; None, если плагина нет.

    Возвращаемый путь – готовое значение adapterPath для расширения VS Code:
    каталог, содержащий подкаталог repo/ с jar-файлами адаптера.
    """
    for path in debug_adapter_paths():
        if has_adapter_jars(path):
            return path
    return None
