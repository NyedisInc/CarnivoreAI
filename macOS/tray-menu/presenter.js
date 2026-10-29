
'use strict';

const { degradeItems } = require('./capabilities');

const LINUX_DEBOUNCE_MS = 400;

function toTemplate(items, dispatch, iconFor, namedIcon) {
  return items.map((item) => {
    if (item.type === 'separator') return { type: 'separator' };
    const out = { label: item.label, enabled: item.enabled !== false };
    if (item.type === 'header' || item.type === 'checkbox' || item.type === 'radio') out.type = item.type;
    for (const key of ['sublabel', 'toolTip', 'accelerator', 'badge', 'checked']) {
      if (item[key] !== undefined) out[key] = item[key];
    }
    if (item.led && iconFor) {
      const icon = iconFor(item.led);
      if (icon) out.icon = icon;
    }
    if (item.icon && namedIcon) {
      const icon = namedIcon(item.icon);
      if (icon) out.icon = icon;
    }
    if (item.submenu) out.submenu = toTemplate(item.submenu, dispatch, iconFor, namedIcon);
    else if (item.action) out.click = () => dispatch(item.action);
    return out;
  });
}

function createDarwinPresenter(deps) {
  const build = (optionKey) => deps.Menu.buildFromTemplate(
    toTemplate(degradeItems(deps.buildItems({ optionKey }), deps.caps), deps.dispatch, deps.iconFor, deps.namedIcon));
  const show = (optionKey) => {
    deps.tray.popUpContextMenu(build(Boolean(optionKey)));
    if (deps.onOpen) deps.onOpen();
  };
  deps.tray.setIgnoreDoubleClickEvents(true);
  deps.tray.on('click', (event) => show(event && event.altKey));
  deps.tray.on('right-click', (event) => show(event && event.altKey));
  return {
    show,
    refresh() {},
    menuForDock: () => build(false),
  };
}

function createLinuxPresenter(deps) {
  const timers = deps.timers || { setTimeout, clearTimeout };
  let open = false;
  let dirty = false;
  let timer = null;
  let current = null;
  const apply = () => {
    timer = null;
    if (open) {
      dirty = true;
      return;
    }
    dirty = false;
    current = deps.Menu.buildFromTemplate(toTemplate(degradeItems(deps.buildItems({ optionKey: false }), deps.caps), deps.dispatch, deps.iconFor));
    current.on('menu-will-show', () => { open = true; });
    current.on('menu-will-close', () => {
      open = false;
      if (dirty) apply();
    });
    deps.tray.setContextMenu(current);
  };
  apply();
  return {
    show() {},
    refresh() {
      if (timer) timers.clearTimeout(timer);
      timer = timers.setTimeout(apply, LINUX_DEBOUNCE_MS);
    },
    menuForDock: () => current,
  };
}

function createPresenter(platform, deps) {
  return platform === 'darwin' ? createDarwinPresenter(deps) : createLinuxPresenter(deps);
}

module.exports = { LINUX_DEBOUNCE_MS, toTemplate, createDarwinPresenter, createLinuxPresenter, createPresenter };
