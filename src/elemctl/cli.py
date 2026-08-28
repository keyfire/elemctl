"""The elemctl command-line interface.

Output conventions: the result is JSON on stdout (ensure_ascii=False, indent 2);
the progress of long operations is lines on stderr; an error is JSON with an
error field on stderr and exit code 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, i18n, plugins
from .build import (
    build_assembly,
    find_project_dir,
    git_dirty_files,
    inspect_assembly,
    read_assembly_manifest,
    read_assembly_project,
)
from .client import (
    CALCULATION_RULE_FIELDS,
    OIDC_SERVICE,
    ElementClient,
    brief_app,
    brief_assembly,
    extract_assembly_id,
    sign_in_hint,
)
from .config import Config
from .deploy import deploy_from_sources, verify_deploy
from .errors import ApiError, ConfigError, ElemctlError, PluginError
from .probe import probe_project
from .versions import newest_first


def make_client(config):
    """The client factory; extracted so that the tests can substitute it."""
    return ElementClient(config)


# -- output --------------------------------------------------------------------


def _emit(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _progress(message):
    print(message, file=sys.stderr)


def _fail(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    return 1


def _reconfigure_streams():
    """Switch the console output to UTF-8 – otherwise Cyrillic breaks on Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


# -- configuration and identifier resolution -----------------------------------


def _config(args):
    return Config.from_env(
        env_file=args.env_file,
        base_url=args.base_url,
        client_id=args.client_id,
        client_secret=args.client_secret,
        timeout=args.timeout,
    )


def _require(explicit, fallback, what):
    """Take the explicit value or the one from the configuration; otherwise an error."""
    value = explicit or fallback
    if not value:
        raise ConfigError(i18n.t("cli.not-set", what=what))
    return value


def _require_with_source(explicit, fallback, what):
    """The same value plus where it came from: "flag" or "env".

    The source matters for the deploy report: a target taken from the environment
    is exactly the case in which one deploys to the wrong application without
    noticing, so it must not look the same as an explicitly given one.
    """
    if explicit:
        return explicit, "flag"
    if fallback:
        return fallback, "env"
    raise ConfigError(i18n.t("cli.not-set", what=what))


def _ensure_clean_tree(project_dir):
    """Abort the work when the project directory has uncommitted changes.

    The check runs before the build and all the more before the upload:
    --require-clean promises that exactly the state of HEAD goes into the archive.
    An unavailable git is a refusal as well: in that case there is nothing to
    confirm a clean tree with.
    """
    directory = find_project_dir(project_dir)
    dirty = git_dirty_files(directory)
    if dirty is None:
        raise ElemctlError(i18n.t("cli.require-clean-no-git", dir=directory))
    if dirty:
        raise ElemctlError(
            i18n.t("cli.require-clean-dirty", dir=directory, count=len(dirty))
        )


# -- command handlers ----------------------------------------------------------


def cmd_token(args):
    client = make_client(_config(args))
    _emit({"token": client.token()})
    return 0


def cmd_apps_list(args):
    client = make_client(_config(args))
    apps = client.list_apps(name=args.name or "")
    if args.brief:
        apps = [brief_app(app) for app in apps if isinstance(app, dict)]
    _emit(apps)
    return 0


def cmd_apps_get(args):
    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    _emit(client.get_app(client.resolve_app_id(app_id)))
    return 0


def cmd_apps_find(args):
    """Look an application up by name. A missing application is an answer, not an error.

    The exit code is 0 in both cases: the found field carries the verdict. A non-zero exit
    code means the request itself failed (no access, network, configuration) and comes with
    JSON carrying an error field on stderr – otherwise the caller cannot tell "there is no
    stand" from "we failed to ask".

    Deleted applications (status Deleted) are skipped by default, so that the id found is fit
    for work; the --include-deleted flag brings the search back to all the applications.
    """
    client = make_client(_config(args))
    app = client.find_app(args.name, include_deleted=args.include_deleted)
    if app is None:
        _emit({"id": None, "found": False})
        return 0
    _emit({"id": app.get("id"), "found": True})
    return 0


def _create_app_from_args(client, config, args):
    """Create an application from the creation flags; return its card.

    The logic shared by apps create and apps ensure. The source is the given
    assembly (--version-id), the project's latest assembly (--latest-build) or
    the project as a whole (--project-id, which risks an empty skeleton). With
    --wait it waits until the application is ready.
    """
    project_id = args.project_id or config.project_id
    version_id = args.version_id

    if args.latest_build and not version_id:
        if not project_id:
            raise ConfigError(i18n.t("cli.latest-build-needs-project"))
        latest = client.latest_assembly(project_id)
        if latest is None:
            raise ElemctlError(
                i18n.t("cli.project-has-no-builds", project_id=project_id)
            )
        version_id = extract_assembly_id(latest)

    kwargs = {
        "development_mode": not args.no_dev_mode,
        "space_id": args.space_id or config.space_id or None,
        "technology_version": args.tech_version or None,
    }
    if version_id:
        card = client.create_app(args.name, project_version_id=version_id, **kwargs)
    elif project_id:
        _progress(i18n.t("cli.whole-project-source-warning"))
        card = client.create_app(args.name, image_id=project_id, **kwargs)
    else:
        raise ConfigError(i18n.t("cli.app-source-required"))

    if args.wait:
        app_id = (card or {}).get("id")
        if app_id:
            card = client.wait_app_ready(app_id, log=_progress)
    return card


def _report_sign_in(card):
    """Say out loud how to sign in to the application; return the same as a field.

    A stand nobody can get into is not a ready stand, and the way in is not
    guessable: the accounts used elsewhere do not work in a fresh application
    (client.sign_in_hint). The text goes to stderr, where the rest
    of the progress goes, and the machine-readable twin goes into the JSON – an
    agent reading only stdout must learn it too.
    """
    hint = sign_in_hint(card)
    _progress(hint["hint"])
    _progress(hint["note"])
    return hint


def cmd_apps_create(args):
    config = _config(args)
    client = make_client(config)
    card = _create_app_from_args(client, config, args)
    hint = _report_sign_in(card)
    _emit({**card, "sign-in": hint} if isinstance(card, dict) else card)
    return 0


def _applied_assembly_id(card):
    """The assembly the application currently runs, out of its card ("" when unknown)."""
    return str(((card or {}).get("source") or {}).get("project-version-id") or "")


def _apply_and_verify(client, app_id, version_id):
    """Apply the assembly, wait for the application and check that it really landed.

    Applying is not a fact until it is verified: on a failure the platform silently
    rolls the application back to the previous build and starts it, so a status of
    Running says nothing about the assembly that was asked for.
    """
    started_at = datetime.now(timezone.utc)
    client.apply_build(app_id, image_id=version_id)
    _progress(i18n.t("cli.apply.started", version_id=version_id))
    client.ensure_running(app_id, log=_progress)
    return verify_deploy(
        client, app_id, expected_assembly_id=version_id, since=started_at, log=_progress
    )


def cmd_apps_apply(args):
    """Apply an already uploaded assembly to an application and verify the result."""
    config = _config(args)
    client = make_client(config)
    app_id = client.resolve_app_id(
        _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    )
    report = _apply_and_verify(client, app_id, args.version_id)
    _emit(report.to_dict())
    return 0 if report.ok else 1


def cmd_apps_ensure(args):
    """Idempotently bring an application with the given name into existence.

    It looks the application up by the rules of apps find (deleted ones, in
    status Deleted, do not count): if it is already there – it does nothing and
    returns created: false; if it is not – it creates one from the creation flags
    and returns created: true. An existing application is never re-created:
    delete + create give a new URL and break the external links to the previous
    one. The exit code is 0 in both cases; a failed request is JSON with an error
    field on stderr and exit code 1.

    The creation flags act on creation alone, and --version-id is one of them.
    That silence cost a stand: ensure over an existing application answered
    created: false and exit code 0 while the assembly stayed the previous one,
    and nothing in the answer said so. Now the answer carries applied - whether
    the application runs the requested assembly - and, when it does not, names
    the way to bring it there; with --apply the same run does it.

    Both answers end with the way into the application (the sign-in field and
    the same on stderr): the caller of ensure is usually raising a stand, and a
    stand nobody can sign in to is not raised yet.
    """
    config = _config(args)
    client = make_client(config)
    existing = client.find_app(args.name)
    if existing is not None:
        answer = {
            "id": existing.get("id"),
            "created": False,
            "sign-in": _report_sign_in(existing),
        }
        answer.update(_ensure_build_state(client, existing, args))
        _emit(answer)
        return 0
    card = _create_app_from_args(client, config, args)
    _emit({
        "id": (card or {}).get("id"),
        "created": True,
        "applied": True,
        "sign-in": _report_sign_in(card),
    })
    return 0


def _ensure_build_state(client, existing, args):
    """What ensure has to say about the ASSEMBLY of an application it did not create.

    Nothing when no assembly was asked for - ensure was then about existence alone.
    """
    requested = str(args.version_id or "")
    if not requested:
        return {}
    app_id = str(existing.get("id") or "")
    applied = _applied_assembly_id(existing)
    if applied and applied == requested:
        _progress(i18n.t("cli.ensure.build-already", requested=requested))
        return {"applied": True, "applied-version-id": applied}
    if args.apply:
        report = _apply_and_verify(client, app_id, requested)
        return {"applied": bool(report.ok), "verify": report.to_dict()}
    _progress(i18n.t(
        "cli.ensure.build-differs",
        applied=applied or i18n.t("deploy.unknown"),
        requested=requested,
        app_id=app_id,
    ))
    return {"applied": False, "applied-version-id": applied}


def cmd_apps_delete(args):
    client = make_client(_config(args))
    app_id = client.resolve_app_id(args.app_id)
    response = client.delete_app(app_id)
    _emit(response if response is not None else {"deleted": True, "app-id": app_id})
    return 0


def cmd_apps_debug(args):
    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    _emit(client.get_debug_info(client.resolve_app_id(app_id)) or {})
    return 0


def cmd_apps_start(args):
    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    app_id = client.resolve_app_id(app_id)
    response = client.start_app(app_id)
    _emit(response if response is not None else {"ok": True, "app-id": app_id})
    return 0


def cmd_apps_stop(args):
    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    app_id = client.resolve_app_id(app_id)
    response = client.stop_app(app_id)
    _emit(response if response is not None else {"ok": True, "app-id": app_id})
    return 0


def cmd_spaces_list(args):
    client = make_client(_config(args))
    _emit(client.list_spaces())
    return 0


def cmd_projects_list(args):
    client = make_client(_config(args))
    _emit(client.list_projects())
    return 0


def cmd_projects_get(args):
    config = _config(args)
    client = make_client(config)
    project_id = _require(
        args.project_id, config.project_id, i18n.t("cli.require.project-id-arg")
    )
    _emit(client.get_project(project_id))
    return 0


def cmd_projects_delete(args):
    client = make_client(_config(args))
    response = client.delete_project(args.project_id)
    _emit(response if response is not None else {"deleted": True, "project-id": args.project_id})
    return 0


def cmd_builds_list(args):
    """The project's assemblies, newest first and limited by default.

    A long-lived project alone holds over a thousand assemblies: printing them all
    made the answer to "which commit is the applied build from" a matter of
    piping through head and hoping the right card made the cut. The default
    shows the latest ten; --limit 0 brings the whole list back, and the cut is
    never silent - the count of what was left out goes to stderr.
    """
    config = _config(args)
    client = make_client(config)
    project_id = _require(
        args.project_id, config.project_id, i18n.t("cli.require.project-id-flag")
    )
    assemblies = newest_first(client.list_assemblies(project_id))
    total = len(assemblies)
    if args.limit > 0 and total > args.limit:
        assemblies = assemblies[: args.limit]
        _progress(i18n.t("cli.builds-list-truncated", shown=len(assemblies), total=total))
    if args.brief:
        assemblies = [brief_assembly(assembly) for assembly in assemblies]
    _emit(assemblies)
    return 0


def cmd_builds_get(args):
    config = _config(args)
    client = make_client(config)
    project_id = _require(
        args.project_id, config.project_id, i18n.t("cli.require.project-id-flag")
    )
    _emit(client.get_assembly(project_id, args.version))
    return 0


def _upload_target(args, config):
    """The target project of the upload and the source of that choice.

    The sources: "flag" – the --project-id flag, "env" – ELEMENT_PROJECT_ID from
    the environment or the .env file, None – no project is set, the platform will
    create a new one. The --new-project flag switches the binding from the
    environment off; together with --project-id it is contradictory, which is a
    call error.
    """
    if args.new_project:
        if args.project_id:
            raise ElemctlError(i18n.t("cli.upload-new-project-conflict"))
        return None, None
    if args.project_id:
        return args.project_id, "flag"
    if config.project_id:
        return config.project_id, "env"
    return None, None


def _upload_name_mismatch(client, project_id, file_path):
    """The names of the assembly and of the target project when they differ.

    The console shows the project under the name of the LAST uploaded assembly, so
    a foreign assembly renames the project and its group. Returns None when the
    names match or when they cannot be compared: not being able to compare is no
    proof of danger, and an unreadable manifest or an unreachable project card must
    not stand in the way of an upload.

    Compared is what the console actually shows against what this archive would put
    there - the PRESENTATION of its project descriptor. The technical name of the
    manifest is a different thing: a project named `crm` is shown as "Acme CRM",
    and comparing those two called every correct upload a rename and refused
    it. The manifest name answers only when the archive carries no descriptor.
    """
    try:
        identity = read_assembly_project(file_path)
        assembly_name = identity["presentation"] or identity["name"]
        project_card = client.get_project(project_id) or {}
        project_name = (project_card.get("name") or "").strip()
    except Exception:
        return None
    if not assembly_name or not project_name or assembly_name == project_name:
        return None
    return {"assembly": assembly_name, "project": project_name, "project_id": project_id}


def cmd_builds_upload(args):
    config = _config(args)
    client = make_client(config)
    file_path = Path(args.file)
    if not file_path.is_file():
        raise ElemctlError(i18n.t("cli.build-file-not-found", path=file_path))
    project_id, project_id_source = _upload_target(args, config)
    if project_id_source == "env":
        _progress(i18n.t("cli.upload-target-from-env", project_id=project_id))
    if project_id:
        # A name mismatch is far more often a slip than an intent: the target came from
        # ELEMENT_PROJECT_ID, and the assembly is someone else's. Until now the mismatch
        # was only printed a moment before the irreversible act, and in the flow that reads
        # as a hint rather than as a fork - so it now takes an explicit --force-rename.
        mismatch = _upload_name_mismatch(client, project_id, file_path)
        if mismatch and not args.force_rename:
            raise ElemctlError(i18n.t("cli.upload-name-mismatch", **mismatch))
        if mismatch:
            _progress(i18n.t("cli.upload-name-mismatch-forced", **mismatch))
    # The branch and the commit live in the MANIFEST inside the archive - the build wrote
    # them there. They are not sent alongside: the documented upload method has no such
    # parameters, and the server ignores them when sent (a direct POST with a real hash
    # answered commit-id: null) - the commit of an assembly card comes from the project's
    # link to its repository.
    response = client.upload_assembly(
        file_path.read_bytes(),
        project_id=project_id,
        space_id=args.space_id or config.space_id or None,
    )
    _emit(
        {
            "assembly-id": extract_assembly_id(response),
            "project-id": project_id,
            "project-id-source": project_id_source,
            "response": response,
        }
    )
    return 0


def cmd_builds_delete(args):
    config = _config(args)
    client = make_client(config)
    project_id = _require(
        args.project_id, config.project_id, i18n.t("cli.require.project-id-flag")
    )
    response = client.delete_assembly(project_id, args.version)
    _emit(response if response is not None else {"deleted": True, "version": args.version})
    return 0


def _build_result_dict(result):
    """The dictionary of the build result for the JSON output.

    The version is given as separate fields, so that CI does not have to dig it
    out of the file name; version-source answers the question "where it came from".
    """
    return {
        "file": str(result.file),
        "name": result.name,
        "vendor": result.vendor,
        "version": result.version,
        "version-source": result.version_source,
        "kind": result.kind,
        "branch": result.branch,
        "commit": result.commit,
        "dirty": None if result.dirty_files is None else bool(result.dirty_files),
        "skipped-files": list(result.skipped_files),
    }


def cmd_build(args):
    if args.require_clean:
        _ensure_clean_tree(args.project_dir)
    result = build_assembly(
        args.project_dir,
        output_dir=args.output,
        version=args.build_version or "",
        last_build_version=args.last_build or "",
        branch=args.branch,
        commit=args.commit,
        kind=args.kind or "",
    )
    if result.skipped_files:
        # The JSON carries the list; the warning goes to the progress stream, where
        # a person actually sees it.
        _progress(i18n.t(
            "deploy.skipped-files",
            count=len(result.skipped_files),
            files=", ".join(result.skipped_files[:5]),
        ))
    _emit(_build_result_dict(result))
    return 0


def cmd_inspect(args):
    _emit(inspect_assembly(args.file))
    return 0


def _dry_run_target(args):
    """The target a real deploy would take, for the --dry-run report.

    Softly: --dry-run only builds an archive and must keep working without any
    configuration at all, so an unreadable .env leaves the target fields empty
    instead of failing the build.
    """
    try:
        config = _config(args)
    except ConfigError:
        return {}
    app_id = args.app_id or config.app_id or ""
    project_id = args.project_id or config.project_id or ""
    return {
        "app-id": app_id,
        "app-id-source": ("flag" if args.app_id else "env" if app_id else ""),
        "project-id": project_id,
        "project-id-source": ("flag" if args.project_id else "env" if project_id else ""),
    }


def cmd_deploy(args):
    if args.require_clean:
        _ensure_clean_tree(args.project_dir)
    if args.dry_run:
        result = build_assembly(
            args.project_dir,
            output_dir=args.output,
            version=args.build_version or "",
            branch=args.branch,
            commit=args.commit,
        )
        report = _build_result_dict(result)
        report.update(_dry_run_target(args))
        _emit(report)
        return 0

    config = _config(args)
    client = make_client(config)
    app_id, app_id_source = _require_with_source(
        args.app_id, config.app_id, i18n.t("cli.require.app-id-flag")
    )
    # An application is addressed by its id or by its exact name, the way apps get/start/stop do:
    # the name is what a person has in front of them, the id is what the API wants. A UUID passes
    # through without a request.
    app_id = client.resolve_app_id(app_id)
    project_id, project_id_source = _require_with_source(
        args.project_id, config.project_id, i18n.t("cli.require.project-id-flag")
    )
    report = deploy_from_sources(
        client,
        app_id,
        project_id,
        project_dir=args.project_dir,
        output_dir=args.output,
        version=args.build_version or "",
        branch=args.branch,
        commit=args.commit,
        app_id_source=app_id_source,
        project_id_source=project_id_source,
        allow_data_loss=args.allow_data_loss,
        log=_progress,
    )
    _emit(report.to_dict())
    return 0 if report.ok else 1


def _user_list_id(client, args):
    """The id of the target user list: from the argument or from the application.

    Exactly one of the two is expected. --app takes the application's own list
    (default-user-list of its card) – that is the everyday case: the settings of
    the checklist are made on the list of a particular application, and its
    presentation is named after the application anyway.
    """
    target = getattr(args, "user_list", None)
    app = getattr(args, "app", None)
    if target and app:
        raise ElemctlError(i18n.t("cli.user-list-source-conflict"))
    if app:
        return client.app_user_list_id(app)
    if target:
        return client.resolve_user_list_id(target)
    raise ConfigError(i18n.t("cli.user-list-required"))


def cmd_user_lists_list(args):
    client = make_client(_config(args))
    _emit(client.list_user_lists(name=args.name or ""))
    return 0


def cmd_user_lists_get(args):
    client = make_client(_config(args))
    _emit(client.get_user_list(_user_list_id(client, args)))
    return 0


def cmd_user_lists_self_registration(args):
    """Self-registration of users of the list: read the state or change it."""
    client = make_client(_config(args))
    list_id = _user_list_id(client, args)
    if args.enable == args.disable:  # neither given, or both at once
        if args.enable:
            raise ElemctlError(i18n.t("cli.enable-disable-conflict"))
        _emit({"list-id": list_id, "self-registration": client.get_self_registration(list_id)})
        return 0
    settings = client.set_self_registration(list_id, enabled=args.enable)
    _emit({"list-id": list_id, "self-registration": settings})
    return 0



def _calculation_rules(args):
    """The rules from a file and the per-key flags; an unknown key is refused here.

    Refused rather than passed through: the platform answers 400 to a key it does not
    know (the schema of the same catalog spells one of them differently), and a rejected
    request says far less than a message naming the four keys that exist.
    """
    rules = {}
    if getattr(args, "rules_file", ""):
        data = json.loads(Path(args.rules_file).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ConfigError(i18n.t("cli.rules-file-not-object"))
        rules.update(data)
    for flag, key in (
        ("response_kind", "response-kind"),
        ("presentation_rule", "presentation-rule"),
        ("phone_rule", "phone-rule"),
        ("email_rule", "email-rule"),
    ):
        value = getattr(args, flag, "") or ""
        if value:
            rules[key] = value
    unknown = sorted(set(rules) - set(CALCULATION_RULE_FIELDS))
    if unknown:
        raise ConfigError(i18n.t(
            "cli.rules-unknown-keys",
            keys=", ".join(unknown), known=", ".join(CALCULATION_RULE_FIELDS),
        ))
    return rules


def cmd_user_lists_calculation_rules(args):
    """The rules that build a user from the provider's answer: show the target or write them.

    Without values the command does not pretend to show the rules – the platform does not
    return them – it names the service they would go to and says why there is nothing to
    show. Writing reports honestly what was confirmed and what could not be.
    """
    client = make_client(_config(args))
    list_id = _user_list_id(client, args)
    service_type = args.service_type or OIDC_SERVICE
    rules = _calculation_rules(args)
    if not rules:
        service = client.find_account_service(
            list_id, service_id=args.service or "", service_type=service_type
        ) or {}
        _emit({
            "list-id": list_id,
            "service-id": service.get("account-service-id"),
            "service-type": service.get("account-service-type"),
            "rules": None,
            "note": i18n.t("cli.rules-not-returned"),
        })
        return 0
    report = client.set_calculation_rules(
        list_id, rules, service_id=args.service or "", service_type=service_type
    )
    if not report.get("written"):
        raise ElemctlError(i18n.t("cli.rules-no-service", list=list_id, service=service_type))
    _emit({
        "list-id": list_id,
        **report,
        "note": i18n.t("cli.rules-not-verified"),
        "next": i18n.t("cli.rules-next"),
    })
    return 0


def cmd_user_lists_password_login(args):
    """Signing in with a login and a password – the account service of type Local.

    Without a flag the command answers with the current state; the answer says
    `enabled: null` when the list has no such service at all (nothing to sign in
    with by password), and `changed` tells whether this very call altered
    anything.
    """
    client = make_client(_config(args))
    list_id = _user_list_id(client, args)
    if args.enable == args.disable:
        if args.enable:
            raise ElemctlError(i18n.t("cli.enable-disable-conflict"))
        service = next(
            (
                item for item in client.list_account_services(list_id)
                if isinstance(item, dict)
                and str(item.get("account-service-type") or "").lower() == "local"
            ),
            None,
        )
        _emit({
            "list-id": list_id,
            "enabled": None if service is None else bool(service.get("enabled")),
            "changed": False,
        })
        return 0
    outcome = client.set_password_login(list_id, enabled=args.enable)
    service = outcome["service"]
    _emit({
        "list-id": list_id,
        "enabled": None if service is None else bool(service.get("enabled")),
        "changed": outcome["changed"],
    })
    return 0


def cmd_probe(args):
    """An isolated compilation check that does not touch the working application.

    The environment is taken WITHOUT ELEMENT_APP_ID and ELEMENT_PROJECT_ID: the
    probe must not be able to reach the working application, and the target
    project is chosen by the platform out of the vendor and the name of the
    manifest. The exit code follows the compilation verdict; leftovers of a
    failed cleanup go to stderr, they do not change the verdict.
    """
    if args.require_clean:
        _ensure_clean_tree(args.project_dir)
    config = _config(args)
    client = make_client(config)
    report = probe_project(
        client,
        project_dir=args.project_dir,
        output_dir=args.output,
        space_id=args.space_id or config.space_id or None,
        app_name=args.name or "",
        version=args.build_version or "",
        keep=args.keep,
        log=_progress,
    )
    _emit(report.to_dict())
    return 0 if report.ok else 1


def cmd_branches_list(args):
    client = make_client(_config(args))
    _emit(client.list_branches(project_id=args.project_id or "", name=args.name or ""))
    return 0


def cmd_branches_get(args):
    client = make_client(_config(args))
    _emit(client.get_branch(args.branch_id))
    return 0


def cmd_branches_create(args):
    config = _config(args)
    client = make_client(config)
    project_id = _require(
        args.project_id, config.project_id, i18n.t("cli.require.project-id-flag")
    )
    _emit(client.create_branch(args.name, project_id, app_id=args.app_id or None))
    return 0


def cmd_branches_update(args):
    client = make_client(_config(args))
    _emit(client.update_branch(args.branch_id, app_id=args.app_id or None))
    return 0


def cmd_branches_delete(args):
    client = make_client(_config(args))
    response = client.delete_branch(args.branch_id)
    _emit(response if response is not None else {"deleted": True, "branch-id": args.branch_id})
    return 0


def cmd_branches_merge(args):
    client = make_client(_config(args))
    response = client.merge_branch(args.branch_id)
    _emit(response if response is not None else {"merged": True, "branch-id": args.branch_id})
    return 0


def cmd_dumps_create(args):
    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    _emit(client.create_dump(app_id, description=args.description or ""))
    return 0


def cmd_dumps_get(args):
    client = make_client(_config(args))
    _emit(client.get_dump(args.app_id, args.dump_id))
    return 0


def cmd_tasks_list(args):
    client = make_client(_config(args))
    _emit(client.list_app_tasks(args.app_id or ""))
    return 0


def cmd_tasks_get_group(args):
    client = make_client(_config(args))
    _emit(client.get_group_task(args.task_id))
    return 0


def cmd_tech_get(args):
    config = _config(args)
    client = make_client(config)
    app_id = _require(args.app_id, config.app_id, i18n.t("cli.require.app-id-arg"))
    _emit({"app-id": app_id, "technology-version": client.get_technology_version(app_id)})
    return 0


def cmd_tech_set(args):
    client = make_client(_config(args))
    _emit(client.set_technology_version(args.version, [args.app_id]))
    return 0


def cmd_debug_adapter(args):
    """The path to the platform debug adapter directory brought by the plugin.

    The directory holds a repo/ subdirectory with the jar files of the adapter – that is
    the ready value of the xbsl.debug.adapterPath setting for the VS Code extension. A
    missing plugin is an answer (found: false, code 0), not an error: a non-zero code
    would mean a failure.
    """
    path = plugins.debug_adapter_path()
    if path is None:
        _emit({"path": None, "found": False})
        return 0
    _emit({"path": str(path), "found": True, "adapter-class": plugins.ADAPTER_MAIN_CLASS})
    return 0


def cmd_plugins(args):
    """Plugin diagnostics: what the plugins bring – adapter directories and commands.

    The adapter directories are listed jar-less ones included (that is exactly
    what a diagnostic is for), the commands – with the entry point they arrived
    through and whether they are exposed to MCP.
    """
    paths = plugins.debug_adapter_paths()
    _emit(
        {
            "debug-adapter": [
                {"path": str(p), "has-jars": plugins.has_adapter_jars(p)} for p in paths
            ],
            "commands": [
                {
                    "name": command.name,
                    "source": command.source,
                    "mcp": command.tool_name if command.mcp else None,
                }
                for command in plugins.plugin_commands()
            ],
        }
    )
    return 0


def cmd_self_update(args):
    """Update the installed elemctl by unpacking the wheel (safe while the exe is busy)."""
    from . import selfupdate

    old, new = selfupdate.self_update(
        version=args.version, log=_progress, stop_busy=getattr(args, "stop_holders", False)
    )
    _emit({"updated": old != new, "from": old, "to": new})
    return 0


def cmd_mcp(args):
    try:
        from . import mcp_server
    except ImportError:
        raise ElemctlError(i18n.t("cli.mcp-extra-required"))
    mcp_server.main(config=_config(args))
    return 0


# -- parser --------------------------------------------------------------------


def _plugin_handler(command):
    """The CLI handler of a plugin command: the context, the call, the JSON, the exit code."""

    def handle(args):
        config = _config(args)
        context = plugins.CommandContext(config, client_factory=make_client, log=_progress)
        values = {
            argument.dest: getattr(args, argument.dest, argument.value_default)
            for argument in command.arguments
        }
        result = command.handler(context, **values)
        _emit(result)
        # The same convention the core reports follow: ok: false is exit code 1.
        return 1 if isinstance(result, dict) and result.get("ok") is False else 0

    return handle


def _argument_kwargs(argument):
    """Translate an argument declaration into the keyword arguments of add_argument."""
    kwargs = {"help": argument.help}
    if argument.type is bool:
        kwargs["action"] = "store_true"
        return kwargs
    kwargs["type"] = argument.type
    kwargs["default"] = argument.default
    if argument.choices:
        kwargs["choices"] = list(argument.choices)
    if argument.is_option:
        if argument.required:
            kwargs["required"] = True
    elif not argument.required:
        kwargs["nargs"] = "?"
    return kwargs


def add_plugin_commands(sub):
    """Register the commands the plugins bring as subcommands of the CLI.

    A name that the core already occupies is an error rather than a silent
    override: a plugin must not be able to substitute itself for `deploy`. The
    check is against the parsers already registered, so it stays true whatever
    the core grows.
    """
    for command in plugins.plugin_commands():
        if command.name in sub.choices:
            raise PluginError(i18n.t(
                "plugins.command-name-taken", where=command.source, name=command.name
            ))
        parser = sub.add_parser(command.name, help=command.help)
        for argument in command.arguments:
            parser.add_argument(argument.name, **_argument_kwargs(argument))
        parser.set_defaults(handler=_plugin_handler(command), plugin_command=command)


def _add_create_flags(p):
    """Add the application source and creation flags (shared by apps create and apps ensure)."""
    p.add_argument("name", metavar="NAME", help=i18n.t("cli.help.arg.app-name"))
    p.add_argument("--project-id", help=i18n.t("cli.help.create-project-id"))
    p.add_argument("--version-id", help=i18n.t("cli.help.create-version-id"))
    p.add_argument("--latest-build", action="store_true", help=i18n.t("cli.help.create-latest-build"))
    p.add_argument("--space-id", help=i18n.t("cli.help.create-space-id"))
    p.add_argument("--tech-version", help=i18n.t("cli.help.create-tech-version"))
    p.add_argument("--no-dev-mode", action="store_true", help=i18n.t("cli.help.create-no-dev-mode"))
    p.add_argument("--wait", action="store_true", help=i18n.t("cli.help.create-wait"))


# The global options are declared on the root parser, so argparse only accepts them
# BEFORE the subcommand: "elemctl deploy --env-file .env" used to die with
# "unrecognized arguments". They are hoisted to the front of argv instead, which keeps
# the order rule out of the checklists and out of the skills.
_GLOBAL_OPTIONS = (
    "--base-url",
    "--client-id",
    "--client-secret",
    "--env-file",
    "--timeout",
    "--lang",
)


def _hoist_global_options(argv):
    """Move the global options standing after the subcommand to the front of argv.

    Both spellings are handled ("--env-file path" and "--env-file=path"). Everything
    after a bare "--" is left untouched: there the tokens belong to the command, not
    to the parser. An option without a value is left in place as well - let argparse
    report it in its own words.
    """
    argv = list(argv)
    hoisted, rest = [], []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            rest.extend(argv[index:])
            break
        if arg in _GLOBAL_OPTIONS and index + 1 < len(argv):
            hoisted.extend([arg, argv[index + 1]])
            index += 2
            continue
        if any(arg.startswith(option + "=") for option in _GLOBAL_OPTIONS):
            hoisted.append(arg)
            index += 1
            continue
        rest.append(arg)
        index += 1
    return hoisted + rest


def build_parser():
    parser = i18n.ArgumentParser(
        prog="elemctl",
        description=i18n.t("cli.help.description"),
    )
    parser.add_argument("--base-url", help=i18n.t("cli.help.base-url"))
    parser.add_argument("--client-id", help=i18n.t("cli.help.client-id"))
    parser.add_argument("--client-secret", help=i18n.t("cli.help.client-secret"))
    parser.add_argument("--env-file", help=i18n.t("cli.help.env-file"))
    parser.add_argument("--timeout", type=float, default=None, help=i18n.t("cli.help.timeout"))
    parser.add_argument(
        "--lang",
        choices=i18n.LANGS,
        help=i18n.t("cli.help.lang"),
    )
    parser.add_argument("--version", action="version", help=i18n.t("cli.help.version"),
                        version=f"elemctl {__version__}")

    # title= renders the list under a "commands:" heading instead of argparse's default
    # "positional arguments: command" – the same heading the sibling tools use.
    sub = parser.add_subparsers(
        dest="command",
        metavar=i18n.t("cli.help.command-metavar"),
        title=i18n.t("cli.help.commands-title"),
    )
    action = i18n.t("cli.help.action-metavar")  # the metavar for every group's subcommands

    p = sub.add_parser("token", help=i18n.t("cli.help.token"))
    p.set_defaults(handler=cmd_token)

    # apps ----------------------------------------------------------------
    apps = sub.add_parser("apps", help=i18n.t("cli.help.apps"))
    apps_sub = apps.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = apps_sub.add_parser("list", help=i18n.t("cli.help.apps-list"))
    p.add_argument("--name", help=i18n.t("cli.help.apps-list-name"))
    p.add_argument("--brief", action="store_true", help=i18n.t("cli.help.apps-list-brief"))
    p.set_defaults(handler=cmd_apps_list)

    p = apps_sub.add_parser("get", help=i18n.t("cli.help.apps-get"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-ref"))
    p.set_defaults(handler=cmd_apps_get)

    p = apps_sub.add_parser("find", help=i18n.t("cli.help.apps-find"))
    p.add_argument("name", metavar="NAME", help=i18n.t("cli.help.arg.app-name"))
    p.add_argument(
        "--include-deleted",
        action="store_true",
        help=i18n.t("cli.help.apps-find-include-deleted"),
    )
    p.set_defaults(handler=cmd_apps_find)

    p = apps_sub.add_parser("create", help=i18n.t("cli.help.apps-create"))
    _add_create_flags(p)
    p.set_defaults(handler=cmd_apps_create)

    p = apps_sub.add_parser("ensure", help=i18n.t("cli.help.apps-ensure"))
    _add_create_flags(p)
    p.add_argument("--apply", action="store_true", help=i18n.t("cli.help.apps-ensure-apply"))
    p.set_defaults(handler=cmd_apps_ensure)

    p = apps_sub.add_parser("apply", help=i18n.t("cli.help.apps-apply"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-ref"))
    p.add_argument(
        "version_id", metavar="VERSION_ID", help=i18n.t("cli.help.arg.version-id-required")
    )
    p.set_defaults(handler=cmd_apps_apply)

    p = apps_sub.add_parser("delete", help=i18n.t("cli.help.apps-delete"))
    p.add_argument("app_id", metavar="APP_ID", help=i18n.t("cli.help.arg.app-ref-required"))
    p.set_defaults(handler=cmd_apps_delete)

    p = apps_sub.add_parser("start", help=i18n.t("cli.help.apps-start"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-ref"))
    p.set_defaults(handler=cmd_apps_start)

    p = apps_sub.add_parser("stop", help=i18n.t("cli.help.apps-stop"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-ref"))
    p.set_defaults(handler=cmd_apps_stop)

    p = apps_sub.add_parser("debug", help=i18n.t("cli.help.apps-debug"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-ref"))
    p.set_defaults(handler=cmd_apps_debug)

    # spaces ----------------------------------------------------------------
    spaces = sub.add_parser("spaces", help=i18n.t("cli.help.spaces"))
    spaces_sub = spaces.add_subparsers(dest="subcommand", metavar=action, required=True)
    p = spaces_sub.add_parser("list", help=i18n.t("cli.help.spaces-list"))
    p.set_defaults(handler=cmd_spaces_list)

    # projects --------------------------------------------------------------
    projects = sub.add_parser("projects", help=i18n.t("cli.help.projects"))
    projects_sub = projects.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = projects_sub.add_parser("list", help=i18n.t("cli.help.projects-list"))
    p.set_defaults(handler=cmd_projects_list)

    p = projects_sub.add_parser("get", help=i18n.t("cli.help.projects-get"))
    p.add_argument("project_id", nargs="?", metavar="PROJECT_ID", help=i18n.t("cli.help.arg.project-id"))
    p.set_defaults(handler=cmd_projects_get)

    p = projects_sub.add_parser("delete", help=i18n.t("cli.help.projects-delete"))
    p.add_argument("project_id", metavar="PROJECT_ID", help=i18n.t("cli.help.arg.project-id-required"))
    p.set_defaults(handler=cmd_projects_delete)

    # builds ----------------------------------------------------------------
    builds = sub.add_parser("builds", help=i18n.t("cli.help.builds"))
    builds_sub = builds.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = builds_sub.add_parser("list", help=i18n.t("cli.help.builds-list"))
    p.add_argument("--project-id", help=i18n.t("cli.help.arg.project-id"))
    p.add_argument(
        "--limit", type=int, default=10, help=i18n.t("cli.help.builds-list-limit")
    )
    p.add_argument(
        "--brief", action="store_true", help=i18n.t("cli.help.builds-list-brief")
    )
    p.set_defaults(handler=cmd_builds_list)

    p = builds_sub.add_parser("get", help=i18n.t("cli.help.builds-get"))
    p.add_argument("version", metavar="VERSION", help=i18n.t("cli.help.arg.assembly-version"))
    p.add_argument("--project-id", help=i18n.t("cli.help.arg.project-id"))
    p.set_defaults(handler=cmd_builds_get)

    p = builds_sub.add_parser("upload", help=i18n.t("cli.help.builds-upload"))
    p.add_argument("file", metavar="FILE", help=i18n.t("cli.help.arg.assembly-file"))
    p.add_argument("--project-id", help=i18n.t("cli.help.builds-upload-project-id"))
    p.add_argument(
        "--new-project",
        action="store_true",
        help=i18n.t("cli.help.builds-upload-new-project"),
    )
    p.add_argument(
        "--force-rename",
        action="store_true",
        help=i18n.t("cli.help.builds-upload-force-rename"),
    )
    p.add_argument("--space-id", help=i18n.t("cli.help.arg.space-id"))
    p.set_defaults(handler=cmd_builds_upload)

    p = builds_sub.add_parser("delete", help=i18n.t("cli.help.builds-delete"))
    p.add_argument("version", metavar="VERSION", help=i18n.t("cli.help.arg.assembly-version"))
    p.add_argument("--project-id", help=i18n.t("cli.help.arg.project-id"))
    p.set_defaults(handler=cmd_builds_delete)

    # build -----------------------------------------------------------------
    p = sub.add_parser("build", help=i18n.t("cli.help.build"))
    p.add_argument("--project-dir", help=i18n.t("cli.help.build-project-dir"))
    p.add_argument("--output", help=i18n.t("cli.help.build-output"))
    p.add_argument("--build-version", help=i18n.t("cli.help.build-build-version"))
    p.add_argument("--last-build", help=i18n.t("cli.help.build-last-build"))
    p.add_argument("--commit", help=i18n.t("cli.help.build-commit"))
    p.add_argument("--branch", help=i18n.t("cli.help.build-branch"))
    p.add_argument("--kind", choices=["application", "library"], help=i18n.t("cli.help.build-kind"))
    p.add_argument(
        "--require-clean",
        action="store_true",
        help=i18n.t("cli.help.build-require-clean"),
    )
    p.set_defaults(handler=cmd_build)

    # inspect ---------------------------------------------------------------
    p = sub.add_parser("inspect", help=i18n.t("cli.help.inspect"))
    p.add_argument("file", metavar="FILE", help=i18n.t("cli.help.inspect-file"))
    p.set_defaults(handler=cmd_inspect)

    # deploy ----------------------------------------------------------------
    p = sub.add_parser("deploy", help=i18n.t("cli.help.deploy"))
    p.add_argument("--app-id", help=i18n.t("cli.help.arg.app-id"))
    p.add_argument("--project-id", help=i18n.t("cli.help.arg.project-id"))
    p.add_argument("--project-dir", help=i18n.t("cli.help.deploy-project-dir"))
    p.add_argument("--output", help=i18n.t("cli.help.deploy-output"))
    p.add_argument("--build-version", help=i18n.t("cli.help.deploy-build-version"))
    p.add_argument("--branch", help=i18n.t("cli.help.deploy-branch"))
    p.add_argument("--commit", help=i18n.t("cli.help.deploy-commit"))
    p.add_argument("--dry-run", action="store_true", help=i18n.t("cli.help.deploy-dry-run"))
    p.add_argument(
        "--require-clean",
        action="store_true",
        help=i18n.t("cli.help.deploy-require-clean"),
    )
    p.add_argument(
        "--allow-data-loss",
        action="store_true",
        help=i18n.t("cli.help.deploy-allow-data-loss"),
    )
    p.set_defaults(handler=cmd_deploy)

    # user-lists ------------------------------------------------------------
    user_lists = sub.add_parser("user-lists", help=i18n.t("cli.help.user-lists"))
    user_lists_sub = user_lists.add_subparsers(dest="subcommand", metavar=action, required=True)

    def add_target(parser):
        """The target list: a positional argument or --app (the application's own list)."""
        parser.add_argument(
            "user_list", nargs="?", metavar="LIST", help=i18n.t("cli.help.arg.user-list")
        )
        parser.add_argument("--app", help=i18n.t("cli.help.user-lists-app"))

    p = user_lists_sub.add_parser("list", help=i18n.t("cli.help.user-lists-list"))
    p.add_argument("--name", help=i18n.t("cli.help.user-lists-list-name"))
    p.set_defaults(handler=cmd_user_lists_list)

    p = user_lists_sub.add_parser("get", help=i18n.t("cli.help.user-lists-get"))
    add_target(p)
    p.set_defaults(handler=cmd_user_lists_get)

    p = user_lists_sub.add_parser(
        "self-registration", help=i18n.t("cli.help.user-lists-self-registration")
    )
    add_target(p)
    p.add_argument("--enable", action="store_true", help=i18n.t("cli.help.user-lists-enable"))
    p.add_argument("--disable", action="store_true", help=i18n.t("cli.help.user-lists-disable"))
    p.set_defaults(handler=cmd_user_lists_self_registration)

    p = user_lists_sub.add_parser(
        "password-login", help=i18n.t("cli.help.user-lists-password-login")
    )
    add_target(p)
    p.add_argument("--enable", action="store_true", help=i18n.t("cli.help.user-lists-enable"))
    p.add_argument("--disable", action="store_true", help=i18n.t("cli.help.user-lists-disable"))
    p.set_defaults(handler=cmd_user_lists_password_login)

    p = user_lists_sub.add_parser(
        "calculation-rules", help=i18n.t("cli.help.user-lists-calculation-rules")
    )
    add_target(p)
    p.add_argument("--rules-file", help=i18n.t("cli.help.rules-file"))
    p.add_argument("--response-kind", help=i18n.t("cli.help.rule-response-kind"))
    p.add_argument("--presentation-rule", help=i18n.t("cli.help.rule-presentation"))
    p.add_argument("--phone-rule", help=i18n.t("cli.help.rule-phone"))
    p.add_argument("--email-rule", help=i18n.t("cli.help.rule-email"))
    p.add_argument("--service", help=i18n.t("cli.help.rules-service"))
    p.add_argument("--service-type", help=i18n.t("cli.help.rules-service-type"))
    p.set_defaults(handler=cmd_user_lists_calculation_rules)

    # probe -----------------------------------------------------------------
    p = sub.add_parser("probe", help=i18n.t("cli.help.probe"))
    p.add_argument("--project-dir", help=i18n.t("cli.help.probe-project-dir"))
    p.add_argument("--output", help=i18n.t("cli.help.probe-output"))
    p.add_argument("--build-version", help=i18n.t("cli.help.probe-build-version"))
    p.add_argument("--name", help=i18n.t("cli.help.probe-name"))
    p.add_argument("--space-id", help=i18n.t("cli.help.probe-space-id"))
    p.add_argument("--keep", action="store_true", help=i18n.t("cli.help.probe-keep"))
    p.add_argument(
        "--require-clean",
        action="store_true",
        help=i18n.t("cli.help.probe-require-clean"),
    )
    p.set_defaults(handler=cmd_probe)

    # branches ----------------------------------------------------------------
    branches = sub.add_parser("branches", help=i18n.t("cli.help.branches"))
    branches_sub = branches.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = branches_sub.add_parser("list", help=i18n.t("cli.help.branches-list"))
    p.add_argument("--project-id", help=i18n.t("cli.help.arg.project-id"))
    p.add_argument("--name", help=i18n.t("cli.help.branches-list-name"))
    p.set_defaults(handler=cmd_branches_list)

    p = branches_sub.add_parser("get", help=i18n.t("cli.help.branches-get"))
    p.add_argument("branch_id", metavar="ID", help=i18n.t("cli.help.arg.branch-id"))
    p.set_defaults(handler=cmd_branches_get)

    p = branches_sub.add_parser("create", help=i18n.t("cli.help.branches-create"))
    p.add_argument("name", metavar="NAME", help=i18n.t("cli.help.arg.branch-name"))
    p.add_argument("--project-id", help=i18n.t("cli.help.arg.project-id"))
    p.add_argument("--app-id", help=i18n.t("cli.help.branches-create-app-id"))
    p.set_defaults(handler=cmd_branches_create)

    p = branches_sub.add_parser("update", help=i18n.t("cli.help.branches-update"))
    p.add_argument("branch_id", metavar="ID", help=i18n.t("cli.help.arg.branch-id"))
    p.add_argument("--app-id", help=i18n.t("cli.help.arg.app-id"))
    p.set_defaults(handler=cmd_branches_update)

    p = branches_sub.add_parser("delete", help=i18n.t("cli.help.branches-delete"))
    p.add_argument("branch_id", metavar="ID", help=i18n.t("cli.help.arg.branch-id"))
    p.set_defaults(handler=cmd_branches_delete)

    p = branches_sub.add_parser("merge", help=i18n.t("cli.help.branches-merge"))
    p.add_argument("branch_id", metavar="ID", help=i18n.t("cli.help.arg.branch-id"))
    p.set_defaults(handler=cmd_branches_merge)

    # dumps ----------------------------------------------------------------
    dumps = sub.add_parser("dumps", help=i18n.t("cli.help.dumps"))
    dumps_sub = dumps.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = dumps_sub.add_parser("create", help=i18n.t("cli.help.dumps-create"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id"))
    p.add_argument("--description", help=i18n.t("cli.help.dumps-create-description"))
    p.set_defaults(handler=cmd_dumps_create)

    p = dumps_sub.add_parser("get", help=i18n.t("cli.help.dumps-get"))
    p.add_argument("app_id", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id-required"))
    p.add_argument("dump_id", metavar="DUMP_ID", help=i18n.t("cli.help.arg.dump-id"))
    p.set_defaults(handler=cmd_dumps_get)

    # tasks ----------------------------------------------------------------
    tasks = sub.add_parser("tasks", help=i18n.t("cli.help.tasks"))
    tasks_sub = tasks.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = tasks_sub.add_parser("list", help=i18n.t("cli.help.tasks-list"))
    p.add_argument("--app-id", help=i18n.t("cli.help.tasks-list-app-id"))
    p.set_defaults(handler=cmd_tasks_list)

    p = tasks_sub.add_parser("get-group", help=i18n.t("cli.help.tasks-get-group"))
    p.add_argument("task_id", metavar="TASK_ID", help=i18n.t("cli.help.arg.task-id"))
    p.set_defaults(handler=cmd_tasks_get_group)

    # tech ----------------------------------------------------------------
    tech = sub.add_parser("tech", help=i18n.t("cli.help.tech"))
    tech_sub = tech.add_subparsers(dest="subcommand", metavar=action, required=True)

    p = tech_sub.add_parser("get", help=i18n.t("cli.help.tech-get"))
    p.add_argument("app_id", nargs="?", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id"))
    p.set_defaults(handler=cmd_tech_get)

    p = tech_sub.add_parser("set", help=i18n.t("cli.help.tech-set"))
    p.add_argument("app_id", metavar="APP_ID", help=i18n.t("cli.help.arg.app-id-required"))
    p.add_argument("version", metavar="VERSION", help=i18n.t("cli.help.arg.tech-version"))
    p.set_defaults(handler=cmd_tech_set)

    # debug-adapter -------------------------------------------------------
    p = sub.add_parser("debug-adapter", help=i18n.t("cli.help.debug-adapter"))
    p.set_defaults(handler=cmd_debug_adapter)

    # plugins -------------------------------------------------------------
    p = sub.add_parser("plugins", help=i18n.t("cli.help.plugins"))
    p.set_defaults(handler=cmd_plugins)

    # self-update ---------------------------------------------------------
    p = sub.add_parser("self-update", help=i18n.t("cli.help.self-update"))
    p.add_argument("--version", help=i18n.t("cli.help.self-update-version"))
    p.add_argument("--stop-holders", action="store_true",
                   help=i18n.t("cli.help.selfupdate-stop"))
    p.set_defaults(handler=cmd_self_update)

    # mcp ----------------------------------------------------------------
    p = sub.add_parser("mcp", help=i18n.t("cli.help.mcp"))
    p.set_defaults(handler=cmd_mcp)

    # plugins ------------------------------------------------------------
    # Last of all: the commands of the core are already in place, and a name
    # clash with any of them is caught right here.
    add_plugin_commands(sub)

    return parser


def main(argv=None):
    """The CLI entry point; returns the exit code of the process."""
    _reconfigure_streams()
    if argv is None:
        argv = sys.argv[1:]
    argv = _hoist_global_options(argv)
    # The language is needed BEFORE build_parser: the help (help=) is assembled in the chosen
    # language. So argv is prescanned for --lang; env and the locale are taken into account by
    # t() itself through current_lang() while the parser is being built.
    i18n.set_lang(i18n.lang_from_argv(argv))
    try:
        parser = build_parser()
    except ElemctlError as error:
        # A broken plugin must not fall out as a traceback: the parser is built
        # before any command runs, so its errors need the same JSON treatment.
        return _fail({"error": str(error)})
    args = parser.parse_args(argv)
    # Pin the language again, now out of the parsed arguments: argparse also accepts
    # abbreviations (--lan en), which the prescan does not catch; for the runtime this is the
    # authoritative source.
    i18n.set_lang(args.lang)  # None keeps the env / locale / ru order
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return 1
    try:
        result = handler(args)
        return 0 if result is None else int(result)
    except ApiError as error:
        return _fail(error.to_dict())
    except ElemctlError as error:
        return _fail({"error": str(error)})
    except OSError as error:
        return _fail({"error": str(error)})


if __name__ == "__main__":
    sys.exit(main())
