/* HD2 Stratagem LAN 0.21.0 — application controller. Visual components live in ./components. */
(function () {
  'use strict';
  var h = React.createElement;
  var UI = window.HD2UI;
  var MAIN_KEYS = Array.from({ length: 10 }, function (_, digit) {
    return { id: 'numpad_' + digit, label: String(digit), title: 'Numpad ' + digit, group: 'main' };
  });
  var EXTRA_KEYS = [
    { id: 'numpad_decimal', label: '.', title: 'Numpad Decimal', group: 'extra' },
    { id: 'numpad_subtract', label: '-', title: 'Numpad Subtract', group: 'extra' },
    { id: 'numpad_add', label: '+', title: 'Numpad Add', group: 'extra' },
    { id: 'numpad_multiply', label: '*', title: 'Numpad Multiply', group: 'extra' },
    { id: 'numpad_divide', label: '/', title: 'Numpad Divide', group: 'extra' }
  ];
  var ALL_KEYS = MAIN_KEYS.concat(EXTRA_KEYS);
  var KEY_BY_ID = {};
  ALL_KEYS.forEach(function (key) { KEY_BY_ID[key.id] = key; });
  var CATEGORY_PRIORITY = ['По умолчанию', 'Стратагемы заданий', 'Оружие поддержки', 'Орбитальные и авиаудары', 'Оборонительные установки', 'Рюкзаки', 'Техника'];

  function api(path, options) {
    options = options || {};
    var headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
    return fetch(path, Object.assign({}, options, { headers: headers })).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok) {
          var detail = payload.detail;
          var message = detail && typeof detail === 'object' ? detail.message : detail;
          var error = new Error(message || ('Ошибка HTTP ' + response.status));
          error.status = response.status;
          error.payload = payload;
          throw error;
        }
        return payload;
      });
    });
  }

  function mergeLocalConfigChanges(base, candidate, latest) {
    var merged = Object.assign({}, latest);
    ['bindings', 'direction_keys'].forEach(function (field) {
      merged[field] = Object.assign({}, latest[field] || {});
      var before = base[field] || {};
      var after = candidate[field] || {};
      Object.keys(after).forEach(function (key) {
        if (before[key] !== after[key]) merged[field][key] = after[key];
      });
    });
    ['open_key', 'press_ms', 'gap_ms', 'open_hold_ms'].forEach(function (field) {
      if (base[field] !== candidate[field]) merged[field] = candidate[field];
    });
    return merged;
  }

  function App() {
    React.Component.call(this);
    this.state = {
      catalog: [], categories: [], config: null,
      selectedBinding: 'numpad_1',
      pickerOpen: false, activeCategory: 'По умолчанию', search: '',
      pressedKeys: {}, loading: true, saving: false,
      settingsOpen: false, settingsDraft: null, settingsBase: null, toast: null
    };
    this.toastTimer = null;
    this.keySocket = null;
    this.keyPingTimer = null;
    this.keyReconnectTimer = null;
    this.pressedTimers = {};
    this.isUnmounted = false;
  }
  App.prototype = Object.create(React.Component.prototype);
  App.prototype.constructor = App;

  App.prototype.componentDidMount = function () {
    var self = this;
    api('/api/stratagems').then(function (data) {
      var categories = data.categories || [];
      categories = CATEGORY_PRIORITY.filter(function (category) { return categories.indexOf(category) !== -1; })
        .concat(categories.filter(function (category) { return CATEGORY_PRIORITY.indexOf(category) === -1; }));
      self.setState({ catalog: data.items || [], categories: categories, activeCategory: categories[0] || 'По умолчанию', loading: false });
      self.loadConfig().catch(function (error) {
        self.setState({ loading: false, toast: { message: 'Не удалось загрузить настройки: ' + error.message, error: true } });
      });
    }).catch(function (error) {
      self.setState({ loading: false, toast: { message: 'Не удалось загрузить каталог: ' + error.message, error: true } });
    });
  };
  App.prototype.componentWillUnmount = function () {
    this.isUnmounted = true;
    if (this.toastTimer) clearTimeout(this.toastTimer);
    if (this.keyPingTimer) clearInterval(this.keyPingTimer);
    if (this.keyReconnectTimer) clearTimeout(this.keyReconnectTimer);
    Object.keys(this.pressedTimers).forEach(function (key) { clearTimeout(this.pressedTimers[key]); }, this);
    if (this.keySocket) { this.keySocket.onclose = null; this.keySocket.close(); this.keySocket = null; }
  };
  App.prototype.notify = function (message, error) {
    var self = this;
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.setState({ toast: { message: message, error: !!error } });
    this.toastTimer = setTimeout(function () { self.setState({ toast: null }); }, 3000);
  };
  App.prototype.loadConfig = function () {
    var self = this;
    return api('/api/config').then(function (config) {
      self.applyRemoteConfig(config);
      self.connectKeySocket();
      return config;
    });
  };
  App.prototype.applyRemoteConfig = function (incoming) {
    if (!incoming) return;
    var currentRevision = Number(this.state.config && this.state.config.revision || 0);
    var incomingRevision = Number(incoming.revision || 1);
    if (incomingRevision <= currentRevision) return;
    var patch = { config: incoming };

    // Keep an open settings dialog in sync too: untouched fields follow the server,
    // while edits the user has already made locally remain in the draft.
    if (this.state.settingsOpen && this.state.settingsDraft && this.state.settingsBase) {
      var oldBase = this.state.settingsBase;
      var oldDraft = this.state.settingsDraft;
      var newBase = {
        open_key: incoming.open_key,
        direction_keys: Object.assign({}, incoming.direction_keys),
        press_ms: incoming.press_ms, gap_ms: incoming.gap_ms, open_hold_ms: incoming.open_hold_ms
      };
      var newDraft = Object.assign({}, oldDraft, { direction_keys: Object.assign({}, oldDraft.direction_keys) });
      ['open_key', 'press_ms', 'gap_ms', 'open_hold_ms'].forEach(function (field) {
        if (oldDraft[field] === oldBase[field]) newDraft[field] = newBase[field];
      });
      ['U', 'D', 'L', 'R'].forEach(function (direction) {
        if (oldDraft.direction_keys[direction] === oldBase.direction_keys[direction]) {
          newDraft.direction_keys[direction] = newBase.direction_keys[direction];
        }
      });
      patch.settingsBase = newBase;
      patch.settingsDraft = newDraft;
    }
    this.setState(patch);
  };
  App.prototype.setPhysicalKeyState = function (bindingId, pressed) {
    var next = Object.assign({}, this.state.pressedKeys);
    if (pressed) next[bindingId] = true; else delete next[bindingId];
    this.setState({ pressedKeys: next });
  };
  App.prototype.handlePhysicalKeyEvent = function (event) {
    var bindingId = event && event.binding_id;
    if (!KEY_BY_ID[bindingId]) return;
    if (this.pressedTimers[bindingId]) clearTimeout(this.pressedTimers[bindingId]);
    if (event.type === 'key_down') {
      this.setPhysicalKeyState(bindingId, true);
      var self = this;
      // Safety release in case the browser misses a key-up while the Game Bar is suspended.
      this.pressedTimers[bindingId] = setTimeout(function () {
        self.setPhysicalKeyState(bindingId, false);
        delete self.pressedTimers[bindingId];
      }, 900);
    } else if (event.type === 'key_up') {
      var self = this;
      this.pressedTimers[bindingId] = setTimeout(function () {
        self.setPhysicalKeyState(bindingId, false);
        delete self.pressedTimers[bindingId];
      }, 110);
    }
  };
  App.prototype.connectKeySocket = function () {
    var self = this;
    if (this.isUnmounted || typeof WebSocket === 'undefined') return;
    if (this.keySocket && (this.keySocket.readyState === WebSocket.OPEN || this.keySocket.readyState === WebSocket.CONNECTING)) return;
    var scheme = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    var socket = new WebSocket(scheme + window.location.host + '/ws/keys');
    this.keySocket = socket;
    socket.onmessage = function (message) {
      try {
        var event = JSON.parse(message.data);
        if (event.type === 'key_down' || event.type === 'key_up') {
          self.handlePhysicalKeyEvent(event);
          return;
        }
        if ((event.type === 'ready' || event.type === 'config_updated') && event.config) {
          self.applyRemoteConfig(event.config);
          return;
        }
        if (event.type === 'settings_updated' && event.settings) {
          var latestRevision = Number(event.revision || 0);
          var knownRevision = Number(self.state.config && self.state.config.revision || 0);
          if (latestRevision > knownRevision) {
            // A config_updated packet normally arrives immediately before this one.
            // Fetching the canonical snapshot also heals clients that reconnect mid-broadcast.
            self.loadConfig().catch(function () {});
          }
        }
      } catch (error) { /* Ignore malformed synchronization packets. */ }
    };
    socket.onopen = function () {
      if (self.keyPingTimer) clearInterval(self.keyPingTimer);
      self.keyPingTimer = setInterval(function () {
        if (socket.readyState === WebSocket.OPEN) socket.send('ping');
      }, 20000);
    };
    socket.onclose = function () {
      if (self.keySocket === socket) self.keySocket = null;
      if (self.keyPingTimer) { clearInterval(self.keyPingTimer); self.keyPingTimer = null; }
      if (!self.isUnmounted) {
        self.keyReconnectTimer = setTimeout(function () { self.connectKeySocket(); }, 1800);
      }
    };
    socket.onerror = function () { try { socket.close(); } catch (error) {} };
  };
  App.prototype.persistConfig = function (next, successMessage) {
    var self = this;
    var previous = Object.assign({}, this.state.config);

    function send(candidate, base, retriesLeft) {
      var payload = Object.assign({}, candidate, { revision: Number(base.revision || 1) });
      self.setState({ config: candidate, saving: true });
      return api('/api/config', { method: 'PUT', body: JSON.stringify(payload) }).then(function (result) {
        var saved = result.config || candidate;
        var currentlyShown = Number(self.state.config && self.state.config.revision || 0);
        if (Number(saved.revision || 0) >= currentlyShown) self.setState({ config: saved, saving: false });
        else self.setState({ saving: false });
        if (successMessage) self.notify(successMessage);
        return saved;
      }).catch(function (error) {
        var detail = error.payload && error.payload.detail;
        var latestFromServer = detail && typeof detail === 'object' ? detail.config : null;
        var current = self.state.config || previous;
        var currentRevision = Number(current.revision || 0);
        var latest = latestFromServer;

        // A WebSocket update can arrive after the 409 response was generated.
        // Prefer whichever snapshot has the greater revision before merging.
        if (latest && currentRevision > Number(latest.revision || 0)) latest = current;
        if (error.status === 409 && latest && retriesLeft > 0) {
          var merged = mergeLocalConfigChanges(base, candidate, latest);
          self.setState({ config: latest, saving: false });
          return send(merged, latest, retriesLeft - 1);
        }
        if (latest) {
          if (Number(latest.revision || 0) >= currentRevision) self.setState({ config: latest, saving: false });
          else self.setState({ saving: false });
        } else if (currentRevision <= Number(base.revision || 0)) {
          // Roll back only if no newer canonical state has arrived meanwhile.
          self.setState({ config: previous, saving: false });
        } else {
          self.setState({ saving: false });
        }
        self.notify(error.message, true);
        throw error;
      });
    }

    // A handful of bounded retries makes near-simultaneous edits from three or
    // more windows converge without hiding genuine validation/network failures.
    return send(next, previous, 4);
  };
  App.prototype.findItem = function (name) {
    return this.state.catalog.find(function (item) { return item.name === name; }) || null;
  };
  App.prototype.openPicker = function (bindingId) {
    var assignedName = this.state.config && this.state.config.bindings ? this.state.config.bindings[bindingId] : null;
    var assignedItem = assignedName ? this.findItem(assignedName) : null;
    var category = assignedItem ? assignedItem.category : (this.state.activeCategory || this.state.categories[0] || 'По умолчанию');
    this.setState({ selectedBinding: bindingId, pickerOpen: true, activeCategory: category, search: '' });
  };
  App.prototype.closePicker = function () { this.setState({ pickerOpen: false, search: '' }); };
  App.prototype.assign = function (name) {
    if (!this.state.config || !this.state.selectedBinding) return;
    var next = Object.assign({}, this.state.config, { bindings: Object.assign({}, this.state.config.bindings) });
    next.bindings[this.state.selectedBinding] = name;
    var key = KEY_BY_ID[this.state.selectedBinding];
    var self = this;
    this.persistConfig(next, 'Назначено: ' + name + ' → ' + key.title + '.').then(function () { self.closePicker(); }).catch(function () {});
  };
  App.prototype.clearBinding = function (bindingId) {
    if (!this.state.config) return;
    var next = Object.assign({}, this.state.config, { bindings: Object.assign({}, this.state.config.bindings) });
    next.bindings[bindingId] = null;
    var key = KEY_BY_ID[bindingId];
    var self = this;
    this.persistConfig(next, 'Назначение ' + key.title + ' очищено.').then(function () { self.closePicker(); }).catch(function () {});
  };
  App.prototype.handleSearch = function (event) { this.setState({ search: event.target.value }); };
  App.prototype.filteredCatalog = function () {
    var category = this.state.activeCategory;
    var query = this.state.search.trim().toLocaleLowerCase('ru');
    return this.state.catalog.filter(function (item) {
      if (item.category !== category) return false;
      if (!query) return true;
      return (item.name + ' ' + item.category + ' ' + item.code).toLocaleLowerCase('ru').indexOf(query) !== -1;
    });
  };
  App.prototype.openSettings = function () {
    var config = this.state.config;
    var snapshot = {
      open_key: config.open_key,
      direction_keys: Object.assign({}, config.direction_keys),
      press_ms: config.press_ms, gap_ms: config.gap_ms, open_hold_ms: config.open_hold_ms
    };
    this.setState({ settingsDraft: Object.assign({}, snapshot, { direction_keys: Object.assign({}, snapshot.direction_keys) }),
      settingsBase: snapshot, settingsOpen: true });
  };
  App.prototype.updateDraft = function (key, value) {
    var draft = Object.assign({}, this.state.settingsDraft);
    draft[key] = value;
    this.setState({ settingsDraft: draft });
  };
  App.prototype.updateDirection = function (direction, value) {
    var draft = Object.assign({}, this.state.settingsDraft);
    draft.direction_keys = Object.assign({}, draft.direction_keys);
    draft.direction_keys[direction] = value;
    this.setState({ settingsDraft: draft });
  };
  App.prototype.saveSettings = function (event) {
    event.preventDefault();
    var draft = Object.assign({}, this.state.settingsDraft, { direction_keys: Object.assign({}, this.state.settingsDraft.direction_keys) });
    var values = Object.keys(draft.direction_keys).map(function (key) { return String(draft.direction_keys[key]).toUpperCase(); });
    var allowed = ['UP', 'DOWN', 'LEFT', 'RIGHT', 'W', 'A', 'S', 'D'];
    if (values.some(function (value) { return allowed.indexOf(value) === -1; }) || new Set(values).size !== 4) {
      this.notify('Укажи четыре разные клавиши направлений.', true); return;
    }
    var invalid = false;
    [['press_ms', 25, 250], ['gap_ms', 20, 300], ['open_hold_ms', 50, 500]].forEach(function (field) {
      var value = Number(draft[field[0]]);
      if (!Number.isInteger(value) || value < field[1] || value > field[2]) invalid = true;
      draft[field[0]] = value;
    });
    if (invalid) { this.notify('Проверь диапазоны времени в настройках.', true); return; }
    // Start from the newest server snapshot and overlay only fields changed in this
    // dialog. This prevents an old open settings dialog in Chrome from restoring
    // stale values after Edge has already saved a different setting.
    var base = this.state.settingsBase || this.state.config;
    var next = Object.assign({}, this.state.config);
    ['open_key', 'press_ms', 'gap_ms', 'open_hold_ms'].forEach(function (field) {
      if (draft[field] !== base[field]) next[field] = draft[field];
    });
    next.direction_keys = Object.assign({}, this.state.config.direction_keys);
    ['U', 'D', 'L', 'R'].forEach(function (direction) {
      if (draft.direction_keys[direction] !== base.direction_keys[direction]) {
        next.direction_keys[direction] = draft.direction_keys[direction];
      }
    });
    var self = this;
    this.persistConfig(next, 'Настройки сохранены.').then(function () { self.setState({ settingsOpen: false, settingsDraft: null, settingsBase: null }); }).catch(function () {});
  };

  App.prototype.render = function () {
    if (this.state.loading) {
      return h('div', { className: 'boot-screen' }, h('div', { className: 'boot-mark' }, 'HD'), h('strong', null, 'STRATAGEM CONTROL'), h('span', null, 'ЗАГРУЗКА КАТАЛОГА…'));
    }
    var self = this;
    var selectedKey = this.state.selectedBinding;
    var selectedAssignment = this.state.config && this.state.selectedBinding ? this.state.config.bindings[this.state.selectedBinding] : null;
    var bindingConfig = this.state.config ? this.state.config.bindings : {};
    var selectedItems = ALL_KEYS.map(function (key) {
      var name = bindingConfig[key.id];
      var item = name ? self.findItem(name) : null;
      return item ? { key: key, item: item } : null;
    }).filter(Boolean);
    return h('div', { className: 'app-shell' },
      this.state.config ? h(UI.NumPad, {
        keys: ALL_KEYS,
        bindings: this.state.config.bindings,
        findItem: this.findItem.bind(this),
        activeKey: this.state.pickerOpen ? this.state.selectedBinding : null,
        pressedKeys: this.state.pressedKeys,
        onChoose: this.openPicker.bind(this),
        onSettings: this.openSettings.bind(this)
      }) : null,
      h(UI.StratagemPicker, {
        open: this.state.pickerOpen,
        selectedKey: selectedKey,
        currentAssignment: selectedAssignment,
        keys: ALL_KEYS,
        catalog: this.state.catalog,
        categories: this.state.categories,
        bindings: bindingConfig,
        selectedItems: selectedItems,
        activeCategory: this.state.activeCategory,
        search: this.state.search,
        results: this.filteredCatalog(),
        onSearch: this.handleSearch.bind(this),
        onCategory: function (category) { self.setState({ activeCategory: category }); },
        onAssign: this.assign.bind(this),
        onClearAssignment: function () { self.clearBinding(self.state.selectedBinding); },
        onClose: this.closePicker.bind(this)
      }),
      h(UI.SettingsDialog, {
        open: this.state.settingsOpen, draft: this.state.settingsDraft, saving: this.state.saving,
        onClose: function () { self.setState({ settingsOpen: false }); },
        onDraft: this.updateDraft.bind(this), onDirection: this.updateDirection.bind(this),
        onSubmit: this.saveSettings.bind(this)
      }),
      h(UI.Toast, { toast: this.state.toast })
    );
  };

  ReactDOM.render(h(App), document.getElementById('root'));
})();
