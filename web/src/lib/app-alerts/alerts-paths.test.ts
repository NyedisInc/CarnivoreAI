import { afterEach, describe, expect, it, vi } from 'vitest';
import { dismissAlert, dismissResolvedAlerts, refreshAlerts, runAlertAction, snoozeAlert } from './alerts.svelte';

describe('alert store request paths', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('never doubles the /api/v1 prefix', async () => {
    const seen: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      seen.push(url);
      return new Response(JSON.stringify({ alerts: [], counts: { error: 0, warn: 0, info: 0 } }), { status: 200 });
    }));
    await refreshAlerts();
    await dismissAlert(3);
    await snoozeAlert(3, 5);
    await dismissResolvedAlerts();
    expect(seen.filter((u) => u.includes('/api/v1/api/v1'))).toEqual([]);
    expect(seen).toContain('/api/v1/alerts?state=all&limit=200');
    expect(seen).toContain('/api/v1/alerts/3/dismiss');
    expect(seen).toContain('/api/v1/alerts/3/snooze');
    expect(seen).toContain('/api/v1/alerts/dismiss-resolved');
  });
});

describe('runAlertAction request path', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('posts a stored recheck action to exactly /api/v1/alerts/3/recheck', async () => {
    const seen: Array<{ url: string; method?: string }> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      seen.push({ url, method: init?.method });
      return new Response('{}', { status: 200 });
    }));
    await runAlertAction({ id: 'recheck', label_key: 'k', method: 'POST', route: '/alerts/3/recheck' });
    expect(seen).toEqual([{ url: '/api/v1/alerts/3/recheck', method: 'POST' }]);
  });
});
