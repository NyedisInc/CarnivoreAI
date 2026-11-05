/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { boardAnswer } from './fixtures';

const api = vi.hoisted(() => ({
  fetchBoard: vi.fn(), fetchBoards: vi.fn(), fetchDraft: vi.fn(), mintTicket: vi.fn(),
  fetchAttachments: vi.fn(async (slug: string) => ({ slug, attachments: [] })),
}));
// Only the reads the page makes on load are replaced; every other export of board-api stays the real one.
vi.mock('./board-api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./board-api')>()), ...api }));
vi.mock('../../lib/resource-push/boot', () => ({
  resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {}, isLive: () => true }),
}));
const sdk = vi.hoisted(() => ({ themeChoices: vi.fn(() => []), activeThemeId: vi.fn(() => 'carnivore'), themeTokens: vi.fn(() => ({})) }));
vi.mock('../sdk', async (importOriginal) => ({ ...(await importOriginal<typeof import('../sdk')>()), ...sdk }));

import { registerBoardHeaderKey, resetBoardHeaderKeys } from '../sdk/board-header-keys';
import BoardScreen from './BoardScreen.svelte';
import DummyKey from './fixtures/DummyHeaderKey.svelte';

let app: ReturnType<typeof mount> | null = null;
let shown = true;

async function open(): Promise<void> {
  window.history.replaceState(null, '', '/static/popout.html?tab=reviewboard&board=20261013-bottom-bar');
  app = mount(BoardScreen, { target: document.body });
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  api.fetchBoard.mockResolvedValue(boardAnswer());
  api.fetchBoards.mockResolvedValue({ boards: [] });
  api.fetchDraft.mockResolvedValue(null);
  api.mintTicket.mockResolvedValue({ url: '/v/x', expires_in: 3600, view: 'main' });
  localStorage.clear();
  registerBoardHeaderKey({ id: 'test.dummy', component: DummyKey, enabled: () => shown });
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  resetBoardHeaderKeys();
  vi.unstubAllGlobals();
});

describe('the board header seam', () => {
  it('draws an enabled registered key and hands it the board slug', async () => {
    shown = true;
    await open();
    const key = document.querySelector('[data-dummy-header-key]');
    expect(key).not.toBeNull();
    expect(key!.getAttribute('data-slug')).toBe('20261013-bottom-bar');
  });

  it('leaves a disabled key out', async () => {
    shown = false;
    await open();
    expect(document.querySelector('[data-board-strip]')).not.toBeNull();
    expect(document.querySelector('[data-dummy-header-key]')).toBeNull();
  });
});
