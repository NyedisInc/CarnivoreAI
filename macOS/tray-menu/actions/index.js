
'use strict';

const MODULES = [require('./app'), require('./sessions'), require('./phone'), require('./autonomy'), require('./server'),
  require('./troubleshoot'), require('./uninstall')];

function allHandlers(ctx) {
  const out = {};
  for (const mod of MODULES) {
    for (const [kind, fn] of Object.entries(mod.handlers(ctx))) {
      if (out[kind]) throw new Error(`tray action ${kind} is handled twice`);
      out[kind] = fn;
    }
  }
  return out;
}

function createDispatcher(ctx) {
  const table = allHandlers(ctx);
  return function dispatch(action) {
    const fn = action && table[action.kind];
    if (!fn) {
      console.error('[tray-menu] no handler for action', action && action.kind);
      ctx.dialog.showErrorBox('Carnivore: menu item did nothing', `No handler for ${action && action.kind}.`);
      return;
    }
    Promise.resolve()
      .then(() => fn(action))
      .catch((error) => {
        console.error('[tray-menu] action failed', action.kind, error);
        ctx.dialog.showErrorBox('Carnivore: menu action failed', String((error && error.message) || error));
      });
  };
}

module.exports = { allHandlers, createDispatcher };
