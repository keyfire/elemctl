"""elemctl – a CLI, an MCP server and a library for Console API v2 of the
1C:Enterprise.Element platform (1cmycloud).

Public API of the library:

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

__version__ = "0.19.0"

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
