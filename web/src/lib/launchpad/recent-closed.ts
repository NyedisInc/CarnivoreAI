import { RECENT_KEYS } from '../../../../client/js/labels/recent-session.js';

type Translate = (key: string, params?: Record<string, unknown> | null) => string;

export interface ClosedWords {
    label: string;
    title: string;
}

type BasisKeys = { label: string; title: string };
const LAST_ACTIVE_KEYS: BasisKeys = { label: RECENT_KEYS.lastActiveLabel, title: RECENT_KEYS.lastActiveTitle };
const BASIS_KEYS: Record<string, BasisKeys> = {
    closed: { label: RECENT_KEYS.closedLabel, title: RECENT_KEYS.closedTitle },
    last_active: LAST_ACTIVE_KEYS,
    added: { label: RECENT_KEYS.addedLabel, title: RECENT_KEYS.addedTitle },
};

function stampMs(stamp: string): number {
    const zoned = /(Z|[+-]\d\d:?\d\d)$/.test(stamp) ? stamp : `${stamp}Z`;
    return Date.parse(zoned);
}

function age(ms: number, t: Translate): string {
    const minutes = Math.max(0, Math.floor(ms / 60000));
    if (minutes < 1) return t(RECENT_KEYS.ageNow);
    if (minutes < 60) return t(RECENT_KEYS.ageMinutes, { count: minutes });
    if (minutes < 1440) return t(RECENT_KEYS.ageHours, { count: Math.floor(minutes / 60) });
    return t(RECENT_KEYS.ageDays, { count: Math.floor(minutes / 1440) });
}

export function closedWords(
    closedAt: string | null | undefined,
    closedBasis: string | null | undefined,
    t: Translate,
    now: number = Date.now(),
): ClosedWords | null {
    if (!closedAt) return null;
    const ms = stampMs(closedAt);
    if (!Number.isFinite(ms)) return null;
    const keys = BASIS_KEYS[closedBasis ?? ''] ?? LAST_ACTIVE_KEYS;
    return {
        label: t(keys.label, { age: age(now - ms, t) }),
        title: t(keys.title, { when: new Date(ms).toLocaleString() }),
    };
}
