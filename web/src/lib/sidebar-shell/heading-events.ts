import type { Attachment } from 'svelte/attachments';
import { cascadeBandFold, toggleBandFold } from './heading-fold';
import { watchCascadeHint } from './cascade-hint';
import { renameGroup } from './heading-group-actions';
import { itemMenuState, openItemMenu } from '../item-menu/open.svelte';
import { isMenuKey } from '../zone-shell/key-nav';
import type { ItemMenuType } from '../item-menu/types';
import { groupUuidOf } from '../drawer/group-store';
import { focusHeading, onSectionKeydown, onSectionPointerDown, sectionDragTookClick } from './section-drag';
import { sectionTargetOf } from './section-heading';

const owned = new WeakSet<Element>();

const HEADER_ROW = '.session-sidebar-group__headerrow';

const KEBAB_SELECTOR = '[data-group-menu], [data-project-menu], [data-company-menu]';

const KEBAB_TYPES: readonly (readonly [string, ItemMenuType])[] = [
    ['data-group-menu', 'group'],
    ['data-project-menu', 'project'],
    ['data-company-menu', 'company'],
];

function headingKebab(el: Element | null): { type: ItemMenuType; key: string; el: Element } | null {
    if (!el) return null;
    for (const [attr, type] of KEBAB_TYPES) {
        if (el.hasAttribute(attr)) return { type, key: el.getAttribute(attr) || '', el };
    }
    return null;
}

interface MenuTarget {
    type: ItemMenuType;
    key: string;
    el: Element;
}

function menuTargetOf(row: Element | null): MenuTarget | null {
    if (!row) return null;
    const kebab = headingKebab(row.querySelector(KEBAB_SELECTOR));
    if (kebab) return kebab;
    const section = sectionTargetOf(row);
    return section ? { type: 'section', key: section.key, el: row } : null;
}

function restoreHeadingFocus(key: string): void {
    queueMicrotask(() => {
        if (itemMenuState.open) return;
        const at = document.activeElement;
        if (!at || at === document.body || !at.isConnected || at.closest('.acm-menu')) focusHeading(key);
    });
}

function openMenuFor(target: MenuTarget, at: { x: number; y: number } | null): boolean {
    const opts = target.type === 'section' ? { onClose: () => restoreHeadingFocus(target.key) } : {};
    return openItemMenu(target.type, { key: target.key, anchor: target.el }, target.el, at, opts);
}

export function shellOwnsHeading(target: EventTarget | null): boolean {
    const el = target as Element | null;
    const row = el && typeof el.closest === 'function' ? el.closest(HEADER_ROW) : null;
    return !!row && owned.has(row);
}

function onClick(e: MouseEvent): void {
    const target = e.target as Element | null;
    if (!target || typeof target.closest !== 'function') return;
    if (sectionDragTookClick()) {
        e.preventDefault();
        e.stopPropagation();
        return;
    }
    if (target.closest('.session-sidebar-rename-edit')) {
        e.stopPropagation();
        return;
    }
    const kebab = headingKebab(target.closest(KEBAB_SELECTOR));
    if (kebab) {
        e.preventDefault();
        e.stopPropagation();
        openItemMenu(kebab.type, { key: kebab.key, anchor: kebab.el }, kebab.el);
        return;
    }
    const toggle = target.closest('[data-group-toggle]');
    if (toggle) {
        e.stopPropagation();
        const key = toggle.getAttribute('data-group-toggle') || '';
        if (e.shiftKey) cascadeBandFold(key);
        else toggleBandFold(key);
        return;
    }
}

function onContextMenu(e: MouseEvent): void {
    const target = e.target as Element | null;
    if (e.defaultPrevented || !target || typeof target.closest !== 'function' || target.closest('.session-sidebar-rename-edit')) return;
    const row = target.closest(HEADER_ROW);
    if (!row) return;
    const menu = menuTargetOf(row);
    if (!menu) return;
    const opened = openMenuFor(menu, { x: e.clientX, y: e.clientY });
    if (!opened) return;
    e.preventDefault();
    e.stopPropagation();
}

function onMousedown(e: MouseEvent): void {
    if (e.shiftKey && (e.target as Element | null)?.closest?.('[data-group-toggle]')) e.preventDefault();
}

function openFromKeyboard(e: KeyboardEvent, target: Element | null): boolean {
    if (!target || typeof target.closest !== 'function' || target.closest('.session-sidebar-rename-edit')) return false;
    const row = target.closest(HEADER_ROW);
    const menu = menuTargetOf(row);
    if (!menu || !openMenuFor(menu, null)) return false;
    e.preventDefault();
    e.stopPropagation();
    return true;
}

function onKeydown(e: KeyboardEvent): void {
    const target = e.target as Element | null;
    if (isMenuKey(e) && openFromKeyboard(e, target)) return;
    const header = target && typeof target.closest === 'function' ? target.closest('[data-group-toggle]') : null;
    if (!header) return;
    if (e.key !== 'F2') {
        const row = header.closest('.session-sidebar-group__headerrow');
        if (row) onSectionKeydown(e, row);
        return;
    }
    const uuid = groupUuidOf(header.getAttribute('data-group-toggle') || '');
    if (!uuid) return;
    e.preventDefault();
    e.stopPropagation();
    renameGroup(uuid);
}

function onPointerdown(e: PointerEvent): void {
    onSectionPointerDown(e, e.currentTarget as Element);
}

export function headingEvents(): Attachment<HTMLElement> {
    return (node) => {
        owned.add(node);
        node.addEventListener('click', onClick);
        node.addEventListener('contextmenu', onContextMenu);
        node.addEventListener('keydown', onKeydown);
        node.addEventListener('mousedown', onMousedown);
        node.addEventListener('pointerdown', onPointerdown);
        const unwatch = watchCascadeHint(node);
        return () => {
            unwatch();
            node.removeEventListener('mousedown', onMousedown);
            node.removeEventListener('pointerdown', onPointerdown);
            owned.delete(node);
            node.removeEventListener('click', onClick);
            node.removeEventListener('contextmenu', onContextMenu);
            node.removeEventListener('keydown', onKeydown);
        };
    };
}
