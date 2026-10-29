import { announce } from './interaction-globals';
import { commitAssignment } from './group-assign';
import { bandNames, ownsOrder, repaintKeepingFocus, rowEls, visibleNames } from './row-focus';
import { closestTo, drawer, listElement, rg } from './row-globals';
import { movedSentence } from './row-reorder';
import * as Arrangement from '../drawer/arrangement';
import * as G from '../drawer/group-store';
import { isPinned } from '../drawer/store';

export const DRAG_SLOP_PX = 4;

export const TOUCH_EXTRA_SLOP_PX = 10;

interface Drag {
    name: string;
    band: string | null;
    bandMoved: boolean;
    startX: number;
    startY: number;
    claimedClick: boolean;
    active: boolean;
    crossed: boolean | undefined;
    group: string | null | undefined;
    groupChanged: boolean;
    pointerId: number;
    pointerType: string;
}

let drag: Drag | null = null;

let claimedClick = false;

export function slop(pointerType: string): number {
    return pointerType === 'touch' ? DRAG_SLOP_PX + TOUCH_EXTRA_SLOP_PX : DRAG_SLOP_PX;
}

export function isDragging(): boolean {
    return !!drag && drag.active;
}

export function tookClick(): boolean {
    const was = claimedClick;
    claimedClick = false;
    return was;
}

export function bandKeyAt(clientY: number): string | null {
    const list = listElement();
    if (!list) return null;
    let last: Element | null = null;
    for (const g of Array.from(list.querySelectorAll('.session-sidebar-group[data-group]'))) {
        last = g;
        if (clientY < g.getBoundingClientRect().bottom) return g.getAttribute('data-group');
    }
    return last ? last.getAttribute('data-group') : null;
}

function beforeNameAt(rows: HTMLElement[], clientY: number, name: string): string | null {
    for (const el of rows) {
        if (el.dataset.name === name) continue;
        const box = el.getBoundingClientRect();
        if (clientY < box.top + box.height / 2) return el.dataset.name || null;
    }
    return null;
}

export function onRowPointerDown(e: PointerEvent): void {
    claimedClick = false;
    if (drag) return;
    if (typeof e.button === 'number' && e.button !== 0) return;
    const grip = closestTo(e.target, '[data-grip-session]');
    const row = (grip ? grip.closest('.session-sidebar-row') : closestTo(e.target, '.session-sidebar-row')) as HTMLElement | null;
    if (!row || !row.dataset.name) return;
    if (row.dataset.band === 'layouts') return;
    if (!grip) {
        if (closestTo(e.target, 'button, input, textarea, select, a, [contenteditable]')) return;
        if (e.pointerType === 'touch') return;
    } else {
        e.preventDefault();
        e.stopPropagation();
    }
    drag = {
        name: row.dataset.name, band: row.dataset.band || null, bandMoved: false,
        startX: e.clientX, startY: e.clientY, claimedClick: false, active: false,
        crossed: undefined, group: undefined, groupChanged: false,
        pointerId: e.pointerId, pointerType: e.pointerType,
    };
    const handle = grip || row;
    try {
        handle.setPointerCapture?.(e.pointerId);
    } catch {
    }
    document.addEventListener('pointermove', onPointerMove);
    document.addEventListener('pointerup', onPointerUp);
    document.addEventListener('pointercancel', onPointerUp);
}

function reorderInBand(d: Drag, clientY: number): boolean {
    if (!d.band || !ownsOrder(d.band)) return false;
    const inBand = rowEls().filter((el) => el.dataset.band === d.band);
    const names = inBand.map((el) => el.dataset.name || '');
    if (names.indexOf(d.name) === -1) return false;
    if (Arrangement.placeInBand(d.band, d.name, beforeNameAt(inBand, clientY, d.name), names)) {
        d.bandMoved = true;
        repaintKeepingFocus(d.name, d.band);
    }
    return true;
}

function handOff(d: Drag, e: PointerEvent): boolean {
    if (d.pointerType === 'touch') return false;
    const tabDrag = rg().CloudeWeb?.tabDrag;
    const list = listElement();
    if (!list || !tabDrag) return false;
    const box = list.getBoundingClientRect();
    const dx = Math.abs(e.clientX - d.startX);
    const sideways = !d.active && dx >= slop(d.pointerType) && dx > Math.abs(e.clientY - d.startY);
    if (!sideways && e.clientX >= box.left && e.clientX <= box.right) return false;
    const taken = tabDrag.begin({
        name: d.name, pointerId: d.pointerId, pointerType: d.pointerType, clientX: e.clientX, clientY: e.clientY,
    });
    if (!taken) return false;
    d.claimedClick = true;
    onPointerUp();
    return true;
}

function onPointerMove(e: PointerEvent): void {
    const d = drag;
    if (!d) return;
    if (handOff(d, e)) return;
    if (!d.active) {
        if (Math.abs(e.clientY - d.startY) < slop(d.pointerType)) return;
        d.active = true;
        d.claimedClick = true;
        if (e.cancelable) e.preventDefault();
        window.getSelection?.()?.removeAllRanges?.();
        listElement()?.classList.add('session-sidebar-list--dragging');
        drawer()?.setDragging?.(true);
    }
    const overKey = bandKeyAt(e.clientY);
    if (overKey !== null && overKey === d.band && reorderInBand(d, e.clientY)) return;
    if (overKey !== null && !G.isFilingBand(overKey)) return;
    const beforeName = beforeNameAt(rowEls(), e.clientY, d.name);
    const intent = overKey !== null
        ? G.bandIntent(overKey)
        : { pinned: isPinned(d.name), group: undefined };
    if (intent.group !== undefined) {
        const before = G.setOptimistic(d.name, intent.group);
        if (before !== intent.group) d.groupChanged = true;
        d.group = intent.group;
    }
    const result = Arrangement.placeAt(d.name, intent.pinned, beforeName, visibleNames());
    if (!result) {
        if (d.groupChanged) repaintKeepingFocus(d.name);
        return;
    }
    if (result.crossed) d.crossed = result.pinned;
    repaintKeepingFocus(d.name);
}

function onPointerUp(): void {
    const d = drag;
    if (!d) return;
    drag = null;
    document.removeEventListener('pointermove', onPointerMove);
    document.removeEventListener('pointerup', onPointerUp);
    document.removeEventListener('pointercancel', onPointerUp);
    claimedClick = d.claimedClick;
    listElement()?.classList.remove('session-sidebar-list--dragging');
    drawer()?.setDragging?.(false);
    if (!d.active) return;
    const g = rg();
    if (d.bandMoved && !d.groupChanged && d.crossed === undefined && d.band) {
        announce(movedSentence(d.name, bandNames(d.band)));
        return;
    }
    if (d.groupChanged) {
        void commitAssignment(d.name, d.group === undefined ? null : d.group);
        return;
    }
    announce(movedSentence(d.name, visibleNames(), d.crossed));
    if (d.crossed === undefined) void g.SessionSidebarGroupOrder?.commitMemberOrder?.(d.name);
}
