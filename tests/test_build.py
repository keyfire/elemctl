"""Local build tests: file selection, the manifest, the archive contents, archive inspection."""

from __future__ import annotations

import re
import zipfile
from datetime import datetime, timezone

import pytest

from elemctl.build import (
    build_assembly,
    build_manifest,
    collect_with_skipped,
    find_project_dir,
    git_metadata,
    inspect_assembly,
    parse_project_libraries,
    read_project_meta,
)
from elemctl.errors import BuildError


def _fill_library(project_dir):
    """Fill the library: a subsystem, a package inside it, global and local types.

    Подсистема.yaml is deliberately not created: a library subsystem may have none
    (that is how the real libraries of the platform vendor are built), so the contents
    are determined by the directory layout rather than by a descriptor file.
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
        # Without ОбластьВидимости – the default is ВПодсистеме, the type is not visible outside.
        "ВидЭлемента: Структура\nИмя: ОписаниеТокена\n",
        encoding="utf-8",
    )


def _fill_project(project_dir):
    """Fill the project with typical files, including the junk that has to be excluded."""
    (project_dir / "Основная").mkdir()
    (project_dir / "Основная" / "Справочник.yaml").write_text("Имя: Товары\n", encoding="utf-8")
    (project_dir / "Основная" / "Справочник.xbsl").write_text("// код\n", encoding="utf-8")
    (project_dir / "Ресурсы").mkdir()
    (project_dir / "Ресурсы" / "logo.png").write_bytes(b"\x89PNG fake")
    # A resource is an arbitrary file: extensions outside the whitelist are included as well.
    (project_dir / "Ресурсы" / "Политика.pdf").write_bytes(b"%PDF fake")
    (project_dir / "Ресурсы" / "СчётНаОплату.mxl").write_bytes(b"MXL fake")
    (project_dir / "Ресурсы" / "Шаблоны").mkdir()
    (project_dir / "Ресурсы" / "Шаблоны" / "Письмо.htm").write_text(
        "<html/>", encoding="utf-8"
    )
    # A resource directory also occurs at the nested levels (inside a package).
    (project_dir / "Основная" / "Ресурсы").mkdir()
    (project_dir / "Основная" / "Ресурсы" / "Шаблон.docx").write_bytes(b"DOCX fake")
    # The junk that must not get into the archive:
    (project_dir / "заметка.tmp").write_text("temp", encoding="utf-8")
    (project_dir / "протокол.pdf").write_bytes(b"%PDF fake")  # outside Ресурсы – the whitelist
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
    # Path separators – forward slashes only.
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


def test_application_includes_declared_local_libraries(project_factory, tmp_path):
    app = project_factory()
    app_yaml = app / "Проект.yaml"
    app_yaml.write_text(
        app_yaml.read_text(encoding="utf-8")
        + "Библиотеки:\n"
        + "    -\n"
        + "        Имя: standard-tools\n"
        + "        Поставщик: acme\n"
        + "        Версия: 1.0\n",
        encoding="utf-8",
    )
    library = project_factory(name="standard-tools", kind="Библиотека")
    (library / "Инструменты").mkdir()
    (library / "Инструменты" / "Сервис.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИмя: Сервис\n", encoding="utf-8"
    )
    (library / "Инструменты" / "НеизвестныйРесурс.pdf").write_bytes(b"%PDF")
    project_factory(name="unrelated", kind="Библиотека")

    result = build_assembly(app, output_dir=tmp_path / "dist", branch="", commit="")

    with zipfile.ZipFile(result.file) as archive:
        names = set(archive.namelist())
    assert "acme/crm/Проект.yaml" in names
    assert "acme/standard-tools/Проект.yaml" in names
    assert "acme/standard-tools/Инструменты/Сервис.yaml" in names
    assert "acme/unrelated/Проект.yaml" not in names
    assert result.skipped_files == [
        "acme/standard-tools/Инструменты/НеизвестныйРесурс.pdf"
    ]


def test_application_includes_transitive_local_library(project_factory, tmp_path):
    app = project_factory()
    app_yaml = app / "Проект.yaml"
    app_yaml.write_text(
        app_yaml.read_text(encoding="utf-8")
        + "Libraries:\n"
        + "  - Name: standard-tools\n"
        + "    Vendor: acme\n"
        + "    Version: 1.0\n",
        encoding="utf-8",
    )
    library = project_factory(name="standard-tools", kind="Библиотека")
    library_yaml = library / "Проект.yaml"
    library_yaml.write_text(
        library_yaml.read_text(encoding="utf-8")
        + "Библиотеки:\n"
        + "  - Имя: shared-kernel\n"
        + "    Поставщик: globex\n"
        + "    Версия: 1.0\n",
        encoding="utf-8",
    )
    project_factory(vendor="globex", name="shared-kernel", kind="Библиотека")

    result = build_assembly(app, output_dir=tmp_path / "dist", branch="", commit="")

    with zipfile.ZipFile(result.file) as archive:
        names = set(archive.namelist())
    assert "acme/standard-tools/Проект.yaml" in names
    assert "globex/shared-kernel/Проект.yaml" in names


def test_missing_local_library_is_left_for_the_platform(project_factory, tmp_path):
    app = project_factory()
    app_yaml = app / "Проект.yaml"
    app_yaml.write_text(
        app_yaml.read_text(encoding="utf-8")
        + "Библиотеки:\n"
        + "  - Имя: published-library\n"
        + "    Поставщик: globex\n"
        + "    Версия: 2.0\n",
        encoding="utf-8",
    )

    result = build_assembly(app, output_dir=tmp_path / "dist", branch="", commit="")

    with zipfile.ZipFile(result.file) as archive:
        names = set(archive.namelist())
    assert "acme/crm/Проект.yaml" in names
    assert not any(name.startswith("globex/published-library/") for name in names)


def test_parse_project_libraries_supports_both_descriptor_languages():
    libraries = parse_project_libraries(
        "Имя: crm\n"
        "Библиотеки:\n"
        "    -\n"
        "        Имя: tools\n"
        "        Поставщик: acme\n"
        "    - Name: mail\n"
        "      Vendor: globex\n"
        "Подсистемы:\n"
        "    - Main\n"
    )

    assert [(item.vendor, item.name) for item in libraries] == [
        ("acme", "tools"),
        ("globex", "mail"),
    ]


def test_library_gets_release_line_and_xlib_extension(project_factory, tmp_path):
    project_dir = project_factory(name="lib1", kind="Библиотека")
    result = build_assembly(project_dir, output_dir=tmp_path / "dist", branch="", commit="")

    assert result.file.suffix == ".xlib"
    assert result.kind == "Library"
    with zipfile.ZipFile(result.file) as archive:
        manifest = archive.read("Assembly.yaml").decode("utf-8")
    assert "ProjectKind: Library" in manifest
    # The Release: line (with an empty value) – at the end of the manifest.
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
    # The project directory itself is found too.
    assert find_project_dir(project_dir) == project_dir


def test_missing_project_yaml_raises(tmp_path):
    empty = tmp_path / "пусто"
    empty.mkdir()
    with pytest.raises(BuildError):
        find_project_dir(empty)


def test_layout_scheme_enforced(tmp_path):
    # The directory name does not match the "Имя" field – that breaks the layout scheme.
    project_dir = tmp_path / "repo" / "acme" / "другое-имя"
    project_dir.mkdir(parents=True)
    (project_dir / "Проект.yaml").write_text(
        "Имя: crm\nПоставщик: acme\nВерсия: 1.0\n", encoding="utf-8"
    )
    with pytest.raises(BuildError) as excinfo:
        read_project_meta(project_dir)
    # The substitutions are checked, not the message template: the text is localized.
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
    # Compatibility comes from РежимСовместимости: Проект.yaml has no ВерсияТехнологии property.
    assert report["compatibility"] == "9.0"

    assert report["subsystems"] == [
        {
            "name": "ОчередьСообщений",
            "qualified": "acme::crm::ОчередьСообщений",
            "packages": ["Структуры"],
            "global_types": 2,
        }
    ]
    # Only the Глобально ones are visible outside, and the qualified name includes the package.
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


# -- the version from the CI environment -----------------------------------------


def test_ci_build_number_order_and_digits_only():
    from elemctl.build import ci_build_number

    # The probing order is fixed; non-numeric values are skipped.
    var, number = ci_build_number({"BUILD_NUMBER": "5", "CI_PIPELINE_IID": "9"})
    assert (var, number) == ("CI_PIPELINE_IID", "9")
    var, number = ci_build_number({"CI_PIPELINE_IID": "9a", "GITHUB_RUN_NUMBER": "12"})
    assert (var, number) == ("GITHUB_RUN_NUMBER", "12")
    assert ci_build_number({"CI_PIPELINE_IID": ""}) == ("", "")
    assert ci_build_number({}) == ("", "")


def test_build_version_from_ci_environment(project_factory, tmp_path, monkeypatch):
    """With no explicit version and no last build the suffix comes from the CI run number."""
    monkeypatch.setenv("CI_PIPELINE_IID", "137")
    result = build_assembly(project_factory(), output_dir=tmp_path / "out")
    assert result.version == "1.0-137"
    assert result.version_source == "CI_PIPELINE_IID"


def test_build_version_ci_environment_yields_to_flag_and_last_build(
    project_factory, tmp_path, monkeypatch
):
    """An explicit version and the auto-increment from the last build outrank the CI run number."""
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


# -- the English spellings of the descriptor --------------------------------------


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
    """A descriptor with English keys is read on a par with the Russian one.

    The platform applies such a project normally, while the build used to reject
    it, demanding that the "Имя" and "Поставщик" fields be filled in.
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
    """Russian Имя/Поставщик and an English Version: the version is not replaced by the default.

    The build used to silently get "1.0" instead of the declared one – the artifact
    name and the version drifted apart from the project.
    """
    project_dir = tmp_path / "repo-mixed" / "acme" / "crm"
    project_dir.mkdir(parents=True)
    (project_dir / "Проект.yaml").write_text(
        "Имя: crm\nПоставщик: acme\nVersion: 1.0.0\n", encoding="utf-8"
    )
    meta = read_project_meta(project_dir)
    assert meta.base_version == "1.0.0"


def test_build_english_project_end_to_end(tmp_path):
    """An English descriptor builds: the manifest carries the project's Name/Vendor/Version."""
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


# -- uncommitted changes of the project directory ---------------------------------


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


def test_a_resource_outside_the_resources_directory_is_reported_as_skipped(project_factory):
    """The "Неизвестный ресурс" failure seen from the build side.

    A file with an extension outside the allowlist only gets into the archive when
    it lies in a `Ресурсы` directory. Kept anywhere else it silently misses the
    archive, and the platform says so only when applying - so the build names it.
    """
    project_dir = project_factory()
    (project_dir / "Ресурсы").mkdir()
    (project_dir / "Ресурсы" / "договор.pdf").write_bytes(b"%PDF-1.4")
    (project_dir / "Документы").mkdir()
    (project_dir / "Документы" / "прайс.pdf").write_bytes(b"%PDF-1.4")

    selected, skipped = collect_with_skipped(project_dir)

    names = {path.name for path in selected}
    assert "договор.pdf" in names  # inside Ресурсы any extension is taken
    assert [path.name for path in skipped] == ["прайс.pdf"]


def test_deliberately_excluded_files_are_not_reported_as_skipped(project_factory):
    """.gitignore, .env and prebuilt archives are meant to stay out - they are not a loss."""
    project_dir = project_factory()
    (project_dir / ".gitignore").write_text("dist\n", encoding="utf-8")
    (project_dir / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (project_dir / "crm 1.0-1.xasm").write_bytes(b"PK\x03\x04")

    _, skipped = collect_with_skipped(project_dir)

    assert skipped == []


def test_build_result_carries_the_skipped_files(project_factory, tmp_path):
    project_dir = project_factory()
    (project_dir / "Документы").mkdir()
    (project_dir / "Документы" / "прайс.pdf").write_bytes(b"%PDF-1.4")

    result = build_assembly(project_dir, output_dir=tmp_path / "dist", version="1.0-1")

    assert result.skipped_files == ["Документы/прайс.pdf"]


# --- the branch of a detached checkout (a CI runner) ---------------------------------------


def _repository(project_dir, *, detach=False):
    """A real git repository around the project - the metadata is read from git itself."""
    import subprocess

    root = project_dir.parents[1]
    run = lambda *args: subprocess.run(  # noqa: E731 - a local shorthand, three lines below
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    run("init", "-b", "master")
    run("config", "user.email", "build@example.test")
    run("config", "user.name", "Build")
    run("add", "-A")
    run("commit", "-m", "project")
    if detach:
        head = run("rev-parse", "HEAD").stdout.strip()
        run("checkout", "--detach", head)
    return root


def test_branch_of_a_normal_checkout_is_the_branch(project_factory):
    project_dir = project_factory()
    _repository(project_dir)
    commit, branch = git_metadata(project_dir, environ={})
    assert branch == "master" and len(commit) == 40


def test_detached_checkout_takes_the_branch_from_the_ci(project_factory):
    """A runner checks out the commit, so git answers the literal `HEAD` - useless in a manifest."""
    project_dir = project_factory()
    _repository(project_dir, detach=True)

    _, branch = git_metadata(project_dir, environ={"CI_COMMIT_BRANCH": "master"})
    assert branch == "master"
    # A tag pipeline fills only CI_COMMIT_REF_NAME.
    _, branch = git_metadata(project_dir, environ={"CI_COMMIT_REF_NAME": "v1.2.3"})
    assert branch == "v1.2.3"
    _, branch = git_metadata(project_dir, environ={"GITHUB_REF_NAME": "main"})
    assert branch == "main"


def test_a_ci_variable_saying_head_is_not_a_branch_name(project_factory):
    """`HEAD` is the very word this fix removes - taking it from the environment repeats it."""
    project_dir = project_factory()
    _repository(project_dir, detach=True)

    _, branch = git_metadata(project_dir, environ={"CI_COMMIT_REF_NAME": "HEAD"})
    assert branch == ""


def test_detached_checkout_without_a_ci_leaves_the_branch_empty(project_factory):
    """Пустое поле честнее слова, похожего на имя ветки."""
    project_dir = project_factory()
    _repository(project_dir, detach=True)

    commit, branch = git_metadata(project_dir, environ={})
    assert branch == "" and len(commit) == 40


def test_manifest_of_a_detached_build_carries_no_head(project_factory, tmp_path):
    """Сквозь сборку: в Assembly.yaml не должно быть строки `Branch: HEAD`."""
    project_dir = project_factory()
    _repository(project_dir, detach=True)

    result = build_assembly(project_dir, output_dir=tmp_path / "dist", version="1.0-1")

    with zipfile.ZipFile(result.file) as archive:
        manifest = archive.read("Assembly.yaml").decode("utf-8")
    assert "BranchName: HEAD" not in manifest
    assert "BranchName:" in manifest  # поле на месте, просто пустое
    # Отрицательный контроль: имя ветки из окружения CI в манифест доходит.
    with_ci = build_assembly(
        project_dir, output_dir=tmp_path / "ci", version="1.0-2",
        **dict(zip(("commit", "branch"), git_metadata(project_dir, environ={"CI_COMMIT_BRANCH": "master"}))),
    )
    with zipfile.ZipFile(with_ci.file) as archive:
        assert "BranchName: master" in archive.read("Assembly.yaml").decode("utf-8")
