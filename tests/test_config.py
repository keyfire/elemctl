"""Configuration tests: .env parsing and the precedence of the sources."""

from __future__ import annotations

import codecs

import pytest

from elemctl.config import Config, parse_bool, parse_env_file
from elemctl.errors import ConfigError


def test_parse_env_file_rules(tmp_path):
    env_path = tmp_path / "test.env"
    env_path.write_text(
        "\n".join(
            [
                "# комментарий",
                "",
                "ELEMENT_BASE_URL=https://1cmycloud.com/",
                "export ELEMENT_CLIENT_ID=cid-123",
                "ELEMENT_CLIENT_SECRET=\"секрет в кавычках\"",
                "ELEMENT_APP_ID='одинарные'",
                "СТРОКА БЕЗ ЗНАКА РАВЕНСТВА",
            ]
        ),
        encoding="utf-8",
    )
    values = parse_env_file(env_path)
    assert values["ELEMENT_BASE_URL"] == "https://1cmycloud.com/"
    assert values["ELEMENT_CLIENT_ID"] == "cid-123"
    assert values["ELEMENT_CLIENT_SECRET"] == "секрет в кавычках"
    assert values["ELEMENT_APP_ID"] == "одинарные"
    assert "СТРОКА БЕЗ ЗНАКА РАВЕНСТВА" not in values


def test_parse_env_file_with_bom(tmp_path):
    env_path = tmp_path / "bom.env"
    content = "ELEMENT_BASE_URL=https://api.test\n"
    env_path.write_bytes(codecs.BOM_UTF8 + content.encode("utf-8"))
    values = parse_env_file(env_path)
    assert values["ELEMENT_BASE_URL"] == "https://api.test"


def test_priority_explicit_over_env_over_file(tmp_path):
    env_path = tmp_path / "prio.env"
    env_path.write_text(
        "ELEMENT_BASE_URL=https://file.test\n"
        "ELEMENT_CLIENT_ID=file-id\n"
        "ELEMENT_CLIENT_SECRET=file-secret\n",
        encoding="utf-8",
    )
    environ = {"ELEMENT_CLIENT_ID": "env-id"}
    config = Config.from_env(
        env_file=env_path, environ=environ, client_secret="explicit-secret"
    )
    # base_url is in the file only, client_id is overridden by the environment, the secret
    # by the explicit argument.
    assert config.base_url == "https://file.test"
    assert config.client_id == "env-id"
    assert config.client_secret == "explicit-secret"


def test_tls_configuration_from_env_and_file(tmp_path):
    env_path = tmp_path / "tls.env"
    env_path.write_text(
        "ELEMENT_TLS_VERIFY=false\n"
        "ELEMENT_TLS_STRICT=no\n"
        "ELEMENT_CA_FILE=internal-ca.pem\n",
        encoding="utf-8",
    )
    config = Config.from_env(env_file=env_path, environ={})
    assert config.tls_verify is False
    assert config.tls_strict is False
    assert config.ca_file == "internal-ca.pem"


@pytest.mark.parametrize("value", ["1", "true", "YES", "on", True])
def test_boolean_true_values(value):
    assert parse_bool(value, name="TEST") is True


@pytest.mark.parametrize("value", ["0", "false", "NO", "off", False])
def test_boolean_false_values(value):
    assert parse_bool(value, name="TEST") is False


def test_invalid_tls_boolean_is_a_configuration_error():
    with pytest.raises(ConfigError, match="ELEMENT_TLS_VERIFY"):
        Config.from_env(environ={"ELEMENT_TLS_VERIFY": "flase"})


def test_tls_defaults_are_safe():
    config = Config.from_env(environ={})
    assert config.tls_verify is True
    assert config.tls_strict is True


def test_default_env_file_in_cwd(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ELEMENT_APP_ID=from-dot-env\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    config = Config.from_env(environ={})
    assert config.app_id == "from-dot-env"


def test_base_url_trailing_slash_stripped():
    assert Config(base_url="https://api.test/").base_url == "https://api.test"
    config = Config.from_env(environ={"ELEMENT_BASE_URL": "https://api.test///"})
    assert config.base_url == "https://api.test"


@pytest.mark.parametrize("base_url", ["http://localhost:8080/console", "https://api.test/path"])
def test_base_url_allows_http_and_https_addresses(base_url):
    assert Config(base_url=base_url).base_url == base_url


@pytest.mark.parametrize("base_url", ["api.test", "ftp://api.test"])
def test_base_url_requires_an_http_scheme(base_url):
    with pytest.raises(ConfigError, match="http://.*https://"):
        Config(base_url=base_url)


def test_empty_base_url_is_allowed_until_connection_is_required():
    assert Config.from_env(environ={}).base_url == ""


def test_missing_env_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        Config.from_env(env_file=tmp_path / "нет-такого.env", environ={})


def test_missing_relative_env_file_names_the_absolute_path_and_cwd(tmp_path, monkeypatch):
    """A relative --env-file is resolved from the CURRENT directory, not from
    --project-dir; the message must show where the file was actually looked for,
    or the refusal reads as "the stand is unreachable" in a background run."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as excinfo:
        Config.from_env(env_file=".agent/local.env", environ={})
    message = str(excinfo.value)
    assert ".agent" in message
    assert str(tmp_path) in message  # both the resolved path and the cwd carry it


def test_require_reports_missing_variables(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # so that no stray .env is picked up
    config = Config.from_env(environ={"ELEMENT_BASE_URL": "https://api.test"})
    with pytest.raises(ConfigError) as excinfo:
        config.require()
    message = str(excinfo.value)
    assert "ELEMENT_CLIENT_ID" in message
    assert "ELEMENT_CLIENT_SECRET" in message
    assert "ELEMENT_BASE_URL" not in message


# -- ELEMCTL_NO_PROXY: the stand's own .env, not only the process environment ---------------


def test_no_proxy_defaults_to_false(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # so that no stray .env is picked up
    assert Config.from_env(environ={}).no_proxy is False


def test_no_proxy_sourced_from_the_env_file(tmp_path):
    """An MCP call reaches a local stand through env_file alone – there is no way for the
    caller to set a process variable for a single call – so the file has to carry the switch."""
    env_path = tmp_path / "local.env"
    env_path.write_text(
        "ELEMENT_BASE_URL=https://local.test\nELEMCTL_NO_PROXY=1\n", encoding="utf-8"
    )
    config = Config.from_env(env_file=env_path, environ={})
    assert config.no_proxy is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "FALSE", "NO"])
def test_no_proxy_false_spellings_in_the_file_do_not_enable_it(tmp_path, value):
    env_path = tmp_path / "local.env"
    env_path.write_text(f"ELEMCTL_NO_PROXY={value}\n", encoding="utf-8")
    config = Config.from_env(env_file=env_path, environ={})
    assert config.no_proxy is False


def test_no_proxy_process_variable_still_wins_over_the_file(tmp_path):
    """The process variable, when explicitly set, keeps working exactly as before – it is
    what a plain CLI call in a shell sets, and the file must not override it."""
    env_path = tmp_path / "local.env"
    env_path.write_text("ELEMCTL_NO_PROXY=1\n", encoding="utf-8")
    off = Config.from_env(env_file=env_path, environ={"ELEMCTL_NO_PROXY": "0"})
    assert off.no_proxy is False

    env_path.write_text("ELEMCTL_NO_PROXY=0\n", encoding="utf-8")
    on = Config.from_env(env_file=env_path, environ={"ELEMCTL_NO_PROXY": "1"})
    assert on.no_proxy is True


def test_no_proxy_of_two_environments_does_not_mix_in_one_process(tmp_path):
    """One MCP server process serves several stands by env_file in turn; the switch of the
    local one must not leak into a call that targets the cloud one right after it."""
    local_env = tmp_path / "local.env"
    local_env.write_text("ELEMCTL_NO_PROXY=1\n", encoding="utf-8")
    cloud_env = tmp_path / "cloud.env"
    cloud_env.write_text("ELEMENT_BASE_URL=https://cloud.example\n", encoding="utf-8")

    local = Config.from_env(env_file=local_env, environ={})
    cloud = Config.from_env(env_file=cloud_env, environ={})

    assert local.no_proxy is True
    assert cloud.no_proxy is False


def test_no_proxy_accepts_an_explicit_argument_like_every_other_field(tmp_path):
    """The docstring of from_env promises explicit argument > environment > file for every
    field. no_proxy was the one exception: the override was never popped out of **overrides,
    so it fell through to the "unknown configuration parameters" check at the end and
    from_env(no_proxy=...) raised TypeError instead of resolving - there are no callers doing
    that today, which is exactly how the gap went unnoticed."""
    env_path = tmp_path / "local.env"
    env_path.write_text("ELEMCTL_NO_PROXY=1\n", encoding="utf-8")

    off = Config.from_env(env_file=env_path, environ={"ELEMCTL_NO_PROXY": "1"}, no_proxy=False)
    assert off.no_proxy is False

    on_path = tmp_path / "on.env"
    on_path.write_text("ELEMCTL_NO_PROXY=0\n", encoding="utf-8")
    on = Config.from_env(env_file=on_path, environ={"ELEMCTL_NO_PROXY": "0"}, no_proxy=True)
    assert on.no_proxy is True
