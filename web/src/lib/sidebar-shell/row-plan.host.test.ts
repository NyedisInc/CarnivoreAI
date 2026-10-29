import { describe, expect, test } from 'vitest';

import { buildRowPlan } from './row-plan';
import { rowHost } from './row-host';

const remote = { name: 'HostaTest', status: 'idle', host_key: 'hosta', host_label: 'hosta', host_state: 'up' };

describe('remote row host chip', () => {
    test.each(['compact', 'cozy'])('%s draws it inline', (mode) => {
        const plan = buildRowPlan(remote, mode, 'other', null, rowHost()) as { hostInline: { text: string } | null };
        expect(plan.hostInline?.text).toBe('hosta');
    });
    test('a local row draws none; detailed draws it inline on an agent row, on the second line of a terminal row', () => {
        const local = buildRowPlan({ name: 'a', status: 'idle' }, 'compact', 'other', null, rowHost()) as { hostInline: unknown };
        expect(local.hostInline).toBeNull();
        const det = buildRowPlan(remote, 'detailed', 'other', null, rowHost()) as { hostInline: { text: string } | null; meta: unknown };
        expect(det.hostInline?.text).toBe('hosta');
        expect(det.meta).toBeNull();
        const term = buildRowPlan({ ...remote, agent_family: 'shell' }, 'detailed', 'other', null, rowHost()) as { hostInline: unknown; meta: { host: unknown } };
        expect(term.hostInline).toBeNull();
        expect(term.meta.host).not.toBeNull();
    });
});
