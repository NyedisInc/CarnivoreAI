/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

let row: Record<string, unknown> = {};
vi.mock('../../opscenter/api', async () => {
  const actual = await vi.importActual<typeof import('../../opscenter/api')>('../../opscenter/api');
  return { ...actual, sessions: { get data() { return [row]; } } };
});
const openPage = vi.fn(async () => ({}));
vi.mock('../browser/select-push.svelte', () => ({ openPage: (...a: unknown[]) => openPage(...(a as [])) }));
vi.mock('../background-work/background-work', async () => ({
  ...(await vi.importActual<object>('../background-work/background-work')),
  fetchBackgroundWork: vi.fn(async () => ({ state: 'ok', family: 'claude', detail: '', as_of: null, owners: 'ok', processes: [] })),
}));
vi.mock('../subagents/subagents', async () => ({
  ...(await vi.importActual<object>('../subagents/subagents')),
  fetchSubagents: vi.fn(async () => ({ state: 'ok', subagents: [] })),
}));
vi.mock('../timers/timers', async () => ({
  ...(await vi.importActual<object>('../timers/timers')),
  fetchTimers: vi.fn(async () => ({ state: 'ok', timers: [] })),
}));

import ControlCenter from './ControlCenter.svelte';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; openPage.mockClear(); });

async function draw(sessionId = 'ses_1'): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(ControlCenter, { target: host, props: { sessionId, focus: 'ports' } });
  flushSync();
  await tick();
  return host;
}

const servers = [
  { port: 8000, url: 'http://localhost:8000', address: '0.0.0.0', process: 'python3.12' },
  { port: 5173, url: 'http://localhost:5173', address: '127.0.0.1', process: 'node' },
];

test('ports list in port order with program and bind; a click offers here or your browser', async () => {
  row = { session: { id: 'ses_1' }, host_key: 'local', local_servers: servers };
  const winOpen = vi.spyOn(window, 'open').mockImplementation(() => null);
  const host = await draw();
  const rows = [...host.querySelectorAll('[data-scc-port]')];
  expect(rows.map((r) => r.getAttribute('data-scc-port'))).toEqual(['5173', '8000']);
  expect(rows[0]!.textContent).toContain('node');
  expect(rows[1]!.querySelector('[data-lan="true"]')).not.toBeNull();

  expect(host.querySelector('[data-scc-open]')).toBeNull();
  (rows[0]!.querySelector('[data-scc-port-open]') as HTMLButtonElement).click();
  flushSync();
  (host.querySelector('[data-scc-open="here"]') as HTMLButtonElement).click();
  flushSync();
  expect(openPage).toHaveBeenCalledWith({ url: 'http://localhost:5173' });
  expect(host.querySelector('[data-scc-open]')).toBeNull();

  (rows[1]!.querySelector('[data-scc-port-open]') as HTMLButtonElement).click();
  flushSync();
  (host.querySelector('[data-scc-open="browser"]') as HTMLButtonElement).click();
  expect(winOpen).toHaveBeenCalledWith('http://localhost:8000', '_blank', 'noopener');
  expect(openPage).toHaveBeenCalledOnce();
  winOpen.mockRestore();
});

test("a paired computer's ports are listed, not openable; none says so", async () => {
  row = { session: { id: 'remote:peer-studio:carnivore_x' }, host_key: 'peer-studio', local_servers: servers };
  let host = await draw('remote:peer-studio:carnivore_x');
  expect(host.querySelectorAll('[data-scc-port]')).toHaveLength(2);
  expect(host.querySelector('[data-scc-port-open]')).toBeNull();
  unmount(app!); app = null; document.body.innerHTML = '';
  row = { session: { id: 'ses_1' }, local_servers: [] };
  host = await draw();
  expect(host.querySelector('[data-scc-empty="ports"]')).not.toBeNull();
});
