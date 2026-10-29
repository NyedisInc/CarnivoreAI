/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { setDrawerEnv } from '../drawer/env';
import { fakeStorage } from '../drawer/test-support';
import { rememberLastView, type RestoreDeps } from '../drawer/last-view';
import { handleMenuPageEscape } from '../menu-page/menu-page-escape';
import { registerHomeEscape } from './home-escape';

let off: () => void = () => {};

beforeEach(() => setDrawerEnv({ localStorage: fakeStorage() }));
afterEach(() => {
  off();
  setDrawerEnv(null);
});

function deps(screen: string): RestoreDeps {
  return {
    screen: () => screen,
    rows: () => [{ name: 'carnivore_a', session_id: 'ses_a' }],
    hasLayout: () => true,
    openSession: vi.fn(() => true),
    openLayout: vi.fn(),
  };
}

function escape(): KeyboardEvent {
  return new KeyboardEvent('keydown', { key: 'Escape', cancelable: true });
}

it('Escape on the dashboard goes back to the previous session', () => {
  const d = deps('launchpad');
  off = registerHomeEscape(d);
  rememberLastView({ kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
  const event = escape();
  expect(handleMenuPageEscape(event, { pageOpen: () => false, close: () => {} })).toBe(true);
  expect(d.openSession).toHaveBeenCalledWith('ses_a', 'carnivore_a');
  expect(event.defaultPrevented).toBe(true);
});

it('Escape does nothing on the dashboard when nothing was open before', () => {
  const d = deps('launchpad');
  off = registerHomeEscape(d);
  expect(handleMenuPageEscape(escape(), { pageOpen: () => false, close: () => {} })).toBe(false);
  expect(d.openSession).not.toHaveBeenCalled();
});

it('Escape is left alone off the dashboard', () => {
  const d = deps('terminal');
  off = registerHomeEscape(d);
  rememberLastView({ kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' });
  expect(handleMenuPageEscape(escape(), { pageOpen: () => false, close: () => {} })).toBe(false);
});
