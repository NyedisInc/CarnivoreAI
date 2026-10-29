
'use strict';

const os = require('os');
const path = require('path');
const childProcess = require('child_process');
const confirmWindow = require('../../nuke-confirm');
const { UNREGISTER_ARG } = require('../../engine-host/constants');
const { resolvePayload } = require('../../engine/payload-select');

const UNREGISTER_TIMEOUT_MS = 30000;

const NUKE_LOG_FILE = path.join(os.tmpdir(), 'cloudecode-nuke.log');

const UNINSTALL_LOG_FILE = path.join(os.tmpdir(), 'carnivore-uninstall.log');

function uninstallScriptSource(ctx) {
  return ctx.app.isPackaged
    ? path.join(process.resourcesPath, 'uninstall.sh')
    : path.join(__dirname, '..', '..', '..', 'uninstall.sh');
}

function unregisterLoginService(ctx) {
  const execFile = ctx.execFile || childProcess.execFile;
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  return new Promise((resolve) => {
    execFile(process.execPath, [UNREGISTER_ARG], { timeout: UNREGISTER_TIMEOUT_MS, env }, (error) => resolve(!error));
  });
}

async function askStopSessions(ctx, copyDir) {
  const { response } = await ctx.dialog.showMessageBox({
    type: 'question', title: 'Uninstall Carnivore', buttons: ['keep sessions running', 'end sessions'], defaultId: 0, cancelId: 0,
    message: 'Also end your carnivore terminal sessions?', detail: 'Ending them stops any work running inside. Keeping them leaves them running without the app.',
  });
  if (response !== 1) return [];
  const payload = resolvePayload(process.resourcesPath);
  if (!payload) return ['--stop-tmux'];
  const copy = path.join(copyDir, 'tmux');
  ctx.fs.copyFileSync(payload.tmux, copy);
  ctx.fs.chmodSync(copy, 0o700);
  return ['--stop-tmux', '--tmux-bin', copy];
}

async function uninstallApp(ctx) {
  if (!(await confirmWindow.promptForUninstallConfirmation())) return;
  const source = uninstallScriptSource(ctx);
  if (!ctx.fs.existsSync(source)) {
    ctx.dialog.showErrorBox('Carnivore: uninstall failed', `The uninstall script is missing from this install:\n${source}`);
    return;
  }
  if (ctx.app.isPackaged && !(await unregisterLoginService(ctx))) {
    ctx.dialog.showErrorBox('Carnivore: uninstall stopped', 'Carnivore could not remove its login service, so nothing was uninstalled.\n\n'
      + 'Remove Carnivore in System Settings, General, Login Items & Extensions, then try again, or run the uninstall script from Terminal.');
    return;
  }
  const copyDir = ctx.fs.mkdtempSync(path.join(os.tmpdir(), 'carnivore-uninstall-'));
  const copy = path.join(copyDir, 'uninstall.sh');
  ctx.fs.copyFileSync(source, copy);
  ctx.fs.chmodSync(copy, 0o700);
  let extraArgs = [];
  if (ctx.app.isPackaged) {
    extraArgs = await askStopSessions(ctx, copyDir);
    const bundle = path.resolve(process.execPath, '..', '..', '..');
    if (bundle.endsWith('.app')) {
      try {
        await ctx.shell.trashItem(bundle);
      } catch (error) {
        console.error('[uninstall] could not move the app to the Trash:', error);
      }
    }
  }
  const env = { ...process.env };
  delete env.TMUX;
  delete env.TMUX_PANE;
  const log = ctx.fs.openSync(UNINSTALL_LOG_FILE, 'a');
  const spawn = ctx.spawn || childProcess.spawn;
  const child = spawn('/bin/bash', [copy, '--yes', ...extraArgs], { detached: true, stdio: ['ignore', log, log], env });
  child.unref();
  ctx.fs.closeSync(log);
}

async function nuke(ctx) {
  const confirmed = await confirmWindow.promptForNukeConfirmation('');
  if (!confirmed) return;
  console.log('Nuking system...');
  const sm = ctx.serverManager;
  await sm.stop();
  ctx.stopStatsPolling();

  const projectRoot = sm.getProjectRoot();
  const nukeScript = path.join(projectRoot, 'nuke.sh');
  const nukeFlags = ctx.app.isPackaged ? ['--skip-confirm', '--system'] : ['--skip-confirm'];
  const execFile = ctx.execFile || childProcess.execFile;
  const logStream = ctx.fs.createWriteStream(NUKE_LOG_FILE, { flags: 'a' });
  logStream.write(`\n\n=== Nuke started at ${new Date().toISOString()} ===\n`);
  logStream.write(`Script path: ${nukeScript}\nWorking directory: ${projectRoot}\nCommand: /bin/bash "${nukeScript}" ${nukeFlags.join(' ')}\n\n`);

  execFile('/bin/bash', [nukeScript, ...nukeFlags], { cwd: projectRoot, maxBuffer: 16 * 1024 * 1024 }, (error, stdout, stderr) => {
    logStream.write(`STDOUT:\n${stdout}\n\n`);
    if (stderr) logStream.write(`STDERR:\n${stderr}\n\n`);
    logStream.write(`Exit code: ${error ? error.code : 0}\n`);
    const envExists = ctx.fs.existsSync(path.join(projectRoot, '.env'));
    const venvExists = ctx.fs.existsSync(path.join(projectRoot, 'venv'));
    const configExists = ctx.fs.existsSync(path.join(projectRoot, 'config.json'));
    const cleanupSucceeded = !envExists && !venvExists;
    logStream.write(`\nCleanup verification:\n  .env exists: ${envExists}\n  venv exists: ${venvExists}\n`
      + `  config.json exists: ${configExists}\n  Cleanup succeeded: ${cleanupSucceeded}\n`
      + `=== Nuke finished at ${new Date().toISOString()} ===\n`);
    logStream.end();

    if (error) {
      console.error('Nuke failed:', error);
      ctx.dialog.showErrorBox('Nuke Failed', `Failed to complete system reset:\n\n${error.message}\n\nCheck logs at: ${NUKE_LOG_FILE}`);
    } else if (!cleanupSucceeded) {
      console.error('Nuke script succeeded but cleanup verification failed');
      ctx.dialog.showErrorBox('Nuke Incomplete', 'Script completed but cleanup verification failed.\n\nFiles still exist:\n'
        + `${envExists ? '  - .env\n' : ''}${venvExists ? '  - venv/\n' : ''}\nCheck logs at: ${NUKE_LOG_FILE}`);
    } else {
      console.log('Nuke completed successfully');
      ctx.dialog.showMessageBox({
        type: 'info', title: 'System Reset Complete', message: 'Carnivore has been completely removed.',
        detail: `All configuration has been deleted.\n\nLogs saved to: ${NUKE_LOG_FILE}\n\nRun ./setup.sh to configure again.\n\nThe app will now quit.`,
        buttons: ['OK'],
      }).then(() => ctx.app.quit());
    }
  });
}

function handlers(ctx) {
  return { 'server.nuke': () => nuke(ctx), 'server.uninstall': () => uninstallApp(ctx) };
}

module.exports = { NUKE_LOG_FILE, UNINSTALL_LOG_FILE, nuke, uninstallApp, handlers, unregisterLoginService, askStopSessions };
