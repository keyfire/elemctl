"""Obtaining and caching the Console API token.

A token lives for about an hour, so it is cached in a file in the system
temporary directory with a one-hour TTL; the cache key tells base_url +
client_id pairs apart. On a 401 the client asks for a token forcibly
(force=True).
"""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import time
from pathlib import Path

from . import i18n
from .errors import ApiError

TOKEN_TTL = 3600.0
# Margin before expiry: the cache counts as good while more than the margin is left to live.
EXPIRY_MARGIN = 30.0


def extract_token(payload):
    """Extract the token out of the server response.

    The token sits in the first non-empty of the id_token, token, value,
    access_token fields. A special case: the value "Not implemented" is not
    a token and is skipped.
    """
    if not isinstance(payload, dict):
        return None
    for key in ("id_token", "token", "value", "access_token"):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        value = value.strip()
        if not value or value == "Not implemented":
            continue
        return value
    return None


class TokenManager:
    """Hands out a valid Bearer token, hiding caching and refreshing."""

    def __init__(self, config, transport, cache_dir=None):
        self._config = config
        self._transport = transport
        self._cache_dir = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir())
        self._token = None
        self._expires_at = 0.0

    def get_token(self, force=False):
        """Return a token: from memory, from the file cache, or by asking for a new one."""
        now = time.time()
        if not force:
            if self._token and now + EXPIRY_MARGIN < self._expires_at:
                return self._token
            cached = self._read_cache()
            if cached and now + EXPIRY_MARGIN < cached.get("expires", 0):
                self._token = cached["token"]
                self._expires_at = cached["expires"]
                return self._token
        token = self._request_token()
        self._token = token
        self._expires_at = now + TOKEN_TTL
        self._write_cache()
        return token

    # -- internals -------------------------------------------------------

    def _cache_path(self):
        key = f"{self._config.base_url}|{self._config.client_id}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return self._cache_dir / f"elemctl-token-{digest}.json"

    def _read_cache(self):
        try:
            data = json.loads(self._cache_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(data, dict) and isinstance(data.get("token"), str):
            return data
        return None

    def _write_cache(self):
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {"token": self._token, "expires": self._expires_at}
            self._cache_path().write_text(
                json.dumps(payload), encoding="utf-8"
            )
        except OSError:
            # The cache is only a speedup; its unavailability must not break the work.
            pass

    def _request_token(self):
        config = self._config.require()
        credentials = f"{config.client_id}:{config.client_secret}".encode("utf-8")
        basic = base64.b64encode(credentials).decode("ascii")
        url = f"{config.base_url}/console/sys/token"
        response = self._transport.request(
            "POST",
            url,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=b"grant_type=client_credentials",
            timeout=config.timeout,
        )
        if not 200 <= response.status < 300:
            raise ApiError(
                i18n.t("auth.token-http-error", status=response.status),
                status=response.status,
                method="POST",
                url=url,
                body=_safe_body(response),
            )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        token = extract_token(payload)
        if not token:
            raise ApiError(
                i18n.t("auth.token-not-found"),
                status=response.status,
                method="POST",
                url=url,
                body=payload if payload is not None else response.text(),
            )
        return token


def _safe_body(response):
    """The body for the error details: JSON, or the text when it does not parse."""
    try:
        return response.json()
    except ValueError:
        return response.text()
