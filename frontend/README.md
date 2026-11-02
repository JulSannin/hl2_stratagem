# HD2 Stratagem LAN UI 0.20.0

React UMD UI is split into reusable components and modular stylesheets:

- `src/components/NumPad.js` and `src/styles/numpad.css` — physical keypad layout and feedback.
- `src/components/StratagemPicker.js` and `src/styles/picker.css` — floating stratagem chooser, category grid, selected icon overview and delayed hover labels.
- `src/components/SettingsDialog.js` and `src/styles/dialogs.css` — responsive settings modal.
- `src/components/Toast.js` and `src/styles/core.css` — common notifications and design tokens.
- `src/App.js` — API state owner and physical-key WebSocket client.

The FastAPI server serves vendored React runtime files and static components from `web/assets`; Node.js/npm are not required on the gaming PC. Keep matching copies in `frontend/src` and `web/assets`.


Multi-client synchronization is handled in `src/App.js`: the WebSocket receives the initial canonical config and subsequent `config_updated` / `settings_updated` packets. Every PUT carries a config revision; on HTTP 409, independent local edits are merged onto the server snapshot and retried a bounded number of times. Local-only UI state such as open dialogs, search text and selected category is intentionally not synchronized.



## Reliability review 0.19.0
- Low-level hook consumes auto-repeat keydown events while a mapped key is held, without retriggering macros.
- Macro settings are snapshotted at trigger time.
- WebSocket broadcast writes are serialized and fan out concurrently.
- Cross-origin WebSocket connections are rejected.
- Failed config file writes roll back memory state and revision.


## Optimization & reliability review 0.20.0
- Canonical WebSocket handshake is serialized with broadcasts; clients receive `ready` before deltas.
- Slow sockets are evicted after a bounded send timeout.
- Config saves use monotonic revisions, bounded retries and stale-state protection.
- Runtime source copies in `src/` and served `web/assets/` must remain byte-identical.
- React runtime is still the legacy React 16 UMD bundle; a future migration to React 19 should replace the script-global runtime and bootstrapping together, not just update package.json.
