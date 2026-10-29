import { describe, expect, test } from 'vitest';
import { alertKindId, attentionKinds } from './kinds';

const catalog = [
  { id: 'backup_health', label_key: 'app_alert.source.backup_health', icon: 'database' },
  { id: 'save_pipeline', label_key: 'app_alert.source.save_pipeline', icon: 'workflow' },
  { id: 'other', label_key: 'app_alert.source.other', icon: 'bell' },
];

describe('attentionKinds', () => {
  test('approvals, huddle and failed automations always, then one per sender the server lists, in its order', () => {
    expect(attentionKinds([]).map((k) => k.id)).toEqual(['approvals', 'huddle', 'automations']);
    expect(attentionKinds(catalog).map((k) => k.id)).toEqual(['approvals', 'huddle', 'automations', 'alert_backup_health', 'alert_save_pipeline', 'alert_other']);
  });

  test('every kind names how it is read: a store origin, a route and pushed topics', () => {
    for (const kind of attentionKinds(catalog)) {
      expect(kind.labelKey).not.toBe('');
      expect(kind.route.startsWith('/')).toBe(true);
      expect(kind.topics.length).toBeGreaterThan(0);
    }
    const automations = attentionKinds([]).find((k) => k.id === 'automations');
    expect(automations).toMatchObject({ origin: 'automation', route: '/automations/runs', topics: ['automations', 'automation_runs'] });
  });

  test('a glyph the compiled icon set lacks falls back to the bell, one it has is kept', () => {
    const byId = Object.fromEntries(attentionKinds(catalog).map((k) => [k.id, k.icon]));
    expect(byId['alert_backup_health']).toBe('database');
    expect(byId['alert_save_pipeline']).toBe('bell');
    expect(byId['approvals']).toBe('check-circle');
    expect(byId['automations']).toBe('clock');
  });

  test('every id is one the server accepts as a bell_kinds key', () => {
    for (const kind of attentionKinds(catalog)) expect(kind.id).toMatch(/^[a-z][a-z0-9_]{0,63}$/);
  });
});

describe('alertKindId', () => {
  test('the sender is the tail of the label an alert row carries; no label is the fallback sender', () => {
    expect(alertKindId('app_alert.source.self_check')).toBe('alert_self_check');
    expect(alertKindId(null)).toBe('alert_other');
    expect(alertKindId(undefined)).toBe('alert_other');
  });
});
