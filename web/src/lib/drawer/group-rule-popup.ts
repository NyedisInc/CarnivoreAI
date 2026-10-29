import { t } from '../i18n/index.svelte';
import { mountPanel, unmountPanel } from '../mount';
import { drawerEnv } from './env';
import * as GroupStore from './group-store';
import type { GroupRule } from './group-rule';
import { refreshGroups, repaintDrawerRows } from '../sidebar-shell/interaction-globals';
import GroupRulePanel from './GroupRulePanel.svelte';

export const MOUNT_ID = 'group-rule-panel-mount';

let openPopup: HTMLElement | null = null;
let returnFocusTo: HTMLElement | null = null;
let wired = false;

export function close(restoreFocus = false): void {
    unmountPanel(MOUNT_ID);
    if (openPopup && openPopup.parentNode) openPopup.parentNode.removeChild(openPopup);
    openPopup = null;
    const target = returnFocusTo;
    returnFocusTo = null;
    if (restoreFocus && target && target.isConnected) target.focus();
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
    const box = anchor.getBoundingClientRect();
    el.style.top = `${Math.round(box.bottom + 2)}px`;
    document.body.appendChild(el);
    openPopup = el;
    returnFocusTo = anchor instanceof HTMLElement ? anchor : null;
    mountPanel(MOUNT_ID, GroupRulePanel, { groupUuid, save: (rule: GroupRule) => saveRule(groupUuid, rule) });
    const left = Math.min(box.left, window.innerWidth - el.offsetWidth - 8);
    el.style.left = `${Math.max(8, Math.round(left))}px`;
    const bottomGap = window.innerHeight - (box.bottom + 2 + el.offsetHeight) - 8;
    if (bottomGap < 0) el.style.top = `${Math.max(8, Math.round(box.bottom + 2 + bottomGap))}px`;
    wire();
}

function wire(): void {
    if (wired) return;
    document.addEventListener('mousedown', (e) => {
        if (openPopup && !openPopup.contains(e.target as Node)) close();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && openPopup) close(true);
    });
    wired = true;
}
