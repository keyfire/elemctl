"""elemctl - a CLI, an MCP server and a library for managing applications built
with the 1C:Element technology through Console API v2.

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

__version__ = "0.52.0"

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
