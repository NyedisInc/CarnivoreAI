import { settingById, slugOf, type SectionId } from './settings-registry';

export function dirtyTabsOf(ids: readonly string[], section: SectionId): Set<string> {
    const out = new Set<string>();
    for (const id of ids) {
        const def = settingById(id);
        if (def && def.section === section) out.add(slugOf(def.group));
    }
    return out;
}

export function dirtySectionsOf(ids: readonly string[]): Set<SectionId> {
    const out = new Set<SectionId>();
    for (const id of ids) {
        const def = settingById(id);
        if (def) out.add(def.section);
    }
    return out;
}
