import { describe, expect, test, vi } from 'vitest';

vi.mock('../../api/auth.svelte', () => ({ auth: { state: 'signed-in' }, initAuth: async () => {}, ApiError: class ApiError extends Error {}, authFetch: async () => null }));

import { setLocale } from '../../../lib/i18n/index.svelte';
import { fieldDisabled } from '../../../lib/item-settings/api';
import { icons } from '../../ui/icons';
import { OPTION_KEY_RE } from '../../../lib/drawer-zone/option-values';
import { isRetiredPlacementKey, placementHead, placementOptionsFor } from '../../widgets/placement-options';
import './placement';
import { questionsHead, questionsSchema } from './placement';

setLocale('en');

const ONLY = (id: string) => ({ kind_all: false, ...Object.fromEntries(['approvals', 'huddle', 'automations'].filter((k) => k !== id).map((k) => [`kind_${k}`, false])) });

describe('the schema', () => {
  test('exactly an all check, then approvals, task manager questions and automations that failed, in one group, all on by default', () => {
    const schema = questionsSchema();
    expect(Object.keys(schema.fields)).toEqual(['kind_all', 'kind_approvals', 'kind_huddle', 'kind_automations']);
    for (const field of Object.values(schema.fields)) expect(field).toMatchObject({ kind: 'boolean', default: true });
    expect(schema.groups).toHaveLength(1);
    expect(schema.groups?.[0]?.fields).toEqual(Object.keys(schema.fields));
    for (const key of Object.keys(schema.fields)) expect(OPTION_KEY_RE.test(key)).toBe(true);
  });

  test('all disables the three kinds while it is on and frees them when it is off', () => {
    const schema = questionsSchema();
    expect(fieldDisabled(schema, 'kind_all', {})).toBe(false);
    expect(fieldDisabled(schema, 'kind_huddle', {})).toBe(true);
    expect(fieldDisabled(schema, 'kind_huddle', { kind_all: true })).toBe(true);
    expect(fieldDisabled(schema, 'kind_huddle', { kind_all: false })).toBe(false);
    expect(fieldDisabled(schema, 'kind_automations', { kind_all: false, kind_automations: false })).toBe(false);
  });

  test('the widget registered it, and names the earlier build\'s keys as retired', () => {
    expect(placementOptionsFor('core.questions')?.schema().fields['kind_approvals']).toBeDefined();
    expect(isRetiredPlacementKey('core.questions', 's_alert_backup_health')).toBe(true);
    expect(isRetiredPlacementKey('core.questions', 'kind_all')).toBe(false);
    expect(isRetiredPlacementKey('core.notes', 's_huddle')).toBe(false);
  });
});

describe('the head', () => {
  test('all (the default) wears the bell and the widget\'s name', () => {
    expect(questionsHead({})).toEqual({ icon: 'bell', title: 'waiting on you' });
    expect(questionsHead({ kind_all: true, kind_huddle: false })).toEqual({ icon: 'bell', title: 'waiting on you' });
    expect('bell' in icons).toBe(true);
  });

  test('exactly one kind checked wears that kind\'s own icon and name', () => {
    expect(questionsHead(ONLY('approvals'))).toEqual({ icon: 'check-circle', title: 'approvals' });
    expect(questionsHead(ONLY('huddle'))).toEqual({ icon: 'chat', title: 'task manager questions' });
    expect(questionsHead(ONLY('automations'))).toEqual({ icon: 'clock', title: 'automations that failed' });
  });

  test('two kinds checked wear the bell; none checked keeps the widget\'s own', () => {
    expect(questionsHead({ kind_all: false, kind_huddle: false })).toEqual({ icon: 'bell', title: 'waiting on you' });
    expect(questionsHead({ kind_all: false, kind_approvals: false, kind_huddle: false, kind_automations: false })).toBeNull();
  });

  test('keys of the earlier build change nothing', () => {
    expect(questionsHead({ s_huddle: false, s_approvals: false, counts: false })).toEqual({ icon: 'bell', title: 'waiting on you' });
  });

  test('the shared lookup reaches it, and a widget without one has none', () => {
    expect(placementHead('core.questions', ONLY('huddle'))).toEqual({ icon: 'chat', title: 'task manager questions' });
    expect(placementHead('core.notes', {})).toBeNull();
  });
});
