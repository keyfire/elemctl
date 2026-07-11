# XBSL Debug (1C:Element)

Отладка приложений **1С:Предприятие.Элемент** (язык XBSL) в обычном Visual Studio Code —
точки останова, стек вызовов, значения переменных, шаги — без веб-среды разработки на Theia.

Расширение тонкое: оно запускает **штатный debug-адаптер платформы** (Java, протокол DAP) и
получает координаты debug-сессии через [`elemctl`](https://github.com/keyfire/elemctl)
(Console API `/actions/debug`). Идентификатор сессии генерируется на клиенте и связывает
адаптер и отлаживаемое приложение через сервер отладки платформы.

## Почему нужна настройка

Debug-адаптер платформы — это проприетарные Java-компоненты 1С, поэтому **они не входят в
расширение**. Возьмите их из своего дистрибутива 1С:Элемент (вы им лицензированы) и укажите путь.

## Требования

1. **JDK 17+** (подойдёт и 21). Проверка: `java -version`.
2. **elemctl** с командой `apps debug` и настроенным `.env` (реквизиты Console API) в рабочей
   папке проекта. Проверка: `elemctl apps debug` возвращает JSON с `debug-address`/`debug-token`.
3. **Debug-адаптер платформы** из дистрибутива — каталог `.../@1c-appengine-plugin/bin/debugger`
   (в нём подкаталог `repo` с jar-ами `com.e1c.g5rt.debugger.*`). Извлеките его на диск.
4. **Отладка включена на сервере** приложения (у облачных стендов — как правило, уже включена).

## Настройка

В `settings.json`:

```jsonc
{
  "xbslDebug.adapterPath": "C:/path/to/@1c-appengine-plugin/bin/debugger",
  "xbslDebug.javaPath": "java",        // или полный путь к java
  "xbslDebug.elemctlPath": "elemctl"   // или полный путь к elemctl
}
```

`.vscode/launch.json`:

```jsonc
{
  "version": "0.2.0",
  "configurations": [
    {
      "type": "xbsl",
      "request": "attach",
      "name": "Отладка приложения 1С:Элемент"
      // "appId": "<app-id>",        // по умолчанию — ELEMENT_APP_ID из .env
      // "authMode": "anonymous",    // режим входа отлаживаемого приложения
      // "projectLocations": ["${workspaceFolder}/e1c/site"]
    }
  ]
}
```

## Как пользоваться

1. Откройте папку проекта (с `.env` для elemctl) в VS Code.
2. Поставьте точки останова в `.xbsl`.
3. F5 → выберите конфигурацию «Отладка приложения 1С:Элемент».
4. Расширение получит координаты сессии через elemctl, запустит адаптер и откроет отлаживаемое
   приложение в браузере с параметрами debug-сессии. Дальше — обычная отладка VS Code.

## Как это устроено

- `DebugAdapterDescriptorFactory` запускает
  `java … -cp <adapterPath>/repo/* com.e1c.g5rt.debugger.adapter.App` как stdio-DAP-сервер.
- `DebugConfigurationProvider` зовёт `elemctl apps debug`, генерирует `sessionId`, собирает
  attach-конфиг (`uri=debug-address`, `debugToken`, `sessionId`, `clientDebugAddress`,
  `workspace`, `projectLocations`, `application`, `locale`, `authMode`, `retryTimeout`) и открывает
  приложение по `…?debug-server-host&debug-server-port&debug-session-id=<sessionId>`.

## Статус

Ранняя версия. Ядро (запуск адаптера, DAP, получение токена, оркестрация сессии) проверено;
поля сопоставления исходников (`workspace`/`projectLocations`/`application`) могут требовать
подгонки под конкретный проект для точной привязки точек останова.
