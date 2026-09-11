"""One command rebuilds every generated page - the step that cannot be half-remembered.

The command reference and the mirrored pages come from two different generators, and each of
them used to be a thing to remember on its own. One of them was forgotten often enough to turn
`main` red on the documentation guard, so they are one step now, and this is what the test asks
for: every generator called in the same run, and a run where one of them failed saying so
instead of passing quietly.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rebuild-docs.py"

spec = importlib.util.spec_from_file_location("rebuild_docs", SCRIPT)
rebuild_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rebuild_docs)


def done(returncode=0, stdout="", stderr=""):
    """What a process runner answers with."""
    return type("Done", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()


def recorder(*answers):
    """A fake process runner: the calls it collected, and the answers it gives in turn.

    An answer that is an exception is raised instead of returned - that is how a generator
    which is not on the machine at all behaves.
    """
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        answer = answers[len(calls) - 1] if len(calls) <= len(answers) else done()
        if isinstance(answer, Exception):
            raise answer
        return answer

    return calls, run


def test_one_run_calls_every_generator():
    """The whole point: the reference and the mirrors are rebuilt by one command."""
    calls, run = recorder()

    assert rebuild_docs.main([], run=run) == 0
    assert [command for command, _ in calls] == [list(step) for _, step in rebuild_docs.STEPS]


def test_a_generator_is_read_as_utf8_from_the_repository_root():
    """The output of a generator names the Russian pages it writes.

    With the system code page the reader thread died on the first Cyrillic byte and the output
    vanished - exit code 0 and all.
    """
    calls, run = recorder()

    rebuild_docs.main([], run=run)

    for _, kwargs in calls:
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["cwd"] == str(rebuild_docs.ROOT)


def test_a_python_generator_is_told_to_write_utf8():
    """Reading UTF-8 from a child that writes the console code page is the same mangling.

    A plain Python script encodes its stream in the code page of the console, so the Russian
    page names arrive as replacement characters - which is exactly what a nested run of this
    script produced before the two halves of the agreement were spelled out.
    """
    calls, run = recorder()

    rebuild_docs.main([], run=run)

    for _, kwargs in calls:
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"


def test_a_generator_that_failed_makes_the_whole_step_fail():
    """A rebuild that did not happen must not look like a finished step."""
    calls, run = recorder(done(1, stderr="cli.md: the generator gave up"))

    assert rebuild_docs.main([], run=run) == 1
    # ...and the other half still ran: a report about one generator that says nothing about the
    # next turns one rebuild into two
    assert len(calls) == len(rebuild_docs.STEPS)


def test_a_generator_that_cannot_start_is_reported_and_not_raised():
    """No node on the machine is the same answer: the pages are not rebuilt."""
    calls, run = recorder(done(), OSError("node not found"))

    assert rebuild_docs.main([], run=run) == 1
    assert len(calls) == len(rebuild_docs.STEPS)


def test_the_steps_are_the_generators_the_repository_carries():
    """A renamed generator must not leave the step quietly rebuilding nothing."""
    assert len(rebuild_docs.STEPS) > 1
    for _, command in rebuild_docs.STEPS:
        assert (ROOT / command[-1]).is_file(), command
