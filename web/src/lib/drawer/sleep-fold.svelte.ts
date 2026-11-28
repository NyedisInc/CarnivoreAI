import { createDeviceClassToggle } from './device-class-toggle.svelte';
import { drawerController } from './controller-ref';
import type { ViewClass } from './view-class';

export const FOLD_SLEEPING_KEY = 'carnivore.session.sidebar.fold_sleeping';
const MOBILE_LOCAL_SUFFIX = '.mobile';
const MOBILE_FIELD_SUFFIX = '_mobile';

export function preferenceField(cls: ViewClass): string {
    return `sidebar_fold_sleeping${cls === 'mobile' ? MOBILE_FIELD_SUFFIX : ''}`;
}

let openBands = $state<Record<string, boolean>>({});

const toggle = createDeviceClassToggle<boolean>({
    storageKey: FOLD_SLEEPING_KEY,
    mobileStorageKey: FOLD_SLEEPING_KEY + MOBILE_LOCAL_SUFFIX,
    field: preferenceField('desktop'),
    mobileField: preferenceField('mobile'),
    absentShown: true,
    initial: true,
    logName: 'SessionSidebarSleepFold',
    noun: 'fold-sleeping',
    afterChange: () => {
        openBands = {};
        drawerController()?.repaint?.();
    },
});

export function sleepingFolded(): boolean {
    return toggle.value();
}

export function setSleepingFolded(next: boolean): boolean {
    return toggle.set(next);
}

export function toggleSleepingFolded(): boolean {
    const next = !toggle.value();
    toggle.set(next);
    return next;
}

export function isSleepFoldOpen(bandKey: string): boolean {
    return !!openBands[bandKey];
}

export function toggleSleepFoldBand(bandKey: string): boolean {
    const next = !openBands[bandKey];
    openBands = { ...openBands, [bandKey]: next };
    return next;
}

export function resetSleepFoldBands(): void {
    openBands = {};
}

export function init(): void {
    toggle.init();
}
