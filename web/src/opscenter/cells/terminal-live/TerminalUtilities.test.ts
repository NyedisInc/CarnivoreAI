/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';
import TerminalUtilities from './TerminalUtilities.svelte';

installPopoverPolyfill();
const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

function setup(controller: unknown, sessionId: string, width = 1200): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalUtilities, { target, props: { controller, sessionId, slot: `terminal:${sessionId}`, width } }));
  flushSync();
  return target;
}

test('connection events affect only their own controller and retain a prior verdict on mount', () => {
  const first = { connectionStatus: { text: 'Connected', className: 'connected' } };
  const second = {};
  const one = setup(first, 'one');
  const two = setup(second, 'two');
  expect(one.querySelector('[role=status]')?.getAttribute('aria-label')).toBe('Connected');
  window.dispatchEvent(new CustomEvent('cloude:terminal-connection', {
    detail: { controller: second, text: 'Disconnected', className: 'error' },
  }));
  flushSync();
  expect(two.querySelector('[role=status]')?.getAttribute('aria-label')).toBe('Disconnected');
  expect(one.querySelector('[role=status]')?.getAttribute('aria-label')).toBe('Connected');
});

test.each([1200, 200])('background changes stay bound to their cell when input focus moves, at width %i', async (width) => {
  const setOverride = vi.fn(async () => ({}));
  const palette = { foreground: '#fff', background: '#000' };
  const minimumDim = vi.fn(() => 0.8);
  vi.stubGlobal('TerminalBackground', {
    DEFAULT_DIM: 0.8, minimumDim, getActiveSession: () => 'other',
    ACTIVE_SESSION_EVENT: 'background-focus', getOverrides: () => ({}), setOverride,
  });
  vi.stubGlobal('Themes', { listAll: () => [{ id: 'picture', background: { image: 'image.png' } }], getActiveTerminalManifest: () => null });
  const target = setup({ _currentTmuxName: () => 'cloude_second', term: { options: { theme: palette } } }, 'second', width);
  (target.querySelector('[data-tool="background"] .tbg-open') as HTMLButtonElement).click();
  flushSync();
  window.dispatchEvent(new CustomEvent('background-focus', { detail: { session: 'cloude_primary' } }));
  flushSync();
  const select = target.querySelector('.tbg__select') as HTMLSelectElement;
  select.value = 'none';
  select.dispatchEvent(new Event('change', { bubbles: true }));
  await Promise.resolve();
  expect(setOverride).toHaveBeenCalledWith('cloude_second', expect.objectContaining({ disabled: true }));
  expect(minimumDim).toHaveBeenCalledWith(palette);
});

test('the background picture is a labelled kebab row at every width, never a strip icon', () => {
  for (const width of [undefined, 200]) {
    const target = setup({ _currentTmuxName: () => 'cloude_second' }, 'second', width);
    expect(target.querySelector('.cell-tools [data-tool="background"]')).toBeNull();
    const button = target.querySelector('.cell-options [data-tool="background"] .tbg-open') as HTMLButtonElement;
    expect(button.getAttribute('role')).toBe('menuitem');
    expect(button.textContent?.trim().length).toBeGreaterThan(0);
  }
});
