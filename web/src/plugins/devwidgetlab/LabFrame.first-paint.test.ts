/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, tick, unmount } from 'svelte';
import LabFrame from './LabFrame.svelte';
import DrawerChrome from './DrawerChrome.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';
import type { LabSize } from '../sdk/widget-lab';

setLocale('en');

let release: (value: unknown) => void = () => undefined;
vi.mock('./frame-reader', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./frame-reader')>()),
  provideScenario: vi.fn(),
  waitForReport: vi.fn(() => new Promise((resolve) => { release = resolve; })),
  stageBottom: vi.fn(() => 200),
}));

let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

const size = { name: 'm', w: 300, h: 200, viewport: 1600 } as unknown as LabSize;

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
}

describe('the left drawer frame', () => {
  it('stays hidden until the page reports the box the sidebar fills, then shows exactly that box', async () => {
    app = mount(LabFrame, {
      target: document.body,
      props: { spec: { widget: 'core.notes', host: 'drawer', size: 'm', theme: 'carnivore', fixture: 'data', scenario: false, shell: 'sidebar' }, size, scenario: null, title: 'f', onreport: () => undefined },
    });
    flushSync();
    const frame = document.querySelector<HTMLIFrameElement>('iframe.dwl-frame')!;
    expect(frame.style.visibility).toBe('hidden');
    frame.dispatchEvent(new Event('load'));
    await settle();
    expect(frame.style.visibility).toBe('hidden');
    release({ error: null, result: { hasFixture: true, clip: { w: 288, h: 800 } } });
    await settle();
    expect(frame.style.visibility).toBe('');
    expect(document.querySelector<HTMLElement>('.dwl-frame-wrap')!.dataset.box).toBe('288x800');
  });

  it('never hides a grid frame', () => {
    app = mount(LabFrame, {
      target: document.body,
      props: { spec: { widget: 'core.notes', host: 'home', size: 'm', theme: 'carnivore', fixture: 'data', scenario: false }, size, scenario: null, title: 'f', onreport: () => undefined },
    });
    flushSync();
    expect(document.querySelector<HTMLIFrameElement>('iframe.dwl-frame')!.style.visibility).toBe('');
  });
});

describe('the right and bottom drawers\' bar', () => {
  const body = createRawSnippet(() => ({ render: () => '<div class="frame-stand-in"></div>' }));

  for (const dock of ['right', 'bottom'] as const) {
    it(`lights the widget's own icon in its own tone (${dock})`, () => {
      app = mount(DrawerChrome, { target: document.body, props: { dock, title: 'files', icon: { name: 'folder', tone: 'oc-cyan' }, children: body } });
      flushSync();
      const key = document.querySelector<HTMLElement>('[data-key-open]')!;
      expect(key.dataset.icon).toBe('folder');
      expect(key.getAttribute('style')).toContain('--rail-tone: var(--oc-cyan)');
    });
  }
});
