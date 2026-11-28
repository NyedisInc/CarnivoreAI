import { t } from '../i18n/index.svelte';
import * as GroupStore from '../drawer/group-store';
import { isExpanded as isLayoutExpanded } from '../drawer/layouts-model';
import { LAYOUT_ITEM_FOLD_PREFIX } from '../drawer/store-keys';
import { toggleBandFold } from './heading-fold';
import { openModal } from '../modal';
import { groupContainerChoices } from './group-containers';
import { judgeGroupName } from './group-name';
import NewGroupModal, { type NewGroupAnswer } from './NewGroupModal.svelte';
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

export async function createGroupThenAssign(
    name: string | null, onFiled?: () => void, parentKey?: string | null,
): Promise<void> {
    const answer = await openModal<NewGroupAnswer, { initialParent: string; choices: ReturnType<typeof groupContainerChoices> }>(
        NewGroupModal,
        { initialParent: parentKey ?? '', choices: groupContainerChoices() },
    );
    if (answer === null) return;
    const raw = answer.name;
    const scopeParent = answer.parentKey || null;
    const siblings = GroupStore.current().groups.filter((g) => (g.parent_key ?? null) === scopeParent);
    const verdict = judgeGroupName(raw, siblings.map((g) => g.name));
    if (!verdict.ok) {
        announceFailure(t(`sidebar.group.new.refused.${verdict.reason}`));
        return;
    }
    const api = hg().API;
    try {
        if (!api) throw new Error(t('error.server_unreachable'));
        const known = new Set(GroupStore.current().groups.map((g) => g.group_uuid));
        const body = scopeParent
            ? await api.createSessionGroup(verdict.value, scopeParent)
            : await api.createSessionGroup(verdict.value);
        if (scopeParent?.startsWith(LAYOUT_ITEM_FOLD_PREFIX) && !isLayoutExpanded(scopeParent.slice(LAYOUT_ITEM_FOLD_PREFIX.length))) {
            toggleBandFold(scopeParent);
        }
        applyGroups(body);
        const fresh = (body.groups ?? []).filter((g) => !known.has(g.group_uuid));
        const made = fresh.filter((g) => g.name === verdict.value).pop() ?? fresh.pop();
        if (name && made) {
            if (await commitAssignment(name, made.group_uuid)) onFiled?.();
        } else if (name) {
            announceFailure(t('sidebar.group.create_failed', { reason: t('sidebar.group.new.not_found') }));
        } else announce(t('sidebar.group.created', { name: verdict.value }));
    } catch (err) {
        announceFailure(t('sidebar.group.create_failed', { reason: reasonOf(err) }));
    }
}
