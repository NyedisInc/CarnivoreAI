import type { BarPatch, BarsTogether, WidgetBarsStored, WidgetBarsView } from '../../widget-bars/bar-settings.svelte';
import type { RailEdge } from '../../session-rail/rail-model';

export type BarOp = { kind: 'bar'; edge: RailEdge; patch: BarPatch } | { kind: 'together'; value: BarsTogether | null };

export type ShowChoice = 'both' | 'side' | 'bottom' | 'none';

export const SHOW_CHOICES: readonly ShowChoice[] = ['both', 'side', 'bottom', 'none'];

export const EDGES: readonly RailEdge[] = ['side', 'bottom'];

export function showChoice(view: WidgetBarsView): ShowChoice {
    if (view.side.show && view.bottom.show) return 'both';
    if (view.side.show) return 'side';
    return view.bottom.show ? 'bottom' : 'none';
}

export function showOps(choice: ShowChoice, view: WidgetBarsView): BarOp[] {
    const wanted: Record<RailEdge, boolean> = { side: choice === 'both' || choice === 'side', bottom: choice === 'both' || choice === 'bottom' };
    return EDGES.filter((edge) => view[edge].show !== wanted[edge]).map((edge) => ({ kind: 'bar', edge, patch: { show: wanted[edge] } }));
}

export function undoOps(stored: WidgetBarsStored | null, ops: readonly BarOp[]): BarOp[] {
    return ops.map((op): BarOp => {
        if (op.kind === 'together') return { kind: 'together', value: stored?.together ?? null };
        const prior = stored?.[op.edge] ?? {};
        const patch: Record<string, unknown> = {};
        for (const key of Object.keys(op.patch)) patch[key] = (prior as Record<string, unknown>)[key] ?? null;
        return { kind: 'bar', edge: op.edge, patch: patch as BarPatch };
    });
}
