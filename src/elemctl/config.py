"""Configuration of the connection to the platform.

The parameters are collected from three sources, in decreasing priority:
explicit arguments, environment variables, the .env file (section 2 of the
specification).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import i18n
from .errors import ConfigError

# Which environment variable each configuration field corresponds to.
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
    """Parse a .env file into a KEY -> VALUE dictionary.

    The rules: empty lines and lines starting with "#" are skipped, an "export "
    prefix as well as single or double quotes around the value are allowed;
    the encoding is UTF-8, a BOM is possible.
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
    """The parameters of the connection to the Console API."""

    base_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    app_id: str = ""
    project_id: str = ""
    space_id: str = ""
    timeout: float = field(default=DEFAULT_TIMEOUT)

    def __post_init__(self):
        # The trailing slash of the base URL is always stripped.
        self.base_url = (self.base_url or "").rstrip("/")

    @classmethod
    def from_env(cls, env_file=None, environ=None, **overrides):
        """Collect the configuration: explicit arguments > environment > .env file.

        env_file – the path to the .env; without it the .env file in the current
        directory is taken, if it exists. environ – the source of the environment
        variables (os.environ by default; the parameter is there for the tests).
        """
        env = os.environ if environ is None else environ

        file_values = {}
        if env_file:
            path = Path(env_file)
            if not path.is_file():
                raise ConfigError(i18n.t("config.env-file-not-found", path=path))
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
            raise TypeError(i18n.t("config.unknown-params", unknown=unknown))

        return cls(**values)

    def require(self):
        """Check the mandatory connection parameters; return self."""
        missing = []
        for field_name in ("base_url", "client_id", "client_secret"):
            if not getattr(self, field_name):
                missing.append(ENV_KEYS[field_name])
        if missing:
            raise ConfigError(
                i18n.t("config.connection-not-set", missing=", ".join(missing))
            )
        return self
