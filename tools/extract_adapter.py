#!/usr/bin/env python3
"""Extraction of the 1C:Enterprise.Element Java debug adapter from a distribution.

The adapter sits inside the .car (which is a ZIP) of the server-with-IDE, under
data/ide/theia/plugins/@1c-appengine-plugin/bin/debugger/ (the bin/ and repo/
subdirectories with the adapter jars). Proprietary 1C components are not part of
elemctl – this script extracts them from the distribution you are licensed for.

The result is an <output>/<version>/ directory with a repo/ subdirectory: a ready value for
the xbsl.debug.adapterPath setting of the XBSL VS Code extension. The script also writes
<output>/index.json (the available versions and the default one) – the file a package that
ships the adapter through the elemctl.debug_adapter entry point group reads to answer
`elemctl debug-adapter`.

Usage:
    python tools/extract_adapter.py <path to the .car or to the distribution directory> --output C:/tools/xbsl-adapter
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
import re

ADAPTER_PREFIX = "data/ide/theia/plugins/@1c-appengine-plugin/bin/debugger/"
VERSION_RE = re.compile(r"(\d+\.\d+\.\d+\+\d+)")


def find_car(path: Path) -> Path:
    """Path to the .car of the server-with-IDE: the file itself or one inside a distribution directory."""
    if path.is_file():
        return path
    if path.is_dir():
        cars = sorted(path.glob("*element-server-with-ide-*.car"))
        if not cars:
            cars = sorted(path.glob("*.car"))
        if cars:
            return cars[0]
    raise SystemExit(f"no .car found in {path}")


def detect_version(car: Path) -> str:
    """The platform version taken from the .car file name (major.minor.patch+build)."""
    match = VERSION_RE.search(car.name)
    if not match:
        raise SystemExit(f"could not determine the version from the name {car.name}")
    return match.group(1)


def extract(car: Path, version: str, output: Path) -> tuple[Path, int]:
    """Extract the adapter directory from the .car into <output>/<version>/; return the path and the file count."""
    target = output / version
    if target.exists():
        raise SystemExit(f"the version directory already exists: {target} (remove it to re-extract)")
    count = 0
    with zipfile.ZipFile(car) as archive:
        members = [
            name
            for name in archive.namelist()
            if name.startswith(ADAPTER_PREFIX) and not name.endswith("/")
        ]
        if not members:
            raise SystemExit(f"{car.name} has no {ADAPTER_PREFIX} directory")
        for name in members:
            relative = name[len(ADAPTER_PREFIX):]
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(archive.read(name))
            count += 1
    return target, count


def update_index(output: Path, version: str) -> None:
    """Append the version to <output>/index.json and make it the default one."""
    index = output / "index.json"
    data = {"available": [], "default": version}
    if index.exists():
        data = json.loads(index.read_text(encoding="utf-8"))
    if version not in data["available"]:
        data["available"].append(version)
    data["available"].sort()
    data["default"] = version
    index.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="extract the 1C:Enterprise.Element platform debug adapter from a distribution"
    )
    parser.add_argument("distro", help="the path to a .car file or to a distribution directory")
    parser.add_argument(
        "--output",
        default="adapter",
        help="the directory for adapter/<version>/ and index.json (default: ./adapter)",
    )
    args = parser.parse_args(argv)

    car = find_car(Path(args.distro))
    version = detect_version(car)
    output = Path(args.output)
    target, count = extract(car, version, output)
    update_index(output, version)
    print(f"extracted {count} files; adapterPath = {target}")
    print(f"index.json updated in {output} (default={version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
