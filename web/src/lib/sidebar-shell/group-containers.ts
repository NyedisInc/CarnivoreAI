import { companyList } from '../companies';
import { projects } from '../../opscenter/api/projects.svelte';
import { layoutsBridge } from '../layouts-bridge/bridge';
import { bridge as drawerLayoutsBridge } from '../drawer/layouts-model';
import { BAND_BROWSERS, BAND_FILES, BAND_TERMINALS } from '../drawer/bucketing';
import * as GroupStore from '../drawer/group-store';
import { LAYOUT_FOLD_KEY, LAYOUT_ITEM_FOLD_PREFIX, ROGUE_FOLD_KEY } from '../drawer/store-keys';
import { t } from '../i18n/index.svelte';
import type { SelectChoice, SelectOption } from '../base/Select.svelte';

export type ContainerSection = 'sections' | 'layouts' | 'companies' | 'projects' | 'groups';

export interface GroupContainerOption {
    key: string | null;
    label: string;
    section: ContainerSection;
}

function forbiddenGroupUuids(excludeUuid: string | undefined, groups: readonly GroupStore.SessionGroup[]): Set<string> {
    const out = new Set<string>();
    if (!excludeUuid) return out;
    out.add(excludeUuid);
    let grew = true;
    while (grew) {
        grew = false;
        for (const g of groups) {
            if (out.has(g.group_uuid)) continue;
            const parentUuid = g.parent_key ? GroupStore.groupUuidOf(g.parent_key) : null;
            if (parentUuid && out.has(parentUuid)) {
                out.add(g.group_uuid);
                grew = true;
            }
        }
    }
    return out;
}

export function groupContainerOptions(excludeGroupUuid?: string): GroupContainerOption[] {
    const out: GroupContainerOption[] = [
        { key: null, label: t('sidebar.group.location.top'), section: 'sections' },
        { key: GroupStore.BAND_PINNED, label: t('sidebar.band.pinned'), section: 'sections' },
        { key: LAYOUT_FOLD_KEY, label: t('sidebar.band.layouts'), section: 'sections' },
        { key: ROGUE_FOLD_KEY, label: t('sidebar.band.rogue'), section: 'sections' },
        { key: BAND_TERMINALS, label: t('sidebar.band.terminals'), section: 'sections' },
        { key: BAND_BROWSERS, label: t('sidebar.band.browsers'), section: 'sections' },
        { key: BAND_FILES, label: t('sidebar.band.files'), section: 'sections' },
    ];

    const savedLayouts = [...(drawerLayoutsBridge()?.list() ?? layoutsBridge.list())].sort((a, b) => (a.name || '').localeCompare(b.name || '', undefined, { sensitivity: 'base' }));
    for (const l of savedLayouts) {
        if (!l?.layout_uuid) continue;
        out.push({ key: `${LAYOUT_ITEM_FOLD_PREFIX}${l.layout_uuid}`, label: l.name || l.layout_uuid, section: 'layouts' });
    }

    const companies = [...companyList()].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
    for (const c of companies) {
        out.push({ key: `c:${c.id}`, label: c.name, section: 'companies' });
    }

    const activeProjects = (projects.data ?? [])
        .filter((p) => p.id !== null && p.id !== undefined && !p.archived_at)
        .sort((a, b) => (a.name || '').localeCompare(b.name || '', undefined, { sensitivity: 'base' }));
    for (const p of activeProjects) {
        out.push({ key: `${GroupStore.BAND_PROJECT_PREFIX}${p.id}`, label: p.name || t('sidebar.project.unnamed'), section: 'projects' });
    }

    const allGroups = GroupStore.current().groups;
    const forbidden = forbiddenGroupUuids(excludeGroupUuid, allGroups);
    for (const g of allGroups) {
        if (forbidden.has(g.group_uuid)) continue;
        out.push({ key: GroupStore.bandKeyFor(g.group_uuid), label: g.name, section: 'groups' });
    }

    return out;
}

export function groupContainerChoices(excludeGroupUuid?: string): SelectChoice[] {
    const raw = groupContainerOptions(excludeGroupUuid);
    const bySection = new Map<ContainerSection, SelectOption[]>();
    for (const opt of raw) {
        const list = bySection.get(opt.section) ?? [];
        list.push({ value: opt.key ?? '', label: opt.label });
        bySection.set(opt.section, list);
    }
    const order: readonly ContainerSection[] = ['sections', 'layouts', 'companies', 'projects', 'groups'];
    const out: SelectChoice[] = [];
    for (const sec of order) {
        const opts = bySection.get(sec);
        if (opts && opts.length) out.push({ group: t(`sidebar.group.location.${sec}`), options: opts });
    }
    return out;
}
