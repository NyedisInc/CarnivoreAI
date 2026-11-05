/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { HOME_SLOT_ATTR, initHomeInMain } from './home-in-main';

let stop: () => void = () => {};
let pause = vi.fn();

/* the home screen */
function page(): { terminal: HTMLElement; home: HTMLElement; grid: HTMLElement } {
  document.body.innerHTML = `
    <div id="terminal-screen" class="screen active"><div id="terminal-grid"><div class="oc-surface"></div><div data-session-rail></div></div></div>
    <div id="launchpad-screen" class="screen"></div>`;
  return { terminal: document.getElementById('terminal-screen')!, home: document.getElementById('launchpad-screen')!, grid: document.getElementById('terminal-grid')! };
}

function showHome(terminal: HTMLElement, home: HTMLElement): void {
  terminal.classList.remove('active');
  home.classList.add('active');
}

async function resizeTo(width: number): Promise<void> {
  vi.stubGlobal('innerWidth', width);
  window.dispatchEvent(new Event('resize'));
  await Promise.resolve();
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
});

it('moves Home into the grid, beside the rails, with the terminal screen still up', async () => {
  const { terminal, home, grid } = page();
  stop = initHomeInMain(document, pause);
  showHome(terminal, home);
  await Promise.resolve();
  expect(pause).toHaveBeenCalledOnce();
  expect(home.parentElement).toBe(grid);
  expect(grid.hasAttribute(HOME_SLOT_ATTR)).toBe(true);
  expect(terminal.classList.contains('active')).toBe(true);
  expect(document.querySelector('[data-session-rail]')!.contains(home)).toBe(false);
});

it('puts Home back in the body where it was when another screen takes over', async () => {
  const { terminal, home, grid } = page();
  stop = initHomeInMain(document, pause);
  showHome(terminal, home);
  await Promise.resolve();
  home.classList.remove('active');
  await Promise.resolve();
  expect(home.parentElement).toBe(document.body);
  expect(home.previousElementSibling).toBe(terminal);
  expect(grid.hasAttribute(HOME_SLOT_ATTR)).toBe(false);
  expect(pause).toHaveBeenCalledOnce();
});

it('stays the plain full screen on a phone width and when it did not come from a session', async () => {
  vi.stubGlobal('innerWidth', 600);
  const narrow = page();
  stop = initHomeInMain(document, pause);
  showHome(narrow.terminal, narrow.home);
  await Promise.resolve();
  expect(narrow.home.parentElement).toBe(document.body);
  expect(narrow.terminal.classList.contains('active')).toBe(false);
  stop();

  vi.stubGlobal('innerWidth', 1300);
  const cold = page();
  cold.terminal.classList.remove('active');
  stop = initHomeInMain(document, pause);
  cold.home.classList.add('active');
  await Promise.resolve();
  expect(cold.home.parentElement).toBe(document.body);
  expect(pause).not.toHaveBeenCalled();
});

it('does not take the slot over the empty "no session" terminal screen', async () => {
  const { terminal, home } = page();
  terminal.classList.add('terminal-screen--empty');
  stop = initHomeInMain(document, pause);
  showHome(terminal, home);
  await Promise.resolve();
  expect(home.parentElement).toBe(document.body);
});

it('leaves the slot below 1024 and takes it again when the window widens, with no screen change (#2774)', async () => {
  const { terminal, home, grid } = page();
  stop = initHomeInMain(document, pause);
  showHome(terminal, home);
  await Promise.resolve();
  await resizeTo(900);
  expect(home.parentElement).toBe(document.body);
  expect(terminal.classList.contains('active')).toBe(false);
  await resizeTo(1440);
  expect(home.parentElement).toBe(grid);
  expect(terminal.classList.contains('active')).toBe(true);
});

it('keeps no measured state, and only the surface under Home is inert, never the rails', async () => {
  const { terminal, home } = page();
  stop = initHomeInMain(document, pause);
  showHome(terminal, home);
  await Promise.resolve();
  expect(document.documentElement.getAttribute('style') ?? '').toBe('');
  expect(document.querySelector('.oc-surface')!.hasAttribute('inert')).toBe(true);
  expect(document.querySelector('[data-session-rail]')!.closest('[inert]')).toBeNull();
  home.classList.remove('active');
  await Promise.resolve();
  expect(document.querySelector('[inert]')).toBeNull();
});

it('the stylesheet gives Home the surface cell of the grid, with no stacking context of its own', () => {
  const css = readFileSync('src/lib/launchpad/home-in-main.css', 'utf8');
  const rules = css.replace(/\/\*[\s\S]*?\*\//g, '');
  expect(rules).toMatch(/#terminal-grid\.ps-grid-surface > #launchpad-screen\.active/);
  expect(rules).toMatch(/grid-row:\s*1 \/ 2/);
  expect(rules).toMatch(/position:\s*absolute/);
  expect(rules).not.toMatch(/z-index|contain:|transform:|position:\s*fixed|--menu-surface/);
});
