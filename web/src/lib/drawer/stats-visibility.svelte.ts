import { createDeviceClassToggle } from './device-class-toggle.svelte';

export const STORAGE_KEY = 'carnivore.session.sidebar.stats';
export const MOBILE_STORAGE_KEY = 'carnivore.session.sidebar.stats.mobile';
export const PREFERENCE_FIELD = 'sidebar_show_stats';
export const MOBILE_PREFERENCE_FIELD = 'sidebar_show_stats_mobile';
const ABSENT_SHOWN = false;

const toggle = createDeviceClassToggle<boolean | null>({
    storageKey: STORAGE_KEY,
    mobileStorageKey: MOBILE_STORAGE_KEY,
    field: PREFERENCE_FIELD,
    mobileField: MOBILE_PREFERENCE_FIELD,
    absentShown: ABSENT_SHOWN,
    initial: null,
    logName: 'SessionSidebarStats',
    noun: 'stats',
});

export function statsShown(): boolean | null {
    return toggle.value();
}

export function setStatsShown(next: boolean): boolean {
    return toggle.set(next);
}

export function init(): void {
    toggle.init();
}
