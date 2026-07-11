// XBSL Debug — тонкий адаптер отладки 1С:Предприятие.Элемент под обычный VS Code.
//
// Расширение не несёт debug-адаптер платформы (проприетарные jar-ы 1С): оно запускает штатный
// Java-адаптер `com.e1c.g5rt.debugger.adapter.App` из каталога, указанного в xbslDebug.adapterPath
// (извлекается из дистрибутива Элемента), и обращается с ним по DAP через stdio — ровно так же,
// как это делает среда разработки на Theia.
//
// Токен и адрес debug-сессии берутся у платформы через `elemctl apps debug` (Console API
// /actions/debug). Идентификатор сессии генерируется на стороне клиента и кладётся И в attach
// адаптеру, И в URL отлаживаемого приложения — сервер отладки сшивает их по нему.

import * as vscode from "vscode";
import { execFile } from "child_process";
import { randomUUID } from "crypto";
import * as path from "path";

const DEBUG_TYPE = "xbsl";
const ADAPTER_MAIN_CLASS = "com.e1c.g5rt.debugger.adapter.App";

interface DebugInfo {
  "debug-token": string;
  "debug-address": string;
  "client-debug-address": string;
}

function cfg() {
  return vscode.workspace.getConfiguration("xbslDebug");
}

// Запускает elemctl и возвращает распарсенный JSON stdout. cwd = рабочая папка (там .env).
function runElemctl(args: string[], cwd: string | undefined): Promise<any> {
  const bin = (cfg().get<string>("elemctlPath") || "elemctl").trim() || "elemctl";
  return new Promise((resolve, reject) => {
    execFile(bin, args, { cwd, maxBuffer: 8 * 1024 * 1024, windowsHide: true }, (err, stdout, stderr) => {
      if (err) {
        reject(new Error(`${bin} ${args.join(" ")}: ${stderr || err.message}`));
        return;
      }
      const text = (stdout || "").trim();
      try {
        resolve(text ? JSON.parse(text) : {});
      } catch {
        reject(new Error(`${bin} ${args.join(" ")}: вывод не JSON: ${text.slice(0, 200)}`));
      }
    });
  });
}

// Хост и порт из client-debug-address (wss://host:port) для параметров отлаживаемого приложения.
function hostPort(wssUrl: string): { host: string; port: string } {
  const u = new URL(wssUrl);
  return { host: u.hostname, port: u.port || (u.protocol === "wss:" ? "443" : "80") };
}

// Запускает штатный Java-адаптер как stdio DAP.
class XbslDebugAdapterFactory implements vscode.DebugAdapterDescriptorFactory {
  createDebugAdapterDescriptor(
    _session: vscode.DebugSession
  ): vscode.ProviderResult<vscode.DebugAdapterDescriptor> {
    const adapterPath = (cfg().get<string>("adapterPath") || "").trim();
    if (!adapterPath) {
      throw new Error(
        "Не задан xbslDebug.adapterPath — путь к каталогу debug-адаптера платформы " +
          "(папка с подкаталогом repo из дистрибутива Элемента)."
      );
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
      config.type = DEBUG_TYPE;
      config.request = "attach";
      config.name = "Отладка приложения 1С:Элемент";
    }
    const cwd = folder?.uri.fsPath ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

    try {
      const appArgs = config.appId ? [String(config.appId)] : [];
      const debugInfo: DebugInfo = await runElemctl(["apps", "debug", ...appArgs], cwd);
      if (!debugInfo["debug-address"] || !debugInfo["debug-token"]) {
        throw new Error(
          "elemctl apps debug не вернул debug-address/debug-token. " +
            "Проверьте, что отладка включена на сервере и elemctl поддерживает `apps debug`."
        );
      }
      const app = await runElemctl(["apps", "get", ...appArgs], cwd).catch(() => ({}));

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
        workspace: cwd,
        // Карта соответствия исходников; пустой объект = как в среде разработки (сервер
        // сопоставляет по путям setBreakpoints). Привязка к локальным .xbsl — точка доводки.
        projectLocations: {},
        locale: vscode.env.language?.startsWith("ru") ? "ru" : vscode.env.language || "ru",
        clientDebugAddress: debugInfo["client-debug-address"],
        application,
        authMode: config.authMode === "anonymous" || config.authMode === "another_user" ? config.authMode : undefined,
        retryTimeout: "60",
      });

      // URL отлаживаемого приложения открываем после старта сессии (см. onDidStartDebugSession).
      const appUrl: string | undefined = application.uri;
      if (cfg().get<boolean>("openApplicationOnStart", true) && appUrl && debugInfo["client-debug-address"]) {
        const { host, port } = hostPort(debugInfo["client-debug-address"]);
        const authModeParam = config.authMode ? `&auth-mode=${config.authMode}` : "";
        const sep = appUrl.includes("?") ? "&" : "?";
        pendingApp.set(
          sessionId,
          `${appUrl}${sep}debug-server-host=${host}&debug-server-port=${port}&debug-session-id=${sessionId}${authModeParam}`
        );
      }
      return config;
    } catch (e: any) {
      void vscode.window.showErrorMessage(`XBSL Debug: ${e?.message ?? e}`);
      return undefined;
    }
  }
}

// sessionId -> URL отлаживаемого приложения, открываемый при старте сессии.
const pendingApp = new Map<string, string>();

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.debug.registerDebugConfigurationProvider(DEBUG_TYPE, new XbslConfigurationProvider()),
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
