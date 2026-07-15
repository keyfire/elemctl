"""Безопасное обновление установленного elemctl распаковкой колеса.

Штатные `pipx upgrade` / `pip install --upgrade` на Windows ломают установку, если
`elemctl.exe` или `python.exe` заняты работающим MCP-сервером (`elemctl mcp`): pip не
может перезаписать точку входа и откатывается, пакет пропадает. Эта команда обновляет
ТОЛЬКО пакет в site-packages (файлы `.py` не блокируются, в отличие от `.exe`), а стаб
`elemctl.exe` при следующем запуске вызовет уже новый код. Занятые exe не трогаются.

Ядро elemctl не имеет внешних зависимостей: качаем колесо и распаковываем стандартной
библиотекой (urllib + zipfile). Обновляется только сам пакет elemctl, не его extra.
"""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

from . import __version__
from .errors import ElemctlError

PYPI_VERSION = "https://pypi.org/pypi/elemctl/{version}/json"
PYPI_LATEST = "https://pypi.org/pypi/elemctl/json"


def _site_packages() -> Path:
    """Каталог, куда установлен пакет (site-packages в боевой установке)."""
    return Path(__file__).resolve().parent.parent


def _fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ElemctlError("версия не найдена на PyPI") from error
        raise ElemctlError(f"PyPI ответил {error.code}") from error
    except OSError as error:
        raise ElemctlError(f"не удалось обратиться к PyPI: {error}") from error


def _wheel_url(version: str | None) -> tuple[str, str]:
    """URL и точная версия колеса py3-none-any с PyPI (latest или указанной)."""
    data = _fetch_json(PYPI_VERSION.format(version=version) if version else PYPI_LATEST)
    resolved = data["info"]["version"]
    for entry in data["urls"]:
        if entry["filename"].endswith("-py3-none-any.whl"):
            return entry["url"], resolved
    raise ElemctlError(f"на PyPI нет wheel для elemctl {resolved}")


def self_update(version: str | None = None, log=print) -> tuple[str, str]:
    """Обновить elemctl в site-packages распаковкой колеса. Вернуть (было, стало)."""
    url, target = _wheel_url(version)
    if version is None and target == __version__:
        log(f"уже актуально: elemctl {__version__}")
        return __version__, __version__

    site = _site_packages()
    log(f"скачиваю elemctl {target} с PyPI...")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            blob = resp.read()
    except OSError as error:
        raise ElemctlError(f"не удалось скачать колесо: {error}") from error

    # Снести старый пакет и dist-info; exe в Scripts не трогаем (могут быть заняты MCP).
    for pattern in ("elemctl", "elemctl-*.dist-info"):
        for path in site.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    log(f"распаковываю в {site}...")
    with zipfile.ZipFile(BytesIO(blob)) as archive:
        archive.extractall(site)

    _update_pipx_metadata(site, target, log)
    log(f"готово: elemctl {__version__} -> {target}. Перезапустите MCP-сессии (elemctl mcp).")
    return __version__, target


def _update_pipx_metadata(site: Path, version: str, log) -> None:
    """Поправить package_version в pipx_metadata.json (иначе pipx list покажет старую версию)."""
    meta = site.parent.parent / "pipx_metadata.json"  # <venv>/Lib/site-packages -> <venv>
    if not meta.is_file():
        return
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        main = data.get("main_package") or {}
        if main.get("package") == "elemctl":
            main["package_version"] = version
            meta.write_text(json.dumps(data, indent=4), encoding="utf-8")
            log("обновлён pipx_metadata.json")
    except (OSError, ValueError):
        pass
