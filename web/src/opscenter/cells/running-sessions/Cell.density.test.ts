/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const ROWS = [
  { label: 'a long running session name that has to wrap', tmux_session: 'carnivore_a', agent_family: 'claude', activity_status: 'working', startup_gate: null,
    unread: false, status_source: 'registry', session: { id: 's1', working_dir: '/work/a', created_at: 1_000, last_activity: 1_000, model: null } },
];

vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api');
  return {
    ...actual,
    sessions: { get data() { return ROWS; }, get status() { return 'ok'; }, get error() { return null; }, refresh: async () => undefined },
    asleep: { get data() { return []; }, refresh: async () => undefined },
    projects: { get data() { return []; }, get status() { return 'ok'; } },
  };
});

import Cell from './Cell.svelte';
import CellWithHost from '../../shell/fixtures/CellWithHost.svelte';
import { declaredActionsFor } from '../../widgets/menu/declared-actions.svelte';
import { setLocale } from '../../../lib/i18n/index.svelte';

setLocale('en');

let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

function draw(options: Record<string, string>, onOption?: (k: string, v: unknown) => void): HTMLElement {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(CellWithHost, { target: host, props: { slot: 'running-sessions', cell: Cell, hostId: 'rs-host', options, onOption: onOption as never } });
  flushSync();
  return host;
}

const placeOf = (host: HTMLElement): HTMLElement | null => host.querySelector('[data-col="task"] .oc-task-detail');

describe('NAME / TASK lines', () => {
  test('normal (the default) adds the folder and last activity line', () => {
    const place = placeOf(draw({}, () => undefined));
    expect(place).not.toBeNull();
    expect(place?.textContent).toContain('/work/a');
    expect(place?.textContent).not.toContain('registry');
  });

  test('compact draws the name alone', () => {
    expect(placeOf(draw({ density: 'compact' }, () => undefined))).toBeNull();
  });

  test('a host that stores no options keeps its size-driven detail line and declares no choice', () => {
    const host = draw({});
    expect(placeOf(host)?.textContent).toContain('registry');
    expect(declaredActionsFor('rs-host').some((a) => a.id.startsWith('density:'))).toBe(false);
  });
});

describe('the choice in the widget menu', () => {
  test('two radio items, normal checked, each writing the option through the host', () => {
    const written: [string, unknown][] = [];
    draw({}, (k, v) => written.push([k, v]));
    const items = declaredActionsFor('rs-host').filter((a) => a.id.startsWith('density:'));
    expect(items.map((a) => [a.id, a.checked])).toEqual([['density:compact', false], ['density:normal', true]]);
    items[0]?.run();
    expect(written).toEqual([['density', 'compact']]);
  });
});

describe('the overlay', () => {
  test('the NAME / TASK wrapper is not the base task wrapper', () => {
    const host = draw({}, () => undefined);
    expect(host.querySelector('[data-col="task"] .oc-task')).toBeNull();
    expect(host.querySelector('[data-col="task"] .oc-session-task')).not.toBeNull();
  });
});
