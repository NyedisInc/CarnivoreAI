/** @vitest-environment jsdom */
import { expect, test, vi } from 'vitest';
import { tick } from 'svelte';

vi.mock('../lib/mount', () => ({ mountPanel: () => null }));
vi.mock('../opscenter/App.svelte', () => ({ default: {} }));
vi.mock('./TabPopout.svelte', () => ({ default: {} }));
vi.mock('../opscenter/engine/home-sync.svelte', () => ({ startHomeSync: () => {} }));
vi.mock('../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<typeof import('../opscenter/api/auth.svelte')>()),
  authFetch: vi.fn(async (path: string) => (path === '/cplugs' ? { cplugs: [{ id: 'taskmanager', enabled: false }] } : {})),
}));

test('a plugin switched off on the server is off in the pop-out', async () => {
  window.history.replaceState(null, '', '/static/popout.html?tab=reviewboard&board=20261013-bottom-bar');
  const { taskManagerPopout } = await import('../plugins/taskmanager/popout');
  const { cplugEnabled, cplugEnablement } = await import('../plugins/host/enablement.svelte');
  expect(cplugEnabled(taskManagerPopout.manifest)).toBe(true);

  await import('./main');
  for (let i = 0; i < 8 && !cplugEnablement.read; i += 1) { await Promise.resolve(); await tick(); }

  expect(cplugEnablement.read).toBe(true);
  expect(cplugEnabled(taskManagerPopout.manifest)).toBe(false);
}, 30_000); // the real entry imports the whole pop-out bundle, which takes several seconds cold
