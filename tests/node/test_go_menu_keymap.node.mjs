import assert from 'node:assert/strict';
import path from 'node:path';
import Module from 'node:module';
import { fileURLToPath } from 'node:url';

const macDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'macOS');
const require = Module.createRequire(path.join(macDir, 'x.js'));
const { installApplicationMenu } = require(path.join(macDir, 'app-menu', 'index.js'));

const { auditAccelerators } = require(path.join(macDir, 'app-menu', 'chords.js'));
const { toAccelerator } = require(path.join(macDir, 'app-menu', 'accelerator.js'));

let n = 0;
/** Run one named case. */
async function t(name, fn) { await fn(); n++; console.log(`ok - ${name}`); }

async function harness() {
  const handlers = {};
  const built = [];
  const frame = {};
  const sender = { mainFrame: frame };
  await installApplicationMenu({
    app: { name: 'Carnivore', isPackaged: false },
    Menu: { buildFromTemplate: (tpl) => { built.push(tpl); return tpl; }, setApplicationMenu: () => {} },
    shell: { openExternal: () => {} }, appWindow: { sendMenuCommand: () => {} }, showAbout: () => {}, quitAndStopEngine: () => {},
    waiting: () => null, exportDiagnostics: () => {}, loadTranslator: async () => (k) => k,
    ipcMain: { on: (ch, fn) => { handlers[ch] = fn; } }, fromMainPage: (e) => e.main !== false, log: () => {},
  });
  const send = (channel, payload, event = {}) => handlers[channel]?.({ sender, senderFrame: frame, ...event }, payload);
  const item = (id) => built.at(-1).find((m) => m.id === 'go').submenu.find((i) => i.id === id);
  return { send, item, count: () => built.length };
}

await t('defaults: Cmd+[ and Cmd+] until the page speaks', async () => {
  const h = await harness();
  assert.equal(h.item('go.back').accelerator, 'Cmd+[');
  assert.equal(h.item('go.forward').accelerator, 'Cmd+]');
});
await t('an override back = cmd+j shows Cmd+J and rebuilds the menu', async () => {
  const h = await harness();
  const before = h.count();
  h.send('carnivore:go-keys', { 'history.back': ['cmd+j'], 'history.forward': ['cmd+]'] });
  assert.equal(h.item('go.back').accelerator, 'Cmd+J');
  assert.equal(h.item('go.forward').accelerator, 'Cmd+]');
  assert.equal(h.count(), before + 1);
});
await t('an unbound action shows no accelerator; an unmappable chord never throws', async () => {
  const h = await harness();
  h.send('carnivore:go-keys', { 'history.back': [], 'history.forward': ['cmd+wat'] });
  assert.equal(h.item('go.back').accelerator, undefined);
  assert.equal(h.item('go.forward').accelerator, undefined);
});
await t('a malformed push is refused and an equal push does not rebuild', async () => {
  const h = await harness();
  h.send('carnivore:go-keys', 'nope');
  assert.equal(h.item('go.back').accelerator, 'Cmd+[');
  h.send('carnivore:go-keys', { 'history.back': ['cmd+j'] });
  const c = h.count();
  h.send('carnivore:go-keys', { 'history.back': ['cmd+j'] });
  assert.equal(h.count(), c);
});
await t('toAccelerator maps web chords and returns null for what it cannot draw', () => {
  assert.equal(toAccelerator('cmd+j'), 'Cmd+J');
  assert.equal(toAccelerator('shift+cmd+arrowleft'), 'Shift+Cmd+Left');
  assert.equal(toAccelerator('ctrl+alt+cmd+f10'), 'Ctrl+Alt+Cmd+F10');
  assert.equal(toAccelerator('cmd+['), 'Cmd+[');
  assert.equal(toAccelerator('cmd++'), 'Cmd+Plus');
  assert.equal(toAccelerator('Cmd+]'), 'Cmd+]');
  for (const bad of ['', 'cmd+', 'cmd+wat', 'hyper+j', 'cmd+é', null, 7, 'x'.repeat(50)]) assert.equal(toAccelerator(bad), null, String(bad));
});
await t('text-editing, reserved and Cmd-less chords show no accelerator (macOS offers them to the menu before the page)', async () => {
  const h = await harness();
  for (const chord of ['shift+cmd+arrowleft', 'cmd+arrowleft', 'alt+arrowleft', 'cmd+backspace', 'alt+backspace', 'shift+alt+arrowright', 'cmd+k', 'cmd+c', 'cmd+z', 'ctrl+j', 'j', 'cmd+]']) {
    h.send('carnivore:go-keys', { 'history.back': [chord] });
    assert.equal(h.item('go.back').accelerator, undefined, chord);
  }
  h.send('carnivore:go-keys', { 'history.back': ['cmd+arrowleft', 'cmd+j'] });
  assert.equal(h.item('go.back').accelerator, 'Cmd+J', 'the first chord that passes wins');
});
await t('the audit exempts nothing for registerAccelerator false', () => {
  const found = auditAccelerators([{ id: 'x', submenu: [{ id: 'x.f', accelerator: 'Cmd+F', registerAccelerator: false }] }]);
  assert.equal(found.length, 1);
});
await t('one bad or over-long chord drops only itself', async () => {
  const h = await harness();
  h.send('carnivore:go-keys', { 'history.back': [7, 'x'.repeat(50), 'cmd+j'], 'history.forward': 'nope' });
  assert.equal(h.item('go.back').accelerator, 'Cmd+J');
  assert.equal(h.item('go.forward').accelerator, 'Cmd+]', 'a non-array value is ignored');
});
await t('a push from a sub-frame or a window that is not the main one is refused', async () => {
  const h = await harness();
  h.send('carnivore:go-keys', { 'history.back': ['cmd+j'] }, { senderFrame: {} });
  assert.equal(h.item('go.back').accelerator, 'Cmd+[', 'sub-frame');
  h.send('carnivore:go-keys', { 'history.back': ['cmd+j'] }, { main: false });
  assert.equal(h.item('go.back').accelerator, 'Cmd+[', 'not the main window');
});
await t('a chord that is another menu item\'s shortcut shows no accelerator; the item\'s own chord stays', async () => {
  const h = await harness();
  h.send('carnivore:go-keys', { 'history.back': ['cmd+n'] });
  assert.equal(h.item('go.back').accelerator, undefined, 'File > New Session holds Cmd+N');
  h.send('carnivore:go-keys', { 'history.back': ['cmd+n', 'cmd+j'] });
  assert.equal(h.item('go.back').accelerator, 'Cmd+J');
});
console.log(`${n} passed`);
