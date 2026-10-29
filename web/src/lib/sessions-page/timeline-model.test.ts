import { expect, test } from 'vitest';
import { lastActivityMs, planLanes } from './timeline-model';
import { session } from '../projects-shared/test-fixtures';
import type { PageRow, Signals } from './filters';

const NOW = Date.UTC(2026, 9, 14, 12, 0, 0);
const iso = (minBefore: number): string => new Date(NOW - minBefore * 60000).toISOString();
const mk = (over: Record<string, unknown>): PageRow => ({
    s: session({ session_uuid: 'a1', state: 'asleep', row_id: 7, ...over }),
    groupKey: '1', projectRef: null, project: 'alpha', company: null, computer: null, provider: 'claude',
});

test('an asleep row with only last_activity_at in the window gets an asleep lane, and an all-null row stays NaN', () => {
    const sig: Signals = { live: () => undefined, asleepUnread: () => false };
    const active = mk({ last_activity_at: iso(30), last_work_at: null, last_seen_running_at: null });
    const never = mk({ last_activity_at: null, last_work_at: null, last_seen_running_at: null });
    const plan = planLanes([active, never], sig, 60, NOW);
    expect(plan.asleep.flatMap((g) => g.rows)).toEqual([active]);
    expect(plan.fold.flatMap((g) => g.rows)).toEqual([never]);
    expect(lastActivityMs(active)).toBe(NOW - 30 * 60000);
    expect(lastActivityMs(never)).toBeNaN();
});
