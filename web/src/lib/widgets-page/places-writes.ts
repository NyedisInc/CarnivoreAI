/* the widgets page */
import type { Translate } from '../sessions/types';
import { drawerZone } from '../drawer-zone/zone-store.svelte';
import { isRepeatable, zoneItemKey } from '../drawer-zone/zone-model';
import { placeInRail, railStores } from '../session-rail/rail-store.svelte';
import type { RailEdge } from '../session-rail/rail-model';
import { dashboardLayout } from '../dashboards/board-layout';
import { setDashboardLayout } from '../dashboards/api';
import { widgetBars } from '../widget-bars/bar-settings.svelte';
import { homeLayout } from '../../opscenter/engine/layout.svelte';
import { hideCell, showCell } from '../../opscenter/engine/model';
import type { SlotId } from '../../opscenter/engine/types';
import { boardList, liveBoardId } from './places-state.svelte';
import { editBars } from './bar-run';
import { placeName, type PlaceId } from './places';
import { closeToast, showToast } from './undo-toast';

const EDGE: Readonly<Record<'right' | 'bottom', RailEdge>> = { right: 'side', bottom: 'bottom' };

function where(place: PlaceId, boardId: string | null, t: Translate): string {
    if (place !== 'board') return placeName(place, t);
    return t('widgets.places.board.named', { name: boardList().find((board) => board.id === boardId)?.name ?? '' });
}

function saved(text: string, undo: () => void | Promise<unknown>, t: Translate): void {
    showToast({ kind: 'saved', text, surface: t('widgets.page.title'), undo: { label: t('widgets.page.toast.undo'), run: () => { closeToast(); void Promise.resolve(undo()).then(() => showToast({ kind: 'undone', text: t('widgets.page.toast.undone'), surface: t('widgets.page.title'), ms: 2000 })); } } });
}

function failed(t: Translate): void {
    showToast({ kind: 'failed', text: t('widgets.places.toast.failed'), surface: t('widgets.page.title') });
}

function drawerSnapshot(): () => Promise<void> {
    const items = drawerZone.items.map((item) => ({ ...item }));
    const glance = drawerZone.glanceStored ? drawerZone.glanceStored.map((p) => ({ ...p, options: { ...p.options } })) : null;
    return () => drawerZone.commit(items, glance);
}

async function writeBoard(boardId: string, cellId: string, op: 'show' | 'hide'): Promise<(() => Promise<unknown>) | null> {
    const cell = cellId as SlotId;
    const before = dashboardLayout(boardId);
    if (!before) return null;
    const after = op === 'show' ? showCell(before, cell) : hideCell(before, cell);
    if (after === before) return null;
    if (boardId === liveBoardId()) {
        if (op === 'show') homeLayout.show(cell);
        else homeLayout.hide(cell);
        return async () => void (op === 'show' ? homeLayout.hide(cell) : homeLayout.show(cell));
    }
    await setDashboardLayout(boardId, after);
    return () => setDashboardLayout(boardId, before);
}

export async function addToPlace(widget: string, name: string, place: PlaceId, boardId: string | null, cell: string | null, t: Translate): Promise<boolean> {
    const text = t('widgets.places.toast.added', { widget: name, place: where(place, boardId, t) });
    if (place === 'right' || place === 'bottom') {
        editBars(() => void placeInRail(EDGE[place], widget), text, t);
        return true;
    }
    if (place === 'drawer' || place === 'glance') {
        const restore = drawerSnapshot();
        const did = place === 'drawer' ? drawerZone.add(widget) : drawerZone.addGlance(widget, isRepeatable(widget)) !== null;
        if (did) saved(text, restore, t);
        return did;
    }
    if (boardId === null || cell === null) return false;
    try {
        const restore = await writeBoard(boardId, cell, 'show');
        if (restore) saved(text, restore, t);
        return restore !== null;
    } catch {
        failed(t);
        return false;
    }
}

export async function removeFromPlace(widget: string, name: string, place: PlaceId, key: string | null, boardId: string | null, cell: string | null, t: Translate): Promise<boolean> {
    const text = t('widgets.places.toast.removed', { widget: name, place: where(place, boardId, t) });
    if (place === 'right' || place === 'bottom') {
        const rail = railStores[EDGE[place]];
        const row = rail.items.find((item) => item.widget === widget && (key === null || zoneItemKey(item) === key));
        if (!row) return false;
        editBars(() => void rail.remove(zoneItemKey(row)), text, t);
        return true;
    }
    if (place === 'drawer' || place === 'glance') {
        const restore = drawerSnapshot();
        const id = key ?? (place === 'drawer' ? drawerZone.items.find((item) => item.widget === widget) : drawerZone.glance.find((one) => one.widget === widget)) ;
        const target = typeof id === 'string' ? id : id && 'id' in id ? id.id : id ? zoneItemKey(id) : null;
        if (target === null) return false;
        const did = place === 'drawer' ? drawerZone.remove(target) : drawerZone.removeGlance(target);
        if (did) saved(text, restore, t);
        return did;
    }
    if (boardId === null || cell === null) return false;
    try {
        const restore = await writeBoard(boardId, cell, 'hide');
        if (restore) saved(text, restore, t);
        return restore !== null;
    } catch {
        failed(t);
        return false;
    }
}

function spotFor(sections: readonly (readonly { widget: string }[])[], movingKey: string, to: number, keyOf: (item: never) => string): { section: number; index: number } {
    let left = to;
    for (let section = 0; section < sections.length; section++) {
        const length = (sections[section] as readonly never[]).filter((item) => keyOf(item) !== movingKey).length;
        if (left <= length && (left < length || section === sections.length - 1)) return { section, index: left };
        left -= length;
    }
    return { section: Math.max(0, sections.length - 1), index: 0 };
}

export function moveInPlace(place: Exclude<PlaceId, 'board'>, key: string, to: number, name: string, t: Translate): void {
    const text = t('widgets.places.toast.moved', { widget: name, n: to + 1, place: placeName(place, t) });
    if (place === 'right' || place === 'bottom') {
        const rail = railStores[EDGE[place]];
        const item = rail.items.find((one) => zoneItemKey(one) === key);
        if (!item) return;
        const spot = spotFor(rail.sections, key, to, (one: never) => zoneItemKey(one));
        editBars(() => void rail.place({ ...spot, split: null }, item.widget, item.target, item.instance ?? null), text, t);
        return;
    }
    const restore = drawerSnapshot();
    if (place === 'drawer') drawerZone.move(key, to);
    else drawerZone.moveGlance(key, to);
    saved(text, restore, t);
}

export async function resetBars(t: Translate): Promise<void> {
    const result = await widgetBars.reset();
    if (result === 'failed') failed(t);
    else showToast({ kind: 'saved', text: t('widgets.places.toast.reset'), surface: t('widgets.page.title'), ms: 4000 });
}
