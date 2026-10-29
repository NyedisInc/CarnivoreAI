/* the widgets page */
import type { ZoneItem } from '../drawer-zone/zone-model';
import { RAIL_EDGES, type RailEdge } from '../session-rail/rail-model';
import type { RailLayout } from '../session-rail/rail-sections';

export interface BarAction {
    kind: 'add' | 'move' | 'take_out';
    edge: RailEdge;
}

export type BarStatus = { kind: 'none' } | { kind: 'in'; edge: RailEdge } | { kind: 'many'; count: number };

export type RailSnap = Record<RailEdge, RailLayout | null>;

function other(edge: RailEdge): RailEdge {
    return edge === 'side' ? 'bottom' : 'side';
}

export function copiesIn(widget: string, items: readonly ZoneItem[]): number {
    return items.filter((item) => item.widget === widget).length;
}

export function barActionsFor(widget: string, side: readonly ZoneItem[], bottom: readonly ZoneItem[]): { status: BarStatus; actions: BarAction[] } {
    const count = { side: copiesIn(widget, side), bottom: copiesIn(widget, bottom) };
    const total = count.side + count.bottom;
    if (total === 0) {
        return { status: { kind: 'none' }, actions: RAIL_EDGES.map((edge) => ({ kind: 'add', edge }) as BarAction) };
    }
    if (total > 1) return { status: { kind: 'many', count: total }, actions: [] };
    const edge: RailEdge = count.side === 1 ? 'side' : 'bottom';
    return {
        status: { kind: 'in', edge },
        actions: [
            { kind: 'move', edge: other(edge) },
            { kind: 'take_out', edge },
        ],
    };
}

export function writtenRails(before: RailSnap, after: RailSnap): RailEdge[] {
    return RAIL_EDGES.filter((edge) => JSON.stringify(before[edge]) !== JSON.stringify(after[edge]));
}

export function restorePlan(written: readonly RailEdge[], before: RailSnap, after: RailSnap): RailEdge[] {
    const size = (layout: RailLayout | null): number => (layout ? layout.sections.reduce((sum, section) => sum + section.length, 0) : -1);
    const gained = (edge: RailEdge): number => size(after[edge]) - size(before[edge]);
    return [...written].sort((a, b) => gained(b) - gained(a));
}
