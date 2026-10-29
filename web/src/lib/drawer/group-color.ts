import { mountPanel, unmountPanel } from '../mount';
import { t } from '../i18n/index.svelte';
import GroupColorPicker from './GroupColorPicker.svelte';
import { drawerEnv } from './env';
import * as GroupStore from './group-store';
import type { LayoutsBridge } from './layouts-model';
import { refreshGroups, repaintDrawerRows } from '../sidebar-shell/interaction-globals';
import {
    ANIMATIONS, COLORS, GRADIENTS, fxHtml, nextStyle, styleAttrs, type RowStyle,
} from './group-color-palette';

export { ANIMATIONS, COLORS, GRADIENTS, nextStyle };

export const PICKER_ID = 'group-color-picker';

interface Subject {
    style: RowStyle;
    label: string;
    titleKey: string;
    failedKey: string;
    write(style: RowStyle): Promise<unknown>;
    onFailed(): Promise<void>;
}

let openPicker: HTMLElement | null = null;
let returnFocusTo: HTMLElement | null = null;
let wired = false;

function groupForKey(key: string): GroupStore.SessionGroup | null {
    if (!GroupStore.isUsable()) return null;
    const uuid = GroupStore.groupUuidOf(key);
    return uuid ? GroupStore.groupByUuid(uuid) : null;
}

export function attrsFor(key: string): string {
    return styleAttrs(groupForKey(key), 'group');
}

export function layoutRowAttrs(layout: RowStyle | null): string {
    return styleAttrs(layout, 'layout');
}

export function groupFxHtml(key: string, text: string): string {
    return fxHtml(attrsFor(key), 'group', text);
}

export function layoutFxHtml(layout: RowStyle | null, text: string): string {
    return fxHtml(layoutRowAttrs(layout), 'layout', text);
}

function subjectFor(kind: string, id: string): Subject | null {
    if (kind === 'group') {
        const group = GroupStore.isUsable() ? GroupStore.groupByUuid(id) : null;
        if (!group) return null;
        return {
            style: { colour: group.colour, gradient: group.gradient || null, animation: group.animation || 'none' },
            label: group.name,
            titleKey: 'sidebar.group.colour.title_named',
            failedKey: 'sidebar.group.colour.failed',
            write: async (style) => {
                const body = await drawerEnv().API.setSessionGroupStyle(id, style);
                GroupStore.apply(body);
                repaintDrawerRows();
            },
            onFailed: async () => { await refreshGroups(); },
        };
    }
    if (kind === 'layout') {
        const layouts = drawerEnv().CloudeWeb?.layouts as LayoutsBridge | undefined;
        const layout = layouts && typeof layouts.get === 'function' ? layouts.get(id) : null;
        if (!layouts || !layout) return null;
        return {
            style: { colour: layout.colour, gradient: layout.gradient || null, animation: layout.animation || 'none' },
            label: layout.name,
            titleKey: 'layout.row.colour.title_named',
            failedKey: 'layout.row.colour.failed',
            write: (style) => layouts.setStyle(id, style),
            onFailed: async () => {},
        };
    }
    return null;
}

export function close(restoreFocus = false): void {
    unmountPanel(PICKER_ID);
    if (openPicker && openPicker.parentNode) openPicker.parentNode.removeChild(openPicker);
    openPicker = null;
    const target = returnFocusTo;
    returnFocusTo = null;
    if (restoreFocus && target && target.isConnected) target.focus();
}

async function commitStyle(kind: string, id: string, style: RowStyle): Promise<boolean> {
    const subject = subjectFor(kind, id);
    if (!subject) return false;
    try {
        await subject.write(style);
        return true;
    } catch (err) {
        await subject.onFailed();
        const reason = err instanceof Error && err.message ? err.message : String(err);
        drawerEnv().WriteFailureNotice?.report?.(t(subject.failedKey, { reason }));
        return false;
    }
}

export function setStyle(groupUuid: string, style: RowStyle): Promise<boolean> {
    return commitStyle('group', groupUuid, style);
}

function paintBody(el: HTMLElement, style: RowStyle, onpick: (field: string, value: string) => void): void {
    const active = document.activeElement as HTMLElement | null;
    const focusedValue = active && el.contains(active) ? active.dataset.styleValue : undefined;
    unmountPanel(PICKER_ID);
    mountPanel(PICKER_ID, GroupColorPicker, { style, onpick });
    const again = focusedValue ? el.querySelector<HTMLElement>(`[data-style-value="${focusedValue}"]`) : null;
    if (again) again.focus();
}

export function openFull(anchor: Element, kind: string, id: string): void {
    close();
    const subject = subjectFor(kind, id);
    if (!subject) return;
    const el = document.createElement('div');
    el.id = PICKER_ID;
    el.className = 'group-colour-picker popup-focus';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', t(subject.titleKey, { name: subject.label }));
    el.dataset.subjectKind = kind;
    el.dataset.subjectId = id;
    const box = anchor.getBoundingClientRect();
    el.style.top = `${Math.round(box.bottom + 2)}px`;
    document.body.appendChild(el);
    openPicker = el;
    returnFocusTo = anchor instanceof HTMLElement ? anchor : null;
    const onpick = async (field: string, value: string): Promise<void> => {
        const current = subjectFor(kind, id);
        if (!current) { close(); return; }
        const ok = await commitStyle(kind, id, nextStyle(current.style, field, value));
        const fresh = subjectFor(kind, id);
        if (ok && fresh && openPicker === el) paintBody(el, fresh.style, onpick);
    };
    paintBody(el, subject.style, onpick);
    const left = Math.min(box.left, window.innerWidth - el.offsetWidth - 8);
    el.style.left = `${Math.max(8, Math.round(left))}px`;
    const first = el.querySelector<HTMLElement>('[aria-checked="true"]') || el.querySelector<HTMLElement>('button');
    if (first) first.focus();
    wire();
}

export function openFor(anchor: Element, kind: string, id: string): void {
    const menu = drawerEnv().SessionSidebarColorMenu as { open?(a: Element, k: string, i: string): boolean } | undefined;
    if (menu && typeof menu.open === 'function' && menu.open(anchor, kind, id)) return;
    openFull(anchor, kind, id);
}

export function open(anchor: Element, groupUuid: string): void {
    openFor(anchor, 'group', groupUuid);
}

function wire(): void {
    if (wired) return;
    document.addEventListener('mousedown', (e) => {
        if (openPicker && !openPicker.contains(e.target as Node)) close();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && openPicker) close(true);
    });
    wired = true;
}
