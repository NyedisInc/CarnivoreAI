/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { HOME_IN_MAIN_CLASS, initHomeInMain } from './home-in-main';

let stop: () => void = () => {};
let pause = vi.fn();

function page(): { terminal: HTMLElement; home: HTMLElement; surface: HTMLElement } {
  document.body.innerHTML = `
    <div id="terminal-screen" class="screen active"><div id="terminal-grid"><div class="oc-surface"></div><div data-session-rail></div></div></div>
    <div id="launchpad-screen" class="screen"></div>`;
  const surface = document.querySelector<HTMLElement>('#terminal-grid > .oc-surface')!;
  surface.getBoundingClientRect = () => ({ top: 10, left: 300, right: 1200, bottom: 700, width: 900, height: 690 }) as DOMRect;
  return { terminal: document.getElementById('terminal-screen')!, home: document.getElementById('launchpad-screen')!, surface };
}

function showHome(terminal: HTMLElement, home: HTMLElement): void {
  terminal.classList.remove('active');
  home.classList.add('active');
}

beforeEach(() => {
  pause = vi.fn();
  vi.stubGlobal('innerWidth', 1300);
  vi.stubGlobal('innerHeight', 800);
});
afterEach(() => {
  stop();
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
  document.documentElement.removeAttribute('style');
});

it('keeps the terminal screen and its rails up and lays Home over the surface', async () => {
  const { terminal, home, surface } = page();
  stop = initHomeInMain(document, pause);
  showHome(terminal, home);
  await Promise.resolve();
  expect(pause).toHaveBeenCalledOnce();
  expect(terminal.classList.contains('active')).toBe(true);
  expect(document.body.classList.contains(HOME_IN_MAIN_CLASS)).toBe(true);
  expect(surface.hasAttribute('inert')).toBe(true);
  expect(document.querySelector('[data-session-rail]')!.closest('[inert]')).toBeNull();
  expect(document.documentElement.style.getPropertyValue('--menu-surface-left')).toBe('300px');
  expect(document.documentElement.style.getPropertyValue('--menu-surface-right')).toBe('100px');
});

it('leaves the main area when another screen takes over', async () => {
  const { terminal, home, surface } = page();
  stop = initHomeInMain(document, pause);
  showHome(terminal, home);
  await Promise.resolve();
  home.classList.remove('active');
  terminal.classList.add('active');
  await Promise.resolve();
  expect(document.body.classList.contains(HOME_IN_MAIN_CLASS)).toBe(false);
  expect(surface.hasAttribute('inert')).toBe(false);
  expect(pause).toHaveBeenCalledOnce();
});

it('stays as it was on a phone width', async () => {
  vi.stubGlobal('innerWidth', 600);
  const { terminal, home } = page();
  stop = initHomeInMain(document, pause);
  showHome(terminal, home);
  await Promise.resolve();
  expect(terminal.classList.contains('active')).toBe(false);
  expect(document.body.classList.contains(HOME_IN_MAIN_CLASS)).toBe(false);
  expect(pause).not.toHaveBeenCalled();
});

it('the stylesheet pins Home to the measured main-area insets, not the whole window', () => {
  const css = readFileSync('src/lib/launchpad/home-in-main.css', 'utf8');
  expect(css).toMatch(/body\.home-in-main #launchpad-screen\.active/);
  expect(css).toMatch(/position:\s*fixed/);
  for (const side of ['top', 'left', 'right', 'bottom']) expect(css).toContain(`var(--menu-surface-${side})`);
});
