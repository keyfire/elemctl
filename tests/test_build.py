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
    # Ресурс – произвольный файл: расширения вне белого списка тоже включаются.
    (project_dir / "Ресурсы" / "Политика.pdf").write_bytes(b"%PDF fake")
    (project_dir / "Ресурсы" / "СчётНаОплату.mxl").write_bytes(b"MXL fake")
    (project_dir / "Ресурсы" / "Шаблоны").mkdir()
    (project_dir / "Ресурсы" / "Шаблоны" / "Письмо.htm").write_text(
        "<html/>", encoding="utf-8"
    )
    # Каталог ресурсов бывает и на вложенных уровнях (у пакета).
    (project_dir / "Основная" / "Ресурсы").mkdir()
    (project_dir / "Основная" / "Ресурсы" / "Шаблон.docx").write_bytes(b"DOCX fake")
    # Мусор, который в архив попасть не должен:
    (project_dir / "заметка.tmp").write_text("temp", encoding="utf-8")
    (project_dir / "протокол.pdf").write_bytes(b"%PDF fake")  # вне Ресурсы – белый список
    (project_dir / "Ресурсы" / ".env").write_text("SECRET=1", encoding="utf-8")
    (project_dir / "Ресурсы" / "сборка 1.0-2.xasm").write_bytes(b"PK")
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
        "acme/crm/Основная/Ресурсы/Шаблон.docx",
        "acme/crm/Ресурсы/logo.png",
        "acme/crm/Ресурсы/Политика.pdf",
        "acme/crm/Ресурсы/СчётНаОплату.mxl",
        "acme/crm/Ресурсы/Шаблоны/Письмо.htm",
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
    # Проверяются подстановки, а не строка схемы: текст локализуется.
    assert ".../acme/crm" in str(excinfo.value)
    assert "acme/другое-имя" in str(excinfo.value)


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


# -- версия из окружения CI ------------------------------------------------------


def test_ci_build_number_order_and_digits_only():
    from elemctl.build import ci_build_number

    # Порядок перебора фиксированный; нечисловые значения пропускаются.
    var, number = ci_build_number({"BUILD_NUMBER": "5", "CI_PIPELINE_IID": "9"})
    assert (var, number) == ("CI_PIPELINE_IID", "9")
    var, number = ci_build_number({"CI_PIPELINE_IID": "9a", "GITHUB_RUN_NUMBER": "12"})
    assert (var, number) == ("GITHUB_RUN_NUMBER", "12")
    assert ci_build_number({"CI_PIPELINE_IID": ""}) == ("", "")
    assert ci_build_number({}) == ("", "")


def test_build_version_from_ci_environment(project_factory, tmp_path, monkeypatch):
    """Без явной версии и последней сборки суффикс берётся из номера прогона CI."""
    monkeypatch.setenv("CI_PIPELINE_IID", "137")
    result = build_assembly(project_factory(), output_dir=tmp_path / "out")
    assert result.version == "1.0-137"
    assert result.version_source == "CI_PIPELINE_IID"


def test_build_version_ci_environment_yields_to_flag_and_last_build(
    project_factory, tmp_path, monkeypatch
):
    """Явная версия и автоинкремент от последней сборки старше номера прогона CI."""
    monkeypatch.setenv("CI_PIPELINE_IID", "137")
    project_dir = project_factory()
    explicit = build_assembly(project_dir, output_dir=tmp_path / "a", version="2.0-9")
    assert (explicit.version, explicit.version_source) == ("2.0-9", "flag")
    incremented = build_assembly(
        project_dir, output_dir=tmp_path / "b", last_build_version="1.0-41"
    )
    assert (incremented.version, incremented.version_source) == ("1.0-42", "last-build")


def test_build_version_default_without_ci(project_factory, tmp_path):
    result = build_assembly(project_factory(), output_dir=tmp_path / "out")
    assert result.version == "1.0-1"
    assert result.version_source == "default"


# -- английские написания дескриптора ---------------------------------------------


def _english_project(tmp_path, *, version_line="Version: 3.1", kind_line=""):
    project_dir = tmp_path / "repo-en" / "acme" / "crm"
    project_dir.mkdir(parents=True)
    lines = ["Name: crm", "Vendor: acme", version_line]
    if kind_line:
        lines.append(kind_line)
    (project_dir / "Проект.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (project_dir / "Проект.xbsl").write_text("// module\n", encoding="utf-8")
    return project_dir


def test_project_meta_english_keys(tmp_path):
    """Дескриптор с английскими ключами читается наравне с русским.

    Платформа применяет такой проект штатно, а сборка раньше отвечала
    'должны быть заполнены поля "Имя" и "Поставщик"'.
    """
    meta = read_project_meta(_english_project(tmp_path))
    assert (meta.name, meta.vendor, meta.base_version) == ("crm", "acme", "3.1")
    assert meta.kind == "Application"


def test_project_meta_english_library_kind(tmp_path):
    meta = read_project_meta(
        _english_project(tmp_path, kind_line="ProjectKind: Library")
    )
    assert meta.kind == "Library"


def test_project_meta_mixed_keys_version_not_lost(tmp_path):
    """Русские Имя/Поставщик и английский Version: версия не подменяется умолчанием.

    Раньше сборка молча получала "1.0" вместо заявленной – имя артефакта и
    версия разъезжались с проектом.
    """
    project_dir = tmp_path / "repo-mixed" / "acme" / "crm"
    project_dir.mkdir(parents=True)
    (project_dir / "Проект.yaml").write_text(
        "Имя: crm\nПоставщик: acme\nVersion: 1.0.0\n", encoding="utf-8"
    )
    meta = read_project_meta(project_dir)
    assert meta.base_version == "1.0.0"


def test_build_english_project_end_to_end(tmp_path):
    """Английский дескриптор собирается: манифест несёт Name/Vendor/Version проекта."""
    result = build_assembly(
        _english_project(tmp_path, kind_line="CompatibilityMode: 10.0"),
        output_dir=tmp_path / "out",
        version="3.1-7",
    )
    assert result.name == "crm" and result.vendor == "acme"
    report = inspect_assembly(result.file)
    assert report["manifest"]["Name"] == "crm"
    assert report["manifest"]["Vendor"] == "acme"
    assert report["version"] == "3.1-7"
    assert report["compatibility"] == "10.0"


# -- незакоммиченные изменения каталога проекта -----------------------------------


def test_git_dirty_files_outside_repository_is_none(project_factory, tmp_path):
    from elemctl.build import git_dirty_files

    assert git_dirty_files(project_factory()) is None


def test_build_result_dirty_files_in_repository(project_factory, tmp_path):
    import shutil
    import subprocess

    from elemctl.build import git_dirty_files

    if shutil.which("git") is None:
        pytest.skip("git недоступен")
    project_dir = project_factory()
    repo_root = project_dir.parent.parent
    subprocess.run(["git", "-C", str(repo_root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-qm", "init"],
        check=True,
    )

    assert git_dirty_files(project_dir) == []
    (project_dir / "Проект.xbsl").write_text("// правка\n", encoding="utf-8")
    dirty = git_dirty_files(project_dir)
    assert dirty is not None and len(dirty) == 1
    assert "Проект.xbsl" in dirty[0]

    result = build_assembly(project_dir, output_dir=tmp_path / "out", version="1.0-1")
    assert result.dirty_files == dirty
