/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import PublicBoard from './PublicBoard.svelte';
import type { AnswerSet, BoardResult, DraftResult, NextResult, PostResult, PublicBoardData } from './board-client';
import type { WatchDocument } from './newer-watch';

const THEME = { '--oc-orange': 'rgb(255, 128, 0)', '--oc-ground-page': 'rgb(16, 16, 16)' };
const LAYER_BOARD: PublicBoardData = {
  title: 'menu', revision: 'r2', viewport: 600, views: [{ id: 'main', label: 'main', frame: '/f/ticket-main' }], prompts: [],
  layer: { kind: 'questions', items: [] }, access: 'answer', theme: THEME, draft: null,
};
const PROMPT_BOARD: PublicBoardData = {
  title: 'bar', revision: 'r1', viewport: 600, views: [{ id: 'main', label: 'main', frame: '/f/ticket-main' }], access: 'answer', theme: null,
  prompts: [{ id: 'padding', kind: 'check', label: 'more padding?', options: [] }],
  draft: { body: { answers: [{ prompt: 'padding', checked: true }] } },
};
const VISIBLE: WatchDocument = { hidden: false, addEventListener: () => undefined, removeEventListener: () => undefined };

let app: ReturnType<typeof mount> | null = null;

interface Opened { save: ReturnType<typeof vi.fn>; load: ReturnType<typeof vi.fn>; send: ReturnType<typeof vi.fn> }

async function open(board: PublicBoardData, extra: { wait?: (revision: string) => Promise<NextResult>; next?: PublicBoardData } = {}): Promise<Opened> {
  let calls = 0;
  const load = vi.fn(async (): Promise<BoardResult> => ({ kind: 'board', board: calls++ === 0 || !extra.next ? board : extra.next }));
  const save = vi.fn(async (_body: { revision: string } & AnswerSet): Promise<DraftResult> => ({ kind: 'saved', changed: true }));
  const send = vi.fn(async (): Promise<PostResult> => ({ kind: 'received', duplicate: false }));
  const wait = extra.wait ?? (async (): Promise<NextResult> => ({ kind: 'fixed' }));
  app = mount(PublicBoard, { target: document.body, props: { load, send, save, wait, doc: VISIBLE } });
  await settle();
  return { save, load, send };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
}

function frameWindow(): { win: Window; sent: Array<Record<string, unknown>> } {
  const frame = document.querySelector('iframe') as HTMLIFrameElement;
  const win = frame.contentWindow as Window;
  const sent: Array<Record<string, unknown>> = [];
  vi.spyOn(win, 'postMessage').mockImplementation(((message: Record<string, unknown>) => { sent.push(message); }) as Window['postMessage']);
  return { win, sent };
}

function fromFrame(win: Window, data: Record<string, unknown>): void {
  window.dispatchEvent(new MessageEvent('message', { data: { rb: 1, ...data }, origin: 'null', source: win }));
}

beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} }));
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  document.documentElement.removeAttribute('style');
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('the owner\'s theme', () => {
  it('paints the questions layer: on the frame\'s ready the page sends the owner\'s palette and the layer strings', async () => {
    await open(LAYER_BOARD);
    const { win, sent } = frameWindow();
    fromFrame(win, { type: 'ready', anchors: [], theme_aware: true });
    const theme = sent.find((m) => m.type === 'theme');
    expect(theme?.vars).toEqual(THEME);
    const strings = sent.find((m) => m.type === 'strings')?.map as Record<string, string> | undefined;
    expect(strings?.['cplug.reviewboard.layer.note']).toBe('note');
  });

  it('wears the palette on the visitor page itself', async () => {
    await open(LAYER_BOARD);
    expect(document.documentElement.style.getPropertyValue('--oc-orange')).toBe('rgb(255, 128, 0)');
  });

  it('takes no message from anything but its own frame in an opaque origin', async () => {
    await open(LAYER_BOARD);
    const { win, sent } = frameWindow();
    window.dispatchEvent(new MessageEvent('message', { data: { rb: 1, type: 'ready' }, origin: 'https://evil.test', source: win }));
    window.dispatchEvent(new MessageEvent('message', { data: { rb: 1, type: 'ready' }, origin: 'null', source: window }));
    expect(sent).toEqual([]);
  });
});

describe('a read only link', () => {
  it('draws no control and says read only', async () => {
    await open({ ...PROMPT_BOARD, access: 'read' });
    expect(document.querySelector('.pb-titlebar .pb-label')?.textContent).toBe('read only');
    expect(document.querySelectorAll('input, textarea, select').length).toBe(0);
    expect(document.querySelector('[data-visitor-send-answers], [data-visitor-send-comment]')).toBeNull();
  });
});

describe('autosave', () => {
  it('redraws the saved draft after a reload', async () => {
    await open(PROMPT_BOARD);
    const yes = document.querySelector<HTMLInputElement>('[data-visitor-answers] input[type=radio]');
    expect(yes?.checked).toBe(true);
  });

  it('saves every change as this browser\'s draft of the revision on screen, after the quiet time', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const { save } = await open(PROMPT_BOARD);
    const no = document.querySelectorAll<HTMLInputElement>('[data-visitor-answers] input[type=radio]')[1]!;
    no.click();
    flushSync();
    expect(save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1600);
    expect(save).toHaveBeenCalledWith({ revision: 'r1', answers: [{ prompt: 'padding', checked: false }] });
  });

  it('autosaves a layer\'s answers from the frame, but never the page\'s own start', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    const { save } = await open(LAYER_BOARD);
    const { win } = frameWindow();
    fromFrame(win, { type: 'payload', payload: { layer: 'questions', v: 1, values: {} } });
    fromFrame(win, { type: 'ready', anchors: [] });
    fromFrame(win, { type: 'payload', payload: { layer: 'questions', v: 1, values: {} } });
    await vi.advanceTimersByTimeAsync(2000);
    expect(save).not.toHaveBeenCalled();
    fromFrame(win, { type: 'payload', payload: { layer: 'questions', v: 1, values: { a: 'yes' } } });
    await vi.advanceTimersByTimeAsync(1600);
    expect(save).toHaveBeenCalledWith({ revision: 'r2', payload: { layer: 'questions', v: 1, values: { a: 'yes' } } });
  });
});

describe('a newer revision', () => {
  it('moves a visitor on the newest revision to the newer one at once and says so', async () => {
    let answered = false;
    const wait = async (): Promise<NextResult> => {
      if (answered) return new Promise<NextResult>(() => undefined);
      answered = true;
      return { kind: 'newer', revision: 'r2' };
    };
    const { load } = await open(PROMPT_BOARD, { wait, next: { ...PROMPT_BOARD, revision: 'r2', draft: null } });
    expect(load).toHaveBeenCalledTimes(2);
    expect(document.querySelector('.pb-meta')?.textContent).toBe('revision r2');
    expect(document.querySelector('[data-visitor-moved]')?.textContent).toBe('moved to newer version r2');
    expect(document.querySelector('[data-visitor-newer]')).toBeNull();
  });

  it('shows no key for a link that never moves', async () => {
    await open(PROMPT_BOARD);
    expect(document.querySelector('[data-visitor-newer]')).toBeNull();
  });
});

describe('the slice 5 review', () => {
  it('a comment names the revision on screen, so it lands there even after a follow link moved', async () => {
    const { send } = await open(PROMPT_BOARD);
    (document.querySelector('[data-visitor-key="comment"]') as HTMLButtonElement).click();
    flushSync();
    (document.querySelector('[data-visitor-comment] textarea') as HTMLTextAreaElement).value = 'tighter';
    document.querySelector('[data-visitor-comment] textarea')!.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    (document.querySelector('[data-visitor-send-comment]') as HTMLButtonElement).click();
    await settle();
    expect(send.mock.calls.map((call) => [call[0], (call[1] as { revision?: string }).revision])).toEqual([['comments', 'r1']]);
  });

  it('a read only link tells a questions layer to draw read only', async () => {
    await open({ ...LAYER_BOARD, access: 'read' });
    const { win, sent } = frameWindow();
    fromFrame(win, { type: 'ready', anchors: [], theme_aware: true });
    expect(sent.find((m) => m.type === 'mode')).toMatchObject({ readonly: true });
  });

  it('a link that answers tells the frame nothing of the kind', async () => {
    await open(LAYER_BOARD);
    const { win, sent } = frameWindow();
    fromFrame(win, { type: 'ready', anchors: [], theme_aware: true });
    expect(sent.find((m) => m.type === 'mode')).toBeUndefined();
  });
});
