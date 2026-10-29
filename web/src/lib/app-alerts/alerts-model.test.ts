import { describe, expect, it } from 'vitest';
import { panelSections, shouldToast, type AppAlert } from './alerts-model';

function alert(over: Partial<AppAlert>): AppAlert {
  return {
    id: 1, key: 'k', source: 's', severity: 'error', title_key: 'app_alert.x', params: {}, detail_key: null,
    state: 'active', sticky: false, auto_resolve: true, first_seen: '2026-09-29T10:00:00+00:00',
    last_seen: '2026-09-29T10:00:00+00:00', count: 1, resolved_at: null, dismissed_at: null,
    snoozed_until: null, actions: [], ...over,
  };
}

describe('shouldToast', () => {
  it('toasts a newly raised alert of any severity once, never a bump or a resolve', () => {
    const seen = new Set<number>();
    expect(shouldToast({ type: 'app_alert.raised', id: 4, severity: 'error' }, seen)).toBe(true);
    expect(shouldToast({ type: 'app_alert.raised', id: 4, severity: 'error' }, seen)).toBe(false);
    expect(shouldToast({ type: 'app_alert.updated', id: 5, severity: 'error', count: 2 }, seen)).toBe(false);
    expect(shouldToast({ type: 'app_alert.resolved', id: 6, severity: 'error' }, seen)).toBe(false);
    expect(shouldToast({ type: 'app_alert.raised', id: 7, severity: 'warn' }, seen)).toBe(true);
    expect(shouldToast({ type: 'app_alert.raised', id: 8, severity: 'info' }, seen)).toBe(true);
  });
});

describe('panelSections', () => {
  it('puts open alerts errors first and keeps only the last day of resolved ones', () => {
    const now = Date.parse('2026-09-29T12:00:00+00:00');
    const { open, resolved } = panelSections([
      alert({ id: 1, severity: 'warn', last_seen: '2026-09-29T11:00:00+00:00' }),
      alert({ id: 2, severity: 'error' }),
      alert({ id: 3, state: 'snoozed', severity: 'info' }),
      alert({ id: 4, state: 'resolved', resolved_at: '2026-09-29T09:00:00+00:00' }),
      alert({ id: 5, state: 'resolved', resolved_at: '2026-09-27T09:00:00+00:00' }),
      alert({ id: 6, state: 'dismissed' }),
    ], now);
    expect(open.map((a) => a.id)).toEqual([2, 1, 3]);
    expect(resolved.map((a) => a.id)).toEqual([4]);
  });
});
