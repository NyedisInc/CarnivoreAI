/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { readFileSync } from 'node:fs';
import PublicBoard from './PublicBoard.svelte';
import type { BoardResult, DraftResult, NextResult, PostResult, PublicBoardData } from './board-client';
import type { WatchDocument } from './newer-watch';

const VISIBLE: WatchDocument = { hidden: false, addEventListener: () => undefined, removeEventListener: () => undefined };
const STRIP = [{ revision: 'r1', answered: true }, { revision: 'r2', answered: false }, { revision: 'r3', answered: false }];
const make = (revision: string, strip = STRIP): PublicBoardData => ({
  title: 'bar', revision, viewport: 600, views: [{ id: 'main', label: 'main', frame: `/f/${revision}` }], access: 'answer', theme: null,
  prompts: [{ id: 'padding', kind: 'check', label: 'more padding?', options: [] }], draft: null, revisions: strip,
});

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
}

async function open(boards: Record<string, PublicBoardData>, newest: string | (() => string), wait?: (revision: string) => Promise<NextResult>) {
  const load = vi.fn(async (revision?: string): Promise<BoardResult> => ({ kind: 'board', board: boards[revision ?? (typeof newest === 'function' ? newest() : newest)]! }));
  const save = vi.fn(async (): Promise<DraftResult> => ({ kind: 'saved', changed: true }));
  const send = vi.fn(async (): Promise<PostResult> => ({ kind: 'received', duplicate: false }));
  const asked: string[] = [];
  const hold = wait ?? (async (revision: string): Promise<NextResult> => { asked.push(revision); return new Promise<NextResult>(() => undefined); });
  app = mount(PublicBoard, { target: document.body, props: { load, send, save, wait: hold, doc: VISIBLE } });
  await settle();
  return { load, save, asked };
}
const chips = (): HTMLButtonElement[] => [...document.querySelectorAll<HTMLButtonElement>('[data-visitor-rev]')];

beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} }));
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('the strip', () => {
  it('draws a chip per served revision, the shown one pressed, and marks where this visitor answered', async () => {
    await open({ r3: make('r3') }, 'r3');
    expect(chips().map((c) => c.getAttribute('data-visitor-rev'))).toEqual(['r1', 'r2', 'r3']);
    expect(chips().map((c) => c.getAttribute('aria-pressed'))).toEqual(['false', 'false', 'true']);
    expect(chips().map((c) => c.hasAttribute('data-answered'))).toEqual([true, false, false]);
    expect(document.querySelector('[data-visitor-bar]')!.contains(chips()[0]!)).toBe(true);
  });

  it('is not drawn for a link that served one revision (a pinned link shows its one revision)', async () => {
    await open({ r1: make('r1', [{ revision: 'r1', answered: false }]) }, 'r1');
    expect(chips()).toEqual([]);
    expect(document.querySelector('.pb-meta')?.textContent).toBe('revision r1');
  });

  it('a press reviews that revision: the board is read again naming it, and its chip is the pressed one', async () => {
    const { load } = await open({ r1: make('r1'), r3: make('r3') }, 'r3');
    chips()[0]!.click();
    await settle();
    expect(load).toHaveBeenLastCalledWith('r1');
    expect(chips().map((c) => c.getAttribute('aria-pressed'))).toEqual(['true', 'false', 'false']);
    expect(document.querySelector('iframe')!.getAttribute('src')).toContain('/f/r1');
  });

  it('writes what the visitor answers while reviewing to THAT revision', async () => {
    vi.useFakeTimers();
    const { save } = await open({ r1: make('r1'), r3: make('r3') }, 'r3');
    chips()[0]!.click();
    await settle();
    const pick = document.querySelector<HTMLInputElement>('input[type="radio"], input[type="checkbox"]')!;
    pick.checked = true;
    pick.dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    await vi.advanceTimersByTimeAsync(2000);
    await settle();
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ revision: 'r1' }));
    expect(save).not.toHaveBeenCalledWith(expect.objectContaining({ revision: 'r3' }));
    vi.useRealTimers();
  });
});

describe('stale answers (R7-4)', () => {
  it('the last gesture wins: a slow answer for an earlier press never replaces the revision the visitor chose after it', async () => {
    let slowR1: (r: BoardResult) => void = () => undefined;
    const load = vi.fn((revision?: string): Promise<BoardResult> => revision === 'r1'
      ? new Promise<BoardResult>((done) => { slowR1 = done; })
      : Promise.resolve({ kind: 'board', board: make(revision ?? 'r3') }));
    const save = vi.fn(async (): Promise<DraftResult> => ({ kind: 'saved', changed: true }));
    app = mount(PublicBoard, { target: document.body, props: { load, save, send: vi.fn(async (): Promise<PostResult> => ({ kind: 'received', duplicate: false })), wait: () => new Promise<NextResult>(() => undefined), doc: VISIBLE } });
    await settle();
    chips()[0]!.click();
    await settle();
    chips()[1]!.click();
    await settle();
    slowR1({ kind: 'board', board: make('r1') });
    await settle();
    expect(chips().map((c) => c.getAttribute('aria-pressed'))).toEqual(['false', 'true', 'false']);
    expect(document.querySelector('iframe')!.getAttribute('src')).toContain('/f/r2');
  });
});

describe('the view-switch refresh (R8-2)', () => {
  it('a refresh still in flight when the visitor presses a revision chip never paints the older revision under the new press', async () => {
    const two = (revision: string): PublicBoardData => ({ ...make(revision), frame_ttl: 100, views: [{ id: 'main', label: 'main', frame: `/f/${revision}` }, { id: 'alt', label: 'alt', frame: `/f/${revision}-alt` }] });
    let refresh: (r: BoardResult) => void = () => undefined;
    let calls = 0;
    const load = vi.fn((revision?: string): Promise<BoardResult> => {
      calls += 1;
      if (calls === 2) return new Promise<BoardResult>((done) => { refresh = done; });
      return Promise.resolve({ kind: 'board', board: two(revision ?? 'r3') });
    });
    let clock = 0;
    app = mount(PublicBoard, { target: document.body, props: { load, now: () => clock, wait: () => new Promise<NextResult>(() => undefined), doc: VISIBLE } });
    await settle();
    clock = 90_000;
    document.querySelectorAll<HTMLButtonElement>('[role="radio"]')[1]!.click();
    await settle();
    chips()[0]!.click();
    await settle();
    refresh({ kind: 'board', board: two('r3') });
    await settle();
    expect(chips().map((c) => c.getAttribute('aria-pressed'))).toEqual(['true', 'false', 'false']);
  });
});

describe('a newer revision', () => {
  let said = false;
  const once = (next: string): ((revision: string) => Promise<NextResult>) => {
    said = false;
    return async () => (said ? new Promise<NextResult>(() => undefined) : ((said = true), { kind: 'newer', revision: next }));
  };

  it('moves a visitor on the newest revision to it at once, and keeps the newer key as the notice', async () => {
    const strip4 = [...STRIP, { revision: 'r4', answered: false }];
    const { load } = await open({ r3: make('r3'), r4: make('r4', strip4) }, () => (said ? 'r4' : 'r3'), once('r4'));
    expect(load).toHaveBeenCalledTimes(2);
    expect(load).toHaveBeenLastCalledWith(undefined);
    expect(chips().map((c) => c.getAttribute('aria-pressed'))).toEqual(['false', 'false', 'false', 'true']);
    expect(document.querySelector('[data-visitor-moved]')?.textContent).toBe('moved to newer version r4');
    expect(document.querySelector('[data-visitor-newer]')).toBeNull();
  });

  it('drops the moved notice once the visitor picks a revision themselves (it must not stay under an older one)', async () => {
    const strip4 = [...STRIP, { revision: 'r4', answered: false }];
    await open({ r1: make('r1', strip4), r3: make('r3'), r4: make('r4', strip4) }, () => (said ? 'r4' : 'r3'), once('r4'));
    expect(document.querySelector('[data-visitor-moved]')).not.toBeNull();
    chips()[0]!.click();
    await settle();
    expect(document.querySelector('[data-visitor-moved]')).toBeNull();
  });

  it('does not pull a visitor away from an older revision they are reviewing: it offers the key', async () => {
    const strip4 = [...STRIP, { revision: 'r4', answered: false }];
    let release: (answer: NextResult) => void = () => undefined;
    const wait = (): Promise<NextResult> => new Promise((done) => { release = done; });
    const { load } = await open({ r1: make('r1', strip4), r3: make('r3'), r4: make('r4', strip4) }, 'r3', wait);
    chips()[0]!.click();
    await settle();
    release({ kind: 'newer', revision: 'r4' });
    await settle();
    expect(load).toHaveBeenLastCalledWith('r1');
    expect(document.querySelector('[data-visitor-newer]')?.textContent).toBe('newer version r4');
    expect(document.querySelector('[data-visitor-moved]')).toBeNull();
  });

  it('the held wait watches the newest revision, not the one under review', async () => {
    const { asked } = await open({ r1: make('r1'), r3: make('r3') }, 'r3');
    chips()[0]!.click();
    await settle();
    expect(new Set(asked)).toEqual(new Set(['r3']));
  });
});

describe('the bar stays thin', () => {
  it('the strip rule sits in the title bar and takes no row of its own', () => {
    const css = readFileSync(`${process.cwd()}/src/cplugs/reviewboard/public/visitor-page/public.css`, 'utf8');
    expect(css).toMatch(/\.pb-revs\s*\{[^}]*display:\s*inline-flex/);
  });
});
