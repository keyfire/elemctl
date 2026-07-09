"""Исключения elemctl.

Иерархия простая: всё наследуется от ElemctlError, чтобы вызывающая сторона
могла перехватить любую ошибку инструмента одним except.
"""

from __future__ import annotations


class ElemctlError(Exception):
    """Базовое исключение elemctl."""


class ConfigError(ElemctlError):
    """Ошибка конфигурации подключения: не хватает параметров или файла."""


class BuildError(ElemctlError):
    """Ошибка локальной сборки архива .xasm/.xlib."""


class TransportError(ElemctlError):
    """Сетевая ошибка: до сервера не удалось достучаться."""


class ApiError(ElemctlError):
    """Ошибка Console API: HTTP-статус и тело ответа сервера.

    Детали сериализуемы в JSON (метод to_dict) – так CLI выводит их
    в stderr без потери информации.
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
        """Представить ошибку JSON-сериализуемым словарём."""
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
