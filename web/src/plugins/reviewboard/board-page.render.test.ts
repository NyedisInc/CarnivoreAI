/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { boardAnswer } from './fixtures';

const api = vi.hoisted(() => ({
  fetchBoard: vi.fn(),
  fetchBoards: vi.fn(),
  rescan: vi.fn(),
  mintTicket: vi.fn(),
  clearScratch: vi.fn(),
  fetchAttachments: vi.fn(async (slug: string) => ({ slug, attachments: [] })), fetchAttachmentBlob: vi.fn(),
}));
vi.mock('./board-api', () => api);
vi.mock('../../lib/resource-push/boot', () => ({
  resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {}, isLive: () => true }),
}));

import BoardScreen from './BoardScreen.svelte';

let app: ReturnType<typeof mount> | null = null;

/** Let promises and effects settle. */
async function settle(): Promise<void> {
  for (let i = 0; i < 5; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}

async function open(search: string): Promise<void> {
  window.history.replaceState(null, '', `/static/popout.html${search}`);
  app = mount(BoardScreen, { target: document.body });
  await settle();
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  api.fetchBoard.mockResolvedValue(boardAnswer());
  api.fetchBoards.mockResolvedValue({ boards: [{ slug: '20261013-bottom-bar', status: 'ok', title: 'bottom bar', revisions: 3, rounds: 1, state: 'your_turn', last_activity: null }] });
  api.mintTicket.mockImplementation(async (_slug: string, revision: string, view: string) => ({
    url: `/api/v1/cplugs/reviewboard/view/ticket-${revision}-${view}`, expires_in: 3600, view,
  }));
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

const frame = (): HTMLIFrameElement => document.querySelector('iframe[data-board-frame]') as HTMLIFrameElement;
const revisionButtons = (): string[] => [...document.querySelectorAll('[data-history="revision"]')].map((b) => b.textContent!.trim());

describe('the mockup frame', () => {
  it('is sandboxed with allow-scripts ONLY, never allow-same-origin, and loads the ticketed viewer path', async () => {
    await open('?tab=reviewboard&board=20261013-bottom-bar');
    expect(frame()).not.toBeNull();
    expect(frame().getAttribute('sandbox')).toBe('allow-scripts');
    expect(frame().getAttribute('sandbox')!.split(/\s+/)).not.toContain('allow-same-origin');
    expect(frame().getAttribute('referrerpolicy')).toBe('no-referrer');
    expect(frame().getAttribute('src')).toBe('/api/v1/cplugs/reviewboard/view/ticket-r3-main');
  });

  it('hears its own window and DROPS a message from any other source', async () => {
    await open('?tab=reviewboard&board=20261013-bottom-bar');
    const post = (source: unknown) => window.dispatchEvent(new MessageEvent('message', {
      source: source as MessageEventSource, origin: 'null', data: { rb: 1, type: 'anchor', anchor: 'buttons' },
    }));
    post(window);
    post(null);
    flushSync();
    expect(document.querySelector('[data-board-pointed]')).toBeNull();
    post(frame().contentWindow);
    flushSync();
    expect(document.querySelector('[data-board-pointed]')?.textContent).toContain('button row');
    expect(document.querySelector('[data-board-pointed]')?.textContent).toContain('which row');
  });
});

describe('the history bar', () => {
  it('opens on the newest revision, steps back and forward, and comes back to current', async () => {
    await open('?tab=reviewboard&board=20261013-bottom-bar');
    expect(revisionButtons()).toEqual(['r1', 'r2', 'r3']);
    expect(document.querySelectorAll('[data-history="round"]')).toHaveLength(1);
    const current = () => document.querySelector('[data-history="revision"][aria-current="true"]')?.textContent?.trim();
    expect(current()).toBe('r3');
    const [back, forward] = [...document.querySelectorAll('[data-board-strip] .rb-tools [data-btn]')] as HTMLButtonElement[];
    expect(forward!.disabled).toBe(true);
    back!.click();
    await settle();
    expect(current()).toBe('r2');
    expect(frame().getAttribute('src')).toBe('/api/v1/cplugs/reviewboard/view/ticket-r2-main');
    (document.querySelectorAll('[data-history="revision"]')[0] as HTMLButtonElement).click();
    await settle();
    expect(current()).toBe('r1');
    expect(back!.disabled).toBe(true);
    (document.querySelector('[data-back-current]') as HTMLButtonElement).click();
    await settle();
    expect(current()).toBe('r3');
    expect(document.querySelector('[data-back-current]')).toBeNull();
  });

  it('opens at the revision in the address', async () => {
    await open('?tab=reviewboard&board=20261013-bottom-bar&rev=r1');
    expect(frame().getAttribute('src')).toBe('/api/v1/cplugs/reviewboard/view/ticket-r1-main');
  });
});

describe('the page with no board in the address', () => {
  it('lists the boards and opens the one picked', async () => {
    await open('?tab=reviewboard');
    expect(frame()).toBeNull();
    (document.querySelector('[data-board-row]') as HTMLButtonElement).click();
    await settle();
    expect(api.fetchBoard).toHaveBeenCalledWith('20261013-bottom-bar');
    expect(frame()).not.toBeNull();
    expect(window.location.search).toContain('board=20261013-bottom-bar');
  });
});

describe('a scratch board (#1758)', () => {
  it('offers the clear key only on a scratch board, asks first, then clears and shows the list', async () => {
    await open('?tab=reviewboard&board=20261013-bottom-bar');
    expect(document.querySelector('[data-board-clear]')).toBeNull();
    unmount(app!);
    app = null;
    api.fetchBoard.mockResolvedValue(boardAnswer({ ext: { scratch: { v: 1 } } }));
    api.clearScratch.mockResolvedValue({ slug: '20261013-bottom-bar', revisions: 3, files: 2, bytes: 10 });
    await open('?tab=reviewboard&board=20261013-bottom-bar');
    (document.querySelector('[data-board-clear]') as HTMLButtonElement).click();
    await settle();
    expect(api.clearScratch).not.toHaveBeenCalled();
    expect(document.querySelector('[data-board-clear-confirm][role="alertdialog"].popup-focus [data-btn="danger"]')).not.toBeNull();
    (document.querySelector('[data-board-clear-go]') as HTMLButtonElement).click();
    await settle();
    expect(api.clearScratch).toHaveBeenCalledWith('20261013-bottom-bar');
    expect(window.location.search).not.toContain('board=');
    expect(document.querySelector('[data-board-row]')).not.toBeNull();
  });
});
