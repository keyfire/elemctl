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

from .errors import BuildError
from .versions import next_version

PROJECT_FILE = "Проект.yaml"

# Расширения, попадающие в архив: исходники, изображения, веб-ресурсы.
ALLOWED_EXTENSIONS = {
    ".yaml", ".xbsl", ".xbql", ".md", ".txt", ".json",
    ".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".css", ".html", ".js", ".woff", ".woff2", ".ttf", ".eot",
}

# Каталоги, исключаемые целиком (плюс все скрытые – с точки в начале).
EXCLUDED_DIRS = {".git", ".claude", ".github", "__pycache__", "node_modules", ".venv"}

# Файлы, исключаемые по точному имени.
EXCLUDED_FILES = {".gitignore", ".env", ".DS_Store"}

# Файлы, исключаемые по расширению (готовые архивы сборок).
EXCLUDED_SUFFIXES = (".xasm", ".xlib")


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
    """Результат локальной сборки архива."""

    file: Path
    name: str
    vendor: str
    version: str
    kind: str
    branch: str
    commit: str
    files: list = field(default_factory=list)


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


def find_project_dir(start=None):
    """Найти каталог проекта: первый каталог с Проект.yaml вглубь от start."""
    base = Path(start) if start else Path.cwd()
    if (base / PROJECT_FILE).is_file():
        return base
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not _is_excluded_dir(d))
        if PROJECT_FILE in files:
            return Path(root)
    raise BuildError(f"каталог проекта не найден: нет {PROJECT_FILE} внутри {base}")


def read_project_meta(project_dir):
    """Прочитать метаданные проекта и проверить раскладку каталогов.

    Каталог проекта обязан лежать по схеме {repo}/{vendor}/{name}/Проект.yaml.
    """
    project_dir = Path(project_dir).resolve()
    project_file = project_dir / PROJECT_FILE
    if not project_file.is_file():
        raise BuildError(f"не найден {project_file}")
    values = parse_flat_yaml(project_file.read_text(encoding="utf-8-sig"))

    name = values.get("Имя", "").strip()
    vendor = values.get("Поставщик", "").strip()
    if not name or not vendor:
        raise BuildError(
            f'в {project_file} должны быть заполнены поля "Имя" и "Поставщик"'
        )
    if project_dir.name != name or project_dir.parent.name != vendor:
        raise BuildError(
            "каталог проекта обязан лежать по схеме {repo}/{vendor}/{name}/"
            + PROJECT_FILE
            + f": ожидался путь .../{vendor}/{name}, фактический – "
            + f"{project_dir.parent.name}/{project_dir.name}"
        )

    base_version = values.get("Версия", "").strip() or "1.0"
    kind = "Library" if values.get("ВидПроекта", "").strip() == "Библиотека" else "Application"
    return ProjectMeta(
        name=name,
        vendor=vendor,
        base_version=base_version,
        kind=kind,
        project_dir=project_dir,
        repo_root=project_dir.parent.parent,
    )


def collect_project_files(project_dir):
    """Отобрать файлы проекта для архива по правилам раздела 5 спецификации."""
    project_dir = Path(project_dir)
    selected = []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = sorted(d for d in dirs if not _is_excluded_dir(d))
        for file_name in sorted(files):
            if _is_excluded_file(file_name):
                continue
            if Path(file_name).suffix.lower() not in ALLOWED_EXTENSIONS:
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

    Версия: явная version, иначе автоинкремент от last_build_version,
    а без обеих – "{базовая версия}-1". branch и commit переопределяют
    git-метаданные (None – взять из git). kind переопределяет вид проекта
    ("application"/"library").
    """
    directory = find_project_dir(project_dir) if project_dir else find_project_dir()
    meta = read_project_meta(directory)

    project_kind = _normalize_kind(kind) or meta.kind
    build_version = version.strip() if version else next_version(
        meta.base_version, last_build_version or None
    )

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
    )


# -- внутреннее ---------------------------------------------------------------


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
    raise BuildError(f"неизвестный вид проекта: {kind} (ожидалось application или library)")


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
