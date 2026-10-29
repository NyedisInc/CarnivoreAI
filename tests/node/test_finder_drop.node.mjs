
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { EventEmitter } from 'node:events';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const drop = require(path.join(root, 'macOS', 'finder-drop.js'));
const targets = require(path.join(root, 'macOS', 'folder-targets.js'));

const work = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'finder-drop-test-')));
let failures = 0;
const test = async (name, fn) => {
  try { await fn(); console.log('ok   ' + name); } catch (error) { failures += 1; console.log('FAIL ' + name + '\n' + (error && error.stack)); }
};
const mkdir = (...parts) => { const p = path.join(work, ...parts); fs.mkdirSync(p, { recursive: true }); return p; };

function pageWindow(bridge) {
  const win = { console, setTimeout, clearTimeout };
  win.window = win;
  if (bridge) win.carnivoreDesktop = bridge;
  vm.createContext(win);
  for (const file of ['client/js/clipboard.js', 'client/js/terminal-input-ownership.js', 'client/js/terminal-file-drop.js']) {
    try { vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), win, { filename: file }); } catch (error) {
      if (file.endsWith('clipboard.js')) throw error;
    }
  }
  return win;
}
function container() {
  const handlers = {};
  return { handlers, addEventListener(type, fn, capture) { handlers[type] = { fn, capture }; } };
}
function terminal(win, el) {
  const inserted = [];
  return {
    inserted, _containerEl: () => el, _showStatusPill() {},
    insertText(text, ticket) { if (win.TerminalInputOwnership && !win.TerminalInputOwnership.deliver(this, ticket)) return; inserted.push(text); },
  };
}
const dropEvent = (files) => {
  const ev = { dataTransfer: { types: ['Files'], files }, prevented: false, stopped: false, preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; } };
  return ev;
};
function shellWords(text) {
  const out = execFileSync('bash', ['-c', 'printf "%s\\0" ' + text]).toString('utf8');
  return out.split('\0').slice(0, -1);
}
const bridgeOf = (paths) => ({ capabilities: ['droppedPaths'], droppedPaths: () => paths });

await test('1 quoting: spaces, quotes, $, backtick, ; survive as ONE word each; control characters and relative paths are skipped', async () => {
  const names = ['/Users/a b/my file.txt', "/tmp/it's here", '/tmp/say "hi"', '/tmp/$HOME/`id`', '/tmp/a;b', '/tmp/plain.txt', "/tmp/'\"mix $x `y` ; z'"];
  const win = pageWindow(bridgeOf([...names, '/tmp/new\nline', 'relative/path', '', '/tmp/tab\there']));
  const el = container(); const term = terminal(win, el);
  assert.equal(win.TerminalFileDrop.attach(term), true);
  assert.equal(el.handlers.drop.capture, true);
  const ev = dropEvent([{}]);
  el.handlers.drop.fn(ev);
  assert.equal(term.inserted.length, 1);
  const text = term.inserted[0];
  assert.deepEqual(shellWords(text), names, 'each path is one shell word, byte for byte');
  assert.ok(text.endsWith(' ') && !text.endsWith('  '), 'one trailing space');
  assert.ok(!/[\r\n]/.test(text), 'no Enter byte and no newline');
  assert.ok(ev.prevented && ev.stopped);
  const two = pageWindow(bridgeOf(['/a b', '/c']));
  const el2 = container(); const t2 = terminal(two, el2); two.TerminalFileDrop.attach(t2);
  el2.handlers.drop.fn(dropEvent([{}, {}]));
  assert.equal(t2.inserted[0], "'/a b' /c ");
  const none = pageWindow(bridgeOf(['', 'rel', '/x\ny']));
  const el3 = container(); const t3 = terminal(none, el3); none.TerminalFileDrop.attach(t3);
  el3.handlers.drop.fn(dropEvent([{}]));
  assert.deepEqual(t3.inserted, []);
});

await test('2 no bridge, or no droppedPaths capability: nothing attached, nothing inserted; text drags are left alone', async () => {
  for (const bridge of [null, { capabilities: [], droppedPaths: () => ['/a'] }, { capabilities: ['droppedPaths'] }]) {
    const win = pageWindow(bridge); const el = container(); const term = terminal(win, el);
    assert.equal(win.TerminalFileDrop.attach(term), false);
    assert.deepEqual(Object.keys(el.handlers), []);
    assert.deepEqual(term.inserted, []);
  }
  const win = pageWindow(bridgeOf(['/a'])); const el = container(); const term = terminal(win, el); win.TerminalFileDrop.attach(term);
  const textDrag = { dataTransfer: { types: ['text/plain'], files: [] }, preventDefault() { assert.fail('prevented'); }, stopPropagation() { assert.fail('stopped'); } };
  el.handlers.drop.fn(textDrag); el.handlers.dragover.fn(textDrag);
  assert.deepEqual(term.inserted, []);
  const over = { dataTransfer: { types: ['Files'], dropEffect: '' }, preventDefault() { this.prevented = true; } };
  el.handlers.dragover.fn(over);
  assert.ok(over.prevented && over.dataTransfer.dropEffect === 'copy');
});

await test('3 ownership: a session switched between the gesture and the write inserts nothing', async () => {
  const win = pageWindow(null);
  let generation = 1;
  win.NavigationGeneration = { current: () => generation, isCurrent: (n) => n === generation };
  win.carnivoreDesktop = { capabilities: ['droppedPaths'], droppedPaths: () => { generation = 2; return ['/a/b']; } };
  const el = container(); const term = terminal(win, el); win.TerminalFileDrop.attach(term);
  el.handlers.drop.fn(dropEvent([{}]));
  assert.deepEqual(term.inserted, [], 'the ticket was claimed at the gesture, so the stale write is refused');
  win.carnivoreDesktop = bridgeOf(['/a/b']);
  el.handlers.drop.fn(dropEvent([{}]));
  assert.deepEqual(term.inserted, ['/a/b ']);
});

await test('4 canonical folder: a folder, its symlink and its realpath agree; a file, a missing path, a relative path and "" are refused', async () => {
  const real = mkdir('real dir'); const link = path.join(work, 'link'); fs.symlinkSync(real, link);
  const file = path.join(real, 'f.txt'); fs.writeFileSync(file, 'x');
  for (const p of [real, link, real + '/', path.join(real, '..', 'real dir')]) assert.equal(drop.canonicalFolder(p).path, real, p);
  for (const p of [file, path.join(work, 'nope'), 'relative/dir', '', null, 7, real + '\n']) assert.equal(drop.canonicalFolder(p).ok, false, String(p));
  const home = mkdir('fakehome', 'proj');
  const expanded = drop.canonicalFolder('~/proj', { fs, os: { homedir: () => path.dirname(home) } });
  assert.equal(expanded.path, home);
});

function rig(projects, creates) {
  const log = { posts: [], dialogs: [], opened: [] };
  const api = {
    async getAuthed() { return { reachable: true, status: 200, data: projects, error: null }; },
    async sendAuthed(route, body, method) { log.posts.push({ route, body, method }); return creates(body, log.posts.length); },
  };
  const make = (answers) => {
    const queue = [...answers];
    return createDropOpener(api, log, queue);
  };
  return { log, make };
}
function createDropOpener(api, log, queue) {
  return drop.createFinderDrop({
    api: () => api, loadTranslator: async () => (k) => k, appWindow: { open: (hash) => { log.opened.push(hash); return true; } },
    dialog: { async showMessageBox(opts) { log.dialogs.push(opts); return { response: queue.length ? queue.shift() : 0 }; } },
  });
}

await test('5 open or create: existing project under another spelling opens with no POST; new folder asks first; retries a taken name', async () => {
  const real = mkdir('my proj'); const link = path.join(work, 'proj-link'); fs.symlinkSync(real, link);
  let r = rig([{ id: 1, name: 'My Proj', path: link, root: link }], () => assert.fail('POST'));
  let res = await r.make([]).open([real]);
  assert.deepEqual(res, { done: true }); assert.deepEqual(r.log.opened, ['session/My%20Proj']); assert.deepEqual(r.log.posts, []); assert.deepEqual(r.log.dialogs, []);
  const fresh = mkdir('fresh one');
  r = rig([], () => assert.fail('POST'));
  await r.make([1]).open([fresh]);
  assert.deepEqual(r.log.posts, []); assert.deepEqual(r.log.opened, []);
  assert.equal(r.log.dialogs[0].detail, fresh, 'the dialog shows the real path'); assert.equal(r.log.dialogs[0].defaultId, 1, 'Cancel is the default button');
  r = rig([], () => ({ reachable: true, status: 201, data: {}, error: null }));
  await r.make([0]).open([path.join(work, 'fresh one')]);
  assert.deepEqual(r.log.posts, [{ route: '/api/v1/projects', body: { name: 'fresh one', path: fresh }, method: 'POST' }]);
  assert.deepEqual(r.log.opened, ['session/fresh%20one']);
  r = rig([], (body) => (body.name === 'fresh one'
    ? { reachable: false, status: 400, data: null, body: { detail: 'a project named fresh one already exists' }, error: 'x' }
    : { reachable: true, status: 201, data: {}, error: null }));
  await r.make([0]).open([fresh]);
  assert.deepEqual(r.log.posts.map((p) => p.body.name), ['fresh one', 'fresh one (2)']); assert.deepEqual(r.log.opened, ['session/fresh%20one%20(2)']);
  r = rig([], () => ({ reachable: false, status: 409, data: null, body: { existing_project: { id: 4, name: 'Other' } }, error: 'x' }));
  await r.make([0]).open([fresh]);
  assert.deepEqual(r.log.opened, ['session/Other']);
  r = rig([], () => ({ reachable: false, status: 409, data: null, body: { code: 'project_root_refused', detail: 'no' }, error: 'x' }));
  await r.make([0]).open([fresh]);
  assert.deepEqual(r.log.opened, []); assert.equal(r.log.dialogs[1].message, 'menubar.drop.refused');
  const file = path.join(fresh, 'a.txt'); fs.writeFileSync(file, 'x');
  r = rig([], () => assert.fail('POST'));
  await r.make([]).open([file]);
  assert.equal(r.log.dialogs[0].message, 'menubar.drop.not_folder'); assert.deepEqual(r.log.opened, []);
  const down = drop.createFinderDrop({ api: () => null, loadTranslator: async () => (k) => k, appWindow: { open: () => assert.fail('open') }, dialog: { showMessageBox: () => assert.fail('dialog') } });
  assert.deepEqual(await down.open([fresh]), { done: false });
});

await test('5i open-file is held until the server answers, then replayed once; a batch within 150 ms is one drop', async () => {
  const fresh = mkdir('held');
  const handlers = {}; const calls = [];
  let up = false;
  const opener = { async open(paths) { calls.push([...paths]); return { done: up }; } };
  const wired = drop.wireFinderDrop({ app: { on: (name, fn) => { handlers[name] = fn; } }, opener: () => opener });
  let prevented = 0;
  handlers['open-file']({ preventDefault: () => { prevented += 1; } }, fresh);
  handlers['open-file']({ preventDefault: () => { prevented += 1; } }, fresh + '2');
  await new Promise((r) => setTimeout(r, drop.BATCH_MS + 80));
  assert.equal(prevented, 2); assert.deepEqual(calls, [[fresh, fresh + '2']]);
  up = true; await wired.onServerUp();
  assert.equal(calls.length, 2, 'replayed once'); await wired.onServerUp(); assert.equal(calls.length, 2, 'not replayed again');
});

function targetRig({ rows = [], projects = [], editor = '', answer = 0, dir = null } = {}) {
  const log = { shown: [], execs: [], dialogs: [] };
  const api = {
    async fetchSessions() { return { reachable: true, sessions: rows, error: null }; },
    async getAuthed(route) {
      if (route === '/api/v1/projects') return { reachable: true, data: projects };
      if (route === '/api/v1/config/settings') return { reachable: true, data: { workspace: { default_editor: editor } } };
      return { reachable: false, error: 'unexpected ' + route };
    },
  };
  const t = targets.createFolderTargets({
    api: () => api, loadTranslator: async () => (k) => k,
    dialog: { async showMessageBox(o) { log.dialogs.push(o); return { response: answer }; } },
    shell: { showItemInFolder: (p) => log.shown.push(p) },
    dataDir: () => dir || mkdir('userdata-' + Math.random().toString(36).slice(2)),
    spawn: (file, args, options) => {
      log.execs.push({ file, args, options });
      const child = new EventEmitter(); child.unref = () => { log.unref = true; };
      setImmediate(() => child.emit('exit', 0, null));
      return child;
    },
  });
  return { t, log };
}
const sessionRow = (id, dir, extra = {}) => ({ session: { id, working_dir: dir }, host_key: 'local', ...extra });

await test('6 folder targets: ids are checked, main resolves the folder, reveal uses the realpath, the editor runs by execFile with one folder argument', async () => {
  const nasty = mkdir('x; rm -rf ~'); const link = path.join(work, 'nasty-link'); fs.symlinkSync(nasty, link);
  const rows = [sessionRow('ses_1', link), sessionRow('adopted:abc', nasty), sessionRow('ses_peer', nasty, { host_key: 'peer-a' }), sessionRow('ses_gone', path.join(work, 'gone'))];
  const projects = [{ id: 7, name: 'P', path: nasty, root: nasty }];
  const a = targetRig({ rows, projects, editor: 'open -a "Visual Studio Code"' });
  assert.deepEqual(await a.t.reveal('ses_1'), { ok: true, reason: 'ok', error: null }); assert.deepEqual(a.log.shown, [nasty], 'showItemInFolder gets the realpath');
  assert.equal((await a.t.reveal('adopted:abc')).ok, true);
  assert.equal((await a.t.reveal('project:7')).ok, true); assert.equal(a.log.shown[2], nasty);
  assert.equal((await a.t.reveal('remote:peer-a:ses_1')).reason, 'remote');
  assert.equal((await a.t.reveal('ses_peer')).reason, 'remote', 'a non-local host_key row');
  assert.equal((await a.t.reveal('ses_unknown')).reason, 'missing', 'not in the listing');
  assert.equal((await a.t.reveal('ses_gone')).reason, 'missing', 'the folder is gone');
  assert.equal((await a.t.reveal('project:99')).reason, 'missing');
  for (const bad of ['', 'project:7;x', 'project:', '../etc', 'ses_1\n', 'ses_ 1', null, 7, { id: 'ses_1' }]) assert.equal((await a.t.reveal(bad)).reason, 'failed', String(bad));
  assert.equal(a.log.shown.length, 3, 'only the three good ids revealed anything');
  const r = await a.t.openInEditor('project:7');
  assert.equal(r.ok, true);
  assert.deepEqual(a.log.execs.map((e) => ({ file: e.file, args: e.args })), [{ file: '/usr/bin/open', args: ['-a', 'Visual Studio Code', nasty] }], 'spawn, folder is the last single argument');
  assert.deepEqual(a.log.execs[0].options, { detached: true, stdio: 'ignore' }, 'detached, no pipes');
  assert.ok(!a.log.execs.some((e) => /(^|\/)(sh|bash|zsh)$/.test(e.file) || e.args.includes('-c')), 'no shell');
  const b = targetRig({ rows, projects, editor: '/usr/local/bin/code -w' });
  await b.t.openInEditor('ses_1');
  assert.deepEqual(b.log.execs.map((e) => ({ file: e.file, args: e.args })), [{ file: '/usr/local/bin/code', args: ['-w', nasty] }]);
  const c = targetRig({ rows, projects, editor: '' });
  assert.equal((await c.t.openInEditor('ses_1')).reason, 'no_editor');
  assert.deepEqual(c.log.execs, []); assert.equal(c.log.dialogs[0].message, 'menubar.editor.none_message');
  const d = targetRig({ rows, projects, editor: 'code -w' });
  assert.equal((await d.t.openInEditor('ses_1')).reason, 'failed'); assert.deepEqual(d.log.execs, []);
});

await test('7 open in editor: first use and every change ask first, a cancel runs nothing, the folder is not part of the approval', async () => {
  const folder = mkdir('ravcrest-ravvale'); const folder2 = mkdir('corridge-cormont');
  const rows = [sessionRow('ses_1', folder), sessionRow('ses_2', folder2)];
  const dir = mkdir('ud');
  const a = targetRig({ rows, editor: '/usr/bin/curl -o /tmp/x', answer: 1, dir });
  assert.equal((await a.t.openInEditor('ses_1')).reason, 'cancelled'); assert.deepEqual(a.log.execs, []);
  assert.equal(a.log.dialogs.length, 1); assert.match(a.log.dialogs[0].detail, /"\/usr\/bin\/curl"\n"-o"\n"\/tmp\/x"\n"[^"]*ravcrest-ravvale"/, 'the exact argv, one element per line');
  assert.equal(fs.existsSync(path.join(dir, 'editor-command-confirmed.json')), false);
  const b = targetRig({ rows, editor: '/usr/local/bin/code -w', answer: 0, dir });
  assert.equal((await b.t.openInEditor('ses_1')).ok, true); assert.equal(b.log.dialogs.length, 1); assert.equal(b.log.execs.length, 1);
  assert.equal((await b.t.openInEditor('ses_2')).ok, true); assert.equal(b.log.dialogs.length, 1, 'the folder is outside the hash'); assert.equal(b.log.execs.length, 2);
  const c = targetRig({ rows, editor: '/usr/local/bin/code -w --evil', answer: 0, dir });
  assert.equal((await c.t.openInEditor('ses_1')).ok, true); assert.equal(c.log.dialogs.length, 1, 'a changed command asks again');
  assert.match(c.log.dialogs[0].detail, /^menubar\.terminal\.confirm_changed/, 'and says it changed since the last approval');
  assert.notEqual(path.basename(path.join(dir, 'editor-command-confirmed.json')), 'terminal-custom-confirmed.json');
});

await test('8 the editor splitter reads what shlex.quote writes', async () => {
  const oit = require(path.join(root, 'macOS', 'open-in-terminal.js'));
  const words = (s) => oit.splitTemplate(s).words;
  assert.deepEqual(words("/usr/bin/open -a 'Visual Studio Code'"), ['/usr/bin/open', '-a', 'Visual Studio Code']);
  assert.deepEqual(words("'/Applications/Sublime Text.app/Contents/SharedSupport/bin/subl' -w"), ['/Applications/Sublime Text.app/Contents/SharedSupport/bin/subl', '-w']);
  assert.deepEqual(words(`'it'"'"'s' x`), ["it's", 'x'], 'shlex.quote of a name with a single quote');
  assert.deepEqual(words('open -a "My \\"Term\\""'), ['open', '-a', 'My "Term"']);
  assert.deepEqual(words('a\\ b c'), ['a b', 'c']);
  assert.equal(oit.splitTemplate("open 'x").ok, false); assert.equal(oit.splitTemplate('open x\\').ok, false);
  assert.deepEqual(words('open -na "My Term" --args'), ['open', '-na', 'My Term', '--args'], 'the R1-14 form still works');
  assert.deepEqual(words("''"), [''], 'an empty quoted word is a word');
});

fs.rmSync(work, { recursive: true, force: true });
if (failures) { console.log(`\n${failures} failed`); process.exit(1); }
console.log('\nall passed');
