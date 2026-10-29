import { t } from '../i18n/index.svelte';
import { mountIconPicker, unmountIconPicker } from '../icon-picker/icon-picker-host';
import { drawerEnv } from './env';
import * as GroupStore from './group-store';
import { refreshGroups, repaintDrawerRows } from '../sidebar-shell/interaction-globals';
import { COLORS } from './group-color-palette';

export const MOUNT_ID = 'group-icon-picker-mount';

const MARK_SIZE = 12;

let openPopup: HTMLElement | null = null;
let returnFocusTo: HTMLElement | null = null;
let wired = false;

function groupFor(groupUuid: string | null): GroupStore.SessionGroup | null {
    return GroupStore.isUsable() && groupUuid ? GroupStore.groupByUuid(groupUuid) : null;
}

export function iconOf(groupUuid: string | null): string | null {
    const group = groupFor(groupUuid);
    return group && typeof group.icon === 'string' && group.icon ? group.icon : null;
}

export function markHtml(iconId: string | null | undefined): string {
    if (!iconId) return '';
    const glyphs = drawerEnv().CloudeGlyphs as { iconSvg?(id: string, size: number): string } | undefined;
    const svg = glyphs && typeof glyphs.iconSvg === 'function' ? glyphs.iconSvg(iconId, MARK_SIZE) : '';
    return svg
        ? `<span class="session-sidebar-group__icon" data-group-icon="${iconId.replace(/[^a-z0-9-]/g, '')}" aria-hidden="true">${svg}</span>`
        : '';
}

export function headingMark(groupUuid: string | null): string {
    return groupUuid ? markHtml(iconOf(groupUuid)) : '';
}

export function close(restoreFocus = false): void {
    unmountIconPicker(MOUNT_ID);
    if (openPopup && openPopup.parentNode) openPopup.parentNode.removeChild(openPopup);
    openPopup = null;
    const target = returnFocusTo;
    returnFocusTo = null;
    if (restoreFocus && target && target.isConnected) target.focus();
}

export async function setIcon(groupUuid: string, iconId: string | null): Promise<boolean> {
    const env = drawerEnv();
    try {
        const body = await env.API.setSessionGroupIcon(groupUuid, iconId);
        GroupStore.apply(body);
        repaintDrawerRows();
        return true;
    } catch (err) {
        await refreshGroups();
        const reason = err instanceof Error && err.message ? err.message : String(err);
        env.WriteFailureNotice?.report?.(t('sidebar.group.icon.failed', { reason }));
        return false;
    }
}

function buildPopup(group: GroupStore.SessionGroup): HTMLElement {
    const el = document.createElement('div');
    el.className = 'group-icon-picker popup-focus';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', t('sidebar.group.icon.title_named', { name: group.name }));
    el.dataset.groupUuid = group.group_uuid;
    const title = document.createElement('div');
    title.className = 'modal-titlerow group-colour-picker__title';
    title.textContent = t('sidebar.group.icon.title');
    const body = document.createElement('div');
    body.className = 'group-icon-picker__body';
    body.id = MOUNT_ID;
    if (group.colour && (COLORS as readonly string[]).includes(group.colour)) {
        body.style.setProperty('--icon-hue', `var(--drawer-hue-${group.colour})`);
    }
    el.append(title, body);
    return el;
}

export function open(anchor: Element, groupUuid: string): void {
    close();
    const group = groupFor(groupUuid);
    if (!group) return;
    const el = buildPopup(group);
    const box = anchor.getBoundingClientRect();
    el.style.top = `${Math.round(box.bottom + 2)}px`;
    document.body.appendChild(el);
    openPopup = el;
    returnFocusTo = anchor instanceof HTMLElement ? anchor : null;
    mountIconPicker(MOUNT_ID, {
        value: iconOf(groupUuid),
        onChange: (id) => { void setIcon(groupUuid, id); queueMicrotask(() => close(true)); },
        onCancel: () => close(true),
        autofocus: true,
    });
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
