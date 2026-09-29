"""The export of the build an application runs: the client, the CLI command and the MCP tool.

The method belongs to Console API 2.0, and the reference documents it under 2.1 as well; the
client takes the 2.0 path, the way it does with every method 2.0 has. A console that has no
handler for a path answers a 401 naming it, the status a refused token gets, and the refusal
has to say that the server is older than the method.
"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile

import pytest

from elemctl import cli
from elemctl.errors import ApiError, ElemctlError, UnknownMethodError

APP = "0a1b2c3d-0000-4000-8000-000000000002"
EXPORT_PATH = f"/console/api/v2/applications/{APP}/project/export"

NO_HANDLER = {
    "error": {
        "code": 16,
        "status": "UNAUTHENTICATED",
        "message": f'Handler of HTTP request "[POST] /v2/applications/{APP}/project/export" '
                   'in application "console" not found.',
        "details": [],
    }
}


def _entry(name):
    """An archive entry with a fixed stamp: two archives built a second apart stay equal."""
    return zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))


def _archive(name="crm", version="1.0-9"):
    """A build archive the way the server sends one: directory entries, files, the manifest."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_entry(f"acme/{name}/"), "")
        archive.writestr(_entry(f"acme/{name}/Проект.yaml"), f"Имя: {name}\nПоставщик: acme\n")
        archive.writestr(
            _entry("Assembly.yaml"),
            f"ManifestVersion: 1.0\nProjectKind: Application\nVendor: acme\nName: {name}\n"
            f"Version: {version}\n",
        )
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    """No stand of the developer's leaks in, and the current directory is a scratch one."""
    for key in ("ELEMENT_BASE_URL", "ELEMENT_CLIENT_ID", "ELEMENT_CLIENT_SECRET",
                "ELEMENT_APP_ID", "ELEMENT_PROJECT_ID", "ELEMENT_SPACE_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


# --- the client -----------------------------------------------------------------------------


def test_the_export_posts_to_the_method_of_2_0_and_saves_the_archive_as_it_came(api, tmp_path):
    client, transport = api
    transport.add("POST", EXPORT_PATH, body=_archive())

    report = client.export_app(APP)

    export = transport.calls_to("POST", EXPORT_PATH)
    assert len(export) == 1
    assert export[0]["data"] is None  # the method takes no body
    saved = tmp_path / "crm 1.0-9.xasm"
    assert saved.read_bytes() == _archive()
    assert report == {
        "app-id": APP,
        "file": str(saved.resolve()),
        "size": len(_archive()),
        "manifest": {
            "ManifestVersion": "1.0",
            "ProjectKind": "Application",
            "Vendor": "acme",
            "Name": "crm",
            "Version": "1.0-9",
        },
    }


def test_output_names_a_directory_or_the_file_itself(api, tmp_path):
    client, transport = api
    transport.add("POST", EXPORT_PATH, body=_archive())
    folder = tmp_path / "exports"
    folder.mkdir()

    into_folder = client.export_app(APP, output=str(folder))
    as_file = client.export_app(APP, output=str(tmp_path / "deep" / "app.xasm"))

    assert into_folder["file"] == str((folder / "crm 1.0-9.xasm").resolve())
    assert as_file["file"] == str((tmp_path / "deep" / "app.xasm").resolve())
    assert (tmp_path / "deep" / "app.xasm").read_bytes() == _archive()


def test_an_answer_that_is_no_archive_is_not_saved_under_the_name_of_one(api, tmp_path):
    client, transport = api
    transport.add("POST", EXPORT_PATH, body=b'{"status": "OK"}')

    with pytest.raises(ElemctlError, match="не архив сборки"):
        client.export_app(APP)

    assert not any(path.suffix == ".xasm" for path in tmp_path.rglob("*"))


def test_a_server_without_the_method_is_named_as_such(api):
    """The 401 of a missing handler is not about the token, so no new token is asked for."""
    client, transport = api
    transport.add("POST", EXPORT_PATH, NO_HANDLER, status=401)

    with pytest.raises(UnknownMethodError) as refusal:
        client.export_app(APP)

    error = refusal.value
    assert isinstance(error, ApiError) and error.status == 401
    assert "не знает метода POST" in error.message and "Console API 2.0" in error.message
    assert error.body == NO_HANDLER
    assert len(transport.calls_to("POST", EXPORT_PATH)) == 1
    assert len(transport.calls_to("POST", "/console/sys/token")) == 1


def test_a_refusal_of_the_application_is_raised_as_it_came(api):
    client, transport = api
    transport.add(
        "POST", EXPORT_PATH, {"error": {"message": "Application with id x not found."}},
        status=404,
    )

    with pytest.raises(ApiError) as refusal:
        client.export_app(APP)

    assert refusal.value.status == 404
    assert not isinstance(refusal.value, UnknownMethodError)


# --- the CLI -------------------------------------------------------------------------------


def test_the_command_saves_the_build_and_prints_the_report(api, monkeypatch, tmp_path, capsys):
    client, transport = api
    transport.add("POST", EXPORT_PATH, body=_archive())
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(["apps", "export", APP, "--output", str(tmp_path)])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["file"] == str((tmp_path / "crm 1.0-9.xasm").resolve())
    assert (tmp_path / "crm 1.0-9.xasm").read_bytes() == _archive()


def test_the_command_takes_the_application_from_the_environment(api, monkeypatch, capsys):
    """It only reads the server, so the application defaults the way `apps get` does."""
    client, transport = api
    transport.add("POST", EXPORT_PATH, body=_archive())
    monkeypatch.setenv("ELEMENT_APP_ID", APP)
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(["apps", "export"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["app-id"] == APP


def test_the_command_on_an_old_server_fails_with_the_reason(api, monkeypatch, capsys):
    client, transport = api
    transport.add("POST", EXPORT_PATH, NO_HANDLER, status=401)
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(["apps", "export", APP])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    failure = json.loads(captured.err)
    assert failure["status"] == 401
    assert "Console API 2.0" in failure["error"]


# --- the MCP tool ---------------------------------------------------------------------------


def _mcp_server(monkeypatch, client):
    pytest.importorskip("mcp.server", reason="extra elemctl[mcp] не установлен")
    from elemctl import mcp_server
    from elemctl.config import Config

    monkeypatch.setattr(mcp_server, "ElementClient", lambda config: client)
    return mcp_server.create_server(
        Config(base_url="https://api.test", client_id="cid", client_secret="secret")
    )


def test_the_tool_saves_the_build_the_way_the_command_does(api, monkeypatch, tmp_path):
    client, transport = api
    transport.add("POST", EXPORT_PATH, body=_archive())
    server = _mcp_server(monkeypatch, client)
    from elemctl.mcp_server import call_result_content

    result = asyncio.run(server.call_tool(
        "export_app", {"app_id": APP, "output": str(tmp_path / "app.xasm")},
    ))
    report = json.loads(call_result_content(result)[0].text)

    assert report["file"] == str((tmp_path / "app.xasm").resolve())
    assert (tmp_path / "app.xasm").read_bytes() == _archive()
    assert len(transport.calls_to("POST", EXPORT_PATH)) == 1


def test_the_tool_says_what_it_does_and_what_it_takes(monkeypatch, api):
    client, _transport = api
    server = _mcp_server(monkeypatch, client)
    from elemctl.mcp_server import tool_input_schema

    tool = next(tool for tool in asyncio.run(server.list_tools()) if tool.name == "export_app")
    description = tool.description or ""
    assert "чтения" in description and "export_extension" in description
    assert set(tool_input_schema(tool).get("required") or []) == {"app_id"}
