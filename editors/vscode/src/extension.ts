// XBSL Debug – тонкий адаптер отладки 1С:Предприятие.Элемент под обычный VS Code.
//
// Расширение не несёт debug-адаптер платформы (проприетарные jar-ы 1С): оно запускает штатный
// Java-адаптер `com.e1c.g5rt.debugger.adapter.App` из каталога, указанного в xbslDebug.adapterPath
// (извлекается из дистрибутива Элемента), и обращается с ним по DAP через stdio – ровно так же,
// как это делает среда разработки на Theia.
//
// Токен и адрес debug-сессии берутся у платформы через `elemctl apps debug` (Console API
// /actions/debug). Идентификатор сессии генерируется на стороне клиента и кладётся И в attach
// адаптеру, И в URL отлаживаемого приложения – сервер отладки сшивает их по нему.
//
// Привязка точек останова: идентификатор модуля = путь файла ОТНОСИТЕЛЬНО workspace с прямыми
// разделителями, в формате `<Поставщик>/<Имя>/<путь в проекте>.xbsl`. Поэтому workspace должен
// указывать на каталог, содержащий `<Поставщик>/<Имя>/Проект.yaml`; расширение находит его само
// (detectWorkspaceRoot), даже если в VS Code открыт подкаталог.

import * as vscode from "vscode";
import { execFile } from "child_process";
import { randomUUID } from "crypto";
import * as fs from "fs";
import * as path from "path";

const DEBUG_TYPE = "xbsl";
const ADAPTER_MAIN_CLASS = "com.e1c.g5rt.debugger.adapter.App";

const output = vscode.window.createOutputChannel("XBSL Debug");

interface DebugInfo {
  "debug-token": string;
  "debug-address": string;
  "client-debug-address": string;
}

function cfg() {
  return vscode.workspace.getConfiguration("xbslDebug");
}

function log(line: string): void {
  output.appendLine(`[${new Date().toLocaleTimeString()}] ${line}`);
}

// Запускает elemctl и возвращает распарсенный JSON stdout. cwd = корень исходников (там .env).
function runElemctl(args: string[], cwd: string | undefined): Promise<any> {
  const bin = (cfg().get<string>("elemctlPath") || "elemctl").trim() || "elemctl";
  log(`elemctl ${args.join(" ")} (cwd: ${cwd ?? "-"})`);
  return new Promise((resolve, reject) => {
    execFile(bin, args, { cwd, maxBuffer: 8 * 1024 * 1024, windowsHide: true }, (err, stdout, stderr) => {
      if (err) {
        const enoent = (err as NodeJS.ErrnoException).code === "ENOENT";
        const hint = enoent
          ? vscode.l10n.t("elemctl not found. Install it (pipx install elemctl) or set the path in the xbslDebug.elemctlPath setting.")
          : (stderr || err.message);
        reject(new Error(`${bin} ${args.join(" ")}: ${hint}`));
        return;
      }
      const text = (stdout || "").trim();
      try {
        resolve(text ? JSON.parse(text) : {});
      } catch {
        reject(new Error(`${bin} ${args.join(" ")}: ${vscode.l10n.t("output is not JSON")}: ${text.slice(0, 200)}`));
      }
    });
  });
}

// Хост и порт из client-debug-address (wss://host:port) для параметров отлаживаемого приложения.
function hostPort(wssUrl: string): { host: string; port: string } {
  const u = new URL(wssUrl);
  return { host: u.hostname, port: u.port || (u.protocol === "wss:" ? "443" : "80") };
}

function listSubdirs(dir: string, limit = 64): string[] {
  try {
    return fs
      .readdirSync(dir, { withFileTypes: true })
      .filter((e) => e.isDirectory() && !e.name.startsWith(".") && e.name !== "node_modules")
      .slice(0, limit)
      .map((e) => e.name);
  } catch {
    return [];
  }
}

// Если это Проект.yaml проекта, лежащего по схеме <корень>/<Поставщик>/<Имя>/Проект.yaml,
// возвращает <корень> – значение workspace, при котором идентификаторы модулей
// (`Поставщик/Имя/...` относительно workspace) совпадают с ожиданиями debug-сервера.
function rootFromProjectYaml(projectYaml: string): string | undefined {
  let text: string;
  try {
    text = fs.readFileSync(projectYaml, "utf8");
  } catch {
    return undefined;
  }
  const vendor = /^Поставщик:\s*["']?([\w.-]+)["']?\s*$/mu.exec(text)?.[1];
  const name = /^Имя:\s*["']?([\w.-]+)["']?\s*$/mu.exec(text)?.[1];
  if (!vendor || !name) {
    return undefined;
  }
  const projectDir = path.dirname(projectYaml);
  if (path.basename(projectDir) !== name || path.basename(path.dirname(projectDir)) !== vendor) {
    log(vscode.l10n.t("Project {0}: directories do not match the <root>/{1}/{2} layout – this Проект.yaml is skipped.", projectYaml, vendor, name));
    return undefined;
  }
  return path.dirname(path.dirname(projectDir));
}

// Ищет корень исходников: каталог, содержащий <Поставщик>/<Имя>/Проект.yaml. Смотрит саму
// открытую папку, две папки вверх (открыт подкаталог проекта) и до двух уровней вниз
// (открыт корень репозитория). Возвращает undefined, если проект не найден.
export function detectWorkspaceRoot(folder: string): string | undefined {
  const candidates: string[] = [
    path.join(folder, "Проект.yaml"),
    path.join(path.dirname(folder), "Проект.yaml"),
    path.join(path.dirname(path.dirname(folder)), "Проект.yaml"),
  ];
  for (const d1 of listSubdirs(folder)) {
    candidates.push(path.join(folder, d1, "Проект.yaml"));
    for (const d2 of listSubdirs(path.join(folder, d1))) {
      candidates.push(path.join(folder, d1, d2, "Проект.yaml"));
    }
  }
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      const root = rootFromProjectYaml(c);
      if (root) {
        return root;
      }
    }
  }
  return undefined;
}

function standardConfig(): vscode.DebugConfiguration {
  return {
    type: DEBUG_TYPE,
    request: "attach",
    name: vscode.l10n.t("Debug 1C:Element application"),
  };
}

// Запускает штатный Java-адаптер как stdio DAP.
class XbslDebugAdapterFactory implements vscode.DebugAdapterDescriptorFactory {
  createDebugAdapterDescriptor(
    _session: vscode.DebugSession
  ): vscode.ProviderResult<vscode.DebugAdapterDescriptor> {
    const adapterPath = (cfg().get<string>("adapterPath") || "").trim();
    if (!adapterPath) {
      void offerSetup(vscode.l10n.t("The platform debug adapter path is not set (xbslDebug.adapterPath)."));
      throw new Error(
        vscode.l10n.t("xbslDebug.adapterPath is not set – the platform debug adapter directory (a folder with the repo subdirectory from the Element distribution). The \"XBSL: Set up 1C:Element debugging\" command can help.")
      );
    }
    if (!isAdapterDir(adapterPath)) {
      void offerSetup(vscode.l10n.t("No adapter jars found in {0} (the repo subdirectory).", adapterPath));
      throw new Error(vscode.l10n.t("xbslDebug.adapterPath: {0} has no repo subdirectory with com.e1c.g5rt.debugger.* jars", adapterPath));
    }
    const java = (cfg().get<string>("javaPath") || "java").trim() || "java";
    const classpath = path.join(adapterPath, "repo", "*");
    const args = [
      "-Dfile.encoding=UTF-8",
      "--add-opens",
      "java.base/java.lang=ALL-UNNAMED",
      "--add-opens",
      "java.base/jdk.internal.misc=ALL-UNNAMED",
      "-cp",
      classpath,
      ADAPTER_MAIN_CLASS,
    ];
    log(`${java} -cp ${classpath} ${ADAPTER_MAIN_CLASS}`);
    return new vscode.DebugAdapterExecutable(java, args);
  }
}

// Дособирает attach-конфиг: тянет токен/адрес через elemctl, генерирует sessionId, добавляет
// поля, которые ждёт адаптер, и планирует открытие отлаживаемого приложения.
class XbslConfigurationProvider implements vscode.DebugConfigurationProvider {
  async resolveDebugConfiguration(
    folder: vscode.WorkspaceFolder | undefined,
    config: vscode.DebugConfiguration
  ): Promise<vscode.DebugConfiguration | undefined> {
    if (!config.type) {
      Object.assign(config, standardConfig());
    }
    const folderPath = folder?.uri.fsPath ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

    // Корень исходников: явный workspace из launch.json > авто-поиск > открытая папка.
    let root: string | undefined = typeof config.workspace === "string" && config.workspace ? config.workspace : undefined;
    if (!root && folderPath) {
      root = detectWorkspaceRoot(folderPath);
      if (root && path.resolve(root) !== path.resolve(folderPath)) {
        log(vscode.l10n.t("Sources root detected automatically: {0}", root));
      }
    }
    if (!root) {
      root = folderPath;
      void vscode.window.showWarningMessage(
        vscode.l10n.t("XBSL Debug: <Vendor>/<Name>/Проект.yaml not found – breakpoints may not bind. Open the repository root with the sources or set \"workspace\" in launch.json.")
      );
    }

    try {
      const globalArgs: string[] = [];
      if (typeof config.envFile === "string" && config.envFile) {
        globalArgs.push("--env-file", config.envFile);
      }
      const appArgs = config.appId ? [String(config.appId)] : [];
      const debugInfo: DebugInfo = await runElemctl([...globalArgs, "apps", "debug", ...appArgs], root);
      if (!debugInfo["debug-address"] || !debugInfo["debug-token"]) {
        throw new Error(
          vscode.l10n.t("elemctl apps debug returned no debug-address/debug-token. Check that debugging is enabled on the server and elemctl supports `apps debug`.")
        );
      }
      const app = await runElemctl([...globalArgs, "apps", "get", ...appArgs], root).catch(() => ({}));

      const sessionId = randomUUID();
      // Адаптер ждёт application в camelCase; карта elemctl отдаёт поля через дефис.
      const application = {
        id: app?.id,
        name: app?.name,
        error: app?.error ?? null,
        status: app?.status,
        displayName: app?.["display-name"] ?? app?.name,
        uri: app?.uri,
        spaceId: app?.["space-id"],
      };

      Object.assign(config, {
        request: "attach",
        stopOnEntry: config.stopOnEntry ?? false,
        endSessionIfClientDisconnected: true,
        clientApplicationPath: config.clientApplicationPath ?? "",
        noDebug: config.noDebug ?? false,
        debugToken: debugInfo["debug-token"],
        uri: debugInfo["debug-address"],
        sessionId,
        workspace: root,
        // Карта соответствия исходников для внешних библиотек; для модулей самого проекта
        // достаточно правильного workspace (идентификатор модуля = относительный путь).
        projectLocations: config.projectLocations ?? {},
        locale: vscode.env.language?.startsWith("ru") ? "ru" : vscode.env.language || "ru",
        clientDebugAddress: debugInfo["client-debug-address"],
        application,
        authMode: config.authMode === "anonymous" || config.authMode === "another_user" ? config.authMode : undefined,
        retryTimeout: "60",
      });

      // URL отлаживаемого приложения открываем после старта сессии (см. onDidStartDebugSession).
      const appUrl: string | undefined = application.uri;
      if (appUrl && debugInfo["client-debug-address"]) {
        const { host, port } = hostPort(debugInfo["client-debug-address"]);
        const authModeParam = config.authMode ? `&auth-mode=${config.authMode}` : "";
        const sep = appUrl.includes("?") ? "&" : "?";
        const debuggeeUrl = `${appUrl}${sep}debug-server-host=${host}&debug-server-port=${port}&debug-session-id=${sessionId}${authModeParam}`;
        log(vscode.l10n.t("Debuggee application URL: {0}", debuggeeUrl));
        if (cfg().get<boolean>("openApplicationOnStart", true)) {
          pendingApp.set(sessionId, debuggeeUrl);
        }
      }
      return config;
    } catch (e: any) {
      const msg = `XBSL Debug: ${e?.message ?? e}`;
      log(msg);
      void vscode.window.showErrorMessage(msg, vscode.l10n.t("Setup wizard")).then((a) => {
        if (a) {
          void vscode.commands.executeCommand("xbslDebug.setup");
        }
      });
      return undefined;
    }
  }
}

// sessionId -> URL отлаживаемого приложения, открываемый при старте сессии.
const pendingApp = new Map<string, string>();

function isAdapterDir(dir: string): boolean {
  try {
    return fs
      .readdirSync(path.join(dir, "repo"))
      .some((f) => /com\.e1c\.g5rt\.debugger\.adapter.*\.jar$/i.test(f));
  } catch {
    return false;
  }
}

function execOk(bin: string, args: string[], cwd?: string): Promise<{ ok: boolean; text: string }> {
  return new Promise((resolve) => {
    execFile(bin, args, { cwd, windowsHide: true, maxBuffer: 1024 * 1024 }, (err, stdout, stderr) => {
      resolve({ ok: !err, text: (stdout || "") + (stderr || "") + (err && !stdout && !stderr ? String(err.message) : "") });
    });
  });
}

async function offerSetup(reason: string): Promise<void> {
  const run = vscode.l10n.t("Setup wizard");
  const a = await vscode.window.showWarningMessage(`XBSL Debug: ${reason}`, run);
  if (a === run) {
    void vscode.commands.executeCommand("xbslDebug.setup");
  }
}

// Setup wizard: java -> адаптер -> elemctl (.env) -> launch.json. Каждый шаг чинится на
// месте; итог – сводка и подсказка "F5".
async function setupWizard(): Promise<void> {
  output.show(true);
  const results: string[] = [];
  const folderPath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  const root = folderPath ? detectWorkspaceRoot(folderPath) ?? folderPath : undefined;

  // 1. Java.
  let java = (cfg().get<string>("javaPath") || "java").trim() || "java";
  let j = await execOk(java, ["-version"]);
  if (!j.ok) {
    const pick = vscode.l10n.t("Locate java...");
    const a = await vscode.window.showWarningMessage(
      vscode.l10n.t("Java not found ({0}). The adapter needs Java 17+.", java),
      pick
    );
    if (a === pick) {
      const f = await vscode.window.showOpenDialog({ canSelectFiles: true, canSelectFolders: false, title: vscode.l10n.t("Java executable (java / java.exe)") });
      if (f?.[0]) {
        java = f[0].fsPath;
        await cfg().update("javaPath", java, vscode.ConfigurationTarget.Global);
        j = await execOk(java, ["-version"]);
      }
    }
  }
  results.push((j.ok ? "$(check) " : "$(error) ") + "Java: " + (j.ok ? j.text.split("\n")[0].trim() : vscode.l10n.t("not found")));

  // 2. Debug-адаптер платформы.
  let adapterPath = (cfg().get<string>("adapterPath") || "").trim();
  if (!adapterPath || !isAdapterDir(adapterPath)) {
    const pick = vscode.l10n.t("Choose the adapter folder...");
    const a = await vscode.window.showWarningMessage(
      vscode.l10n.t("The platform debug adapter directory is needed (a folder with a repo subdirectory holding com.e1c.g5rt.debugger.* jars). It is extracted from the 1C:Element distribution: data/ide/theia/plugins/@1c-appengine-plugin/bin/debugger."),
      pick
    );
    if (a === pick) {
      const f = await vscode.window.showOpenDialog({ canSelectFiles: false, canSelectFolders: true, title: vscode.l10n.t("Adapter directory (contains repo/)") });
      if (f?.[0]) {
        adapterPath = f[0].fsPath;
        if (isAdapterDir(adapterPath)) {
          await cfg().update("adapterPath", adapterPath, vscode.ConfigurationTarget.Global);
        } else {
          void vscode.window.showErrorMessage(vscode.l10n.t("No repo/ with adapter jars found in {0}.", adapterPath));
        }
      }
    }
  }
  const adapterOk = !!adapterPath && isAdapterDir(adapterPath);
  results.push((adapterOk ? "$(check) " : "$(error) ") + vscode.l10n.t("Adapter: {0}", adapterOk ? adapterPath : vscode.l10n.t("not configured")));

  // 3. elemctl и реквизиты Console API (.env в корне исходников).
  const elemctlBin = (cfg().get<string>("elemctlPath") || "elemctl").trim() || "elemctl";
  const e = await execOk(elemctlBin, ["apps", "get"], root);
  let appLine: string;
  if (e.ok) {
    try {
      const app = JSON.parse(e.text);
      appLine = vscode.l10n.t("Application: {0} ({1})", app["display-name"] ?? app.name ?? "?", app.uri ?? "");
    } catch {
      appLine = vscode.l10n.t("elemctl responds, but the output is not JSON");
    }
  } else {
    appLine = vscode.l10n.t("elemctl: {0}", e.text.trim().slice(0, 300) || vscode.l10n.t("not found (pipx install elemctl)"));
  }
  results.push((e.ok ? "$(check) " : "$(error) ") + appLine);
  if (!e.ok) {
    results.push("    " + vscode.l10n.t("Check: elemctl is installed and is version >= 0.4 (the apps debug command), and the sources root has a .env with ELEMENT_BASE_URL/CLIENT_ID/CLIENT_SECRET/APP_ID."));
  }

  // 4. launch.json.
  if (folderPath) {
    const launch = path.join(folderPath, ".vscode", "launch.json");
    if (!fs.existsSync(launch)) {
      const make = vscode.l10n.t("Create launch.json");
      const a = await vscode.window.showInformationMessage(
        vscode.l10n.t("Create .vscode/launch.json with a debug configuration? (Optional: F5 works without it.)"),
        make
      );
      if (a === make) {
        fs.mkdirSync(path.dirname(launch), { recursive: true });
        fs.writeFileSync(launch, JSON.stringify({ version: "0.2.0", configurations: [standardConfig()] }, null, 2), "utf8");
        results.push("$(check) " + vscode.l10n.t("Created {0}", launch));
      }
    }
  }

  for (const r of results) {
    log(r.replace(/\$\((check|error)\) /g, (m) => (m.includes("check") ? "[ok] " : "[X] ")));
  }
  const allOk = j.ok && adapterOk && e.ok;
  const summary = allOk
    ? vscode.l10n.t("All set. Open an .xbsl file, put a breakpoint and press F5 – the application opens in the browser and execution stops on your breakpoint.")
    : vscode.l10n.t("Setup is not complete – details are in the \"XBSL Debug\" output panel.");
  void (allOk ? vscode.window.showInformationMessage(summary) : vscode.window.showWarningMessage(summary));
}

export function activate(context: vscode.ExtensionContext): void {
  const provider = new XbslConfigurationProvider();
  context.subscriptions.push(
    output,
    vscode.commands.registerCommand("xbslDebug.setup", setupWizard),
    vscode.debug.registerDebugConfigurationProvider(DEBUG_TYPE, provider),
    vscode.debug.registerDebugConfigurationProvider(
      DEBUG_TYPE,
      {
        provideDebugConfigurations(): vscode.DebugConfiguration[] {
          return [standardConfig()];
        },
      },
      vscode.DebugConfigurationProviderTriggerKind.Dynamic
    ),
    vscode.debug.registerDebugAdapterDescriptorFactory(DEBUG_TYPE, new XbslDebugAdapterFactory()),
    vscode.debug.onDidStartDebugSession((session) => {
      if (session.type !== DEBUG_TYPE) {
        return;
      }
      const sid = session.configuration?.sessionId as string | undefined;
      const url = sid ? pendingApp.get(sid) : undefined;
      if (sid && url) {
        pendingApp.delete(sid);
        void vscode.env.openExternal(vscode.Uri.parse(url));
      }
    })
  );
}

export function deactivate(): void {
  pendingApp.clear();
}
