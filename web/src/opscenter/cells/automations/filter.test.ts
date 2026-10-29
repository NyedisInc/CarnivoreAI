import { describe, expect, it } from 'vitest';
import type { Automation } from '../../../lib/automations/api';
import { cronWords } from '../../../lib/automations/cron-words';
import { isGlobalWidget } from '../../widgets/global-scope';
import { forSession, notTiedToSession, sessionOf } from './filter';

function auto(name: string, target: Automation['target'], next: number | null = null, enabled = true): Automation {
  return {
    automation_id: `id-${name}`, name, enabled, trigger: { cron: '0 9 * * *', timezone: 'UTC' }, target, delivery: { notify: true, notify_on: null },
    next_fire_at: next, revision: 1, created_at: 0, updated_at: 0, created_by: 'app', created_actor: { kind: 'app' }, updated_by: 'app',
    updated_actor: { kind: 'app' }, retry_due_at: null, description: '', project_id: null, misfire: 'skip', retry_max: 0, retry_backoff_s: 0, max_runtime_s: null,
  };
}

const all: Automation[] = [
  auto('late', { kind: 'session_message', session_uuid: 'u1' }, 200),
  auto('soon', { kind: 'session_message', session_uuid: 'u1' }, 100),
  auto('other', { kind: 'session_message', session_uuid: 'u2' }, 50),
  auto('catch-up', { kind: 'recipe', recipe: 'save_catch_up' }, 10),
  auto('project', { kind: 'command', command: 'x', project_id: 3 }),
  auto('blank', { kind: 'session_message', session_uuid: '' }),
];

describe('automations widget filters', () => {
  it('reads a session only from a session message naming it', () => {
    expect(sessionOf(all[0]!)).toBe('u1');
    expect(sessionOf(all[3]!)).toBeNull();
    expect(sessionOf(all[5]!)).toBeNull();
  });

  it('lists only its own session, soonest first', () => {
    expect(forSession(all, 'u1').map((a) => a.name)).toEqual(['soon', 'late']);
    expect(forSession(all, 'nope')).toEqual([]);
    expect(forSession(all, null)).toEqual([]);
  });

  it('lists every automation tied to no session, and the two lists never overlap', () => {
    const global = notTiedToSession(all).map((a) => a.name);
    expect(global).toEqual(['catch-up', 'blank', 'project']);
    const tied = ['u1', 'u2'].flatMap((u) => forSession(all, u).map((a) => a.name));
    expect([...global, ...tied].sort()).toEqual(all.map((a) => a.name).sort());
  });

  it('sorts a disabled automation after the ones that will run', () => {
    const list = [auto('off', { kind: 'recipe' }, 5, false), auto('on', { kind: 'recipe' }, 500)];
    expect(notTiedToSession(list).map((a) => a.name)).toEqual(['on', 'off']);
  });

  it('draws the globe on the global automations widget only', () => {
    expect(isGlobalWidget('core.automations-all')).toBe(true);
    expect(isGlobalWidget('core.automations')).toBe(false);
  });
});

describe('cronWords', () => {
  it('words the common shapes and falls back to the raw string', () => {
    expect(cronWords('*/15 * * * *')).toBe('every 15 minutes');
    expect(cronWords('5 * * * *')).toBe('hourly at :05');
    expect(cronWords('0 9 1 * *')).toMatch(/^monthly, day 1 at /);
    expect(cronWords('0 9 * * 1-5')).toMatch(/^weekdays at /);
    expect(cronWords('0 9 * 3 *')).toBe('cron 0 9 * 3 *');
    expect(cronWords('nonsense')).toBe('cron nonsense');
  });
});
