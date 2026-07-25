"""self-update tests: updating by unpacking the wheel with no network (urllib is mocked)."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

import elemctl
from elemctl import cli, selfupdate


def _fake_wheel(version: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("elemctl/__init__.py", f'__version__ = "{version}"\n')
        archive.writestr(f"elemctl-{version}.dist-info/METADATA", f"Version: {version}\n")
    return buf.getvalue()


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_self_update_extracts_wheel(monkeypatch, tmp_path):
    """The wheel is unpacked into site-packages; the old package and dist-info are removed."""
    site = tmp_path / "site-packages"
    (site / "elemctl").mkdir(parents=True)
    (site / "elemctl" / "__init__.py").write_text('__version__ = "0.0.1"\n', encoding="utf-8")
    (site / "elemctl-0.0.1.dist-info").mkdir()
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: site)
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v: ("http://pypi/elemctl.whl", "9.9.9"))
    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9")))

    old, new = selfupdate.self_update(log=lambda *a: None)

    assert new == "9.9.9" and old == elemctl.__version__
    assert '__version__ = "9.9.9"' in (site / "elemctl" / "__init__.py").read_text(encoding="utf-8")
    assert not (site / "elemctl-0.0.1.dist-info").exists()  # the old dist-info is gone
    assert (site / "elemctl-9.9.9.dist-info").exists()


def test_self_update_noop_when_current(monkeypatch, tmp_path):
    """When the PyPI version equals the current one and no version is asked for – nothing is downloaded."""
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v: ("http://pypi/x.whl", elemctl.__version__))

    def boom(*a, **k):
        raise AssertionError("скачивание не должно происходить")

    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", boom)
    old, new = selfupdate.self_update(log=lambda *a: None)
    assert old == new == elemctl.__version__


def test_updates_pipx_metadata(monkeypatch, tmp_path):
    """package_version in pipx_metadata.json is updated when the venv is a pipx one."""
    site = tmp_path / "venv" / "Lib" / "site-packages"
    (site / "elemctl").mkdir(parents=True)
    (site / "elemctl" / "__init__.py").write_text("x\n", encoding="utf-8")
    meta = tmp_path / "venv" / "pipx_metadata.json"
    meta.write_text(json.dumps({"main_package": {"package": "elemctl", "package_version": "0.0.1"}}), encoding="utf-8")
    monkeypatch.setattr(selfupdate, "_site_packages", lambda: site)
    monkeypatch.setattr(selfupdate, "_wheel_url", lambda v: ("http://pypi/x.whl", "9.9.9"))
    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", lambda url, timeout=0: _FakeResp(_fake_wheel("9.9.9")))

    selfupdate.self_update(log=lambda *a: None)

    assert json.loads(meta.read_text(encoding="utf-8"))["main_package"]["package_version"] == "9.9.9"


def test_cli_self_update(monkeypatch, capsys):
    monkeypatch.setattr(selfupdate, "self_update", lambda version=None, log=print: ("0.5.0", "0.6.0"))
    rc = cli.main(["self-update"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"updated": True, "from": "0.5.0", "to": "0.6.0"}
