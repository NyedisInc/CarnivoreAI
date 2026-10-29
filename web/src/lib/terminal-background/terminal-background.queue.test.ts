/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import TerminalBackgroundButton from './TerminalBackgroundButton.svelte';

installPopoverPolyfill();

const THEME = { id: 'carnivore', name: 'Carnivore', source: 'builtin', background: { image: 'background.png', dim: 0.8 },
  xterm: { background: '#0e1112', foreground: '#eaebed' } };

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.replaceChildren();
});

test('a dim change during a save is written after it with the latest value', async () => {
  const dims: Array<number | null> = [];
  const releases: Array<() => void> = [];
  (globalThis as Record<string, unknown>).TerminalBackground = {
    DEFAULT_DIM: 0.8, minimumDim: () => 0.1, getActiveSession: () => 'cloude_demo', getOverrides: () => ({}),
    setOverride: (_s: string, body: { dim: number | null }) => new Promise((resolve) => { dims.push(body.dim); releases.push(() => resolve({})); }),
    uploadImage: async () => ({}), clearImage: async () => ({}),
  };
  (globalThis as Record<string, unknown>).Themes = { listAll: () => [THEME], getActiveTerminalManifest: () => THEME };
  app = mount(TerminalBackgroundButton as never, { target: document.body, props: {} });
  flushSync();
  document.querySelector<HTMLButtonElement>('.tbg-open')!.click();
  flushSync();
  const range = document.querySelector<HTMLInputElement>('.tbg__range')!;
  range.value = '50';
  range.dispatchEvent(new Event('input', { bubbles: true }));
  range.dispatchEvent(new Event('change', { bubbles: true }));
  await Promise.resolve();
  range.value = '60';
  range.dispatchEvent(new Event('input', { bubbles: true }));
  range.dispatchEvent(new Event('change', { bubbles: true }));
  expect(dims).toEqual([0.5]);
  releases[0]!();
  await new Promise((r) => setTimeout(r, 10));
  expect(dims).toEqual([0.5, 0.6]);
  releases[1]?.();
});
