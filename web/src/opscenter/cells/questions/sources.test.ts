import { describe, expect, test } from 'vitest';
import { ALL_OPTION, allOn, checkedKinds, copyListsKind, isLiveOption, isRetiredOption, kindOn, kindOptionKey } from './sources';

const only = (...ids: string[]) => Object.fromEntries(['approvals', 'huddle', 'automations'].filter((id) => !ids.includes(id)).map((id) => [kindOptionKey(id), false]));

describe('allOn and kindOn', () => {
  test('absent is on, only an explicit false is off', () => {
    expect(allOn(undefined)).toBe(true);
    expect(allOn({ [ALL_OPTION]: true })).toBe(true);
    expect(allOn({ [ALL_OPTION]: false })).toBe(false);
    expect(kindOn(undefined, 'huddle')).toBe(true);
    expect(kindOn({ kind_huddle: false }, 'huddle')).toBe(false);
  });
});

describe('copyListsKind', () => {
  test('while all is on everything is listed, the bell\'s alerts too, whatever the kind checks say', () => {
    expect(copyListsKind(undefined, 'alert_backup_health')).toBe(true);
    expect(copyListsKind({ kind_huddle: false }, 'huddle')).toBe(true);
  });

  test('with all off only a checked built-in kind is listed, and an alert never is', () => {
    const options = { kind_all: false, ...only('approvals', 'automations') };
    expect(copyListsKind(options, 'approvals')).toBe(true);
    expect(copyListsKind(options, 'huddle')).toBe(false);
    expect(copyListsKind(options, 'alert_backup_health')).toBe(false);
  });
});

describe('checkedKinds', () => {
  test('empty while all is on; else the built-in kinds whose check is on', () => {
    expect(checkedKinds(undefined)).toEqual([]);
    expect(checkedKinds({ kind_all: false, ...only('huddle') }).map((k) => k.id)).toEqual(['huddle']);
    expect(checkedKinds({ kind_all: false }).map((k) => k.id)).toEqual(['approvals', 'huddle', 'automations']);
    expect(checkedKinds({ kind_all: false, ...only() })).toEqual([]);
  });
});

describe('retired keys', () => {
  test('the per-source and counts keys of the earlier build are retired; the new ones are live', () => {
    for (const key of ['s_huddle', 's_approvals', 's_alert_backup_health', 'counts']) {
      expect(isRetiredOption(key)).toBe(true);
      expect(isLiveOption(key)).toBe(false);
    }
    for (const key of ['kind_all', 'kind_approvals', 'kind_huddle', 'kind_automations']) {
      expect(isRetiredOption(key)).toBe(false);
      expect(isLiveOption(key)).toBe(true);
    }
  });
});
