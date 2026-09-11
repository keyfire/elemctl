#!/usr/bin/env python
"""Rebuild every generated documentation page: the command reference and the mirrors.

Four pages of this repository are written by a generator, and each generator used to be its own
thing to remember - `python scripts/gen-cli-docs.py` after a flag changed, `node
scripts/sync-docs.mjs` after the changelog did. The second one was forgotten often enough that
writing the changelog link and rebuilding the mirrors were made one command; that left the
command reference as the last "do not forget", the same trap in the same shape.

One command rebuilds all of them:

    python scripts/rebuild-docs.py

Exit code 1 when any half did not rebuild - a rebuild that did not happen must not look like a
finished step. The generators are called the way a person calls them, so this script stays a
schedule of steps: nothing here is a second implementation of what they do.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The generators, in the order they have to run: the pages come from the tool itself, and the
#: mirroring script goes last because it carries sections of those pages into the READMEs.
STEPS = (
    ("the command reference", (sys.executable, "scripts/gen-cli-docs.py")),
    ("the mirrored pages", ("node", "scripts/sync-docs.mjs")),
)


def rebuild(root: Path = ROOT, run=None) -> tuple[bool, str]:
    """Every generator run in turn; (did they all work, what they said).

    One failing generator does not stop the next: a run that reports one half broken and says
    nothing about the other turns one rebuild into two. `run` is the process runner, the test's
    way in - a default bound at definition time would leave the real generators running under
    it. A generator that is not installed (no node on the machine) is reported like any other
    failure instead of raising: the answer the caller needs is the same, the pages are not
    rebuilt and the commit is not ready.
    """
    ok = True
    said: list[str] = []
    for what, command in STEPS:
        spelled = " ".join(command)
        try:
            # The encoding is spelled out on purpose: a generator names the Russian pages it
            # writes, and on a Windows console Python would decode that with the system code
            # page - the reader thread then dies on the first Cyrillic byte and the output is
            # lost while the exit code still says everything went well.
            done = (run or subprocess.run)(
                list(command), cwd=str(root), capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
        except OSError as error:
            ok = False
            said.append(f"{what}: {spelled}: {error}")
            continue
        output = ((done.stdout or "") + (done.stderr or "")).strip()
        if output:
            said.append(output)
        if done.returncode != 0:
            ok = False
            said.append(f"{what}: `{spelled}` ended with {done.returncode}")
    return ok, "\n".join(said)


def main(argv=None, run=None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the generated documentation pages: the command reference and the "
                    "mirrored pages."
    )
    parser.parse_args(argv)

    ok, said = rebuild(ROOT, run)
    if said:
        print(said)
    if not ok:
        print("the generated pages were NOT rebuilt - fix what failed above before committing",
              file=sys.stderr)
        return 1
    print("stage the generated pages together with the sources they were rebuilt from")
    return 0


if __name__ == "__main__":
    sys.exit(main())
