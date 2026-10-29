/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import ControlCenter from './ControlCenter.svelte';
import {
  DEFAULT_SESSION_CONTROL_OPTION, SESSION_CONTROL_OPTIONS, resolveSessionControlOption,
} from './control-center';

vi.mock('../../opscenter/api', async () => {
  const actual = await vi.importActual<typeof import('../../opscenter/api')>('../../opscenter/api');
  return { ...actual, sessions: { get data() { return [{ session: { id: 'ses_1' }, agent_family: 'claude' }]; } } };
});

const PROCESSES = [
  { pid: 101, start: 'Mon Sep 28 08:58:46 2026', task_id: 'bsub00001', started_at: '2026-09-28T12:58:46Z',
    children: 1, summary: 'ssh host tail -f log', agent_id: 'a1' },
  { pid: 202, start: 'Mon Sep 28 09:00:00 2026', task_id: 'bparent01', started_at: '2026-09-28T13:00:00Z',
    children: 0, summary: 'npm run watch', agent_id: null },
];

const FINISHED_WITH_PROCESS = [
  ...PROCESSES,
  { pid: 303, start: 'Mon Sep 28 09:05:00 2026', task_id: 'bsub00003', started_at: '2026-09-28T13:05:00Z',
    children: 0, summary: 'tail -f server.log', agent_id: 'a4' },
];

let backgroundWorkProcesses: typeof PROCESSES = PROCESSES;

vi.mock('../background-work/background-work', async () => {
  const actual = await vi.importActual<typeof import('../background-work/background-work')>('../background-work/background-work');
  return {
    ...actual,
    fetchBackgroundWork: vi.fn(async () => ({ state: 'ok', family: 'claude', detail: '', as_of: null,
      owners: 'ok', processes: backgroundWorkProcesses })),
    terminateProcess: (...args: unknown[]) => terminateOne(...args),
  };
});
vi.mock('../subagents/subagents', async () => {
  const actual = await vi.importActual<typeof import('../subagents/subagents')>('../subagents/subagents');
  const agent = (id: string, status: string, description: string) => ({ id, agent_type: 'Explore', description,
    model: null, background: true, spawn_depth: 1, started_at: '2026-09-28T13:00:00Z', last_activity_at: null,
    status, status_reason: 'x', end_status: null });
  return {
    ...actual,
    fetchSubagents: vi.fn(async () => ({ state: 'ok', family: 'claude', conversation_uuid: 'u', detail: '',
      as_of: null, counts: null,
      subagents: [agent('a1', 'running', 'tail the log'), agent('a2', 'running', 'map the repo'),
        agent('a3', 'done', 'long gone'), agent('a4', 'done', 'restarted the watcher')] })),
  };
});
function timer(id: string, status: string, cron: string | null, human: string | null, minutes: number, prompt: string) {
  return { id, kind: cron ? 'cron' : 'wakeup', status, cron, human_schedule: human,
    delay_seconds: cron ? null : 1800, recurring: !!cron && cron.startsWith('*'), durable: false,
    created_at: new Date(Date.now() + (minutes - 30) * 60 * 1000).toISOString(),
    fire_at: new Date(Date.now() + minutes * 60 * 1000).toISOString(), expires_at: null, prompt, reason: null };
}
const LIVE_TIMER = [timer('t1', 'live', '*/5 * * * *', 'every 5 minutes', 4, 'check the deploy')];
let timerRows: Array<Omit<ReturnType<typeof timer>, 'fire_at'> & { fire_at: string | null }> = LIVE_TIMER;
vi.mock('../timers/timers', async () => {
  const actual = await vi.importActual<typeof import('../timers/timers')>('../timers/timers');
  return {
    ...actual,
    fetchTimers: vi.fn(async () => ({ state: 'ok', family: 'claude', conversation_uuid: 'u', process: 'alive',
      process_started_at: null, counts: null, next_fire_at: null, background: null, detail: '', as_of: null,
      timers: timerRows })),
  };
});
const terminateOne = vi.fn();
const terminateMany = vi.fn();
const interrupt = vi.fn();
vi.mock('./control-center', async () => {
  const actual = await vi.importActual<typeof import('./control-center')>('./control-center');
  return {
    ...actual,
    terminateAll: (...args: unknown[]) => terminateMany(...args),
    interruptSession: (...args: unknown[]) => interrupt(...args),
  };
});

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  terminateOne.mockReset();
  terminateMany.mockReset();
  interrupt.mockReset();
  backgroundWorkProcesses = PROCESSES;
  timerRows = LIVE_TIMER;
});

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function setup(): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(ControlCenter, { target, props: { sessionId: 'ses_1', focus: 'processes' } }));
  await settle();
  return target;
}

const section = (root: HTMLElement, name: string) => root.querySelector<HTMLElement>(`[data-scc-section="${name}"]`)!;
const danger = (root: HTMLElement) => root.querySelector<HTMLButtonElement>('.scc-confirm [data-btn="danger"]')!;

test('three sections: timers listed, sub-agents with what they launched, processes with pid and age', async () => {
  const root = await setup();
  expect(section(root, 'processes').getAttribute('data-focused')).toBe('true');
  expect(section(root, 'timers').textContent).toContain('check the deploy');
  expect(section(root, 'timers').querySelector('button')).toBeNull();
  const agents = section(root, 'agents');
  expect(agents.querySelectorAll('[data-scc-agent]')).toHaveLength(2);
  expect(agents.querySelector('[data-scc-agent="a1"] [data-scc-stop]')).not.toBeNull();
  expect(agents.querySelector('[data-scc-agent="a2"] .scc-quiet')?.textContent).toBe('no shells');
  const procs = section(root, 'processes');
  expect(procs.querySelector('[data-scc-pid="101"]')?.textContent).toContain('pid 101, 1 process under it');
  expect(procs.querySelector('.scc-count')?.textContent).toBe('2');
});

test('stop all processes: armed first, then every listed pair is sent once', async () => {
  terminateMany.mockResolvedValue({ results: [
    { pid: 101, outcome: 'terminated', code: null, detail: '' },
    { pid: 202, outcome: 'refused', code: 'start_mismatch', detail: '' }], term: [101], kill: [], survivors: [] });
  const root = await setup();
  section(root, 'processes').querySelector<HTMLButtonElement>('[data-scc-act]')!.click();
  flushSync();
  expect(terminateMany).not.toHaveBeenCalled();
  expect(root.querySelector('.scc-ask')?.textContent).toContain('stop all 2 shells');
  danger(root).click();
  await settle();
  expect(terminateMany).toHaveBeenCalledTimes(1);
  expect(terminateMany.mock.calls[0]![0]).toBe('ses_1');
  expect((terminateMany.mock.calls[0]![1] as { pid: number }[]).map((p) => p.pid)).toEqual([101, 202]);
  expect(section(root, 'processes').querySelector('.scc-notice')?.textContent).toBe('1 stopped · 1 refused');
});

test('a sub-agent stop sends only the processes that sub-agent launched', async () => {
  terminateMany.mockResolvedValue({ results: [{ pid: 101, outcome: 'killed', code: null, detail: '' }],
    term: [101], kill: [101], survivors: [] });
  const root = await setup();
  section(root, 'agents').querySelector<HTMLButtonElement>('[data-scc-agent="a1"] [data-scc-stop]')!.click();
  flushSync();
  expect(terminateMany).not.toHaveBeenCalled();
  danger(root).click();
  await settle();
  expect((terminateMany.mock.calls[0]![1] as { pid: number }[]).map((p) => p.pid)).toEqual([101]);
});

test('stop all sub-agents interrupts the session, and Escape disarms without sending', async () => {
  interrupt.mockResolvedValue({ sent: true, key: 'escape', agent_pid: 9, activity_status: 'working', detail: '' });
  const root = await setup();
  const all = () => section(root, 'agents').querySelector<HTMLButtonElement>('[data-scc-act]')!;
  all().click();
  flushSync();
  root.querySelector('.scc')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  flushSync();
  expect(root.querySelector('.scc-confirm')).toBeNull();
  expect(interrupt).not.toHaveBeenCalled();
  all().click();
  flushSync();
  expect(root.querySelector('.scc-ask')?.textContent).toContain('interrupt this session');
  danger(root).click();
  await settle();
  expect(interrupt).toHaveBeenCalledWith('ses_1');
  expect(section(root, 'agents').querySelector('.scc-notice')?.textContent).toContain('escape sent');
});

test('one process stop goes through the single guarded route', async () => {
  terminateOne.mockResolvedValue({ pid: 202, outcome: 'terminated', term: [202], kill: [], survivors: [], detail: '' });
  const root = await setup();
  section(root, 'processes').querySelector<HTMLButtonElement>('[data-scc-pid="202"] [data-scc-stop]')!.click();
  flushSync();
  expect(terminateOne).not.toHaveBeenCalled();
  danger(root).click();
  await settle();
  expect(terminateOne.mock.calls[0]![1]).toMatchObject({ pid: 202, start: 'Mon Sep 28 09:00:00 2026' });
  expect(terminateMany).not.toHaveBeenCalled();
});

test('a finished sub-agent stops when it still owns a live process, otherwise it has no button at all', async () => {
  backgroundWorkProcesses = FINISHED_WITH_PROCESS;
  terminateMany.mockResolvedValue({ results: [{ pid: 303, outcome: 'terminated', code: null, detail: '' }],
    term: [303], kill: [], survivors: [] });
  const root = await setup();
  const agents = section(root, 'agents');
  expect(agents.querySelector('[data-scc-agent="a3"]')).toBeNull();
  const row = agents.querySelector('[data-scc-agent="a4"]')!;
  expect(row).not.toBeNull();
  expect(row.querySelector('.scc-num')?.textContent).toBe('finished');
  const stop = row.querySelector<HTMLButtonElement>('[data-scc-stop]')!;
  expect(stop).not.toBeNull();
  expect(stop.hasAttribute('title')).toBe(false);
  stop.click();
  flushSync();
  expect(root.querySelector('.scc-ask')?.textContent).toContain('shell this agent started');
  danger(root).click();
  await settle();
  expect((terminateMany.mock.calls[0]![1] as { pid: number }[]).map((p) => p.pid)).toEqual([303]);
});

test('timers read as times, live first, with fired and canceled ones folded into a history', async () => {
  const at = new Date(Date.now() + 32 * 60 * 1000);
  const pinned = `${at.getMinutes()} ${at.getHours()} ${at.getDate()} ${at.getMonth() + 1} *`;
  timerRows = [
    timer('t2', 'fired', '10 14 28 9 *', null, -90, 'run the nightly import'),
    { ...timer('t1', 'live', pinned, pinned, 32, 'check the release suite'), fire_at: null },
    timer('t3', 'cancelled', null, null, -40, 'remind me to push'),
    timer('t4', 'live', '*/30 * * * *', 'every 30 minutes', 18, 'summarize new issues'),
  ];
  const root = await setup();
  const timers = section(root, 'timers');
  const live = [...timers.querySelectorAll('[data-scc-timer="live"]')];
  expect(live.map((row) => row.querySelector('.scc-text')?.textContent)).toEqual(['summarize new issues', 'check the release suite']);
  expect(timers.querySelector('.scc-count')?.textContent).toBe('2');
  expect(timers.textContent).not.toContain(pinned);
  expect(live[1]?.querySelector('.scc-type')?.textContent).toMatch(/^once, (today|tomorrow) \d{1,2}:\d{2} (am|pm)$/);
  expect(live[1]?.querySelector('.scc-num')?.textContent).toBe('in 32m');
  expect(live[0]?.querySelector('.scc-type')?.textContent).toBe('every 30 minutes');
  const fold = timers.querySelector<HTMLButtonElement>('.scc-fold')!;
  expect(fold.textContent).toBe('history (2)');
  expect(fold.getAttribute('aria-expanded')).toBe('false');
  expect(timers.textContent).not.toContain('run the nightly import');
  fold.click();
  flushSync();
  const ended = [...timers.querySelectorAll('[data-scc-timer="ended"]')];
  expect(ended.map((row) => row.querySelector('.scc-type')?.textContent)).toEqual(['canceled', 'fired']);
  expect(ended[1]?.querySelector('.scc-num')?.textContent).toMatch(/(today|yesterday) \d{1,2}:\d{2} (am|pm)$/);
});

test('columns (the default): every section body draws at once, none hidden', async () => {
  const root = await setup();
  expect(root.querySelector('.scc')?.getAttribute('data-layout')).toBe('columns');
  for (const name of ['timers', 'agents', 'processes']) {
    expect(section(root, name).getAttribute('data-open')).toBe('true');
  }
  expect(section(root, 'timers').querySelector('.scc-list')).not.toBeNull();
  expect(section(root, 'agents').querySelector('.scc-list')).not.toBeNull();
  expect(section(root, 'processes').querySelector('.scc-list')).not.toBeNull();
});

test('accordion: only the focused section is open; clicking another header opens it and closes the rest', async () => {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(ControlCenter, { target, props: { sessionId: 'ses_1', focus: 'processes', layout: 'accordion' } }));
  await settle();
  expect(target.querySelector('.scc')?.getAttribute('data-layout')).toBe('accordion');
  expect(section(target, 'processes').getAttribute('data-open')).toBe('true');
  expect(section(target, 'timers').getAttribute('data-open')).toBe('false');
  expect(section(target, 'timers').querySelector('.scc-list')).toBeNull();
  expect(section(target, 'agents').getAttribute('data-open')).toBe('false');

  section(target, 'agents').querySelector<HTMLElement>('.scc-head')!.click();
  flushSync();
  expect(section(target, 'agents').getAttribute('data-open')).toBe('true');
  expect(section(target, 'agents').querySelector('.scc-list')).not.toBeNull();
  expect(section(target, 'processes').getAttribute('data-open')).toBe('false');
  expect(section(target, 'processes').querySelector('.scc-list')).toBeNull();
});

test('accordion: the "stop all" button inside a closed section\'s header never also opens it via bubbling', async () => {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(ControlCenter, { target, props: { sessionId: 'ses_1', focus: 'timers', layout: 'accordion' } }));
  await settle();
  section(target, 'processes').querySelector<HTMLButtonElement>('[data-scc-act]')!.click();
  flushSync();
  expect(section(target, 'processes').getAttribute('data-open')).toBe('true');
  expect(target.querySelector('.scc-confirm')).not.toBeNull();
});

test('resolveSessionControlOption: a/b/c are all implemented, anything else falls back to "a"', () => {
  expect(DEFAULT_SESSION_CONTROL_OPTION).toBe('a');
  expect(SESSION_CONTROL_OPTIONS).toEqual(['a', 'b', 'c']);
  expect(resolveSessionControlOption('a')).toBe('a');
  expect(resolveSessionControlOption('b')).toBe('b');
  expect(resolveSessionControlOption('c')).toBe('c');
  expect(resolveSessionControlOption('z')).toBe('a');
  expect(resolveSessionControlOption(undefined)).toBe('a');
});

test('opening on a section never calls scrollIntoView, which would scroll the terminal cell too', async () => {
  const spy = vi.fn();
  const original = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = spy;
  try {
    await setup();
    expect(spy).not.toHaveBeenCalled();
  } finally {
    Element.prototype.scrollIntoView = original;
  }
});

test('tabs layout: the rail is the shared page tabs, one per section, and choosing one opens that section (T-4)', async () => {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(ControlCenter, { target, props: { sessionId: 'ses_1', focus: 'processes', layout: 'tabs' } }));
  await settle();
  const strip = target.querySelector('.scc-tabs.oc-ptabs');
  expect(strip, 'the rail wears the shared Tabs').not.toBeNull();
  expect([...strip!.querySelectorAll('[role="tab"]')].map((el) => el.getAttribute('data-tab'))).toEqual(['timers', 'agents', 'processes']);
  expect(strip!.querySelector('[data-tab="processes"]')!.getAttribute('aria-selected')).toBe('true');
  strip!.querySelector<HTMLElement>('[data-tab="agents"]')!.click();
  flushSync();
  expect(strip!.querySelector('[data-tab="agents"]')!.getAttribute('aria-selected')).toBe('true');
  expect(section(target, 'agents').getAttribute('data-open')).toBe('true');
});
