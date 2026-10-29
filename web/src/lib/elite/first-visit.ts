import { hydratePrefs, prefsStatus, save } from './elite-prefs';

export const SEEN_FIELD = 'warez_elite_seen';

export type FirstVisit = 'elite' | 'normal' | 'wait';

interface Bridge { read(field: string, localReader: () => unknown): unknown }

export function firstVisit(): FirstVisit {
    const status = prefsStatus();
    if (status === 'hydrated') {
        const bridge = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
        return bridge && bridge.read(SEEN_FIELD, () => null) !== true ? 'elite' : 'normal';
    }
    return status === 'not_hydrated' ? 'wait' : 'normal';
}

export async function settleFirstVisit(): Promise<'elite' | 'normal'> {
    await hydratePrefs();
    const view = firstVisit();
    return view === 'elite' ? 'elite' : 'normal';
}

export function markEliteSeen(): Promise<void> {
    return save(SEEN_FIELD, true);
}
