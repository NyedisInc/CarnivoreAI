
'use strict';

function portUnknown(ctx) {
  ctx.dialog.showErrorBox('Carnivore: unknown server port',
    'Could not determine the configured port from .env (PORT= is set but not a valid port number). Fix .env and restart Carnivore.');
}

function openApp(ctx, hash) {
  if (!ctx.appWindow.open(hash || undefined)) portUnknown(ctx);
}

/* nothing at all something else */
function openSetupWizard(ctx) {
  const sm = ctx.serverManager;
  const base = sm.getPublishedUrl();
  if (!base) {
    portUnknown(ctx);
    return;
  }
  if (sm.getSetupVerdict().status === 'incomplete' && ctx.appWindow.open()) {
    ctx.rebindAfterPair.startWatch(ctx.rebindDeps());
    return;
  }
  if (sm.getState() !== 'running') {
    ctx.dialog.showMessageBox({
      type: 'info', title: 'Server not running', message: 'The setup page is served by the Carnivore server.',
      detail: 'Start the server from this menu, then open Setup and Config again.', buttons: ['OK'],
    });
    return;
  }
  ctx.shell.openExternal(`${base}/setup`);
}

function openWebAccount(ctx) {
  const sm = ctx.serverManager;
  const base = sm.getPublishedUrl();
  if (!base) {
    portUnknown(ctx);
    return;
  }
  if (sm.getState() !== 'running') {
    ctx.dialog.showMessageBox({ type: 'info', title: 'Server not running', message: 'The account page is served by the Carnivore server.',
      detail: 'Start the server from this menu, then open the account page again.', buttons: ['OK'] });
    return;
  }
  ctx.shell.openExternal(`${base}/#account`);
}

function handlers(ctx) {
  return {
    'app.open': (a) => openApp(ctx, a.hash),
    'app.browser': () => {
      const url = ctx.serverManager.getPublishedUrl();
      if (!url) portUnknown(ctx);
      else ctx.shell.openExternal(url);
    },
    'app.about': () => ctx.showAbout(),
    'app.account': () => openWebAccount(ctx),
    'app.quit': () => {
      console.log('Quit requested from the menu.');
      ctx.app.quit();
    },
    'app.quit_stop': () => {
      console.log('Quit and stop engine requested from the menu.');
      ctx.setQuitIntent('engine');
      ctx.app.quit();
    },
    'update.install': () => { Promise.resolve(ctx.autoUpdate.install()).then((ok) => { if (!ok) ctx.autoUpdate.check(); }); },
    'update.check': () => {
      if (ctx.autoUpdate.getState().state === 'ready') ctx.autoUpdate.install();
      else ctx.autoUpdate.check();
    },
    'setup.finish': () => {
      ctx.appWindow.open();
      ctx.rebindAfterPair.startWatch(ctx.rebindDeps());
    },
    'setup.wizard': () => openSetupWizard(ctx),
  };
}

module.exports = { portUnknown, openApp, openSetupWizard, openWebAccount, handlers };
