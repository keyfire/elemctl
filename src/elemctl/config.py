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
from .transport import NO_PROXY_ENV, no_proxy_enabled

# Which environment variable each configuration field corresponds to.
ENV_KEYS = {
    "base_url": "ELEMENT_BASE_URL",
    "client_id": "ELEMENT_CLIENT_ID",
    "client_secret": "ELEMENT_CLIENT_SECRET",
    "app_id": "ELEMENT_APP_ID",
    "project_id": "ELEMENT_PROJECT_ID",
    "space_id": "ELEMENT_SPACE_ID",
    "ca_file": "ELEMENT_CA_FILE",
}

BOOL_ENV_KEYS = {
    "tls_verify": "ELEMENT_TLS_VERIFY",
    "tls_strict": "ELEMENT_TLS_STRICT",
}

DEFAULT_TIMEOUT = 60.0


def parse_bool(value, *, name):
    """Parse a human-friendly boolean, rejecting typos instead of weakening TLS."""
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ConfigError(i18n.t("config.invalid-boolean", name=name, value=value))


def ensure_env_file_exists(env_file):
    """Raise the clear ConfigError Config.from_env gives a bad explicit env_file, without
    building a Config – so the CLI's mcp command can fail fast on a bad --env-file at
    startup, before Config.from_env's own check would only ever run on the first call.

    Returns the resolved Path on success, since from_env needs it right after this check too.
    """
    path = Path(env_file)
    if not path.is_file():
        # The absolute path and the cwd answer the actual question: a
        # relative --env-file is resolved from the CURRENT directory,
        # not from --project-dir, and in a background run the current
        # directory is not always the one it seems to be.
        raise ConfigError(
            i18n.t(
                "config.env-file-not-found",
                path=path,
                absolute=path.resolve(),
                cwd=Path.cwd(),
            )
        )
    return path


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
    ca_file: str = ""
    tls_verify: bool = True
    tls_strict: bool = True
    #: Bypass the environment's proxy for every request of this configuration (ELEMCTL_NO_PROXY).
    #: A tool-behaviour switch rather than a platform contract field, so it has no ENV_KEYS
    #: entry of its own – from_env resolves it through its own explicit-argument/NO_PROXY_ENV
    #: precedence instead.
    no_proxy: bool = False
    timeout: float = field(default=DEFAULT_TIMEOUT)

    def __post_init__(self):
        # The trailing slash of the base URL is always stripped.
        self.base_url = (self.base_url or "").rstrip("/")
        if self.base_url and not self.base_url.lower().startswith(("http://", "https://")):
            raise ConfigError(i18n.t("config.invalid-base-url", value=self.base_url))
        self.tls_verify = parse_bool(self.tls_verify, name=BOOL_ENV_KEYS["tls_verify"])
        self.tls_strict = parse_bool(self.tls_strict, name=BOOL_ENV_KEYS["tls_strict"])

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
            path = ensure_env_file_exists(env_file)
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

        for field_name, env_key in BOOL_ENV_KEYS.items():
            override = overrides.pop(field_name, None)
            if override not in (None, ""):
                values[field_name] = parse_bool(override, name=env_key)
            elif env.get(env_key) not in (None, ""):
                values[field_name] = parse_bool(env[env_key], name=env_key)
            elif file_values.get(env_key) not in (None, ""):
                values[field_name] = parse_bool(file_values[env_key], name=env_key)

        # no_proxy follows the same three-source precedence as every other field above –
        # explicit argument, then process environment, then the file – but not the strict
        # parse_bool of BOOL_ENV_KEYS: it keeps the permissive reading ELEMCTL_NO_PROXY always
        # had, so a typo does not raise where it used to just leave the proxy in place. The
        # file source matters for MCP: a call only carries env_file, and a process variable
        # cannot be set for one call among several the same server process serves.
        no_proxy_override = overrides.pop("no_proxy", None)
        if no_proxy_override not in (None, ""):
            values["no_proxy"] = no_proxy_enabled(no_proxy_override)
        elif env.get(NO_PROXY_ENV) not in (None, ""):
            values["no_proxy"] = no_proxy_enabled(env[NO_PROXY_ENV])
        elif file_values.get(NO_PROXY_ENV) not in (None, ""):
            values["no_proxy"] = no_proxy_enabled(file_values[NO_PROXY_ENV])

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
