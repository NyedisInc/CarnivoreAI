import { t } from '../../i18n/index.svelte';
import * as GroupStore from '../../drawer/group-store';
import { commitAssignment, createGroupThenAssign } from '../../sidebar-shell/group-assign';
import { usableGroups } from '../../sidebar-shell/interaction-globals';
import type { MenuNode } from '../../drawer-tabs/add-component-menu';
import { closing } from '../../widget-menu/model';
import { defineItemMenu } from '../registry';

defineItemMenu('grouppick', {
    build({ name }, env) {
        if (!usableGroups()) return null;
        const currentUuid = GroupStore.groupOf(name);
        const groups = GroupStore.current().groups;
        const nodes: MenuNode[] = groups.map((group) => ({
            id: `group-${group.group_uuid}`,
            label: group.name,
            checked: group.group_uuid === currentUuid,
            run: () => { void commitAssignment(name, group.group_uuid); },
        }));
        nodes.push({ id: 'ungroup', label: t('sidebar.group.pick.other'), checked: currentUuid === null, run: () => { void commitAssignment(name, null); } });
        nodes.push({ id: 'new-group', label: t('sidebar.group.pick.new'), run: () => { void createGroupThenAssign(name); } });
        return { nodes: closing(nodes, env.close), ariaLabel: t('sidebar.group.pick.label', { name }) };
    },
});
