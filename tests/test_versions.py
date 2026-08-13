"""Tests of numeric comparison and auto-increment of assembly versions."""

from __future__ import annotations

from elemctl.versions import newest_first, next_version, pick_latest, version_counter


def test_version_counter():
    assert version_counter("1.0-42") == 42
    assert version_counter("1.0-9") == 9
    assert version_counter("1.0") == 0
    assert version_counter("") == 0
    assert version_counter("1.0-abc") == 0


def test_numeric_comparison_not_lexicographic():
    # Lexicographically "1.0-9" > "1.0-10"; the numeric comparison puts that right.
    assemblies = [
        {"assembly-version": "1.0-9", "id": "old"},
        {"assembly-version": "1.0-10", "id": "new"},
        {"assembly-version": "1.0-2", "id": "older"},
    ]
    assert pick_latest(assemblies)["id"] == "new"


def test_pick_latest_empty():
    assert pick_latest([]) is None
    assert pick_latest(None) is None


def test_newest_first_orders_by_created_then_counter():
    """The created stamp decides; a card without one goes after the stamped ones,
    ordered by the numeric version counter alone. Non-dict items are dropped."""
    assemblies = [
        {"id": "old", "created": "2026-01-01T10:00:00.000Z", "assembly-version": "1.0-1"},
        {"id": "new", "created": "2026-03-01T10:00:00.000Z", "assembly-version": "1.0-3"},
        {"id": "mid", "created": "2026-02-01T10:00:00.000Z", "assembly-version": "1.0-2"},
        {"id": "stampless-late", "assembly-version": "1.0-9"},
        {"id": "stampless-early", "assembly-version": "1.0-4"},
        "not-a-card",
    ]
    assert [item["id"] for item in newest_first(assemblies)] == [
        "new", "mid", "old", "stampless-late", "stampless-early"
    ]


def test_newest_first_empty():
    assert newest_first([]) == []
    assert newest_first(None) == []


def test_next_version_autoincrement():
    assert next_version("1.0", None) == "1.0-1"
    assert next_version("1.0", "") == "1.0-1"
    assert next_version("1.0", "1.0-41") == "1.0-42"
    assert next_version("2.5", "2.5-9") == "2.5-10"
