# XBSL Debug (1C:Element)

**English** · [Русский](https://github.com/keyfire/elemctl/blob/main/editors/vscode/README.ru.md)

Debug **1C:Enterprise.Element** (XBSL) applications in regular Visual Studio Code:
breakpoints, call stack (client and server frames in one chain), variable values,
stepping - without the Theia-based web IDE.

The extension is thin: it launches the **platform's own debug adapter** (Java, DAP
protocol) and obtains debug session coordinates via
[`elemctl`](https://github.com/keyfire/elemctl) (Console API `/actions/debug`). The
session id is generated on the client and ties together the adapter and the debuggee
application through the platform debug server.

## Quick start

1. Install prerequisites (see below), then run the command
   **"XBSL: Set up 1C:Element debugging"** from the Command Palette (`Ctrl+Shift+P`).
   The wizard checks Java, the adapter directory and elemctl, and offers to create
   `launch.json`.
2. Open the folder with your application sources (the repository root that contains
   `<Vendor>/<Name>/Project.yaml` and the `.env` file for elemctl).
3. Put a breakpoint in any `.xbsl` file.
4. Press **F5**. The application opens in the browser with debug parameters; execution
   stops on your breakpoint in VS Code.

## Prerequisites

1. **JDK 17+** (21 works too). Check: `java -version`.
2. **elemctl >= 0.5** (the `apps debug` and `debug-adapter` commands) with a configured
   `.env` (Console API credentials) in the sources root. If elemctl is missing, the
   extension offers to install it right from the error message and the setup wizard.
   Check: `elemctl apps debug` returns JSON with `debug-address`/`debug-token`.
3. **The platform debug adapter.** The easiest way is to install the elemctl plugin (the
   `elemctl-plugin` package), which ships the adapter: the extension then gets its path
   from `elemctl debug-adapter` automatically, with nothing to configure. Alternatively,
   extract the adapter from your 1C:Element distribution (the directory
   `.../@1c-appengine-plugin/bin/debugger`, which contains a `repo` subdirectory with the
   adapter's jar files) and set `xbslDebug.adapterPath`. The adapter consists of
   proprietary 1C components, so **it is not bundled** with the extension.
4. **Debugging enabled on the application server** (cloud stands usually have it
   enabled already).

## Settings

The setup wizard fills these for you; manual `settings.json` equivalent:

```jsonc
{
  // adapterPath can be left empty if the elemctl plugin (elemctl-plugin) is installed –
  // the extension gets the adapter path from "elemctl debug-adapter".
  "xbslDebug.adapterPath": "C:/path/to/@1c-appengine-plugin/bin/debugger",
  "xbslDebug.javaPath": "java",        // or a full path to java
  "xbslDebug.elemctlPath": "elemctl"   // or a full path to elemctl
}
```

`launch.json` is optional (F5 works without it). Full form:

```jsonc
{
  "version": "0.2.0",
  "configurations": [
    {
      "type": "xbsl",
      "request": "attach",
      "name": "Debug 1C:Element application"
      // "appId": "<app-id>",     // default: ELEMENT_APP_ID from .env
      // "envFile": "C:/work/.env", // default: .env of the sources root
      // "authMode": "anonymous", // sign-in mode of the debuggee
      // "workspace": "C:/src/my-repo" // sources root, normally auto-detected
    }
  ]
}
```

## How breakpoints bind to sources

The debug server identifies a module by its path **relative to the sources root**, in
the form `<Vendor>/<Name>/<path inside the project>.xbsl` (forward slashes). So the
sources must lie in a `<Vendor>/<Name>/` directory matching `Project.yaml`, and
`workspace` must point to the directory that contains it. The extension detects this
root automatically from the opened folder (it looks for `<Vendor>/<Name>/Project.yaml`
around it), so you can open the repository root or a subfolder. Override with the
`workspace` attribute in `launch.json` if needed.

## How it works

When you press F5, three pieces cooperate. VS Code talks DAP to a Java adapter over
stdio; the adapter talks to the platform's debug server over a WebSocket; the debuggee
(your application, opened in a browser) connects to the same debug server and is stitched
to your session by a shared `sessionId`.

![VS Code with this extension, the Java debug adapter and elemctl on the developer machine; the platform debug server and the Console API in the 1C:Element cloud; the browser with the debugged application joins the debug server by the same sessionId](https://raw.githubusercontent.com/keyfire/elemctl/main/editors/vscode/images/how-it-works.png)

Step by step:

1. `DebugConfigurationProvider` runs `elemctl apps debug` (Console API `/actions/debug`)
   to get `debug-address`, `debug-token` and `client-debug-address`, and `elemctl apps
   get` for the application card. elemctl reads the `ELEMENT_*` credentials and the app id
   from the `.env` in the sources root.
2. `DebugAdapterDescriptorFactory` takes the adapter directory (the `xbslDebug.adapterPath`
   setting, or `elemctl debug-adapter` from the plugin when it is empty) and starts
   `java ... -cp <adapterPath>/repo/*` (the adapter's main class) as a stdio DAP
   server and hands it the attach config (`uri=debug-address`, `debugToken`, a generated
   `sessionId`, `clientDebugAddress`, `workspace`, `projectLocations`, `application`,
   `locale`, `authMode`, `retryTimeout`).
3. On session start the extension opens the application in the browser at
   `<app-uri>?debug-server-host=...&debug-server-port=...&debug-session-id=<sessionId>`. The
   debug server matches the running application to your adapter by that `sessionId`.
4. The "XBSL Debug" output channel logs every elemctl call, the detected sources root and
   the debuggee URL.

## Which paths go where

Three settings tell the extension where the tools live. All are optional if the tools are
on `PATH`; set them to absolute paths otherwise. The setup wizard fills them for you.

| Setting | What to point it at | Example |
| --- | --- | --- |
| `xbslDebug.adapterPath` | Can be left empty if the elemctl plugin is installed (the adapter comes from `elemctl debug-adapter`). Otherwise the **debug adapter directory** extracted from your 1C:Element distribution – a folder that contains a `repo` subfolder with the adapter's jar files (in the distribution it is `.../@1c-appengine-plugin/bin/debugger`). | `C:/tools/xbsl-debug-adapter` (must contain `repo/...jar`) |
| `xbslDebug.javaPath` | The **Java 17+ launcher**. Leave as `java` if it is on `PATH`. | `C:/Program Files/Java/jdk-21/bin/java.exe` |
| `xbslDebug.elemctlPath` | The **elemctl executable** (>= 0.5). Leave as `elemctl` if it is on `PATH`. | `C:/Users/me/.local/bin/elemctl.exe` |
| `xbslDebug.fixVariablesFilter` | Work around the platform crash on filterless `variables` requests (see [Known limitations](#known-limitations)). Keep it on. | `true` (default) |

The `.env` with Console API credentials (`ELEMENT_BASE_URL`, `ELEMENT_CLIENT_ID`,
`ELEMENT_CLIENT_SECRET`, `ELEMENT_APP_ID`) lives in the **sources root**, not in a setting
– elemctl picks it up from there. Point at a different one with the `envFile` attribute in
`launch.json`.

## Status

Verified end-to-end against a cloud application: attach, breakpoints in client and
server modules, a mixed client+server call stack with local source paths, scopes and
variables, continue. Note: `stopOnEntry` pauses every thread of a live web application
(each server call), which is noisy - prefer breakpoints.

## Known limitations

- **Expanding a structure in the Variables tree on a client frame** used to hang the
  debuggee's client runtime and drop the session. The root cause is a platform bug: a DAP
  `variables` request WITHOUT the `filter` field (which is exactly what the VS Code
  Variables view sends for small values) crashes the debugged application's JS runtime,
  while a filtered request works fine. Since 0.3.0 the extension works around it
  automatically: a DAP middleware rewrites every filterless `variables` request into
  filtered ones (`named` + `indexed`, with the counts taken from the parent's response)
  and merges the results, so the whole value tree expands normally on both client and
  server frames. The workaround is controlled by the `xbslDebug.fixVariablesFilter`
  setting (on by default) - keep it on until the platform learns to handle
  `filter=NONE`.

## Deploy from VS Code

The companion [XBSL](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl)
extension adds the **XBSL: deploy the project (elemctl)** command (`xbsl.deploy`, also a
cloud button in the editor title of `.xbsl` files): it hands the project to `elemctl deploy`
- build from sources, upload, apply, restart and **verification that the apply actually took
effect**. On a failed apply the platform silently rolls the application back while still
reporting `Running`; elemctl does not trust the status and exits non-zero.

The exact command line is shown in a confirmation dialog, then runs as a terminal task, so
the progress and the final JSON report stay visible. The working directory is the workspace
folder: elemctl reads the connection and the target from its `.env` (`ELEMENT_BASE_URL`,
`ELEMENT_CLIENT_ID`/`SECRET`, `ELEMENT_APP_ID`, `ELEMENT_PROJECT_ID`).

| Setting | Default | Meaning |
| --- | --- | --- |
| `xbsl.deploy.elemctlPath` | `elemctl` | The elemctl executable for the deploy command. |
| `xbsl.deploy.envFile` | - | A `.env` with the connection and the target, passed as `--env-file` (relative to the workspace folder or absolute); handy in a git worktree whose `.env` lives in the main checkout. |
| `xbsl.deploy.appId` | - | Target application (`--app-id`); empty - `ELEMENT_APP_ID` from the environment / `.env`. |
| `xbsl.deploy.extraArgs` | - | Extra `elemctl deploy` arguments, space-separated. |

A set `xbsl.projectRoot` is passed as `--project-dir`; a missing elemctl is offered for
installation right from the error message.

## See also

The [XBSL](https://marketplace.visualstudio.com/items?itemName=keyfire.xbsl) extension
(the [xbsl-lint](https://github.com/keyfire/xbsl-lint) project) - syntax highlighting,
linting, a form preview, and a *deploy the project* button that runs `elemctl deploy`.
