/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { createStandInClient, installTerminalStandIn, NEEDS_TERMINAL_CLIENT, STAND_IN_TRANSCRIPT } from './terminal-stand-in';
import { startLiveTerminal } from '../opscenter/cells/terminal-live/client';

const globals = globalThis as Record<string, unknown>;
const NAMES = ['CloudeTerminal', 'TerminalScroll', 'TerminalLayout', 'TerminalInputBuffer', 'AltScreenScroll', 'TerminalStartupNotice'];
afterEach(() => { for (const name of NAMES) delete globals[name]; });

describe('the terminal stand-in', () => {
  test('a widget that hosts no terminal gets nothing (the control)', () => {
    installTerminalStandIn('core.notes');
    expect(globals['CloudeTerminal']).toBeUndefined();
  });

  test('both terminal-hosting widgets are covered', () => {
    expect([...NEEDS_TERMINAL_CLIENT].sort()).toEqual(['core.shell', 'core.terminal']);
  });

  test('a real client already on the page is never replaced', () => {
    const real = { createTerminalClient: () => null };
    globals['CloudeTerminal'] = real;
    installTerminalStandIn('core.shell');
    expect(globals['CloudeTerminal']).toBe(real);
  });

  test('the cell starts a live terminal against it and the pane holds the canned transcript', async () => {
    installTerminalStandIn('core.shell');
    const host = document.createElement('div');
    document.body.append(host);
    const live = startLiveTerminal(host, 'shell:row:9101', { session: { id: 'ses_x' } });
    expect(live).not.toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(host.querySelector('[data-stand-in="terminal"]')?.textContent).toBe(STAND_IN_TRANSCRIPT.join('\n'));
    live?.dispose();
    expect(host.querySelector('[data-stand-in]')).toBeNull();
  });

  test('a stand-in with no container paints nothing and does not throw', async () => {
    const client = createStandInClient(null);
    await client.init();
    await expect(client.reconnectToExistingSession(null)).resolves.toBeUndefined();
    client.dispose();
  });

  test('no line is wider than the drawer small pane holds (20 characters)', () => {
    expect(Math.max(...STAND_IN_TRANSCRIPT.map((line) => line.length))).toBeLessThan(20);
  });
});
