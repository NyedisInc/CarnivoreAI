import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { updateUxFor, createNoticeMemo } = require('../../macOS/update-ux.js');

test('manual mode: available, downloading and ready wear the update icon and a row; only available notifies', () => {
  for (const [state, notify] of [['available', true], ['downloading', false], ['ready', false]]) {
    const ux = updateUxFor({ state, version: '1.16.4' }, false);
    assert.equal(ux.trayIcon, 'update');
    assert.equal(ux.menuRow.version, '1.16.4');
    assert.equal(ux.menuRow.label, 'update to 1.16.4: download, install and restart');
    assert.equal(ux.notify, notify);
  }
});

test('auto mode shows nothing in any state', () => {
  for (const state of ['available', 'downloading', 'ready', 'error', 'current']) {
    assert.deepEqual(updateUxFor({ state, version: '1.16.4' }, true), { trayIcon: 'normal', menuRow: null, notify: false });
  }
});

test('every other state is normal in manual mode', () => {
  for (const state of ['idle', 'checking', 'current', 'unknown', 'error', 'update_refused', 'not_configured', 'invalid_feed']) {
    assert.deepEqual(updateUxFor({ state, version: '1.16.4' }, false), { trayIcon: 'normal', menuRow: null, notify: false });
  }
  assert.equal(updateUxFor(null, false).trayIcon, 'normal');
});

test('the notice memo announces a version once, survives a relaunch, and announces the next version', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'update-ux-'));
  try {
    assert.equal(createNoticeMemo({ dir: () => dir }).shouldAnnounce('1.16.4'), true);
    const relaunched = createNoticeMemo({ dir: () => dir });
    assert.equal(relaunched.shouldAnnounce('1.16.4'), false);
    assert.equal(relaunched.shouldAnnounce('1.16.5'), true);
    assert.equal(relaunched.shouldAnnounce(''), false);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

const { load, env, snap } = await import('./tray_menu_fixtures.mjs');
const { windowFacts } = require('../../macOS/update-window.js');
const { buildMenuModel } = load('model/index.js');

test('the update row is the FIRST menu item with the red icon in manual mode, and absent in auto mode', () => {
  const manual = buildMenuModel(snap({ autoUpdate: false, update: { state: 'available', version: '1.16.4' } }), env);
  assert.equal(manual[0].id, 'update.install');
  assert.equal(manual[0].icon, 'update');
  assert.equal(manual[0].label, 'update to 1.16.4: download, install and restart');
  assert.deepEqual(manual[0].action, { kind: 'update.install' });
  const auto = buildMenuModel(snap({ autoUpdate: true, update: { state: 'ready', version: '1.16.4' } }), env);
  assert.ok(!auto.some((i) => i.id === 'update.install'));
});

test('the progress window shows downloading with a percent, the install phases, and the error with try again', () => {
  const t = (key, params) => `${key}|${params ? JSON.stringify(params) : ''}`;
  const down = windowFacts({ state: 'downloading', version: '1.16.4', percent: 41 }, t);
  assert.equal(down.phase, 'downloading');
  assert.equal(down.percent, 41);
  assert.equal(down.retryLabel, null);
  for (const phase of ['verifying', 'installing', 'restarting']) {
    const f = windowFacts({ state: 'ready', version: '1.16.4', percent: 100, phase }, t);
    assert.equal(f.phase, phase);
    assert.equal(f.percent, null);
  }
  const bad = windowFacts({ state: 'update_refused', version: '1.16.4', detail: 'signature mismatch', phase: null }, t);
  assert.equal(bad.phase, 'error');
  assert.equal(bad.detail, 'signature mismatch');
  assert.ok(bad.retryLabel);
});

test('the progress window page is served by its own session, never from file:// inside app.asar (#2477)', async () => {
  const { createUpdateWindow } = require('../../macOS/update-window.js');
  const handlers = new Map();
  const protocol = { handle: (scheme, fn) => handlers.set(scheme, fn), isProtocolHandled: (scheme) => handlers.has(scheme) };
  const loads = [];
  class BrowserWindow {
    constructor(opts) {
      this.opts = opts;
      this.webContents = { on() {}, setWindowOpenHandler() {}, session: { setPermissionRequestHandler() {}, protocol } };
    }
    on() {} once() {} isDestroyed() { return false; }
    loadFile(file) { loads.push(`file://${file}`); }
    loadURL(url) { loads.push(url); }
  }
  const w = createUpdateWindow({ BrowserWindow, ipcMain: { handle() {}, on() {} }, getFacts: () => ({ title: 'update' }),
    runAction() {}, tokensCss: () => ':root{}' });
  w.open();
  assert.equal(loads.length, 1);
  const url = new URL(loads[0]);
  assert.notEqual(url.protocol, 'file:', 'a file:// page inside app.asar paints blank in the packaged app');
  const serve = handlers.get(url.protocol.slice(0, -1));
  assert.ok(serve, 'the page scheme is handled on the window\'s own session');
  const page = await serve(new Request(url.href));
  assert.equal(page.status, 200);
  assert.match(page.headers.get('content-type'), /^text\/html/);
  assert.match(await page.text(), /<script src="update\.js"><\/script>/);
  const css = await serve(new Request(new URL('update.css', url).href));
  assert.equal(css.status, 200);
  assert.match(css.headers.get('content-type'), /^text\/css/);
  for (const bad of ['../update-window.js', '%2E%2E/main.js', 'nope.html']) {
    assert.equal((await serve(new Request(new URL(bad, url).href))).status, 404, bad);
  }
  assert.equal((await serve(new Request(url.href.replace(url.host, 'other')))).status, 404, 'another host');
});
