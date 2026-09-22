"""The proxy side of the HTTP transport.

Why this file exists: a session had `HTTPS_PROXY=127.0.0.1:12334` in its environment, and every
call to a live internal stand died as a plain connection reset on `/console/sys/token`. urllib
honours the proxy - correctly - and the stand looked dead while it was running; two runs were
lost before anyone suspected the proxy. So a proxy that cannot possibly help is bypassed, one
that can is left alone, and a failure that went through a proxy says so.
"""

import http.client
import json
import ssl
import urllib.error
import urllib.request

import pytest

from elemctl import transport
from elemctl.client import ElementClient
from elemctl.config import Config
from elemctl.errors import ConfigError, ElemctlError, TransportError
from elemctl.transport import UrllibTransport
from tests.conftest import UrlopenAnswer


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


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("YES", True), ("on", True), ("anything-else", True),
    ("", False), ("0", False), ("false", False), ("NO", False),
])
def test_no_proxy_enabled_parses_permissively(value, expected):
    """The same lenient reading a typo must not lock a caller out of: only the four falsy
    spellings turn the switch off, everything else - including a typo - turns it on."""
    assert transport.no_proxy_enabled(value) is expected


def test_explicit_no_proxy_true_bypasses_regardless_of_the_process_variable(monkeypatch):
    """Config resolves ELEMCTL_NO_PROXY itself (process variable, then the stand's .env) and
    hands the transport the already-decided value - the transport must trust it as is."""
    monkeypatch.delenv(transport.NO_PROXY_ENV, raising=False)
    opener = UrllibTransport(no_proxy=True)._opener("https://1cmycloud.com/console")
    assert opener is not urllib.request.urlopen


def test_explicit_no_proxy_false_is_not_overridden_by_the_process_variable(monkeypatch):
    """A resolved False (the stand's .env says nothing, and this call's config carries that)
    must not be second-guessed by a process variable set for an unrelated call."""
    monkeypatch.setenv(transport.NO_PROXY_ENV, "1")
    opener = UrllibTransport(no_proxy=False)._opener("https://1cmycloud.com/console")
    assert opener is urllib.request.urlopen


def test_no_proxy_omitted_falls_back_to_the_process_variable_as_before(monkeypatch):
    """Direct construction without Config (a library caller, most of the existing tests here)
    must see exactly the old behaviour: the process variable alone decides."""
    monkeypatch.setenv(transport.NO_PROXY_ENV, "1")
    opener = UrllibTransport()._opener("https://1cmycloud.com/console")
    assert opener is not urllib.request.urlopen


def test_a_failure_through_a_proxy_names_it(monkeypatch):
    """The hint is the whole point of the entry: without it the message says only that the
    connection was reset, and the proxy is the last thing anyone suspects."""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12334")
    monkeypatch.delenv("NO_PROXY", raising=False)

    def _boom(*_args, **_kwargs):
        raise ConnectionResetError(10054, "connection reset")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(TransportError) as failure:
        UrllibTransport().request("GET", "https://stand.example.ru/console/sys/token")
    assert "127.0.0.1:12334" in str(failure.value)
    assert transport.NO_PROXY_ENV in str(failure.value)


def test_a_failure_going_direct_does_not_blame_the_proxy_it_bypassed(monkeypatch):
    """self._no_proxy means this transport went straight to the server - naming a proxy that
    was configured but never used would send a reader's search the wrong way."""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12334")
    monkeypatch.delenv("NO_PROXY", raising=False)

    def _boom(*_args, **_kwargs):
        raise ConnectionResetError(10054, "connection reset")

    client = UrllibTransport(no_proxy=True)
    client._direct = type("FakeOpener", (), {"open": staticmethod(_boom)})()
    with pytest.raises(TransportError) as failure:
        client.request("GET", "https://stand.example.ru/console/sys/token")
    assert "127.0.0.1:12334" not in str(failure.value)
    assert transport.NO_PROXY_ENV not in str(failure.value)


def test_a_failure_through_a_proxy_masks_its_credentials(monkeypatch):
    """The proxy address is diagnostic, the password in it is not - HTTPS_PROXY carrying
    user:pass@ must not turn a connection failure into a leak of that password."""
    monkeypatch.setenv("HTTPS_PROXY", "http://user:pass@proxy.example:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)

    def _boom(*_args, **_kwargs):
        raise ConnectionResetError(10054, "connection reset")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(TransportError) as failure:
        UrllibTransport().request("GET", "https://stand.example.ru/console/sys/token")
    message = str(failure.value)
    assert "proxy.example:3128" in message
    assert "user" not in message
    assert "pass" not in message


def test_a_failure_without_a_proxy_says_nothing_about_one(monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)

    def _boom(*_args, **_kwargs):
        raise ConnectionResetError(10054, "connection reset")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(TransportError) as failure:
        UrllibTransport().request("GET", "https://stand.example.ru/console/sys/token")
    assert transport.NO_PROXY_ENV not in str(failure.value)


def test_default_transport_verifies_certificates_and_hostnames():
    context = UrllibTransport().ssl_context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        assert context.verify_flags & ssl.VERIFY_X509_STRICT


def test_strict_can_be_relaxed_without_disabling_verification():
    context = UrllibTransport(tls_strict=False).ssl_context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        assert not context.verify_flags & ssl.VERIFY_X509_STRICT


def test_verification_can_be_explicitly_disabled():
    context = UrllibTransport(tls_verify=False).ssl_context
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


def test_verification_switched_off_says_so_on_stderr(capsys):
    """The point of the entry: a .env written once keeps the check off for months, and nothing
    about a call that skips verification looks different from a call that passed it."""
    UrllibTransport(tls_verify=False)
    streams = capsys.readouterr()
    assert "ELEMENT_TLS_VERIFY" in streams.err
    # stdout is the answer of the command - a warning there would end up inside piped JSON.
    assert streams.out == ""


def test_a_verifying_transport_keeps_quiet(capsys):
    UrllibTransport()
    UrllibTransport(tls_strict=False)
    streams = capsys.readouterr()
    assert (streams.out, streams.err) == ("", "")


def test_invalid_ca_file_is_a_configuration_error(tmp_path):
    missing = tmp_path / "missing-ca.pem"
    with pytest.raises(ConfigError, match="missing-ca.pem"):
        UrllibTransport(ca_file=str(missing))


def test_ca_file_is_added_to_the_default_trust_store(monkeypatch):
    loaded = []
    original = ssl.create_default_context

    def _context():
        context = original()
        original_load = context.load_verify_locations

        def _load(*, cafile=None, capath=None, cadata=None):
            loaded.append(cafile)
            return original_load(cafile=cafile, capath=capath, cadata=cadata)

        # SSLContext methods are read-only, so return a small forwarding wrapper.
        class Context:
            def __getattr__(self, name):
                return _load if name == "load_verify_locations" else getattr(context, name)

            def __setattr__(self, name, value):
                setattr(context, name, value)

        return Context()

    monkeypatch.setattr(ssl, "create_default_context", _context)
    # The missing file still proves which path was handed to the context before it raises.
    with pytest.raises(ConfigError):
        UrllibTransport(ca_file="company-ca.pem")
    assert loaded == ["company-ca.pem"]


def test_public_request_receives_the_configured_context(monkeypatch):
    captured = {}

    def _boom(_request, **kwargs):
        captured.update(kwargs)
        raise ConnectionResetError(10054, "connection reset")

    client = UrllibTransport(tls_strict=False)
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(TransportError):
        client.request("GET", "https://stand.example.ru/console/sys/token")
    assert captured["context"] is client.ssl_context


# -- an answer that breaks off ----------------------------------------------------------

#: A public host, so the transport goes through urllib.request.urlopen, which the tests replace.
STAND = "https://stand.example.ru"
APPS = f"{STAND}/console/api/v2/applications"


def _answer_with(monkeypatch, answer):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: answer)


def _refuse_with(monkeypatch, failure):
    def _refuse(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(urllib.request, "urlopen", _refuse)


def test_a_body_that_breaks_off_is_a_network_failure(monkeypatch):
    """http.client raises IncompleteRead outside OSError, and it used to pass the handler.

    The command ended with a traceback, and a read that is made again after a dropped
    connection was not made again after this one.
    """
    cut_short = http.client.IncompleteRead(b'{"items": [', 4096)
    _answer_with(monkeypatch, UrlopenAnswer(broken=cut_short))

    with pytest.raises(TransportError) as failure:
        UrllibTransport().request("GET", APPS)
    assert failure.value.__cause__ is cut_short
    assert "IncompleteRead" in str(failure.value)


@pytest.mark.parametrize("cut_short", [
    http.client.IncompleteRead(b"<html>", 512),
    ConnectionResetError(10054, "connection reset"),
], ids=["IncompleteRead", "ConnectionResetError"])
def test_an_error_body_that_breaks_off_is_a_network_failure(monkeypatch, cut_short):
    """The body of an error status is read inside the handler of HTTPError.

    A failure raised there went past the other handler of the same try, and so did a plain
    dropped connection.
    """
    refusal = urllib.error.HTTPError(
        APPS, 502, "Bad Gateway", {}, UrlopenAnswer(broken=cut_short)
    )
    _refuse_with(monkeypatch, refusal)

    with pytest.raises(TransportError) as failure:
        UrllibTransport().request("GET", APPS)
    assert failure.value.__cause__ is cut_short


@pytest.mark.parametrize("garbled", [
    http.client.BadStatusLine("SSH-2.0-OpenSSH_9.6\r\n"),
    http.client.BadStatusLine("\r\n"),
    http.client.UnknownProtocol("HTTP/2.0"),
    http.client.LineTooLong("header line"),
    http.client.HTTPException("got more than 100 headers"),
    http.client.RemoteDisconnected("Remote end closed connection without response"),
], ids=[
    "garbled-status-line", "blank-status-line", "unknown-protocol", "line-too-long",
    "too-many-headers", "remote-disconnected",
])
def test_an_answer_http_client_cannot_read_is_a_network_failure(monkeypatch, garbled):
    """Every failure of http.client derives from HTTPException, and one handler takes them all.

    The text of some is too thin to act on: a garbled status line comes as that line alone,
    and a blank one leaves no text at all. So the message names the class, the way the
    traceback used to.
    """
    _refuse_with(monkeypatch, garbled)

    with pytest.raises(TransportError) as failure:
        UrllibTransport().request("GET", APPS)
    assert failure.value.__cause__ is garbled
    assert type(garbled).__name__ in str(failure.value)


def test_an_address_http_client_rejects_is_not_a_network_failure(monkeypatch):
    """InvalidURL is raised before anything is sent, so asking again cannot help.

    A network failure is read again and may name the proxy as the likely cause, and here both
    would send the reader the wrong way.
    """
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12334")
    monkeypatch.delenv("NO_PROXY", raising=False)
    _refuse_with(monkeypatch, http.client.InvalidURL("nonnumeric port: '8O80'"))

    with pytest.raises(ElemctlError) as failure:
        UrllibTransport().request("GET", "https://stand.example.ru:8O80/console/sys/token")
    assert not isinstance(failure.value, TransportError)
    assert "8O80" in str(failure.value)
    assert transport.NO_PROXY_ENV not in str(failure.value)


def test_a_body_that_breaks_off_is_read_again_where_reads_are_repeated(monkeypatch, tmp_path):
    """The task list is read again after a dropped connection, and a body cut short is one."""
    tasks = [{"application-id": "app-1", "status": "Completed"}]
    reads = [
        UrlopenAnswer(broken=http.client.IncompleteRead(b'[{"application-id"', 4096)),
        UrlopenAnswer(json.dumps(tasks).encode("utf-8")),
    ]

    def _urlopen(request, **_kwargs):
        if request.full_url.endswith("/console/sys/token"):
            return UrlopenAnswer(b'{"id_token": "TOKEN"}')
        return reads.pop(0)

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    client = ElementClient(
        Config(base_url=STAND, client_id="cid", client_secret="secret"),
        token_cache_dir=tmp_path,
    )
    client._sleep = lambda seconds: None

    assert client.list_app_tasks("app-1") == tasks
    assert reads == []
