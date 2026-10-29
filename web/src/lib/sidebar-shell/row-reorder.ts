/* rogue agents */
import { t } from '../i18n/index.svelte';
import { announce } from './interaction-globals';
import { activateRow, armAsleepRow } from './row-activate';
import {
    bandNames, ownsOrder, repaintKeepingFocus, rowEls, setFocusRow, visibleNames,
} from './row-focus';
import { dataOf, drawer, rg } from './row-globals';
import { beginRowRename } from './row-rename';
import * as Arrangement from '../drawer/arrangement';

export function movedSentence(name: string, names: string[], crossed?: boolean): string {
    const params = { name, position: names.indexOf(name) + 1, total: names.length };
    if (crossed === undefined) return t('sidebar.row.move.moved', params);
    return t(crossed ? 'sidebar.row.move.pinned' : 'sidebar.row.move.unpinned', params);
}

export function moveRow(name: string, delta: number, band?: string): boolean {
    const edge = delta < 0 ? 'top' : 'bottom';
    if (band && ownsOrder(band)) {
        if (!Arrangement.moveInBand(band, name, delta, bandNames(band))) {
            announce(t(`sidebar.row.move.${edge}_of_group`, { name }));
            return false;
        }
        repaintKeepingFocus(name, band);
        announce(movedSentence(name, bandNames(band)));
        return true;
    }
    const result = Arrangement.move(name, delta, visibleNames());
    if (!result) {
        announce(t(`sidebar.row.move.${edge}_of_list`, { name }));
        return false;
    }
    repaintKeepingFocus(name);
    announce(movedSentence(name, visibleNames(), result.crossed ? result.pinned : undefined));
    if (!result.crossed) void rg().SessionSidebarGroupOrder?.commitMemberOrder?.(name);
    return true;
}

export function togglePinRow(name: string): boolean {
    const now = Arrangement.togglePin(name, visibleNames());
    repaintKeepingFocus(name);
    announce(t(now ? 'sidebar.row.pin.pinned' : 'sidebar.row.pin.unpinned', { name }));
    return now;
}

const SHIFT_CLOSE_KEYS: ReadonlySet<string> = new Set(['Enter', ' ', 'Delete']);

export function shiftCloseRow(e: KeyboardEvent, row: HTMLElement): boolean {
    if (!e.shiftKey || !SHIFT_CLOSE_KEYS.has(e.key) || row.dataset.shiftClose !== '1') return false;
    const closeKey = row.querySelector('[data-browser-row-action="close"]');
    if (!closeKey) return false;
    e.preventDefault();
    void rg().SessionSidebarBrowsers?.onKeyClick?.(closeKey);
    return true;
}

export function onRowKeydown(e: KeyboardEvent, row: HTMLElement): void {
    const name = row.dataset.name;
    if (!name || e.target !== row) return;
    if (e.key === 'F2') {
        e.preventDefault();
        beginRowRename(row);
        return;
    }
    if (shiftCloseRow(e, row)) return;
    const rows = rowEls();
    const idx = rows.indexOf(row);
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault();
        const step = e.key === 'ArrowDown' ? 1 : -1;
        if (e.altKey) {
            moveRow(name, step, row.dataset.band);
            return;
        }
        const next = rows[idx + step];
        if (next) setFocusRow(next.dataset.name || null, next.dataset.band, true);
        return;
    }
    if (e.key === 'Home' || e.key === 'End') {
        e.preventDefault();
        const target = e.key === 'Home' ? rows[0] : rows[rows.length - 1];
        if (target) setFocusRow(target.dataset.name || null, target.dataset.band, true);
        return;
    }
    if (e.key === 'p' || e.key === 'P') {
        e.preventDefault();
        togglePinRow(name);
        return;
    }
    if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        const ctrl = drawer();
        if (!ctrl) return;
        if (!armAsleepRow(row)) void activateRow(ctrl, row);
    }
}

export function onPinClick(e: MouseEvent, btn: Element): void {
    e.stopPropagation();
    e.preventDefault();
    togglePinRow(btn.getAttribute('data-pin-session') || dataOf(btn, 'pinSession'));
}
