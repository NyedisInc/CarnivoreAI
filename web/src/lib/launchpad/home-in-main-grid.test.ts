/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { initHomeInMain } from './home-in-main';

const g = globalThis as Record<string, unknown>;
let stop: () => void = () => {};
let mountCalls = 0;
let unmountCalls = 0;

const settle = async (): Promise<void> => {
  for (let i = 0; i < 4; i++) await Promise.resolve();
};

beforeEach(() => {
  mountCalls = 0;
  unmountCalls = 0;
  vi.stubGlobal('innerWidth', 1300);
  vi.stubGlobal('innerHeight', 800);
  document.body.innerHTML = `
    <div id="terminal-screen" class="screen active"><div id="terminal-grid"></div></div>
    <div id="launchpad-screen" class="screen"></div>`;
  g.CloudeWeb = {
    mountTerminalGrid: () => {
      mountCalls++;
      const surface = document.createElement('div');
      surface.className = 'oc-surface';
      surface.getBoundingClientRect = () => ({ top: 0, left: 300, right: 1200, bottom: 700, width: 900, height: 690 }) as DOMRect;
      surface.innerHTML = '<div class="oc-cell">primary</div>';
      document.getElementById('terminal-grid')!.append(surface);
      return true;
    },
    unmountTerminalGrid: () => {
      unmountCalls++;
      document.getElementById('terminal-grid')!.replaceChildren();
    },
  };
  (0, eval)(readFileSync('../client/js/terminal-grid-host.js', 'utf8'));
  stop = initHomeInMain(document, () => {});
});
afterEach(() => {
  stop();
  vi.unstubAllGlobals();
  delete g.CloudeWeb;
  delete g.TerminalGridHost;
  document.body.replaceChildren();
});

it('Home over the main area keeps the grid and its cells, and Escape back leaves them', async () => {
  await settle();
  expect(mountCalls).toBe(1);
  const terminal = document.getElementById('terminal-screen')!;
  const home = document.getElementById('launchpad-screen')!;

  terminal.classList.remove('active');
  home.classList.add('active');
  await settle();
  expect(unmountCalls).toBe(0);
  expect(document.querySelectorAll('#terminal-grid > .oc-surface > .oc-cell')).toHaveLength(1);

  home.classList.remove('active');
  terminal.classList.remove('active');
  terminal.classList.add('active');
  await settle();
  expect(unmountCalls).toBe(0);
  expect(mountCalls).toBe(1);
  expect(document.querySelectorAll('#terminal-grid > .oc-surface > .oc-cell')).toHaveLength(1);
});
