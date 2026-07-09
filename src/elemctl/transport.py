"""HTTP-транспорт поверх urllib – единственная точка сетевых вызовов.

Транспорт выделен в отдельный объект, чтобы тесты могли подменить его
заглушкой и работать без сети.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .errors import TransportError


class HttpResponse:
    """Ответ HTTP-запроса: статус, заголовки и тело в байтах."""

    def __init__(self, status, headers, body):
        self.status = int(status)
        self.headers = dict(headers or {})
        self.body = body or b""

    def text(self):
        """Тело ответа строкой (UTF-8, нечитаемые байты заменяются)."""
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        """Тело ответа как JSON; для пустого тела – None."""
        if not self.body:
            return None
        return json.loads(self.text())


class UrllibTransport:
    """Транспорт на urllib.request.

    Ответы с кодами не-2xx возвращаются как обычные ответы (решение об
    ошибке принимает клиент); сетевые сбои превращаются в TransportError.
    """

    def request(self, method, url, *, headers=None, data=None, timeout=60.0):
        request = urllib.request.Request(url, data=data, method=method)
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(response.status, response.headers, response.read())
        except urllib.error.HTTPError as error:
            # HTTPError сам является ответом – возвращаем его тело и код.
            return HttpResponse(error.code, error.headers, error.read())
        except OSError as error:
            raise TransportError(f"сетевая ошибка {method} {url}: {error}") from error
