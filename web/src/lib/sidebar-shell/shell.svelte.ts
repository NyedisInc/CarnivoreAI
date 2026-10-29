import { flushSync } from 'svelte';
import { mountPanel, panelInstance, unmountPanel } from '../mount';
import SessionListWidget from '../session-list/SessionListWidget.svelte';
import { shellOwnsHeading } from './heading-events';
import { isHeadingEditing, reconcileHeadingRename } from './heading-rename.svelte';
import { legacyDrawer } from './legacy';
import { buildListPlan, type ListPlan, type PaintInput } from './plan';
import { paintSelection } from './row-activate';
import { isDragging as rowDragging } from './row-drag';
import { togglePinRow } from './row-reorder';
import { isDragging as sectionDragging } from './section-drag';
import { shellOwnsRow } from './row-events';
import { beginRowRename } from './row-rename';

export const SHELL_ATTR = 'data-list-shell';

export class ShellView {
    plan = $state.raw<ListPlan | null>(null);
}

const view = new ShellView();

let mountedOn: Element | null = null;

function release(): void {
    if (!mountedOn) return;
    const el = mountedOn;
    mountedOn = null;
    if (el.id) unmountPanel(el.id);
    el.removeAttribute(SHELL_ATTR);
}

function paint(listEl: Element, input: PaintInput): boolean {
    if (!listEl || !listEl.id) {
        release();
        return false;
    }
    const plan = buildListPlan(legacyDrawer(), input);
    if (!plan) {
        release();
        return false;
    }
    view.plan = plan;
    if (mountedOn !== listEl || !panelInstance(listEl.id)) {
        release();
        listEl.replaceChildren();
        mountPanel(listEl.id, SessionListWidget, { view });
        if (!panelInstance(listEl.id)) return false;
        mountedOn = listEl;
    }
    flushSync();
    listEl.setAttribute(SHELL_ATTR, 'svelte');
    reconcileHeadingRename(listEl);
    return true;
}

interface RepaintGlobals {
    SessionSidebar?: { repaint?(): void };
}

export function repaintDrawer(): boolean {
    const ctrl = (globalThis as unknown as RepaintGlobals).SessionSidebar;
    if (!ctrl || typeof ctrl.repaint !== 'function') return false;
    ctrl.repaint();
    return true;
}

function drew(listEl: Element | null): boolean {
    return !!listEl && listEl === mountedOn && listEl.getAttribute(SHELL_ATTR) === 'svelte';
}

function owns(target: EventTarget | null): boolean {
    return shellOwnsHeading(target) || shellOwnsRow(target);
}

export const sidebarShell = {
    paint,
    repaint: repaintDrawer,
    owns,
    drew,
    paintSelection,
    isDragging: (): boolean => rowDragging() || sectionDragging(),
    isEditing: isHeadingEditing,
    beginRowRename,
    togglePinRow,
};
