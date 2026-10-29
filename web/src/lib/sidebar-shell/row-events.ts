/* at the gesture */
import type { Attachment } from 'svelte/attachments';
import { activateRow, armAsleepRow, runRowAction, wakeFromArm } from './row-activate';
import { openSessionAutomationsFor, openShare, openSubagents, openTimers, toggleKeepAwake } from './row-controls';
import { onRowPointerDown, tookClick } from './row-drag';
import { cascadeBandFold, toggleBandFold } from './heading-fold';
import { closestTo, drawer, rg } from './row-globals';
import { searchD } from '../drawer/search-d.svelte';
import { onPinClick, onRowKeydown } from './row-reorder';
import { disarmWake } from './wake-arm.svelte';
import { suppressMiddleAutoscroll } from '../confirm-ok/confirm-ok';
import { onRowAuxClick } from './row-middle-click';
import {
    cancelPress, onClickCapture as onMenuClickCapture, onContextMenu as onMenuContextMenu, onMenuKey,
    onPointerDown as onMenuPointerDown, onPointerMove as onMenuPointerMove,
} from './row-menu-gestures';

const owned = new WeakSet<Element>();

const handled = new WeakSet<Element>();

const ROW = '.session-sidebar-row';

export function shellOwnsRow(target: EventTarget | null): boolean {
    const row = closestTo(target, ROW);
    if (!row) return false;
    if (handled.has(row)) return true;
    const band = row.closest('.session-sidebar-group[data-group]');
    return !!band && owned.has(band);
}

function onClick(e: MouseEvent): void {
    const row = closestTo(e.target, ROW);
    if (!row) return;
    handled.add(row);
    const ctrl = drawer();
    if (!ctrl) return;
    if (tookClick()) return;
    if (closestTo(e.target, '.session-sidebar-rename-edit')) {
        e.stopPropagation();
        return;
    }
    const fold = closestTo(e.target, '[data-group-toggle]');
    if (fold) {
        e.stopPropagation();
        const key = fold.getAttribute('data-group-toggle') || '';
        if (e.shiftKey) cascadeBandFold(key);
        else toggleBandFold(key);
        return;
    }
    if (closestTo(e.target, '[data-wake-arm]')) {
        e.stopPropagation();
        if (closestTo(e.target, '[data-wake-arm-go]')) {
            void wakeFromArm(ctrl, row);
        } else if (closestTo(e.target, '[data-wake-arm-cancel]')) {
            disarmWake();
            (row as HTMLElement).focus({ preventScroll: true });
        }
        return;
    }
    const pin = closestTo(e.target, '[data-pin-session]');
    if (pin) {
        onPinClick(e, pin);
        return;
    }
    const browserKey = closestTo(e.target, '[data-browser-row-action]');
    if (browserKey) {
        e.stopPropagation();
        void rg().SessionSidebarBrowsers?.onKeyClick?.(browserKey);
        return;
    }
    const cup = closestTo(e.target, '[data-keep-awake-session]');
    if (cup) {
        e.stopPropagation();
        void toggleKeepAwake(ctrl, cup);
        return;
    }
    const share = closestTo(e.target, '[data-share-session-id]');
    if (share) {
        e.stopPropagation();
        void openShare(ctrl, share);
        return;
    }
    const subagents = closestTo(e.target, '[data-subagents-session-id]');
    if (subagents) {
        e.stopPropagation();
        openSubagents(subagents);
        return;
    }
    const timers = closestTo(e.target, '[data-timers-session-id]');
    if (timers) {
        e.stopPropagation();
        openTimers(timers);
        return;
    }
    const automations = closestTo(e.target, '[data-automations-session-uuid]');
    if (automations) {
        e.stopPropagation();
        openSessionAutomationsFor(automations);
        return;
    }
    const actions = rg().SessionRowActions;
    const action = actions ? closestTo(e.target, `[${actions.ATTR_ACTION}]`) : null;
    if (action) {
        e.stopPropagation();
        void runRowAction(ctrl, action);
        return;
    }
    if (armAsleepRow(row)) return;
    void activateRow(ctrl, row);
}

function onKeydown(e: KeyboardEvent): void {
    const row = closestTo(e.target, ROW) as HTMLElement | null;
    if (!row) return;
    handled.add(row);
    if (onMenuKey(e)) return;
    onRowKeydown(e, row);
}

function onPointerDown(e: PointerEvent): void {
    const row = closestTo(e.target, ROW);
    if (!row) return;
    handled.add(row);
    onMenuPointerDown(e);
    onRowPointerDown(e);
}

export function bandEvents(): Attachment<HTMLElement> {
    return (node) => {
        owned.add(node);
        node.addEventListener('click', onClick);
        node.addEventListener('keydown', onKeydown);
        node.addEventListener('pointerdown', onPointerDown);
        node.addEventListener('mousedown', suppressMiddleAutoscroll);
        node.addEventListener('auxclick', onRowAuxClick);
        node.addEventListener('click', onMenuClickCapture, true);
        node.addEventListener('contextmenu', onMenuContextMenu);
        node.addEventListener('pointermove', onMenuPointerMove);
        node.addEventListener('pointerup', cancelPress);
        node.addEventListener('pointercancel', cancelPress);
        return () => {
            node.removeEventListener('click', onMenuClickCapture, true);
            node.removeEventListener('contextmenu', onMenuContextMenu);
            node.removeEventListener('pointermove', onMenuPointerMove);
            node.removeEventListener('pointerup', cancelPress);
            node.removeEventListener('pointercancel', cancelPress);
            owned.delete(node);
            node.removeEventListener('click', onClick);
            node.removeEventListener('keydown', onKeydown);
            node.removeEventListener('pointerdown', onPointerDown);
            node.removeEventListener('mousedown', suppressMiddleAutoscroll);
            node.removeEventListener('auxclick', onRowAuxClick);
        };
    };
}
