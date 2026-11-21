/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { boardAnswer } from './fixtures';

vi.mock('../../lib/mount', () => ({ mountPanel: () => null }));
vi.mock('../../opscenter/App.svelte', () => ({ default: {} }));
vi.mock('../../popout/TabPopout.svelte', () => ({ default: {} }));
vi.mock('../../opscenter/engine/home-sync.svelte', () => ({ startHomeSync: () => {} }));
const api = vi.hoisted(() => ({
  fetchBoard: vi.fn(), fetchBoards: vi.fn(async () => ({ boards: [] })), fetchDraft: vi.fn(async () => null),
  mintTicket: vi.fn(async () => ({ url: '/v/x', expires_in: 3600, view: 'main' })),
  fetchAttachments: vi.fn(async (slug: string) => ({ slug, attachments: [] })),
}));
vi.mock('./board-api', async (original) => ({ ...(await original<typeof import('./board-api')>()), ...api }));
vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<typeof import('../../opscenter/api/auth.svelte')>()),
  authFetch: vi.fn(async (path: string) => {
    if (path === '/cplugs') return { cplugs: [{ id: 'reviewboard', enabled: true, settings: { publicLinksEnabled: true } }] };
    if (path.startsWith('/cplugs/reviewboard/public/visitors')) return { responses: [] };
    return {};
  }),
}));

let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  vi.unstubAllGlobals();
});

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}

test('a board opened in the pop-out shows the share and visitors keys in its title strip', async () => {
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  api.fetchBoard.mockResolvedValue(boardAnswer());
  window.history.replaceState(null, '', '/static/popout.html?tab=reviewboard&board=20261013-bottom-bar');

  await import('../../popout/main');
  await settle();
  const { default: BoardScreen } = await import('./BoardScreen.svelte');
  app = mount(BoardScreen, { target: document.body });
  await settle();

  const tools = document.querySelector('[data-board-strip] .rb-tools');
  expect(tools).not.toBeNull();
  expect(tools?.querySelectorAll('[data-board-share-key]')).toHaveLength(1);
  expect(tools?.querySelectorAll('[data-board-visitors-key]')).toHaveLength(1);
}, 30_000); // the real entry imports the whole pop-out bundle, which takes several seconds cold
