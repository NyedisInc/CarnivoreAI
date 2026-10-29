// Keep Mac Awake

'use strict';

const side = require('../side-state');
const trayAutomations = require('../../tray-automations');
const { openApp } = require('./app');

const BEAST_GRID_HASH = '#plugins/beastmode/settings';

async function write(ctx, w) {
  const api = ctx.data.api();
  if (!api) {
    ctx.dialog.showErrorBox(`Carnivore: could not ${w.what}`, 'The server is not running or its port failed the ownership check.');
    return null;
  }
  const result = await api.sendAuthed(w.route, w.body, w.method);
  if (!result.reachable) {
    const missing = result.status === 404 || result.status === 405 || (w.routeKey === 'logLevelExpiry' && result.status === 422);
    if (missing && w.routeKey) ctx.data.markRoute(w.routeKey, 'missing');
    ctx.dialog.showErrorBox(`Carnivore: could not ${w.what}`, missing
      ? 'This server is older than the menu bar app and does not have this switch yet. Update the server.'
      : `The server refused: ${result.error || 'unknown error'}`);
    return null;
  }
  return result.data;
}

function standDownReport(result) {
  const body = (result && (result.data || result.body)) || {};
  const failed = Array.isArray(body.failed) ? body.failed.filter((s) => typeof s === 'string') : [];
  const status = result && result.status;
  const done = [body.beast_off && 'Beast Mode is off.', body.swarm_off && 'The Swarm is off.',
    body.scheduler_paused && 'The scheduler is paused.'].filter(Boolean);
  const ok2xx = Number.isInteger(status) && status >= 200 && status < 300;
  if (!ok2xx || failed.length) {
    const lines = [...done];
    if (failed.length) lines.push(`These steps failed: ${failed.join(', ')}.`);
    else lines.push(`The server answered ${status ? `HTTP ${status}` : 'nothing'}${result && result.error ? ` (${result.error})` : ''}.`);
    return { ok: false, type: 'warning', message: 'Stand Down did not finish.', detail: `${lines.join('\n')}\nAlerts are unchanged.` };
  }
  return { ok: true, type: 'info', message: 'Carnivore stood down.',
    detail: `${done.join('\n') || 'Everything was already off.'}\nAlerts are unchanged.` };
}

function handlers(ctx) {
  const after = async (promise) => {
    await promise;
    await ctx.data.refreshSide();
    ctx.refresh();
  };
  return {
    'autonomy.keep_awake': (a) => after(write(ctx, { route: side.ROUTES.keepAwake, body: { always: Boolean(a.always) }, method: 'PUT',
      what: 'change Keep Mac Awake', routeKey: 'keepAwake' })),
    'autonomy.beast_off': () => after(write(ctx, { route: side.ROUTES.beast, body: { enabled: false }, method: 'PUT', what: 'turn Beast Mode off' })),
    'autonomy.beast_open': () => openApp(ctx, BEAST_GRID_HASH),
    'autonomy.swarm': (a) => after(write(ctx, { route: side.ROUTES.swarm, body: { enabled: Boolean(a.enabled) }, method: 'PUT',
      what: a.enabled ? 'turn the Swarm on' : 'turn the Swarm off' })),
    'autonomy.scheduler': (a) => after((async () => {
      const api = ctx.data.api();
      const result = api ? await trayAutomations.setSchedulerPaused(api, a.paused) : { ok: false, error: 'the server is not reachable' };
      if (!result.ok) {
        ctx.dialog.showErrorBox('Carnivore: could not change the scheduler',
          `The automation scheduler could not be ${a.paused ? 'paused' : 'resumed'}: ${result.error || 'unknown error'}`);
      }
    })()),
    'autonomy.stand_down': () => after((async () => {
      const api = ctx.data.api();
      if (!api) {
        ctx.dialog.showErrorBox('Carnivore: could not stand down', 'The server is not running or its port failed the ownership check.');
        return;
      }
      const result = await api.sendAuthed(side.ROUTES.standDown, {}, 'POST');
      if (result.status === 404 || result.status === 405) {
        ctx.data.markRoute('standDown', 'missing');
        ctx.dialog.showErrorBox('Carnivore: could not stand down', 'This server is older than the menu bar app and does not have Stand Down yet. Update the server.');
        return;
      }
      const report = standDownReport(result);
      ctx.dialog.showMessageBox({ type: report.type, title: 'Stand Down', message: report.message, detail: report.detail, buttons: ['OK'] });
    })()),
    'debug.log_level': (a) => after(write(ctx, { route: side.ROUTES.logLevel, body: side.logLevelBody(a.level), method: 'PUT',
      what: `set the log level to ${a.level}`, routeKey: a.level === 'debug' ? 'logLevelExpiry' : undefined })),
  };
}

module.exports = { BEAST_GRID_HASH, write, standDownReport, handlers };
