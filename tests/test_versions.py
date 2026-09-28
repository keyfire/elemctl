"""Tests of numeric comparison and auto-increment of assembly versions."""

from __future__ import annotations

from elemctl.versions import (
    highest_version,
    missing_counters,
    newest_first,
    next_version,
    pick_latest,
    server_may_keep,
    version_base,
    version_counter,
)


def test_the_highest_version_of_a_base_among_plain_strings():
    """The strings the registry keeps: another base and a tail that is not a number stay out."""
    versions = ["1.0-3", "1.0-10", "2.0-40", "1.0-probe-ab12cd34", "1.0", "", None, "1.0-9"]

    assert highest_version(versions, "1.0") == "1.0-10"
    assert highest_version(versions, "2.0") == "2.0-40"
    assert highest_version(versions, "3.0") == ""
    assert highest_version(None, "1.0") == ""


def test_the_server_keeps_only_a_number_of_the_project_base():
    """False is certain: the server numbers the upload by the Версия of the descriptor."""
    assert server_may_keep("1.0.0-7", "1.0.0")
    assert not server_may_keep("1.0.0-i1", "1.0.0")
    assert not server_may_keep("1.0.0", "1.0.0")
    assert not server_may_keep("1.0.1-7", "1.0.0")
    assert not server_may_keep("1.0.0-", "1.0.0")
    assert not server_may_keep("1.0.0-٧", "1.0.0")  # a digit, but not one the server counts


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


def test_version_base():
    assert version_base("1.0.2-7") == "1.0.2"
    assert version_base("1.0") == ""
    assert version_base("") == ""


def test_next_version_restarts_with_a_new_base():
    # The old base keeps its high counters; a bumped project starts from 1 again.
    assert next_version("1.0.2", "1.0.1-19023") == "1.0.2-1"
    assert next_version("1.0.2", "1.0.2-1") == "1.0.2-2"


def test_pick_latest_by_base():
    assemblies = [
        {"assembly-version": "1.0.1-19023", "id": "old-base"},
        {"assembly-version": "1.0.2-1", "id": "first"},
        {"assembly-version": "1.0.2-3", "id": "third"},
        {"assembly-version": "1.0.2-2", "id": "second"},
    ]
    assert pick_latest(assemblies, base_version="1.0.2")["id"] == "third"
    assert pick_latest(assemblies, base_version="1.0.3") is None
    assert pick_latest(assemblies)["id"] == "old-base"


def test_missing_counters_sees_a_hole_in_the_numbering():
    """The platform hands out the numbers of a base one after another; a hole is a deletion."""
    assemblies = [
        {"assembly-version": "1.0-1"},
        {"assembly-version": "1.0-2"},
        {"assembly-version": "1.0-5"},
    ]
    assert missing_counters(assemblies) == 2


def test_missing_counters_sees_a_base_whose_beginning_is_gone():
    """The numbering of a base starts at 1, so a listing that starts at 15 has lost fourteen."""
    assert missing_counters([{"assembly-version": "1.0.2-15"}]) == 14


def test_missing_counters_counts_every_base_apart():
    """A bumped project starts counting again - the bases say nothing about each other."""
    assemblies = [
        {"assembly-version": "1.0.1-1"},
        {"assembly-version": "1.0.1-2"},
        {"assembly-version": "1.0.2-1"},
        {"assembly-version": "1.0.2-3"},
    ]
    assert missing_counters(assemblies) == 1


def test_an_unbroken_listing_has_nothing_missing_however_long():
    """The case the retired threshold of thirty called a remnant on its length alone."""
    assert missing_counters([{"assembly-version": f"1.0-{n}"} for n in range(1, 41)]) == 0


def test_missing_counters_ignores_what_the_platform_did_not_number():
    """A version without a numeric tail says nothing either way and must not invent a gap."""
    assemblies = [
        {"assembly-version": "1.0-1"},
        {"assembly-version": "release"},
        {"assembly-version": None},
        "not-a-card",
    ]
    assert missing_counters(assemblies) == 0
    assert missing_counters([]) == 0
    assert missing_counters(None) == 0
