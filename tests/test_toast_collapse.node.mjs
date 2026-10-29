// ----------------------------------------------------------------------

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';

import { makeEnv, toast, cards } from './lib_toast_dom_stub.mjs';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const COLLAPSE_SRC = fs.readFileSync(
  path.join(ROOT, 'client/js/toast-collapse.js'), 'utf8');

function makeCollapseEnv() {
  const env = makeEnv();
  vm.runInContext(COLLAPSE_SRC, env.sandbox, { filename: 'toast-collapse.js' });
  if (!env.sandbox.window.ToastCollapse) {
    throw new Error(
      'toast-collapse.js did not export window.ToastCollapse, so every '
      + 'assertion below would be measuring the no-module skip branch in '
      + 'toast-render.js rather than the toggle itself');
  }
  return env;
}

const tests = [];
/** Description: register one named case. Inputs: name, fn. Output: None. */
function test(name, fn) { tests.push([name, fn]); }


test('NEGATIVE CONTROL: with the module unloaded, no toggle appears', () => {
  const { container, mgr } = makeEnv();
  mgr.add(toast('Notification', 'files ready', 'three files attached', 's1'));
  const card = cards(container)[0];
  assert.ok(card, 'setup: the card must exist before any absence means anything');
  assert.equal(card.querySelector('.toast__toggle'), null,
    'no toggle can appear when toast-collapse.js was never loaded');
});

test('a card with a body gets the toggle', () => {
  const { container, mgr } = makeCollapseEnv();
  mgr.add(toast('Notification', 'files ready', 'three files attached', 's1'));
  const card = cards(container)[0];
  const toggle = card.querySelector('.toast__toggle');
  assert.ok(toggle, 'a card with winner.body must render the toggle');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false',
    'a freshly rendered card starts collapsed');
  assert.ok(toggle.getAttribute('aria-label'),
    'the toggle must say what it does, for a screen reader with no icon');
});

test('an attachment card with no body still gets the toggle', () => {
  const { container, mgr } = makeCollapseEnv();
  mgr.add(toast('Attachment', 'file received', null, 's2'));
  const card = cards(container)[0];
  assert.ok(card.querySelector('.toast__toggle'),
    'an Attachment-kind card must render the toggle even with body === null');
});

test('a card with neither a body nor Attachment kind gets no toggle', () => {
  const { container, mgr } = makeCollapseEnv();
  mgr.add(toast('Stop', 'session finished', null, 's3'));
  const card = cards(container)[0];
  assert.ok(card, 'setup');
  assert.equal(card.querySelector('.toast__toggle'), null,
    'a toggle that would expand nothing must not be drawn');
});


test('clicking the toggle flips data-expanded and aria-expanded together', () => {
  const { container, mgr } = makeCollapseEnv();
  mgr.add(toast('Notification', 'files ready', 'three files attached', 's4'));
  const card = cards(container)[0];
  const toggle = card.querySelector('.toast__toggle');

  assert.notEqual(card.dataset.expanded, '1', 'setup: starts collapsed');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false', 'setup: starts collapsed');

  toggle.click();
  assert.equal(card.dataset.expanded, '1',
    'a click must expand the card (data-expanded="1")');
  assert.equal(toggle.getAttribute('aria-expanded'), 'true',
    'a click must flip aria-expanded along with data-expanded, not just one');

  toggle.click();
  assert.equal(card.dataset.expanded, '0',
    'a second click must collapse the card again');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false',
    'a second click must flip aria-expanded back too');
});

test('the toggle click does not also fire the card\'s navigate handler', () => {
  const { container, mgr, sandbox } = makeCollapseEnv();
  const nav = [];
  sandbox.window.ToastNavigate = { go: (w) => nav.push(w.id) };
  const t = toast('Notification', 'files ready', 'three files attached', 's5', 'tmux-s5');
  mgr.add(t);
  const card = cards(container)[0];
  card.querySelector('.toast__toggle').click();
  assert.equal(nav.length, 0,
    'the toggle must stop propagation before it reaches the card\'s own click handler');
});

// ----------------------------------------------------------------- runner

let failed = 0;
for (const [name, fn] of tests) {
  try {
    // eslint-disable-next-line no-await-in-loop
    await fn();
    console.log('ok  ', name);
  } catch (err) {
    failed += 1;
    console.error('FAIL', name, '\n     ', err.message);
  }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
process.exit(failed ? 1 : 0);
