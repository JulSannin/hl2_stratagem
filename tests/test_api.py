import copy
import json
import pytest

from fastapi.testclient import TestClient

import app as server


def open_client(monkeypatch):
    monkeypatch.setattr(server, "CONFIG", copy.deepcopy(server.CONFIG))
    monkeypatch.setattr(server, "CONFIG_REVISION", 1)
    monkeypatch.setattr(server, "write_config", lambda _config: None)
    return TestClient(server.app)


def test_catalog_and_static_react_assets():
    client = TestClient(server.app)
    homepage = client.get("/")
    assert homepage.status_code == 200
    assert 'id="root"' in homepage.text
    assert "/assets/app.js" in homepage.text
    assert "/assets/components/NumPad.js" in homepage.text
    assert "/assets/components/StratagemPicker.js" in homepage.text
    assert "/assets/css/numpad.css" in homepage.text
    assert client.get("/assets/react.production.min.js").status_code == 200
    assert client.get("/assets/react-dom.production.min.js").status_code == 200
    for asset in [
        "/assets/app.js", "/assets/components/NumPad.js",
        "/assets/components/StratagemPicker.js", "/assets/components/SettingsDialog.js",
        "/assets/components/Toast.js",
        "/assets/css/core.css", "/assets/css/numpad.css",
        "/assets/css/picker.css", "/assets/css/dialogs.css"
    ]:
        response = client.get(asset)
        assert response.status_code == 200, asset
    app_js = client.get("/assets/app.js").text
    css = client.get("/assets/css/numpad.css").text
    assert "UI.NumPad" in app_js
    assert "UI.StratagemPicker" in app_js
    assert "renderAssignments" not in app_js
    assert "Активные макросы" not in app_js
    assert "СОСТОЯНИЕ МАКРОСОВ" not in app_js
    assert "Как пользоваться" not in app_js
    assert "numpad_decimal" in app_js
    assert "numpad_10" not in app_js
    assert ".numpad-grid" in css
    assert "aspect-ratio: 4 / 5" in css
    assert "100dvh" in css
    catalog = client.get("/api/stratagems").json()
    assert len(catalog["items"]) == 111
    assert all("icon_url" in item and item["icon_url"].startswith("/api/icons/") for item in catalog["items"])


def test_physical_keypad_geometry_and_componentized_responsive_styles():
    client = TestClient(server.app)
    numpad_js = client.get("/assets/components/NumPad.js").text
    picker_js = client.get("/assets/components/StratagemPicker.js").text
    numpad_css = client.get("/assets/css/numpad.css").text
    picker_css = client.get("/assets/css/picker.css").text
    # Physical Numpad: empty Num Lock and Enter positions, operator row, tall plus, wide zero.
    assert "numpad_divide: [2, 1]" in numpad_js
    assert "numpad_multiply: [3, 1]" in numpad_js
    assert "numpad_subtract: [4, 1]" in numpad_js
    assert "numpad_add: [4, '2 / span 3']" in numpad_js
    assert "numpad_0: ['1 / span 2', 5]" in numpad_js
    assert "numpad_decimal: [3, 5]" in numpad_js
    assert "numpad_enter" not in numpad_js and "Num Lock" not in numpad_js
    assert "numpad-heading" not in numpad_js
    assert "settings-gear" in numpad_js
    assert "каталог" not in picker_js.lower() or "Типы стратагем" in picker_js
    assert ".numpad-grid" in numpad_css and "aspect-ratio: 4 / 5" in numpad_css
    assert "@media (max-height: 500px)" in numpad_css
    assert ".console-layout" in numpad_css
    assert "grid-template-columns: repeat(auto-fit" in picker_css
    assert "overflow-x: auto" not in picker_css
    assert "picker-icon-grid" in picker_css
    assert "picker-icon-tile" in picker_css
    assert "position: fixed" in picker_css
    assert "filter: none !important" in picker_css

def test_exactly_ten_digit_and_five_operator_bindings():
    keys = server.BINDING_KEYS
    assert len(keys) == 15
    assert [k["id"] for k in keys if k["group"] == "main"] == [f"numpad_{i}" for i in range(10)]
    assert [k["id"] for k in keys if k["group"] == "extra"] == [
        "numpad_decimal", "numpad_subtract", "numpad_add", "numpad_multiply", "numpad_divide"
    ]
    assert "numpad_10" not in server.BINDING_BY_ID


def test_config_is_open_without_pin_and_persists(monkeypatch):
    client = open_client(monkeypatch)
    assert client.post("/api/auth", json={"pin": "123456"}).status_code == 404
    config = client.get("/api/config").json()
    assert set(config["bindings"]) == server.BINDING_IDS
    config["bindings"]["numpad_0"] = server.CATALOG[0]["name"]
    config["bindings"]["numpad_decimal"] = server.CATALOG[1]["name"]
    saved = client.put("/api/config", json=config)
    assert saved.status_code == 200
    assert saved.json()["config"]["bindings"]["numpad_0"] == server.CATALOG[0]["name"]
    assert saved.json()["config"]["bindings"]["numpad_decimal"] == server.CATALOG[1]["name"]
    latest = client.get("/api/config").json()
    invalid = copy.deepcopy(latest)
    invalid["bindings"].pop("numpad_divide")
    assert client.put("/api/config", json=invalid).status_code == 422
    invalid = copy.deepcopy(latest)
    invalid["bindings"]["numpad_add"] = "нет такой стратагемы"
    assert client.put("/api/config", json=invalid).status_code == 422


def test_old_four_slot_config_migrates_to_digit_bindings(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    legacy = {
        "slots": [server.CATALOG[0]["name"], None, server.CATALOG[2]["name"], None],
        "open_key": "CTRL",
        "direction_keys": {"U": "UP", "D": "DOWN", "L": "LEFT", "R": "RIGHT"},
        "press_ms": 65, "gap_ms": 65, "open_hold_ms": 100, "pin": "123456"
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    monkeypatch.setattr(server, "CONFIG_PATH", path)
    migrated = server.read_config()
    assert migrated["bindings"]["numpad_1"] == server.CATALOG[0]["name"]
    assert migrated["bindings"]["numpad_3"] == server.CATALOG[2]["name"]
    assert migrated["bindings"]["numpad_0"] is None
    assert len(migrated["bindings"]) == 15
    saved_again = json.loads(path.read_text(encoding="utf-8"))
    assert "pin" not in saved_again


def test_previous_fifteen_plus_enter_config_migrates_without_enter(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    legacy_bindings = {key_id: None for key_id in server.BINDING_IDS}
    legacy_bindings["numpad_10"] = server.CATALOG[1]["name"]
    legacy_bindings["numpad_decimal"] = server.CATALOG[0]["name"]
    path.write_text(json.dumps({"bindings": legacy_bindings, "pin": "123456"}), encoding="utf-8")
    monkeypatch.setattr(server, "CONFIG_PATH", path)
    migrated = server.read_config()
    assert len(migrated["bindings"]) == 15
    assert "numpad_10" not in migrated["bindings"]
    assert migrated["bindings"]["numpad_decimal"] == server.CATALOG[0]["name"]


def test_hook_maps_only_requested_fifteen_keys():
    hook = server.GlobalNumpadHook(server.MACROS)
    class Info:
        def __init__(self, vk, scan=0, flags=0):
            self.vkCode, self.scanCode, self.flags = vk, scan, flags
    for digit in range(10):
        assert hook._binding_from_event(Info(0x60 + digit)) == f"numpad_{digit}"
    assert hook._binding_from_event(Info(0x6E)) == "numpad_decimal"
    assert hook._binding_from_event(Info(0x6D)) == "numpad_subtract"
    assert hook._binding_from_event(Info(0x6B)) == "numpad_add"
    assert hook._binding_from_event(Info(0x6A)) == "numpad_multiply"
    assert hook._binding_from_event(Info(0x6F)) == "numpad_divide"
    assert hook._binding_from_event(Info(0x0D, scan=0x1C, flags=1)) is None


def test_default_and_mission_groups_are_preserved():
    groups = {}
    for item in server.CATALOG:
        groups[item["category"]] = groups.get(item["category"], 0) + 1
    assert groups["По умолчанию"] == 3
    assert groups["Стратагемы заданий"] == 15
    assert len(server.ICON_MAP) == 111
    assert all(item["name"] in server.ICON_MAP for item in server.CATALOG)


def test_arrow_key_config_is_accepted(monkeypatch):
    client = open_client(monkeypatch)
    config = client.get("/api/config").json()
    config["direction_keys"] = {"U": "UP", "D": "DOWN", "L": "LEFT", "R": "RIGHT"}
    saved = client.put("/api/config", json=config)
    assert saved.status_code == 200
    assert saved.json()["config"]["direction_keys"] == config["direction_keys"]


def test_macro_rejects_unknown_binding_without_auth(monkeypatch):
    client = open_client(monkeypatch)
    response = client.post("/api/macro/numpad_10", json={"wait_for_game": True})
    assert response.status_code == 404


def test_game_svg_icons_are_cached_locally(monkeypatch, tmp_path):
    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            return b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'

    calls = []
    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(server, "ICON_CACHE_DIR", tmp_path)
    monkeypatch.setattr(server.urllib.request, "urlopen", fake_urlopen)
    client = TestClient(server.app)
    first = client.get('/api/icons/0')
    second = client.get('/api/icons/0')
    assert first.status_code == 200
    assert first.headers['content-type'].startswith('image/svg+xml')
    assert b'<svg' in first.content
    assert second.content == first.content
    assert len(calls) == 1
    assert (tmp_path / '0.svg').exists()


def test_version_and_status():
    client = TestClient(server.app)
    assert server.app.version == "0.21.0"
    status = client.get("/api/status").json()
    assert status["version"] == "0.21.0"
    assert len(status["binding_keys"]) == 15
    assert status["macro"]["binding_count"] == 15


def test_numpad_keys_show_only_symbol_or_original_icon():
    client = TestClient(server.app)
    component = client.get("/assets/components/NumPad.js").text
    css = client.get("/assets/css/numpad.css").text
    assert "num-key-name" not in component
    assert "num-key-empty" not in component
    assert "key-clear" not in component
    assert "h('img'" in component and "item\n        ?" in component
    assert "key.label" in component
    assert "label: '-'" in client.get("/assets/app.js").text
    assert "num-key-label" in component and "num-key-name" not in component
    assert "filter: none !important" in css
    assert "background: #000" in css
    assert "brightness(0)" not in css
    assert "numpad_add: [4, '2 / span 3']" in component


def test_websocket_delivers_physical_key_feedback_without_pin():
    with TestClient(server.app) as client:
        # No PIN, HTTP token, or query token is needed.
        with client.websocket_connect("/ws/keys") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            server.publish_key_event("key_down", "numpad_7")
            down = websocket.receive_json()
            assert down["type"] == "key_down"
            assert down["binding_id"] == "numpad_7"
            server.publish_key_event("key_up", "numpad_7")
            up = websocket.receive_json()
            assert up["type"] == "key_up"
            assert up["binding_id"] == "numpad_7"


def test_pin_and_auth_dialog_are_removed():
    client = TestClient(server.app)
    homepage = client.get("/").text
    app_js = client.get("/assets/app.js").text
    assert client.get("/api/config").status_code == 200
    assert client.put("/api/config", json=server.public_config()).status_code == 200
    assert client.post("/api/auth", json={"pin": "123456"}).status_code == 404
    assert "AuthDialog" not in homepage
    assert "hd2_access_token" not in app_js
    assert "X-Access-Token" not in app_js
    assert "/ws/keys?token=" not in app_js
    assert "/ws/keys'" in app_js
    assert "authOpen" not in app_js
    assert "/api/auth" not in app_js
    assert "AuthDialog" not in app_js


def test_minimal_numpad_has_real_key_press_feedback():
    client = TestClient(server.app)
    app_js = client.get("/assets/app.js").text
    numpad_js = client.get("/assets/components/NumPad.js").text
    numpad_css = client.get("/assets/css/numpad.css").text
    homepage = client.get("/").text
    assert "new WebSocket(scheme + window.location.host + '/ws/keys')" in app_js
    assert "key_down" in app_js and "key_up" in app_js
    assert "pressedKeys" in app_js
    assert "is-game-pressed" in numpad_js
    assert ".numpad-key.is-game-pressed" in numpad_css
    assert "settings-gear" in numpad_js
    assert "numpad-heading" not in numpad_js
    assert "Цифровой блок" not in numpad_js
    assert "РАСКЛАДКА НАЗНАЧЕНИЙ" not in numpad_js
    assert "components/Header.js" not in homepage
    assert "css/header.css" not in homepage


def test_websocket_runtime_dependency_is_installed_by_requirements():
    from pathlib import Path
    requirements = (Path(server.APP_DIR) / "requirements.txt").read_text(encoding="utf-8")
    assert "uvicorn[standard]" in requirements


def test_picker_is_floating_category_grid_with_icons_only():
    client = TestClient(server.app)
    picker_js = client.get("/assets/components/StratagemPicker.js").text
    picker_css = client.get("/assets/css/picker.css").text
    app_js = client.get("/assets/app.js").text
    assert "picker-backdrop" in picker_js
    assert "picker-icon-grid" in picker_js
    assert "picker-icon-tile" in picker_js
    assert "picker-search" in picker_js
    assert "picker-row" not in picker_js
    assert "['Все']" not in picker_js
    assert "activeCategory: 'Все'" not in app_js
    assert "repeat(auto-fill" in picker_css
    assert "filter: none !important" in picker_css
    assert "numpad-key-wrap ' + (key.cls || '')" in client.get("/assets/components/NumPad.js").text


def test_special_key_icon_geometry_is_constrained():
    client = TestClient(server.app)
    css = client.get("/assets/css/numpad.css").text
    for selector in [".key-add .num-key-icon", ".key-0 .num-key-icon", ".key-decimal .num-key-icon", ".key-divide .num-key-icon"]:
        assert selector in css


def test_picker_has_category_grid_delayed_tooltips_and_selected_overview():
    client = TestClient(server.app)
    picker_js = client.get("/assets/components/StratagemPicker.js").text
    picker_css = client.get("/assets/css/picker.css").text
    app_js = client.get("/assets/app.js").text
    assert "picker-selected-strip" in picker_js
    assert "selectedItems" in picker_js
    assert "picker-selected-mark" in picker_js
    assert "data-tooltip" in picker_js
    assert "assignedItem.category" in app_js
    assert "}, 500);" in picker_js
    assert "picker-categories" in picker_css
    assert "display: grid" in picker_css
    assert "overflow-x: auto" not in picker_css


def test_settings_popup_is_adaptive_and_scrolls_internally():
    client = TestClient(server.app)
    settings_js = client.get("/assets/components/SettingsDialog.js").text
    dialogs_css = client.get("/assets/css/dialogs.css").text
    app_js = client.get("/assets/app.js").text
    assert "settings-dialog" in settings_js
    assert "settings-body" in settings_js
    assert "aria-modal" in settings_js
    assert "openSettings" in app_js
    assert "max-height: min(760px, calc(100dvh - 20px))" in dialogs_css
    assert "overflow-y: auto" in dialogs_css
    assert "@media (max-width: 560px)" in dialogs_css
    assert "@media (max-width: 380px)" in dialogs_css


def test_settings_dialog_has_no_title_cancel_and_arrow_only_direction_labels():
    client = TestClient(server.app)
    settings_js = client.get("/assets/components/SettingsDialog.js").text
    assert "КОНФИГУРАЦИЯ ВВОДА" not in settings_js
    assert "h2" not in settings_js
    assert "ОТМЕНА" not in settings_js
    assert "settings-close" not in settings_js
    assert "settings-direction-glyph" in settings_js
    assert "DIRECTION_GLYPHS" in settings_js
    assert "↑ Вверх" not in settings_js
    assert "↓ Вниз" not in settings_js
    assert "← Влево" not in settings_js
    assert "→ Вправо" not in settings_js
    assert "СОХРАНИТЬ" in settings_js


def test_stratagem_name_tooltip_is_above_the_icon():
    client = TestClient(server.app)
    picker_js = client.get("/assets/components/StratagemPicker.js").text
    picker_css = client.get("/assets/css/picker.css").text
    assert "picker-hover-description" in picker_js
    assert "scheduleHoverDescription" in picker_js
    assert "setTimeout(function ()" in picker_js
    assert "}, 500);" in picker_js
    assert "position: fixed" in picker_css
    assert "picker-hover-description.is-visible" in picker_css
    assert "picker-icon-tooltip" not in picker_js
    assert "picker-icon-tile:hover img" not in picker_css


def test_assigned_key_description_appears_above_key_with_name_and_arrows():
    client = TestClient(server.app)
    component = client.get("/assets/components/NumPad.js").text
    css = client.get("/assets/css/numpad.css").text
    assert "key-description-tooltip" in component
    assert "item.name" in component and "item.arrows" in component
    assert "key-description-name" in component and "key-description-arrows" in component
    # Native browser title tooltips used to cover the icon; use the custom positioned tooltip instead.
    assert "title: accessibleName" not in component
    assert "bottom: calc(100% + 9px)" in css
    assert ".numpad-key-wrap:hover .key-description-tooltip" in css
    assert "transition-delay: .5s, .5s, 0s" in css


def test_websocket_ready_includes_canonical_initial_config_and_revision():
    with TestClient(server.app) as client:
        config = client.get("/api/config").json()
        with client.websocket_connect("/ws/keys") as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "ready"
            assert ready["config"]["revision"] == config["revision"]
            assert ready["config"]["bindings"] == config["bindings"]
            assert "status" in ready


def test_config_updates_are_broadcast_to_every_websocket_client(monkeypatch):
    open_client(monkeypatch)
    with TestClient(server.app) as client:
        config = client.get("/api/config").json()
        with client.websocket_connect("/ws/keys") as edge_socket, client.websocket_connect("/ws/keys") as chrome_socket:
            assert edge_socket.receive_json()["type"] == "ready"
            assert chrome_socket.receive_json()["type"] == "ready"
            config["bindings"]["numpad_7"] = server.CATALOG[0]["name"]
            response = client.put("/api/config", json=config)
            assert response.status_code == 200
            saved = response.json()["config"]
            for socket in (edge_socket, chrome_socket):
                event = socket.receive_json()
                assert event["type"] == "config_updated"
                assert event["revision"] == saved["revision"]
                assert event["config"]["bindings"]["numpad_7"] == server.CATALOG[0]["name"]


def test_stale_config_is_rejected_with_latest_snapshot_instead_of_overwriting():
    with TestClient(server.app) as client:
        tab_a = client.get("/api/config").json()
        tab_b = copy.deepcopy(tab_a)
        tab_a["bindings"]["numpad_1"] = server.CATALOG[0]["name"]
        saved_a = client.put("/api/config", json=tab_a)
        assert saved_a.status_code == 200
        tab_b["bindings"]["numpad_2"] = server.CATALOG[1]["name"]
        stale = client.put("/api/config", json=tab_b)
        assert stale.status_code == 409
        current = stale.json()["detail"]["config"]
        assert current["bindings"]["numpad_1"] == server.CATALOG[0]["name"]
        assert current["bindings"]["numpad_2"] is None


def test_settings_update_emits_dedicated_event(monkeypatch):
    with open_client(monkeypatch) as client:
        config = client.get("/api/config").json()
        with client.websocket_connect("/ws/keys") as websocket:
            websocket.receive_json()
            config["press_ms"] = 90 if config["press_ms"] != 90 else 85
            response = client.put("/api/config", json=config)
            assert response.status_code == 200
            config_event = websocket.receive_json()
            settings_event = websocket.receive_json()
            assert config_event["type"] == "config_updated"
            assert settings_event["type"] == "settings_updated"
            assert settings_event["settings"]["press_ms"] == config["press_ms"]


def test_browser_client_uses_revisioned_sync_and_merges_stale_dialog_edits():
    client = TestClient(server.app)
    app_js = client.get("/assets/app.js").text
    assert "config_updated" in app_js
    assert "settings_updated" in app_js
    assert "mergeLocalConfigChanges" in app_js
    assert "payload = Object.assign({}, candidate, { revision: Number(base.revision || 1) })" in app_js
    assert "settingsBase" in app_js
    assert "draft.direction_keys[direction] !== base.direction_keys[direction]" in app_js


def test_config_revision_is_persisted_and_required(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr(server, "CONFIG_PATH", path)
    monkeypatch.setattr(server, "CONFIG_REVISION", 12)
    server.write_config(server.CONFIG)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["_revision"] == 12
    client = TestClient(server.app)
    config = client.get("/api/config").json()
    config.pop("revision")
    assert client.put("/api/config", json=config).status_code == 422


def test_open_settings_dialog_merges_remote_values_without_losing_local_edits():
    app_js = TestClient(server.app).get("/assets/app.js").text
    assert "App.prototype.applyRemoteConfig" in app_js
    assert "oldDraft[field] === oldBase[field]" in app_js
    assert "oldDraft.direction_keys[direction] === oldBase.direction_keys[direction]" in app_js
    assert "patch.settingsBase = newBase" in app_js
    assert "self.applyRemoteConfig(event.config)" in app_js


def test_hook_consumes_key_repeat_and_triggers_macro_only_once(monkeypatch):
    hook = server.GlobalNumpadHook(server.MACROS)
    monkeypatch.setattr(server, "CONFIG", json.loads(json.dumps(server.CONFIG)))
    monkeypatch.setitem(server.CONFIG["bindings"], "numpad_7", server.CATALOG[0]["name"])
    monkeypatch.setattr(server, "windows_is_game_foreground", lambda: (True, "Helldivers2.exe"))
    events, triggers = [], []
    monkeypatch.setattr(server, "publish_key_event", lambda event_type, binding_id: events.append((event_type, binding_id)))
    monkeypatch.setattr(server.MACROS, "trigger", lambda *args, **kwargs: triggers.append((args, kwargs)) or (True, "ok"))

    assert hook.handle_binding_event("numpad_7", True, False) is True
    assert hook.handle_binding_event("numpad_7", True, False) is True
    assert len(triggers) == 1
    assert events == [("key_down", "numpad_7")]
    assert hook.handle_binding_event("numpad_7", False, True) is True
    assert events[-1] == ("key_up", "numpad_7")
    assert "numpad_7" not in hook.pressed


def test_unassigned_or_non_game_numpad_input_passes_through(monkeypatch):
    hook = server.GlobalNumpadHook(server.MACROS)
    monkeypatch.setattr(server, "CONFIG", json.loads(json.dumps(server.CONFIG)))
    monkeypatch.setitem(server.CONFIG["bindings"], "numpad_8", None)
    monkeypatch.setattr(server, "windows_is_game_foreground", lambda: (True, "Helldivers2.exe"))
    assert hook.handle_binding_event("numpad_8", True, False) is False

    monkeypatch.setitem(server.CONFIG["bindings"], "numpad_8", server.CATALOG[0]["name"])
    monkeypatch.setattr(server, "windows_is_game_foreground", lambda: (False, "chrome.exe"))
    assert hook.handle_binding_event("numpad_8", True, False) is False
    assert "numpad_8" not in hook.pressed


def test_macro_execution_uses_immutable_settings_snapshot(monkeypatch):
    monkeypatch.setattr(server, "CONFIG", json.loads(json.dumps(server.CONFIG)))
    engine = server.MacroEngine()
    snapshot = {
        "open_key": "CTRL",
        "direction_keys": {"U": "UP", "D": "DOWN", "L": "LEFT", "R": "RIGHT"},
        "press_ms": 65, "gap_ms": 65, "open_hold_ms": 100,
    }
    sent, sleeps = [], []
    monkeypatch.setattr(server, "windows_is_game_foreground", lambda: (True, "Helldivers2.exe"))

    def fake_send(vk, key_up=False):
        sent.append((vk, key_up))
        if len(sent) == 1:
            with server.CONFIG_LOCK:
                server.CONFIG["open_key"] = "ALT"
                server.CONFIG["direction_keys"] = {"U": "W", "D": "S", "L": "A", "R": "D"}
                server.CONFIG["press_ms"] = 200
                server.CONFIG["gap_ms"] = 200
                server.CONFIG["open_hold_ms"] = 250

    monkeypatch.setattr(server, "send_vk", fake_send)
    monkeypatch.setattr(engine, "_wait_or_cancel", lambda duration: sleeps.append(duration))
    engine._execute("numpad_7", {"name": "Тест", "code": "UR"}, 0, snapshot)

    assert sent == [
        (server.VK["CTRL"], False),
        (server.VK["UP"], False), (server.VK["UP"], True),
        (server.VK["RIGHT"], False), (server.VK["RIGHT"], True),
        (server.VK["CTRL"], True),
    ]
    assert sleeps == [0.1, 0.065, 0.065, 0.065, 0.065]
    assert engine.last_result.startswith("Готово:")


def test_websocket_rejects_cross_origin_browser_connection():
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with TestClient(server.app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/keys", headers={"origin": "https://attacker.example"}):
                pass


def test_failed_config_write_rolls_back_memory_and_revision(monkeypatch):
    monkeypatch.setattr(server, "CONFIG", json.loads(json.dumps(server.CONFIG)))
    monkeypatch.setattr(server, "CONFIG_REVISION", 77)
    config = server.public_config()
    config["bindings"]["numpad_6"] = server.CATALOG[0]["name"]
    before = server.public_config()

    def fail_write(_config):
        raise OSError("disk is read-only")

    monkeypatch.setattr(server, "write_config", fail_write)
    from fastapi import HTTPException
    payload = server.ConfigPayload(**config)
    with pytest.raises(HTTPException) as exc:
        server.update_configuration(payload)
    assert exc.value.status_code == 500
    assert server.public_config() == before
    assert server.CONFIG_REVISION == 77



def test_http_guard_allows_local_hosts_and_rejects_dns_rebinding_hosts():
    assert server.is_local_host("127.0.0.1:8765", "127.0.0.1")
    assert server.is_local_host("192.168.1.77:8765", "192.168.1.3")
    assert server.is_local_host("localhost:8765", "127.0.0.1")
    assert server.is_local_host("gaming-pc.local:8765", "192.168.1.3")
    assert not server.is_local_host("attacker.example:8765", "192.168.1.3")
    assert not server.is_local_host("192.168.1.77:8765", "8.8.8.8")
    assert not server.is_local_host("8.8.8.8:8765", "192.168.1.3")


def test_mutating_http_requests_reject_foreign_origin_but_allow_same_origin(monkeypatch):
    with open_client(monkeypatch) as client:
        config = client.get("/api/config").json()
        foreign = client.put("/api/config", json=config, headers={"origin": "https://attacker.example"})
        assert foreign.status_code == 403
        same = client.put("/api/config", json=config, headers={"origin": "http://testserver"})
        assert same.status_code == 200


def test_corrupt_config_is_backed_up_before_defaults_are_written(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"bindings": ', encoding="utf-8")
    monkeypatch.setattr(server, "CONFIG_PATH", path)
    monkeypatch.setattr(server, "CONFIG_REVISION", 1)
    recovered = server.read_config()
    assert set(recovered["bindings"]) == server.BINDING_IDS
    backups = list(tmp_path.glob("config.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '{"bindings": '
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert set(saved["bindings"]) == server.BINDING_IDS
    assert saved["_revision"] >= 1


def test_config_write_is_atomic_and_leaves_no_temp_file(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr(server, "CONFIG_PATH", path)
    monkeypatch.setattr(server, "CONFIG_REVISION", 9)
    server.write_config(server.CONFIG)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["_revision"] == 9
    assert not path.with_suffix(".tmp").exists()


def test_icon_cache_serializes_concurrent_misses_and_writes_atomically(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time as time_module

    calls = []
    call_lock = threading.Lock()
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit):
            time_module.sleep(0.04)
            return b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'

    def fake_urlopen(request, timeout):
        with call_lock:
            calls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(server, "ICON_CACHE_DIR", tmp_path)
    monkeypatch.setattr(server.urllib.request, "urlopen", fake_urlopen)
    relative = server.ICON_MAP[server.CATALOG[0]["name"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda _: server._ensure_icon_cached(0, relative), range(8)))
    assert len(set(paths)) == 1
    assert len(calls) == 1
    assert paths[0].read_bytes().startswith(b'<svg')
    assert not list(tmp_path.glob("*.tmp"))


def test_hook_repairs_pressed_state_after_lost_key_up(monkeypatch):
    hook = server.GlobalNumpadHook(server.MACROS)
    monkeypatch.setattr(server, "CONFIG", json.loads(json.dumps(server.CONFIG)))
    monkeypatch.setitem(server.CONFIG["bindings"], "numpad_7", server.CATALOG[0]["name"])
    monkeypatch.setattr(server, "windows_is_game_foreground", lambda: (True, "Helldivers2.exe"))
    clock = [100.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: clock[0])
    events, triggers = [], []
    monkeypatch.setattr(server, "publish_key_event", lambda event_type, binding_id: events.append((event_type, binding_id)))
    monkeypatch.setattr(server.MACROS, "trigger", lambda *args, **kwargs: triggers.append(binding_id := args[0]) or (True, "ok"))

    assert hook.handle_binding_event("numpad_7", True, False) is True
    clock[0] = 100.5  # Windows auto-repeat while the key is still held.
    assert hook.handle_binding_event("numpad_7", True, False) is True
    assert len(triggers) == 1
    clock[0] = 103.0  # The old key_up was lost; next press clears stale state.
    assert hook.handle_binding_event("numpad_7", True, False) is True
    assert len(triggers) == 2
    assert events == [
        ("key_down", "numpad_7"), ("key_up", "numpad_7"), ("key_down", "numpad_7")
    ]


def test_injected_keyboard_events_are_ignored_by_hook_source():
    source = (server.APP_DIR / "app.py").read_text(encoding="utf-8")
    assert "LLKHF_INJECTED = 0x10" in source
    assert "LLKHF_LOWER_IL_INJECTED = 0x02" in source
    assert "info.flags & (self.LLKHF_INJECTED | self.LLKHF_LOWER_IL_INJECTED)" in source


def test_hook_has_idempotent_lifecycle_and_shutdown_cleanup():
    source = (server.APP_DIR / "app.py").read_text(encoding="utf-8")
    assert "if self.thread and self.thread.is_alive():" in source
    assert "def stop(self, timeout: float = 3.0):" in source
    assert "user32.PostThreadMessageW(thread_id, self.WM_QUIT, 0, 0)" in source
    assert "HOTKEYS.stop()" in source
    assert "self.pressed.clear()" in source


def test_config_client_keeps_newer_websocket_snapshot_on_failed_put():
    app_js = (server.APP_DIR / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "var latestFromServer = detail" in app_js
    assert "currentRevision > Number(latest.revision || 0)" in app_js
    assert "currentRevision <= Number(base.revision || 0)" in app_js
    assert "return send(next, previous, 4)" in app_js


def test_python_minimum_is_supported_release():
    bat = (server.APP_DIR / "run_server.bat").read_text(encoding="utf-8")
    assert "sys.version_info >= (3,12)" in bat
    assert "Python 3.12 or newer" in bat
    assert "3.10 or newer" not in bat



def test_icon_map_rejects_paths_that_escape_repository_root(monkeypatch, tmp_path):
    path = tmp_path / "icon_map.json"
    path.write_text(json.dumps({
        "valid": "Weapons/valid.svg",
        "traversal": "../../secret.svg",
        "absolute": "/etc/passwd",
        "windows": "..\\secret.svg",
        "url": "https://example.com/icon.svg",
    }), encoding="utf-8")
    monkeypatch.setattr(server, "ICON_MAP_PATH", path)
    mapping = server.load_icon_map()
    assert mapping == {"valid": "Weapons/valid.svg"}


def test_hook_sends_throttled_visual_heartbeat_for_long_key_holds(monkeypatch):
    hook = server.GlobalNumpadHook(server.MACROS)
    monkeypatch.setattr(server, "CONFIG", json.loads(json.dumps(server.CONFIG)))
    monkeypatch.setitem(server.CONFIG["bindings"], "numpad_5", server.CATALOG[0]["name"])
    monkeypatch.setattr(server, "windows_is_game_foreground", lambda: (True, "Helldivers2.exe"))
    clock = [200.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: clock[0])
    events, triggers = [], []
    monkeypatch.setattr(server, "publish_key_event", lambda event_type, binding_id: events.append((event_type, binding_id)))
    monkeypatch.setattr(server.MACROS, "trigger", lambda *args, **kwargs: triggers.append(args[0]) or (True, "ok"))

    assert hook.handle_binding_event("numpad_5", True, False)
    clock[0] = 200.4
    assert hook.handle_binding_event("numpad_5", True, False)  # ordinary OS repeat
    clock[0] = 200.8
    assert hook.handle_binding_event("numpad_5", True, False)  # one visual heartbeat
    assert triggers == ["numpad_5"]
    assert events == [("key_down", "numpad_5"), ("key_down", "numpad_5")]
    assert hook.handle_binding_event("numpad_5", False, True)
    assert events[-1] == ("key_up", "numpad_5")



def test_html_and_icon_urls_are_versioned_to_prevent_stale_browser_assets():
    client = TestClient(server.app)
    response = client.get("/")
    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert "/assets/app.js?v=0.21.0" in response.text
    assert "/assets/components/NumPad.js?v=0.21.0" in response.text
    first = client.get("/api/stratagems").json()["items"][0]
    assert first["icon_url"].endswith("?v=0.21.0")


def test_frontend_sources_match_the_exact_files_served_by_fastapi():
    from pathlib import Path
    app_dir = Path(server.APP_DIR)
    pairs = [
        ("frontend/src/App.js", "web/assets/app.js"),
        ("frontend/src/components/NumPad.js", "web/assets/components/NumPad.js"),
        ("frontend/src/components/StratagemPicker.js", "web/assets/components/StratagemPicker.js"),
        ("frontend/src/components/SettingsDialog.js", "web/assets/components/SettingsDialog.js"),
        ("frontend/src/components/Toast.js", "web/assets/components/Toast.js"),
        ("frontend/src/styles/core.css", "web/assets/css/core.css"),
        ("frontend/src/styles/numpad.css", "web/assets/css/numpad.css"),
        ("frontend/src/styles/picker.css", "web/assets/css/picker.css"),
        ("frontend/src/styles/dialogs.css", "web/assets/css/dialogs.css"),
    ]
    for source, served in pairs:
        assert (app_dir / source).read_bytes() == (app_dir / served).read_bytes(), (source, served)



def test_local_network_guard_rejects_public_peer_even_with_private_host():
    assert not server.is_local_host("192.168.1.5:8765", "203.0.113.7")
    assert server.is_local_peer("192.168.1.5")
    assert server.is_local_peer("127.0.0.1")
    assert not server.is_local_peer("203.0.113.7")



def test_macro_shutdown_cancels_an_in_progress_input_and_releases_modifiers(monkeypatch):
    import threading
    engine = server.MacroEngine()
    engine.start()
    monkeypatch.setattr(server, "windows_is_game_foreground", lambda: (True, "Helldivers2.exe"))
    opened = threading.Event()
    sent = []
    def fake_send(vk, key_up=False):
        sent.append((vk, key_up))
        if vk == server.VK["CTRL"] and not key_up:
            opened.set()
    monkeypatch.setattr(server, "send_vk", fake_send)
    snapshot = {
        "open_key": "CTRL",
        "direction_keys": {"U": "UP", "D": "DOWN", "L": "LEFT", "R": "RIGHT"},
        "press_ms": 65, "gap_ms": 65, "open_hold_ms": 500,
    }
    worker = threading.Thread(target=engine._execute, args=("numpad_7", {"name": "Тест", "code": "U"}, 0, snapshot))
    worker.start()
    assert opened.wait(1.0)
    engine.shutdown(timeout=1.0)
    worker.join(1.0)
    assert not worker.is_alive()
    assert sent == [(server.VK["CTRL"], False), (server.VK["CTRL"], True)]
    assert not engine.running
    assert "отменён" in engine.last_result.lower()


def test_macro_engine_refuses_to_restart_while_old_worker_is_alive():
    import threading
    engine = server.MacroEngine()
    gate = threading.Event()
    worker = threading.Thread(target=gate.wait)
    engine.worker = worker
    worker.start()
    try:
        assert engine.start() is False
        assert engine.shutting_down is False
    finally:
        gate.set()
        worker.join(1.0)


def test_launcher_skips_dependency_install_when_environment_is_healthy():
    bat = (server.APP_DIR / "run_server.bat").read_text(encoding="utf-8")
    assert "Checking required packages" in bat
    assert "pip._vendor.packaging.version" in bat
    assert "Skipping pip." in bat
    assert "pip install --disable-pip-version-check -r requirements.txt" in bat
    assert "Existing virtual environment uses Python older than 3.12" in bat
    assert "sys.version_info >= (3,12)" in bat


def test_picker_and_settings_popups_are_top_anchored():
    client = TestClient(server.app)
    picker_css = client.get("/assets/css/picker.css").text
    dialogs_css = client.get("/assets/css/dialogs.css").text
    assert "place-items: start center" in picker_css
    assert "align-content: start" in picker_css
    assert "place-items: start center" in dialogs_css
    assert "align-content: start" in dialogs_css
    assert "max-height: min(840px, calc(100dvh - 20px))" in picker_css
    assert "max-height: min(760px, calc(100dvh - 20px))" in dialogs_css


def test_picker_hover_tooltip_uses_safe_text_and_half_second_delay():
    client = TestClient(server.app)
    picker_js = client.get("/assets/components/StratagemPicker.js").text
    picker_css = client.get("/assets/css/picker.css").text
    assert "name.textContent = item.name" in picker_js
    assert "token.textContent = arrow" in picker_js
    assert "document.body.appendChild(tooltip)" in picker_js
    assert "rect.top - size.height - 9" in picker_js
    assert "}, 500);" in picker_js
    assert "pointer-events: none" in picker_css
    assert "picker-hover-description.is-visible" in picker_css


def test_served_assets_match_component_sources():
    from pathlib import Path
    app_dir = Path(server.APP_DIR)
    pairs = [
        ("frontend/src/components/StratagemPicker.js", "web/assets/components/StratagemPicker.js"),
        ("frontend/src/styles/picker.css", "web/assets/css/picker.css"),
        ("frontend/src/styles/dialogs.css", "web/assets/css/dialogs.css"),
        ("frontend/src/styles/numpad.css", "web/assets/css/numpad.css"),
    ]
    for source, served in pairs:
        assert (app_dir / source).read_bytes() == (app_dir / served).read_bytes(), served
