"""Тесты локальной сборки: отбор файлов, манифест, состав архива, разбор архива."""

from __future__ import annotations

import re
import zipfile
from datetime import datetime, timezone

import pytest

from elemctl.build import (
    build_assembly,
    build_manifest,
    find_project_dir,
    inspect_assembly,
    read_project_meta,
)
from elemctl.errors import BuildError


def _fill_library(project_dir):
    """Наполнить библиотеку: подсистема, пакет внутри неё, глобальные и локальные типы.

    Подсистема.yaml намеренно не создаётся: у подсистемы библиотеки его может не быть
    (так устроены и реальные библиотеки поставщика платформы), поэтому состав
    определяется раскладкой каталогов, а не файлом-описанием.
    """
    subsystem = project_dir / "ОчередьСообщений"
    (subsystem / "Структуры").mkdir(parents=True)
    (subsystem / "ОчередьПрограммныйИнтерфейс.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИмя: ОчередьПрограммныйИнтерфейс\nОбластьВидимости: Глобально\n",
        encoding="utf-8",
    )
    (subsystem / "ОчередьСлужебный.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИмя: ОчередьСлужебный\nОбластьВидимости: ВПроекте\n",
        encoding="utf-8",
    )
    (subsystem / "Структуры" / "ОписаниеСообщения.yaml").write_text(
        "ВидЭлемента: Структура\nИмя: ОписаниеСообщения\nОбластьВидимости: Глобально\n",
        encoding="utf-8",
    )
    (subsystem / "Структуры" / "ОписаниеТокена.yaml").write_text(
        # Без ОбластьВидимости – умолчание ВПодсистеме, наружу тип не виден.
        "ВидЭлемента: Структура\nИмя: ОписаниеТокена\n",
        encoding="utf-8",
    )


def _fill_project(project_dir):
    """Наполнить проект типичными файлами, включая мусор для исключения."""
    (project_dir / "Основная").mkdir()
    (project_dir / "Основная" / "Справочник.yaml").write_text("Имя: Товары\n", encoding="utf-8")
    (project_dir / "Основная" / "Справочник.xbsl").write_text("// код\n", encoding="utf-8")
    (project_dir / "Ресурсы").mkdir()
    (project_dir / "Ресурсы" / "logo.png").write_bytes(b"\x89PNG fake")
    # Мусор, который в архив попасть не должен:
    (project_dir / "заметка.tmp").write_text("temp", encoding="utf-8")
    (project_dir / ".env").write_text("SECRET=1", encoding="utf-8")
    (project_dir / ".DS_Store").write_bytes(b"\x00")
    (project_dir / "старая сборка 1.0-1.xasm").write_bytes(b"PK")
    (project_dir / ".git").mkdir()
    (project_dir / ".git" / "HEAD").write_text("ref: refs/heads/master", encoding="utf-8")
    (project_dir / "__pycache__").mkdir()
    (project_dir / "__pycache__" / "кэш.json").write_text("{}", encoding="utf-8")
    (project_dir / "node_modules").mkdir()
    (project_dir / "node_modules" / "lib.js").write_text(";", encoding="utf-8")
    (project_dir / ".claude").mkdir()
    (project_dir / ".claude" / "settings.json").write_text("{}", encoding="utf-8")


def test_archive_composition_and_manifest(project_factory, tmp_path):
    project_dir = project_factory()
    _fill_project(project_dir)
    out_dir = tmp_path / "dist"

    result = build_assembly(project_dir, output_dir=out_dir, branch="master", commit="abc123")

    assert result.file.name == "crm 1.0-1.xasm"
    assert result.file.parent == out_dir

    with zipfile.ZipFile(result.file) as archive:
        names = set(archive.namelist())
        manifest = archive.read("Assembly.yaml").decode("utf-8")

    assert names == {
        "Assembly.yaml",
        "acme/crm/Проект.yaml",
        "acme/crm/Проект.xbsl",
        "acme/crm/Основная/Справочник.yaml",
        "acme/crm/Основная/Справочник.xbsl",
        "acme/crm/Ресурсы/logo.png",
    }
    # Разделители путей – только прямые слэши.
    assert not any("\\" in name for name in names)

    assert "ManifestVersion: 1.0" in manifest
    assert "ProjectKind: Application" in manifest
    assert "Vendor: acme" in manifest
    assert "Name: crm" in manifest
    assert "Version: 1.0-1" in manifest
    assert "BranchName: master" in manifest
    assert "CommitId: abc123" in manifest
    assert re.search(r"Created: \d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}", manifest)
    assert "Release:" not in manifest


def test_library_gets_release_line_and_xlib_extension(project_factory, tmp_path):
    project_dir = project_factory(name="lib1", kind="Библиотека")
    result = build_assembly(project_dir, output_dir=tmp_path / "dist", branch="", commit="")

    assert result.file.suffix == ".xlib"
    assert result.kind == "Library"
    with zipfile.ZipFile(result.file) as archive:
        manifest = archive.read("Assembly.yaml").decode("utf-8")
    assert "ProjectKind: Library" in manifest
    # Строка Release: (с пустым значением) – в конце манифеста.
    assert manifest.rstrip().splitlines()[-1] == "Release:"


def test_explicit_version_and_autoincrement(project_factory, tmp_path):
    project_dir = project_factory()
    explicit = build_assembly(
        project_dir, output_dir=tmp_path / "d1", version="1.0-99", branch="", commit=""
    )
    assert explicit.version == "1.0-99"
    assert explicit.file.name == "crm 1.0-99.xasm"

    incremented = build_assembly(
        project_dir, output_dir=tmp_path / "d2", last_build_version="1.0-41", branch="", commit=""
    )
    assert incremented.version == "1.0-42"


def test_kind_override(project_factory, tmp_path):
    project_dir = project_factory()
    result = build_assembly(
        project_dir, output_dir=tmp_path / "dist", kind="library", branch="", commit=""
    )
    assert result.file.suffix == ".xlib"


def test_created_is_utc_formatted(project_factory, tmp_path):
    project_dir = project_factory()
    moment = datetime(2026, 7, 9, 12, 34, 56, tzinfo=timezone.utc)
    result = build_assembly(
        project_dir, output_dir=tmp_path / "dist", now=moment, branch="", commit=""
    )
    with zipfile.ZipFile(result.file) as archive:
        manifest = archive.read("Assembly.yaml").decode("utf-8")
    assert "Created: 2026.07.09 12:34:56" in manifest


def test_find_project_dir_walks_deep(project_factory, tmp_path):
    project_dir = project_factory()
    repo_root = project_dir.parent.parent
    assert find_project_dir(repo_root) == project_dir
    # Каталог проекта сам по себе тоже находится.
    assert find_project_dir(project_dir) == project_dir


def test_missing_project_yaml_raises(tmp_path):
    empty = tmp_path / "пусто"
    empty.mkdir()
    with pytest.raises(BuildError):
        find_project_dir(empty)


def test_layout_scheme_enforced(tmp_path):
    # Имя каталога не совпадает с полем "Имя" – это нарушение схемы.
    project_dir = tmp_path / "repo" / "acme" / "другое-имя"
    project_dir.mkdir(parents=True)
    (project_dir / "Проект.yaml").write_text(
        "Имя: crm\nПоставщик: acme\nВерсия: 1.0\n", encoding="utf-8"
    )
    with pytest.raises(BuildError) as excinfo:
        read_project_meta(project_dir)
    assert "{repo}/{vendor}/{name}" in str(excinfo.value)


def test_manifest_field_order():
    manifest = build_manifest(
        kind="Application",
        vendor="acme",
        name="crm",
        version="1.0-7",
        created=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        branch="master",
        commit="deadbeef",
    )
    keys = [line.partition(":")[0] for line in manifest.strip().splitlines()]
    assert keys == [
        "ManifestVersion",
        "ProjectKind",
        "Vendor",
        "Name",
        "Version",
        "Created",
        "BranchName",
        "CommitId",
    ]


def test_inspect_library_archive(project_factory, tmp_path):
    project_dir = project_factory(kind="Библиотека", base_version="9.0")
    project_yaml = project_dir / "Проект.yaml"
    project_yaml.write_text(
        project_yaml.read_text(encoding="utf-8")
        + "Представление: Библиотека очереди сообщений\nРежимСовместимости: 9.0\n",
        encoding="utf-8",
    )
    _fill_library(project_dir)

    built = build_assembly(project_dir, output_dir=tmp_path / "dist", version="9.0.2")
    report = inspect_assembly(built.file)

    assert report["kind"] == "Library"
    assert (report["vendor"], report["name"], report["version"]) == ("acme", "crm", "9.0.2")
    assert report["representation"] == "Библиотека очереди сообщений"
    # Совместимость берётся из РежимСовместимости: свойства ВерсияТехнологии в Проект.yaml нет.
    assert report["compatibility"] == "9.0"

    assert report["subsystems"] == [
        {
            "name": "ОчередьСообщений",
            "qualified": "acme::crm::ОчередьСообщений",
            "packages": ["Структуры"],
            "global_types": 2,
        }
    ]
    # Наружу видны только Глобально, и полное имя включает сегмент пакета.
    assert [item["qualified"] for item in report["global_types"]] == [
        "acme::crm::ОчередьСообщений::ОчередьПрограммныйИнтерфейс",
        "acme::crm::ОчередьСообщений::Структуры::ОписаниеСообщения",
    ]
    assert [item["kind"] for item in report["global_types"]] == ["ОбщийМодуль", "Структура"]


def test_inspect_rejects_foreign_file(tmp_path):
    foreign = tmp_path / "заметка.txt"
    foreign.write_text("не архив", encoding="utf-8")
    with pytest.raises(BuildError) as excinfo:
        inspect_assembly(foreign)
    assert "не является архивом сборки" in str(excinfo.value)


def test_inspect_requires_manifest(tmp_path):
    archive_path = tmp_path / "без-манифеста.xlib"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("acme/crm/Проект.yaml", "Имя: crm\n")
    with pytest.raises(BuildError) as excinfo:
        inspect_assembly(archive_path)
    assert "Assembly.yaml" in str(excinfo.value)


def test_inspect_missing_file(tmp_path):
    with pytest.raises(BuildError):
        inspect_assembly(tmp_path / "нет-такого.xlib")
