import { drawerController } from './controller-ref';
import { createDeviceClassToggle } from './device-class-toggle.svelte';

export const STORAGE_KEY = 'carnivore.session.sidebar.closed';
export const MOBILE_STORAGE_KEY = 'carnivore.session.sidebar.closed.mobile';
export const PREFERENCE_FIELD = 'sidebar_show_closed';
export const MOBILE_PREFERENCE_FIELD = 'sidebar_show_closed_mobile';
const ABSENT_SHOWN = false;

const toggle = createDeviceClassToggle<boolean>({
    storageKey: STORAGE_KEY,
    mobileStorageKey: MOBILE_STORAGE_KEY,
    field: PREFERENCE_FIELD,
    mobileField: MOBILE_PREFERENCE_FIELD,
    absentShown: ABSENT_SHOWN,
    initial: ABSENT_SHOWN,
    logName: 'SessionSidebarClosed',
    noun: 'closed',
    afterChange: () => void drawerController()?.refreshNow?.(),
});

export function closedShown(): boolean {
    return toggle.value();
}

export function setClosedShown(next: boolean): boolean {
    return toggle.set(next);
}

export function init(): void {
    toggle.init();
}
