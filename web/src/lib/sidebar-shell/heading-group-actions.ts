import { t } from '../i18n/index.svelte';
import { confirmOk } from '../confirm-ok/confirm-ok';
import { isExpanded as isLayoutExpanded } from '../drawer/layouts-model';
import { LAYOUT_ITEM_FOLD_PREFIX } from '../drawer/store-keys';
import { toggleBandFold } from './heading-fold';
import { headingDrawn, openHeadingRename } from './heading-rename.svelte';
import {
    announce, announceFailure, applyGroups, hg, reasonOf, refreshGroups, usableGroups,
    type GroupsBody,
} from './interaction-globals';

const GROUP_KEY_PREFIX = 'g:';

export function renameGroup(groupUuid: string): boolean {
    const G = usableGroups();
    const group = G?.groupByUuid(groupUuid);
    const api = hg().API;
    if (!group || !api) return false;
    const key = GROUP_KEY_PREFIX + groupUuid;
    if (!headingDrawn(key)) {
        announceFailure(t('sidebar.heading.rename.no_editor'));
        return false;
    }
    return openHeadingRename({
        key,
        seed: group.name,
        ariaLabel: t('sidebar.group.rename.aria', { name: group.name }),
        save: (value) => api.renameSessionGroup(groupUuid, value),
        successText: (value) => t('sidebar.group.renamed', { name: value }),
        afterSuccess: (body) => applyGroups(body as GroupsBody),
    });
}

export async function writeGroupOrder(next: string[]): Promise<boolean> {
    const api = hg().API;
    if (!api) return false;
    try {
        applyGroups(await api.reorderSessionGroups(next));
        return true;
    } catch (err) {
        await refreshGroups();
        announceFailure(t('sidebar.group.reorder_failed', { reason: reasonOf(err) }));
        return false;
    }
}

export async function moveGroup(groupUuid: string, delta: number): Promise<boolean> {
    const G = usableGroups();
    if (!G) return false;
    const all = G.current().groups;
    const target = all.find((g) => g.group_uuid === groupUuid);
    if (!target) return false;
    const parent = target.parent_key ?? null;
    const siblings = all.filter((g) => (g.parent_key ?? null) === parent).map((g) => g.group_uuid);
    const at = siblings.indexOf(groupUuid);
    const to = at + (delta < 0 ? -1 : 1);
    if (at === -1 || to < 0 || to >= siblings.length) return false;
    const swapped = siblings.slice();
    swapped[at] = siblings[to] as string;
    swapped[to] = groupUuid;
    let si = 0;
    const next = all.map((g) => ((g.parent_key ?? null) === parent ? swapped[si++] as string : g.group_uuid));
    if (!(await writeGroupOrder(next))) return false;
    announce(t('sidebar.group.moved', { position: to + 1, total: siblings.length }));
    return true;
}

export async function moveGroupToParent(
    groupUuid: string, parentKey: string | null, locationLabel: string,
): Promise<boolean> {
    const G = usableGroups();
    const group = G?.groupByUuid(groupUuid);
    const api = hg().API;
    if (!group || !api?.setSessionGroupParent) return false;
    try {
        const body = await api.setSessionGroupParent(groupUuid, parentKey);
        if (parentKey?.startsWith(LAYOUT_ITEM_FOLD_PREFIX) && !isLayoutExpanded(parentKey.slice(LAYOUT_ITEM_FOLD_PREFIX.length))) {
            toggleBandFold(parentKey);
        }
        applyGroups(body);
        announce(t('sidebar.group.reparented', { name: group.name, location: locationLabel }));
        return true;
    } catch (err) {
        await refreshGroups();
        announceFailure(t('sidebar.group.reparent_failed', { name: group.name, reason: reasonOf(err) }));
        return false;
    }
}

export async function deleteGroup(groupUuid: string): Promise<boolean> {
    const G = usableGroups();
    const group = G?.groupByUuid(groupUuid);
    const { API: api } = hg();
    if (!group || !api) return false;
    const count = group.members.length;
    const ok = await confirmOk({
        title: t('sidebar.group.remove.title'),
        message: t('sidebar.group.remove.message', { name: group.name }),
        details: t('sidebar.group.remove.detail', { count }),
        okLabel: t('sidebar.group.remove.confirm'),
        cancelLabel: t('sidebar.group.remove.cancel'),
        variant: 'danger',
    });
    if (!ok) return false;
    try {
        const body = await api.deleteSessionGroup(groupUuid);
        applyGroups(body);
        announce(t('sidebar.group.removed', { name: group.name, freed: body.freed, count }));
        return true;
    } catch (err) {
        announceFailure(t('sidebar.group.remove_failed', { reason: reasonOf(err) }));
        return false;
    }
}
