(function () {
  'use strict';
  var h = React.createElement;
  var DIRECTION_GLYPHS = { U: '↑', D: '↓', L: '←', R: '→' };

  function CloseIcon() {
    return h('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' },
      h('path', { d: 'M6 6l12 12M18 6L6 18', fill: 'none', stroke: 'currentColor', strokeWidth: '2', strokeLinecap: 'round' })
    );
  }

  function SettingsDialog(props) {
    if (!props.open || !props.draft) return null;
    var d = props.draft;
    function directionField(direction) {
      var options = [['UP','↑'],['DOWN','↓'],['LEFT','←'],['RIGHT','→'],['W','W'],['A','A'],['S','S'],['D','D']];
      return h('label', { className: 'settings-field settings-direction-field', key: direction, 'aria-label': 'Клавиша направления ' + DIRECTION_GLYPHS[direction] },
        h('span', { className: 'settings-direction-glyph', 'aria-hidden': 'true' }, DIRECTION_GLYPHS[direction]),
        h('select', { value: d.direction_keys[direction], onChange: function (e) { props.onDirection(direction, e.target.value); }, 'aria-label': 'Клавиша ' + DIRECTION_GLYPHS[direction] },
          options.map(function (option) { return h('option', { key: option[0], value: option[0] }, option[1]); })
        )
      );
    }
    function numberField(field, label, min, max) {
      return h('label', { className: 'settings-field', key: field },
        h('span', null, label),
        h('input', { type: 'number', min: min, max: max, step: 5, value: d[field], onChange: function (e) { props.onDraft(field, e.target.value); } }),
        h('small', null, min + '–' + max + ' мс')
      );
    }
    return h('div', { className: 'dialog-backdrop settings-backdrop', onMouseDown: function (e) { if (e.target === e.currentTarget) props.onClose(); } },
      h('form', { className: 'settings-dialog', onSubmit: props.onSubmit, role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Настройки макросов' },
        h('header', { className: 'dialog-heading' },
          h('button', { type: 'button', className: 'dialog-close', onClick: props.onClose, 'aria-label': 'Закрыть настройки' }, h(CloseIcon))
        ),
        h('div', { className: 'settings-body' },
          h('section', { className: 'settings-section' },
            h('div', { className: 'settings-section-title' }, 'УПРАВЛЕНИЕ В ИГРЕ'),
            h('div', { className: 'settings-grid settings-grid-controls' },
              h('label', { className: 'settings-field' },
                h('span', null, 'Клавиша открытия меню'),
                h('select', { value: d.open_key, onChange: function (e) { props.onDraft('open_key', e.target.value); } },
                  h('option', { value: 'CTRL' }, 'CTRL'), h('option', { value: 'ALT' }, 'ALT'), h('option', { value: 'SHIFT' }, 'SHIFT')
                )
              ),
              directionField('U'), directionField('D'), directionField('L'), directionField('R')
            )
          ),
          h('section', { className: 'settings-section' },
            h('div', { className: 'settings-section-title' }, 'СКОРОСТЬ ВВОДА'),
            h('div', { className: 'settings-grid settings-grid-timing' },
              numberField('press_ms', 'Длительность нажатия', 25, 250),
              numberField('gap_ms', 'Пауза между клавишами', 20, 300),
              numberField('open_hold_ms', 'Удержание меню', 50, 500)
            )
          )
        ),
        h('footer', { className: 'dialog-actions' },
          h('button', { type: 'submit', className: 'primary-button', disabled: props.saving }, props.saving ? 'СОХРАНЕНИЕ…' : 'СОХРАНИТЬ')
        )
      )
    );
  }
  window.HD2UI = window.HD2UI || {};
  window.HD2UI.SettingsDialog = SettingsDialog;
})();
