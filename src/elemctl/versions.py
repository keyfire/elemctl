"""Версии сборок: числовое сравнение и автоинкремент.

Версия сборки имеет вид "{база}-{счётчик}", например "1.0-42". Сравнивать
версии нужно по числовому счётчику после последнего дефиса: "1.0-10" новее
"1.0-9", хотя лексикографически порядок обратный.
"""

from __future__ import annotations


def version_counter(version):
    """Числовой счётчик версии – суффикс после последнего дефиса.

    Для версии без дефиса или с нечисловым суффиксом возвращается 0.
    """
    text = str(version or "")
    head, sep, tail = text.rpartition("-")
    if not sep:
        return 0
    try:
        return int(tail)
    except ValueError:
        return 0


def next_version(base_version, last_version=None):
    """Следующая версия сборки: "{база}-{N+1}" от последней, иначе "{база}-1"."""
    base = (base_version or "1.0").strip()
    if not last_version:
        return f"{base}-1"
    return f"{base}-{version_counter(last_version) + 1}"


def pick_latest(assemblies, version_key="assembly-version"):
    """Выбрать из списка сборок последнюю по числовому счётчику версии."""
    best = None
    best_counter = -1
    for item in assemblies or []:
        if not isinstance(item, dict):
            continue
        counter = version_counter(item.get(version_key))
        if counter > best_counter:
            best = item
            best_counter = counter
    return best
