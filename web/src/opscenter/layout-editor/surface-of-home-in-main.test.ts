/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { surfaceOf } from './empty-space-menu.svelte';

afterEach(() => {
  document.body.innerHTML = '';
});

test('a press on the home screen is Home while the terminal screen is also active', () => {
  document.body.innerHTML = '<div id="terminal-screen" class="screen active"></div><div id="launchpad-screen" class="screen active"><div id="gap"></div></div>';
  expect(surfaceOf(document.getElementById('gap'))).toBe('home');
});

test('a press on the terminal page is still the terminal', () => {
  document.body.innerHTML = '<div id="terminal-screen" class="screen active"><div id="gap"></div></div><div id="launchpad-screen" class="screen"></div>';
  expect(surfaceOf(document.getElementById('gap'))).toBe('terminal');
});
