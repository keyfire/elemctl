"""Запуск пакета как модуля: python -m elemctl <аргументы>.

Нужен тем, кто вызывает elemctl текущим интерпретатором, не полагаясь на
консольную точку входа в PATH (например, обёртки в чужих репозиториях).
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
