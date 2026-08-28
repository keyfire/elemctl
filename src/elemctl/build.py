"""Local build of an .xasm/.xlib file from the project sources.

A build file is a ZIP archive (deflate): the Assembly.yaml manifest at the root,
then the project files under {vendor}/{name}/... paths relative to the repository
root (section 5 of the specification). Path separators inside the archive are
forward slashes.
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

# The platform accepts BOTH spellings of the service file names - its converter
# checks the pairs itself (Проект/Project, Подсистема/Subsystem). The Russian
# spelling stays canonical in messages naming a single file.
PROJECT_FILE = "Проект.yaml"
PROJECT_FILE_EN = "Project.yaml"
PROJECT_FILES = (PROJECT_FILE, PROJECT_FILE_EN)
MANIFEST_FILE = "Assembly.yaml"
SUBSYSTEM_FILE = "Подсистема.yaml"
SUBSYSTEM_FILE_EN = "Subsystem.yaml"
SUBSYSTEM_FILES = (SUBSYSTEM_FILE, SUBSYSTEM_FILE_EN)

# The visibility scope at which a type is available to the project that plugged
# the library in - both spellings, like everything else in a descriptor.
GLOBAL_SCOPES = ("Глобально", "Global")

# Extensions that go into the archive outside the resource directories: sources,
# images, web resources.
ALLOWED_EXTENSIONS = {
    ".yaml", ".xbsl", ".xbql", ".md", ".txt", ".json",
    ".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".css", ".htm", ".html", ".js", ".woff", ".woff2", ".ttf", ".eot",
}

# The resource directory of a subsystem or a package. By the platform documentation
# a resource is an arbitrary file, so inside such directories there is no selection
# by extension.
RESOURCES_DIR = "Ресурсы"

# Directories excluded entirely (plus every hidden one – starting with a dot).
EXCLUDED_DIRS = {".git", ".claude", ".github", "__pycache__", "node_modules", ".venv"}

# Files excluded by exact name.
EXCLUDED_FILES = {".gitignore", ".env", ".DS_Store"}

# Files excluded by extension (prebuilt build archives).
EXCLUDED_SUFFIXES = (".xasm", ".xlib")

# The CI environment variables carrying the run number – the source of the build
# version suffix when neither an explicit version nor a last build is given: every
# CI run happens in a clean working directory, so local numbering would always
# yield "-1".
CI_BUILD_NUMBER_VARS = ("CI_PIPELINE_IID", "GITHUB_RUN_NUMBER", "BUILD_NUMBER")


@dataclass
class ProjectMeta:
    """The project metadata from Проект.yaml/Project.yaml and from the directory layout."""

    name: str
    vendor: str
    base_version: str
    kind: str  # "Application" or "Library"
    project_dir: Path
    repo_root: Path
    project_file: Path = None  # the descriptor the metadata was read from


@dataclass(frozen=True)
class LibraryRef:
    """A library referenced by a project's Библиотеки/Libraries section."""

    name: str
    vendor: str


@dataclass
class BuildResult:
    """The result of a local archive build.

    version_source – where the build version came from: "flag" (set explicitly),
    "last-build" (auto-increment from the last build), the name of a CI variable
    (the run number from the environment) or "default". dirty_files – the files
    with uncommitted changes in the project directory; None when git is
    unavailable or the directory is not inside a repository.
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
    skipped_files: list = field(default_factory=list)


def parse_flat_yaml(text):
    """Parse the flat top-level "key: value" pairs of a YAML text.

    Nested lines (the indented ones), blank lines and comments are skipped –
    for Проект.yaml that is enough.
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


def parse_project_libraries(text):
    """Parse library references from Библиотеки/Libraries in Проект.yaml.

    elemctl deliberately has no YAML dependency. Project descriptors use a small,
    regular subset here: a top-level list whose items have Имя/Name and
    Поставщик/Vendor fields. Other nested sections and fields are ignored.
    """
    entries = []
    current = None
    section_indent = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" \t"))
        stripped = raw_line.strip()

        if section_indent is None:
            if indent != 0:
                continue
            key, value = _yaml_pair(stripped)
            if key not in ("Библиотеки", "Libraries"):
                continue
            if value and value != "[]":
                return []
            section_indent = indent
            continue

        if indent <= section_indent:
            break

        if stripped.startswith("-"):
            if current is not None:
                entries.append(current)
            current = {}
            stripped = stripped[1:].strip()
            if not stripped:
                continue

        if current is None:
            continue
        key, value = _yaml_pair(stripped)
        if key:
            current[key] = value

    if current is not None:
        entries.append(current)

    libraries = []
    for entry in entries:
        name = descriptor_value(entry, "Имя", "Name")
        vendor = descriptor_value(entry, "Поставщик", "Vendor")
        if name and vendor:
            libraries.append(LibraryRef(name=name, vendor=vendor))
    return libraries


def project_file_in(directory):
    """The project descriptor inside the directory, either spelling, or None."""
    for name in PROJECT_FILES:
        candidate = Path(directory) / name
        if candidate.is_file():
            return candidate
    return None


def descriptor_value(values, russian, english):
    """The value of a descriptor property by its Russian or English spelling.

    Bilingual sources are a declared feature of the platform: a descriptor
    written with English keys (Name, Vendor, Version...) is applied as usual,
    so it has to be read in both spellings too.
    """
    for key in (russian, english):
        value = str(values.get(key, "") or "").strip()
        if value:
            return value
    return ""


def local_project_dependencies(meta):
    """The root project and its locally available library dependencies.

    A missing local directory means the library is supplied externally by the
    platform and is therefore not an error. Dependencies of local libraries are
    followed too, so an application build is self-contained for the whole local
    dependency graph.
    """
    projects = [meta]
    seen = {(meta.vendor, meta.name)}
    index = 0
    while index < len(projects):
        project = projects[index]
        index += 1
        text = project.project_file.read_text(encoding="utf-8-sig")
        for library in parse_project_libraries(text):
            key = (library.vendor, library.name)
            if key in seen:
                continue
            candidate = meta.repo_root / library.vendor / library.name
            if project_file_in(candidate) is None:
                continue
            projects.append(read_project_meta(candidate))
            seen.add(key)
    return projects


def ci_build_number(environ=None):
    """The CI run number from the environment: the variable name and its numeric value.

    The variables are tried in the CI_BUILD_NUMBER_VARS order; non-numeric
    values are skipped. With no number a pair of empty strings is returned.
    """
    env = os.environ if environ is None else environ
    for var in CI_BUILD_NUMBER_VARS:
        value = str(env.get(var, "") or "").strip()
        if value.isdigit():
            return var, value
    return "", ""


def find_project_dir(start=None):
    """Find the project directory: the first one with Проект.yaml/Project.yaml downward from start."""
    base = Path(start) if start else Path.cwd()
    if project_file_in(base) is not None:
        return base
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not _is_excluded_dir(d))
        if any(name in files for name in PROJECT_FILES):
            return Path(root)
    raise BuildError(i18n.t(
        "build.project-dir-not-found", file="/".join(PROJECT_FILES), base=base
    ))


def read_project_meta(project_dir):
    """Read the project metadata and check the directory layout.

    The project directory must follow the {repo}/{vendor}/{name}/Проект.yaml
    layout; the descriptor may carry either spelling of its name.
    """
    project_dir = Path(project_dir).resolve()
    project_file = project_file_in(project_dir)
    if project_file is None:
        raise BuildError(i18n.t("build.not-found", file=project_dir / PROJECT_FILE))
    values = parse_flat_yaml(project_file.read_text(encoding="utf-8-sig"))

    name = descriptor_value(values, "Имя", "Name")
    vendor = descriptor_value(values, "Поставщик", "Vendor")
    if not name or not vendor:
        raise BuildError(i18n.t("build.name-vendor-required", file=project_file))
    if project_dir.name != name or project_dir.parent.name != vendor:
        raise BuildError(i18n.t(
            "build.layout-mismatch",
            file=project_file.name,
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
        project_file=project_file,
    )


def collect_project_files(project_dir):
    """Select the project files for the archive by the rules of specification section 5.

    Outside the resource directories an allowlist of extensions applies; inside a
    `Ресурсы` directory (at any level, including its subdirectories) files of any
    extension are taken – a resource may be an arbitrary file: .pdf, .htm, .mxl etc.
    """
    return collect_with_skipped(project_dir)[0]


def collect_with_skipped(project_dir):
    """The same selection plus what it left behind: (selected, skipped).

    skipped holds the files that lie in the project tree and did NOT get into the
    archive because of their extension - deliberately excluded ones (.gitignore,
    .env, prebuilt .xasm/.xlib) are not counted, they are meant to stay out. This
    is the "Неизвестный ресурс" failure seen from the build side: a resource kept
    OUTSIDE a `Ресурсы` directory with an extension nobody put on the allowlist
    silently misses the archive, and the platform only says so when applying.
    """
    project_dir = Path(project_dir)
    selected, skipped = [], []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = sorted(d for d in dirs if not _is_excluded_dir(d))
        in_resources = RESOURCES_DIR in Path(root).relative_to(project_dir).parts
        for file_name in sorted(files):
            path = Path(root) / file_name
            if _is_excluded_file(file_name):
                continue
            if not in_resources and Path(file_name).suffix.lower() not in ALLOWED_EXTENSIONS:
                skipped.append(path)
                continue
            selected.append(path)
    return selected, skipped


# Where the branch name comes from when the checkout is detached. A CI runner checks out
# the commit, not the branch, so git itself has nothing to answer - but the CI knows.
# GitLab fills CI_COMMIT_BRANCH on a branch pipeline only, and CI_COMMIT_REF_NAME on any.
_CI_BRANCH_VARIABLES = ("CI_COMMIT_BRANCH", "CI_COMMIT_REF_NAME", "GITHUB_REF_NAME")


def _detached_branch(environ=None):
    """The branch name from the CI environment, or "" when nothing names it."""
    source = os.environ if environ is None else environ
    for name in _CI_BRANCH_VARIABLES:
        value = (source.get(name) or "").strip()
        if value and value != "HEAD":
            return value
    return ""


def git_metadata(project_dir, environ=None):
    """The commit hash and the branch name of the git repository holding the project.

    When git is unavailable (no command, not a repository) – empty strings.

    A detached checkout is answered by the CI, not by git: `rev-parse --abbrev-ref HEAD`
    says the literal `HEAD` there, and that is what every assembly built on a runner used
    to record as its branch - the manifest field exists to answer "where is this build
    from", and `HEAD` answers nothing. When the environment does not name a branch either,
    the field is left EMPTY: an honest blank beats a word that looks like a branch name.
    """
    commit = _git_output(project_dir, "rev-parse", "HEAD")
    branch = _git_output(project_dir, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        branch = _detached_branch(environ)
    return commit, branch


def git_dirty_files(project_dir):
    """The files with uncommitted changes in the project directory.

    A build captures the disk as it is at the moment it starts, so a divergence
    from HEAD has to be visible to the caller. Returned is the list of paths from
    git status --porcelain limited to the directory; None – when git is unavailable
    or the directory is not inside a repository (as opposed to an empty list,
    meaning "clean").
    """
    try:
        # core.quotepath=false: otherwise non-ASCII paths arrive as quoted octal
        # escape sequences and the warning is unreadable.
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
    """Compose the text of the Assembly.yaml manifest."""
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
    """Build the assembly archive from the project sources; return a BuildResult.

    The version: the explicit version, otherwise an auto-increment from
    last_build_version, otherwise a suffix taken from the CI run number (the
    CI_BUILD_NUMBER_VARS variables), and with none of that – "{base version}-1".
    branch and commit override the git metadata (None – take it from git). kind
    overrides the project kind ("application"/"library").
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

    projects = local_project_dependencies(meta) if project_kind == "Application" else [meta]
    archive_names = []
    skipped_names = []
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Assembly.yaml", manifest)
        for project in projects:
            files, skipped = collect_with_skipped(project.project_dir)
            for file_path in files:
                relative = file_path.relative_to(project.project_dir)
                arc_name = "/".join((project.vendor, project.name) + relative.parts)
                archive.write(file_path, arcname=arc_name)
                archive_names.append(arc_name)
            skipped_names.extend(
                _result_path(project, meta, path) for path in skipped
            )

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
        skipped_files=skipped_names,
    )


def read_assembly_manifest(path):
    """The manifest of a build archive (.xasm/.xlib) without parsing its contents.

    A light operation for the checks made before an upload: only Assembly.yaml
    is read from the archive root.
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


def read_assembly_project(path):
    """What the archive says about its PROJECT: vendor, name and presentation.

    The manifest carries the technical pair the platform recognizes a project by
    (vendor plus name), and the project descriptor inside the archive carries the
    presentation - the name a console shows. The two are different things: a
    project named `crm` is shown as "Acme CRM", and comparing one against
    the other calls every correct upload a mismatch.

    Light, like read_assembly_manifest: two entries are read, nothing is walked.
    The presentation is "" when the archive carries no descriptor - then there is
    nothing to compare and the caller must not invent one.
    """
    archive_path = Path(path)
    manifest = read_assembly_manifest(archive_path)
    vendor = (manifest.get("Vendor") or "").strip()
    name = (manifest.get("Name") or "").strip()
    presentation = ""
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        prefix = f"{vendor}/{name}/"
        entry = next((prefix + item for item in PROJECT_FILES if prefix + item in names), None)
        if entry is not None:
            descriptor = parse_flat_yaml(_read_entry(archive, entry))
            presentation = (
                descriptor_value(descriptor, "Представление", "Presentation") or ""
            ).strip()
    return {"vendor": vendor, "name": name, "presentation": presentation}


def inspect_assembly(path):
    """Inspect a prebuilt assembly archive (.xasm/.xlib) – the inverse of build_assembly.

    Returns the manifest, the project properties, its subsystems and the types
    available to the project that plugged it in (ОбластьВидимости: Глобально) –
    with their qualified names. The namespace of a type is
    {vendor}::{name}::{subsystem}[::{package}], where a package is a nested
    directory of a subsystem (a package has no descriptor file of its own).
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
            project_entry = next(
                (prefix + entry for entry in PROJECT_FILES if prefix + entry in names), None
            )
            if project_entry is None:
                raise BuildError(i18n.t(
                    "build.no-project-file",
                    file=archive_path,
                    entry=prefix + "/".join(PROJECT_FILES),
                ))
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
        # There is no ВерсияТехнологии in Проект.yaml – compatibility is set by
        # РежимСовместимости, and it is exactly what is matched against the target project.
        "compatibility": descriptor_value(project, "РежимСовместимости", "CompatibilityMode"),
        "representation": descriptor_value(project, "Представление", "Presentation"),
        "project": project,
        "subsystems": _subsystems(elements, vendor, name),
        "global_types": [item for item in elements if item["scope"] in GLOBAL_SCOPES],
    }


# -- internal -----------------------------------------------------------------


def _yaml_pair(text):
    """A key and an unquoted scalar value from one simple YAML line."""
    if ":" not in text:
        return "", ""
    key, _, value = text.partition(":")
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return key, value


def _result_path(project, root, path):
    """A diagnostic path, preserving the old root-project spelling."""
    relative = path.relative_to(project.project_dir).as_posix()
    if project.vendor == root.vendor and project.name == root.name:
        return relative
    return "/".join((project.vendor, project.name, relative))


def _read_entry(archive, entry):
    return archive.read(entry).decode("utf-8-sig")


def _archive_elements(archive, names, prefix):
    """The project elements in the archive: name, kind, visibility scope, qualified name."""
    vendor_name = prefix.rstrip("/").split("/")
    elements = []
    for entry in sorted(names):
        if not entry.startswith(prefix) or not entry.endswith(".yaml"):
            continue
        parts = entry[len(prefix):].split("/")
        if parts[-1] in PROJECT_FILES + SUBSYSTEM_FILES or len(parts) < 2:
            continue
        values = parse_flat_yaml(_read_entry(archive, entry))
        kind = descriptor_value(values, "ВидЭлемента", "ElementKind")
        if not kind:
            continue
        # The directories between the subsystem and the file are packages, each
        # one contributing a segment of the name.
        namespace = "::".join(vendor_name + parts[:-1])
        element_name = descriptor_value(values, "Имя", "Name") or parts[-1][: -len(".yaml")]
        # The default visibility scope is ВПодсистеме, the global one is written
        # explicitly; the spelling of the default follows the descriptor around it.
        scope = descriptor_value(values, "ОбластьВидимости", "VisibilityScope")
        if not scope:
            scope = "InSubsystem" if "ElementKind" in values else "ВПодсистеме"
        elements.append({
            "name": element_name,
            "kind": kind,
            "scope": scope,
            "subsystem": parts[0],
            "namespace": namespace,
            "qualified": f"{namespace}::{element_name}",
            "entry": entry,
        })
    return elements


def _subsystems(elements, vendor, name):
    """The project's subsystems and their packages – from the directory layout.

    A subsystem is a first-level directory; Подсистема.yaml is optional (a library
    may have none at all), so it cannot be relied upon.
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
        if item["scope"] in GLOBAL_SCOPES:
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
