/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import LabFrame from './LabFrame.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';
import { CORE_ID, buildWidgetMenu, setMenuPreviewOnly } from '../../lib/widget-menu/model';
import * as reader from './frame-reader';
import { MENU_CHOOSE, MENU_HIDE, MENU_SHOW, type LabSize } from '../sdk/widget-lab';

setLocale('en');

vi.mock('./frame-reader', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./frame-reader')>()),
  provideScenario: vi.fn(),
  waitForReport: vi.fn(async () => ({ error: null, result: { hasFixture: true } })),
  stageBottom: vi.fn(() => 200),
}));

let app: ReturnType<typeof mount> | null = null;

Object.assign(HTMLElement.prototype, { showPopover: () => undefined, hidePopover: () => undefined });

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  setMenuPreviewOnly(null);
  vi.mocked(reader.waitForReport).mockClear();
});

const size = { name: 'm', w: 300, h: 200, viewport: 1280 } as unknown as LabSize;

describe('the widget menu in a preview frame', () => {
  it('draws the frame\'s menu in this page at the mapped point, hands a chosen item back to the frame by its path, and never changes the frame\'s box', async () => {
    app = mount(LabFrame, {
      target: document.body,
      props: { spec: { widget: 'core.notes', host: 'home', size: 'm', theme: 'carnivore', fixture: 'data', scenario: false }, size, scenario: null, title: 'f', onreport: () => undefined },
    });
    const frame = document.querySelector<HTMLIFrameElement>('iframe.dwl-frame')!;
    const wrap = document.querySelector<HTMLElement>('.dwl-frame-wrap')!;
    flushSync();
    frame.dispatchEvent(new Event('load'));
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
    const sent = vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation(() => undefined);
    const boxBefore = [wrap.dataset.box, wrap.style.width, wrap.style.height, frame.getAttribute('width')];
    const post = async (data: object) => {
      window.dispatchEvent(new MessageEvent('message', { data, origin: location.origin, source: frame.contentWindow }));
      await tick();
      flushSync();
    };
    await post({ type: MENU_SHOW, id: 7, label: 'widget menu', anchor: { left: 10, top: 20, right: 30, bottom: 40 }, nodes: [{ id: 'a', label: 'show header', runs: true }, { id: 'b', label: 'pop out', blocked: 'preview only' }] });
    expect(document.body.textContent).toContain('show header');
    expect(document.body.textContent).toContain('pop out');
    expect([wrap.dataset.box, wrap.style.width, wrap.style.height, frame.getAttribute('width')]).toEqual(boxBefore);
    const item = [...document.querySelectorAll<HTMLElement>('button, [role="menuitem"]')].find((el) => el.textContent?.includes('show header'))!;
    item.click();
    await tick();
    expect(sent).toHaveBeenCalledWith({ type: MENU_CHOOSE, id: 7, path: ['a'] }, location.origin);
    await post({ type: MENU_HIDE, id: 7 });
    for (let i = 0; i < 5; i += 1) { await new Promise((r) => setTimeout(r, 20)); flushSync(); }
    expect(document.body.textContent).not.toContain('show header');
    expect([wrap.dataset.box, wrap.style.width, wrap.style.height]).toEqual(boxBefore.slice(0, 3));
  });

  it('ignores a menu message that did not come from its own frame', async () => {
    app = mount(LabFrame, {
      target: document.body,
      props: { spec: { widget: 'core.notes', host: 'home', size: 'm', theme: 'carnivore', fixture: 'data', scenario: false }, size, scenario: null, title: 'f', onreport: () => undefined },
    });
    flushSync();
    window.dispatchEvent(new MessageEvent('message', { data: { type: MENU_SHOW, id: 1, label: 'x', anchor: null, nodes: [{ id: 'a', label: 'intruder' }] }, origin: location.origin, source: window }));
    await tick();
    flushSync();
    expect(document.body.textContent).not.toContain('intruder');
  });

  it('blocks pop out and close in a preview as "preview only", and runs the in-widget items', () => {
    setMenuPreviewOnly([CORE_ID.popOut, CORE_ID.closeWidget]);
    let toggled = false;
    const nodes = buildWidgetMenu({ editing: false, onClose: () => undefined, popOut: () => undefined, close: { run: () => undefined }, header: { shown: true, toggle: () => { toggled = true; } } });
    const byId = (id: string) => nodes.find((n) => n.id === id)!;
    expect(byId(CORE_ID.popOut).blocked).toBe('preview only');
    expect(byId(CORE_ID.closeWidget).blocked).toBe('preview only');
    expect(byId(CORE_ID.showHeader).blocked).toBeUndefined();
    byId(CORE_ID.showHeader).run!();
    expect(toggled).toBe(true);
  });
});
