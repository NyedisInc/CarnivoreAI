/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { boardAnswer } from '../reviewboard/fixtures';

const api = vi.hoisted(() => ({
  fetchBoard: vi.fn(), fetchBoards: vi.fn(), fetchDraft: vi.fn(), mintTicket: vi.fn(),
  fetchAttachments: vi.fn(async (slug: string) => ({ slug, attachments: [] })),
}));
// Only the reads the page makes on load are replaced; every other export of board-api stays the real one.
vi.mock('../reviewboard/board-api', async (importOriginal) => ({ ...(await importOriginal<typeof import('../reviewboard/board-api')>()), ...api }));
vi.mock('../../lib/resource-push/boot', () => ({
  resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {}, isLive: () => true }),
}));
const sdk = vi.hoisted(() => ({ cplugEnabled: vi.fn(), themeChoices: vi.fn(() => []), activeThemeId: vi.fn(() => 'carnivore'), themeTokens: vi.fn(() => ({})) }));
vi.mock('../sdk', async (importOriginal) => ({ ...(await importOriginal<typeof import('../sdk')>()), ...sdk }));

import { resetBoardHeaderKeys } from '../sdk/board-header-keys';
import BoardScreen from '../reviewboard/BoardScreen.svelte';
import { publicboardCplug } from './index';

let app: ReturnType<typeof mount> | null = null;

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
  publicboardCplug.start?.();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  resetBoardHeaderKeys();
  vi.unstubAllGlobals();
});

describe('the share key in the board header', () => {
  it('is drawn while the plugin is on', async () => {
    sdk.cplugEnabled.mockReturnValue(true);
    await open();
    expect(document.querySelector('[data-board-strip]')).not.toBeNull();
    expect(document.querySelectorAll('[data-board-share-key]')).toHaveLength(1);
  });

  it('is not drawn while the plugin is off', async () => {
    sdk.cplugEnabled.mockReturnValue(false);
    await open();
    expect(document.querySelector('[data-board-strip]')).not.toBeNull();
    expect(document.querySelector('[data-board-share-key]')).toBeNull();
  });
});
