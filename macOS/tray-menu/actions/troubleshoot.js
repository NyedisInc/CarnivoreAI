// Copy Diagnostics
// Copy Diagnostics

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

/* CARNIVORE_STATE_DIR CLOUDE_STATE_DIR */
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
    ctx.dialog.showErrorBox('Carnivore will not stop that process', refusal);
    return;
  }
  const answer = await ctx.dialog.showMessageBox({
    type: 'warning', title: 'Stop the process holding the port?', message: `Stop PID ${holder.pid} (${holder.name})?`,
    detail: `It is listening on port ${port}, so the Carnivore server cannot start.\n\nExecutable: ${holder.exe}\n`
      + `Owner: uid ${holder.uid} (you)\nStarted: ${holder.start}\n\nIt gets SIGTERM, then SIGKILL after a few seconds.`,
    buttons: ['Leave It Running', `Stop PID ${holder.pid}`], defaultId: 0, cancelId: 0,
  });
  if (answer.response !== 1) return;
  const outcome = await portTrust.killHolder(port, holder, deps);
  ctx.dialog.showMessageBox({ type: outcome.stopped ? 'info' : 'warning', title: 'Kill Port Holder',
    message: outcome.stopped ? 'The port holder was stopped.' : 'Nothing was stopped.', detail: outcome.detail, buttons: ['OK'] });
  ctx.refresh();
}

async function reinstallEnv(ctx) {
  const sm = ctx.serverManager;
  if (sm.getState() !== 'stopped' || sm.isProcessRunning()) {
    ctx.dialog.showErrorBox('Stop the server first', `The server is running${sm.processPid ? ` (PID ${sm.processPid})` : ''}; `
      + 'stop it from Server & Troubleshoot, then reinstall its environment.');
    return;
  }
  if (sm.payload) {
    await ctx.dialog.showMessageBox({ type: 'info', title: 'Nothing to reinstall', message: 'This install has no Python environment to rebuild.',
      detail: 'The server runs on the Python that ships inside the app. Reinstall or update the app to repair it.', buttons: ['OK'] });
    return;
  }
  const venv = path.join(sm.baseDir, 'venv');
  const aside = `${venv}.replaced-${Date.now()}`;
  const answer = await ctx.dialog.showMessageBox({
    type: 'warning', title: 'Reinstall the server environment?', message: 'Rebuild the server\'s Python environment?',
    detail: `The current one is moved aside, not deleted:\n${aside}\n\nA new one is created and its packages installed `
      + '(one to two minutes, needs the network), then the server starts. No server process is running.',
    buttons: ['Cancel', 'Reinstall'], defaultId: 0, cancelId: 0,
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
        ctx.dialog.showErrorBox('Carnivore: no server log', `There is no server log at ${sm.logFile} yet.`);
        return;
      }
      ctx.execFile('/usr/bin/open', ['-a', 'Console', sm.logFile], (error) => {
        if (error) ctx.dialog.showErrorBox('Carnivore: Console would not open the log', error.message);
      });
    },
    'server.reveal_logs': () => ctx.shell.openPath(path.dirname(sm.logFile)),
    'debug.reveal_state': () => ctx.shell.openPath(stateDir()),
    'server.copy_diagnostics': async () => {
      const read = await readDiagnostics(ctx);
      if (!read.text) {
        ctx.dialog.showErrorBox('Carnivore: no diagnostics', `Diagnostics could not be collected: ${read.error}`);
        return;
      }
      const more = read.text.length > PREVIEW_CHARS ? `\n\n... ${read.text.length - PREVIEW_CHARS} more characters` : '';
      const answer = await ctx.dialog.showMessageBox({ type: 'info', title: 'Copy Diagnostics',
        message: 'Copy these diagnostics? Secrets are redacted.', detail: read.text.slice(0, PREVIEW_CHARS) + more,
        buttons: ['Cancel', 'Copy'], defaultId: 1, cancelId: 0 });
      if (answer.response === 1) ctx.clipboard.writeText(read.text);
    },
    // Copy Diagnostics
    'server.export_diagnostics': () => {
      const userData = ctx.app.getPath('userData');
      return createExport({ readDiagnostics: () => readDiagnostics(ctx), dialog: ctx.dialog, shell: ctx.shell, fs: ctx.fs, t: ctx.t,
        version: ctx.app.getVersion(), dumpsDir: path.join(userData, 'crash-dumps'), crashLog: path.join(userData, 'logs', 'crash-events.log'),
        home: os.homedir(), downloadsDir: ctx.app.getPath('downloads') }).run();
    },
    'server.check_health': async () => {
      const health = await sm.getHealth();
      ctx.dialog.showMessageBox({ type: health ? 'info' : 'warning', title: 'Check Health Now',
        message: health ? 'The server answered its health check.' : 'The server did not answer its health check.',
        detail: health ? `status ${health.status}, version ${health.version}, up ${health.uptime} s` : `Nothing answered on port ${sm.getPort()}.`,
        buttons: ['OK'] });
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
      else ctx.dialog.showMessageBox({ type: 'info', title: 'Newest Crash Report', message: 'No Carnivore crash reports.', buttons: ['OK'] });
    },
  };
}

module.exports = { DEBUG_BOOT_ENV, PREVIEW_CHARS, withEnv, stateDir, readDiagnostics, newestCrashReport, killPortHolder, reinstallEnv, handlers };
