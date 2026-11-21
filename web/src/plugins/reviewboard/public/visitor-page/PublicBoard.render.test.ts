/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import PublicBoard from './PublicBoard.svelte';
import type { BoardResult, PageState, PublicBoardData } from './board-client';
import catalog from '../../catalog.en.js';

const BOARD: PublicBoardData = {
  title: 'bottom bar', revision: 'r2', frame_ttl: 300, summary: 'moved the bar to the bottom', viewport: 1000, max_width: null, expires_at: 1900000000,
  views: [{ id: 'main', label: 'main', frame: '/f/ticket-main' }, { id: 'alt', label: 'dark', frame: '/f/ticket-alt' }],
  prompts: [{ id: 'q1', kind: 'choice', label: 'which bar?', options: [{ id: 'a', label: 'tall' }, { id: 'b', label: 'short' }] }],
};
let app: ReturnType<typeof mount> | null = null;

async function open(result: BoardResult): Promise<void> {
  app = mount(PublicBoard, { target: document.body, props: { load: async () => result } });
  for (let i = 0; i < 4; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
}

beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} }));
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; vi.unstubAllGlobals(); });

describe('a board', () => {
  it('draws the title strip, the revision and the summary', async () => {
    await open({ kind: 'board', board: BOARD });
    expect(document.querySelector('.pb-title')?.textContent).toBe('bottom bar');
    expect(document.querySelector('.pb-meta')?.textContent).toBe('revision r2');
    expect(document.querySelector('.pb-summary')?.textContent).toBe('moved the bar to the bottom');
  });

  it('puts the mockup in a frame that is sandboxed with scripts only, never the same origin, with no referrer', async () => {
    await open({ kind: 'board', board: BOARD });
    const frame = document.querySelector('iframe') as HTMLIFrameElement;
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
    expect(frame.getAttribute('referrerpolicy')).toBe('no-referrer');
    expect(frame.getAttribute('src')).toBe('/f/ticket-main');
  });

  it('switches pages with the segmented control', async () => {
    await open({ kind: 'board', board: BOARD });
    const items = [...document.querySelectorAll<HTMLButtonElement>('.oc-segmented button')];
    expect(items.map((i) => i.textContent)).toEqual(['main', 'dark']);
    items[1]!.click();
    await tick(); flushSync();
    expect(document.querySelector('iframe')?.getAttribute('src')).toBe('/f/ticket-alt');
    expect(items[1]!.getAttribute('aria-checked')).toBe('true');
  });

  it('shows the questions as text and offers nothing to answer, attach or post', async () => {
    await open({ kind: 'board', board: BOARD });
    expect(document.querySelector('.pb-prompts')?.textContent).toContain('which bar?');
    expect(document.querySelector('.pb-prompts')?.textContent).toContain('tall, short');
    expect(document.querySelectorAll('input, textarea, select, form, a, [contenteditable]').length).toBe(0);
    expect(document.querySelectorAll('button').length).toBe(2);
  });

  it('says only the revision it shows, whatever else the answer carries (a link shows one revision)', async () => {
    await open({ kind: 'board', board: { ...BOARD, latest: 'r3', follows: true } as PublicBoardData });
    expect(document.querySelector('.pb-meta')?.textContent).toBe('revision r2');
    expect(document.body.textContent).not.toContain('r3');
  });

  it('draws every agent-written text as text, never as markup: title, summary, page labels, questions and choices', async () => {
    const evil = (what: string): string => `<img src=x onerror=alert('${what}')>`;
    await open({ kind: 'board', board: {
      ...BOARD, title: evil('t'), summary: `<b>${evil('s')}</b>`,
      views: [{ id: 'main', label: evil('v1'), frame: '/f/a' }, { id: 'alt', label: evil('v2'), frame: '/f/b' }],
      prompts: [{ id: 'q1', kind: 'choice', label: evil('p'), options: [{ id: 'a', label: evil('o1') }, { id: 'b', label: evil('o2') }] }],
    } });
    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('b')).toBeNull();
    for (const what of ['t', 's', 'v1', 'v2', 'p', 'o1', 'o2']) expect(document.body.textContent, what).toContain(`onerror=alert('${what}')`);
  });
});

describe('the frame addresses lapse, so the page asks again (review of 3b, M2)', () => {
  const fresh = (n: number): PublicBoardData => ({ ...BOARD, frame_ttl: 3, views: BOARD.views.map((v) => ({ ...v, frame: `/f/${v.id}-${n}` })) });

  async function openClocked(): Promise<{ load: ReturnType<typeof vi.fn>; clock: { t: number } }> {
    const clock = { t: 1_000_000 };
    let calls = 0;
    const load = vi.fn(async (): Promise<BoardResult> => ({ kind: 'board', board: fresh(++calls) }));
    app = mount(PublicBoard, { target: document.body, props: { load, now: () => clock.t } });
    for (let i = 0; i < 4; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
    return { load, clock };
  }
  async function press(label: string): Promise<void> {
    [...document.querySelectorAll<HTMLButtonElement>('.oc-segmented button')].find((b) => b.textContent === label)!.click();
    for (let i = 0; i < 4; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
  }

  it('a view switch inside the lifetime reuses the addresses and asks nothing', async () => {
    const { load, clock } = await openClocked();
    clock.t += 2000;
    await press('dark');
    expect(load).toHaveBeenCalledTimes(1);
    expect(document.querySelector('iframe')?.getAttribute('src')).toBe('/f/alt-1');
  });

  it('a view switch once the addresses are four fifths old asks once and uses the fresh ones', async () => {
    const { load, clock } = await openClocked();
    clock.t += 2500;
    await press('dark');
    expect(load).toHaveBeenCalledTimes(2);
    expect(document.querySelector('iframe')?.getAttribute('src')).toBe('/f/alt-2');
    await press('main');
    expect(load).toHaveBeenCalledTimes(2);
    expect(document.querySelector('iframe')?.getAttribute('src')).toBe('/f/main-2');
  });

  it('there is no timer: time passing alone asks nothing', async () => {
    vi.useFakeTimers();
    try {
      const { load, clock } = await openClocked();
      clock.t += 10 * 60 * 1000;
      vi.advanceTimersByTime(10 * 60 * 1000);
      expect(load).toHaveBeenCalledTimes(1);
    } finally { vi.useRealTimers(); }
  });

  it.each(['limited', 'unavailable'] as const)('a %s answer to the refresh keeps the board and switches with the addresses held', async (state) => {
    const { load, clock } = await openClocked();
    load.mockResolvedValueOnce({ kind: 'state', state });
    clock.t += 2500;
    await press('dark');
    expect(document.querySelector('.pb-note--state')).toBeNull();
    expect(document.querySelector('.pb-title')?.textContent).toBe('bottom bar');
    expect(document.querySelector('iframe')?.getAttribute('src')).toBe('/f/alt-1');
  });

  it('after a refused refresh the next switch tries again', async () => {
    const { load, clock } = await openClocked();
    load.mockResolvedValueOnce({ kind: 'state', state: 'limited' });
    clock.t += 2500;
    await press('dark');
    await press('main');
    expect(load).toHaveBeenCalledTimes(3);
    expect(document.querySelector('iframe')?.getAttribute('src')).toBe('/f/main-2');
  });

  it('a link that ended meanwhile shows its state instead of a dead frame', async () => {
    const { load, clock } = await openClocked();
    load.mockResolvedValueOnce({ kind: 'state', state: 'ended' });
    clock.t += 2500;
    await press('dark');
    expect(document.querySelector('.pb-note--state')?.getAttribute('data-state')).toBe('ended');
    expect(document.querySelector('iframe')).toBeNull();
  });
});

describe('every state', () => {
  const STATES: PageState[] = ['invalid', 'ended', 'limited', 'misrouted', 'unavailable'];
  it.each(STATES)('%s draws its own catalog sentence and no frame', async (state) => {
    await open({ kind: 'state', state });
    const note = document.querySelector('.pb-note--state') as HTMLElement;
    const text = (catalog as unknown as Record<string, string>)[`cplug.reviewboard.public.page.state.${state}`];
    expect(text).toBeTruthy();
    expect(note.textContent).toBe(text);
    expect(note.textContent).toBe(note.textContent?.toLowerCase());
    expect(note.getAttribute('data-state')).toBe(state);
    expect(document.querySelector('iframe')).toBeNull();
  });
  it('the five sentences are different', () => {
    const all = STATES.map((s) => (catalog as unknown as Record<string, string>)[`cplug.reviewboard.public.page.state.${s}`]);
    expect(new Set(all).size).toBe(5);
  });
});
