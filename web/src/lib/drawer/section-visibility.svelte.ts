/* show open sessions */
import { drawerController } from './controller-ref';
import { createDeviceClassToggle, type DeviceClassToggle } from './device-class-toggle.svelte';
import type { ViewClass } from './view-class';

const ABSENT_SHOWN = true;

export type OptionalSection = 'open' | 'sleeping';

export const OPTIONAL_SECTIONS: readonly OptionalSection[] = ['open', 'sleeping'];

export const STORAGE_KEYS: Readonly<Record<OptionalSection, string>> = {
    open: 'carnivore.session.sidebar.list_open',
    sleeping: 'carnivore.session.sidebar.list_sleeping',
};

const MOBILE_LOCAL_SUFFIX = '.mobile';
const MOBILE_FIELD_SUFFIX = '_mobile';

export function preferenceField(id: OptionalSection, cls: ViewClass): string {
    return `sidebar_list_${id}${cls === 'mobile' ? MOBILE_FIELD_SUFFIX : ''}`;
}

function storageKey(id: OptionalSection, cls: ViewClass): string {
    return STORAGE_KEYS[id] + (cls === 'mobile' ? MOBILE_LOCAL_SUFFIX : '');
}

const toggles: Readonly<Record<OptionalSection, DeviceClassToggle<boolean>>> = Object.fromEntries(
    OPTIONAL_SECTIONS.map((id) => [id, createDeviceClassToggle<boolean>({
        storageKey: storageKey(id, 'desktop'),
        mobileStorageKey: storageKey(id, 'mobile'),
        field: preferenceField(id, 'desktop'),
        mobileField: preferenceField(id, 'mobile'),
        absentShown: ABSENT_SHOWN,
        initial: ABSENT_SHOWN,
        logName: 'SessionSidebarSections',
        noun: id,
        afterChange: () => void drawerController()?.refreshNow?.(),
    })]),
) as Record<OptionalSection, DeviceClassToggle<boolean>>;

export function sectionShown(id: OptionalSection): boolean {
    return toggles[id].value();
}

export function setSectionShown(id: OptionalSection, next: boolean): boolean {
    return toggles[id].set(next);
}

export function init(): void {
    for (const id of OPTIONAL_SECTIONS) toggles[id].init();
}
