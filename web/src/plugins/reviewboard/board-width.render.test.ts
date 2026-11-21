/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { boardAnswer, revision } from './fixtures';
import { BOARD_MAX_WIDTH, cappedRoom, widthCap } from './board-model';
import { WIDTH_KEY } from './board-width';

const api = vi.hoisted(() => ({
  fetchBoard: vi.fn(), fetchBoards: vi.fn(), rescan: vi.fn(), mintTicket: vi.fn(), clearScratch: vi.fn(),
  fetchAttachments: vi.fn(async (slug: string) => ({ slug, attachments: [] })), fetchAttachmentBlob: vi.fn(),
}));
vi.mock('./board-api', () => api);
vi.mock('../../lib/resource-push/boot', () => ({
  resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {}, isLive: () => true }),
}));

import BoardScreen from './BoardScreen.svelte';

const ROOM = 1400;

let app: ReturnType<typeof mount> | null = null;

/** Let promises and effects settle. */
async function settle(): Promise<void> {
  for (let i = 0; i < 5; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}

async function open(over: Parameters<typeof revision>[1] = {}): Promise<void> {
  api.fetchBoard.mockResolvedValue(boardAnswer({ revisions: [revision(1, over)], rounds: [] }));
  window.history.replaceState(null, '', '/static/popout.html?tab=reviewboard&board=20261013-bottom-bar');
  app = mount(BoardScreen, { target: document.body });
  await settle();
}

const box = (): HTMLElement => document.querySelector('.rb-box') as HTMLElement;
const iframe = (): HTMLElement => document.querySelector('iframe[data-board-frame]') as HTMLElement;
const key = (): HTMLButtonElement | null => document.querySelector('[data-board-width]');

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('ResizeObserver', class {
    constructor(private cb: ResizeObserverCallback) {}
    observe(el: Element): void {
      const size = [{ inlineSize: ROOM, blockSize: 600 }];
      this.cb([{ target: el, contentRect: { width: ROOM, height: 600 }, borderBoxSize: size, contentBoxSize: size, devicePixelContentBoxSize: size } as unknown as ResizeObserverEntry], this as unknown as ResizeObserver);
    }
    unobserve(): void {}
    disconnect(): void {}
  });
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => ROOM });
  api.mintTicket.mockResolvedValue({ url: '/x', expires_in: 3600, view: 'main' });
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
});

describe('widthCap and cappedRoom', () => {
  it('gives a layer the fixed max and a canvas its own ask, until full width is chosen; no ask is full width', () => {
    expect(widthCap({ layer: { kind: 'questions' } }, false)).toBe(BOARD_MAX_WIDTH);
    expect(widthCap({ layer: { kind: 'rows' } }, true)).toBeNull();
    expect(widthCap({ max_width: 900 }, false)).toBe(900);
    expect(widthCap({ max_width: 900 }, true)).toBeNull();
    expect(widthCap({}, false)).toBeNull();
    expect(widthCap({ max_width: null }, false)).toBeNull();
  });
  it('holds a wide room to the cap and leaves a narrow one or no cap alone', () => {
    expect(cappedRoom(1400, 760)).toBe(760);
    expect(cappedRoom(500, 760)).toBe(500);
    expect(cappedRoom(1400, null)).toBe(1400);
  });
});

describe('a capped board reflows at the cap and is never scaled', () => {
  it('lays a canvas out at its max_width at scale 1, even when its declared viewport is wider', async () => {
    await open({ max_width: 900, viewport: 1200 });
    expect(box().style.getPropertyValue('--rb-scale')).toBe('1');
    expect(box().style.getPropertyValue('--rb-w')).toBe('900px');
    expect(iframe()).not.toBeNull();
  });

  it('lays a layer out at the fixed max at scale 1 whatever its stored viewport', async () => {
    await open({ layer: { kind: 'questions', items: [] }, viewport: 900 });
    expect(box().style.getPropertyValue('--rb-scale')).toBe('1');
    expect(box().style.getPropertyValue('--rb-w')).toBe(`${BOARD_MAX_WIDTH}px`);
  });

  it('reflows a layer at the whole room, still scale 1, once full width is chosen', async () => {
    await open({ layer: { kind: 'questions', items: [] }, viewport: 900 });
    key()!.click();
    await settle();
    expect(box().style.getPropertyValue('--rb-scale')).toBe('1');
    expect(box().style.getPropertyValue('--rb-w')).toBe(`${ROOM}px`);
    expect(box().classList.contains('rb-box--capped')).toBe(false);
  });

  it('still scales an uncapped canvas with a wide declared viewport to fit', async () => {
    await open({ viewport: 2000 });
    expect(Number(box().style.getPropertyValue('--rb-scale'))).toBeLessThan(1);
  });
});

describe('the width key', () => {
  it('is absent and full width when the agent set no max width', async () => {
    await open();
    expect(key()).toBeNull();
    expect(box().classList.contains('rb-box--capped')).toBe(false);
  });

  it('shows when the agent set one, titled for what it does, and remembers full width', async () => {
    await open({ max_width: 900 });
    expect(key()!.title).toBe('full width');
    expect(box().classList.contains('rb-box--capped')).toBe(true);
    key()!.click();
    await settle();
    expect(box().classList.contains('rb-box--capped')).toBe(false);
    expect(key()!.title).toBe('set width');
    expect(localStorage.getItem(WIDTH_KEY)).toBe('1');
    key()!.click();
    await settle();
    expect(box().classList.contains('rb-box--capped')).toBe(true);
    expect(localStorage.getItem(WIDTH_KEY)).toBeNull();
  });

  it('starts at full width when this device chose it', async () => {
    localStorage.setItem(WIDTH_KEY, '1');
    await open({ max_width: 900 });
    expect(box().classList.contains('rb-box--capped')).toBe(false);
  });

  it('shows on a layer board too, which starts capped', async () => {
    await open({ layer: { kind: 'questions', items: [] } });
    expect(key()).not.toBeNull();
    expect(box().classList.contains('rb-box--capped')).toBe(true);
  });
});
