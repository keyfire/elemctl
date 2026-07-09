"""Конфигурация подключения к платформе.

Параметры собираются из трёх источников по убыванию приоритета:
явные аргументы, переменные окружения, .env-файл (раздел 2 спецификации).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError

# Соответствие полей конфигурации переменным окружения.
ENV_KEYS = {
    "base_url": "ELEMENT_BASE_URL",
    "client_id": "ELEMENT_CLIENT_ID",
    "client_secret": "ELEMENT_CLIENT_SECRET",
    "app_id": "ELEMENT_APP_ID",
    "project_id": "ELEMENT_PROJECT_ID",
    "space_id": "ELEMENT_SPACE_ID",
}

DEFAULT_TIMEOUT = 60.0


def parse_env_file(path):
    """Разобрать .env-файл в словарь KEY -> VALUE.

    Правила: пустые строки и строки с "#" в начале пропускаются, допускается
    префикс "export " и одинарные или двойные кавычки вокруг значения;
    кодировка UTF-8, возможен BOM.
    """
    values = {}
    text = Path(path).read_text(encoding="utf-8-sig")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


@dataclass
class Config:
    """Параметры подключения к Console API."""

    base_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    app_id: str = ""
    project_id: str = ""
    space_id: str = ""
    timeout: float = field(default=DEFAULT_TIMEOUT)

    def __post_init__(self):
        # Хвостовой слэш базового URL всегда обрезается.
        self.base_url = (self.base_url or "").rstrip("/")

    @classmethod
    def from_env(cls, env_file=None, environ=None, **overrides):
        """Собрать конфигурацию: явные аргументы > окружение > .env-файл.

        env_file – путь к .env; без него берётся файл .env в текущем
        каталоге, если существует. environ – источник переменных окружения
        (по умолчанию os.environ; параметр нужен тестам).
        """
        env = os.environ if environ is None else environ

        file_values = {}
        if env_file:
            path = Path(env_file)
            if not path.is_file():
                raise ConfigError(f".env-файл не найден: {path}")
            file_values = parse_env_file(path)
        else:
            default_path = Path(".env")
            if default_path.is_file():
                file_values = parse_env_file(default_path)

        values = {}
        for field_name, env_key in ENV_KEYS.items():
            override = overrides.pop(field_name, None)
            if override not in (None, ""):
                values[field_name] = str(override)
            elif env.get(env_key):
                values[field_name] = env[env_key]
            elif file_values.get(env_key):
                values[field_name] = file_values[env_key]

        timeout = overrides.pop("timeout", None)
        if timeout:
            values["timeout"] = float(timeout)

        if overrides:
            unknown = ", ".join(sorted(overrides))
            raise TypeError(f"неизвестные параметры конфигурации: {unknown}")

        return cls(**values)

    def require(self):
        """Проверить обязательные параметры подключения; вернуть self."""
        missing = []
        for field_name in ("base_url", "client_id", "client_secret"):
            if not getattr(self, field_name):
                missing.append(ENV_KEYS[field_name])
        if missing:
            raise ConfigError(
                "не заданы параметры подключения: " + ", ".join(missing)
                + " (переменные окружения, .env-файл или флаги CLI)"
            )
        return self
