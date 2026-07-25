"""Safe update of an installed elemctl by unpacking the wheel.

The regular `pipx upgrade` / `pip install --upgrade` break the installation on Windows
when `elemctl.exe` or `python.exe` are held by a running MCP server (`elemctl mcp`): pip
cannot overwrite the entry point and rolls back, and the package disappears. This command
updates ONLY the package in site-packages (`.py` files are not locked, unlike `.exe`),
and the `elemctl.exe` stub calls the new code on its next run. Busy exe files are left
untouched.

The elemctl core has no external dependencies: the wheel is downloaded and unpacked with
the standard library (urllib + zipfile). Only the elemctl package itself is updated, not
its extras.
"""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

from . import __version__, i18n
from .errors import ElemctlError

PYPI_VERSION = "https://pypi.org/pypi/elemctl/{version}/json"
PYPI_LATEST = "https://pypi.org/pypi/elemctl/json"


def _site_packages() -> Path:
    """The directory the package is installed into (site-packages in a real installation)."""
    return Path(__file__).resolve().parent.parent


def _fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ElemctlError(i18n.t("selfupdate.version-not-found")) from error
        raise ElemctlError(i18n.t("selfupdate.pypi-http-error", status=error.code)) from error
    except OSError as error:
        raise ElemctlError(i18n.t("selfupdate.pypi-unreachable", error=error)) from error


def _wheel_url(version: str | None) -> tuple[str, str]:
    """The URL and the exact version of the py3-none-any wheel on PyPI (latest or the given one)."""
    data = _fetch_json(PYPI_VERSION.format(version=version) if version else PYPI_LATEST)
    resolved = data["info"]["version"]
    for entry in data["urls"]:
        if entry["filename"].endswith("-py3-none-any.whl"):
            return entry["url"], resolved
    raise ElemctlError(i18n.t("selfupdate.no-wheel", version=resolved))


def self_update(version: str | None = None, log=print) -> tuple[str, str]:
    """Update elemctl in site-packages by unpacking the wheel. Return (before, after)."""
    url, target = _wheel_url(version)
    if version is None and target == __version__:
        log(i18n.t("selfupdate.already-current", version=__version__))
        return __version__, __version__

    site = _site_packages()
    log(i18n.t("selfupdate.downloading", version=target))
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            blob = resp.read()
    except OSError as error:
        raise ElemctlError(i18n.t("selfupdate.download-failed", error=error)) from error

    # Remove the old package and its dist-info; the exe files in Scripts are left alone
    # (they may be held by an MCP server).
    for pattern in ("elemctl", "elemctl-*.dist-info"):
        for path in site.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    log(i18n.t("selfupdate.unpacking", path=site))
    with zipfile.ZipFile(BytesIO(blob)) as archive:
        archive.extractall(site)

    _update_pipx_metadata(site, target, log)
    log(i18n.t("selfupdate.done", before=__version__, after=target))
    return __version__, target


def _update_pipx_metadata(site: Path, version: str, log) -> None:
    """Fix package_version in pipx_metadata.json (otherwise pipx list shows the old version)."""
    meta = site.parent.parent / "pipx_metadata.json"  # <venv>/Lib/site-packages -> <venv>
    if not meta.is_file():
        return
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        main = data.get("main_package") or {}
        if main.get("package") == "elemctl":
            main["package_version"] = version
            meta.write_text(json.dumps(data, indent=4), encoding="utf-8")
            log(i18n.t("selfupdate.metadata-updated"))
    except (OSError, ValueError):
        pass
