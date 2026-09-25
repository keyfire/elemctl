"""self-update right after a release: which version counts as the latest.

The engine of the toolkit showed the failure on 24.09.2026, two minutes after a release: the
plain command answered "already current" with the previous version, while an explicit
`--version` went through at once. The latest version came from the simple index alone, and the
index still listed the release before. Both listings of PyPI are cached node by node, so either
may lag, while the page of the new version is fresh. These tests stand PyPI up as a table of
addresses; an address the table does not know answers 404, the way a page of an unpublished
version does. No network is touched.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from elemctl import i18n, selfupdate
from elemctl.errors import ElemctlError

INSTALLED = "0.44.0"


def _wheel(version: str) -> dict:
    name = f"elemctl-{version}-py3-none-any.whl"
    return {"filename": name, "url": f"https://files.test/{name}"}


def _index(*versions: str, yanked: tuple[str, ...] = ()) -> dict:
    """A PEP 691 answer of the simple index listing a wheel and an sdist of every version."""
    files = []
    for version in versions:
        files.append({**_wheel(version), "yanked": version in yanked})
        files.append({"filename": f"elemctl-{version}.tar.gz",
                      "url": f"https://files.test/elemctl-{version}.tar.gz"})
    return {"meta": {"api-version": "1.1"}, "files": files}


def _page(version: str, *, yanked: bool = False, named: str = "") -> dict:
    """The JSON document of one version; `named` stands in for a page naming another one."""
    return {"info": {"version": named or version, "yanked": yanked}, "urls": [_wheel(version)]}


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class PyPI:
    """urlopen over a table of addresses: a dict is served as JSON, an exception is raised,
    bytes are served as they are, and an address missing from the table answers 404."""

    def __init__(self, table: dict):
        self.table = table
        self.asked: list[str] = []

    def __call__(self, target, timeout=0):
        url = getattr(target, "full_url", target)
        self.asked.append(url)
        if url not in self.table:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        answer = self.table[url]
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, bytes):
            return _Answer(answer)
        return _Answer(json.dumps(answer).encode("utf-8"))


def _page_url(version: str) -> str:
    return selfupdate.PYPI_VERSION.format(version=version)


@pytest.fixture
def pypi(monkeypatch):
    def install(table: dict) -> PyPI:
        fake = PyPI(table)
        monkeypatch.setattr(selfupdate.urllib.request, "urlopen", fake)
        return fake
    return install


def _latest(lines=None):
    return selfupdate._wheel_url(None, log=(lines.append if lines is not None else None))


def test_both_listings_lag_and_the_page_of_the_next_release_is_found(pypi):
    """The very case of 24.09: both listings name the release before, the page is out."""
    fake = pypi({
        selfupdate.PYPI_SIMPLE: _index("0.43.0", INSTALLED),
        selfupdate.PYPI_LATEST: _page(INSTALLED),
        _page_url("0.45.0"): _page("0.45.0"),
    })
    lines: list[str] = []

    url, version = _latest(lines)

    assert version == "0.45.0" and url.endswith("elemctl-0.45.0-py3-none-any.whl")
    assert len(lines) == 1
    assert "0.45.0" in lines[0] and "страница версии" in lines[0]
    # The listings come first, then the pages of the next patch, minor and major.
    assert fake.asked[:5] == [
        selfupdate.PYPI_SIMPLE, selfupdate.PYPI_LATEST,
        _page_url("0.44.1"), _page_url("0.45.0"), _page_url("1.0.0"),
    ]


def test_the_listings_agreeing_ask_three_pages_and_say_nothing(pypi):
    fake = pypi({
        selfupdate.PYPI_SIMPLE: _index("0.43.0", INSTALLED),
        selfupdate.PYPI_LATEST: _page(INSTALLED),
    })
    lines: list[str] = []

    assert _latest(lines)[1] == INSTALLED
    assert lines == []
    assert fake.asked == [
        selfupdate.PYPI_SIMPLE, selfupdate.PYPI_LATEST,
        _page_url("0.44.1"), _page_url("0.45.0"), _page_url("1.0.0"),
    ]


def test_a_lagging_index_loses_to_a_fresh_summary(pypi):
    pypi({
        selfupdate.PYPI_SIMPLE: _index("0.43.0"),
        selfupdate.PYPI_LATEST: _page(INSTALLED),
    })
    lines: list[str] = []

    url, version = _latest(lines)

    assert version == INSTALLED and url.endswith(f"elemctl-{INSTALLED}-py3-none-any.whl")
    assert len(lines) == 1 and "0.43.0" in lines[0] and INSTALLED in lines[0]


def test_a_lagging_summary_loses_to_a_fresh_index(pypi):
    pypi({
        selfupdate.PYPI_SIMPLE: _index("0.43.0", INSTALLED),
        selfupdate.PYPI_LATEST: _page("0.43.0"),
    })
    lines: list[str] = []

    assert _latest(lines)[1] == INSTALLED
    assert len(lines) == 1 and "сводный JSON – 0.43.0" in lines[0]


def test_two_releases_inside_one_window_of_lag(pypi):
    """The look goes on from the page it found: 0.44.1 leads to 0.44.2."""
    pypi({
        selfupdate.PYPI_SIMPLE: _index(INSTALLED),
        selfupdate.PYPI_LATEST: _page(INSTALLED),
        _page_url("0.44.1"): _page("0.44.1"),
        _page_url("0.44.2"): _page("0.44.2"),
    })
    assert _latest()[1] == "0.44.2"


def test_the_newest_of_the_next_pages_wins(pypi):
    pypi({
        selfupdate.PYPI_SIMPLE: _index(INSTALLED),
        selfupdate.PYPI_LATEST: _page(INSTALLED),
        _page_url("0.44.1"): _page("0.44.1"),
        _page_url("0.45.0"): _page("0.45.0"),
    })
    assert _latest()[1] == "0.45.0"


def test_a_yanked_release_and_a_page_of_another_version_do_not_count(pypi):
    pypi({
        selfupdate.PYPI_SIMPLE: _index(INSTALLED),
        selfupdate.PYPI_LATEST: _page(INSTALLED),
        _page_url("0.44.1"): _page("0.44.1", yanked=True),
        _page_url("0.45.0"): _page("0.45.0", named=INSTALLED),
    })
    lines: list[str] = []

    assert _latest(lines)[1] == INSTALLED
    assert lines == []


def test_a_summary_that_cannot_be_read_leaves_the_index_to_answer(pypi):
    pypi({
        selfupdate.PYPI_SIMPLE: _index(INSTALLED),
        selfupdate.PYPI_LATEST: b"<html>proxy error</html>",
    })
    assert _latest()[1] == INSTALLED


def test_an_unreachable_summary_leaves_the_index_to_answer(pypi):
    pypi({
        selfupdate.PYPI_SIMPLE: _index(INSTALLED),
        selfupdate.PYPI_LATEST: OSError("connection reset"),
    })
    assert _latest()[1] == INSTALLED


def test_neither_listing_answering_is_an_error_in_words(pypi):
    pypi({
        selfupdate.PYPI_SIMPLE: OSError("no route"),
        selfupdate.PYPI_LATEST: OSError("no route"),
    })
    with pytest.raises(ElemctlError, match="PyPI"):
        _latest()


def test_an_explicit_version_the_index_does_not_list_is_found_on_its_page(pypi):
    """The index may lag behind a release it will list in a minute; the page does not."""
    fake = pypi({
        selfupdate.PYPI_SIMPLE: _index(INSTALLED),
        _page_url("0.45.0"): _page("0.45.0"),
    })

    url, version = selfupdate._wheel_url("0.45.0")

    assert version == "0.45.0" and url.endswith("elemctl-0.45.0-py3-none-any.whl")
    # An explicit version is looked up and nothing more: no summary, no look past it.
    assert fake.asked == [selfupdate.PYPI_SIMPLE, _page_url("0.45.0")]


def test_an_explicit_version_nobody_knows_is_named_as_such(pypi):
    pypi({selfupdate.PYPI_SIMPLE: _index(INSTALLED)})
    with pytest.raises(ElemctlError, match="версия не найдена"):
        selfupdate._wheel_url("9.9.9")


def test_a_release_installed_by_its_number_is_not_rolled_back(pypi, monkeypatch):
    """Every source still names the release before: the plain command must change nothing."""
    monkeypatch.setattr(selfupdate, "__version__", "0.45.0")
    pypi({
        selfupdate.PYPI_SIMPLE: _index(INSTALLED),
        selfupdate.PYPI_LATEST: _page(INSTALLED),
    })

    def no_download(*args, **kwargs):
        raise AssertionError("nothing may be moved or unpacked")

    monkeypatch.setattr(selfupdate, "_move_aside", no_download)
    lines: list[str] = []

    before, after = selfupdate.self_update(log=lines.append)

    assert before == after == "0.45.0"
    assert any("Ничего не меняю" in line and INSTALLED in line for line in lines)


def test_the_sources_line_speaks_english_too(pypi):
    pypi({
        selfupdate.PYPI_SIMPLE: _index(INSTALLED),
        selfupdate.PYPI_LATEST: _page(INSTALLED),
        _page_url("0.44.1"): _page("0.44.1"),
    })
    lines: list[str] = []
    i18n.set_lang("en")
    try:
        _latest(lines)
    finally:
        i18n.set_lang("ru")
    assert lines and "the PyPI sources disagree" in lines[0]
    assert "the page of version 0.44.1 is already published" in lines[0]


def test_the_next_versions_are_the_next_patch_minor_and_major():
    assert selfupdate._next_versions("0.44.0") == ["0.44.1", "0.45.0", "1.0.0"]
    assert selfupdate._next_versions("0.44.0.post1") == ["0.44.1", "0.45.0", "1.0.0"]
    assert selfupdate._next_versions("0.45.0rc1") == []
