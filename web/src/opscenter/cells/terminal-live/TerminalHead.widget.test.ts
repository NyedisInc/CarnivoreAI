/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return {
    ...real,
    sessions: { data: [{ session_row_id: 7, project_id: 4, label: 'alpha', agent_family: 'claude', tmux_session: 'carnivore_alpha', session: { id: 'ses_1', working_dir: '/w' } }], status: 'ok', refresh: vi.fn() },
    primarySessionId: () => 'ses_1',
  };
});
vi.mock('../../lib/active-terminal', async () => {
  const { fakeActive: active } = await import('../../../lib/session-rail/test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('./actions', () => ({ registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false }));
vi.mock('../../../lib/terminal-search/cell-search', () => ({ cellSearchFor: () => null }));
vi.mock('../registry', async () => {
  const { default: TerminalHeadProbe } = await import('../../shell/fixtures/TerminalHeadProbe.svelte');
  return { entryFor: () => ({ component: TerminalHeadProbe }) };
});

import { RAIL_FIELD } from '../../../lib/session-rail/rail-model';
import { follow, keyIn, mountRails, unmountRails } from '../../../lib/session-rail/rail-test-harness';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';
import { setLocale } from '../../../lib/i18n/index.svelte';
import { TOOLBAR_ITEMS } from './toolbar';

setLocale('en');
installPopoverPolyfill();

const one = (...items: Record<string, unknown>[]) => ({ v: 2, sections: [{ items }] });
const section = (): HTMLElement => document.querySelector<HTMLElement>('[data-rail-out-widget="core.notes"]')!;

function open(): void {
  keyIn('side', 'core.notes').click();
  flushSync();
}

function controlRows(root: HTMLElement): Element[] {
  const heads = [...root.querySelectorAll('[data-widget-head], .oc-frame-strip')];
  const loose = [...root.querySelectorAll('.cell-tools')].filter((bar) => !bar.closest('[data-widget-head], .oc-frame-strip'));
  return [...heads, ...loose];
}

function menuWords(head: Element): string[] {
  head.querySelector<HTMLButtonElement>('[data-corner]')!.click();
  flushSync();
  return [...document.querySelectorAll<HTMLElement>('[role^="menuitem"]')].map((item) => (item.textContent ?? '').trim());
}

beforeEach(() => mountRails());
afterEach(() => unmountRails());

describe('the terminal widget in a bar', () => {
  test('header on: exactly one header row, the tools are in it, and there is no kebab', () => {
    follow(RAIL_FIELD, one({ widget: 'core.notes', options: { show_header: true } }));
    open();
    const rows = controlRows(section());
    expect(rows).toHaveLength(1);
    const head = rows[0]!;
    expect(head.matches('[data-widget-head]')).toBe(true);
    expect(head.querySelector('.cell-tools [data-tool="search"]'), 'search is a title strip control').not.toBeNull();
    expect(section().querySelector('[data-tool="overflow"]'), 'a widget draws no kebab of its own').toBeNull();
  });

  test('header on: every control is in the title strip or the widget menu, never both and never neither', () => {
    follow(RAIL_FIELD, one({ widget: 'core.notes', options: { show_header: true } }));
    open();
    const head = section().querySelector('[data-widget-head]')!;
    const inHead = new Set([...head.querySelectorAll<HTMLElement>('.cell-tools [data-tool]')].map((el) => el.dataset.tool!));
    const words = menuWords(head);
    const label = (id: string): string => (id === 'sleep' ? 'sleep this session' : id === 'background' ? 'background' : t(id));
    for (const item of TOOLBAR_ITEMS.filter((one) => one.label || one.id === 'background')) {
      const there = inHead.has(item.id);
      const listed = words.some((word) => word.startsWith(label(item.id)));
      expect(there !== listed, `${item.id}: strip ${there}, menu ${listed}`).toBe(true);
    }
  });

  test('header off: no title strip, and the tools draw once, in the one body row', () => {
    follow(RAIL_FIELD, one({ widget: 'core.notes' }));
    open();
    expect(section().querySelector('[data-widget-head]')).toBeNull();
    const rows = controlRows(section());
    expect(rows).toHaveLength(1);
    expect(rows[0]!.closest('.oc-tl-widgetrow')).not.toBeNull();
    expect(rows[0]!.querySelector('[data-tool="search"]')).not.toBeNull();
  });
});

function t(id: string): string {
  const words: Record<string, string> = {
    search: 'search terminal', theme: 'session theme', skills: 'session skills', plugins: 'session plugins',
    files: 'session files', notes: 'session notes', 'size-master': 'size master',
  };
  return words[id] ?? id;
}
