/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { boardAnswer, revision } from './fixtures';
import type { PayloadDraft } from './board-model';
import { AUTOSAVE_MS, ECHO_MS } from './payload-loop.svelte';

const api = vi.hoisted(() => ({
  fetchBoard: vi.fn(), fetchBoards: vi.fn(), rescan: vi.fn(), mintTicket: vi.fn(), clearScratch: vi.fn(),
  fetchDraft: vi.fn(), saveDraft: vi.fn(), deleteDraft: vi.fn(), sendRoundKept: vi.fn(), resendRound: vi.fn(), relinkTask: vi.fn(), fetchTasks: vi.fn(),
  savePayloadDraft: vi.fn(),
  fetchAttachments: vi.fn(async (slug: string) => ({ slug, attachments: [] })), fetchAttachmentBlob: vi.fn(),
}));
vi.mock('./board-api', () => api);
vi.mock('../../lib/resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {}, isLive: () => true }) }));

import BoardScreen from './BoardScreen.svelte';

let app: ReturnType<typeof mount> | null = null;
const PICKS = { aw: { 'aw-002': 'ok', 'aw-003': 'ok', 'aw-004': 'ok', 'aw-005': 'push' } };
const NEWER = { aw: { 'aw-002': 'ok', 'aw-005': 'later' } };
const READY = { rb: 1, type: 'ready', anchors: [], theme_aware: true };

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}
const frame = (): HTMLIFrameElement => document.querySelector('iframe[data-board-frame]') as HTMLIFrameElement;
async function from(data: unknown): Promise<void> {
  window.dispatchEvent(new MessageEvent('message', { source: frame().contentWindow as MessageEventSource, origin: 'null', data }));
  await settle();
}
function board(draft?: PayloadDraft) {
  return boardAnswer({ revisions: [revision(1), revision(2), revision(3, { prompts: [], anchors: [], payload_mode: true,
    saves: [{ n: 1, at: '2026-10-14T10:00:00Z', payload: PICKS, note: 'aw-005 push' }], ...(draft ? { draft } : {}) })] });
}
async function open(): Promise<void> {
  window.history.replaceState(null, '', '/static/popout.html?tab=reviewboard&board=20261013-bottom-bar');
  app = mount(BoardScreen, { target: document.body });
  await settle();
}
async function close(): Promise<void> {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  await settle();
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  api.fetchBoard.mockResolvedValue(board());
  api.fetchBoards.mockResolvedValue({ boards: [] });
  api.fetchDraft.mockResolvedValue(null);
  api.fetchTasks.mockResolvedValue([]);
  api.savePayloadDraft.mockResolvedValue({ revision: 'r3', draft: { at: 'x' }, etag: 'e', changed: true });
  api.mintTicket.mockImplementation(async (_s: string, r: string, v: string) => ({ url: `/v/${r}-${v}`, expires_in: 3600, view: v }));
});

afterEach(async () => {
  await close();
  vi.clearAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('the page always gets the newest state after the frame says ready', () => {
  it('on a first mount: the newest save', async () => {
    await open();
    const spy = vi.spyOn(frame().contentWindow!, 'postMessage');
    await from(READY);
    expect(spy).toHaveBeenCalledWith({ rb: 1, type: 'load', payload: PICKS, save: 1 }, '*');
  });

  it('RE-MOUNT (switch to another tab and back): a fresh board page hands the saved picks over even though the page posted its empty default first', async () => {
    await open();
    await from(READY);
    await close();
    await open();
    const spy = vi.spyOn(frame().contentWindow!, 'postMessage');
    await from({ rb: 1, type: 'payload', payload: { aw: {} } });
    await from(READY);
    await from({ rb: 1, type: 'payload', payload: { aw: {} } });
    expect(spy).toHaveBeenCalledWith({ rb: 1, type: 'load', payload: PICKS, save: 1 }, '*');
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS + ECHO_MS);
    expect(api.savePayloadDraft).not.toHaveBeenCalled();
    expect((document.querySelector('[data-payload-position]') as HTMLElement).textContent).toBe('save 1 of 1');
  });

  it('TAB RETURN / RELOAD with the board page still mounted: the frame says ready again and gets the picks again, not the empty default it posted', async () => {
    await open();
    await from(READY);
    await vi.advanceTimersByTimeAsync(ECHO_MS + 10);
    const spy = vi.spyOn(frame().contentWindow!, 'postMessage');
    await from(READY);
    await from({ rb: 1, type: 'payload', payload: { aw: {} } });
    await from(READY);
    expect(spy.mock.calls.filter((c) => (c[0] as { type: string }).type === 'load').every((c) => JSON.stringify((c[0] as { payload: unknown }).payload) === JSON.stringify(PICKS))).toBe(true);
    expect(spy.mock.calls.filter((c) => (c[0] as { type: string }).type === 'load').length).toBeGreaterThanOrEqual(2);
  });

  it('the draft wins when it is newer than the newest save, and the numbered save wins when it is newer than the draft', async () => {
    api.fetchBoard.mockResolvedValue(board({ at: '2026-10-14T11:00:00Z', payload: NEWER }));
    await open();
    let spy = vi.spyOn(frame().contentWindow!, 'postMessage');
    await from(READY);
    expect(spy).toHaveBeenCalledWith({ rb: 1, type: 'load', payload: NEWER, save: null }, '*');
    await close();
    api.fetchBoard.mockResolvedValue(board({ at: '2026-10-14T09:00:00Z', payload: NEWER }));
    await open();
    spy = vi.spyOn(frame().contentWindow!, 'postMessage');
    await from(READY);
    expect(spy).toHaveBeenCalledWith({ rb: 1, type: 'load', payload: PICKS, save: 1 }, '*');
  });

  it('a pending autosave is written when the board page is unmounted, before the next mount reads it', async () => {
    await open();
    await from(READY);
    await vi.advanceTimersByTimeAsync(ECHO_MS + 10);
    await from({ rb: 1, type: 'payload', payload: NEWER });
    expect(api.savePayloadDraft).not.toHaveBeenCalled();
    await close();
    expect(api.savePayloadDraft).toHaveBeenCalledWith('20261013-bottom-bar', { revision: 'r3', payload: NEWER }, true);
  });
});
