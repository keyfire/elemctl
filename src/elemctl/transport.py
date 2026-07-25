"""HTTP transport over urllib – the only place network calls are made.

The transport is a separate object so that the tests can replace it with a stub
and run without a network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import i18n
from .errors import TransportError


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

    def request(self, method, url, *, headers=None, data=None, timeout=60.0):
        request = urllib.request.Request(url, data=data, method=method)
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(response.status, response.headers, response.read())
        except urllib.error.HTTPError as error:
            # HTTPError is a response by itself – we return its body and code.
            return HttpResponse(error.code, error.headers, error.read())
        except OSError as error:
            raise TransportError(
                i18n.t("transport.network-error", method=method, url=url, error=error)
            ) from error
