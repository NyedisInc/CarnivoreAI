import type { Provider } from './api';

type Translate = (key: string, params?: Record<string, unknown>) => string;

export interface FlowPlan {
    readonly flowing: boolean;
    readonly flowText: string;
    readonly trafficText: string;
    readonly bridgeText: string | null;
}

const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const two = (n: number): string => String(n).padStart(2, '0');

export function clock(epoch: number, now: Date = new Date()): string {
    const at = new Date(epoch * 1000);
    const time = `${two(at.getHours())}:${two(at.getMinutes())}`;
    if (at.toDateString() === now.toDateString()) return time;
    return `${DAYS[at.getDay()]} ${two(at.getMonth() + 1)}/${two(at.getDate())} ${time}`;
}

export function planFlow(t: Translate, stream: Provider['stream'], now: Date = new Date()): FlowPlan {
    const never = t('messaging.ui.provider.traffic_never');
    const when = (epoch: number | null): string => (epoch == null ? never : clock(epoch, now));
    const bridge = stream.bridge;
    return {
        flowing: stream.flow === 'flowing',
        flowText: t(`messaging.ui.provider.flow.${stream.flow === 'flowing' ? 'flowing' : 'stale'}`),
        trafficText: t('messaging.ui.provider.traffic', { inbound: when(stream.last_inbound_at), outbound: when(stream.last_outbound_at) }),
        bridgeText: bridge ? t('messaging.ui.provider.bridge', { latest: bridge.latest, seen: clock(bridge.seen_at, now), cursor: stream.cursor }) : null,
    };
}

export interface IdempotencyPlan {
    readonly proven: boolean;
    readonly text: string;
}

export function planIdempotency(t: Translate, idempotency: Provider['idempotency'], now: Date = new Date()): IdempotencyPlan {
    const at = idempotency.last_proven_at;
    if (!idempotency.proven || at == null) return { proven: false, text: t('messaging.ui.provider.idempotency.never') };
    return { proven: true, text: t('messaging.ui.provider.idempotency.proven', { at: clock(at, now) }) };
}
