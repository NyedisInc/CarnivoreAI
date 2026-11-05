import { PeekController, barState, foldedEdge, realClock, type BarVisual, type Clock, type PeekFlags } from '../../widget-bars/bar-state';
import type { WidgetBarsView } from '../../widget-bars/bar-settings.svelte';
import { stripMode } from '../../widget-bars/bar-pin-action';
import { RAIL_EDGES, type RailEdge } from '../../session-rail/rail-model';

export const PANEL_PX: Readonly<Record<RailEdge, { initial: number; min: number; max: number }>> = Object.freeze({
    side: { initial: 320, min: 160, max: 640 },
    bottom: { initial: 200, min: 100, max: 360 },
});

interface EdgeScene {
    flags: PeekFlags;
    openKey: string | null;
    pinnedOn: 0 | 1 | null;
    panelPx: number;
}

const idle = (): PeekFlags => ({ hover: false, focusIn: false, touchPeek: false, retracting: false });
const fresh = (edge: RailEdge): EdgeScene => ({ flags: idle(), openKey: null, pinnedOn: null, panelPx: PANEL_PX[edge].initial });

export class TryScene {
    agent = $state<0 | 1>(0);
    lead = $state<RailEdge | null>(null);
    edges = $state<Record<RailEdge, EdgeScene>>({ side: fresh('side'), bottom: fresh('bottom') });
    readonly #peek: Record<RailEdge, PeekController>;

    constructor(clock: Clock = realClock) {
        this.#peek = Object.fromEntries(RAIL_EDGES.map((edge) => [edge, new PeekController(clock, (flags) => { this.edges[edge].flags = { ...flags }; })])) as Record<RailEdge, PeekController>;
    }

    visual(edge: RailEdge, view: WidgetBarsView, drawn: boolean): BarVisual {
        const at = this.edges[edge];
        return barState({
            show: view[edge].show, drawn, editing: false, folded: foldedEdge(view.together, this.lead, edge), panelShown: at.openKey !== null,
            mode: stripMode(view[edge].mode), ...at.flags,
        });
    }

    enter(edge: RailEdge): void { this.#peek[edge].enter(); }
    leave(edge: RailEdge): void { this.#peek[edge].leave(); }
    focusIn(edge: RailEdge): void { this.#peek[edge].focusIn(); }
    focusOut(edge: RailEdge): void { this.#peek[edge].focusOut(); }

    press(edge: RailEdge, key: string): void {
        const at = this.edges[edge];
        if (at.openKey === key) {
            at.openKey = null;
            at.pinnedOn = null;
            if (this.lead === edge) this.lead = null;
            this.#peek[edge].panelClosed();
            return;
        }
        at.openKey = key;
        at.pinnedOn = null;
        this.lead = edge;
        this.#peek[edge].open();
    }

    togglePin(edge: RailEdge): void {
        const at = this.edges[edge];
        if (at.openKey === null) return;
        at.pinnedOn = at.pinnedOn === null ? this.agent : null;
    }

    resize(edge: RailEdge, px: number): void {
        const { min, max } = PANEL_PX[edge];
        this.edges[edge].panelPx = Math.min(max, Math.max(min, Math.round(px)));
    }

    switchAgent(): void { this.agent = this.agent === 0 ? 1 : 0; }

    otherPin(edge: RailEdge, key: string): 0 | 1 | null {
        const at = this.edges[edge];
        return at.openKey === key && at.pinnedOn !== null && at.pinnedOn !== this.agent ? at.pinnedOn : null;
    }

    destroy(): void { for (const edge of RAIL_EDGES) this.#peek[edge].destroy(); }
}
