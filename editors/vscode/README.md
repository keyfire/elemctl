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
2. **elemctl >= 0.4** (the `apps debug` command) with a configured `.env` (Console API
   credentials) in the sources root. If elemctl is missing, the extension offers to
   install it right from the error message and the setup wizard. Check: `elemctl apps debug` returns JSON with
   `debug-address`/`debug-token`.
3. **The platform debug adapter** from your 1C:Element distribution: the directory
   `.../@1c-appengine-plugin/bin/debugger` (it contains a `repo` subdirectory with
   the adapter's jar files). Extract it to disk. The adapter consists of
   proprietary 1C components, so **it is not bundled** with the extension - you take it
   from the distribution you are licensed for.
4. **Debugging enabled on the application server** (cloud stands usually have it
   enabled already).

## Settings

The setup wizard fills these for you; manual `settings.json` equivalent:

```jsonc
{
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

```
   VS Code (this extension)                          1C:Element cloud
  ┌───────────────────────────┐
  │  editor, breakpoints,     │      DAP (stdio)   ┌────────────────────────┐
  │  Variables/Watch          │◄──────────────────►│  Java debug adapter     │
  │                           │                    │  from the platform      │
  │  ┌─────────────────────┐  │   spawns java -cp  │  distribution           │
  │  │ xbslDebug.adapterPath│─┼──► <adapterPath>/  └───────────┬────────────┘
  │  │ xbslDebug.javaPath   │ │      repo/*.jar                │ WebSocket
  │  │ xbslDebug.elemctlPath│ │                                │ (debug-address,
  │  └─────────────────────┘  │                                │  debug-token)
  └────────────┬──────────────┘                                ▼
               │ elemctl apps debug / apps get     ┌────────────────────────┐
               │ (Console API /actions/debug)      │  platform debug server  │
               ▼                                    └───────────┬────────────┘
        reads .env in the sources root                          │ same sessionId
        (ELEMENT_* credentials, app id)                         │
                                                                ▼
                                            browser: <app-uri>?debug-server-host=...
                                                     &debug-session-id=<sessionId>
                                            (the extension opens this URL on start)
```

Step by step:

1. `DebugConfigurationProvider` runs `elemctl apps debug` (Console API `/actions/debug`)
   to get `debug-address`, `debug-token` and `client-debug-address`, and `elemctl apps
   get` for the application card. elemctl reads the `ELEMENT_*` credentials and the app id
   from the `.env` in the sources root.
2. `DebugAdapterDescriptorFactory` starts
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
| `xbslDebug.adapterPath` | The **debug adapter directory** extracted from your 1C:Element distribution – a folder that contains a `repo` subfolder with the adapter's jar files. In the distribution it is `.../@1c-appengine-plugin/bin/debugger`. | `C:/tools/xbsl-debug-adapter` (must contain `repo/...jar`) |
| `xbslDebug.javaPath` | The **Java 17+ launcher**. Leave as `java` if it is on `PATH`. | `C:/Program Files/Java/jdk-21/bin/java.exe` |
| `xbslDebug.elemctlPath` | The **elemctl executable** (>= 0.4). Leave as `elemctl` if it is on `PATH`. | `C:/Users/me/.local/bin/elemctl.exe` |

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

- **Expanding a structure in the Variables tree on a client frame** does not respond and
  crashes the debuggee's client runtime, while the adapter survives. This is independent
  of the platform version (verified by matching the adapter and application versions - it
  still fails). Server frames expand to any depth, and the platform's own web IDE expands
  client-frame structures fine, so the issue is specific to debugging the application as a
  standalone browser tab through the external adapter. Workarounds on client frames: the
  value column already shows the whole serialized structure, and `evaluate` works - add a
  Watch expression for the field you need (e.g. `Данные.Возможности[0].Заголовок`). Server
  frames have no such limit.
