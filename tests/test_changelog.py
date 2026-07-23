"""Сторож: текущая версия пакета описана в истории изменений.

elemctl.__version__ – единственный источник версии пакета (pyproject берёт её оттуда). Релиз
поднимает версию; в CHANGELOG должен появиться заголовок дня с этой версией, иначе релиз уедет
без записи о том, что в нём поменялось. Заголовки сгруппированы по дням, версии перечислены через
запятую ("## 2026-07-22 – 0.11.0"), поэтому сторож ищет версию как отдельный токен в любой
строке-заголовке "## ", а не привязывается к конкретному написанию.

CHANGELOG.md (+ .ru.md) зеркалится на сайт документации скриптом scripts/sync-docs.mjs, так что
сторож над источником держит честной и опубликованную страницу.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import elemctl

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("name", ["CHANGELOG.md", "CHANGELOG.ru.md"])
def test_version_is_described_in_changelog(name: str):
    version = elemctl.__version__
    headings = [
        line
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    token = re.compile(rf"(?<![\d.]){re.escape(version)}(?![\d.])")
    assert any(token.search(h) for h in headings), (
        f"{name}: версия {version} (elemctl.__version__) не встречается ни в одном заголовке "
        "'## ' – подняли версию, а история изменений о ней молчит"
    )
