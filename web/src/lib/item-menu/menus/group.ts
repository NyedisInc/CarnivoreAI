import { t } from '../../i18n/index.svelte';
import { addToNodes } from '../../add-to-menu/host';
import { deleteGroup, moveGroup, renameGroup } from '../../sidebar-shell/heading-group-actions';
import { sleepGroup } from '../../sidebar-shell/heading-project-actions';
import { hg, usableGroups } from '../../sidebar-shell/interaction-globals';
import { entryNodes, spaced } from '../entries';
import { defineItemMenu } from '../registry';

defineItemMenu('group', {
    build({ key: groupUuid, anchor }, env) {
        const G = usableGroups();
        const group = G?.groupByUuid(groupUuid);
        if (!G || !group) return null;
        const order = G.current().groups.map((g) => g.group_uuid);
        const at = order.indexOf(groupUuid);
        const entries = spaced([
            [
                { label: t('sidebar.heading.rename'), icon: 'rename', id: 'rename-group', onPick: () => { renameGroup(groupUuid); } },
                { label: 'add', icon: 'add', id: 'add-members', children: () => addToNodes.forGroup(groupUuid), onPick: () => undefined },
                { label: t('sidebar.group.colour.menu'), icon: 'colour', id: 'colour', onPick: () => hg().SessionSidebarGroupColour?.open(anchor, groupUuid) },
                { label: t('sidebar.group.icon.menu'), icon: 'group-icon', id: 'group-icon', onPick: () => hg().SessionSidebarGroupIcon?.open(anchor, groupUuid) },
            ],
            [{ label: t('sidebar.heading.sleep'), icon: 'sleep', id: 'sleep', onPick: () => { void sleepGroup(groupUuid); } }],
            [
                {
                    label: t('sidebar.group.menu.move_up'), icon: 'move-up', id: 'move-up',
                    ...(at === 0 ? { blocked: t('widgets.menu.already_first') } : {}),
                    onPick: () => { void moveGroup(groupUuid, -1); },
                },
                {
                    label: t('sidebar.group.menu.move_down'), icon: 'move-down', id: 'move-down',
                    ...(at === order.length - 1 ? { blocked: t('widgets.menu.already_last') } : {}),
                    onPick: () => { void moveGroup(groupUuid, 1); },
                },
            ],
            [{
                label: t('sidebar.group.menu.remove', { count: group.members.length }), icon: 'close', id: 'delete-group', danger: true,
                onPick: () => { void deleteGroup(groupUuid); },
            }],
        ]);
        return { nodes: entryNodes(entries, env.glyph, env.close), ariaLabel: t('sidebar.group.menu.label', { name: group.name }) };
    },
});
