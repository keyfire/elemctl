"""Тесты числового сравнения и автоинкремента версий сборок."""

from __future__ import annotations

from elemctl.versions import next_version, pick_latest, version_counter


def test_version_counter():
    assert version_counter("1.0-42") == 42
    assert version_counter("1.0-9") == 9
    assert version_counter("1.0") == 0
    assert version_counter("") == 0
    assert version_counter("1.0-abc") == 0


def test_numeric_comparison_not_lexicographic():
    # Лексикографически "1.0-9" > "1.0-10", числовое сравнение это исправляет.
    assemblies = [
        {"assembly-version": "1.0-9", "id": "old"},
        {"assembly-version": "1.0-10", "id": "new"},
        {"assembly-version": "1.0-2", "id": "older"},
    ]
    assert pick_latest(assemblies)["id"] == "new"


def test_pick_latest_empty():
    assert pick_latest([]) is None
    assert pick_latest(None) is None


def test_next_version_autoincrement():
    assert next_version("1.0", None) == "1.0-1"
    assert next_version("1.0", "") == "1.0-1"
    assert next_version("1.0", "1.0-41") == "1.0-42"
    assert next_version("2.5", "2.5-9") == "2.5-10"
