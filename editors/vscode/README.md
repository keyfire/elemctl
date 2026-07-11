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
   credentials) in the sources root. Check: `elemctl apps debug` returns JSON with
   `debug-address`/`debug-token`.
3. **The platform debug adapter** from your 1C:Element distribution: the directory
   `.../@1c-appengine-plugin/bin/debugger` (it contains a `repo` subdirectory with
   `com.e1c.g5rt.debugger.*` jars). Extract it to disk. The adapter consists of
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

- `DebugAdapterDescriptorFactory` starts
  `java ... -cp <adapterPath>/repo/* com.e1c.g5rt.debugger.adapter.App` as a stdio DAP
  server.
- `DebugConfigurationProvider` calls `elemctl apps debug`, generates a `sessionId`,
  assembles the attach configuration (`uri=debug-address`, `debugToken`, `sessionId`,
  `clientDebugAddress`, `workspace`, `projectLocations`, `application`, `locale`,
  `authMode`, `retryTimeout`) and opens the application at
  `...?debug-server-host&debug-server-port&debug-session-id=<sessionId>`.
- The "XBSL Debug" output channel logs elemctl calls, the detected sources root and the
  debuggee URL.

## Status

Verified end-to-end against a cloud application: attach, breakpoints in client and
server modules, a mixed client+server call stack with local source paths, scopes and
variables, continue. Note: `stopOnEntry` pauses every thread of a live web application
(each server call), which is noisy - prefer breakpoints.

## Known limitations

- **Expanding a structure in the Variables tree on a client frame** may crash the
  debuggee's client runtime with an internal platform error (observed with a 9.2.8
  adapter against a 9.2.7 runtime; the adapter itself survives). Server frames expand
  fine to any depth. Workarounds on client frames: the value column already shows the
  whole serialized structure, and `evaluate` works - add a Watch expression for the
  field you need (e.g. `Данные.Возможности[0].Заголовок`).
