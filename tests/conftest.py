"""Shared test scaffolding: a stub transport and a synthetic project.

Every test runs without the network - the network layer is replaced by FakeTransport.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import pytest

from elemctl import i18n
from elemctl.client import ElementClient
from elemctl.config import Config
from elemctl.transport import HttpResponse

# The output language is pinned to Russian: the checks in the other tests compare against the
# Russian message texts, and without pinning the result would depend on the locale of the
# developer's system.
i18n.set_lang("ru")


@pytest.fixture(autouse=True)
def _pinned_language(monkeypatch):
    """Pin Russian BEFORE EVERY test - pinning once at import time is not enough.

    A test that calls cli.main without --lang drops the pin (set_lang(None) restores the
    env / locale order), and every later comparison with Russian text would then fail on an
    English locale. We pin both ways: set_lang is the explicit choice, ELEMCTL_LANG is the
    fallback in case the pin is dropped. The i18n tests, which check env and the locale,
    override or delete this variable themselves.
    """
    monkeypatch.setenv("ELEMCTL_LANG", "ru")
    i18n.set_lang("ru")


@pytest.fixture(autouse=True)
def _no_ci_build_number(monkeypatch):
    """Clear the CI variables carrying the run number BEFORE EVERY test.

    The build version takes its suffix from the CI environment, and the tests
    themselves run in GitHub Actions, where GITHUB_RUN_NUMBER is always set:
    without clearing it the versions in the build tests would depend on the run
    number - green locally, failing in CI. The CI-suffix tests set the variables
    explicitly.
    """
    from elemctl.build import CI_BUILD_NUMBER_VARS

    for var in CI_BUILD_NUMBER_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _private_data_dir(monkeypatch, tmp_path_factory):
    """Point the local registry of uploads at a directory of its own BEFORE EVERY test.

    A deploy, a probe and an upload write down what they uploaded, and the listings read it
    back. Without this the suite would write into the developer's own registry and read
    whatever the developer had uploaded - green on one machine and red on the next. The
    registry tests set the variable themselves where they need to.
    """
    from elemctl.registry import DATA_DIR_ENV

    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path_factory.mktemp("elemctl-data")))


@pytest.fixture(autouse=True)
def _no_plugins(monkeypatch):
    """Turn plugin discovery off BEFORE EVERY test.

    The parser and the MCP server now pick up the commands of the plugins, so a
    plugin installed in the developer's environment would add subcommands and
    tools - the checks of the command tree and of the tool set would then depend
    on what happens to be installed. The plugin tests set the variable themselves.
    """
    from elemctl.plugins import ENV_DISABLE

    monkeypatch.setenv(ENV_DISABLE, "1")


class FakeTransport:
    """A stub transport: answers from a route table and records the calls.

    Several responses can be added for a single route - they are handed out in
    turn, and the last response repeats. An entry added with error= raises it
    instead of answering: that is how a connection that breaks off looks from
    the client, since the real transport turns it into TransportError.
    """

    def __init__(self):
        self.routes = {}
        self.calls = []

    def add(self, method, path, payload=None, status=200, body=None, error=None):
        if body is None:
            body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        entry = {"status": status, "body": body, "error": error}
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
        if entry["error"] is not None:
            raise entry["error"]
        return HttpResponse(entry["status"], {}, entry["body"])

    def calls_to(self, method, path):
        return [c for c in self.calls if c["method"] == method.upper() and c["path"] == path]


class UrlopenAnswer:
    """What urllib.request.urlopen hands back, for the tests of the real transport.

    An answer made with broken= raises it from read() instead of giving the body: that is
    how an answer looks when the connection drops halfway through it.
    """

    def __init__(self, body=b"", *, status=200, broken=None):
        self.status = status
        self.headers = {}
        self._body = body
        self._broken = broken

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        if self._broken is not None:
            raise self._broken
        return self._body

    def close(self):
        pass


@pytest.fixture
def api(tmp_path):
    """A client on the stub transport; the token route is already set up."""
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
    """A factory of a synthetic {repo}/{vendor}/{name}/Проект.yaml project."""

    def make(vendor="acme", name="crm", *, kind=None, base_version="1.0", repo_name="repo",
             presentation="", language=""):
        project_dir = tmp_path / repo_name / vendor / name
        project_dir.mkdir(parents=True)
        lines = [f"Имя: {name}", f"Поставщик: {vendor}", f"Версия: {base_version}"]
        if presentation:
            # The name a console shows - a different thing from the technical name above.
            lines.append(f'Представление: "{presentation}"')
        if language:
            lines.append(f"ЯзыкРазработки: {language}")
        if kind:
            lines.append(f"ВидПроекта: {kind}")
        lines.extend(["Подсистемы:", "  - Основная"])
        (project_dir / "Проект.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (project_dir / "Проект.xbsl").write_text("// модуль проекта\n", encoding="utf-8")
        return project_dir

    return make
