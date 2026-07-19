"""elemctl – CLI, MCP-сервер и библиотека для Console API v2 платформы
1С:Предприятие.Элемент (1cmycloud).

Публичный API библиотеки:

    from elemctl import Config, ElementClient
    from elemctl.deploy import deploy_from_sources
"""

from .client import ElementClient
from .config import Config
from .errors import (
    ApiError,
    BuildError,
    ConfigError,
    ElemctlError,
    PluginError,
    TransportError,
)

__version__ = "0.9.1"

__all__ = [
    "ApiError",
    "BuildError",
    "Config",
    "ConfigError",
    "ElemctlError",
    "ElementClient",
    "PluginError",
    "TransportError",
    "__version__",
]
