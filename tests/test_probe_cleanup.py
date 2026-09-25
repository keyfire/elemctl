"""Removing a probe left on the stand, starting from its application.

A probe kept with --keep used to take three commands and a reading of the platform's rules to
remove: `builds delete` without `--project-id` looked for the build in the project of the
environment and answered "not found", and the build could only go once the application was
really gone. `probe --cleanup` does the whole of it in order, and touches nothing a probe did
not leave: the tests pin the order, the project the build is looked for in, the refusals and
what a second run does after a first one that stopped halfway.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from elemctl import cli
from elemctl.errors import ApiError, ElemctlError
from elemctl.probe import cleanup_probe

APP = "app-probe"
PROJECT = "proj-9"
TOKEN = "abc1d2e3"
PROBE_VERSION = f"1.0-probe-{TOKEN}"


def _card(*, name=f"elemctl-probe-{TOKEN}", status="Running", version=PROBE_VERSION,
          app_id=APP, project=PROJECT, build="asm-probe"):
    return {
        "id": app_id,
        "name": name,
        "status": status,
        "project": {"id": project},
        "source": {"type": "image", "image-id": project, "project-version-id": build,
                   "project-version": version},
    }


class FakeCleanupClient:
    """The client methods the cleanup uses, over a small stand held in memory."""

    def __init__(self, cards, builds, *, projects=None, gone=True, app_id="", project_id=""):
        self.cards = [dict(card) for card in cards]
        self.builds = {key: list(value) for key, value in builds.items()}
        self.projects = projects if projects is not None else [{"id": PROJECT}]
        self.gone = gone
        self.config = SimpleNamespace(app_id=app_id, project_id=project_id)
        self.calls = []

    def list_apps(self, include_deleted=False):
        return [card for card in self.cards
                if include_deleted or card.get("status") != "Deleted"]

    def delete_app(self, app_id):
        self.calls.append(("delete_app", app_id))

    def wait_app_deleted(self, app_id, log=None):
        self.calls.append(("wait_app_deleted", app_id))
        if self.gone:
            for card in self.cards:
                if card["id"] == app_id:
                    card["status"] = "Deleted"
        return self.gone

    def list_assemblies(self, project_id):
        self.calls.append(("list_assemblies", project_id))
        return [{"id": build_id, "assembly-version": version}
                for build_id, version in self.builds.get(project_id, [])]

    def delete_assembly(self, project_id, version):
        self.calls.append(("delete_assembly", project_id, version))
        self.builds[project_id] = [
            item for item in self.builds.get(project_id, []) if item[1] != version
        ]

    def list_projects(self, include_deleted=False):
        return self.projects

    def delete_project(self, project_id):
        self.calls.append(("delete_project", project_id))

    def names(self):
        return [call[0] for call in self.calls]


def _stand(**kwargs):
    builds = kwargs.pop("builds", {PROJECT: [("asm-probe", PROBE_VERSION)]})
    cards = kwargs.pop("cards", [_card()])
    return FakeCleanupClient(cards, builds, **kwargs)


def test_everything_goes_in_the_platforms_order():
    client = _stand(project_id="proj-work")

    report = cleanup_probe(client, APP)

    assert report.ok is True
    assert [call for call in client.calls if call[0] != "list_assemblies"] == [
        ("delete_app", APP),
        ("wait_app_deleted", APP),
        # The build is addressed in the probe's own project, not in the one of the environment.
        ("delete_assembly", PROJECT, PROBE_VERSION),
        ("delete_project", PROJECT),
    ]
    answer = report.to_dict()
    assert answer["app-deleted"] is True and answer["project-deleted"] is True
    assert answer["builds"] == [{"id": "asm-probe", "version": PROBE_VERSION, "deleted": True}]


def test_an_application_that_is_not_a_probes_is_refused():
    client = _stand(cards=[_card(name="crm-dev", version="1.0-42")])

    with pytest.raises(ElemctlError, match="elemctl-probe-"):
        cleanup_probe(client, APP)
    assert client.calls == []


def test_the_working_application_is_refused_even_under_a_probe_name():
    client = _stand(app_id=APP)

    with pytest.raises(ElemctlError, match="ELEMENT_APP_ID"):
        cleanup_probe(client, APP)
    assert "delete_app" not in client.names()


def test_a_probe_named_by_hand_is_known_by_its_build():
    client = _stand(cards=[_card(name="compile-check")])

    report = cleanup_probe(client, APP)

    assert report.ok is True
    assert ("delete_assembly", PROJECT, PROBE_VERSION) in client.calls


def test_the_project_stays_while_other_builds_live_in_it():
    """A probe usually lands in the project that owns the sources - the working one."""
    client = _stand(builds={PROJECT: [("asm-probe", PROBE_VERSION), ("asm-41", "1.0-41")]})

    report = cleanup_probe(client, APP)

    assert report.ok is True
    assert ("delete_assembly", PROJECT, PROBE_VERSION) in client.calls
    assert "delete_project" not in client.names()
    assert report.project_deleted is None and "1.0-41" in report.project_kept


def test_the_project_stays_while_an_application_runs_it():
    other = _card(name="crm-dev", app_id="app-crm", version="1.0-7", build="asm-7")
    client = _stand(cards=[_card(), other])

    report = cleanup_probe(client, APP)

    assert "delete_project" not in client.names()
    assert "crm-dev" in report.project_kept


def test_the_project_of_the_environment_stays_even_when_empty():
    client = _stand(project_id=PROJECT)

    report = cleanup_probe(client, APP)

    assert "delete_project" not in client.names()
    assert "ELEMENT_PROJECT_ID" in report.project_kept


def test_only_the_build_of_this_probe_is_taken():
    other = "1.0-probe-ffff0000"
    client = _stand(builds={PROJECT: [("asm-probe", PROBE_VERSION), ("asm-other", other)]})

    report = cleanup_probe(client, APP)

    deleted = [call[2] for call in client.calls if call[0] == "delete_assembly"]
    assert deleted == [PROBE_VERSION]
    assert other in report.project_kept


def test_a_second_run_finishes_what_the_first_one_left():
    """The application is a tombstone already; the build and the project are still there."""
    client = _stand(cards=[_card(status="Deleted")])

    report = cleanup_probe(client, APP)

    assert report.ok is True and report.app_deleted is True
    assert "delete_app" not in client.names()
    assert ("delete_assembly", PROJECT, PROBE_VERSION) in client.calls
    assert ("delete_project", PROJECT) in client.calls


def test_a_tombstone_is_found_by_its_name():
    client = _stand(cards=[_card(status="Deleted")])

    report = cleanup_probe(client, f"elemctl-probe-{TOKEN}")

    assert report.app_id == APP


def test_an_application_that_does_not_go_stops_the_cleanup():
    client = _stand(gone=False)

    report = cleanup_probe(client, APP)

    assert report.ok is False and report.app_deleted is False
    assert "delete_assembly" not in client.names()
    assert "delete_project" not in client.names()
    assert any("probe --cleanup" in problem for problem in report.problems)


def test_a_project_deleted_already_is_not_deleted_again():
    client = _stand(builds={}, projects=[{"id": PROJECT, "deleted": True}])

    report = cleanup_probe(client, APP)

    assert report.ok is True and report.project_deleted is True
    assert "delete_project" not in client.names()


def test_a_failed_deletion_of_the_build_keeps_the_project_and_the_verdict_says_so():
    client = _stand()

    def refuse(project_id, version):
        client.calls.append(("delete_assembly", project_id, version))
        raise ApiError("Console API ответил 500", status=500)

    client.delete_assembly = refuse

    report = cleanup_probe(client, APP)

    assert report.ok is False
    assert report.builds[0]["deleted"] is False
    assert "delete_project" not in client.names()


# --- the CLI and the MCP tool -----------------------------------------------------------

def test_cli_cleanup_prints_the_report(monkeypatch, capsys):
    client = _stand()
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(["probe", "--cleanup", APP])

    assert rc == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is True and answer["project-deleted"] is True


def test_cli_cleanup_refuses_the_options_of_a_run(monkeypatch, capsys):
    client = _stand()
    monkeypatch.setattr(cli, "make_client", lambda config: client)

    rc = cli.main(["probe", "--cleanup", APP, "--keep", "--name", "x"])

    assert rc == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "--keep" in error and "--name" in error
    assert client.calls == []


def test_cli_cleanup_that_did_not_finish_ends_with_one(monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_client", lambda config: _stand(gone=False))
    assert cli.main(["probe", "--cleanup", APP]) == 1


def test_mcp_probe_cleanup(monkeypatch):
    pytest.importorskip("mcp.server", reason="extra elemctl[mcp] не установлен")
    from elemctl import mcp_server
    from elemctl.config import Config

    client = _stand()
    monkeypatch.setattr(mcp_server, "ElementClient", lambda config: client)
    server = mcp_server.create_server(
        Config(base_url="https://api.test", client_id="cid", client_secret="secret")
    )

    result = asyncio.run(server.call_tool("probe_cleanup", {"app_id": APP}))
    payload = json.loads(mcp_server.call_result_content(result)[0].text)

    assert payload["ok"] is True and payload["log"]
