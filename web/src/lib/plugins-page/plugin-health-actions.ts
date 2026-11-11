import type { HealthRow } from './plugin-health';

export const OPEN_DEVELOPER_ZONE_EVENT = 'plugins:open-developer-zone';

export interface HealthDoors {
    toggle: (id: string, next: boolean) => void;
    openPane: (id: string, tab: 'permissions') => void;
    select: (id: string) => void;
    openDeveloperZone: () => void;
    openCatalog: () => void;
    leaveSafeMode: () => Promise<void>;
}

export interface HealthSubject {
    readonly itemId: string;
    readonly blockedBy: readonly string[];
}

const NEEDS_SUBJECT = new Set(['turn_on', 'turn_off', 'review', 'show_log', 'turn_on_needed_plugin']);
const ALWAYS = new Set(['leave_safe_mode', 'turn_on_third_party', 'turn_on_developer', 'open_catalog']);

export function canRun(row: Pick<HealthRow, 'button'>, subject: HealthSubject | null): boolean {
    const button = row.button;
    if (!button) return false;
    if (ALWAYS.has(button)) return true;
    if (!NEEDS_SUBJECT.has(button) || !subject) return false;
    return button !== 'turn_on_needed_plugin' || subject.blockedBy.length > 0;
}

export async function runHealthButton(row: Pick<HealthRow, 'button'>, subject: HealthSubject | null, doors: HealthDoors): Promise<void> {
    if (!canRun(row, subject)) return;
    switch (row.button) {
        case 'turn_on': doors.toggle(subject!.itemId, true); break;
        case 'turn_off': doors.toggle(subject!.itemId, false); break;
        case 'review':
        case 'show_log': doors.openPane(subject!.itemId, 'permissions'); break;
        case 'turn_on_needed_plugin': doors.select(`cplug:${subject!.blockedBy[0]}`); break;
        case 'turn_on_third_party':
        case 'turn_on_developer': doors.openDeveloperZone(); break;
        case 'open_catalog': doors.openCatalog(); break;
        case 'leave_safe_mode': await doors.leaveSafeMode(); break;
        default: break;
    }
}
