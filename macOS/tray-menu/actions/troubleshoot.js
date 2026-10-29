
'use strict';

const os = require('os');
const path = require('path');
const portTrust = require('../port-trust');
const side = require('../side-state');
const { pycacheEnv } = require('../../engine/payload-select');
const { createExport } = require('../../diagnostics/export');

const DEBUG_BOOT_ENV = 'CARNIVORE_DEBUG_BOOT';

const PREVIEW_CHARS = 1500;
const CRASH_NAME = /^(Carnivore|Electron|Python|python3)[^/]*\.(ips|crash)$/;

function stateDir() {
  return process.env.CARNIVORE_STATE_DIR || process.env.CLOUDE_STATE_DIR
    || path.join(os.homedir(), 'Library', 'Application Support', 'Carnivore');
}

async function readDiagnostics(ctx) {
  const api = ctx.data.api();
  if (api) {
    const result = await api.getAuthed(side.ROUTES.diagnostics);
    if (result.reachable) return { text: JSON.stringify(result.data, null, 2), error: null };
    if (result.status === 404) ctx.data.markRoute('diagnostics', 'missing');
  }
  const serverDir = ctx.serverManager.baseDir;
  const python = ctx.serverManager.payload ? ctx.serverManager.payload.python : path.join(serverDir, 'venv', 'bin', 'python3');
  const env = ctx.serverManager.payload ? { ...process.env, ...pycacheEnv() } : undefined;
  return new Promise((resolve) => {
    ctx.execFile(python, ['-m', 'src.core.diagnostics'], { cwd: serverDir, env, timeout: 30000, maxBuffer: 8 * 1024 * 1024 },
      (error, stdout) => {
        if (error) resolve({ text: null, error: error.code === 'ENOENT' ? 'this install has no diagnostics module yet' : error.message });
        else resolve({ text: String(stdout || ''), error: null });
      });
  });
}

function newestCrashReport(ctx) {
  const dir = path.join(os.homedir(), 'Library', 'Logs', 'DiagnosticReports');
  let names;
  try {
    names = ctx.fs.readdirSync(dir).filter((n) => CRASH_NAME.test(n));
  } catch (error) {
    // there is nothing
    return null;
  }
  const dated = names.map((n) => ({ n, at: ctx.fs.statSync(path.join(dir, n)).mtimeMs })).sort((a, b) => b.at - a.at);
  return dated.length ? path.join(dir, dated[0].n) : null;
}

async function withEnv(env, key, value, fn) {
  const had = Object.prototype.hasOwnProperty.call(env, key);
  const before = env[key];
  env[key] = value;
  try {
    await fn();
  } finally {
    if (had) env[key] = before;
    else delete env[key];
  }
}

async function killPortHolder(ctx) {
  const deps = ctx.portDeps();
  const port = ctx.serverManager.getPort();
  const holder = await portTrust.identifyHolder(port, deps);
  const refusal = portTrust.killRefusal(holder, deps);
  if (refusal) {
    ctx.dialog.showErrorBox(ctx.t('menubar.dialog.port.refuse_title'), refusal);
    return;
  }
  const answer = await ctx.dialog.showMessageBox({
    type: 'warning', title: ctx.t('menubar.dialog.port.confirm_title'),
    message: ctx.t('menubar.dialog.port.confirm_message', { pid: holder.pid, name: holder.name }),
    detail: ctx.t('menubar.dialog.port.confirm_detail', { port, exe: holder.exe, uid: holder.uid, start: holder.start }),
    buttons: [ctx.t('menubar.dialog.port.leave'), ctx.t('menubar.dialog.port.stop', { pid: holder.pid })], defaultId: 0, cancelId: 0,
  });
  if (answer.response !== 1) return;
  const outcome = await portTrust.killHolder(port, holder, deps);
  ctx.dialog.showMessageBox({ type: outcome.stopped ? 'info' : 'warning', title: ctx.t('menubar.dialog.port.done_title'),
    message: ctx.t(outcome.stopped ? 'menubar.dialog.port.stopped' : 'menubar.dialog.port.not_stopped'),
    detail: outcome.detail, buttons: [ctx.t('menubar.dialog.ok')] });
  ctx.refresh();
}

async function reinstallEnv(ctx) {
  const sm = ctx.serverManager;
  if (sm.getState() !== 'stopped' || sm.isProcessRunning()) {
    ctx.dialog.showErrorBox(ctx.t('menubar.dialog.env.stop_first_title'), sm.processPid
      ? ctx.t('menubar.dialog.env.stop_first_detail_pid', { pid: sm.processPid })
      : ctx.t('menubar.dialog.env.stop_first_detail'));
    return;
  }
  if (sm.payload) {
    await ctx.dialog.showMessageBox({ type: 'info', title: ctx.t('menubar.dialog.env.payload_title'),
      message: ctx.t('menubar.dialog.env.payload_message'), detail: ctx.t('menubar.dialog.env.payload_detail'),
      buttons: [ctx.t('menubar.dialog.ok')] });
    return;
  }
  const venv = path.join(sm.baseDir, 'venv');
  const aside = `${venv}.replaced-${Date.now()}`;
  const answer = await ctx.dialog.showMessageBox({
    type: 'warning', title: ctx.t('menubar.dialog.env.confirm_title'), message: ctx.t('menubar.dialog.env.confirm_message'),
    detail: ctx.t('menubar.dialog.env.confirm_detail', { aside }),
    buttons: [ctx.t('menubar.dialog.cancel'), ctx.t('menubar.dialog.env.confirm_go')], defaultId: 0, cancelId: 0,
  });
  if (answer.response !== 1) return;
  try {
    if (ctx.fs.existsSync(venv)) ctx.fs.renameSync(venv, aside);
    sm.pythonPath = sm.findPython();
    sm.resetSupervisor();
    await sm.start();
  } catch (err) {
    await ctx.reportStartFailure(err);
  }
  ctx.refresh();
}

function handlers(ctx) {
  const sm = ctx.serverManager;
  return {
    'server.console_log': () => {
      if (!ctx.fs.existsSync(sm.logFile)) {
        ctx.dialog.showErrorBox(ctx.t('menubar.dialog.log.missing_title'), ctx.t('menubar.dialog.log.missing_detail', { path: sm.logFile }));
        return;
      }
      ctx.execFile('/usr/bin/open', ['-a', 'Console', sm.logFile], (error) => {
        if (error) ctx.dialog.showErrorBox(ctx.t('menubar.dialog.log.console_failed'), error.message);
      });
    },
    'server.reveal_logs': () => ctx.shell.openPath(path.dirname(sm.logFile)),
    'debug.reveal_state': () => ctx.shell.openPath(stateDir()),
    'server.copy_diagnostics': async () => {
      const read = await readDiagnostics(ctx);
      if (!read.text) {
        ctx.dialog.showErrorBox(ctx.t('menubar.dialog.diag.none_title'), ctx.t('menubar.dialog.diag.none_detail', { error: read.error }));
        return;
      }
      const more = read.text.length > PREVIEW_CHARS ? ctx.t('menubar.dialog.diag.more', { count: read.text.length - PREVIEW_CHARS }) : '';
      const answer = await ctx.dialog.showMessageBox({ type: 'info', title: ctx.t('menubar.dialog.diag.copy_title'),
        message: ctx.t('menubar.dialog.diag.copy_message'), detail: read.text.slice(0, PREVIEW_CHARS) + more,
        buttons: [ctx.t('menubar.dialog.cancel'), ctx.t('menubar.dialog.diag.copy_go')], defaultId: 1, cancelId: 0 });
      if (answer.response === 1) ctx.clipboard.writeText(read.text);
    },
    'server.export_diagnostics': () => {
      const userData = ctx.app.getPath('userData');
      return createExport({ readDiagnostics: () => readDiagnostics(ctx), dialog: ctx.dialog, shell: ctx.shell, fs: ctx.fs, t: ctx.t,
        version: ctx.app.getVersion(), dumpsDir: path.join(userData, 'crash-dumps'), crashLog: path.join(userData, 'logs', 'crash-events.log'),
        home: os.homedir(), downloadsDir: ctx.app.getPath('downloads') }).run();
    },
    'server.check_health': async () => {
      const health = await sm.getHealth();
      ctx.dialog.showMessageBox({ type: health ? 'info' : 'warning', title: ctx.t('menubar.dialog.health.title'),
        message: ctx.t(health ? 'menubar.dialog.health.answered' : 'menubar.dialog.health.silent'),
        detail: health
          ? ctx.t('menubar.dialog.health.answered_detail', { status: health.status, version: health.version, uptime: health.uptime })
          : ctx.t('menubar.dialog.health.silent_detail', { port: sm.getPort() }),
        buttons: [ctx.t('menubar.dialog.ok')] });
      ctx.refresh();
    },
    'server.start_debug': async () => {
      try {
        await withEnv(ctx.env || process.env, DEBUG_BOOT_ENV, '1', async () => {
          sm.resetSupervisor();
          await sm.start();
        });
      } catch (err) {
        await ctx.reportStartFailure(err);
      }
      ctx.refresh();
    },
    'server.kill_port_holder': () => killPortHolder(ctx),
    'server.reinstall_env': () => reinstallEnv(ctx),
    'server.crash_report': () => {
      const report = newestCrashReport(ctx);
      if (report) ctx.shell.showItemInFolder(report);
      else ctx.dialog.showMessageBox({ type: 'info', title: ctx.t('menubar.dialog.crash.title'), message: ctx.t('menubar.dialog.crash.none'), buttons: [ctx.t('menubar.dialog.ok')] });
    },
  };
}

module.exports = { DEBUG_BOOT_ENV, PREVIEW_CHARS, withEnv, stateDir, readDiagnostics, newestCrashReport, killPortHolder, reinstallEnv, handlers };
