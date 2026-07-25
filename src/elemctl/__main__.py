"""Running the package as a module: python -m elemctl <arguments>.

Needed by those who call elemctl with the current interpreter instead of relying
on the console entry point being in PATH (wrappers in other repositories, say).
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
