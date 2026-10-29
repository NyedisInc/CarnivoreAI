import { afterEach, describe, expect, it, vi } from 'vitest';
import { armSnoozeWake } from './alerts.svelte';
import type { AppAlert } from './alerts-model';

const snoozed = (until: string | null, state: AppAlert['state'] = 'snoozed'): AppAlert =>
  ({ id: 1, state, snoozed_until: until } as unknown as AppAlert);

describe('snooze wake', () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it('re-reads once just after the earliest snooze ends, and arms nothing otherwise', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-30T12:00:00Z'));
    const fetch = vi.fn(async () => new Response(JSON.stringify({ alerts: [], counts: { error: 0, warn: 0, info: 0 } }), { status: 200 }));
    vi.stubGlobal('fetch', fetch);

    armSnoozeWake([snoozed(null, 'active')]);
    await vi.advanceTimersByTimeAsync(24 * 3600_000);
    expect(fetch).not.toHaveBeenCalled();

    vi.setSystemTime(new Date('2026-09-30T12:00:00Z'));
    armSnoozeWake([snoozed('2026-09-30T12:10:00Z'), snoozed('2026-09-30T12:05:00Z')]);
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(fetch).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1_300);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3600_000);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
