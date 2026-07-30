"""The proxy side of the HTTP transport.

Why this file exists: a session had `HTTPS_PROXY=127.0.0.1:12334` in its environment, and every
call to a live internal stand died as a plain connection reset on `/console/sys/token`. urllib
honours the proxy - correctly - and the stand looked dead while it was running; two runs were
lost before anyone suspected the proxy. So a proxy that cannot possibly help is bypassed, one
that can is left alone, and a failure that went through a proxy says so.
"""

import urllib.error
import urllib.request

import pytest

from elemctl import transport
from elemctl.errors import TransportError
from elemctl.transport import UrllibTransport


@pytest.fixture(autouse=True)
def _no_switch(monkeypatch):
    monkeypatch.delenv(transport.NO_PROXY_ENV, raising=False)


@pytest.mark.parametrize("host", [
    "localhost", "127.0.0.1", "192.168.1.10", "10.0.0.5", "172.16.0.1",
    "stand.local", "build.lan", "[::1]",
])
def test_a_proxy_cannot_serve_these_hosts(host):
    assert transport.is_local_host(host)


@pytest.mark.parametrize("host", [
    "1cmycloud.com", "app.example.com", "8.8.8.8", "element.example.ru", "",
])
def test_everything_else_keeps_going_through_the_proxy(host):
    """A stand behind a corporate proxy has to be reached through it - the default stands."""
    assert not transport.is_local_host(host)


def _opener_of(url, monkeypatch, environ=None):
    monkeypatch.setattr(UrllibTransport, "_direct", None)
    for name, value in (environ or {}).items():
        monkeypatch.setenv(name, value)
    return UrllibTransport()._opener(url)


def test_a_public_host_uses_the_default_opener(monkeypatch):
    assert _opener_of("https://1cmycloud.com/console", monkeypatch) is urllib.request.urlopen


def test_a_loopback_host_goes_past_the_proxy(monkeypatch):
    assert _opener_of("http://127.0.0.1:8080/x", monkeypatch) is not urllib.request.urlopen


def test_the_switch_bypasses_the_proxy_everywhere(monkeypatch):
    opener = _opener_of("https://1cmycloud.com/console", monkeypatch,
                        {transport.NO_PROXY_ENV: "1"})
    assert opener is not urllib.request.urlopen


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_the_switch_off_changes_nothing(monkeypatch, value):
    opener = _opener_of("https://1cmycloud.com/console", monkeypatch,
                        {transport.NO_PROXY_ENV: value})
    assert opener is urllib.request.urlopen


def test_a_failure_through_a_proxy_names_it(monkeypatch):
    """The hint is the whole point of the entry: without it the message says only that the
    connection was reset, and the proxy is the last thing anyone suspects."""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12334")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.setattr(UrllibTransport, "_direct", None)

    def _boom(*_args, **_kwargs):
        raise ConnectionResetError(10054, "connection reset")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(TransportError) as failure:
        UrllibTransport().request("GET", "https://stand.example.ru/console/sys/token")
    assert "127.0.0.1:12334" in str(failure.value)
    assert transport.NO_PROXY_ENV in str(failure.value)


def test_a_failure_without_a_proxy_says_nothing_about_one(monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(UrllibTransport, "_direct", None)

    def _boom(*_args, **_kwargs):
        raise ConnectionResetError(10054, "connection reset")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(TransportError) as failure:
        UrllibTransport().request("GET", "https://stand.example.ru/console/sys/token")
    assert transport.NO_PROXY_ENV not in str(failure.value)
