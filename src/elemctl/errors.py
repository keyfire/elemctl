"""elemctl exceptions.

The hierarchy is simple: everything inherits from ElemctlError, so that a caller
can intercept any error of the tool with a single except.
"""

from __future__ import annotations


class ElemctlError(Exception):
    """The base elemctl exception."""


class ConfigError(ElemctlError):
    """A connection configuration error: parameters or the file are missing."""


class BuildError(ElemctlError):
    """An error of the local .xasm/.xlib archive build."""


class TransportError(ElemctlError):
    """A network error: the server could not be reached."""


class PluginError(ElemctlError):
    """An error of discovering or loading an elemctl plugin (extension points)."""


class ApiError(ElemctlError):
    """A Console API error: the HTTP status and the response body of the server.

    The details are JSON-serializable (the to_dict method) – that is how the CLI
    prints them to stderr without losing information.
    """

    def __init__(self, message, *, status=None, method=None, url=None, body=None, hint=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.method = method
        self.url = url
        self.body = body
        self.hint = hint

    def to_dict(self):
        """Represent the error as a JSON-serializable dictionary."""
        payload = {"error": self.message}
        for key, value in (
            ("status", self.status),
            ("method", self.method),
            ("url", self.url),
            ("body", self.body),
            ("hint", self.hint),
        ):
            if value not in (None, ""):
                payload[key] = value
        return payload
