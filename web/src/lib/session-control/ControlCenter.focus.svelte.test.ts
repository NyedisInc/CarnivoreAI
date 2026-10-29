/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import ControlCenter from './ControlCenter.svelte';

vi.mock('../../opscenter/api', async () => {
  const actual = await vi.importActual<typeof import('../../opscenter/api')>('../../opscenter/api');
  return { ...actual, sessions: { get data() { return [{ session: { id: 'ses_1' }, agent_family: 'claude' }]; } } };
});
vi.mock('../background-work/background-work', async () => {
  const actual = await vi.importActual<typeof import('../background-work/background-work')>('../background-work/background-work');
  return { ...actual, fetchBackgroundWork: vi.fn(async () => ({ state: 'ok', family: 'claude', detail: '', as_of: null, owners: 'ok', processes: [] })) };
});
vi.mock('../subagents/subagents', async () => {
  const actual = await vi.importActual<typeof import('../subagents/subagents')>('../subagents/subagents');
  return { ...actual, fetchSubagents: vi.fn(async () => ({ state: 'ok', family: 'claude', conversation_uuid: 'u', detail: '', as_of: null, counts: null, subagents: [] })) };
});
vi.mock('../timers/timers', async () => {
  const actual = await vi.importActual<typeof import('../timers/timers')>('../timers/timers');
  return { ...actual, fetchTimers: vi.fn(async () => ({ state: 'ok', family: 'claude', conversation_uuid: 'u', process: 'alive', process_started_at: null, counts: null, next_fire_at: null, background: null, detail: '', as_of: null, timers: [] })) };
});

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

const open = (root: HTMLElement, name: string) => root.querySelector<HTMLElement>(`[data-scc-section="${name}"]`)?.getAttribute('data-open');

test('tabs layout: a later focus change to another section switches the open tab', async () => {
  const target = document.createElement('div');
  document.body.append(target);
  const props = $state<{ sessionId: string; focus: 'timers' | 'agents' | 'processes'; layout: 'tabs' }>({ sessionId: 'ses_1', focus: 'processes', layout: 'tabs' });
  mounted.push(mount(ControlCenter, { target, props }));
  await settle();
  expect(open(target, 'processes')).toBe('true');
  props.focus = 'agents';
  await settle();
  expect(open(target, 'agents')).toBe('true');
  expect(open(target, 'processes')).toBe('false');
});
