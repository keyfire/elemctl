"""HTTP transport over urllib – the only place network calls are made.

The transport is a separate object so that the tests can replace it with a stub
and run without a network.
"""

from __future__ import annotations

import ipaddress
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from . import i18n
from .errors import TransportError

#: Set it to bypass the environment's proxy for every request of the tool.
NO_PROXY_ENV = "ELEMCTL_NO_PROXY"

#: Host suffixes served inside a network, never through an outbound proxy.
_LOCAL_SUFFIXES = (".local", ".lan", ".localdomain", ".internal", ".test")


def _no_proxy_requested(environ=None):
    value = (environ if environ is not None else os.environ).get(NO_PROXY_ENV, "")
    return value.strip().lower() not in ("", "0", "false", "no")


def is_local_host(host):
    """Is the host one no outbound proxy can serve - loopback, a private address, .local?

    Judged by the name alone, without resolving it: a DNS lookup on every request would cost
    more than it decides, and the ambiguous case is left to the proxy as before.
    """
    host = (host or "").strip("[]").lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost") or host.endswith(_LOCAL_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def proxy_for(url, environ=None):
    """The proxy the environment sets for this URL, or None - honouring no_proxy as urllib does."""
    parts = urllib.parse.urlsplit(url)
    proxies = urllib.request.getproxies_environment() if environ is None else {
        name.lower()[:-6]: value for name, value in environ.items()
        if name.lower().endswith("_proxy") and name.lower() != "no_proxy" and value
    }
    if urllib.request.proxy_bypass_environment(parts.hostname or "", proxies):
        return None
    return proxies.get(parts.scheme)


class HttpResponse:
    """An HTTP response: the status, the headers and the body in bytes."""

    def __init__(self, status, headers, body):
        self.status = int(status)
        self.headers = dict(headers or {})
        self.body = body or b""

    def text(self):
        """The body as a string (UTF-8, undecodable bytes are replaced)."""
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        """The body as JSON; None for an empty body."""
        if not self.body:
            return None
        return json.loads(self.text())


class UrllibTransport:
    """A transport built on urllib.request.

    Responses with non-2xx codes are returned as ordinary responses (the client
    is the one that decides whether that is an error); network failures turn
    into TransportError.
    """

    #: An opener that ignores the environment's proxies – built once, it holds no state.
    _direct = None

    def _opener(self, url):
        """The opener for this URL: the default one, or a direct one past the proxy.

        A proxy is honoured as before – a stand behind a corporate proxy has to be reached
        through it. Bypassed only where a proxy cannot possibly help: a loopback or private
        address, or when the caller asked for it outright.
        """
        host = urllib.parse.urlsplit(url).hostname
        if not (_no_proxy_requested() or is_local_host(host)):
            return urllib.request.urlopen
        if UrllibTransport._direct is None:
            UrllibTransport._direct = urllib.request.build_opener(
                urllib.request.ProxyHandler({})
            )
        return UrllibTransport._direct.open

    def request(self, method, url, *, headers=None, data=None, timeout=60.0):
        request = urllib.request.Request(url, data=data, method=method)
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with self._opener(url)(request, timeout=timeout) as response:
                return HttpResponse(response.status, response.headers, response.read())
        except urllib.error.HTTPError as error:
            # HTTPError is a response by itself – we return its body and code.
            return HttpResponse(error.code, error.headers, error.read())
        except OSError as error:
            raise TransportError(self._failure(method, url, error)) from error

    def _failure(self, method, url, error):
        """The message of a failed call – naming the proxy when one was in the way.

        A proxy that cannot reach an internal stand fails as a plain connection reset, and the
        stand looks dead while it is running. The hint is what turns that into a one-minute
        diagnosis instead of an hour.
        """
        message = i18n.t("transport.network-error", method=method, url=url, error=error)
        proxy = proxy_for(url)
        if proxy:
            message += " " + i18n.t("transport.proxy-hint", proxy=proxy, variable=NO_PROXY_ENV)
        return message
