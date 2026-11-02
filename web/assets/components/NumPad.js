(function () {
  'use strict';
  var h = React.createElement;

  // Physical Numpad geometry: the two unused physical positions stay empty.
  var KEY_LAYOUT = [
    { id: 'numpad_divide', cls: 'key-divide' },
    { id: 'numpad_multiply', cls: 'key-multiply' },
    { id: 'numpad_subtract', cls: 'key-subtract' },
    { id: 'numpad_7', cls: 'key-7' },
    { id: 'numpad_8', cls: 'key-8' },
    { id: 'numpad_9', cls: 'key-9' },
    { id: 'numpad_add', cls: 'key-add' },
    { id: 'numpad_4', cls: 'key-4' },
    { id: 'numpad_5', cls: 'key-5' },
    { id: 'numpad_6', cls: 'key-6' },
    { id: 'numpad_1', cls: 'key-1' },
    { id: 'numpad_2', cls: 'key-2' },
    { id: 'numpad_3', cls: 'key-3' },
    { id: 'numpad_0', cls: 'key-0' },
    { id: 'numpad_decimal', cls: 'key-decimal' }
  ];
  var POSITIONS = {
    numpad_divide: [2, 1], numpad_multiply: [3, 1], numpad_subtract: [4, 1],
    numpad_7: [1, 2], numpad_8: [2, 2], numpad_9: [3, 2], numpad_add: [4, '2 / span 3'],
    numpad_4: [1, 3], numpad_5: [2, 3], numpad_6: [3, 3],
    numpad_1: [1, 4], numpad_2: [2, 4], numpad_3: [3, 4],
    numpad_0: ['1 / span 2', 5], numpad_decimal: [3, 5]
  };

  function Key(props) {
    var key = props.keyInfo;
    var item = props.item;
    var position = POSITIONS[key.id] || [];
    var style = {};
    if (typeof position[0] === 'number') style.gridColumn = String(position[0]);
    else if (position[0]) style.gridColumn = position[0];
    if (typeof position[1] === 'number') style.gridRow = String(position[1]);
    else if (position[1]) style.gridRow = position[1];

    var accessibleName = item
      ? key.title + ': ' + item.name + '. Код: ' + item.arrows + '. Нажми, чтобы заменить.'
      : key.title + ': назначить стратагему.';
    return h('div', {
      className: 'numpad-key-wrap ' + (key.cls || '') + (item ? ' has-assignment' : ' is-empty') +
        (props.active ? ' is-active' : '') + (props.pressed ? ' is-game-pressed' : ''),
      style: style
    },
      item ? h('div', { className: 'key-description-tooltip', 'aria-hidden': 'true' },
        h('strong', { className: 'key-description-name' }, item.name),
        h('span', { className: 'key-description-arrows' }, String(item.arrows || '').split(' ').filter(Boolean).map(function (arrow, index) {
          return h('i', { key: index }, arrow);
        }))
      ) : null,
      h('button', {
        type: 'button',
        className: 'numpad-key' + (props.pressed ? ' is-game-pressed' : ''),
        onClick: function () { props.onChoose(key.id); },
        'aria-label': accessibleName
      }, item
        ? h('img', {
            className: 'num-key-icon', src: item.icon_url, alt: '', loading: 'lazy', draggable: false,
            onError: function (event) { event.currentTarget.classList.add('icon-unavailable'); }
          })
        : h('span', { className: 'num-key-label', 'aria-hidden': 'true' }, key.label)
      )
    );
  }

  function SettingsGear(props) {
    return h('button', {
      type: 'button', className: 'settings-gear', onClick: props.onClick,
      title: 'Настройки макросов', 'aria-label': 'Настройки макросов'
    }, h('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      h('path', { d: 'M19.14 12.94c.04-.31.06-.62.06-.94s-.02-.63-.07-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.2 7.2 0 0 0-1.63-.95l-.36-2.54a.49.49 0 0 0-.49-.42h-3.84a.49.49 0 0 0-.49.42L9.2 5.3c-.59.23-1.14.55-1.63.95l-2.39-.96a.5.5 0 0 0-.6.22L2.66 8.83a.5.5 0 0 0 .12.64l2.03 1.58a6.4 6.4 0 0 0 0 1.9l-2.03 1.58a.5.5 0 0 0-.12.64l1.92 3.32c.12.21.36.3.6.22l2.39-.96c.49.4 1.04.72 1.63.95l.36 2.54c.04.24.25.42.49.42h3.84c.24 0 .45-.18.49-.42l.36-2.54c.59-.23 1.14-.55 1.63-.95l2.39.96c.24.09.48-.01.6-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.02-1.58ZM12 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7Z' })
    ));
  }

  function NumPad(props) {
    return h('main', { className: 'workspace' },
      h('div', { className: 'console-layout' },
        h('section', { className: 'numpad-case', 'aria-label': 'Виртуальная клавиатура Numpad' },
          h('div', { className: 'numpad-grid' }, KEY_LAYOUT.map(function (entry) {
            var foundKey = props.keys.find(function (candidate) { return candidate.id === entry.id; });
            var key = Object.assign({}, foundKey, { cls: entry.cls });
            var name = props.bindings[entry.id];
            var item = name ? props.findItem(name) : null;
            return h(Key, {
              key: entry.id, keyInfo: key, item: item,
              active: props.activeKey === entry.id,
              pressed: !!(props.pressedKeys && props.pressedKeys[entry.id]),
              onChoose: props.onChoose
            });
          }))
        ),
        h(SettingsGear, { onClick: props.onSettings })
      )
    );
  }

  window.HD2UI = window.HD2UI || {};
  window.HD2UI.NumPad = NumPad;
})();
