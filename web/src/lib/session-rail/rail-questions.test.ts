/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { fakeActive } from './test-support.svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('./test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('./test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { RAIL_FIELD } from './rail-model';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
import { alertCenter } from '../app-alerts/alerts.svelte';
import { setLocale } from '../i18n/index.svelte';
import '../../opscenter/cells/questions/placement';
import { follow, keyIn, keysIn, mountRails, unmountRails, written } from './rail-test-harness';

setLocale('en');

const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

const one = (...items: Record<string, unknown>[]) => ({ v: 2, sections: [{ items }] });

const iconOf = (key: HTMLElement): string | null => key.querySelector('svg[data-icon]')?.getAttribute('data-icon') ?? null;

beforeEach(() => {
  fakeActive.id = 'ses_1';
  alertCenter.sources = [{ id: 'backup_health', label_key: 'app_alert.source.backup_health', icon: 'database' }];
  alertCenter.status = 'ok';
  mountRails();
});
afterEach(() => {
  unmountRails();
  alertCenter.sources = [];
  alertCenter.status = 'idle';
});

describe('two copies of the questions widget in one rail', () => {
  test('each copy is its own key: one kind checked wears that kind\'s icon and name, all or several wear the bell', () => {
    follow(RAIL_FIELD, one(
      { widget: 'core.questions', options: { kind_all: false, kind_huddle: false, kind_automations: false } },
      { widget: 'core.questions', instance: 'i2' },
      { widget: 'core.questions', instance: 'i3', options: { kind_all: false, kind_approvals: false } },
    ));
    expect(keysIn('side')).toEqual(['core.questions', 'core.questions#i2', 'core.questions#i3']);
    const [onlyApprovals, everything, two] = keysIn('side').map((id) => keyIn('side', id));
    expect(iconOf(onlyApprovals!)).toBe('check-circle');
    expect(onlyApprovals!.getAttribute('aria-label')).toBe('approvals');
    expect(iconOf(everything!)).toBe('bell');
    expect(everything!.getAttribute('aria-label')).toBe('waiting on you');
    expect(iconOf(two!)).toBe('bell');
    expect(two!.getAttribute('aria-label')).toBe('waiting on you');
  });

  test('a stored selection of the earlier build changes nothing: the copy is on all and wears the bell', () => {
    follow(RAIL_FIELD, one({ widget: 'core.questions', options: { s_alert_backup_health: false, s_huddle: false } }));
    expect(iconOf(keyIn('side', 'core.questions'))).toBe('bell');
  });
});

describe('the right-click menu', () => {
  function rightClick(el: HTMLElement): void {
    el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
    flushSync();
  }
  const checks = () => [...document.querySelectorAll<HTMLElement>('[data-node^="option:"]')];
  const find = (label: string) => checks().find((item) => item.textContent?.includes(label))!;

  test('in edit layout it holds exactly all, approvals, task manager questions and automations that failed, in that order', () => {
    follow(RAIL_FIELD, one({ widget: 'core.questions', instance: 'i2', options: { kind_all: false, kind_huddle: false } }));
    layoutEditor.active = true;
    flushSync();
    rightClick(keyIn('side', 'core.questions#i2'));
    expect(checks().map((item) => item.textContent?.trim().replace(/\s+\S$/, ''))).toEqual(expect.arrayContaining(['all']));
    expect(find('all').getAttribute('aria-checked')).toBe('false');
    expect(find('approvals').getAttribute('aria-checked')).toBe('true');
    expect(find('task manager questions').getAttribute('aria-checked')).toBe('false');
    expect(find('automations that failed').getAttribute('aria-checked')).toBe('true');
    expect(find('approvals').getAttribute('aria-disabled')).toBeNull();
  });

  test('outside edit layout a right-click on the key opens the same four checks (settings any time)', () => {
    follow(RAIL_FIELD, one({ widget: 'core.questions' }));
    layoutEditor.active = false;
    flushSync();
    rightClick(keyIn('side', 'core.questions'));
    expect(checks().map((item) => item.getAttribute('data-node'))).toEqual(['option:kind_all', 'option:kind_approvals', 'option:kind_huddle', 'option:kind_automations']);
    find('all').click();
    flushSync();
    expect(document.querySelector('[role="menu"]')).not.toBeNull();
    expect((written.at(-1)!.value as { sections: { items: unknown[] }[] }).sections[0]!.items).toEqual([{ widget: 'core.questions', options: { kind_all: false } }]);
  });

  test('while all is on the three kinds are disabled', () => {
    follow(RAIL_FIELD, one({ widget: 'core.questions' }));
    layoutEditor.active = true;
    flushSync();
    rightClick(keyIn('side', 'core.questions'));
    expect(find('all').getAttribute('aria-disabled')).toBeNull();
    for (const label of ['approvals', 'task manager questions', 'automations that failed']) expect(find(label).getAttribute('aria-disabled')).toBe('true');
  });

  test('a click stores the check on that copy alone and the menu stays open', () => {
    follow(RAIL_FIELD, one({ widget: 'core.questions' }, { widget: 'core.questions', instance: 'i2' }));
    layoutEditor.active = true;
    flushSync();
    rightClick(keyIn('side', 'core.questions#i2'));
    find('all').click();
    flushSync();
    expect(document.querySelector('[role="menu"]')).not.toBeNull();
    find('task manager questions').click();
    flushSync();
    expect(document.querySelector('[role="menu"]')).not.toBeNull();
    const stored = written.at(-1)!;
    expect(stored.field).toBe(RAIL_FIELD);
    expect((stored.value as { sections: { items: unknown[] }[] }).sections[0]!.items).toEqual([
      { widget: 'core.questions' },
      { widget: 'core.questions', instance: 'i2', options: { kind_all: false, kind_huddle: false } },
    ]);
    expect(iconOf(keyIn('side', 'core.questions#i2'))).toBe('bell');
  });

  test('writing a copy drops the keys of the earlier build', () => {
    follow(RAIL_FIELD, one({ widget: 'core.questions', options: { s_huddle: false, counts: false } }));
    layoutEditor.active = true;
    flushSync();
    rightClick(keyIn('side', 'core.questions'));
    find('all').click();
    flushSync();
    expect((written.at(-1)!.value as { sections: { items: unknown[] }[] }).sections[0]!.items).toEqual([{ widget: 'core.questions', options: { kind_all: false } }]);
  });
});
