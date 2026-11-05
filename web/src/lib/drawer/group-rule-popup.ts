import { t } from '../i18n/index.svelte';
import { mountPanel, unmountPanel } from '../mount';
import { createAnchoredPopup } from './anchored-popup';
import { drawerEnv } from './env';
import * as GroupStore from './group-store';
import type { GroupRule } from './group-rule';
import { refreshGroups, repaintDrawerRows } from '../sidebar-shell/interaction-globals';
import GroupRulePanel from './GroupRulePanel.svelte';

export const MOUNT_ID = 'group-rule-panel-mount';

const popup = createAnchoredPopup({ onClose: () => unmountPanel(MOUNT_ID) });

export function close(restoreFocus = false): void {
    popup.close(restoreFocus);
}

export async function saveRule(groupUuid: string, rule: GroupRule): Promise<boolean> {
    const env = drawerEnv();
    try {
        const body = await env.API.setSessionGroupRule(groupUuid, rule);
        GroupStore.apply(body);
        repaintDrawerRows();
        return true;
    } catch (err) {
        await refreshGroups();
        const reason = err instanceof Error && err.message ? err.message : String(err);
        env.WriteFailureNotice?.report?.(t('sidebar.group.rule.failed', { reason }));
        return false;
    }
}

export function open(anchor: Element, groupUuid: string): void {
    close();
    const group = GroupStore.isUsable() ? GroupStore.groupByUuid(groupUuid) : null;
    if (!group) return;
    const el = document.createElement('div');
    el.className = 'group-icon-picker popup-focus';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', t('sidebar.group.rule.title_named', { name: group.name }));
    const title = document.createElement('div');
    title.className = 'modal-titlerow group-colour-picker__title';
    title.textContent = t('sidebar.group.rule.title');
    const body = document.createElement('div');
    body.className = 'group-icon-picker__body';
    body.id = MOUNT_ID;
    el.append(title, body);
    popup.open(el, anchor, () => mountPanel(MOUNT_ID, GroupRulePanel, { groupUuid, save: (rule: GroupRule) => saveRule(groupUuid, rule) }));
}
