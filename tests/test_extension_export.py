"""The export of an extension build: Console API 2.1, the CLI command and the MCP tool.

The method lives in Console API 2.1 alone, while the rest of the client stays on 2.0, so the
prefix of every request is checked here. A console that has no handler for a path answers a
401 naming it, the status a refused token gets; the refusal has to say that the server is
older than the method, not send the reader to the keys.
"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile

import pytest

from elemctl import cli
from elemctl.errors import ApiError, ConfigError, ElemctlError, UnknownMethodError

API_2_1 = "/console/api/v2.1"
APP = "0a1b2c3d-0000-4000-8000-000000000001"
EXTENSION_ID = "0a1b2c3d-0000-4000-8000-0000000000e1"
PROJECT_ID = "0a1b2c3d-0000-4000-8000-0000000000aa"
PROJECT_PATH = f"{API_2_1}/applications/{APP}/project"
EXPORT_PATH = f"{API_2_1}/applications/{APP}/project/{EXTENSION_ID}/export"

EXTENSION = {
    "id": EXTENSION_ID,
    "project-id": PROJECT_ID,
    "assembly-id": PROJECT_ID,
    "enabled": True,
    "order": 1,
    "vendor-name": "acme",
    "vendor-presentation": "Acme",
    "project-name": "CrmExtras",
    "project-presentation": "CRM extras",
    "project-version": "1.0",
    "assembly-version": "1.0-3",
}

# What a console without a handler for the path answers - the text of a live answer, with the
# path of this test in it.
NO_HANDLER = {
    "error": {
        "code": 16,
        "status": "UNAUTHENTICATED",
        "message": 'Handler of HTTP request "[GET] /v2.1/applications/x/project" in '
                   'application "console" not found.',
        "details": [],
    }
}


def _entry(name):
    """An archive entry with a fixed stamp: two archives built a second apart stay equal."""
    return zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))


def _archive(name="CrmExtras", version="1.0-3"):
    """A build archive the way the server sends one: the manifest and the project."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            _entry("Assembly.yaml"),
            "ManifestVersion: 1.1\nProjectKind: Extension\n"
            f"Vendor: acme\nName: {name}\nVersion: {version}\n",
        )
        archive.writestr(_entry(f"acme/{name}/Проект.yaml"), "ВидПроекта: Расширение\n")
    return buffer.getvalue()


def _serve(transport, extensions=(EXTENSION,), body=None):
    transport.add("GET", PROJECT_PATH, {
        "application-project": {"project-name": "crm", "assembly-version": "1.0-9"},
        "extension-projects": list(extensions),
    })
    transport.add("POST", EXPORT_PATH, body=_archive() if body is None else body)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    """No stand of the developer's leaks in, and the current directory is a scratch one."""
    for key in ("ELEMENT_BASE_URL", "ELEMENT_CLIENT_ID", "ELEMENT_CLIENT_SECRET",
                "ELEMENT_APP_ID", "ELEMENT_PROJECT_ID", "ELEMENT_SPACE_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


# --- the client -----------------------------------------------------------------------------


def test_the_extensions_of_an_application_are_read_from_console_api_2_1(api):
    """2.0 answers the same path with the application project alone."""
    client, transport = api
    _serve(transport)

    extensions = client.list_app_extensions(APP)

    assert extensions == [EXTENSION]
    assert [call["path"] for call in transport.calls if call["method"] == "GET"] == [PROJECT_PATH]


def test_the_export_posts_to_the_method_of_2_1_and_saves_the_archive_as_it_came(api, tmp_path):
    client, transport = api
    _serve(transport)

    report = client.export_extension(APP, "CrmExtras")

    export = transport.calls_to("POST", EXPORT_PATH)
    assert len(export) == 1
    assert export[0]["data"] is None  # the method takes no body
    saved = tmp_path / "CrmExtras 1.0-3.xasm"
    assert saved.read_bytes() == _archive()
    assert report["file"] == str(saved.resolve())
    assert report["size"] == len(_archive())
    assert report["extension-id"] == EXTENSION_ID
    assert report["project-id"] == PROJECT_ID
    assert report["app-id"] == APP
    assert report["manifest"]["ProjectKind"] == "Extension"
    assert report["manifest"]["Version"] == "1.0-3"


@pytest.mark.parametrize("reference", [PROJECT_ID, "crmextras", "CRM Extras", EXTENSION_ID.upper()])
def test_any_name_of_the_extension_leads_to_the_id_the_server_knows_it_by(api, reference):
    """The segment of the path is the `id` of the extension, whatever the caller gave."""
    client, transport = api
    _serve(transport)

    client.export_extension(APP, reference)

    assert len(transport.calls_to("POST", EXPORT_PATH)) == 1


def test_an_extension_the_application_has_not_got_is_named_with_the_ones_it_has(api):
    """The export answers a wrong id with a 500 that says nothing, so the miss is named first."""
    client, transport = api
    _serve(transport)

    with pytest.raises(ConfigError) as refusal:
        client.export_extension(APP, "billing")

    message = str(refusal.value)
    assert "billing" in message
    assert "acme/CrmExtras 1.0-3" in message and EXTENSION_ID in message
    assert not transport.calls_to("POST", EXPORT_PATH)


def test_an_application_without_extensions_says_it_has_none(api):
    client, transport = api
    _serve(transport, extensions=())

    with pytest.raises(ConfigError, match="ни одного"):
        client.export_extension(APP, "CrmExtras")


def test_two_extensions_under_one_name_are_not_guessed_between(api):
    client, transport = api
    other = {**EXTENSION, "id": "0a1b2c3d-0000-4000-8000-0000000000bb", "vendor-name": "globex"}
    _serve(transport, extensions=(EXTENSION, other))

    with pytest.raises(ConfigError) as refusal:
        client.export_extension(APP, "CrmExtras")

    assert "acme/CrmExtras" in str(refusal.value) and "globex/CrmExtras" in str(refusal.value)
    assert not transport.calls_to("POST", EXPORT_PATH)


def test_an_extension_the_console_named_no_id_for_is_not_sent_as_none(api):
    """The segment is the id; without one the export would get the bare 500 of a miss."""
    client, transport = api
    _serve(transport, extensions=({**EXTENSION, "id": None},))

    with pytest.raises(ElemctlError, match="не назвала ид"):
        client.export_extension(APP, "CrmExtras")

    assert not [call for call in transport.calls if call["method"] == "POST"
                and call["path"] != "/console/sys/token"]


def test_a_server_without_console_api_2_1_is_named_as_such(api):
    """The 401 of a missing handler is not about the token, so no new token is asked for."""
    client, transport = api
    transport.add("GET", PROJECT_PATH, NO_HANDLER, status=401)

    with pytest.raises(UnknownMethodError) as refusal:
        client.export_extension(APP, "CrmExtras")

    error = refusal.value
    assert isinstance(error, ApiError) and error.status == 401
    assert "не знает метода GET" in error.message and "Console API 2.1" in error.message
    assert error.body == NO_HANDLER
    assert len(transport.calls_to("GET", PROJECT_PATH)) == 1
    assert len(transport.calls_to("POST", "/console/sys/token")) == 1
    assert not transport.calls_to("POST", EXPORT_PATH)


def test_a_server_that_lacks_the_export_alone_is_named_too(api):
    client, transport = api
    transport.add("GET", PROJECT_PATH, {"extension-projects": [EXTENSION]})
    transport.add("POST", EXPORT_PATH, NO_HANDLER, status=401)

    with pytest.raises(UnknownMethodError, match="не знает метода POST"):
        client.export_extension(APP, "CrmExtras")


def test_a_refused_token_is_not_taken_for_an_unknown_method(api):
    client, transport = api
    transport.add("GET", PROJECT_PATH, {"error": {"message": "Token expired"}}, status=401)

    with pytest.raises(ApiError) as refusal:
        client.list_app_extensions(APP)

    assert not isinstance(refusal.value, UnknownMethodError)


def test_an_answer_that_is_no_archive_is_not_saved_under_the_name_of_one(api, tmp_path):
    client, transport = api
    _serve(transport, body=b'{"status": "OK"}')

    with pytest.raises(ElemctlError, match="не архив сборки"):
        client.export_extension(APP, "CrmExtras")

    assert not any(path.suffix == ".xasm" for path in tmp_path.rglob("*"))


def test_output_names_a_directory_or_the_file_itself(api, tmp_path):
    client, transport = api
    _serve(transport)
    folder = tmp_path / "exports"
    folder.mkdir()

    into_folder = client.export_extension(APP, "CrmExtras", output=str(folder))
    as_file = client.export_extension(
        APP, "CrmExtras", output=str(tmp_path / "deep" / "ext.xasm")
    )

    assert into_folder["file"] == str((folder / "CrmExtras 1.0-3.xasm").resolve())
    assert as_file["file"] == str((tmp_path / "deep" / "ext.xasm").resolve())
    assert (tmp_path / "deep" / "ext.xasm").read_bytes() == _archive()


# --- the CLI -------------------------------------------------------------------------------


def test_the_command_saves_the_build_and_prints_the_report(api, monkeypatch, tmp_path, capsys):
    client, transport = api
    _serve(transport)
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(["apps", "export-extension", APP, "CrmExtras", "--output", str(tmp_path)])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["file"] == str((tmp_path / "CrmExtras 1.0-3.xasm").resolve())
    assert (tmp_path / "CrmExtras 1.0-3.xasm").read_bytes() == _archive()


def test_the_command_takes_the_application_from_the_environment(api, monkeypatch, capsys):
    """It only reads the server, so the application defaults the way `apps get` does."""
    client, transport = api
    _serve(transport)
    monkeypatch.setenv("ELEMENT_APP_ID", APP)
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(["apps", "export-extension", "CrmExtras"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["app-id"] == APP


def test_the_command_on_an_old_server_fails_with_the_reason(api, monkeypatch, capsys):
    client, transport = api
    transport.add("GET", PROJECT_PATH, NO_HANDLER, status=401)
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(["apps", "export-extension", APP, "CrmExtras"])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    failure = json.loads(captured.err)
    assert failure["status"] == 401
    assert "Console API 2.1" in failure["error"]


def test_the_command_names_the_extensions_the_application_has(api, monkeypatch, capsys):
    client, transport = api
    _serve(transport)
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(["apps", "export-extension", APP, "billing"])

    assert rc == 1
    assert "acme/CrmExtras 1.0-3" in json.loads(capsys.readouterr().err)["error"]


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
    _serve(transport)
    server = _mcp_server(monkeypatch, client)
    from elemctl.mcp_server import call_result_content

    result = asyncio.run(server.call_tool(
        "export_extension",
        {"app_id": APP, "extension": "CrmExtras", "output": str(tmp_path / "ext.xasm")},
    ))
    report = json.loads(call_result_content(result)[0].text)

    assert report["file"] == str((tmp_path / "ext.xasm").resolve())
    assert (tmp_path / "ext.xasm").read_bytes() == _archive()
    assert len(transport.calls_to("POST", EXPORT_PATH)) == 1


def test_the_tool_says_what_it_does_and_what_it_takes(monkeypatch, api):
    client, _transport = api
    server = _mcp_server(monkeypatch, client)
    from elemctl.mcp_server import tool_input_schema

    tool = next(
        tool for tool in asyncio.run(server.list_tools()) if tool.name == "export_extension"
    )
    description = tool.description or ""
    assert "Console API 2.1" in description and "чтения" in description
    schema = tool_input_schema(tool)
    assert set(schema.get("required") or []) == {"app_id", "extension"}
