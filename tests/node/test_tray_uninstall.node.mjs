import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { load, snap, env, byId, repo, catalogKeys } from './tray_menu_fixtures.mjs';

const require = createRequire(import.meta.url);
const server = load('model/server.js');

for (const menu of [server.serverMenuRunning(snap(), env), server.serverMenuDown(snap({ server: { state: 'stopped' } }), env)]) {
  const uninstall = byId([menu], 'uninstall');
  assert.deepEqual(uninstall.submenu.map((i) => i.id), ['uninstall.app', 'uninstall.nuke']);
  assert.equal(uninstall.submenu[0].label, 'Uninstall Carnivore...');
  assert.equal(uninstall.submenu[0].action.kind, 'server.uninstall');
}
assert.ok(catalogKeys.has('menubar.uninstall.app'));

const confirmWindow = require(path.join(repo, 'macOS', 'nuke-confirm.js'));
const uninstall = require(path.join(repo, 'macOS', 'tray-menu', 'actions', 'uninstall.js'));
const html = confirmWindow.buildUninstallHtml();
assert.match(html, /Type <b>UNINSTALL<\/b>/);
assert.match(html, /input\.value !== "UNINSTALL"/);
assert.match(html, /carnivore-projects/);

process.env.TMUX = '/tmp/tmux-501/carnivore,1,0';
process.env.TMUX_PANE = '%1';
const events = [];
let verdict = false;
confirmWindow.promptForUninstallConfirmation = async () => { events.push('confirm'); return verdict; };
const ctx = {
  app: { isPackaged: false }, shell: { trashItem: async () => events.push('trash') }, dialog: { showErrorBox: () => events.push('error') },
  fs, spawn: (cmd, args, opts) => {
    events.push('spawn');
    ctx.spawned = { cmd, args, opts };
    return { unref: () => events.push('unref') };
  },
};

await uninstall.handlers(ctx)['server.uninstall']();
assert.deepEqual(events, ['confirm'], 'cancel spawns nothing');

verdict = true;
events.length = 0;
await uninstall.handlers(ctx)['server.uninstall']();
assert.deepEqual(events, ['confirm', 'spawn', 'unref']);
const { cmd, args, opts } = ctx.spawned;
assert.equal(cmd, '/bin/bash');
assert.equal(args[1], '--yes');
assert.notEqual(args[0], path.join(repo, 'uninstall.sh'), 'runs a private copy, not the original');
assert.ok(args[0].startsWith(os.tmpdir()));
assert.equal(fs.readFileSync(args[0], 'utf8'), fs.readFileSync(path.join(repo, 'uninstall.sh'), 'utf8'));
assert.equal(opts.detached, true);
assert.equal('TMUX' in opts.env, false);
assert.equal('TMUX_PANE' in opts.env, false);
fs.rmSync(path.dirname(args[0]), { recursive: true });

const resources = fs.mkdtempSync(path.join(os.tmpdir(), 'carnivore-resources-'));
fs.copyFileSync(path.join(repo, 'uninstall.sh'), path.join(resources, 'uninstall.sh'));
process.resourcesPath = resources;
let unregisterOk = false;
const packaged = {
  app: { isPackaged: true }, shell: { trashItem: async () => events.push('trash') },
  dialog: { showErrorBox: () => events.push('error'), showMessageBox: async () => { events.push('ask'); return { response: 0 }; } },
  fs, execFile: (cmd, args, opts, done) => { events.push(`unregister:${args[0]}`); done(unregisterOk ? null : new Error('exit 1')); },
  spawn: (cmd, args, opts) => { events.push('spawn'); packaged.spawned = { cmd, args, opts }; return { unref: () => events.push('unref') }; },
};
events.length = 0;
await uninstall.handlers(packaged)['server.uninstall']();
assert.deepEqual(events, ['confirm', 'unregister:--unregister-login-service', 'error'], 'a failed unregister stops before anything is trashed or spawned');
unregisterOk = true;
events.length = 0;
await uninstall.handlers(packaged)['server.uninstall']();
assert.deepEqual(events.slice(0, 3), ['confirm', 'unregister:--unregister-login-service', 'ask']);
assert.ok(events.includes('spawn') && !events.includes('error'));
assert.equal(packaged.spawned.args.includes('--stop-tmux'), false, 'keeping the sessions passes no --stop-tmux');
fs.rmSync(path.dirname(packaged.spawned.args[0]), { recursive: true });
fs.rmSync(resources, { recursive: true });
assert.equal(path.dirname(uninstall.NUKE_LOG_FILE), os.tmpdir());
assert.notEqual(path.dirname(uninstall.NUKE_LOG_FILE), '/tmp');
confirmWindow.promptForNukeConfirmation = async () => true;
const nukeRun = { stream: null, file: null, exec: null };
const nukeCtx = {
  app: { isPackaged: true, quit: () => {} }, dialog: { showErrorBox: () => {}, showMessageBox: async () => ({}) },
  serverManager: { stop: async () => {}, getProjectRoot: () => '/tmp/dir with "quote" and $(touch x)' }, stopStatsPolling: () => {},
  fs: { createWriteStream: (file) => { nukeRun.file = file; return { write: () => {}, end: () => {} }; }, existsSync: () => false },
  exec: () => assert.fail('nuke must not build a shell string'),
  execFile: (cmd, argv, opts, done) => { nukeRun.exec = { cmd, argv, opts }; done(null, '', ''); },
};
await uninstall.nuke(nukeCtx);
assert.equal(nukeRun.exec.cmd, '/bin/bash');
assert.deepEqual(nukeRun.exec.argv, ['/tmp/dir with "quote" and $(touch x)/nuke.sh', '--skip-confirm', '--system']);
assert.equal(nukeRun.file, uninstall.NUKE_LOG_FILE);
console.log('ok test_tray_uninstall');
