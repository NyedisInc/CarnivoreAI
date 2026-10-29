import { drawerZone } from '../drawer-zone/zone-store.svelte';
import { zoneItemKey } from '../drawer-zone/zone-model';
import { railStores } from '../session-rail/rail-store.svelte';
import { dashboardLayout } from '../dashboards/board-layout';
import { homeBoards } from '../../opscenter/engine/home-sync.svelte';
import { rowOfCell } from '../../opscenter/engine/model';
import type { SlotId } from '../../opscenter/engine/types';
import type { PlaceId } from './places';

export interface PlaceRow {
    key: string;
    widget: string;
}

export function startPlaceStores(): void {
    railStores.side.start();
    railStores.bottom.start();
    drawerZone.start();
}

export function rowsOf(place: Exclude<PlaceId, 'board'>): PlaceRow[] {
    if (place === 'right') return railStores.side.items.map((item) => ({ key: zoneItemKey(item), widget: item.widget }));
    if (place === 'bottom') return railStores.bottom.items.map((item) => ({ key: zoneItemKey(item), widget: item.widget }));
    if (place === 'drawer') return drawerZone.items.map((item) => ({ key: zoneItemKey(item), widget: item.widget }));
    return drawerZone.glance.map((one) => ({ key: one.id, widget: one.widget }));
}

export function boardList(): { id: string; name: string }[] {
    return homeBoards.list.map((board) => ({ id: board.id, name: board.name }));
}

export function liveBoardId(): string {
    return homeBoards.viewing ?? homeBoards.active;
}

export function boardHolds(boardId: string, cell: string): boolean {
    const layout = dashboardLayout(boardId);
    return layout !== undefined && rowOfCell(layout, cell as SlotId) !== undefined;
}

export function boardsHolding(cell: string | null): { id: string; name: string }[] {
    return cell === null ? [] : boardList().filter((board) => boardHolds(board.id, cell));
}

export function placedIn(widget: string, place: PlaceId, cell: string | null, boardId: string): boolean {
    if (place === 'board') return cell !== null && boardHolds(boardId, cell);
    return rowsOf(place).some((row) => row.widget === widget);
}

export function placedAnywhere(widget: string, cell: string | null): boolean {
    return (['right', 'bottom', 'drawer', 'glance'] as const).some((place) => rowsOf(place).some((row) => row.widget === widget)) || boardsHolding(cell).length > 0;
}
