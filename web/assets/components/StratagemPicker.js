(function () {
  'use strict';
  var h = React.createElement;
  var PRIORITY = ['По умолчанию', 'Стратагемы заданий', 'Оружие поддержки', 'Орбитальные и авиаудары', 'Оборонительные установки', 'Рюкзаки', 'Техника'];
  var LABELS = {
    'По умолчанию': 'Основные',
    'Стратагемы заданий': 'Задания',
    'Оружие поддержки': 'Оружие поддержки',
    'Орбитальные и авиаудары': 'Орбита и авиация',
    'Оборонительные установки': 'Оборона',
    'Рюкзаки': 'Рюкзаки',
    'Техника': 'Техника'
  };

  // A single body-level tooltip avoids clipping by the scrollable icon grid.
  var hoverDescriptionTimer = null;
  var hoverDescriptionTarget = null;
  var hoverDescriptionNode = null;

  function clearHoverDescription(target) {
    if (target && hoverDescriptionTarget && target !== hoverDescriptionTarget) return;
    if (hoverDescriptionTimer) {
      clearTimeout(hoverDescriptionTimer);
      hoverDescriptionTimer = null;
    }
    if (hoverDescriptionNode && hoverDescriptionNode.parentNode) {
      hoverDescriptionNode.parentNode.removeChild(hoverDescriptionNode);
    }
    hoverDescriptionNode = null;
    hoverDescriptionTarget = null;
  }

  function scheduleHoverDescription(event, item) {
    var target = event.currentTarget;
    clearHoverDescription();
    hoverDescriptionTarget = target;
    hoverDescriptionTimer = setTimeout(function () {
      hoverDescriptionTimer = null;
      if (!target || !target.isConnected || hoverDescriptionTarget !== target) return;

      var tooltip = document.createElement('div');
      tooltip.className = 'picker-hover-description';
      tooltip.setAttribute('role', 'tooltip');

      var name = document.createElement('strong');
      name.className = 'picker-hover-description-name';
      name.textContent = item.name;
      tooltip.appendChild(name);

      var arrows = document.createElement('span');
      arrows.className = 'picker-hover-description-arrows';
      String(item.arrows || '').split(/\s+/).filter(Boolean).forEach(function (arrow) {
        var token = document.createElement('i');
        token.textContent = arrow;
        arrows.appendChild(token);
      });
      if (arrows.childNodes.length) tooltip.appendChild(arrows);

      document.body.appendChild(tooltip);
      var rect = target.getBoundingClientRect();
      var size = tooltip.getBoundingClientRect();
      var margin = 8;
      var left = rect.left + rect.width / 2 - size.width / 2;
      left = Math.max(margin, Math.min(left, window.innerWidth - size.width - margin));
      var top = rect.top - size.height - 9;
      // If the tile is too close to the top edge, show the description directly below it.
      if (top < margin) top = Math.min(window.innerHeight - size.height - margin, rect.bottom + 9);
      tooltip.style.left = Math.round(left) + 'px';
      tooltip.style.top = Math.round(Math.max(margin, top)) + 'px';
      hoverDescriptionNode = tooltip;
      requestAnimationFrame(function () {
        if (hoverDescriptionNode === tooltip && tooltip.isConnected) tooltip.classList.add('is-visible');
      });
    }, 500);
  }

  function CloseIcon() {
    return h('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' },
      h('path', { d: 'M6 6l12 12M18 6L6 18', fill: 'none', stroke: 'currentColor', strokeWidth: '2', strokeLinecap: 'round' })
    );
  }

  function CheckIcon() {
    return h('svg', { viewBox: '0 0 20 20', 'aria-hidden': 'true' },
      h('path', { d: 'm4 10 4 4 8-9', fill: 'none', stroke: 'currentColor', strokeWidth: '2.2', strokeLinecap: 'round', strokeLinejoin: 'round' })
    );
  }

  function SearchIcon() {
    return h('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' },
      h('circle', { cx: '10.8', cy: '10.8', r: '6.5', fill: 'none', stroke: 'currentColor', strokeWidth: '1.8' }),
      h('path', { d: 'm16 16 4.5 4.5', fill: 'none', stroke: 'currentColor', strokeWidth: '1.8', strokeLinecap: 'round' })
    );
  }

  function SelectedStrip(props) {
    if (!props.items || !props.items.length) return null;
    return h('div', { className: 'picker-selected-strip', 'aria-label': 'Уже выбранные стратагемы' },
      props.items.map(function (entry) {
        return h('div', {
          key: entry.key.id,
          className: 'picker-selected-chip',
          'data-tooltip': entry.key.title + ' · ' + entry.item.name,
          'aria-label': entry.key.title + ': ' + entry.item.name
        }, h('img', { src: entry.item.icon_url, alt: '', loading: 'lazy', draggable: false,
          onError: function (event) { event.currentTarget.classList.add('icon-unavailable'); }
        }));
      })
    );
  }

  function StratagemPicker(props) {
    if (!props.open || !props.selectedKey) return null;
    var categories = PRIORITY.filter(function (cat) { return props.categories.indexOf(cat) !== -1; })
      .concat(props.categories.filter(function (cat) { return PRIORITY.indexOf(cat) === -1; }));

    var tabs = categories.map(function (category) {
      var categoryItems = props.catalog.filter(function (item) { return item.category === category; });
      var selectedCount = categoryItems.filter(function (item) {
        return props.keys.some(function (key) { return props.bindings[key.id] === item.name; });
      }).length;
      return h('button', {
        key: category, type: 'button',
        className: 'picker-category' + (props.activeCategory === category ? ' is-active' : ''),
        'aria-pressed': props.activeCategory === category,
        onClick: function () { clearHoverDescription(); props.onCategory(category); },
        title: LABELS[category] || category
      }, h('span', null, LABELS[category] || category),
      h('small', null, categoryItems.length),
      selectedCount ? h('i', { className: 'picker-category-selected', 'aria-label': 'Выбрано: ' + selectedCount }) : null);
    });

    var icons = props.results.map(function (item) {
      var assignedKeys = props.keys.filter(function (key) { return props.bindings[key.id] === item.name; });
      var assigned = assignedKeys.length > 0;
      var current = assignedKeys.some(function (key) { return key.id === props.selectedKey; });
      var assignedLabel = assignedKeys.map(function (key) { return key.title; }).join(', ');
      return h('button', {
        key: item.id, type: 'button',
        className: 'picker-icon-tile' + (assigned ? ' is-assigned' : '') + (current ? ' is-current-assignment' : ''),
        onClick: function () { clearHoverDescription(); props.onAssign(item.name); },
        onMouseEnter: function (event) { scheduleHoverDescription(event, item); },
        onMouseLeave: function (event) { clearHoverDescription(event.currentTarget); },
        onFocus: function (event) { scheduleHoverDescription(event, item); },
        onBlur: function (event) { clearHoverDescription(event.currentTarget); },
        'aria-label': item.name + (assignedLabel ? ', уже назначена на ' + assignedLabel : '')
      }, h('img', { src: item.icon_url, alt: '', loading: 'lazy', draggable: false,
        onError: function (event) { event.currentTarget.classList.add('icon-unavailable'); }
      }), assigned ? h('span', { className: 'picker-selected-mark' }, h(CheckIcon)) : null);
    });

    return h('div', { className: 'picker-backdrop', onMouseDown: function (event) { if (event.target === event.currentTarget) { clearHoverDescription(); props.onClose(); } } },
      h('section', { className: 'picker-dialog', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Выбор стратагемы' },
        h('header', { className: 'picker-toolbar' },
          h('nav', { className: 'picker-categories', 'aria-label': 'Типы стратагем' }, tabs),
          h('button', { type: 'button', className: 'picker-close', onClick: function () { clearHoverDescription(); props.onClose(); }, 'aria-label': 'Закрыть выбор' }, h(CloseIcon))
        ),
        h('label', { className: 'picker-search' },
          h(SearchIcon),
          h('input', { type: 'search', value: props.search || '', onChange: function (event) { clearHoverDescription(); props.onSearch(event); }, placeholder: 'Поиск в выбранной категории…', 'aria-label': 'Поиск стратагем' }),
          props.search ? h('button', { type: 'button', onClick: function () { clearHoverDescription(); props.onSearch({ target: { value: '' } }); }, 'aria-label': 'Очистить поиск' }, '×') : null
        ),
        h(SelectedStrip, { items: props.selectedItems || [] }),
        h('div', { className: 'picker-icon-grid', 'aria-label': 'Стратагемы выбранной категории', onScroll: function () { clearHoverDescription(); } },
          icons.length ? icons : h('div', { className: 'picker-empty' }, 'В этой категории пока нет стратагем.')
        ),
        props.currentAssignment ? h('button', {
          type: 'button', className: 'picker-clear', onClick: props.onClearAssignment,
          title: 'Убрать назначение', 'aria-label': 'Убрать назначение'
        }, '×') : null
      )
    );
  }

  window.HD2UI = window.HD2UI || {};
  window.HD2UI.StratagemPicker = StratagemPicker;
})();
