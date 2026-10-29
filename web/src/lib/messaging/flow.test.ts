import { describe, expect, it } from 'vitest';
import type { Provider } from './api';
import { clock, planFlow, planIdempotency } from './flow';

const t = (key: string, params?: Record<string, unknown>): string => `${key}${params ? JSON.stringify(params) : ''}`;
const NOW = new Date(2026, 9, 11, 20, 0, 0);
const at = (h: number, m: number, day = 11): number => new Date(2026, 9, day, h, m, 0).getTime() / 1000;
const stream = (over: Partial<Provider['stream']>): Provider['stream'] =>
    ({ state: 'live', cursor: 43, gap: null, last_event_at: null, last_inbound_at: null, last_outbound_at: null, bridge: null, flow: 'stale', ...over });

describe('clock', () => {
    it('shows only the time for today and the day for another', () => {
        expect(clock(at(19, 52), NOW)).toBe('19:52');
        expect(clock(at(14, 2, 9), NOW)).toBe('fri 10/09 14:02');
    });
});

describe('planFlow', () => {
    it('says flowing, with the traffic times and the bridge head against the cursor', () => {
        const plan = planFlow(t, stream({ flow: 'flowing', last_inbound_at: at(16, 2), last_outbound_at: at(12, 28), bridge: { latest: 106, seen_at: at(19, 52) } }), NOW);
        expect(plan.flowing).toBe(true);
        expect(plan.flowText).toBe('messaging.ui.provider.flow.flowing');
        expect(plan.trafficText).toContain('"inbound":"16:02"');
        expect(plan.trafficText).toContain('"outbound":"12:28"');
        expect(plan.bridgeText).toContain('"latest":106');
        expect(plan.bridgeText).toContain('"cursor":43');
    });

    it('says stale with never for missing times and no bridge line before a first connect', () => {
        const plan = planFlow(t, stream({}), NOW);
        expect(plan.flowing).toBe(false);
        expect(plan.flowText).toBe('messaging.ui.provider.flow.stale');
        expect(plan.trafficText).toContain('"inbound":"messaging.ui.provider.traffic_never"');
        expect(plan.bridgeText).toBeNull();
    });
});

describe('planIdempotency', () => {
    it('says proven with when the last replayed key was answered with the original', () => {
        const plan = planIdempotency(t, { proven: true, last_proven_at: at(16, 2) }, NOW);
        expect(plan.proven).toBe(true);
        expect(plan.text).toBe('messaging.ui.provider.idempotency.proven{"at":"16:02"}');
    });

    it('says never seen when nothing was proven, even if a stale flag says otherwise', () => {
        expect(planIdempotency(t, { proven: false, last_proven_at: null }, NOW)).toEqual({ proven: false, text: 'messaging.ui.provider.idempotency.never' });
        expect(planIdempotency(t, { proven: true, last_proven_at: null }, NOW).proven).toBe(false);
    });
});
