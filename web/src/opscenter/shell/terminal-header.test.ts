/** @vitest-environment jsdom */
import { expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import TerminalFrame from './fixtures/TerminalFrame.svelte';

test('a terminal publishes one session header in the frame instead of the generic title', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const target = document.createElement('div');
  document.body.appendChild(target);
  const app = mount(TerminalFrame, { target });
  flushSync();
  const header = target.querySelector('.oc-frame-title');
  expect(header?.querySelector('h2')?.textContent).toBe('alpha');
  expect(header?.textContent).toContain('working');
  expect(header?.querySelectorAll('[data-terminal-header]')).toHaveLength(1);
  expect(target.querySelector('.oc-frame-body [data-terminal-header]')).toBeNull();
  expect(header?.querySelector('.cell-tools [data-tool="files"], .cell-options [data-tool="files"]')).not.toBeNull();
  expect(header?.querySelector('[role="status"]')).not.toBeNull();
  await unmount(app);
  target.remove();
  vi.unstubAllGlobals();
});

test('responsive frame layout preserves session palette variables', async () => {
  const { viewport } = await import('../engine/viewport.svelte');
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const target = document.createElement('div');
  document.body.appendChild(target);
  const app = mount(TerminalFrame, { target });
  flushSync();
  const frame = target.querySelector<HTMLElement>('.oc-frame')!;
  frame.dataset.sessionTheme = 'calming';
  frame.style.setProperty('--color-accent', '#41653b');
  frame.style.setProperty('--color-bg', '#f5f4ee');
  try {
    const desktopRows = frame.style.gridTemplateRows;
    viewport.wide = false;
    viewport.phone = true;
    flushSync();
    expect(frame.style.gridTemplateRows).not.toBe(desktopRows);
    expect(frame.style.getPropertyValue('--color-accent')).toBe('#41653b');
    viewport.wide = true;
    viewport.phone = false;
    flushSync();
    expect(frame.style.gridTemplateRows).toBe(desktopRows);
    expect(frame.style.getPropertyValue('--color-accent')).toBe('#41653b');
    expect(frame.style.getPropertyValue('--color-bg')).toBe('#f5f4ee');
  } finally {
    await unmount(app);
    viewport.wide = true;
    viewport.phone = false;
    target.remove();
    vi.unstubAllGlobals();
  }
});
