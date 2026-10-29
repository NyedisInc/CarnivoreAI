import { t } from '../i18n/index.svelte';
import * as GroupStore from '../drawer/group-store';
import { promptText } from './company-actions';
import {
    announce, announceFailure, applyGroups, hg, reasonOf, refreshGroups, repaintDrawerRows, usableGroups,
    type GroupsBody,
} from './interaction-globals';

export async function commitAssignment(name: string, groupUuid: string | null): Promise<boolean> {
    const api = hg().API;
    if (!api) return false;
    GroupStore.setOptimistic(name, groupUuid);
    repaintDrawerRows();
    try {
        applyGroups(await api.assignSessionGroup(name, groupUuid));
    } catch (err) {
        await refreshGroups();
        announceFailure(t('sidebar.group.move_failed', { name, reason: reasonOf(err) }));
        return false;
    }
    const G = usableGroups();
    const label = groupUuid
        ? (G ? GroupStore.labelFor(GroupStore.bandKeyFor(groupUuid)) : t('sidebar.group.pick.some_group'))
        : t('sidebar.group.pick.ungrouped_label');
    announce(t('sidebar.group.move_done', { name, label }));
    return true;
}

export async function createGroupThenAssign(name: string | null): Promise<void> {
    const raw = await promptText({
        title: t('sidebar.group.new.title'),
        label: t('sidebar.group.new.label'),
        placeholder: t('sidebar.group.new.placeholder'),
        confirmLabel: t('sidebar.group.new.create'),
        cancelLabel: t('sidebar.group.new.cancel'),
    });
    if (raw === null) return;
    const api = hg().API;
    try {
        if (!api) throw new Error(t('error.server_unreachable'));
        const body = await api.createSessionGroup(raw);
        applyGroups(body);
        const squeezed = raw.split(/\s+/).filter(Boolean).join(' ');
        const made = (body.groups ?? []).find((g) => g.name === String(raw).trim() || g.name === squeezed);
        if (name && made) await commitAssignment(name, made.group_uuid);
        else announce(t('sidebar.group.created', { name: raw }));
    } catch (err) {
        announceFailure(t('sidebar.group.create_failed', { reason: reasonOf(err) }));
    }
}
