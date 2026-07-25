"""Общие заготовки тестов: транспорт-заглушка и синтетический проект.

Все тесты работают без сети – сетевой слой подменяется FakeTransport.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import pytest

from elemctl import i18n
from elemctl.client import ElementClient
from elemctl.config import Config
from elemctl.transport import HttpResponse

# Язык вывода закреплён за русским: проверки в остальных тестах сверяются с русским текстом
# сообщений, и без закрепления результат зависел бы от локали системы разработчика.
i18n.set_lang("ru")


@pytest.fixture(autouse=True)
def _pinned_language(monkeypatch):
    """Закрепить русский ПЕРЕД КАЖДЫМ тестом – однократного закрепления при импорте мало.

    Тест, зовущий cli.main без --lang, снимает закрепление (set_lang(None) возвращает порядок
    env / локаль), и все последующие сверки с русским текстом падали бы на английской локали.
    Закрепляем обоими путями: set_lang – явный выбор, ELEMCTL_LANG – фолбэк на случай снятия.
    Тесты i18n, проверяющие env и локаль, сами переопределяют или удаляют эту переменную.
    """
    monkeypatch.setenv("ELEMCTL_LANG", "ru")
    i18n.set_lang("ru")


@pytest.fixture(autouse=True)
def _no_ci_build_number(monkeypatch):
    """Вычистить CI-переменные с номером прогона ПЕРЕД КАЖДЫМ тестом.

    Версия сборки берёт суффикс из окружения CI, а сами тесты идут в GitHub
    Actions, где GITHUB_RUN_NUMBER установлена всегда: без зачистки версии в
    тестах сборки зависели бы от номера прогона – локально зелено, в CI нет.
    Тесты CI-суффикса ставят переменные явно.
    """
    from elemctl.build import CI_BUILD_NUMBER_VARS

    for var in CI_BUILD_NUMBER_VARS:
        monkeypatch.delenv(var, raising=False)


class FakeTransport:
    """Транспорт-заглушка: отвечает по таблице маршрутов и записывает вызовы.

    На каждый маршрут можно добавить несколько ответов – они выдаются по
    очереди, последний ответ повторяется.
    """

    def __init__(self):
        self.routes = {}
        self.calls = []

    def add(self, method, path, payload=None, status=200, body=None):
        if body is None:
            body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        entry = {"status": status, "body": body}
        self.routes.setdefault((method.upper(), path), []).append(entry)

    def request(self, method, url, *, headers=None, data=None, timeout=None):
        parts = urlsplit(url)
        self.calls.append(
            {
                "method": method.upper(),
                "path": parts.path,
                "query": parts.query,
                "headers": dict(headers or {}),
                "data": data,
            }
        )
        queue = self.routes.get((method.upper(), parts.path))
        if not queue:
            raise AssertionError(f"неожиданный запрос: {method} {parts.path}")
        entry = queue.pop(0) if len(queue) > 1 else queue[0]
        return HttpResponse(entry["status"], {}, entry["body"])

    def calls_to(self, method, path):
        return [c for c in self.calls if c["method"] == method.upper() and c["path"] == path]


@pytest.fixture
def api(tmp_path):
    """Клиент с транспортом-заглушкой; маршрут токена уже настроен."""
    transport = FakeTransport()
    transport.add("POST", "/console/sys/token", {"id_token": "TOKEN"})
    config = Config(
        base_url="https://api.test", client_id="cid", client_secret="secret", timeout=5.0
    )
    client = ElementClient(config, transport=transport, token_cache_dir=tmp_path / "token-cache")
    client._sleep = lambda seconds: None
    return client, transport


@pytest.fixture
def project_factory(tmp_path):
    """Фабрика синтетического проекта {repo}/{vendor}/{name}/Проект.yaml."""

    def make(vendor="acme", name="crm", *, kind=None, base_version="1.0", repo_name="repo"):
        project_dir = tmp_path / repo_name / vendor / name
        project_dir.mkdir(parents=True)
        lines = [f"Имя: {name}", f"Поставщик: {vendor}", f"Версия: {base_version}"]
        if kind:
            lines.append(f"ВидПроекта: {kind}")
        lines.extend(["Подсистемы:", "  - Основная"])
        (project_dir / "Проект.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (project_dir / "Проект.xbsl").write_text("// модуль проекта\n", encoding="utf-8")
        return project_dir

    return make
