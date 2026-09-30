"""Language of elemctl runtime output: message catalog and lookup.

elemctl is small and has no rule modules, so every user-facing runtime string - error
texts and progress lines - lives right here in MESSAGES and is registered on import:

    MESSAGES = {
        "deploy.verify-failed": {
            "ru": "проверка НЕ пройдена",
            "en": "verification FAILED",
        },
    }
    register(MESSAGES)

A key is `<module>.<name>`. Placeholders are `str.format` fields and must be the same in
every language - `tests/test_i18n.py` enforces that. A brace that is part of the text -
`() [] {{}}` - has to be doubled, because every template is formatted.

The language is chosen by: set_lang() (CLI --lang) > env ELEMCTL_LANG > system locale > ru.
An unknown key is returned as is, so a caller that passes a literal string rather than a key
keeps working.

Scope: runtime output AND the argparse --help text are translated. Help strings are routed
through t() as well, so the parser has to be built after the language is resolved - cli.main
reads --lang out of argv with lang_from_argv() before build_parser(), because argparse itself
learns --lang only when it parses, which is too late to pick the help language. Docstrings and
code comments are source text rather than runtime output and stay outside this scope.
"""

from __future__ import annotations

import argparse as _argparse
import locale as _locale
import os

LANGS = ("ru", "en")
DEFAULT_LANG = "ru"
ENV_LANG = "ELEMCTL_LANG"

_catalog: dict[str, dict[str, str]] = {}
_selected: str | None = None

# Every user-facing runtime string of elemctl. Keys are grouped by the module that emits them.
MESSAGES = {
    # -- build.py -----------------------------------------------------------------
    "build.project-dir-not-found": {
        "ru": "каталог проекта не найден: нет {file} внутри {base}",
        "en": "project directory not found: no {file} in {base}",
    },
    "build.not-found": {
        "ru": "не найден {file}",
        "en": "not found: {file}",
    },
    "build.unknown-kind": {
        "ru": "неизвестный вид проекта: {kind} (ожидалось application, library или extension)",
        "en": "unknown project kind: {kind} (expected application, library or extension)",
    },
    "build.not-archive": {
        "ru": "файл не является архивом сборки: {file}",
        "en": "the file is not a build archive: {file}",
    },
    "build.no-manifest": {
        "ru": "в архиве {file} нет манифеста {manifest}",
        "en": "archive {file} has no manifest {manifest}",
    },
    "build.no-project-file": {
        "ru": "в архиве {file} нет файла проекта {entry}",
        "en": "archive {file} has no project file {entry}",
    },
    "build.name-vendor-required": {
        "ru": 'в {file} должны быть заполнены поля "Имя"/"Name" и "Поставщик"/"Vendor"',
        "en": '{file} must have the "Имя"/"Name" and "Поставщик"/"Vendor" fields filled in',
    },
    "build.layout-mismatch": {
        "ru": "каталог проекта обязан лежать по схеме {{репозиторий}}/{{поставщик}}/{{имя}}/"
              "{file}: ожидался путь .../{vendor}/{name}, фактический – {actual}",
        "en": "the project directory must follow the {{repo}}/{{vendor}}/{{name}}/{file} "
              "layout: expected .../{vendor}/{name}, actual – {actual}",
    },
    # -- cli.py -------------------------------------------------------------------
    "cli.not-set": {
        "ru": "не задан {what}",
        "en": "{what} is not set",
    },
    "cli.require.app-id-arg": {
        "ru": "app-id (аргумент APP_ID или ELEMENT_APP_ID)",
        "en": "app-id (APP_ID argument or ELEMENT_APP_ID)",
    },
    "cli.require.app-ref": {
        "ru": "app-id (аргумент APP_ID или --app-id; ELEMENT_APP_ID здесь не берётся)",
        "en": "app-id (APP_ID argument or --app-id; ELEMENT_APP_ID is not taken here)",
    },
    "cli.require.app-id-flag": {
        "ru": "--app-id (или ELEMENT_APP_ID)",
        "en": "--app-id (or ELEMENT_APP_ID)",
    },
    "cli.require.project-id-arg": {
        "ru": "project-id (аргумент PROJECT_ID или ELEMENT_PROJECT_ID)",
        "en": "project-id (PROJECT_ID argument or ELEMENT_PROJECT_ID)",
    },
    "cli.require.project-id-flag": {
        "ru": "--project-id (или ELEMENT_PROJECT_ID)",
        "en": "--project-id (or ELEMENT_PROJECT_ID)",
    },
    "cli.user-list-source-conflict": {
        "ru": "список задан дважды: аргументом LIST и флагом --app – оставьте что-то одно",
        "en": "the list is given twice: as the LIST argument and as --app – keep one of them",
    },
    "cli.user-list-required": {
        "ru": "не задан список пользователей: аргумент LIST либо флаг --app",
        "en": "no user list given: the LIST argument or the --app flag",
    },
    "cli.enable-disable-conflict": {
        "ru": "флаги --enable и --disable несовместимы",
        "en": "--enable and --disable are mutually exclusive",
    },
    "cli.latest-build-needs-project": {
        "ru": "для --latest-build нужен --project-id (или ELEMENT_PROJECT_ID)",
        "en": "--latest-build requires --project-id (or ELEMENT_PROJECT_ID)",
    },
    "cli.builds-list-truncated": {
        "ru": "перечень сокращён флагом --limit (свежие первыми); все – --limit 0",
        "en": "the listing is cut by --limit (newest first); --limit 0 shows them all",
    },
    "cli.local-command-connection-options": {
        "ru": "команда '{command}' работает только локально – к платформе не "
              "обращается и номер версии на сервере не занимает. Ей переданы ключи "
              "подключения: {options}; на результат они не влияют, уберите их. "
              "Сервер – это другие команды: 'deploy' (сборка, загрузка, применение) "
              "и 'builds upload' (загрузка готового архива)",
        "en": "the '{command}' command works locally: it never calls the platform "
              "and reserves no version number on the server – yet it was given "
              "connection options: {options}. They change nothing about the result, "
              "drop them. The server is other commands: 'deploy' (build, upload, "
              "apply) and 'builds upload' (upload a prebuilt archive)",
    },
    "cli.upload-new-project-conflict": {
        "ru": "флаги --new-project и --project-id несовместимы: либо новый проект, "
              "либо конкретный",
        "en": "--new-project and --project-id are mutually exclusive: either a new "
              "project or a specific one",
    },
    "cli.upload-target-from-env": {
        "ru": "цель загрузки – проект {project_id} из ELEMENT_PROJECT_ID (окружение "
              "или .env-файл); загрузить без ид проекта, в проект по Ид из Проект.yaml "
              "либо новый, – флаг --new-project",
        "en": "upload target is project {project_id} from ELEMENT_PROJECT_ID (the "
              "environment or the .env file); pass --new-project to upload without a project "
              "id, into the project of the Ид of Проект.yaml or a new one",
    },
    "cli.upload-name-mismatch": {
        "ru": "сборка называет свой проект '{assembly}', а проект-цель называется "
              "'{project}' ({project_id}): загрузка ПЕРЕИМЕНУЕТ проект и его группу в "
              "панели, и удалением сборки это не откатывается – прежнее имя возвращает "
              "только загрузка сборки с этим именем. Если так и задумано – повторите с "
              "--force-rename; если сборка чужая – укажите --project-id нужного проекта "
              "либо повторите с --new-project. Флаг --new-project безопасен и для сборки "
              "СВОЕГО проекта: платформа опознает проект по Ид из Проект.yaml, поэтому "
              "такая сборка попадает в существующий проект, а не заводит второй",
        "en": "the assembly calls its project '{assembly}' while the target project is "
              "called '{project}' ({project_id}): the upload RENAMES the project and its "
              "group in the console, and deleting the assembly does not undo it – only "
              "uploading an assembly with the former name brings it back. If that is "
              "intended, repeat with --force-rename; if the assembly belongs elsewhere, "
              "pass the right --project-id or repeat with --new-project. That flag is "
              "safe for an assembly of the SAME project too: the platform recognizes a "
              "project by the Ид of its Проект.yaml, so such an assembly lands in the "
              "existing project instead of starting a second one",
    },
    "cli.upload-project-created": {
        "ru": "сервер завел для сборки новый проект {project}",
        "en": "the server created a new project {project} for the build",
    },
    "cli.upload-project-found": {
        "ru": "сервер положил сборку в существующий проект {project}: у него тот же Ид из "
              "Проект.yaml",
        "en": "the server put the build into the existing project {project}, the one that "
              "carries the Ид of its Проект.yaml",
    },
    "cli.upload-project-landed": {
        "ru": "сборка легла в проект {project}; новый он или прежний, сказать нельзя: перечень "
              "проектов перед загрузкой не прочитался",
        "en": "the build went into project {project}; whether the project is new cannot be "
              "told, since the project list could not be read before the upload",
    },
    "cli.upload-project-renamed": {
        "ru": "внимание: сервер положил сборку в проект {project_id} с тем же Ид из "
              "Проект.yaml и переименовал его вместе с группой: было '{former}', стало "
              "'{name}'. Удалением сборки это не откатывается – прежнее имя возвращает только "
              "загрузка сборки с этим именем",
        "en": "warning: the server put the build into project {project_id}, the one that "
              "carries the Ид of its Проект.yaml, and renamed the project and its group from "
              "'{former}' to '{name}'. Deleting the build does not undo it: only an upload of "
              "a build with the former name brings it back",
    },
    "cli.upload-project-unknown": {
        "ru": "внимание: сервер не назвал проект сборки {assembly}, и ни один проект ее не "
              "перечисляет: найдите его командой elemctl projects list",
        "en": "warning: the server did not name the project of build {assembly}, and no project "
              "lists it: look for it with elemctl projects list",
    },
    "cli.upload-project-by-build-list": {
        "ru": "ответ загрузки проекта не назвал, проект найден по перечням сборок",
        "en": "the answer of the upload named no project, so the project was found by the "
              "build lists",
    },
    "cli.upload-name-mismatch-forced": {
        "ru": "внимание: по флагу --force-rename имя проекта-цели '{project}' "
              "({project_id}) будет переписано именем сборки '{assembly}'; удалением "
              "сборки это не откатывается",
        "en": "warning: --force-rename was given, so the target project name '{project}' "
              "({project_id}) is being overwritten by the assembly name '{assembly}'; "
              "deleting the assembly does not undo it",
    },
    "cli.app-source-required": {
        "ru": "нужен источник приложения: --version-id либо --project-id [--latest-build]. "
              "Приложение всегда создаётся из сборки: пустого приложения в Console API нет. "
              "Если проекта ещё нет, заведите его загрузкой сборки БЕЗ --project-id "
              "(builds upload <файл>.xasm --space-id <id>) - в ответе придёт assembly-id, "
              "его и передайте в --version-id",
        "en": "an application source is required: --version-id or --project-id [--latest-build]. "
              "An application is always created from an assembly: Console API has no empty one. "
              "If the project does not exist yet, create it by uploading an assembly WITHOUT "
              "--project-id (builds upload <file>.xasm --space-id <id>) - the response carries "
              "the assembly-id to pass as --version-id",
    },
    "cli.build-file-not-found": {
        "ru": "файл сборки не найден: {path}",
        "en": "build file not found: {path}",
    },
    "cli.project-has-no-builds": {
        "ru": "у проекта {project_id} нет сборок – загрузите сборку (builds upload) "
              "или укажите --version-id",
        "en": "project {project_id} has no builds – upload one (builds upload) or "
              "pass --version-id",
    },
    "cli.plugin-failed": {
        "ru": "плагин '{source}' не загрузился, его команд нет: {error}",
        "en": "plugin '{source}' did not load, its commands are unavailable: {error}",
    },
    "cli.plugin-command-unavailable": {
        "ru": "команды '{command}' нет, а часть плагинов не загрузилась: {sources}. Команда "
              "могла прийти из них, причины перечислены в plugin-failures",
        "en": "there is no command '{command}', and some plugins did not load: {sources}. The "
              "command may have come from one of them; the reasons are listed in "
              "plugin-failures",
    },
    "cli.wait-broken": {
        "ru": "приложение {app_id} создано, но ожидание оборвалось: {error}",
        "en": "application {app_id} was created, but the wait broke off: {error}",
    },
    "cli.wait-broken-next": {
        "ru": "ид приложения есть в ответе; проверить сборку позже: {command}",
        "en": "the application id is in the answer; to check the build later: {command}",
    },
    "cli.source-instead": {
        "ru": "Приложение {app} работает на сборке {build}: передайте её в --version-id "
              "или возьмите самую свежую сборку проекта ключом --latest-build",
        "en": "Application {app} runs build {build}: pass it as --version-id, or take the "
              "project's newest build with --latest-build",
    },
    "cli.source-latest": {
        "ru": "Самую свежую сборку проекта берёт ключ --latest-build",
        "en": "--latest-build takes the project's newest build",
    },
    "cli.source-project-from-env": {
        "ru": "Проект взят из ELEMENT_PROJECT_ID: если сборка из другого проекта, "
              "назовите его в --project-id",
        "en": "The project comes from ELEMENT_PROJECT_ID: if the build belongs to another "
              "project, name that one with --project-id",
    },
    "cli.source-project-found": {
        "ru": "сборки {build} нет в проекте {project} из ELEMENT_PROJECT_ID: она лежит в "
              "проекте {owner}, по нему и проверена",
        "en": "build {build} is not in project {project} from ELEMENT_PROJECT_ID: it belongs "
              "to project {owner}, and it is checked against that one",
    },
    "cli.source-other-project": {
        "ru": "сборки {build} нет в проекте {project}, названном в --project-id: она лежит в "
              "проекте {owner}. Передайте --project-id {owner_id} или уберите этот ключ – "
              "проект сборки найдется сам",
        "en": "build {build} is not in project {project} named by --project-id: it belongs to "
              "project {owner}. Pass --project-id {owner_id}, or leave the flag out and the "
              "project of the build is found by itself",
    },
    "cli.whole-project-source-warning": {
        "ru": "внимание: источник – проект целиком; на части конфигураций платформы "
              "это даёт пустой каркас (надёжнее --latest-build)",
        "en": "warning: the source is the whole project; on some platform configurations "
              "this yields an empty skeleton (--latest-build is safer)",
    },
    "cli.mcp-extra-required": {
        "ru": 'MCP-зависимость не установлена – выполните: pip install "elemctl[mcp]"',
        "en": 'the MCP dependency is not installed – run: pip install "elemctl[mcp]"',
    },
    "cli.require-clean-no-git": {
        "ru": "--require-clean: git недоступен или {dir} не в репозитории – "
              "подтвердить чистоту дерева нечем",
        "en": "--require-clean: git is unavailable or {dir} is not inside a repository – "
              "there is nothing to confirm a clean tree with",
    },
    "cli.require-clean-dirty": {
        "ru": "--require-clean: в {dir} есть незакоммиченные изменения ({count}) – "
              "операция отменена",
        "en": "--require-clean: {dir} has uncommitted changes ({count}) – "
              "the operation is cancelled",
    },
    # -- client.py ----------------------------------------------------------------
    "client.sign-in-hint": {
        "ru": "как войти в приложение: {url} – учётной записью ПАНЕЛИ УПРАВЛЕНИЯ "
              "платформы (её пользователи подключаются к новому приложению сами и "
              "входят сразу); собственные страницы администрирования приложения "
              "открываются тем же входом",
        "en": "how to sign in: {url} – with a CONTROL PANEL account (its users are "
              "connected to a new application by the platform itself and sign in "
              "right away); the application's own admin pages open under the same "
              "sign-in",
    },
    "client.sign-in-hint-no-uri": {
        "ru": "как войти в приложение: учётной записью ПАНЕЛИ УПРАВЛЕНИЯ платформы "
              "(её пользователи подключаются к новому приложению сами); адрес "
              "появится, когда приложение запустится – apps get (или создавайте "
              "с --wait)",
        "en": "how to sign in: with a CONTROL PANEL account (its users are connected "
              "to a new application by the platform itself); the address appears once "
              "the application starts – apps get (or create it with --wait)",
    },
    "client.sign-in-note": {
        "ru": "у нового приложения свой пустой список пользователей, вход по логину "
              "и паролю выключен, а сервис учётных записей не подключён – поэтому "
              "учётные записи, которыми входят в другие приложения, здесь НЕ "
              "работают: подключение чужого списка пользователей и включение "
              "локального входа этого не меняют",
        "en": "a new application gets its own empty user list, password sign-in is "
              "off and no account service is attached – so the accounts used to sign "
              "in to other applications do NOT work here: connecting someone else's "
              "user list and enabling the local sign-in do not change that",
    },
    "client.assembly-not-found": {
        "ru": "сборка '{version}' не найдена в проекте {project} (ни по версии, ни по ид)",
        "en": "assembly '{version}' not found in project {project} (neither by version nor by id)",
    },
    "client.source-missing": {
        "ru": "сборки {assembly} нет в перечне сборок проекта {project}: платформа удаляет "
              "сборки, которыми никто не пользуется, и из удалённой сборки приложение не "
              "создаётся – на такой запрос она отвечает 400 \"Can't create application\"",
        "en": "assembly {assembly} is not in the build list of project {project}: the platform "
              "deletes the builds nobody uses, and no application can be created from a "
              "deleted one – it answers such a request with 400 \"Can't create application\"",
    },
    "client.source-nowhere": {
        "ru": "Другие проекты стенда эту сборку тоже не перечисляют",
        "en": "No other project of the stand lists the build either",
    },
    "client.app-source-exclusive": {
        "ru": "источник приложения – ровно один из параметров: project_version_id "
              "либо image_id",
        "en": "the application source is exactly one of the parameters: "
              "project_version_id or image_id",
    },
    "client.apps-summary": {
        "ru": "живых {live} из {total}",
        "en": "{live} live of {total}",
    },
    "client.apps-summary-shown": {
        "ru": "живых {live} из {total}, показано {shown}",
        "en": "{live} live of {total}, {shown} shown",
    },
    "client.app-users-summary": {
        "ru": "подключено {total}: администраторов {admins}, с доступом по токену {tokens}",
        "en": "{total} connected: {admins} administrators, {tokens} with token access",
    },
    "client.builds-summary-empty": {
        "ru": "показано {shown} из {total} – у проекта на платформе нет ни одной сборки",
        "en": "{shown} of {total} shown – the project has no builds on the platform",
    },
    "client.builds-summary-unnumbered": {
        "ru": "показано {shown} из {total} – номера нет ни у одной сборки, и по нумерации не "
              "видно, все ли это сборки проекта",
        "en": "{shown} of {total} shown – no build carries a number, so the numbering cannot "
              "tell whether these are all the builds of the project",
    },
    "client.builds-summary-full": {
        "ru": "показано {shown} из {total} – нумерация сборок сплошная, пропавших по ней "
              "не видно: это все сборки проекта на платформе",
        "en": "{shown} of {total} shown – the build numbering runs unbroken and nothing is "
              "missing from it: every build the project has on the platform",
    },
    "client.builds-summary-jumped": {
        "ru": "показано {shown} из {total} – пропавших по нумерации сборок не видно: это все "
              "сборки проекта на платформе",
        "en": "{shown} of {total} shown – nothing is missing from the build numbering: every "
              "build the project has on the platform",
    },
    "client.builds-summary-jump": {
        "ru": ". Скачок {jumps} – не удаление: эту сборку машина загрузила без ид проекта, "
              "номер она принесла из архива, и счет проекта пошел от него",
        "en": ". The jump {jumps} is no deletion: this machine uploaded that build without a "
              "project id, it brought its number from the archive, and the count of the "
              "project went on from it",
    },
    "client.builds-summary-jumps": {
        "ru": ". Скачки {jumps} – не удаления: эти сборки машина загрузила без ид проекта, "
              "номера они принесли из архива, и счет проекта пошел от них",
        "en": ". The jumps {jumps} are no deletions: this machine uploaded those builds without "
              "a project id, they brought their numbers from the archive, and the count of "
              "the project went on from them",
    },
    "client.builds-summary-trimmed": {
        "ru": "показано {shown} из {total} – в нумерации сборок есть пропуски: сборки, "
              "которыми никто не пользуется, платформа удаляет сама, когда приложение проекта "
              "заканчивает применение сборки (сборка работающего приложения остается), а "
              "страниц у перечня нет. Это НЕ вся история сборок проекта",
        "en": "{shown} of {total} shown – the build numbering has gaps: the platform deletes "
              "the builds nobody uses whenever an application of the project finishes "
              "applying a build (a build an application runs stays), and the listing has no "
              "pages. This is NOT the project's whole build history",
    },
    "client.builds-summary-trimmed-extension": {
        "ru": "показано {shown} из {total} – в нумерации сборок есть пропуски: сборки "
              "проекта-расширения платформа сама не удаляет, уборка его не трогает, значит, "
              "пропавшие сборки удалены вручную. Это НЕ вся история сборок проекта",
        "en": "{shown} of {total} shown – the build numbering has gaps: the platform never "
              "deletes the builds of an extension project, its housekeeping leaves such a "
              "project alone, so the missing builds were deleted by hand. This is NOT the "
              "project's whole build history",
    },
    "client.builds-summary-extension": {
        "ru": ". Уборки у проекта-расширения нет: сборки, которые больше не нужны, остаются, "
              "пока их не удалят вручную командой elemctl builds delete",
        "en": ". An extension project has no housekeeping: builds nobody needs any more stay "
              "until they are deleted by hand with elemctl builds delete",
    },
    "client.builds-summary-gap-first": {
        "ru": "под {above}",
        "en": "below {above}",
    },
    "client.builds-summary-jump-and-loss": {
        "ru": ". Пропуск {gap} – и скачок, и удаление: сборку {top} машина загрузила без ид "
              "проекта, и номер она принесла из архива, а из загрузок этой машины в проект в "
              "перечне уже нет {gone}",
        "en": ". The gap {gap} is a jump and a deletion at once: this machine uploaded {top} "
              "without a project id, and it brought its number from the archive, while "
              "the listing no longer has these uploads of this machine into the project: "
              "{gone}",
    },
    "client.builds-summary-and-more": {
        "ru": "{names} и еще {more}",
        "en": "{names} and {more} more",
    },
    "client.app-not-found": {
        "ru": "приложение '{name}' не найдено (ни по ид, ни по точному имени)",
        "en": "application '{name}' not found (neither by id nor by exact name)",
    },
    "client.app-name-ambiguous": {
        "ru": "имя приложения '{name}' неоднозначно, совпадений несколько: {ids} – "
              "укажите ид (UUID)",
        "en": "the application name '{name}' is ambiguous, there are several matches: "
              "{ids} – pass the id (UUID)",
    },
    "client.app-error-status": {
        "ru": "приложение {app} в статусе Error: {error}",
        "en": "application {app} is in status Error: {error}",
    },
    "client.wait-status-timeout": {
        "ru": "не дождались статуса {expected} приложения {app} за {timeout} с "
              "(текущий: {status})",
        "en": "did not reach status {expected} of application {app} within {timeout} s "
              "(current: {status})",
    },
    "client.wait-status-unknown": {
        "ru": "приложение {app} {seconds} с подряд в статусе UNKNOWN, статуса {expected} "
              "дальше не ждем: так консоль называет состояние приложения на сервере, "
              "которому у нее нет имени, и надолго оно бывает, например, у приложения, "
              "у которого пропала база, – такое не запустить и не удалить",
        "en": "application {app} has been in status UNKNOWN for {seconds} s in a row, so "
              "status {expected} is not waited for any longer: the console gives that "
              "status to a server state of the application it has no name for, and it "
              "lasts, for one, on an application whose database is gone – such an "
              "application can be neither started nor deleted",
    },
    "client.wait-ready-timeout": {
        "ru": "приложение {app} не стало готовым за {timeout} с (статус: {status}, uri: {uri})",
        "en": "application {app} did not become ready within {timeout} s "
              "(status: {status}, uri: {uri})",
    },
    "client.transitional-status": {
        "ru": "переходный",
        "en": "transitional",
    },
    "client.no-uri": {
        "ru": "нет",
        "en": "none",
    },
    "client.apply-source-required": {
        "ru": "нужен источник применения: image_id либо project_id",
        "en": "an apply source is required: image_id or project_id",
    },
    "client.apply-busy": {
        "ru": "приложение {app} занято предыдущей операцией – жду освобождения (до {seconds} с); "
              "сборка уже загружена, терять её незачем",
        "en": "application {app} is busy with a previous operation – waiting for it "
              "(up to {seconds} s); the build is uploaded already, there is nothing to gain "
              "by dropping it",
    },
    "client.apply-busy-gone": {
        "ru": "приложение освободилось, применение начато",
        "en": "the application is free again, the apply has started",
    },
    "client.server-starting": {
        "ru": "сервер 1С:Элемент ещё стартует: его консоль не поднялась и отвечает 404 "
              "\"Application \"console\" not found\" ({method} {url}). Запрос тут ни при чём – "
              "повторите, когда {console} начнёт отвечать 302",
        "en": "the 1C:Element server is still starting: its console is not up yet and answers "
              "404 \"Application \"console\" not found\" ({method} {url}). The request is not "
              "at fault – repeat once {console} answers 302",
    },
    "client.server-start-timeout": {
        "ru": "сервер 1С:Элемент не поднял консоль за {seconds} с: она всё ещё отвечает 404 "
              "\"Application \"console\" not found\" ({method} {url}). Повторите, когда "
              "{console} начнёт отвечать 302",
        "en": "the 1C:Element server did not bring its console up in {seconds} s: it still "
              "answers 404 \"Application \"console\" not found\" ({method} {url}). Repeat once "
              "{console} answers 302",
    },
    "client.server-starting-wait": {
        "ru": "сервер 1С:Элемент стартует: консоль отвечает 404 \"Application \"console\" not "
              "found\" – жду её до {seconds} с, спрашиваю раз в {poll} с",
        "en": "the 1C:Element server is starting: its console answers 404 \"Application "
              "\"console\" not found\" – waiting for it up to {seconds} s, asking every {poll} s",
    },
    "client.server-started": {
        "ru": "консоль сервера поднялась – продолжаю",
        "en": "the server console is up – going on",
    },
    "client.api-error": {
        "ru": "Console API ответил {status} на {method} {url}",
        "en": "Console API responded {status} to {method} {url}",
    },
    "client.method-unknown": {
        "ru": "сервер не знает метода {method} {url}: консоль ответила 401 \"Handler of HTTP "
              "request ... not found\", а так она отвечает на путь, для которого у нее нет "
              "обработчика. Токен тут ни при чем: сервер старше этого метода Console API {api}",
        "en": "the server does not know the method {method} {url}: the console answered 401 "
              "\"Handler of HTTP request ... not found\", which is how it answers a path it has "
              "no handler for. The token is not at fault: the server is older than this method "
              "of Console API {api}",
    },
    "client.extension-not-found": {
        "ru": "у приложения {app} нет расширения '{name}' (сравнивались ид расширения, ид его "
              "проекта, имя и представление проекта). Примененные расширения: {extensions}",
        "en": "the application {app} has no extension '{name}' (compared: the extension id, "
              "the id of its project, the name and the presentation of the project). Applied "
              "extensions: {extensions}",
    },
    "client.extensions-none": {
        "ru": "ни одного",
        "en": "none",
    },
    "client.extension-ambiguous": {
        "ru": "под '{name}' в приложении {app} подходит несколько расширений: {extensions} – "
              "укажите ид расширения",
        "en": "several extensions of the application {app} match '{name}': {extensions} – "
              "give the extension id",
    },
    "client.extension-without-id": {
        "ru": "консоль не назвала ид расширения {extension} в приложении {app} (поле id пусто), "
              "а без него сборку расширения не выгрузить",
        "en": "the console named no id for the extension {extension} of the application {app} "
              "(the id field is empty), and the build of an extension cannot be exported "
              "without it",
    },
    "client.extension-export-not-archive": {
        "ru": "выгрузка расширения {extension} из приложения {app} вернула не архив сборки "
              "({size} байт, начало: {start}); файл не записан",
        "en": "the export of the extension {extension} of the application {app} returned no "
              "build archive ({size} bytes, beginning: {start}); no file was written",
    },
    "client.app-export-not-archive": {
        "ru": "выгрузка проекта приложения {app} вернула не архив сборки ({size} байт, "
              "начало: {start}); файл не записан",
        "en": "the export of the project of the application {app} returned no build archive "
              "({size} bytes, beginning: {start}); no file was written",
    },
    "client.delete-failed-precondition": {
        "ru": "в среде разработки приложения есть неопубликованные правки – "
              "платформа не удаляет такие приложения через API; опубликуйте "
              "или отмените правки, либо удалите приложение через панель управления",
        "en": "the application's development environment has unpublished changes – "
              "the platform does not delete such applications via the API; publish "
              "or discard the changes, or delete the application through the control panel",
    },
    "client.app-created-with-error": {
        "ru": "приложение {app} создано со статусом Error: {error}",
        "en": "application {app} was created with status Error: {error}",
    },
    "client.no-error-text": {
        "ru": "без текста ошибки",
        "en": "no error text",
    },
    "client.waiting-status": {
        "ru": "статус приложения: {status} – ждём...",
        "en": "application status: {status} – waiting...",
    },
    "client.transitional": {
        "ru": "(переходный)",
        "en": "(transitional)",
    },
    "client.waiting-ready": {
        "ru": "ждём готовности приложения: статус {status}...",
        "en": "waiting for the application to be ready: status {status}...",
    },
    "client.waiting-read-broken": {
        "ru": "чтение карточки оборвалось, ждём дальше: {error}",
        "en": "reading the card broke off, waiting on: {error}",
    },
    "client.user-list-not-found": {
        "ru": "список пользователей '{name}' не найден",
        "en": "the user list '{name}' was not found",
    },
    "client.user-list-ambiguous": {
        "ru": "под представление '{name}' подходит несколько списков пользователей: {ids} – "
              "укажите ид",
        "en": "several user lists match the presentation '{name}': {ids} – give the id",
    },
    "client.app-user-not-connected": {
        "ru": "пользователь '{user}' не подключён к приложению {app}: среди пользователей "
              "приложения его нет, а доступ по токену платформа меняет только подключённым. "
              "Подключены: {connected}",
        "en": "the user '{user}' is not connected to the application {app}: the users of the "
              "application do not include them, and the platform changes token access for "
              "connected users only. Connected: {connected}",
    },
    "client.app-users-none": {
        "ru": "никто",
        "en": "nobody",
    },
    "client.app-user-ambiguous": {
        "ru": "пользователю '{user}' в приложении {app} соответствует несколько подключений: "
              "{ids} – укажите ид пользователя",
        "en": "several connections of the application {app} match the user '{user}': {ids} – "
              "give the user id",
    },
    "client.token-access-not-changed": {
        "ru": "платформа приняла изменение доступа по токену для '{user}' в приложении {app}, "
              "но перечитанное подключение показывает token-access-enabled: {now} вместо "
              "{wanted}",
        "en": "the platform accepted the change of token access for '{user}' in the "
              "application {app}, but the connection read back shows token-access-enabled: "
              "{now} instead of {wanted}",
    },
    "client.token-access-user-gone": {
        "ru": "платформа приняла изменение доступа по токену для '{user}' в приложении {app}, "
              "но после него приложение этого пользователя среди своих не называет",
        "en": "the platform accepted the change of token access for '{user}' in the "
              "application {app}, but after it the application no longer lists that user",
    },
    "client.app-has-no-user-list": {
        "ru": "у приложения {app} нет собственного списка пользователей (default-user-list пуст)",
        "en": "the application {app} has no user list of its own (default-user-list is empty)",
    },
    "client.account-service-id-required": {
        "ru": "у сервиса учётных записей не задан account-service-id",
        "en": "the account service has no account-service-id",
    },
    "client.waiting-deleted": {
        "ru": "ждём удаления приложения: статус {status}...",
        "en": "waiting for the application to be deleted: status {status}...",
    },
    "client.stopping": {
        "ru": "статус {status} – останавливаем приложение...",
        "en": "status {status} – stopping the application...",
    },
    "client.starting": {
        "ru": "запускаем приложение...",
        "en": "starting the application...",
    },
    # -- config.py ----------------------------------------------------------------
    "config.unknown-params": {
        "ru": "неизвестные параметры конфигурации: {unknown}",
        "en": "unknown configuration parameters: {unknown}",
    },
    "config.env-file-not-found": {
        "ru": ".env-файл не найден: {path} (искали {absolute}; относительный путь "
              "разрешается от текущего каталога {cwd}, а не от каталога проекта)",
        "en": ".env file not found: {path} (looked for {absolute}; a relative path "
              "is resolved from the current directory {cwd}, not from the project "
              "directory)",
    },
    "config.connection-not-set": {
        "ru": "не заданы параметры подключения: {missing} (переменные окружения, "
              ".env-файл или флаги CLI)",
        "en": "connection parameters are not set: {missing} (environment variables, "
              "the .env file or CLI flags)",
    },
    "config.invalid-boolean": {
        "ru": "неверное логическое значение {name}={value!r}; используйте true или false",
        "en": "invalid boolean value {name}={value!r}; use true or false",
    },
    "config.invalid-base-url": {
        "ru": "неверный базовый URL {value!r}; используйте адрес с http:// или https://",
        "en": "invalid base URL {value!r}; use an address starting with http:// or https://",
    },
    "config.ca-file-invalid": {
        "ru": "не удалось загрузить CA-файл {path}: {error}",
        "en": "failed to load CA file {path}: {error}",
    },
    # -- mcp_server.py ------------------------------------------------------------
    "mcp.project-or-version-required": {
        "ru": "нужен project_id или version_id",
        "en": "project_id or version_id is required",
    },
    "mcp.project-has-no-builds": {
        "ru": "у проекта {project_id} нет сборок – загрузите сборку или укажите version_id",
        "en": "project {project_id} has no builds – upload one or pass version_id",
    },
    "mcp.plugin-failed": {
        "ru": "плагин '{source}' не загрузился, его инструментов нет: {error}",
        "en": "plugin '{source}' did not load, its tools are unavailable: {error}",
    },
    "mcp.source-instead": {
        "ru": "Приложение {app} работает на сборке {build}: передайте её в version_id. "
              "С project_id и без version_id инструмент возьмёт самую свежую сборку проекта",
        "en": "Application {app} runs build {build}: pass it as version_id. Given project_id "
              "and no version_id, the tool takes the project's newest build",
    },
    "mcp.source-latest": {
        "ru": "С project_id и без version_id инструмент возьмёт самую свежую сборку проекта",
        "en": "Given project_id and no version_id, the tool takes the project's newest build",
    },
    "mcp.source-project-from-env": {
        "ru": "Проект взят из ELEMENT_PROJECT_ID стенда: если сборка из другого проекта, "
              "назовите его в project_id",
        "en": "The project comes from the stand's ELEMENT_PROJECT_ID: if the build belongs "
              "to another project, name that one in project_id",
    },
    "mcp.source-other-project": {
        "ru": "сборки {build} нет в проекте {project}, названном в project_id: она лежит в "
              "проекте {owner}. Передайте project_id {owner_id} или не передавайте project_id "
              "вовсе – проект сборки найдется сам",
        "en": "build {build} is not in project {project} given as project_id: it belongs to "
              "project {owner}. Pass project_id {owner_id}, or leave project_id out and the "
              "project of the build is found by itself",
    },
    "mcp.extra-required": {
        "ru": 'для MCP-сервера нужен extra: pip install "elemctl[mcp]"',
        "en": 'the MCP server needs the extra: pip install "elemctl[mcp]"',
    },
    # -- plugins.py ---------------------------------------------------------------
    "plugins.entry-point-failed": {
        "ru": "точка расширения '{name}' группы {group} не загрузилась ({value}): {error}",
        "en": "the entry point '{name}' of the group {group} failed to load ({value}): {error}",
    },
    "plugins.factory-failed": {
        "ru": "точка расширения '{name}' группы {group} ({value}) не отдала содержимое: её "
              "функция завершилась ошибкой {error}. Плагин мог быть написан под более новое "
              "ядро, чем установленное elemctl {version}: обновите elemctl (elemctl "
              "self-update) или плагин",
        "en": "entry point '{name}' of group {group} ({value}) did not hand over its contents: "
              "its function failed with {error}. The plugin may be written for a newer core "
              "than the installed elemctl {version}: update elemctl (elemctl self-update) or "
              "the plugin",
    },
    "plugins.not-commands": {
        "ru": "точка расширения '{name}' обязана дать Command, их список или функцию без "
              "аргументов, возвращающую одно из этого; получено: {value}",
        "en": "the entry point '{name}' must give a Command, a list of them or a function "
              "without arguments returning either; got: {value}",
    },
    "plugins.command-name-required": {
        "ru": "у команды плагина '{where}' пустое имя",
        "en": "a command of the plugin '{where}' has an empty name",
    },
    "plugins.command-handler-required": {
        "ru": "у команды '{name}' плагина '{where}' обработчик не вызываемый",
        "en": "the handler of the command '{name}' of the plugin '{where}' is not callable",
    },
    "plugins.not-an-argument": {
        "ru": "у команды '{name}' плагина '{where}' аргумент объявлен не типом Argument: {value}",
        "en": "the command '{name}' of the plugin '{where}' declares an argument that is not "
              "an Argument: {value}",
    },
    "plugins.argument-type-unsupported": {
        "ru": "аргумент {argument} команды '{name}' плагина '{where}' объявлен типом {type}; "
              "поддерживаются: {supported}",
        "en": "the argument {argument} of the command '{name}' of the plugin '{where}' is "
              "declared as {type}; supported are: {supported}",
    },
    "plugins.flag-must-be-option": {
        "ru": "аргумент {argument} команды '{name}' плагина '{where}' булев, а такой аргумент "
              "может быть только опцией (имя с дефисами впереди)",
        "en": "the argument {argument} of the command '{name}' of the plugin '{where}' is "
              "boolean, and such an argument can only be an option (a name starting with dashes)",
    },
    "plugins.multiple-flag": {
        "ru": "аргумент {argument} команды '{name}' плагина '{where}' объявлен повторяемым "
              "(multiple), а это флаг: флаг, указанный дважды, значит то же, что указанный "
              "один раз. Повторяемой может быть опция со значением или позиционный аргумент",
        "en": "the argument {argument} of the command '{name}' of the plugin '{where}' is "
              "declared multiple, and it is a flag: a flag given twice means what it means "
              "given once. An option with a value or a positional argument can be multiple",
    },
    "plugins.multiple-default": {
        "ru": "у повторяемого аргумента {argument} команды '{name}' плагина '{where}' "
              "умолчание {default}, а оно обязано быть списком значений (list или tuple) либо "
              "None",
        "en": "the multiple argument {argument} of the command '{name}' of the plugin '{where}' "
              "has the default {default}, and it has to be a list of values (a list or a "
              "tuple) or None",
    },
    "plugins.argument-duplicate": {
        "ru": "у команды '{name}' плагина '{where}' два аргумента дают одно имя значения: {argument}",
        "en": "two arguments of the command '{name}' of the plugin '{where}' give the same "
              "value name: {argument}",
    },
    "plugins.command-name-taken": {
        "ru": "плагин '{where}' приносит команду '{name}', но такая команда у elemctl уже есть – "
              "плагин обязан выбрать другое имя",
        "en": "the plugin '{where}' brings the command '{name}', but elemctl already has one – "
              "the plugin has to pick another name",
    },
    "plugins.tool-name-taken": {
        "ru": "плагин '{where}' приносит инструмент MCP '{name}', но такой у elemctl уже есть – "
              "поможет mcp_name у команды",
        "en": "the plugin '{where}' brings the MCP tool '{name}', but elemctl already has one – "
              "the mcp_name of the command helps here",
    },
    "plugins.no-client": {
        "ru": "команде плагина не с чем обратиться к платформе: клиент не передан",
        "en": "a command of a plugin has nothing to reach the platform with: no client was given",
    },
    "plugins.alias-needs-positional": {
        "ru": "аргумент {argument} команды '{name}' плагина '{where}' объявляет cli_alias, а "
              "сам не позиционный – синоним имеет смысл только у позиционного аргумента, у "
              "опции уже есть имя, каким её вызывать",
        "en": "the argument {argument} of the command '{name}' of the plugin '{where}' declares "
              "cli_alias while not being positional itself – a synonym only makes sense for a "
              "positional argument, an option already has a name to call it by",
    },
    "plugins.alias-not-an-option": {
        "ru": "cli_alias '{alias}' аргумента {argument} команды '{name}' плагина '{where}' "
              "обязан начинаться с дефиса, как имя опции",
        "en": "the cli_alias '{alias}' of the argument {argument} of the command '{name}' of "
              "the plugin '{where}' has to start with a dash, like an option name",
    },
    "plugins.alias-duplicate": {
        "ru": "у команды '{name}' плагина '{where}' несколько аргументов претендуют на один и "
              "тот же ключ CLI: {flags}",
        "en": "several arguments of the command '{name}' of the plugin '{where}' claim the same "
              "CLI flag: {flags}",
    },
    "plugins.global-option-taken": {
        "ru": "аргумент {argument} команды '{name}' плагина '{where}' занимает имя общего "
              "ключа elemctl {option}. Общий ключ ядро разбирает само, где бы он ни стоял, и "
              "значение не дошло бы до команды либо подменило бы значение ядра. Выберите "
              "другое имя; общие ключи ядра: {options}",
        "en": "the argument {argument} of the command '{name}' of the plugin '{where}' takes the "
              "name of the global elemctl option {option}. The core parses a global option "
              "itself wherever it stands, so the value would either never reach the command or "
              "replace the value of the core. Pick another name; the global options of the core "
              "are: {options}",
    },
    "plugins.value-name-taken": {
        "ru": "аргумент {argument} команды '{name}' плагина '{where}' хранит значение под "
              "именем {dest}, а это имя в разборе команды уже занимает сам CLI. Одно значение "
              "затерло бы другое: позиционный handler, например, подменял обработчик команды "
              "строкой. Выберите другое имя; занятые имена: {names}",
        "en": "the argument {argument} of the command '{name}' of the plugin '{where}' keeps "
              "its value under the name {dest}, and the CLI itself already keeps a value of "
              "that name in the parse of a command. One value would overwrite the other: a "
              "positional handler, for one, replaced the handler of the command with a string. "
              "Pick another name; the names taken are: {names}",
    },
    "plugins.option-taken": {
        "ru": "аргумент {argument} команды '{name}' плагина '{where}' объявляет ключ {option}, "
              "а на этот ключ подкоманда отвечает сама, и разборщик всего CLI не собрался бы. "
              "Выберите другое имя; занятые ключи: {options}",
        "en": "the argument {argument} of the command '{name}' of the plugin '{where}' declares "
              "the option {option}, which a subcommand answers itself, so the parser of the "
              "whole CLI could not be built. Pick another name; the options taken are: {options}",
    },
    "cli.help.plugin-alias": {
        "ru": "то же, что позиционный аргумент {name}",
        "en": "the same as the positional argument {name}",
    },
    "cli.help.plugin-multiple": {
        "ru": "(ключ можно повторить, по значению на каждый)",
        "en": "(the key may be repeated, one value each)",
    },
    "cli.help.plugin-multiple-positional": {
        "ru": "(можно назвать несколько значений через пробел)",
        "en": "(several values may be given, separated by spaces)",
    },
    "cli.help.selfupdate-stop": {
        "ru": "снять серверы, держащие установку (MCP-сессии elemctl), и обновиться. Идущие "
              "команды других сессий называются по pid и не трогаются; со значением all "
              "снимаются и они, и такая команда обрывается без результата. Без флага "
              "держатели только называются",
        "en": "stop the servers holding the installation (elemctl MCP sessions) and update. "
              "Running commands of other sessions are named by pid and left alone; with the "
              "value all they are stopped too, and such a command ends without a result. "
              "Without the flag the holders are only named",
    },
    # -- selfupdate.py ------------------------------------------------------------
    "selfupdate.version-not-found": {
        "ru": "версия не найдена на PyPI",
        "en": "the version was not found on PyPI",
    },
    "selfupdate.pypi-http-error": {
        "ru": "PyPI ответил {status}",
        "en": "PyPI responded {status}",
    },
    "selfupdate.pypi-unreachable": {
        "ru": "не удалось обратиться к PyPI: {error}",
        "en": "could not reach PyPI: {error}",
    },
    "selfupdate.no-wheel": {
        "ru": "на PyPI нет wheel для elemctl {version}",
        "en": "PyPI has no wheel for elemctl {version}",
    },
    "selfupdate.already-current": {
        "ru": "уже актуально: elemctl {version}",
        "en": "already current: elemctl {version}",
    },
    "selfupdate.sources-differ": {
        "ru": "источники PyPI расходятся: {sources}. Беру {version}: списки выпусков догоняют "
              "новую версию за несколько минут",
        "en": "the PyPI sources disagree: {sources}. Taking {version}: the release listings "
              "catch up with a new version within minutes",
    },
    "selfupdate.source-simple": {
        "ru": "простой индекс называет последней {version}",
        "en": "the simple index names {version} as the latest",
    },
    "selfupdate.source-summary": {
        "ru": "сводный JSON – {version}",
        "en": "the JSON summary names {version}",
    },
    "selfupdate.source-page": {
        "ru": "страница версии {version} уже опубликована",
        "en": "the page of version {version} is already published",
    },
    "selfupdate.newer-installed": {
        "ru": "установлена elemctl {installed}, а PyPI пока называет последней {latest}: "
              "списки выпусков ещё не догнали новую версию. Ничего не меняю",
        "en": "elemctl {installed} is installed, while PyPI still names {latest} as the "
              "latest: the release listings have not caught up with the new version yet. "
              "Nothing changed",
    },
    "selfupdate.downloading": {
        "ru": "скачиваю elemctl {version} с PyPI...",
        "en": "downloading elemctl {version} from PyPI...",
    },
    "selfupdate.download-failed": {
        "ru": "не удалось скачать колесо: {error}",
        "en": "could not download the wheel: {error}",
    },
    "selfupdate.unpacking": {
        "ru": "распаковываю в {path}...",
        "en": "unpacking into {path}...",
    },
    "selfupdate.done": {
        "ru": "готово: elemctl {before} -> {after}, импорт проверен отдельным процессом. "
              "Перезапустите MCP-сессии (elemctl mcp).",
        "en": "done: elemctl {before} -> {after}, the import verified in a separate process. "
              "Restart the MCP sessions (elemctl mcp).",
    },
    "selfupdate.busy": {
        "ru": "установку сейчас не заменить – файлы заняты ({error}). {holders}. "
              "Прежняя установка НЕ ТРОНУТА и работает",
        "en": "the installation cannot be replaced right now – files are held ({error}). "
              "{holders}. The previous installation is UNTOUCHED and working",
    },
    "selfupdate.holders": {
        "ru": "Держат установку серверы: {list}",
        "en": "Servers holding the installation: {list}",
    },
    "selfupdate.holders-commands": {
        "ru": "Идут команды: {list}",
        "en": "Commands are running: {list}",
    },
    "selfupdate.holders-unknown": {
        "ru": "Определить держателей не удалось; обычно это MCP-сессии агента (elemctl mcp)",
        "en": "Could not tell which processes hold it; usually the agent's MCP sessions "
              "(elemctl mcp)",
    },
    "selfupdate.advice-servers": {
        "ru": "Закройте их и повторите, либо запустите с --stop-holders",
        "en": "Close them and repeat, or run with --stop-holders",
    },
    "selfupdate.advice-close": {
        "ru": "Закройте их и повторите",
        "en": "Close them and repeat",
    },
    "selfupdate.advice-commands": {
        "ru": "Это чужая работа, и --stop-holders ее не трогает: дождитесь конца команд и "
              "повторите. Ключ --stop-holders=all снимет и их, но такая команда оборвется без "
              "результата",
        "en": "That is someone else's work, and --stop-holders leaves it alone: wait for the "
              "commands to finish and repeat. --stop-holders=all stops them as well, and such "
              "a command ends without a result",
    },
    "selfupdate.server-stopped": {
        "ru": "остановлен сервер: {process}",
        "en": "stopped the server: {process}",
    },
    "selfupdate.command-stopped": {
        "ru": "остановлена команда: {process}",
        "en": "stopped the command: {process}",
    },
    "selfupdate.stop-failed": {
        "ru": "не удалось остановить {process}: {error}",
        "en": "could not stop {process}: {error}",
    },
    "selfupdate.command-spared": {
        "ru": "не трогаю идущую команду: {process}",
        "en": "leaving a running command alone: {process}",
    },
    "selfupdate.process": {"ru": "процесс", "en": "process"},
    "selfupdate.unpack-failed": {
        "ru": "распаковка не удалась ({error}); прежняя установка возвращена на место",
        "en": "extraction failed ({error}); the previous installation is back in place",
    },
    "selfupdate.unverified": {
        "ru": "новая установка не проверилась ({reason}); возвращена прежняя версия {version}",
        "en": "the new installation did not verify ({reason}); the previous version {version} "
              "is back",
    },
    "selfupdate.reason-version": {
        "ru": "импорт отдал {version}",
        "en": "the import answered {version}",
    },
    "selfupdate.reason-no-import": {
        "ru": "пакет не импортируется",
        "en": "the package does not import",
    },
    "selfupdate.metadata-updated": {
        "ru": "обновлён pipx_metadata.json",
        "en": "pipx_metadata.json updated",
    },
    # -- transport.py -------------------------------------------------------------
    "transport.network-error": {
        "ru": "сетевая ошибка {method} {url}: {error}",
        "en": "network error {method} {url}: {error}",
    },
    "transport.invalid-url": {
        "ru": "недопустимый адрес запроса {method} {url}: {error}",
        "en": "invalid request address {method} {url}: {error}",
    },
    "transport.tls-verify-off": {
        "ru": "внимание: проверка сертификата и имени сервера отключена – соединение не "
              "защищено от подмены сервера",
        "en": "warning: certificate and host name verification is off – the connection is "
              "not protected from a spoofed server",
    },
    "transport.tls-verify-off-by": {
        "ru": "внимание: проверка сертификата и имени сервера отключена ({reason}) – "
              "соединение не защищено от подмены сервера",
        "en": "warning: certificate and host name verification is off ({reason}) – the "
              "connection is not protected from a spoofed server",
    },
    "transport.proxy-hint": {
        "ru": "Запрос шёл через прокси {proxy} из окружения. Если стенд внутренний, "
              "прокси до него не дотянется: задайте {variable}=1 (переменной окружения или "
              "строкой в .env этого стенда) или добавьте хост в NO_PROXY.",
        "en": "The request went through the proxy {proxy} from the environment. An internal "
              "stand is not reachable that way: set {variable}=1 (as an environment variable, "
              "or as a line in this stand's .env file) or add the host to NO_PROXY.",
    },
    # -- auth.py ------------------------------------------------------------------
    "auth.token-http-error": {
        "ru": "не удалось получить токен: HTTP {status}",
        "en": "failed to obtain a token: HTTP {status}",
    },
    "auth.token-not-found": {
        "ru": "токен не найден в ответе сервера (ожидались поля id_token, token, "
              "value или access_token)",
        "en": "no token in the server response (the id_token, token, value or "
              "access_token fields were expected)",
    },
    # -- deploy.py ----------------------------------------------------------------
    "deploy.built": {
        "ru": "собран архив {file} (версия {version})",
        "en": "built archive {file} (version {version})",
    },
    "deploy.dirty-tree": {
        "ru": "внимание: в каталоге проекта незакоммиченные изменения ({count}): {files} – "
              "в архив снято текущее состояние диска, а не HEAD",
        "en": "warning: the project directory has uncommitted changes ({count}): {files} – "
              "the archive captured the current disk state, not HEAD",
    },
    "deploy.and-more": {
        "ru": " и ещё {count}",
        "en": " and {count} more",
    },
    "deploy.destructive-changes": {
        "ru": "ОТКАЗ: применение уничтожит данные – находок {count}: {changes}. Расширение длин "
              "данные сохраняет, а сужение, смена типа и снятие целиком элемента со своими "
              "данными – нет. Если потеря данных допустима, повторите с флагом --allow-data-loss "
              "(у инструмента MCP deploy – allow_data_loss=true)",
        "en": "REFUSED: the apply would destroy data – {count} finding(s): {changes}. Widening "
              "keeps the data; a narrowing, a type change and an element with data of its own "
              "removed whole do not. If losing the data is acceptable, repeat with "
              "--allow-data-loss (allow_data_loss=true for the MCP tool deploy)",
    },
    "deploy.destructive-allowed": {
        "ru": "внимание: находок {count}, данные будут пересозданы или удалены "
              "(--allow-data-loss): {changes}",
        "en": "warning: {count} finding(s), the data will be recreated or deleted "
              "(--allow-data-loss): {changes}",
    },
    "deploy.schema-check-skipped": {
        "ru": "сверка схемы не выполнена ({reason}) – сравнить не с чем, это НЕ значит, что "
              "применение безопасно",
        "en": "the schema check did not run ({reason}) – there is nothing to compare against, "
              "which does NOT mean the apply is safe",
    },
    "deploy.schema-skipped-no-project-dir": {
        "ru": "сверка схемы не выполнена: каталог проекта не найден – сравнивать нечего; это НЕ "
              "значит, что применение безопасно",
        "en": "the schema check did not run: the project directory was not found – there is "
              "nothing to compare; this does NOT mean the apply is safe",
    },
    "deploy.schema-skipped-read-failed": {
        "ru": "сверка схемы не выполнена: не удалось прочитать карточку приложения или перечень "
              "сборок ({detail}); это НЕ значит, что применение безопасно",
        "en": "the schema check did not run: the application card or the build list could not "
              "be read ({detail}); this does NOT mean the apply is safe",
    },
    "deploy.schema-skipped-no-applied-build": {
        "ru": "сверка схемы не выполнена: карточка приложения не называет применённую сборку – "
              "сравнивать не с чем",
        "en": "the schema check did not run: the application card names no applied build – "
              "there is nothing to compare against",
    },
    "deploy.schema-skipped-no-applied-extension": {
        "ru": "сверка схемы не выполнена: среди расширений приложения нет расширения проекта "
              "{project} – расширение применяется впервые, сравнивать не с чем",
        "en": "the schema check did not run: the application has no extension of project "
              "{project} yet – the extension is applied for the first time, there is nothing "
              "to compare against",
    },
    "deploy.schema-skipped-applied-build-not-listed": {
        "ru": "сверка схемы не выполнена: применённой сборки {detail} нет в перечне сборок "
              "проекта {project} – похоже, приложение работает на сборке другого проекта; это "
              "НЕ значит, что применение безопасно",
        "en": "the schema check did not run: the applied build {detail} is not in the build "
              "list of project {project} – the application seems to run a build of another "
              "project; this does NOT mean the apply is safe",
    },
    "deploy.schema-skipped-no-commit-id": {
        "ru": "сверка схемы не выполнена: у применённой сборки {detail} не записан коммит, и "
              "локальный реестр загрузок его не знает – сравнивать не с чем. Коммит в карточку "
              "записывает загрузка elemctl в существующий проект, а загрузки этой машины помнит "
              "реестр; сборки, загруженные иначе, с другой машины или прежними версиями, "
              "коммита не несут, а выкат из git-репозитория запишет свой, и следующей сверке "
              "будет с чем сравнить. Это НЕ значит, что применение безопасно",
        "en": "the schema check did not run: the applied build {detail} carries no commit, and "
              "the local registry of uploads does not know it – there is nothing to compare "
              "against. The commit is written to the card by an elemctl upload into an existing "
              "project, and the registry remembers the uploads of this machine; builds uploaded "
              "otherwise, from another machine or by earlier versions carry none, and a deploy "
              "from a git repository writes its own, so the next check has something to "
              "compare. This does NOT mean the apply is safe",
    },
    "deploy.schema-commit-from-registry": {
        "ru": "сверка схемы идёт с коммитом {commit} из локального реестра загрузок: в "
              "карточке применённой сборки {build} коммита нет",
        "en": "the schema is compared with the commit {commit} from the local registry of "
              "uploads: the card of the applied build {build} carries no commit",
    },
    "deploy.schema-commit-from-registry-dirty": {
        "ru": "сверка схемы идёт с коммитом {commit} из локального реестра загрузок: в "
              "карточке применённой сборки {build} коммита нет. Реестр помнит, что эта сборка "
              "собрана из дерева с незакоммиченными правками, и их сверка не увидит",
        "en": "the schema is compared with the commit {commit} from the local registry of "
              "uploads: the card of the applied build {build} carries no commit. The registry "
              "remembers that this build was made from a tree with uncommitted changes, and "
              "the check does not see them",
    },
    "deploy.schema-skipped-commit-unavailable": {
        "ru": "сверка схемы не выполнена: коммита {detail} применённой сборки нет в локальном "
              "репозитории (не сделан git fetch?) – сравнивать не с чем; это НЕ значит, что "
              "применение безопасно",
        "en": "the schema check did not run: the commit {detail} of the applied build is not in "
              "the local repository (no git fetch?) – there is nothing to compare against; this "
              "does NOT mean the apply is safe",
    },
    "deploy.schema-removal": {
        "ru": "внимание: {change}; сервер применяет такое без вопросов",
        "en": "warning: {change}; the server applies that without asking",
    },
    "deploy.schema-not-checked": {
        "ru": "сверка схемы в этот раз не проводилась ({reason}): что применение сузило или "
              "сняло, не проверено",
        "en": "the schema was not checked this time ({reason}): what the apply narrowed or "
              "removed went unchecked",
    },
    "deploy.schema-removed-summary": {
        "ru": "применение сняло элементы с данными: {count} – строки \"снимается\" выше",
        "en": "the apply removed elements that hold data: {count} – see the \"removed\" lines "
              "above",
    },
    # -- registry.py --------------------------------------------------------------
    "registry.write-failed": {
        "ru": "внимание: загрузка не записана в локальный реестр ({path}): {error}. Сборка "
              "загружена; ветку и каталог исходников этой сборки листинги не покажут",
        "en": "warning: the upload was not written to the local registry ({path}): {error}. The "
              "build is uploaded; the listings will not show its branch and source directory",
    },
    "registry.limit-invalid": {
        "ru": "внимание: {variable}={value} – не целое число; реестр загрузок хранит "
              "последние {default} загрузок, как по умолчанию (0 – хранить все)",
        "en": "warning: {variable}={value} is not a whole number; the registry of uploads keeps "
              "the last {default} uploads, the default (0 keeps them all)",
    },
    # -- schema.py ----------------------------------------------------------------
    "schema.kind-attribute": {"ru": "реквизит", "en": "attribute"},
    "schema.kind-dimension": {"ru": "измерение", "en": "dimension"},
    "schema.kind-resource": {"ru": "ресурс", "en": "resource"},
    "schema.length-narrowed": {
        "ru": "{where}: {kind} {name} – длина сужена с {before} до {after}",
        "en": "{where}: {kind} {name} – the length narrowed from {before} to {after}",
    },
    "schema.type-changed": {
        "ru": "{where}: {kind} {name} – тип изменён с {before} на {after}",
        "en": "{where}: {kind} {name} – the type changed from {before} to {after}",
    },
    "schema.dimension-type-changed": {
        "ru": "{where}: {kind} {name} – тип изменён с {before} на {after}; записи регистра "
              "будут конвертированы к новому типу, значения схлопнутся, и применение "
              "упадёт на неуникальности ключей",
        "en": "{where}: {kind} {name} – the type changed from {before} to {after}; the records "
              "of the register will be converted to the new type, the values will collapse "
              "and the apply will fail on the uniqueness of the keys",
    },
    "schema.dimension-removed": {
        "ru": "{where}: измерение {name} удалено – записи регистра схлопнутся на оставшихся "
              "ключах и станут неуникальными",
        "en": "{where}: dimension {name} removed – the records of the register will collapse "
              "onto the keys that are left and stop being unique",
    },
    "schema.attribute-removed": {
        "ru": "{where}: снимается реквизит {name} объекта {object} – его значения будут удалены",
        "en": "{where}: attribute {name} of {object} is removed – its values will be deleted",
    },
    "schema.resource-removed": {
        "ru": "{where}: снимается ресурс {name} регистра {object} – его значения будут удалены",
        "en": "{where}: resource {name} of the register {object} is removed – its values will "
              "be deleted",
    },
    "schema.tabular-part-removed": {
        "ru": "{where}: снимается табличная часть {part} объекта {object} – строки будут удалены",
        "en": "{where}: the tabular part {part} of {object} is removed – its rows will be "
              "deleted",
    },
    "schema.tabular-attribute-removed": {
        "ru": "{where}: снимается реквизит {name} табличной части {part} объекта {object} – "
              "его значения в строках будут удалены",
        "en": "{where}: attribute {name} of the tabular part {part} of {object} is removed – "
              "its values in the rows will be deleted",
    },
    "schema.element-removed": {
        "ru": "{where}: снимается {kind} {name} целиком – вся его таблица будет удалена вместе "
              "со строками",
        "en": "{where}: the {kind} {name} is removed whole – its table will be deleted with "
              "every row",
    },
    "schema.element-recreated": {
        "ru": "{where}: новый Ид у элемента {name} ({kind}) – платформа снимет прежний вместе "
              "со всей таблицей и заведёт пустой; если элемент тот же, верните ему прежний "
              "Ид {before}",
        "en": "{where}: the {kind} {name} has a new Id – the platform drops the old one with "
              "its whole table and creates an empty one; if it is the same {kind}, give it "
              "back its former Id {before}",
    },
    "schema.element-catalog": {"ru": "справочник", "en": "catalog"},
    "schema.element-document": {"ru": "документ", "en": "document"},
    "schema.element-information-register": {
        "ru": "регистр сведений",
        "en": "information register",
    },
    "schema.element-accumulation-register": {
        "ru": "регистр накопления",
        "en": "accumulation register",
    },
    "schema.element-constants-set": {"ru": "набор констант", "en": "constants set"},
    "schema.element-exchange-plan": {"ru": "план обмена", "en": "exchange plan"},
    "schema.element-settings-storage": {"ru": "хранилище настроек", "en": "settings storage"},
    "deploy.skipped-files": {
        "ru": "внимание: в архив НЕ вошли файлы ({count}): {files} – расширение вне списка "
              "разрешённых, а файл лежит не в каталоге Ресурсы; на применении это даёт "
              "\"Неизвестный ресурс\"",
        "en": "warning: files did NOT make it into the archive ({count}): {files} – the extension "
              "is not on the allowlist and the file lies outside a Ресурсы directory; on apply "
              "this shows up as \"Неизвестный ресурс\"",
    },
    "deploy.soap-without-description": {
        "ru": "внимание: у клиентов SOAP-сервиса нет файла описания ({count}): {files} – "
              "рядом с элементом должен лежать файл \"<Имя>.Wsdl.1\"; без него применение "
              "отказывает, а приложение молча откатывается",
        "en": "warning: SOAP service clients have no description file ({count}): {files} – a "
              "\"<Name>.Wsdl.1\" file has to lie next to the element; without it the apply "
              "fails and the application is silently rolled back",
    },
    "deploy.target": {
        "ru": "цель: приложение {app_id} ({app_source}), проект {project_id} ({project_source})",
        "en": "target: application {app_id} ({app_source}), project {project_id} ({project_source})",
    },
    "deploy.source-flag": {
        "ru": "указан флагом",
        "en": "given by a flag",
    },
    "deploy.source-env": {
        "ru": "из окружения/.env",
        "en": "from the environment/.env",
    },
    "deploy.uploaded": {
        "ru": "сборка загружена (id: {id})",
        "en": "build uploaded (id: {id})",
    },
    "deploy.version-not-kept": {
        "ru": "внимание: версию {version} сервер не сохранит – сборку, загруженную в проект, он "
              "нумерует сам: база – Версия проекта ({base}), номер – наибольший, какой он "
              "когда-либо выдавал в этой базе, плюс один. Суффикс архива до сервера не дойдет; "
              "сборку с запуском CI свяжут имя архива и коммит",
        "en": "warning: the server will not keep the version {version} – it numbers a build "
              "uploaded into a project itself: the base is the version of the project ({base}), "
              "the number is the highest it has ever given in that base plus one. The suffix of "
              "the archive does not reach the server; the name of the archive and the commit "
              "tie the build to its CI run",
    },
    "deploy.renumbered": {
        "ru": "внимание: сервер записал сборку как {given}, а не {built} из архива – сборку, "
              "загруженную в проект, он нумерует сам: база – Версия проекта, номер – "
              "наибольший, какой он когда-либо выдавал в этой базе, плюс один",
        "en": "warning: the server recorded the build as {given}, not as {built} from the "
              "archive – it numbers a build uploaded into a project itself: the base is the "
              "version of the project, the number is the highest it has ever given in that base "
              "plus one",
    },
    "deploy.renumbered-count": {
        "ru": "сервер записал сборку как {given}, а не {built} из архива: номер сборки, "
              "загруженной в проект, назначает сервер – наибольший, какой он когда-либо выдавал "
              "в этой базе, плюс один, а номер сборки, которую загружала не эта машина и "
              "которой в перечне уже нет, elemctl узнать неоткуда",
        "en": "the server recorded the build as {given}, not as {built} from the archive: the "
              "number of a build uploaded into a project is the server's – the highest it has "
              "ever given in that base plus one – and elemctl has no way to learn the number of "
              "a build another machine uploaded that is no longer listed",
    },
    "deploy.count-from-registry": {
        "ru": "номер сборки считается от {version} из локального реестра загрузок: в перечне "
              "проекта этой сборки уже нет, а номер удаленной сборки сервер повторно не выдает",
        "en": "the build number is counted on from {version} of the local registry of uploads: "
              "the project no longer lists that build, and the server does not give the number "
              "of a deleted build again",
    },
    "deploy.unknown": {
        "ru": "не определён",
        "en": "unknown",
    },
    "deploy.apply-started": {
        "ru": "применение запущено, ждём стабилизации приложения...",
        "en": "apply started, waiting for the application to stabilize...",
    },
    "deploy.running-verifying": {
        "ru": "приложение в статусе Running, проверяем фактическое применение...",
        "en": "application is Running, verifying the actual apply...",
    },
    "deploy.no-error-text": {
        "ru": "без текста ошибки",
        "en": "no error text",
    },
    "deploy.task": {
        "ru": "задача",
        "en": "task",
    },
    "deploy.task-failed": {
        "ru": "задача {label} завершилась со статусом {status}: {message}",
        "en": "task {label} finished with status {status}: {message}",
    },
    "deploy.assembly-mismatch": {
        "ru": "применённая сборка {applied} не совпадает с загруженной {expected} – "
              "похоже, платформа откатила применение",
        "en": "the applied build {applied} does not match the uploaded one {expected} – "
              "the platform seems to have rolled the apply back",
    },
    "deploy.version-mismatch": {
        "ru": "применённая версия {applied} не совпадает с загруженной {expected} – "
              "похоже, платформа откатила применение",
        "en": "the applied version {applied} does not match the uploaded one {expected} – "
              "the platform seems to have rolled the apply back",
    },
    "deploy.extension-mismatch": {
        "ru": "расширение {extension} работает на сборке {applied}, а не на загруженной "
              "{expected} – похоже, платформа откатила применение",
        "en": "the extension {extension} runs the build {applied}, not the uploaded one "
              "{expected} – the platform seems to have rolled the apply back",
    },
    "deploy.extension-missing": {
        "ru": "сборка {build} принадлежит расширению {extension} (проект {project}), а среди "
              "расширений приложения его нет – похоже, платформа откатила применение. "
              "Расширения приложения: {extensions}",
        "en": "the build {build} belongs to the extension {extension} (project {project}), and "
              "the application has no such extension – the platform seems to have rolled the "
              "apply back. Extensions of the application: {extensions}",
    },
    "deploy.extension-unverifiable": {
        "ru": "применение не проверить: сборка {build} принадлежит расширению {extension} "
              "(проект {project}), карточка приложения называет только сборку самого "
              "приложения, а перечень расширений есть лишь в Console API 2.1. {reason}",
        "en": "the apply cannot be verified: the build {build} belongs to the extension "
              "{extension} (project {project}), the card of the application names the build of "
              "the application alone, and the list of extensions exists in Console API 2.1 "
              "only. {reason}",
    },
    "deploy.extension-lookup-failed": {
        "ru": "не удалось узнать, не сборка ли {build} расширения: {error}. Вердикт вынесен по "
              "карточке приложения, а она называет только сборку самого приложения",
        "en": "could not find out whether {build} is a build of an extension: {error}. The "
              "verdict rests on the card of the application, which names the build of the "
              "application alone",
    },
    "deploy.extension-disabled": {
        "ru": "расширение {extension} применено, но выключено: приложение его не использует",
        "en": "the extension {extension} is applied but disabled: the application does not "
              "use it",
    },
    "deploy.extension-evidence": {
        "ru": "сборка принадлежит проекту расширения {project}: карточка приложения называет "
              "только сборку самого приложения, поэтому применение сверено по перечню его "
              "расширений (Console API 2.1)",
        "en": "the build belongs to the extension project {project}: the card of the application "
              "names the build of the application alone, so the apply was checked against the "
              "list of its extensions (Console API 2.1)",
    },
    "deploy.verify-passed": {
        "ru": "проверка пройдена: сборка применена",
        "en": "verification passed: the build is applied",
    },
    "deploy.problem": {
        "ru": "проблема: {problem}",
        "en": "problem: {problem}",
    },
    "deploy.verify-failed": {
        "ru": "проверка НЕ пройдена",
        "en": "verification FAILED",
    },
    # -- probe.py -----------------------------------------------------------------
    "probe.built": {
        "ru": "собран архив {file} (версия {version})",
        "en": "built archive {file} (version {version})",
    },
    "probe.uploaded": {
        "ru": "сборка загружена (id: {assembly}, проект: {project})",
        "en": "build uploaded (id: {assembly}, project: {project})",
    },
    "probe.project-renamed": {
        "ru": "внимание: сборка пробника легла в проект {project} с тем же Ид из Проект.yaml и "
              "переименовала его вместе с группой: было '{former}', стало '{name}'. Уборка "
              "пробника имя не вернет – его возвращает только загрузка сборки с прежним именем",
        "en": "warning: the probe build went into project {project}, the one that carries the "
              "Ид of its Проект.yaml, and renamed the project and its group from '{former}' to "
              "'{name}'. The cleanup of the probe does not bring the name back: only an upload "
              "of a build with the former name does",
    },
    "probe.unknown": {
        "ru": "не определён",
        "en": "unknown",
    },
    "probe.creating": {
        "ru": "создаём одноразовое приложение {name} – это и есть компиляция...",
        "en": "creating the throwaway application {name} – that is the compilation...",
    },
    "probe.compiled": {
        "ru": "компиляция пройдена",
        "en": "compilation passed",
    },
    "probe.failed": {
        "ru": "компиляция НЕ пройдена, сообщений: {count}",
        "en": "compilation FAILED, messages: {count}",
    },
    "probe.compatibility-refused": {
        "ru": "стенд НЕ знает режим совместимости {mode} (проект объявляет {project}) – "
              "он старше проекта, и проверять здесь нечего: остальные {dropped} сообщений "
              "производны от этого отказа и отброшены. Укажите стенд посвежее "
              "(--env-file с его .env)",
        "en": "the stand does NOT know the compatibility mode {mode} (the project declares "
              "{project}) – it is older than the project and there is nothing to check here: "
              "the remaining {dropped} messages follow from that refusal and were dropped. "
              "Point at a newer stand (--env-file with its .env)",
    },
    "probe.server-log-hint": {
        "ru": "сервер отказал, не назвав ошибок компиляции. Причину он пишет в свой журнал, "
              "файл server.log в каталоге logs экземпляра сервера: нужна последняя строка "
              "\"Caused by\", а строка \"SrcPath:\" рядом называет файл, на котором "
              "остановилось применение. Сервер в Docker: docker exec <контейнер> sh -c "
              "\"grep -n 'Caused by\\|SrcPath' <каталог-экземпляра>/logs/server.log | tail\"",
        "en": "the server refused without naming a compilation error. It writes the cause to "
              "its own log, the server.log file in the logs directory of the server instance: "
              "look for the last \"Caused by\" line, and the \"SrcPath:\" line next to it names "
              "the file the apply stopped at. For a server in Docker: docker exec <container> "
              "sh -c \"grep -n 'Caused by\\|SrcPath' <instance-dir>/logs/server.log | tail\"",
    },
    "probe.no-assembly-id": {
        "ru": "платформа не вернула ид сборки в ответе на загрузку – компилировать нечего",
        "en": "the platform returned no build id in the upload response – nothing to compile",
    },
    "probe.no-app-id": {
        "ru": "платформа не вернула ид приложения в ответе на создание",
        "en": "the platform returned no application id in the create response",
    },
    "probe.kept": {
        "ru": "уборка отключена (--keep): приложение {app}, сборка {version} остались на стенде",
        "en": "cleanup is off (--keep): the application {app} and the build {version} are left in place",
    },
    "probe.cleanup-command": {
        "ru": "убрать всё одной командой: {command}",
        "en": "to remove it all in one command: {command}",
    },
    "probe.cleanup-steps": {
        "ru": "или по шагам, в этом порядке: {steps}. Сборку удаляют только после того, как "
              "приложение исчезнет (apps get ответит 404 или статусом Deleted): пока оно живо, "
              "платформа отвечает на удаление сборки 500",
        "en": "or step by step, in this order: {steps}. The build is deleted only after the "
              "application is gone (apps get answers 404 or the Deleted status): while it is "
              "alive, the platform answers the deletion of the build with a 500",
    },
    "probe.cleanup-working-app": {
        "ru": "приложение {app} окружение называет рабочим (ELEMENT_APP_ID) – уборка пробника "
              "его не трогает. Если его действительно нужно удалить, это делает apps delete",
        "en": "the environment names the application {app} as the working one "
              "(ELEMENT_APP_ID) – a probe's cleanup does not touch it. If it really has to go, "
              "apps delete removes it",
    },
    "probe.cleanup-not-a-probe": {
        "ru": "приложение '{name}' ({app}) оставил не пробник: имя не начинается с {prefix}, "
              "сборка, на которой оно работает ({version}), не сборка пробника – в версии "
              "нет -probe-, и локальный реестр загрузок не помнит, чтобы его создал probe этой "
              "машины. --cleanup убирает только то, что оставил probe; прочие приложения "
              "удаляет apps delete",
        "en": "the application '{name}' ({app}) was not left by a probe: its name does not "
              "start with {prefix}, the build it runs ({version}) is not a probe build – the "
              "version carries no -probe-, and the local registry of uploads remembers no "
              "probe of this machine creating it. --cleanup removes only what probe left; "
              "other applications are deleted with apps delete",
    },
    "probe.cleanup-from-registry": {
        "ru": "ни имя, ни сборка приложения {app} пробника не выдают, но локальный реестр "
              "загрузок помнит, что его создал probe этой машины",
        "en": "neither the name nor the build of the application {app} says probe, but the "
              "local registry of uploads remembers a probe of this machine creating it",
    },
    "probe.cleanup-build-in-use": {
        "ru": "сборка {version} оставлена: на ней теперь работает приложение {app}",
        "en": "the build {version} is kept: the application {app} runs it now",
    },
    "probe.cleanup-app-already-deleted": {
        "ru": "приложение {app} уже удалено: платформа держит его в перечне со статусом Deleted",
        "en": "the application {app} is deleted already: the platform keeps it in the list "
              "under the Deleted status",
    },
    "probe.cleanup-deleting-app": {
        "ru": "удаляю приложение {name} ({app})...",
        "en": "deleting the application {name} ({app})...",
    },
    "probe.cleanup-app-still-there": {
        "ru": "приложение {app} не исчезло за отведённое время – сборки и проект не тронуты; "
              "повторите probe --cleanup {app} позже",
        "en": "the application {app} has not disappeared in time – the builds and the project "
              "are untouched; repeat probe --cleanup {app} later",
    },
    "probe.cleanup-app-not-deleted": {
        "ru": "приложение {app} удалить не удалось ({error}) – сборки и проект не тронуты",
        "en": "the application {app} could not be deleted ({error}) – the builds and the "
              "project are untouched",
    },
    "probe.cleanup-no-project": {
        "ru": "карточка приложения {app} не называет проект – искать сборку пробника негде",
        "en": "the card of the application {app} names no project – there is nowhere to look "
              "for the probe build",
    },
    "probe.cleanup-no-build": {
        "ru": "сборки пробника в проекте {project} уже нет: её убрала платформа или прошлая уборка",
        "en": "the probe build is no longer in the project {project}: the platform or an "
              "earlier cleanup removed it",
    },
    "probe.cleanup-build-deleted": {
        "ru": "удалена сборка {version} проекта {project}",
        "en": "deleted the build {version} of the project {project}",
    },
    "probe.cleanup-project-already": {
        "ru": "проект {project} уже удалён",
        "en": "the project {project} is deleted already",
    },
    "probe.cleanup-project-deleted": {
        "ru": "удалён проект {project}",
        "en": "deleted the project {project}",
    },
    "probe.cleanup-project-kept": {
        "ru": "проект {project} оставлен: {reason}",
        "en": "the project {project} is kept: {reason}",
    },
    "probe.cleanup-project-working": {
        "ru": "окружение называет его рабочим проектом (ELEMENT_PROJECT_ID)",
        "en": "the environment names it as the working project (ELEMENT_PROJECT_ID)",
    },
    "probe.cleanup-project-has-builds": {
        "ru": "в нём остались сборки: {builds}",
        "en": "builds are left in it: {builds}",
    },
    "probe.cleanup-project-in-use": {
        "ru": "на нём работают приложения: {apps}",
        "en": "applications run it: {apps}",
    },
    "probe.cleanup-flags": {
        "ru": "--cleanup убирает уже оставленный пробник и работает один: вместе с ним не "
              "задают {flags}",
        "en": "--cleanup removes a probe already left behind and works alone: {flags} are not "
              "given with it",
    },
    "probe.app-still-there": {
        "ru": "приложение {app} не исчезло за отведённое время – сборку и проект оставили",
        "en": "the application {app} has not disappeared in time – the build and the project are left",
    },
    "probe.assembly-kept": {
        "ru": "сборка {version} осталась в проекте {project}: пока живо приложение из неё, "
              "платформа удалить её не даёт",
        "en": "the build {version} is left in project {project}: the platform refuses to delete it "
              "while an application created from it is alive",
    },
    "probe.cleanup-problem": {
        "ru": "уборка: {problem}",
        "en": "cleanup: {problem}",
    },
    "probe.cleanup-refused": {
        "ru": "пробник {app} не убран: {error}",
        "en": "the probe {app} was not removed: {error}",
    },
    "probe.manifest-incomplete": {
        "ru": "{file}: сервер не примет этот пробник, поэтому он остановлен до сборки. {problems}",
        "en": "{file}: the server will not take this probe, so it stopped before the build. "
              "{problems}",
    },
    "probe.manifest-no-presentation": {
        "ru": "Нет Представление (Presentation): без него консоль отвечает на загрузку сборки "
              "500 \"Internal exception\" и причины не называет. Нужна строка \"{example}\".",
        "en": "There is no Представление (Presentation): without it the console answers the "
              "upload with a 500 \"Internal exception\" and names no cause. The line "
              "\"{example}\" is needed.",
    },
    "probe.manifest-no-development-language": {
        "ru": "Нет ЯзыкРазработки (DevelopmentLanguage): это обязательное свойство проекта, и без "
              "него приложение не создаётся. Нужна строка \"{example}\".",
        "en": "There is no ЯзыкРазработки (DevelopmentLanguage): it is a required property of "
              "the project, and no application is created without it. The line \"{example}\" "
              "is needed.",
    },
    "probe.manifest-no-localization-languages": {
        "ru": "ЯзыкПоУмолчанию (DefaultLanguage) задан без ЯзыкиЛокализации "
              "(LocalizationLanguages): такой проект сервер отклоняет, не называя причины. "
              "Нужна строка \"{example}\".",
        "en": "ЯзыкПоУмолчанию (DefaultLanguage) is set without ЯзыкиЛокализации "
              "(LocalizationLanguages): the server refuses such a project and names no cause. "
              "The line \"{example}\" is needed.",
    },
    # -- help: argparse help texts (cli.py) ---------------------------------------
    # CLI help strings. Key: cli.help.<command> or cli.help.<command>-<flag>.
    # Metavars that already read as English (NAME/APP_ID/FILE) are left untranslated.
    "cli.help.description": {
        "ru": "Управление приложениями платформы 1С:Предприятие.Элемент (Console API v2)",
        "en": "Manage 1C:Enterprise.Element platform applications (Console API v2)",
    },
    "cli.help.base-url": {
        "ru": "базовый URL платформы (ELEMENT_BASE_URL)",
        "en": "platform base URL (ELEMENT_BASE_URL)",
    },
    "cli.help.client-id": {
        "ru": "Client-Id для получения токена (ELEMENT_CLIENT_ID)",
        "en": "Client-Id for obtaining a token (ELEMENT_CLIENT_ID)",
    },
    "cli.help.client-secret": {
        "ru": "Client-Secret к этому Client-Id (ELEMENT_CLIENT_SECRET)",
        "en": "the Client-Secret for that Client-Id (ELEMENT_CLIENT_SECRET)",
    },
    # argparse always prints its own -h/--help in English (see i18n.ArgumentParser).
    "cli.help.group.positional": {
        "ru": "аргументы",
        "en": "positional arguments",
    },
    "cli.help.group.options": {
        "ru": "параметры",
        "en": "options",
    },
    "cli.help.help": {
        "ru": "показать эту справку и выйти",
        "en": "show this help message and exit",
    },
    "cli.help.version": {
        "ru": "показать версию и выйти",
        "en": "show the version and exit",
    },
    # -- identifier arguments shared by several commands --
    "cli.help.arg.app-id": {
        "ru": "ид приложения (по умолчанию ELEMENT_APP_ID)",
        "en": "the application id (default: ELEMENT_APP_ID)",
    },
    "cli.help.arg.app-id-required": {
        "ru": "ид приложения",
        "en": "the application id",
    },
    "cli.help.arg.app-ref": {
        "ru": "ид (UUID) либо точное имя приложения (по умолчанию ELEMENT_APP_ID)",
        "en": "the application id (UUID) or its exact name (default: ELEMENT_APP_ID)",
    },
    "cli.help.arg.app-ref-required": {
        "ru": "ид (UUID) либо точное имя приложения",
        "en": "the application id (UUID) or its exact name",
    },
    "cli.help.arg.app-ref-option": {
        "ru": "то же приложение ключом: deploy и apps ensure принимают только эту форму",
        "en": "the same application as an option: deploy and apps ensure take this form only",
    },
    "cli.app-ref-twice": {
        "ru": "приложение задано дважды и по-разному: позиционно \"{positional}\" и "
              "ключом --app-id \"{option}\" – оставьте одну форму",
        "en": "the application is given twice and differently: positionally \"{positional}\" and "
              "with --app-id \"{option}\" - keep one form",
    },
    "cli.key-repeated": {
        "ru": "ключ {key} принимает одно значение, а повторен с разными: \"{first}\" и "
              "\"{second}\" – оставьте одно",
        "en": "the key {key} takes one value, but it is repeated with different ones: "
              "\"{first}\" and \"{second}\" – keep one",
    },
    "cli.help.arg.project-id": {
        "ru": "ид проекта (по умолчанию ELEMENT_PROJECT_ID)",
        "en": "the project id (default: ELEMENT_PROJECT_ID)",
    },
    "cli.help.arg.project-id-required": {
        "ru": "ид проекта",
        "en": "the project id",
    },
    "cli.help.arg.app-name": {
        "ru": "имя приложения",
        "en": "the application name",
    },
    "cli.help.arg.assembly-version": {
        "ru": "версия сборки либо её ид",
        "en": "the assembly version or its id",
    },
    "cli.help.arg.assembly-file": {
        "ru": "файл сборки .xasm/.xlib",
        "en": "the .xasm/.xlib assembly file",
    },
    "cli.help.arg.space-id": {
        "ru": "пространство, в котором завести проект, когда --project-id не задан "
              "(по умолчанию ELEMENT_SPACE_ID)",
        "en": "the space to create the project in when --project-id is omitted "
              "(default: ELEMENT_SPACE_ID)",
    },
    "cli.help.arg.branch-id": {
        "ru": "ид ветки",
        "en": "the branch id",
    },
    "cli.help.arg.branch-name": {
        "ru": "имя ветки",
        "en": "the branch name",
    },
    "cli.help.arg.dump-id": {
        "ru": "ид дампа",
        "en": "the dump id",
    },
    "cli.help.arg.task-id": {
        "ru": "ид групповой задачи",
        "en": "the group task id",
    },
    "cli.help.arg.tech-version": {
        "ru": "версия технологии, на которую перевести приложение",
        "en": "the technology version to move the application to",
    },
    "cli.help.branches-list-name": {
        "ru": "фильтр по имени ветки",
        "en": "filter by branch name",
    },
    "cli.help.deploy-project-dir": {
        "ru": "каталог проекта (по умолчанию ищется вглубь от текущего)",
        "en": "the project directory (by default searched downward from the current one)",
    },
    "cli.help.env-file": {
        "ru": "путь к .env-файлу (по умолчанию .env в текущем каталоге)",
        "en": "path to the .env file (default: .env in the current directory)",
    },
    "cli.help.timeout": {
        "ru": "срок ожидания запроса в секундах (по умолчанию 60)",
        "en": "request timeout in seconds (default 60)",
    },
    "cli.help.lang": {
        "ru": "язык вывода (по умолчанию: env ELEMCTL_LANG / локаль системы / ru)",
        "en": "output language (default: env ELEMCTL_LANG / system locale / ru)",
    },
    "cli.help.json": {
        "ru": "машиночитаемый вывод: в stdout только JSON ответа, всё остальное "
              "(ход работы, предупреждения, ошибки) – в stderr",
        "en": "machine-readable output: stdout carries the JSON answer alone, "
              "everything else (progress, warnings, errors) goes to stderr",
    },
    "cli.help.quiet": {
        "ru": "не печатать ход работы: в stderr не идут ни строки прогресса, ни "
              "предупреждения, остаются ответ и отказ; форма ответа та же",
        "en": "print no progress: neither progress lines nor warnings go to stderr, the "
              "answer and a failure stay; the form of the answer is the same",
    },
    "cli.help.command-metavar": {
        "ru": "команда",
        "en": "command",
    },
    "cli.help.commands-title": {
        "ru": "команды",
        "en": "commands",
    },
    "cli.help.action-metavar": {
        "ru": "действие",
        "en": "action",
    },
    "cli.help.token": {
        "ru": "получить и напечатать токен",
        "en": "obtain and print a token",
    },
    "cli.help.apps": {
        "ru": "приложения",
        "en": "applications",
    },
    "cli.help.apps-list": {
        "ru": "список приложений",
        "en": "list applications",
    },
    "cli.help.apps-list-name": {
        "ru": "фильтр по подстроке имени без учёта регистра (выполняется на клиенте)",
        "en": "case-insensitive name substring filter (applied client-side)",
    },
    "cli.help.apps-list-status": {
        "ru": "отбор по статусу (Running, Stopped, Error, Deleted); "
              "несколько – через запятую или повтором ключа",
        "en": "filter by status (Running, Stopped, Error, Deleted); "
              "several of them separated by commas or by repeating the key",
    },
    "cli.help.apps-list-include-deleted": {
        "ru": "показывать и удалённые приложения (по умолчанию скрыты)",
        "en": "list deleted applications too (hidden by default)",
    },
    "cli.help.apps-list-brief": {
        "ru": "краткие карточки: ид, имя, статус, uri, применённая версия",
        "en": "brief cards: id, name, status, uri, applied version",
    },
    "cli.help.apps-get": {
        "ru": "карточка приложения; в applied-build – ветка и коммит применённой сборки (из "
              "карточки сборки или из локального реестра загрузок)",
        "en": "application details; applied-build carries the branch and the commit of the "
              "applied build (from the build card or from the local registry of uploads)",
    },
    "cli.help.apps-find": {
        "ru": "найти приложение по имени (точное совпадение без учёта регистра)",
        "en": "find an application by name (exact, case-insensitive match)",
    },
    "cli.help.apps-find-include-deleted": {
        "ru": "искать и среди удалённых приложений (по умолчанию пропускаются)",
        "en": "search deleted applications too (skipped by default)",
    },
    "cli.help.apps-create": {
        "ru": "создать приложение",
        "en": "create an application",
    },
    "cli.help.apps-ensure": {
        "ru": "создать приложение, если его ещё нет (идемпотентно)",
        "en": "create the application if it does not exist yet (idempotent)",
    },
    "cli.help.apps-apply": {
        "ru": "применить загруженную сборку к приложению и проверить, что она правда применилась",
        "en": "apply an uploaded assembly to an application and verify that it really landed",
    },
    "cli.help.apps-ensure-apply": {
        "ru": "если приложение уже есть – применить ему указанную сборку (иначе только сообщается,"
              " что сборка не применена)",
        "en": "when the application already exists, apply the given assembly to it (otherwise the"
              " answer only says that it was not applied)",
    },
    "cli.help.arg.version-id-required": {
        "ru": "ид загруженной сборки (project version id)",
        "en": "id of the uploaded assembly (the project version id)",
    },
    "cli.apply.started": {
        "ru": "применение сборки {version_id} запущено, ждём приложение",
        "en": "applying assembly {version_id} started, waiting for the application",
    },
    "cli.ensure.build-differs": {
        "ru": "приложение уже есть, и на нём сборка {applied}, а не {requested}:"
              " сборка НЕ применена. Примените её командой elemctl apps apply {app_id}"
              " {requested} либо повторите ensure с флагом --apply",
        "en": "the application already exists and runs assembly {applied} rather than"
              " {requested}: the assembly was NOT applied. Apply it with elemctl apps apply"
              " {app_id} {requested}, or repeat ensure with --apply",
    },
    "cli.ensure.build-already": {
        "ru": "приложение уже есть, и на нём та самая сборка {requested}",
        "en": "the application already exists and already runs assembly {requested}",
    },
    "cli.ensure.extension-already": {
        "ru": "приложение уже есть, и его расширение {extension} работает на той самой сборке "
              "{requested} (сверено по перечню расширений приложения, Console API 2.1)",
        "en": "the application already exists, and its extension {extension} already runs the "
              "build {requested} (checked against the list of its extensions, Console API 2.1)",
    },
    "cli.ensure.extension-differs": {
        "ru": "приложение уже есть, а его расширение {extension} работает на сборке {applied}, "
              "а не на {requested}: сборка НЕ применена. Примените ее командой elemctl apps "
              "apply {app_id} {requested} либо повторите ensure с флагом --apply",
        "en": "the application already exists, and its extension {extension} runs the build "
              "{applied} rather than {requested}: the build was NOT applied. Apply it with "
              "elemctl apps apply {app_id} {requested}, or repeat ensure with --apply",
    },
    "cli.ensure.extension-missing": {
        "ru": "приложение уже есть, а расширения {extension} (проект {project}) среди его "
              "расширений нет: сборка {requested} НЕ применена. Примените ее командой elemctl "
              "apps apply {app_id} {requested} либо повторите ensure с флагом --apply",
        "en": "the application already exists, and the extension {extension} (project "
              "{project}) is not among its extensions: the build {requested} was NOT applied. "
              "Apply it with elemctl apps apply {app_id} {requested}, or repeat ensure with "
              "--apply",
    },
    "cli.ensure.extension-unverifiable": {
        "ru": "приложение уже есть, а сборка {requested} принадлежит расширению {extension} "
              "(проект {project}): карточка приложения называет только сборку самого "
              "приложения, а перечень расширений есть лишь в Console API 2.1, которого у "
              "сервера нет. Применена ли сборка, не проверить; применить ее можно командой "
              "elemctl apps apply {app_id} {requested} либо флагом --apply",
        "en": "the application already exists, and the build {requested} belongs to the "
              "extension {extension} (project {project}): the card of the application names "
              "the build of the application alone, and the list of extensions exists in "
              "Console API 2.1 only, which the server lacks. Whether the build is applied "
              "cannot be checked; apply it with elemctl apps apply {app_id} {requested}, or "
              "with --apply",
    },
    "cli.help.apps-delete": {
        "ru": "удалить приложение (необратимо, URL меняется при пересоздании)",
        "en": "delete an application (irreversible; the URL changes on re-creation)",
    },
    "cli.help.apps-start": {
        "ru": "запустить приложение",
        "en": "start an application",
    },
    "cli.help.apps-stop": {
        "ru": "остановить приложение",
        "en": "stop an application",
    },
    "cli.help.apps-debug": {
        "ru": "данные для сессии отладки (debug-token, debug-address)",
        "en": "data for a debug session (debug-token, debug-address)",
    },
    "cli.help.apps-users": {
        "ru": "пользователи, подключённые к приложению: список, ид, представление, "
              "администратор ли и есть ли доступ по токену (логина платформа здесь не "
              "отдаёт)",
        "en": "the users connected to the application: the user list, the id, the "
              "presentation, whether an administrator and whether token access is on (the "
              "platform gives no login here)",
    },
    "cli.help.apps-token-access": {
        "ru": "доступ пользователя к HTTP-сервисам приложения по токену: показать или "
              "переключить (без него вызов сервиса токеном получает 500 \"Token access is "
              "denied\")",
        "en": "a user's access to the HTTP services of the application by a token: show or "
              "switch it (without it a call of a service with a token gets a 500 \"Token access "
              "is denied\")",
    },
    "cli.help.apps-token-access-user": {
        "ru": "логин, представление или ид пользователя (по умолчанию – учётная запись, под "
              "которой работает elemctl); ключ можно повторить: у каждого пользователя тогда своя "
              "запись в ответе, а сбой одного не останавливает остальных",
        "en": "the login, the presentation or the id of the user (default: the account elemctl "
              "signs in with); the key may be repeated: each user then gets an entry of its own "
              "in the answer, and a failure of one does not stop the rest",
    },
    "cli.help.apps-token-access-enable": {
        "ru": "разрешить доступ по токену и перечитать признак",
        "en": "allow the access by a token and read the flag back",
    },
    "cli.help.apps-token-access-disable": {
        "ru": "запретить доступ по токену и перечитать признак",
        "en": "forbid the access by a token and read the flag back",
    },
    "cli.help.apps-export": {
        "ru": "выгрузить в файл сборку, на которой работает приложение (расширения в нее не "
              "входят; их выгружает export-extension)",
        "en": "save the build the application runs to a file (the extensions are not in it; "
              "export-extension saves them)",
    },
    "cli.help.apps-export-output": {
        "ru": "файл или каталог для сборки; по умолчанию текущий каталог и имя из манифеста "
              "архива, \"<Имя> <Версия>.xasm\"",
        "en": "the file or the directory for the build; by default the current directory and "
              "the name after the manifest of the archive, \"<Name> <Version>.xasm\"",
    },
    "cli.help.apps-export-extension": {
        "ru": "выгрузить в файл сборку расширения, примененного в приложении (метод Console "
              "API 2.1; сервер без него получает понятный отказ)",
        "en": "save the build of an extension applied to the application to a file (a method "
              "of Console API 2.1; a server without it gets a plain refusal)",
    },
    "cli.help.arg.extension": {
        "ru": "расширение: ид расширения, ид его проекта, имя или представление проекта",
        "en": "the extension: the extension id, the id of its project, the name or the "
              "presentation of the project",
    },
    "cli.help.apps-export-extension-output": {
        "ru": "файл или каталог для сборки; по умолчанию текущий каталог и имя из манифеста "
              "архива, \"<Имя> <Версия>.xasm\"",
        "en": "the file or the directory for the build; by default the current directory and "
              "the name after the manifest of the archive, \"<Name> <Version>.xasm\"",
    },
    "cli.help.create-project-id": {
        "ru": "проект-источник; с --version-id по перечню его сборок команда проверяет, "
              "что платформа ещё не удалила сборку-источник (по умолчанию ELEMENT_PROJECT_ID)",
        "en": "source project; with --version-id its build list is checked for the source "
              "assembly, which the platform may have deleted (default: ELEMENT_PROJECT_ID)",
    },
    "cli.help.create-version-id": {
        "ru": "id сборки-источника; нового проекта ещё нет – заведите его "
              "'builds upload <файл>.xasm --space-id <id>' без --project-id",
        "en": "id of the source assembly; if the project does not exist yet, create it with "
              "'builds upload <file>.xasm --space-id <id>' without --project-id",
    },
    "cli.help.create-latest-build": {
        "ru": "источник – последняя сборка проекта",
        "en": "source: the project's latest assembly",
    },
    "cli.help.create-space-id": {
        "ru": "пространство",
        "en": "space",
    },
    "cli.help.create-tech-version": {
        "ru": "версия технологии",
        "en": "technology version",
    },
    "cli.help.create-no-dev-mode": {
        "ru": "не создавать среду разработки",
        "en": "do not create a development environment",
    },
    "cli.help.create-wait": {
        "ru": "дождаться готовности приложения (заодно проверяет, что стоит нужная сборка)",
        "en": "wait until the application is ready (and verify the assembly it runs)",
    },
    "cli.help.create-verify": {
        "ru": "проверить, что приложение правда работает на запрошенной сборке"
              " (подразумевает --wait); при неудаче код возврата 1",
        "en": "verify that the application really runs the requested assembly"
              " (implies --wait); exit code 1 when it does not",
    },
    "cli.help.create-no-verify": {
        "ru": "не проверять применённую сборку – только дождаться готовности",
        "en": "do not verify the applied assembly – only wait until ready",
    },
    "cli.help.spaces": {
        "ru": "пространства",
        "en": "spaces",
    },
    "cli.help.spaces-list": {
        "ru": "список пространств",
        "en": "list spaces",
    },
    "cli.help.projects": {
        "ru": "проекты",
        "en": "projects",
    },
    "cli.help.projects-list": {
        "ru": "список проектов",
        "en": "list projects",
    },
    "cli.help.projects-list-name": {
        "ru": "фильтр по подстроке имени без учёта регистра (выполняется на клиенте)",
        "en": "case-insensitive name substring filter (applied client-side)",
    },
    "cli.help.projects-list-include-deleted": {
        "ru": "показывать и удалённые проекты (по умолчанию скрыты)",
        "en": "list deleted projects too (hidden by default)",
    },
    "cli.help.projects-get": {
        "ru": "карточка проекта",
        "en": "project details",
    },
    "cli.help.projects-delete": {
        "ru": "удалить проект",
        "en": "delete a project",
    },
    "cli.help.builds": {
        "ru": "сборки проекта на платформе",
        "en": "project assemblies on the platform",
    },
    "cli.help.builds-list": {
        "ru": "список сборок проекта (свежие первыми)",
        "en": "list project assemblies (newest first)",
    },
    "cli.help.builds-list-limit": {
        "ru": "сколько сборок показать (по умолчанию 10; 0 – все)",
        "en": "how many assemblies to show (default 10; 0 – all)",
    },
    "cli.help.builds-list-brief": {
        "ru": "краткие карточки: ид, версии, дата, ветка, коммит; чего нет в карточке, берётся "
              "из локального реестра загрузок, и источник назван",
        "en": "brief cards: id, versions, date, branch, commit; what the card lacks comes from "
              "the local registry of uploads, and the source is named",
    },
    "cli.help.builds-get": {
        "ru": "карточка сборки по версии либо ид",
        "en": "assembly details by version or id",
    },
    "cli.help.builds-upload": {
        "ru": "загрузить файл сборки (.xasm/.xlib)",
        "en": "upload an assembly file (.xasm/.xlib)",
    },
    "cli.help.builds-upload-new-project": {
        "ru": "загрузить сборку без ид проекта, игнорируя ELEMENT_PROJECT_ID из "
              "окружения и .env-файла: сервер положит ее в проект с ее Ид из Проект.yaml "
              "либо заведет новый",
        "en": "upload the build without a project id, ignoring ELEMENT_PROJECT_ID from "
              "the environment and the .env file: the server puts it into the project of "
              "the Ид of its Проект.yaml or creates a new one",
    },
    "cli.help.builds-upload-force-rename": {
        "ru": "разрешить загрузку сборки с чужим именем: панель переименует "
              "проект-цель и его группу именем сборки",
        "en": "allow uploading an assembly whose name differs: the console renames "
              "the target project and its group after the assembly",
    },
    "cli.help.builds-upload-project-id": {
        "ru": "проект; без него платформа заводит новый проект, и это единственный "
              "способ создать проект через Console API",
        "en": "project; without it the platform creates a new project, which is the "
              "only way to create a project through the Console API",
    },
    "cli.help.builds-delete": {
        "ru": "удалить сборку по версии либо ид",
        "en": "delete an assembly by version or id",
    },
    "cli.help.verify-deploy": {
        "ru": "проверить, что сборка действительно применилась к приложению: задачи с "
              "ошибками (в них файл и позиция ошибки компиляции), сверка применённой "
              "сборки, доступность адреса; сама ничего не разворачивает",
        "en": "check that a build really landed on an application: tasks in an error "
              "status (they carry the file and position of a compilation error), the "
              "applied build compared with the expected one, the address answering; "
              "deploys nothing",
    },
    "cli.help.verify-version-id": {
        "ru": "ид загруженной сборки, которую ждем примененной – надежная сверка "
              "(строку версии сборки, загруженной в проект, сервер назначает сам); "
              "сборку расширения команда узнает сама и сверяет с расширениями приложения",
        "en": "id of the uploaded build expected to be applied – the reliable comparison "
              "(the server assigns the version string of a build uploaded into a project); "
              "a build of an extension is recognized and checked against the extensions of "
              "the application",
    },
    "cli.help.verify-expected-version": {
        "ru": "строка версии вместо ид сборки – запасная сверка",
        "en": "the version string instead of the build id – the fallback comparison",
    },
    "cli.help.verify-since-minutes": {
        "ru": "за сколько последних минут считать ошибки задач своими (по умолчанию 30)",
        "en": "how many last minutes of task failures count as ours (default 30)",
    },
    "cli.help.build": {
        "ru": "локально собрать архив сборки из исходников (к платформе не обращается: "
              "ключи подключения, включая --env-file, команда отвергает, номер версии на "
              "сервере не занимается)",
        "en": "build an assembly archive locally from sources (does not call the platform: "
              "the connection options, --env-file among them, are refused, and no version "
              "number is reserved on the server)",
    },
    "cli.help.build-project-dir": {
        "ru": "каталог проекта (по умолчанию ищется вглубь от текущего)",
        "en": "project directory (by default searched downward from the current one)",
    },
    "cli.help.build-output": {
        "ru": "каталог для архива (по умолчанию текущий)",
        "en": "directory for the archive (default: current)",
    },
    "cli.help.build-build-version": {
        "ru": "явная версия сборки, например 1.0-42",
        "en": "explicit assembly version, e.g. 1.0-42",
    },
    "cli.help.build-last-build": {
        "ru": "версия последней сборки проекта – для автоинкремента",
        "en": "the project's last assembly version – for auto-increment",
    },
    "cli.help.build-commit": {
        "ru": "хэш коммита в манифест (по умолчанию из git)",
        "en": "commit hash for the manifest (default: from git)",
    },
    "cli.help.build-branch": {
        "ru": "имя ветки в манифест (по умолчанию из git)",
        "en": "branch name for the manifest (default: from git)",
    },
    "cli.help.build-kind": {
        "ru": "вид проекта (по умолчанию из Проект.yaml/Project.yaml)",
        "en": "project kind (default: from Проект.yaml/Project.yaml)",
    },
    "cli.help.build-require-clean": {
        "ru": "прервать сборку, если в каталоге проекта есть незакоммиченные изменения",
        "en": "abort the build if the project directory has uncommitted changes",
    },
    "cli.help.inspect": {
        "ru": "разобрать готовый архив сборки (.xasm/.xlib); к платформе не обращается – "
              "ключи подключения, включая --env-file, команда отвергает",
        "en": "inspect a prebuilt assembly archive (.xasm/.xlib); does not call the platform "
              "– the connection options, --env-file among them, are refused",
    },
    "cli.help.inspect-file": {
        "ru": "файл архива сборки",
        "en": "assembly archive file",
    },
    "cli.help.deploy": {
        "ru": "полный цикл: сборка -> загрузка -> применение -> перезапуск -> проверка применения",
        "en": "full cycle: build -> upload -> apply -> restart -> verify the apply",
    },
    "cli.help.deploy-output": {
        "ru": "каталог для архива (по умолчанию временный)",
        "en": "directory for the archive (default: a temporary one)",
    },
    "cli.help.deploy-build-version": {
        "ru": "явная версия сборки",
        "en": "explicit assembly version",
    },
    "cli.help.deploy-branch": {
        "ru": "имя ветки в метаданные (по умолчанию из git)",
        "en": "branch name for the metadata (default: from git)",
    },
    "cli.help.deploy-commit": {
        "ru": "хэш коммита в метаданные (по умолчанию из git)",
        "en": "commit hash for the metadata (default: from git)",
    },
    "cli.help.deploy-dry-run": {
        "ru": "только сборка, без загрузки",
        "en": "build only, no upload",
    },
    "cli.help.deploy-require-clean": {
        "ru": "прервать развёртывание, если в каталоге проекта есть незакоммиченные изменения",
        "en": "abort the deploy if the project directory has uncommitted changes",
    },
    "cli.help.deploy-allow-data-loss": {
        "ru": "разрешить применение, которое пересоздаёт или удаляет данные (сужение длины, "
              "смена типа реквизита, в том числе в табличной части, снятие целиком справочника, "
              "документа или регистра, в том числе описанного заново с новым Ид); без флага "
              "такое развёртывание отклоняется до сборки. "
              "Снятие реквизита или табличной части флага не требует: деплой называет его и "
              "идёт дальше",
        "en": "allow an apply that recreates or deletes data (a narrowed length, a changed "
              "attribute type, a tabular part included, a catalog, a document or a register "
              "removed whole, described anew under a new Id included); without the flag such a "
              "deploy is refused before the build. A "
              "removed attribute or tabular part needs no flag: the deploy names it and goes on",
    },
    "cli.help.deploy-server-start-timeout": {
        "ru": "сколько секунд ждать сервер 1С:Элемент, пока он стартует и его консоль отвечает "
              "404 \"Application \"console\" not found\" (по умолчанию 900; 0 – не ждать)",
        "en": "how many seconds to wait for the 1C:Element server while it is starting and its "
              "console answers 404 \"Application \"console\" not found\" (default 900; 0 – do "
              "not wait)",
    },
    "cli.help.user-lists": {
        "ru": "списки пользователей и их настройки входа",
        "en": "user lists and their sign-in settings",
    },
    "cli.help.user-lists-list": {
        "ru": "список списков пользователей",
        "en": "list the user lists",
    },
    "cli.help.user-lists-list-name": {
        "ru": "фильтр по подстроке представления",
        "en": "filter by a presentation substring",
    },
    "cli.help.user-lists-get": {
        "ru": "карточка списка: регистрация, политика паролей, сервисы учётных записей",
        "en": "the list card: registration, password policy, account services",
    },
    "cli.help.user-lists-self-registration": {
        "ru": "самостоятельная регистрация пользователей: показать или переключить",
        "en": "self-registration of users: show or switch",
    },
    "cli.help.user-lists-password-login": {
        "ru": "вход по логину и паролю (сервис учётных записей Local): показать или переключить",
        "en": "signing in with a login and a password (the Local account service): show or switch",
    },
    "cli.help.user-lists-calculation-rules": {
        "ru": "правила разбора ответа сервиса учётных записей: показать цель или записать правила",
        "en": "the rules that parse the account service's answer: show the target or write them",
    },
    "cli.help.rules-file": {
        "ru": "файл JSON с правилами целиком",
        "en": "a JSON file with the whole set of rules",
    },
    "cli.help.rule-response-kind": {
        "ru": "вид ответа, который разбирается",
        "en": "the kind of answer being parsed",
    },
    "cli.help.rule-presentation": {
        "ru": "правило представления пользователя",
        "en": "the rule that builds the user's presentation",
    },
    "cli.help.rule-phone": {"ru": "правило телефона", "en": "the phone rule"},
    "cli.help.rule-email": {"ru": "правило почты", "en": "the email rule"},
    "cli.help.rules-service": {
        "ru": "сервис учётных записей: идентификатор (по умолчанию – первый сервис типа Oidc)",
        "en": "the account service by id (default: the first service of type Oidc)",
    },
    "cli.help.rules-service-type": {
        "ru": "тип сервиса учётных записей, если идентификатор не задан",
        "en": "the type of the account service when no id is given",
    },
    "cli.rules-file-not-object": {
        "ru": "файл правил должен содержать объект JSON вида {{\"response-kind\": ...}}",
        "en": "the rules file must hold a JSON object like {{\"response-kind\": ...}}",
    },
    "cli.rules-unknown-keys": {
        "ru": "платформа не примет ключи {keys}: она отвечает 400 на всё, кроме {known}",
        "en": "the platform will not accept the keys {keys}: it answers 400 to anything but {known}",
    },
    "cli.rules-no-service": {
        "ru": "в списке {list} нет сервиса учётных записей {service} – записывать правила некуда",
        "en": "list {list} has no {service} account service – there is nowhere to write the rules",
    },
    "cli.rules-not-returned": {
        "ru": "платформа не возвращает эти правила чтением сервиса – показать их нечем; "
              "команда умеет их только записывать",
        "en": "the platform does not return these rules when the service is read – there is "
              "nothing to show; the command can only write them",
    },
    "cli.rules-not-verified": {
        "ru": "правила отправлены и приняты, но подтвердить их значение через API нельзя: "
              "чтение сервиса их не возвращает. Проверено другое – остальная карточка сервиса "
              "после записи не изменилась",
        "en": "the rules were sent and accepted, but their value cannot be confirmed through "
              "the API: reading the service does not return them. What was checked instead – "
              "the rest of the service card is unchanged after the write",
    },
    "cli.rules-next": {
        "ru": "убедиться, что правила применились, можно панелью управления или живым входом",
        "en": "that the rules took effect is answered by the control panel or by a live sign-in",
    },
    "cli.help.user-lists-app": {
        "ru": "взять собственный список приложения (ид либо точное имя приложения)",
        "en": "take the application's own list (its id or exact name)",
    },
    "cli.help.arg.user-list": {
        "ru": "ид списка пользователей либо его точное представление",
        "en": "the user list id or its exact presentation",
    },
    "cli.help.user-lists-enable": {
        "ru": "включить",
        "en": "turn on",
    },
    "cli.help.user-lists-disable": {
        "ru": "выключить",
        "en": "turn off",
    },
    "cli.help.probe": {
        "ru": "изолированная проверка компиляции: сборка -> одноразовое приложение -> "
              "ошибки с файлом и позицией -> уборка; каталог проекта обязан лежать по "
              "схеме {{репозиторий}}/{{Поставщик}}/{{Имя}}/Проект.yaml, как этого требует "
              "сборка",
        "en": "isolated compilation check: build -> throwaway application -> errors with "
              "file and position -> cleanup; the project directory must follow the "
              "{{repository}}/{{Vendor}}/{{Name}}/Project.yaml layout a build requires",
    },
    "cli.help.probe-project-dir": {
        "ru": "каталог проекта – вида .../{{Поставщик}}/{{Имя}} с Проект.yaml внутри "
              "(по умолчанию ищется вглубь от текущего)",
        "en": "the project directory – .../{{Vendor}}/{{Name}} with Project.yaml inside "
              "(by default searched downward from the current one)",
    },
    "cli.help.probe-output": {
        "ru": "каталог для архива (по умолчанию временный)",
        "en": "directory for the archive (default: a temporary one)",
    },
    "cli.help.probe-build-version": {
        "ru": "явная версия сборки (по умолчанию {{база}}-probe-{{токен}} – она обязана быть новой)",
        "en": "explicit build version (default {{base}}-probe-{{token}} – it has to be a new one)",
    },
    "cli.help.probe-name": {
        "ru": "имя одноразового приложения (по умолчанию elemctl-probe-{{токен}})",
        "en": "name of the throwaway application (default elemctl-probe-{{token}})",
    },
    "cli.help.probe-space-id": {
        "ru": "пространство для проекта и приложения (ELEMENT_SPACE_ID)",
        "en": "the space for the project and the application (ELEMENT_SPACE_ID)",
    },
    "cli.help.probe-keep": {
        "ru": "не убирать за собой: оставить приложение и сборку для разбора руками; отчёт "
              "называет команду уборки",
        "en": "skip the cleanup: leave the application and the build for a hands-on look; the "
              "report names the command that removes them",
    },
    "cli.help.probe-cleanup": {
        "ru": "убрать оставленный пробник по его приложению (ид или имя): приложение, сборку "
              "пробника в его проекте и проект, если в нём больше ничего нет; пробник со "
              "своими именем и версией узнаётся по локальному реестру загрузок; чужое "
              "приложение команда не тронет. Ключ можно повторить: пробники убираются по "
              "очереди, у каждого свой отчет, и отказ одного не останавливает остальных",
        "en": "remove a probe left behind, starting from its application (id or name): the "
              "application, the probe build in its project and the project when nothing else "
              "is left in it; a probe with a name and a version of its own is known by the "
              "local registry of uploads; an application that is not a probe's is refused. "
              "The key may be repeated: the probes are removed in turn, each with a report of "
              "its own, and a refusal of one does not stop the rest",
    },
    "cli.help.probe-require-clean": {
        "ru": "прервать проверку, если в каталоге проекта есть незакоммиченные изменения",
        "en": "abort the check if the project directory has uncommitted changes",
    },
    "cli.help.branches": {
        "ru": "ветки среды разработки",
        "en": "development-environment branches",
    },
    "cli.help.branches-list": {
        "ru": "список веток",
        "en": "list branches",
    },
    "cli.help.branches-get": {
        "ru": "карточка ветки",
        "en": "branch details",
    },
    "cli.help.branches-create": {
        "ru": "создать ветку",
        "en": "create a branch",
    },
    "cli.help.branches-create-app-id": {
        "ru": "сразу привязать к приложению",
        "en": "bind to an application right away",
    },
    "cli.help.branches-update": {
        "ru": "изменить ветку (перепривязать к приложению)",
        "en": "update a branch (rebind to an application)",
    },
    "cli.help.branches-delete": {
        "ru": "удалить ветку",
        "en": "delete a branch",
    },
    "cli.help.branches-merge": {
        "ru": "принять изменения ветки",
        "en": "accept the branch's changes",
    },
    "cli.help.dumps": {
        "ru": "дампы приложений",
        "en": "application dumps",
    },
    "cli.help.dumps-create": {
        "ru": "создать дамп",
        "en": "create a dump",
    },
    "cli.help.dumps-create-description": {
        "ru": "описание дампа",
        "en": "dump description",
    },
    "cli.help.dumps-get": {
        "ru": "статус дампа",
        "en": "dump status",
    },
    "cli.help.tasks": {
        "ru": "задачи приложений (перечень – tasks list [--app-id ИД])",
        "en": "application tasks (the listing – tasks list [--app-id ID])",
    },
    "cli.help.tasks-forms": {
        "ru": "Задачи приложений. Формы: elemctl tasks list [--app-id ИД] – перечень задач; "
              "elemctl tasks get-group TASK_ID – статус групповой задачи. Ключ --app-id "
              "принадлежит действию list и ставится после него.",
        "en": "Application tasks. The forms: elemctl tasks list [--app-id ID] – the listing "
              "of tasks; elemctl tasks get-group TASK_ID – the status of a task group. The "
              "--app-id flag belongs to the list action and goes after it.",
    },
    "cli.action-first": {
        "ru": "подсказка: у группы \"{group}\" сначала действие, потом его ключи – "
              "например elemctl {group} {first} ... (действия: {actions})",
        "en": "hint: the action of the \"{group}\" group comes first and its flags after "
              "it – elemctl {group} {first} ..., say (actions: {actions})",
    },
    "cli.help.tasks-list": {
        "ru": "список задач приложений",
        "en": "list application tasks",
    },
    "cli.help.tasks-list-app-id": {
        "ru": "фильтр по приложению (на клиенте)",
        "en": "filter by application (client-side)",
    },
    "cli.help.tasks-get-group": {
        "ru": "статус групповой задачи",
        "en": "group task status",
    },
    "cli.help.tech": {
        "ru": "версия технологии",
        "en": "technology version",
    },
    "cli.help.tech-get": {
        "ru": "версия технологии приложения",
        "en": "the application's technology version",
    },
    "cli.help.tech-set": {
        "ru": "обновить версию технологии (групповая задача)",
        "en": "update the technology version (group task)",
    },
    "cli.help.debug-adapter": {
        "ru": "путь к debug-адаптеру платформы из плагина (для расширения VS Code)",
        "en": "path to the platform debug adapter from the plugin (for the VS Code extension)",
    },
    "cli.help.plugins": {
        "ru": "диагностика плагинов elemctl (точки расширения)",
        "en": "elemctl plugin diagnostics (extension points)",
    },
    "cli.help.self-update": {
        "ru": "обновить elemctl распаковкой колеса (безопасно, когда exe занят MCP-сервером)",
        "en": "update elemctl by unpacking the wheel (safe when the exe is held by the MCP server)",
    },
    "cli.help.self-update-version": {
        "ru": "целевая версия (по умолчанию – последняя с PyPI)",
        "en": "target version (default: the latest from PyPI)",
    },
    "cli.help.mcp": {
        "ru": "запустить MCP-сервер (транспорт stdio)",
        "en": "start the MCP server (stdio transport)",
    },
}


class MessageError(RuntimeError):
    pass


def register(messages: dict[str, dict[str, str]]) -> None:
    """Add messages to the catalog. Every key must carry every language of LANGS."""
    for key, per_lang in messages.items():
        missing = [lang for lang in LANGS if lang not in per_lang]
        if missing:
            raise MessageError(f"Message '{key}' has no translation for: {', '.join(missing)}")
        known = _catalog.get(key)
        if known is not None and known != per_lang:
            raise MessageError(f"Message '{key}' is already registered with a different wording")
        _catalog[key] = dict(per_lang)


def registered_keys() -> list[str]:
    return sorted(_catalog)


def translations(key: str) -> dict[str, str] | None:
    entry = _catalog.get(key)
    return dict(entry) if entry else None


def set_lang(lang: str | None) -> None:
    """Pin the output language for the process (CLI --lang). None restores the lookup order."""
    global _selected
    if lang is not None and lang not in LANGS:
        raise MessageError(f"Unknown language '{lang}'. Available: {', '.join(LANGS)}")
    _selected = lang


def lang_from_argv(argv) -> str | None:
    """Read --lang out of raw argv, before the parser is built.

    The parser is built with translated help=, but argparse learns --lang only when it parses -
    too late to choose the help language. So the value is scanned out of argv beforehand.
    Accepts "--lang en" and "--lang=en". A value outside LANGS returns None: the language stays
    at its default and argparse rejects the bad value with its own message. env / locale need no
    prescan - t() already reads them through current_lang() when the parser is built.
    """
    for i, arg in enumerate(argv):
        value = None
        if arg == "--lang" and i + 1 < len(argv):
            value = argv[i + 1]
        elif arg.startswith("--lang="):
            value = arg[len("--lang="):]
        if value is not None:
            return value if value in LANGS else None
    return None


def _system_lang() -> str | None:
    code = ""
    try:
        code = _locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        pass
    code = (code or os.environ.get("LC_ALL") or os.environ.get("LANG") or "").lower()
    # "ru_RU.UTF-8" and Windows' "Russian_Russia" both start with the language code.
    for lang in LANGS:
        if code.startswith(lang):
            return lang
    return None


def current_lang() -> str:
    if _selected is not None:
        return _selected
    env = os.environ.get(ENV_LANG, "").strip().lower()
    if env in LANGS:
        return env
    return _system_lang() or DEFAULT_LANG


def t(key: str, /, **fields) -> str:
    """Translate a key and substitute the fields. An unknown key is returned unchanged.

    A template is always run through str.format, so a literal brace must be doubled: `{{}}`.
    Formatting conditionally - only when fields are passed - would turn a literal brace into a
    field the day someone adds one, and the failure would surface as a crash at runtime.
    """
    entry = _catalog.get(key)
    if entry is None:
        return key
    template = entry.get(current_lang()) or entry[DEFAULT_LANG]
    return template.format(**fields)


class ArgumentParser(_argparse.ArgumentParser):
    """ArgumentParser with a localized `-h/--help`.

    argparse takes its own built-in strings from the gettext catalog, that is, always in
    English: in the Russian help of every command the `-h, --help` line stayed in a foreign
    language. Nested parsers inherit the class of their parent (`add_subparsers` passes
    `parser_class=type(self)`), so it is enough to create the root one with this class.
    """

    def __init__(self, *args, add_help: bool = True, **kwargs) -> None:
        super().__init__(*args, add_help=False, **kwargs)
        self._positionals.title = t("cli.help.group.positional")
        self._optionals.title = t("cli.help.group.options")
        if add_help:
            self.add_argument("-h", "--help", action="help", help=t("cli.help.help"))


register(MESSAGES)
