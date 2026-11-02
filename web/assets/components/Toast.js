(function () {
  'use strict';
  var h = React.createElement;
  function Toast(props) {
    if (!props.toast) return null;
    return h('div', { className: 'toast' + (props.toast.error ? ' is-error' : ''), role: 'status' },
      h('b', null, props.toast.error ? '!' : '✓'), props.toast.message
    );
  }
  window.HD2UI = window.HD2UI || {};
  window.HD2UI.Toast = Toast;
})();
