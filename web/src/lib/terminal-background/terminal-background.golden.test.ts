/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import TerminalBackgroundButton from './TerminalBackgroundButton.svelte';
import { recorded, reframed, snapshot } from '../dialog-frame/goldens';

/** The move's only intended change: the frame is `AnchoredPopup`'s, which adds its own class. */
const FRAME = { addClasses: ['oc-anchored'] };

installPopoverPolyfill();

const THEME = { id: 'carnivore', name: 'Carnivore', source: 'builtin', background: { image: 'background.png', dim: 0.8 },
  xterm: { background: '#0e1112', foreground: '#eaebed' } };

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.replaceChildren();
});

test('the popover renders its recorded markup', () => {
  (globalThis as Record<string, unknown>).TerminalBackground = {
    DEFAULT_DIM: 0.8, minimumDim: () => 0.79, getActiveSession: () => 'cloude_demo', getOverrides: () => ({}),
    setOverride: async () => ({}), uploadImage: async () => ({}), clearImage: async () => ({}),
  };
  (globalThis as Record<string, unknown>).Themes = { listAll: () => [THEME], getActiveTerminalManifest: () => THEME };
  app = mount(TerminalBackgroundButton as never, { target: document.body, props: {} });
  flushSync();
  document.querySelector<HTMLButtonElement>('.tbg-open')!.click();
  flushSync();
  const now = snapshot(document.querySelector('.tbg-pop')!);
  expect(now).toBe(reframed(recorded('terminal-background', now), FRAME));
});
