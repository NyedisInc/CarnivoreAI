import { t } from '../i18n/index.svelte';
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
    const order = G.current().groups.map((g) => g.group_uuid);
    const at = order.indexOf(groupUuid);
    const to = at + (delta < 0 ? -1 : 1);
    if (at === -1 || to < 0 || to >= order.length) return false;
    const next = order.slice();
    next[at] = order[to] as string;
    next[to] = groupUuid;
    if (!(await writeGroupOrder(next))) return false;
    announce(t('sidebar.group.moved', { position: to + 1, total: order.length }));
    return true;
}

export async function deleteGroup(groupUuid: string): Promise<boolean> {
    const G = usableGroups();
    const group = G?.groupByUuid(groupUuid);
    const { API: api, App: app } = hg();
    if (!group || !api || !app) return false;
    const count = group.members.length;
    const ok = await app.showConfirmModal(
        t('sidebar.group.remove.title'),
        t('sidebar.group.remove.message', { name: group.name }),
        t('sidebar.group.remove.detail', { count }),
        t('sidebar.group.remove.confirm'),
        t('sidebar.group.remove.cancel'),
        'danger',
    );
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
