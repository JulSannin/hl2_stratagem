# HD2 Stratagem LAN API — 0.20.0

PIN-авторизация отключена. HTTP endpoints и WebSocket доступны без токена для использования в доверенной локальной сети.

## HTTP
- `GET /` — минимальный React-интерфейс: физическая раскладка Numpad и шестерёнка настроек.
- `GET /api/status` — состояние сервера, игры, hook и назначения клавиш.
- `GET /api/stratagems` — каталог стратагем с категориями, кодами и URL игровых иконок.
- `GET /api/icons/{icon_id}` — SVG-иконка; загружается при первом запросе и кешируется локально.
- `GET /api/config` — текущие назначения и настройки макросов; ответ включает монотонный `revision`.
- `PUT /api/config` — сохранить назначения и настройки. Поле `revision` обязательно: сервер отклоняет устаревшую конфигурацию ответом HTTP 409 с актуальным снимком в `detail.config`.
- `POST /api/macro/{binding_id}` — запустить макрос для назначения.
- `GET /api/macro/status` — состояние движка макросов.

## WebSocket
- `WS /ws/keys` — события физического Numpad от Windows low-level keyboard hook; авторизация не требуется.
- При соединении сервер отправляет `ready` с полным актуальным `config` (включая `revision`) и снимком состояния `status`.
- При нажатии назначенной клавиши в игре сервер отправляет `{"type":"key_down","binding_id":"numpad_7","at":123.45}`.
- При отпускании отправляет `{"type":"key_up","binding_id":"numpad_7","at":123.56}`.
- Браузер анимирует соответствующую виртуальную клавишу и отправляет ping каждые 20 секунд.
- После сохранения конфигурации всем соединённым вкладкам рассылается `config_updated` с полной конфигурацией и номером `revision`.
- Если изменились параметры управления/скорости, дополнительно отправляется `settings_updated`.
- Синхронизируются только серверные данные. Состояние локального UI (открытый попап, поиск и текущая категория) остаётся независимым в каждой вкладке.
- Клиент передаёт ожидаемый `revision`. При одновременном редактировании устаревшее сохранение получает HTTP 409; актуальный клиент автоматически объединяет независимые изменения и повторяет сохранение один раз.

## Назначения
Основные: `numpad_0` ... `numpad_9`.
Дополнительные: `numpad_decimal`, `numpad_subtract`, `numpad_add`, `numpad_multiply`, `numpad_divide`.
Numpad Enter не перехватывается.

Безопасность: сервис предназначен только для доверенной локальной сети. Не публикуй порт 8765 в интернете и не отключай брандмауэр Windows.

## UI поведения 0.17.0
- Категории в окне назначения расположены адаптивной сеткой без горизонтальной полосы прокрутки.
- Выбранные стратагемы показаны в полосе их оригинальных иконок; в каталоге они выделяются рамкой и отметкой.
- При открытии назначения для уже занятой клавиши выбирается категория текущей стратагемы.
- Подсказка с названием стратагемы появляется при наведении примерно через одну секунду.
- Шестерёнка открывает отдельное адаптивное модальное окно настроек; прокручивается содержимое диалога.


## UI 0.16.0
- Settings dialog: close icon only, no title block or cancel button.
- Direction controls show arrow glyphs without direction words.
- Stratagem tooltip label is positioned above the icon.

- При наведении на назначенную клавишу Numpad через 1 секунду появляется подсказка над клавишей с названием стратагемы и стрелочным кодом.
- Коды сверены 30.10.2026 с текущей опубликованной базой Divers Hub; см. DATA_AUDIT_2026-10-30.md.


## Multi-client sync 0.20.0
Edge в Xbox Game Bar, Chrome и любые другие открытые клиенты подключаются к одному `/ws/keys`. Сервер является единственным источником состояния. Все вкладки получают обновления назначений и настроек без перезагрузки; физические нажатия продолжат транслироваться через тот же канал. Для гарантии порядка изменений используется персистентный номер ревизии `_revision` в `%APPDATA%\HD2StratagemLAN\config.json`.



## Review / reliability 0.20.0
- WebSocket accepts same-origin browser connections; cross-origin `Origin` values are rejected with policy close.
- Broadcasts are serialized to avoid concurrent sends to the same socket. Fan-out to connected tabs is concurrent.
- A macro uses a settings snapshot captured at trigger time, so remote edits cannot change an in-progress sequence.
- Failed config persistence rolls back the in-memory config and revision.
- Windows key-repeat `keydown` messages are swallowed while a mapped Numpad key is held; only the initial press starts a macro.


## Local request guard 0.20.0
- HTTP Host is accepted only for loopback/private LAN IPs, the local machine hostname, or `.local` mDNS names.
- Browser Origin on mutating HTTP methods must match Host. WebSocket Origin must match Host and Host must be local.
- This reduces accidental exposure and browser-based DNS-rebinding/CSRF paths; it is not user authentication. Treat the server as trusted-LAN-only and do not port-forward it.
