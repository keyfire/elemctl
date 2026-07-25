"""Локальная сборка файла .xasm/.xlib из исходников проекта.

Файл сборки – ZIP-архив (deflate): в корне манифест Assembly.yaml, далее
файлы проекта путями {vendor}/{name}/... относительно корня репозитория
(раздел 5 спецификации). Разделители путей в архиве – прямые слэши.
"""

from __future__ import annotations

import os
import subprocess
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import i18n
from .errors import BuildError
from .versions import next_version

PROJECT_FILE = "Проект.yaml"
MANIFEST_FILE = "Assembly.yaml"
SUBSYSTEM_FILE = "Подсистема.yaml"

# Область видимости, при которой тип доступен подключившему библиотеку проекту.
GLOBAL_SCOPE = "Глобально"

# Расширения, попадающие в архив вне каталогов ресурсов: исходники,
# изображения, веб-ресурсы.
ALLOWED_EXTENSIONS = {
    ".yaml", ".xbsl", ".xbql", ".md", ".txt", ".json",
    ".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".css", ".htm", ".html", ".js", ".woff", ".woff2", ".ttf", ".eot",
}

# Каталог ресурсов подсистемы или пакета. Ресурс по документации платформы -
# произвольный файл, поэтому внутри таких каталогов отбора по расширению нет.
RESOURCES_DIR = "Ресурсы"

# Каталоги, исключаемые целиком (плюс все скрытые – с точки в начале).
EXCLUDED_DIRS = {".git", ".claude", ".github", "__pycache__", "node_modules", ".venv"}

# Файлы, исключаемые по точному имени.
EXCLUDED_FILES = {".gitignore", ".env", ".DS_Store"}

# Файлы, исключаемые по расширению (готовые архивы сборок).
EXCLUDED_SUFFIXES = (".xasm", ".xlib")

# Переменные окружения CI с номером прогона - источник суффикса версии сборки,
# когда ни явная версия, ни последняя сборка не заданы: каждый прогон CI идёт
# в чистом рабочем каталоге, и локальная нумерация всегда давала бы "-1".
CI_BUILD_NUMBER_VARS = ("CI_PIPELINE_IID", "GITHUB_RUN_NUMBER", "BUILD_NUMBER")


@dataclass
class ProjectMeta:
    """Метаданные проекта из Проект.yaml и раскладки каталогов."""

    name: str
    vendor: str
    base_version: str
    kind: str  # "Application" или "Library"
    project_dir: Path
    repo_root: Path


@dataclass
class BuildResult:
    """Результат локальной сборки архива.

    version_source – откуда взялась версия сборки: "flag" (задана явно),
    "last-build" (автоинкремент от последней сборки), имя переменной CI
    (номер прогона из окружения) либо "default". dirty_files – файлы с
    незакоммиченными изменениями в каталоге проекта; None, когда git
    недоступен или каталог не в репозитории.
    """

    file: Path
    name: str
    vendor: str
    version: str
    kind: str
    branch: str
    commit: str
    files: list = field(default_factory=list)
    version_source: str = ""
    dirty_files: list | None = None


def parse_flat_yaml(text):
    """Разобрать плоские пары "ключ: значение" верхнего уровня YAML.

    Вложенные строки (с отступом), пустые строки и комментарии пропускаются –
    для Проект.yaml этого достаточно.
    """
    values = {}
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line[:1] in (" ", "\t"):
            continue
        if ":" not in raw_line:
            continue
        key, _, value = raw_line.partition(":")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def descriptor_value(values, russian, english):
    """Значение свойства дескриптора по русскому либо английскому написанию.

    Двуязычие исходников - заявленная возможность платформы: дескриптор,
    записанный английскими ключами (Name, Vendor, Version...), применяется
    штатно, поэтому и читать его нужно в обоих написаниях.
    """
    for key in (russian, english):
        value = str(values.get(key, "") or "").strip()
        if value:
            return value
    return ""


def ci_build_number(environ=None):
    """Номер прогона CI из окружения: имя переменной и числовое значение.

    Переменные перебираются в порядке CI_BUILD_NUMBER_VARS; нечисловые
    значения пропускаются. Без номера возвращается пара пустых строк.
    """
    env = os.environ if environ is None else environ
    for var in CI_BUILD_NUMBER_VARS:
        value = str(env.get(var, "") or "").strip()
        if value.isdigit():
            return var, value
    return "", ""


def find_project_dir(start=None):
    """Найти каталог проекта: первый каталог с Проект.yaml вглубь от start."""
    base = Path(start) if start else Path.cwd()
    if (base / PROJECT_FILE).is_file():
        return base
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not _is_excluded_dir(d))
        if PROJECT_FILE in files:
            return Path(root)
    raise BuildError(i18n.t("build.project-dir-not-found", file=PROJECT_FILE, base=base))


def read_project_meta(project_dir):
    """Прочитать метаданные проекта и проверить раскладку каталогов.

    Каталог проекта обязан лежать по схеме {repo}/{vendor}/{name}/Проект.yaml.
    """
    project_dir = Path(project_dir).resolve()
    project_file = project_dir / PROJECT_FILE
    if not project_file.is_file():
        raise BuildError(i18n.t("build.not-found", file=project_file))
    values = parse_flat_yaml(project_file.read_text(encoding="utf-8-sig"))

    name = descriptor_value(values, "Имя", "Name")
    vendor = descriptor_value(values, "Поставщик", "Vendor")
    if not name or not vendor:
        raise BuildError(i18n.t("build.name-vendor-required", file=project_file))
    if project_dir.name != name or project_dir.parent.name != vendor:
        raise BuildError(i18n.t(
            "build.layout-mismatch",
            file=PROJECT_FILE,
            vendor=vendor,
            name=name,
            actual=f"{project_dir.parent.name}/{project_dir.name}",
        ))

    base_version = descriptor_value(values, "Версия", "Version") or "1.0"
    kind_value = descriptor_value(values, "ВидПроекта", "ProjectKind").lower()
    kind = "Library" if kind_value in ("библиотека", "library") else "Application"
    return ProjectMeta(
        name=name,
        vendor=vendor,
        base_version=base_version,
        kind=kind,
        project_dir=project_dir,
        repo_root=project_dir.parent.parent,
    )


def collect_project_files(project_dir):
    """Отобрать файлы проекта для архива по правилам раздела 5 спецификации.

    Вне каталогов ресурсов действует белый список расширений; внутри каталога
    `Ресурсы` (на любом уровне, включая его подкаталоги) включаются файлы любых
    расширений - ресурсом может быть произвольный файл: .pdf, .htm, .mxl и т.д.
    """
    project_dir = Path(project_dir)
    selected = []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = sorted(d for d in dirs if not _is_excluded_dir(d))
        in_resources = RESOURCES_DIR in Path(root).relative_to(project_dir).parts
        for file_name in sorted(files):
            if _is_excluded_file(file_name):
                continue
            if not in_resources and Path(file_name).suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            selected.append(Path(root) / file_name)
    return selected


def git_metadata(project_dir):
    """Хэш коммита и имя ветки git-репозитория с каталогом проекта.

    При недоступности git (нет команды, не репозиторий) – пустые строки.
    """
    commit = _git_output(project_dir, "rev-parse", "HEAD")
    branch = _git_output(project_dir, "rev-parse", "--abbrev-ref", "HEAD")
    return commit, branch


def git_dirty_files(project_dir):
    """Файлы с незакоммиченными изменениями в каталоге проекта.

    Сборка снимает диск в момент запуска, поэтому расхождение с HEAD должно
    быть видно вызывающему. Возвращается список путей из git status
    --porcelain, ограниченный каталогом; None – когда git недоступен или
    каталог не в репозитории (отличие от пустого списка "чисто").
    """
    try:
        # core.quotepath=false: иначе не-ASCII пути приходят октальными
        # escape-последовательностями в кавычках и предупреждение нечитаемо.
        completed = subprocess.run(
            ["git", "-C", str(project_dir), "-c", "core.quotepath=false",
             "status", "--porcelain", "--", "."],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return [line[3:] for line in completed.stdout.splitlines() if line.strip()]


def build_manifest(*, kind, vendor, name, version, created, branch="", commit=""):
    """Собрать текст манифеста Assembly.yaml."""
    lines = [
        "ManifestVersion: 1.0",
        f"ProjectKind: {kind}",
        f"Vendor: {vendor}",
        f"Name: {name}",
        f"Version: {version}",
        "Created: " + created.strftime("%Y.%m.%d %H:%M:%S"),
        f"BranchName: {branch}",
        f"CommitId: {commit}",
    ]
    if kind == "Library":
        lines.append("Release:")
    return "\n".join(lines) + "\n"


def build_assembly(
    project_dir=None,
    *,
    output_dir=None,
    version="",
    last_build_version="",
    branch=None,
    commit=None,
    kind="",
    now=None,
):
    """Собрать архив сборки из исходников проекта; вернуть BuildResult.

    Версия: явная version, иначе автоинкремент от last_build_version, иначе
    суффикс из номера прогона CI (переменные CI_BUILD_NUMBER_VARS), а без
    всего этого – "{базовая версия}-1". branch и commit переопределяют
    git-метаданные (None – взять из git). kind переопределяет вид проекта
    ("application"/"library").
    """
    directory = find_project_dir(project_dir) if project_dir else find_project_dir()
    meta = read_project_meta(directory)

    project_kind = _normalize_kind(kind) or meta.kind
    if version and version.strip():
        build_version = version.strip()
        version_source = "flag"
    elif last_build_version:
        build_version = next_version(meta.base_version, last_build_version)
        version_source = "last-build"
    else:
        ci_var, ci_number = ci_build_number()
        if ci_number:
            build_version = f"{meta.base_version}-{ci_number}"
            version_source = ci_var
        else:
            build_version = next_version(meta.base_version, None)
            version_source = "default"

    git_commit, git_branch = ("", "")
    if branch is None or commit is None:
        git_commit, git_branch = git_metadata(meta.project_dir)
    branch_name = git_branch if branch is None else branch
    commit_id = git_commit if commit is None else commit

    created = now or datetime.now(timezone.utc)
    manifest = build_manifest(
        kind=project_kind,
        vendor=meta.vendor,
        name=meta.name,
        version=build_version,
        created=created,
        branch=branch_name,
        commit=commit_id,
    )

    extension = ".xlib" if project_kind == "Library" else ".xasm"
    target_dir = Path(output_dir) if output_dir else Path.cwd()
    target_dir.mkdir(parents=True, exist_ok=True)
    archive_path = target_dir / f"{meta.name} {build_version}{extension}"

    files = collect_project_files(meta.project_dir)
    archive_names = []
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Assembly.yaml", manifest)
        for file_path in files:
            relative = file_path.relative_to(meta.project_dir)
            arc_name = "/".join((meta.vendor, meta.name) + relative.parts)
            archive.write(file_path, arcname=arc_name)
            archive_names.append(arc_name)

    return BuildResult(
        file=archive_path,
        name=meta.name,
        vendor=meta.vendor,
        version=build_version,
        kind=project_kind,
        branch=branch_name,
        commit=commit_id,
        files=archive_names,
        version_source=version_source,
        dirty_files=git_dirty_files(meta.project_dir),
    )


def read_assembly_manifest(path):
    """Манифест архива сборки (.xasm/.xlib) без разбора содержимого.

    Лёгкая операция для проверок перед загрузкой: читается только
    Assembly.yaml из корня архива.
    """
    archive_path = Path(path)
    if not archive_path.is_file():
        raise BuildError(i18n.t("build.not-found", file=archive_path))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if MANIFEST_FILE not in archive.namelist():
                raise BuildError(
                    i18n.t("build.no-manifest", file=archive_path, manifest=MANIFEST_FILE)
                )
            return parse_flat_yaml(_read_entry(archive, MANIFEST_FILE))
    except zipfile.BadZipFile:
        raise BuildError(i18n.t("build.not-archive", file=archive_path))


def inspect_assembly(path):
    """Разобрать готовый архив сборки (.xasm/.xlib) – обратная операция к build_assembly.

    Возвращает манифест, свойства проекта, его подсистемы и типы, доступные
    подключившему проекту (ОбластьВидимости: Глобально), – с полными именами.
    Пространство имён типа – {vendor}::{name}::{подсистема}[::{пакет}], где пакет –
    вложенный каталог подсистемы (файла-описания у пакета нет).
    """
    archive_path = Path(path)
    if not archive_path.is_file():
        raise BuildError(i18n.t("build.not-found", file=archive_path))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            if MANIFEST_FILE not in names:
                raise BuildError(
                    i18n.t("build.no-manifest", file=archive_path, manifest=MANIFEST_FILE)
                )
            manifest = parse_flat_yaml(_read_entry(archive, MANIFEST_FILE))
            vendor = manifest.get("Vendor", "").strip()
            name = manifest.get("Name", "").strip()
            prefix = f"{vendor}/{name}/"
            project_entry = prefix + PROJECT_FILE
            if project_entry not in names:
                raise BuildError(
                    i18n.t("build.no-project-file", file=archive_path, entry=project_entry)
                )
            project = parse_flat_yaml(_read_entry(archive, project_entry))
            elements = _archive_elements(archive, names, prefix)
    except zipfile.BadZipFile:
        raise BuildError(i18n.t("build.not-archive", file=archive_path))

    return {
        "file": str(archive_path),
        "manifest": manifest,
        "kind": manifest.get("ProjectKind", ""),
        "vendor": vendor,
        "name": name,
        "version": manifest.get("Version", ""),
        # ВерсияТехнологии в Проект.yaml не существует – совместимость задаёт
        # РежимСовместимости, именно его и сверяют с целевым проектом.
        "compatibility": descriptor_value(project, "РежимСовместимости", "CompatibilityMode"),
        "representation": descriptor_value(project, "Представление", "Presentation"),
        "project": project,
        "subsystems": _subsystems(elements, vendor, name),
        "global_types": [item for item in elements if item["scope"] == GLOBAL_SCOPE],
    }


# -- внутреннее ---------------------------------------------------------------


def _read_entry(archive, entry):
    return archive.read(entry).decode("utf-8-sig")


def _archive_elements(archive, names, prefix):
    """Элементы проекта в архиве: имя, вид, область видимости, полное имя."""
    vendor_name = prefix.rstrip("/").split("/")
    elements = []
    for entry in sorted(names):
        if not entry.startswith(prefix) or not entry.endswith(".yaml"):
            continue
        parts = entry[len(prefix):].split("/")
        if parts[-1] in (PROJECT_FILE, SUBSYSTEM_FILE) or len(parts) < 2:
            continue
        values = parse_flat_yaml(_read_entry(archive, entry))
        kind = values.get("ВидЭлемента", "")
        if not kind:
            continue
        # Каталоги между подсистемой и файлом – пакеты, каждый даёт сегмент имени.
        namespace = "::".join(vendor_name + parts[:-1])
        element_name = descriptor_value(values, "Имя", "Name") or parts[-1][: -len(".yaml")]
        elements.append({
            "name": element_name,
            "kind": kind,
            # Область видимости по умолчанию – ВПодсистеме, глобальная пишется явно.
            "scope": values.get("ОбластьВидимости", "ВПодсистеме"),
            "subsystem": parts[0],
            "namespace": namespace,
            "qualified": f"{namespace}::{element_name}",
            "entry": entry,
        })
    return elements


def _subsystems(elements, vendor, name):
    """Подсистемы проекта и их пакеты – по раскладке каталогов.

    Подсистема – каталог первого уровня; Подсистема.yaml необязателен (у библиотеки
    его может не быть вовсе), поэтому опираться на него нельзя.
    """
    found = {}
    for item in elements:
        subsystem = item["subsystem"]
        entry = found.setdefault(subsystem, {
            "name": subsystem,
            "qualified": f"{vendor}::{name}::{subsystem}",
            "packages": set(),
            "global_types": 0,
        })
        package = item["namespace"].split("::")[3:]
        if package:
            entry["packages"].add("::".join(package))
        if item["scope"] == GLOBAL_SCOPE:
            entry["global_types"] += 1
    result = []
    for subsystem in sorted(found):
        entry = found[subsystem]
        entry["packages"] = sorted(entry["packages"])
        result.append(entry)
    return result


def _is_excluded_dir(name):
    return name in EXCLUDED_DIRS or name.startswith(".")


def _is_excluded_file(name):
    if name in EXCLUDED_FILES:
        return True
    return name.lower().endswith(EXCLUDED_SUFFIXES)


def _normalize_kind(kind):
    value = (kind or "").strip().lower()
    if not value:
        return ""
    if value in ("library", "библиотека"):
        return "Library"
    if value in ("application", "приложение"):
        return "Application"
    raise BuildError(i18n.t("build.unknown-kind", kind=kind))


def _git_output(directory, *args):
    try:
        completed = subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()
